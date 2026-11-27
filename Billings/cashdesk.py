"""
Outpatient cash desk: the single place where money is taken, held on deposit, or paid back.

Rules
- A bill line (Invoice) is paid in instalments: `amount_paid` grows until it reaches `price`,
  and only then is the line `completed=1`, which is what releases the drug / test / service.
- `Invoice.price` is already the line total (rate x qty, after discount). Never multiply again.
- The bill total is always worked out here from the database, never taken from the browser.
- Two kinds of deposit ("wallets"):
    own    = the patient's own deposit: Deposit rows of the patient with no family;
    family = the family folder's deposit: Deposit rows with family set. Any current member's bill
             can be paid from it; the row's patient is the member who paid in or was billed.
  A balance is the sum of the rows (same rule as the old pages): money in is a positive row, using
  it on a bill is a negative 'Withdrawal' row, paying it back is a negative 'Refund' row.
  The cashier chooses which deposit pays. Nothing is ever edited or deleted.
- Every payment carries a one-time `request_id`; a repeated click returns the first result
  instead of recording the same instalment twice.
- Inpatient money is separate (IPD/billing_services.py, the admission account).
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum

from .models import Deposit, Invoice, Receipt, Refund, TransactionUpdate
from .numbering import next_deposit_slip_number, next_receipt_number

PAYMENT_METHODS = ['Cash', 'POS', 'Transfer', 'Cheque', 'Bank Deposit', 'Others']
REFERENCE_METHODS = {'POS', 'Transfer', 'Cheque', 'Bank Deposit'}


class CashDeskError(Exception):
    def __init__(self, message, code='invalid', status=400, **extra):
        super().__init__(message)
        self.message, self.code, self.status, self.extra = message, code, status, extra


# --------------------------------------------------------------------------- helpers
def naira(value, field='Amount', allow_zero=True):
    """Parse a whole-naira amount typed at the desk ('25,000', 25000, '25000.00')."""
    if value in (None, ''):
        return 0
    try:
        d = Decimal(str(value).replace(',', '').replace('₦', '').strip())
    except (InvalidOperation, ValueError):
        raise CashDeskError(f'{field} must be a number.', 'amount')
    if d != d.to_integral_value():
        raise CashDeskError(f'{field} must be in whole naira (no kobo).', 'amount')
    d = int(d)
    if d < 0 or (d == 0 and not allow_zero):
        raise CashDeskError(f'{field} must be more than zero.', 'amount')
    if d > 100_000_000:
        raise CashDeskError(f'{field} looks too large. Check the figure.', 'amount')
    return d


def _method(value):
    m = str(value or 'Cash').strip()
    for opt in PAYMENT_METHODS:
        if m.lower() == opt.lower():
            return opt
    raise CashDeskError(f'Choose a payment method: {", ".join(PAYMENT_METHODS)}.', 'method')


def _reference(method, value):
    ref = str(value or '').strip()
    if method in REFERENCE_METHODS and not ref:
        raise CashDeskError(f'Enter the {method} reference (POS RRN, transfer reference or cheque number).', 'reference')
    if len(ref) > 60:
        raise CashDeskError('The reference is too long (60 characters at most).', 'reference')
    return ref


def _request_id(value):
    rid = str(value or '').strip()
    return rid[:64] or None


def _lock_patient(patient):
    """One cash-desk action per patient at a time (deposit balance and bills stay consistent)."""
    from patients.models import PatientProfile
    return PatientProfile.objects.select_for_update().get(pk=patient.pk)


WALLETS = ('own', 'family')
DEPOSIT_RECEIPT_TYPES = {'own': 'Deposit', 'family': 'Family Deposit'}


def family_of(patient):
    """The family folder the patient currently belongs to, or None."""
    from patients.models import FamilyMember
    m = FamilyMember.objects.filter(patient=patient).select_related('family').first()
    return m.family if m else None


def _lock_family(family):
    from patients.models import FamilyFolder
    return FamilyFolder.objects.select_for_update().get(pk=family.pk)


def deposit_balance(patient):
    """The patient's OWN deposit (not the family's)."""
    return int(Deposit.objects.filter(patient=patient, family__isnull=True).aggregate(s=Sum('amount'))['s'] or 0)


def family_balance(family):
    return int(Deposit.objects.filter(family=family).aggregate(s=Sum('amount'))['s'] or 0) if family else 0


def _wallet(value):
    w = str(value or 'own').strip().lower()
    if w in ('individual', 'personal', 'patient'):
        w = 'own'
    if w not in WALLETS:
        raise CashDeskError("Choose the patient's own deposit or the family deposit.", 'wallet')
    return w


def _family_for_wallet(patient):
    fam = family_of(patient)
    if not fam:
        raise CashDeskError('This patient is not in a family folder, so there is no family deposit.', 'no_family')
    return fam


def _balance_for(wallet, patient, family):
    return family_balance(family) if wallet == 'family' else deposit_balance(patient)


def outstanding_lines(patient):
    """Unpaid or part-paid OPD bill lines (cash invoices, not HMO claims)."""
    return [ln for ln in Invoice.objects.filter(patient=patient, completed=0)
            .exclude(invoice_number__startswith='CLM-').order_by('created_date', 'id') if ln.balance > 0]


def account_summary(patient):
    from django.db.models import Q
    lines = outstanding_lines(patient)
    fam = family_of(patient)
    rows = Deposit.objects.filter(Q(patient=patient, family__isnull=True) | (Q(family=fam) if fam else Q(pk__in=[])))
    recent = rows.select_related('staff', 'patient').order_by('-created_date', '-id')[:20]
    family = None
    if fam:
        members = [m.patient for m in fam.members.select_related('patient').all()]
        family = {
            'id': fam.id, 'name': fam.family_name, 'family_number': fam.family_number,
            'balance': family_balance(fam),
            'members': [{'id': p.id, 'name': f'{p.surname} {p.first_name}'.strip(), 'hospital_number': p.hospital_number}
                        for p in members],
        }
    return {
        'patient_id': patient.pk,
        'deposit_balance': deposit_balance(patient),
        'family': family,
        'outstanding_total': sum(ln.balance for ln in lines),
        'part_paid_total': sum(int(ln.amount_paid or 0) for ln in lines),
        'outstanding': [{
            'id': ln.id, 'invoice_number': ln.invoice_number, 'product': ln.product,
            'price': int(ln.price or 0), 'amount_paid': int(ln.amount_paid or 0), 'balance': ln.balance,
            'created_date': ln.created_date.isoformat() if ln.created_date else None,
        } for ln in lines],
        'deposit_history': [{
            'id': d.id, 'amount': int(d.amount or 0), 'kind': d.payment_type, 'reference': d.reference,
            'wallet': 'family' if d.family_id else 'own',
            'member': f'{d.patient.surname} {d.patient.first_name}'.strip() if d.patient_id else '',
            'slip_number': d.slip_number, 'note': d.note,
            'staff': (getattr(d.staff, 'fullname', '') or getattr(d.staff, 'username', '')) if d.staff else '',
            'created_date': d.created_date.isoformat() if d.created_date else None,
        } for d in recent],
    }


def _bump_receipt_count(patient):
    try:
        tu, _ = TransactionUpdate.objects.get_or_create(patient=patient, completed=0)
        tu.receipt_given = (tu.receipt_given or 0) + 1
        tu.save(update_fields=['receipt_given'])
    except Exception:
        pass


# --------------------------------------------------------------------------- deposits
def record_deposit(patient, *, by, amount, method='Cash', reference='', note='', request_id=None, wallet='own'):
    """Money in. wallet='own' (the patient's deposit) or 'family' (their family folder's)."""
    amount = naira(amount, 'Deposit amount', allow_zero=False)
    method = _method(method)
    reference = _reference(method, reference)
    rid = _request_id(request_id)
    wallet = _wallet(wallet)
    with transaction.atomic():
        patient = _lock_patient(patient)
        family = _lock_family(_family_for_wallet(patient)) if wallet == 'family' else None
        if rid:
            dup = Deposit.objects.filter(patient=patient, request_id=rid).first()
            if dup:
                return dup, _balance_for('family' if dup.family_id else 'own', patient, dup.family)
        dep = Deposit.objects.create(
            patient=patient, family=family, amount=amount, payment_type=method, reference=reference,
            note=str(note or '').strip()[:300], slip_number=next_deposit_slip_number(),
            request_id=rid, staff=by)
        return dep, _balance_for(wallet, patient, family)


def refund_deposit(patient, *, by, amount, method='Cash', reason='', reference='', wallet='own'):
    amount = naira(amount, 'Refund amount', allow_zero=False)
    method = _method(method)
    wallet = _wallet(wallet)
    reason = str(reason or '').strip()
    if not reason:
        raise CashDeskError('Say why the deposit is being refunded.', 'reason_required')
    with transaction.atomic():
        patient = _lock_patient(patient)
        family = _lock_family(_family_for_wallet(patient)) if wallet == 'family' else None
        bal = _balance_for(wallet, patient, family)
        label = 'the family deposit' if family else 'deposit'
        if amount > bal:
            raise CashDeskError(f'Only ₦{bal:,} is on {label}; you cannot refund ₦{amount:,}.', 'over_refund')
        refund = Refund.objects.create(patient=patient, amount=amount, payment_type=method[:12],
                                       payment_to='Family' if family else 'Patient', reason=reason[:300], staff=by)
        Deposit.objects.create(patient=patient, family=family, amount=-amount, payment_type='Refund',
                               reference=str(reference or '').strip()[:60],
                               note=f'Refund #{refund.id}: {reason}'[:300], staff=by)
        return refund, _balance_for(wallet, patient, family)


# --------------------------------------------------------------------------- paying bills
def settle_bill(lines_qs, *, by, amount_received=0, method='Cash', use_deposit=False, deposit_source=None,
                keep_change_as_deposit=False, reference='', remarks='', request_id=None):
    """
    Take a payment (full or part) against the given bill lines.

    `lines_qs` is an Invoice queryset naming the bill (one invoice number or a group of them).
    Money is applied to the unpaid lines oldest first; a line is released only when fully paid.
    Returns a dict describing what happened (receipts, balance left, change).
    """
    cash = naira(amount_received, 'Amount received')
    method = _method(method)
    rid = _request_id(request_id)
    # Which deposit pays (if any): 'own', 'family' or None. `use_deposit=True` alone means 'own'.
    source = str(deposit_source or '').strip().lower() or ('own' if use_deposit else '')
    source = None if source in ('', 'none', 'no', 'false', '0') else _wallet(source)

    with transaction.atomic():
        lines = list(lines_qs.select_for_update(of=('self',)).select_related('patient', 'category')
                     .order_by('created_date', 'id'))
        if not lines:
            raise CashDeskError('Invoice not found.', 'not_found', 404)
        patients = {ln.patient_id for ln in lines}
        if len(patients) > 1:
            raise CashDeskError('These invoices belong to different patients; settle each patient separately.')
        patient = _lock_patient(lines[0].patient)
        inv_num = lines[0].invoice_number or f'INV-{lines[0].id}'

        if rid:   # repeated click / retried request: return the first result
            first = list(Receipt.objects.filter(patient=patient, request_id=rid).order_by('id'))
            if first:
                return _result(patient, lines_qs, inv_num, first, repeated=True)

        pending = [ln for ln in lines if ln.balance > 0]
        due = sum(ln.balance for ln in pending)
        if not pending:
            last = Receipt.objects.filter(patient=patient, invoice_number=inv_num).order_by('-id').first()
            raise CashDeskError(f'Invoice #{inv_num} has nothing left to pay.', 'already_settled', 409,
                                receipt_number=last.receipt_number if last else None)

        reference = _reference(method, reference) if cash > 0 else str(reference or '').strip()[:60]
        family = _lock_family(_family_for_wallet(patient)) if source == 'family' else None
        on_deposit = _balance_for(source, patient, family) if source else 0
        from_deposit = min(max(on_deposit, 0), due)
        cash_applied = min(cash, due - from_deposit)
        change = cash - cash_applied
        applied = from_deposit + cash_applied
        if applied <= 0:
            raise CashDeskError('Enter the amount received (or use the deposit on account).', 'amount')

        # Apply the money to the lines, oldest first.
        left, fully_paid, part_paid = applied, [], []
        for ln in pending:
            if left <= 0:
                break
            take = min(left, ln.balance)
            ln.amount_paid = int(ln.amount_paid or 0) + take
            left -= take
            if ln.amount_paid >= int(ln.price or 0):
                ln.completed = 1
                ln.payment_option = (method if cash_applied else DEPOSIT_RECEIPT_TYPES.get(source, 'Deposit'))[:20]
                fully_paid.append(ln)
            else:
                part_paid.append(ln)
            ln.save(update_fields=['amount_paid', 'completed', 'payment_option'])
        balance_left = due - applied

        note = str(remarks or '').strip()
        status_txt = ('Paid in full' if balance_left == 0
                      else f'Part payment; ₦{balance_left:,} still owed on this bill')
        receipts = []
        category = lines[0].category or getattr(patient, 'category', None)
        if cash_applied > 0:
            receipts.append(Receipt.objects.create(
                patient=patient, invoice_number=inv_num, receipt_number=next_receipt_number(),
                remarks=' · '.join(x for x in [note, status_txt, f'Ref: {reference}' if reference else ''] if x),
                total_price=cash_applied, category=category, payment_type=method, staff=by, request_id=rid))
        if from_deposit > 0:
            where = f'family deposit ({family.family_name})' if family else 'own deposit'
            receipts.append(Receipt.objects.create(
                patient=patient, invoice_number=inv_num, receipt_number=next_receipt_number(),
                remarks=' · '.join(x for x in [note, status_txt, f'Paid from {where}'] if x),
                total_price=from_deposit, category=category, payment_type=DEPOSIT_RECEIPT_TYPES[source],
                staff=by, request_id=rid))
            Deposit.objects.create(patient=patient, family=family, amount=-from_deposit, payment_type='Withdrawal',
                                   note=f'Used on bill {inv_num} ({receipts[-1].receipt_number})'[:300], staff=by)
        if change > 0 and keep_change_as_deposit:
            Deposit.objects.create(patient=patient, amount=change, payment_type=method, reference=reference,
                                   slip_number=next_deposit_slip_number(),
                                   note=f'Change kept on deposit from bill {inv_num}'[:300], staff=by)
        _bump_receipt_count(patient)

        # Care packages start once their bill line is paid in full.
        pkg_ids = {ln.original_source_id for ln in fully_paid
                   if ln.original_source_model == 'Packages' and ln.original_source_id}
        transaction.on_commit(lambda: _dispatch_packages(pkg_ids, patient, by))

        out = _result(patient, lines_qs, inv_num, receipts)
        out.update({
            'cash_applied': cash_applied, 'from_deposit': from_deposit,
            'change_due': 0 if keep_change_as_deposit else change,
            'kept_on_deposit': change if keep_change_as_deposit else 0,
            'items_paid_in_full': len(fully_paid), 'items_part_paid': len(part_paid),
            'deposit_source': source,
            'family_deposit_balance': family_balance(family) if family else None,
        })
        return out


def _result(patient, lines_qs, inv_num, receipts, repeated=False):
    lines = list(lines_qs.all())
    balance_left = sum(ln.balance for ln in lines)
    paid_now = sum(int(r.total_price or 0) for r in receipts)
    return {
        'status': 'success', 'repeated': repeated,
        'invoice_number': inv_num,
        'receipt_number': receipts[0].receipt_number if receipts else None,
        'receipts': [{'receipt_number': r.receipt_number, 'amount': int(r.total_price or 0),
                      'payment_type': r.payment_type} for r in receipts],
        'paid_now': paid_now, 'total_amount': float(paid_now),
        'balance_left': balance_left, 'fully_paid': balance_left == 0,
        'deposit_balance': deposit_balance(patient),
        'patient_name': f'{patient.surname} {patient.first_name}',
        'hospital_number': patient.hospital_number or '',
        'sponsor': patient.sponsor.name if getattr(patient, 'sponsor', None) else 'Self-Pay / Cash',
        'change_due': 0,
    }


def _dispatch_packages(pkg_ids, patient, by):
    if not pkg_ids:
        return
    try:
        from api.views import dispatch_care_package_items
    except Exception:
        return
    for p_id in pkg_ids:
        try:
            dispatch_care_package_items(package_id=p_id, patient=patient, user=by)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Care package %s dispatch failed after payment', p_id)
