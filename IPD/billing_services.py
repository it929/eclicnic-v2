"""
Inpatient billing: one running account per admission.

    charges  - bed-days (posted automatically, midnight census), drugs issued from the ward pharmacy,
               services from the price list, and manual charges (administrators only)
    payments - deposits / payments / refunds; each one is mirrored to Billings.Receipt (or Refund)
    bills    - interim bills (statements) any time; one active final bill once discharge is ordered
    clearance- the ward cannot release the patient (complete_discharge) until the bill is cleared:
               paid in full, or released on credit by an administrator with a reason

Pricing
  * Every price comes from the server: api/pricing.quote for drugs and services, WardTariff for
    bed-days (sponsor + plan -> plan -> sponsor -> General row -> Ward.price). Nothing is priced
    from the client, nothing is priced N0 by default: an item with no price is refused.
  * Sponsor and plan are the ones copied onto the admission at admit time.
  * A line is billed to the sponsor (claim) when the sponsor is an HMO and the price came from its
    plan / sponsor list; otherwise the patient pays. Accounts can switch the payer of a line.

HMO approval
  * Every claim line starts "pending". The Billings Unit records the HMO's PA (pre-authorization) code
    to approve it (approve_charges, one code for one or many lines), or declines it when the plan does
    not cover it (decline_charge): the line is re-priced at the General price and the patient pays.
  * A PA code can be kept on the admission; sponsor-billed bed-days are then approved with it as they post.
  * The final bill is refused while any claim line is still pending.

Integrity
  * Nothing is deleted. A wrong charge or payment is reversed with a reason and stays visible.
    Reversing a drug charge returns the pieces to the store it came from.
  * One bed charge per day (DB constraint). While a final bill is active the account is frozen
    (no new charges); cancel the final bill to reopen it.
  * When the patient leaves (complete_discharge) the account is posted to Billings.Invoice
    (CLM-... for the sponsor's share, INV-... for the patient's) so claims and reports see the stay.
"""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    AdmissionBill, AdmissionCharge, AdmissionEvent, AdmissionPayment, AdmissionTable, BedAllocation,
    PAYMENT_METHODS, WardTariff,
)
from .services import AdmissionError, staff_name

ZERO = Decimal('0.00')
CLOSED = ('discharged', 'cancelled')


def money(v):
    return Decimal(v or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _event(adm, event, detail, staff):
    AdmissionEvent.objects.create(admission=adm, event=event, from_status=adm.status, to_status=adm.status,
                                  detail=detail[:2000], staff=staff)


def _lock(adm):
    return AdmissionTable.objects.select_for_update(of=('self',)).select_related('sponsor', 'sponsor__category', 'plan',
                                                                      'patient').get(pk=adm.pk)


def payer_profile(adm):
    """What the pricing rule sees: the sponsor / plan of the admission."""
    p = adm.patient
    return SimpleNamespace(sponsor=adm.sponsor or getattr(p, 'sponsor', None), plan=adm.plan or getattr(p, 'plan', None))


def is_hmo(sponsor):
    cat = getattr(getattr(sponsor, 'category', None), 'category', '') or ''
    return 'hmo' in cat.lower()


def _payer(adm, source):
    return 'sponsor' if is_hmo(payer_profile(adm).sponsor) and source in ('plan', 'sponsor') else 'patient'


def active_final_bill(adm):
    return adm.bills.filter(kind='final', status='active').first()


def _require_billable(adm):
    if adm.status in CLOSED:
        raise AdmissionError(f'This admission is {adm.get_status_display().lower()}; its account is closed.', 'account_closed')
    if active_final_bill(adm):
        raise AdmissionError('A final bill has been generated, so the account is frozen. '
                             'Cancel the final bill (Accounts) to add charges.', 'account_frozen')


def _qty(value, field='Quantity', hi=10000):
    try:
        q = int(str(value).strip())
    except (TypeError, ValueError):
        raise AdmissionError(f'{field} must be a whole number.', 'invalid_qty')
    if q < 1 or q > hi:
        raise AdmissionError(f'{field} must be between 1 and {hi}.', 'invalid_qty')
    return q


def _amount(value, field='Amount'):
    try:
        a = money(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise AdmissionError(f'{field} must be a number.', 'invalid_amount')
    if a <= 0:
        raise AdmissionError(f'{field} must be more than 0.', 'invalid_amount')
    if a > Decimal('100000000'):
        raise AdmissionError(f'{field} is too large.', 'invalid_amount')
    return a


def _reason(value):
    r = (value or '').strip()
    if not r:
        raise AdmissionError('Enter the reason.', 'reason_required')
    return r[:500]


# ------------------------------------------------------------------------------------------------
# Bed-day pricing and accrual
# ------------------------------------------------------------------------------------------------
def quote_bed(adm, ward):
    """(rate, source, tariff_id) for one day in ``ward``, or None when the ward has no price."""
    prof = payer_profile(adm)
    rows = WardTariff.objects.filter(ward=ward).order_by('-id')
    steps = []
    if prof.plan is not None:
        if prof.sponsor is not None:
            steps.append(('plan', Q(sponsor=prof.sponsor, plan=prof.plan)))
        own = Q(sponsor__isnull=True) | (Q(sponsor_id=prof.plan.sponsor_id) if getattr(prof.plan, 'sponsor_id', None) else Q(pk__in=[]))
        steps.append(('plan', Q(plan=prof.plan) & own))
    if prof.sponsor is not None:
        steps.append(('sponsor', Q(sponsor=prof.sponsor, plan__isnull=True)))
    steps.append(('general', Q(sponsor__isnull=True, plan__isnull=True)))
    for source, q in steps:
        row = rows.filter(q).first()
        if row is not None:
            return money(row.rate), source, row.id
    if ward.price:
        return money(ward.price), 'general', None
    return None


def _ward_at(adm, instant):
    """Ward the patient was in at ``instant`` (a bed allocation covering it), or None."""
    al = (BedAllocation.objects.filter(admission_record=adm, created_date__lte=instant)
          .filter(Q(released_at__isnull=True) | Q(released_at__gt=instant))
          .select_related('ward').order_by('-created_date').first())
    return al.ward if al and al.ward else None


def bed_days_due(adm, *, final=False):
    """[(date, ward)] of bed-days owed. Midnight census: a day is charged when the patient was on a
    bed at the midnight that ends it. A stay with no midnight is charged one day on the final bill."""
    start = timezone.localtime(adm.doctor_admit_date).date()
    end_dt = adm.discharged_at or timezone.now()
    end = timezone.localtime(end_dt).date()
    tz = timezone.get_current_timezone()
    out = []
    d = start
    while d < end:
        midnight = timezone.make_aware(datetime.combine(d + timedelta(days=1), time(0, 0)), tz)
        w = _ward_at(adm, midnight)
        if w:
            out.append((d, w))
        d += timedelta(days=1)
    if final and not out:
        w = _ward_at(adm, end_dt) or (BedAllocation.objects.filter(admission_record=adm).select_related('ward')
                                       .order_by('-created_date').first() or SimpleNamespace(ward=None)).ward
        if w:
            out.append((start, w))
    return out


def accrue_bed_days(adm, *, by=None, final=False):
    """Post any bed-days not yet charged. Returns (posted, warnings). Safe to call repeatedly."""
    if adm.status == 'cancelled' or active_final_bill(adm):
        return 0, []
    have = set(adm.charges.filter(kind='bed').values_list('service_date', flat=True))  # incl. reversed (waived)
    posted, warnings = 0, []
    bed_code = _bed_pa_code(adm)
    for d, ward in bed_days_due(adm, final=final):
        if d in have:
            continue
        q = quote_bed(adm, ward)
        if q is None:
            msg = f'{ward.ward_name} has no daily bed price. Set it in Inpatient › Wards › Prices.'
            if msg not in warnings:
                warnings.append(msg)
            continue
        rate, source, tid = q
        try:
            with transaction.atomic():
                AdmissionCharge.objects.create(
                    admission=adm, kind='bed', description=f'Bed fee: {ward.ward_name}', code=f'WARD-{ward.pk}',
                    service_date=d, qty=1, unit_price=rate, amount=rate, price_source=source, tariff_id=tid,
                    payer=_payer(adm, source), ward=ward, posted_by=by,
                    **(_auto_approval(bed_code) if bed_code and _payer(adm, source) == 'sponsor' else {}))
            posted += 1
        except IntegrityError:
            pass   # posted by a parallel request
    return posted, warnings


# ------------------------------------------------------------------------------------------------
# Charges
# ------------------------------------------------------------------------------------------------
def post_service(adm, *, by, name, code=None, qty=1, notes=''):
    from api.pricing import quote, not_priced_message
    with transaction.atomic():
        adm = _lock(adm)
        _require_billable(adm)
        qty = _qty(qty)
        q = quote(payer_profile(adm), 'service', code=code, name=name)
        if q is None:
            raise AdmissionError(not_priced_message(payer_profile(adm), 'service', name), 'not_priced')
        return AdmissionCharge.objects.create(
            admission=adm, kind='service', description=q.name[:255], code=q.code[:50], service_date=timezone.localdate(),
            qty=qty, unit_price=money(q.rate), amount=money(q.rate * qty), price_source=q.source, tariff_id=q.tariff_id,
            payer=_payer(adm, q.source), notes=(notes or '').strip()[:500], posted_by=by)


def post_drug(adm, *, by, store, product, qty, notes=''):
    """Issue pieces of ``product`` from ``store`` to the patient and charge them (one transaction)."""
    from api.pricing import quote, not_priced_message
    from inventory import stock_service
    with transaction.atomic():
        adm = _lock(adm)
        _require_billable(adm)
        qty = _qty(qty, hi=1000)
        if getattr(product, 'merged_into_id', None):
            product = product.merged_into
        q = quote(payer_profile(adm), 'drug', code=product.product_id, name=product.product_name)
        if q is None:
            raise AdmissionError(not_priced_message(payer_profile(adm), 'drug', product.product_name), 'not_priced')
        try:
            lots = stock_service.issue(store, product, qty, movement_type='DISPENSE', reference=adm.admission_no or '',
                                       notes=f'Inpatient issue to {adm.patient.get_full_name()}'[:255], user=by)
        except stock_service.StockError as e:
            raise AdmissionError(str(e), 'stock')
        batches = ', '.join(f"{l['batch_number'] or 'no batch'} x{l['quantity']}" for l in lots)
        return AdmissionCharge.objects.create(
            admission=adm, kind='drug', description=product.product_name[:255], code=(product.product_id or '')[:50],
            service_date=timezone.localdate(), qty=qty, unit_price=money(q.rate), amount=money(q.rate * qty),
            price_source=q.source, tariff_id=q.tariff_id, payer=_payer(adm, q.source), store=store, product=product,
            notes=('; '.join(x for x in [(notes or '').strip(), f'Batches: {batches}' if batches else ''] if x))[:500],
            posted_by=by)


def post_manual(adm, *, by, description, unit_price, qty=1, payer='patient', notes=''):
    with transaction.atomic():
        adm = _lock(adm)
        _require_billable(adm)
        desc = (description or '').strip()
        if not desc:
            raise AdmissionError('Enter what the charge is for.', 'description_required')
        if payer not in ('patient', 'sponsor'):
            raise AdmissionError('Choose who pays.', 'payer')
        reason = _reason(notes)
        qty = _qty(qty)
        rate = _amount(unit_price, 'Price')
        return AdmissionCharge.objects.create(
            admission=adm, kind='other', description=desc[:255], service_date=timezone.localdate(), qty=qty,
            unit_price=rate, amount=money(rate * qty), price_source='manual', payer=payer, notes=reason, posted_by=by)


def reverse_charge(charge, *, by, reason):
    from inventory import stock_service
    reason = _reason(reason)
    with transaction.atomic():
        adm = _lock(charge.admission)
        _require_billable(adm)
        c = AdmissionCharge.objects.select_for_update().get(pk=charge.pk)
        if c.reversed_at:
            raise AdmissionError('This charge is already reversed.', 'already_reversed')
        if c.kind == 'drug' and c.store_id and c.product_id:
            stock_service.receive(c.store, c.product, c.qty, movement_type='RETURN', reference=adm.admission_no or '',
                                  notes=f'Returned from {adm.patient.get_full_name()}: {reason}'[:255], user=by)
        c.reversed_at = timezone.now()
        c.reversed_by = by
        c.reverse_reason = reason
        c.save(update_fields=['reversed_at', 'reversed_by', 'reverse_reason'])
        extra = ' Pieces returned to stock.' if c.kind == 'drug' and c.store_id and c.product_id else ''
        # A ward order paid by this line goes with it: an undispensed supply leaves the pharmacy queue,
        # a lab / radiology request the department has not started leaves its worklist.
        from .models import MedicationSupply
        n = MedicationSupply.objects.filter(charge=c, status='pending').update(
            status='cancelled', cancelled_by=by, cancelled_at=timezone.now(), cancel_reason=f'Bill line reversed: {reason}')
        if n:
            extra += ' Pharmacy supply cancelled.'
        if c.radiolab_id:
            from .order_services import drop_radiolab_if_unstarted
            extra += (' Request removed from the worklist.' if drop_radiolab_if_unstarted(c)
                      else ' The department had already started the request.')
        _event(adm, 'charge_reversed', f'{c.description} x{c.qty} (₦{c.amount:,.2f}) reversed: {reason}' + extra, by)
        return c


def set_payer(charge, *, by, payer):
    if payer not in ('patient', 'sponsor'):
        raise AdmissionError('Choose who pays.', 'payer')
    with transaction.atomic():
        adm = _lock(charge.admission)
        _require_billable(adm)
        c = AdmissionCharge.objects.select_for_update().get(pk=charge.pk)
        if c.reversed_at:
            raise AdmissionError('This charge is reversed.', 'already_reversed')
        if c.payer == payer:
            return c
        c.payer = payer
        if payer == 'sponsor':   # newly claimed: the HMO must approve it
            c.approval_status, c.pa_code, c.approval_note, c.approval_by, c.approval_at = 'pending', '', '', None, None
        else:
            c.approval_status = ''
        c.save(update_fields=['payer', 'approval_status', 'pa_code', 'approval_note', 'approval_by', 'approval_at'])
        return c


# ------------------------------------------------------------------------------------------------
# HMO approval of claim lines
# ------------------------------------------------------------------------------------------------
def _pa(value):
    code = ' '.join(str(value or '').split())
    if not code:
        raise AdmissionError('Enter the PA code the HMO gave.', 'pa_code_required')
    if len(code) > 60:
        raise AdmissionError('The PA code is too long (60 characters at most).', 'pa_code')
    return code


def _bed_pa_code(adm):
    """PA code that covers new sponsor-billed bed-days: the admission's, else the last approved bed-day's."""
    if adm.pa_code:
        return adm.pa_code
    last = (adm.charges.filter(kind='bed', approval_status='approved', reversed_at__isnull=True)
            .exclude(pa_code='').order_by('-service_date').first())
    return last.pa_code if last else ''


def _auto_approval(code):
    return {'approval_status': 'approved', 'pa_code': code, 'approval_at': timezone.now(),
            'approval_note': 'Covered by the admission authorization'}


def approve_charges(adm, *, by, charge_ids, pa_code, for_admission=False, note=''):
    """Record the HMO's PA code on claim lines. ``for_admission`` also keeps it on the admission, so
    pending and future sponsor-billed bed-days are approved with it. Returns the number of lines approved."""
    code = _pa(pa_code)
    with transaction.atomic():
        adm = _lock(adm)
        if adm.status == 'cancelled':
            raise AdmissionError('This admission was cancelled.', 'account_closed')
        ids = {int(x) for x in (charge_ids or []) if str(x).strip().isdigit()}
        lines = list(AdmissionCharge.objects.select_for_update().filter(admission=adm, pk__in=ids)) if ids else []
        if len(lines) != len(ids):
            raise AdmissionError('Some of the chosen lines are not on this account.', 'not_found')
        for c in lines:
            if c.reversed_at:
                raise AdmissionError(f'{c.description} is reversed.', 'already_reversed')
            if c.payer != 'sponsor':
                raise AdmissionError(f'{c.description} is paid by the patient, not claimed from the sponsor.', 'not_claim')
        if for_admission:
            adm.pa_code = code
            adm.save(update_fields=['pa_code'])
            lines += list(AdmissionCharge.objects.select_for_update().filter(
                admission=adm, kind='bed', payer='sponsor', approval_status='pending', reversed_at__isnull=True)
                .exclude(pk__in=[c.pk for c in lines]))
        if not lines and not for_admission:
            raise AdmissionError('Choose the lines the HMO approved.', 'nothing_chosen')
        now = timezone.now()
        note = (note or '').strip()[:500]
        for c in lines:
            c.approval_status, c.pa_code, c.approval_by, c.approval_at = 'approved', code, by, now
            c.approval_note = note
            c.save(update_fields=['approval_status', 'pa_code', 'approval_by', 'approval_at', 'approval_note'])
        if lines:   # lines already posted to the claims ledger (patient has left) carry the code too
            from Billings.models import Invoice
            Invoice.objects.filter(original_source_model='AdmissionCharge', original_source_id__in=[c.pk for c in lines],
                                   payment_option='Claim').update(pa_code=code)
        total = sum((c.amount for c in lines), ZERO)
        what = f'{len(lines)} line{"s" if len(lines) != 1 else ""} (₦{total:,.2f})' if lines else 'No lines'
        _event(adm, 'hmo_approved', f'{what} approved, PA code {code}'
               + ('; kept as the admission authorization' if for_admission else '') + (f'. {note}' if note else ''), by)
        return len(lines)


def _general_price(adm, c):
    """(rate, tariff_id) of the line's item on the General price list, or None."""
    if c.kind == 'bed':
        if not c.ward_id:
            return None
        row = WardTariff.objects.filter(ward_id=c.ward_id, sponsor__isnull=True, plan__isnull=True).order_by('-id').first()
        if row is not None:
            return money(row.rate), row.id
        return (money(c.ward.price), None) if c.ward.price else None
    if c.kind in ('drug', 'lab', 'radiology', 'service'):
        from api.pricing import quote
        q = quote(payer_profile(adm), c.kind, code=c.code or None, name=c.description, pay_from_purse=True)
        if q is not None and q.source == 'general':
            return money(q.rate), q.tariff_id
    return None


def decline_charge(charge, *, by, reason):
    """The HMO does not cover this line: re-price it at the General price and move it to the patient."""
    reason = _reason(reason)
    with transaction.atomic():
        adm = _lock(charge.admission)
        _require_billable(adm)
        c = AdmissionCharge.objects.select_for_update().get(pk=charge.pk)
        if c.reversed_at:
            raise AdmissionError('This charge is reversed.', 'already_reversed')
        if c.payer != 'sponsor':
            raise AdmissionError('This line is already paid by the patient.', 'not_claim')
        old = c.amount
        g = _general_price(adm, c)
        if g is not None:
            c.unit_price, c.tariff_id = g
            c.amount = money(c.unit_price * c.qty)
            c.price_source = 'general'
            priced = f'General price ₦{c.amount:,.2f}'
        else:
            priced = f'no General price, kept ₦{c.amount:,.2f}'
        c.payer, c.approval_status, c.pa_code = 'patient', 'declined', ''
        c.approval_note, c.approval_by, c.approval_at = reason, by, timezone.now()
        c.save()
        _event(adm, 'hmo_declined', f'{c.description} x{c.qty} (claim ₦{old:,.2f}) not covered: {reason}. '
               f'Patient pays, {priced}.', by)
        return c


# ------------------------------------------------------------------------------------------------
# Payments
# ------------------------------------------------------------------------------------------------
def _receipt_no():
    return f'REC-{timezone.now():%y%m%d}-{random.randint(1000, 9999)}'


def record_payment(adm, *, by, amount, method='Cash', kind='deposit', reference=''):
    from Billings.models import Receipt, Refund
    if kind not in dict(AdmissionPayment.KINDS):
        raise AdmissionError('Choose deposit, payment or refund.', 'kind')
    if method not in dict(PAYMENT_METHODS):
        raise AdmissionError('Choose how the money was paid.', 'method')
    amount = _amount(amount)
    if method in ('POS', 'Transfer', 'Cheque') and not (reference or '').strip():
        raise AdmissionError(f'Enter the {method} reference.', 'reference_required')
    with transaction.atomic():
        adm = _lock(adm)
        if adm.status == 'cancelled':
            raise AdmissionError('This admission was cancelled.', 'account_closed')
        if kind == 'refund':
            bal = account_totals(adm)['balance']
            if amount > -bal:
                raise AdmissionError(f'Only ₦{max(-bal, ZERO):,.2f} is in credit and can be refunded.', 'refund_too_large')
        p = AdmissionPayment.objects.create(admission=adm, kind=kind, amount=amount, method=method,
                                            reference=(reference or '').strip()[:100], received_by=by)
        if kind == 'refund':
            Refund.objects.create(invoice_id=(adm.admission_no or '')[:13], amount=int(amount), payment_type=method[:12],
                                  payment_to='Patient', patient=adm.patient, staff=by)
        else:
            p.receipt_number = _receipt_no()
            p.save(update_fields=['receipt_number'])
            Receipt.objects.create(
                patient=adm.patient, invoice_number=(adm.admission_no or '')[:20], receipt_number=p.receipt_number[:20],
                remarks=f'Inpatient {p.get_kind_display().lower()} · {adm.admission_no}'
                        + (f' · ref {p.reference}' if p.reference else ''),
                total_price=int(amount), category=getattr(adm.patient, 'category', None), payment_type=method, staff=by)
        _event(adm, 'payment', f'{p.get_kind_display()} ₦{amount:,.2f} ({method}{", " + p.reference if p.reference else ""})'
               + (f' · receipt {p.receipt_number}' if p.receipt_number else ''), by)
        return p


def reverse_payment(payment, *, by, reason):
    reason = _reason(reason)
    with transaction.atomic():
        adm = _lock(payment.admission)
        if adm.bill_cleared_at:
            raise AdmissionError('The bill is already cleared for discharge; payments can no longer be reversed here.',
                                 'already_cleared')
        p = AdmissionPayment.objects.select_for_update().get(pk=payment.pk)
        if p.reversed_at:
            raise AdmissionError('This payment is already reversed.', 'already_reversed')
        p.reversed_at = timezone.now()
        p.reversed_by = by
        p.reverse_reason = reason
        p.save(update_fields=['reversed_at', 'reversed_by', 'reverse_reason'])
        _event(adm, 'payment_reversed', f'{p.get_kind_display()} ₦{p.amount:,.2f} '
               f'{("(receipt " + p.receipt_number + ") ") if p.receipt_number else ""}reversed: {reason}', by)
        return p


# ------------------------------------------------------------------------------------------------
# Totals, bills, clearance
# ------------------------------------------------------------------------------------------------
def account_totals(adm):
    charges = [c for c in adm.charges.all() if not c.reversed_at]
    total = sum((c.amount for c in charges), ZERO)
    sponsor = sum((c.amount for c in charges if c.payer == 'sponsor'), ZERO)
    patient = total - sponsor
    pays = [p for p in adm.payments.all() if not p.reversed_at]
    received = sum((p.amount for p in pays if p.kind != 'refund'), ZERO)
    refunded = sum((p.amount for p in pays if p.kind == 'refund'), ZERO)
    paid = received - refunded
    by_kind = {}
    for c in charges:
        by_kind[c.kind] = by_kind.get(c.kind, ZERO) + c.amount
    return {'total': money(total), 'sponsor_total': money(sponsor), 'patient_total': money(patient),
            'received': money(received), 'refunded': money(refunded), 'paid': money(paid),
            'balance': money(patient - paid), 'by_kind': {k: money(v) for k, v in by_kind.items()},
            'lines': len(charges)}


def generate_bill(adm, *, by, kind='interim'):
    if kind not in ('interim', 'final'):
        raise AdmissionError('Choose interim or final bill.', 'kind')
    with transaction.atomic():
        adm = _lock(adm)
        if adm.status == 'cancelled':
            raise AdmissionError('This admission was cancelled.', 'account_closed')
        if kind == 'final':
            pending = adm.supplies.filter(status='pending').count()
            if pending:
                raise AdmissionError(f'{pending} drug supply request{"s are" if pending != 1 else " is"} still awaiting '
                                     f'the pharmacy. Dispense or cancel {"them" if pending != 1 else "it"} before the '
                                     f'final bill.', 'supplies_pending')
            if adm.status != 'discharge_ordered':
                raise AdmissionError('The final bill is made after the doctor signs the discharge. '
                                     'Use an interim bill until then.', 'not_discharge_ordered')
            if active_final_bill(adm):
                raise AdmissionError('A final bill already exists for this admission.', 'final_exists')
        accrue_bed_days(adm, by=by, final=(kind == 'final'))
        if kind == 'final':
            waiting = list(adm.charges.filter(payer='sponsor', approval_status='pending', reversed_at__isnull=True))
            if waiting:
                n = len(waiting)
                raise AdmissionError(
                    f'{n} claim line{"s are" if n != 1 else " is"} still awaiting HMO approval '
                    f'(₦{sum((c.amount for c in waiting), ZERO):,.2f}). Enter the PA code for each, or mark it '
                    f'"Not covered" so the patient pays.', 'approvals_pending')
        t = account_totals(adm)
        if kind == 'final' and t['lines'] == 0:
            raise AdmissionError('There are no charges on this account.', 'no_charges')
        try:
            with transaction.atomic():
                b = AdmissionBill.objects.create(
                    admission=adm, bill_no=f'TMP-{random.randint(10 ** 8, 10 ** 9)}', kind=kind, total=t['total'],
                    sponsor_total=t['sponsor_total'], patient_total=t['patient_total'], paid_total=t['paid'],
                    balance=t['balance'], created_by=by)
        except IntegrityError:
            raise AdmissionError('A final bill already exists for this admission.', 'final_exists')
        b.bill_no = f'IPB-{timezone.now():%Y}-{b.pk:05d}'
        b.save(update_fields=['bill_no'])
        _event(adm, 'bill', f'{b.get_kind_display()} {b.bill_no}: total ₦{b.total:,.2f}, patient ₦{b.patient_total:,.2f}, '
               f'sponsor ₦{b.sponsor_total:,.2f}, paid ₦{b.paid_total:,.2f}, balance ₦{b.balance:,.2f}', by)
        return b


def cancel_final_bill(bill, *, by, reason):
    reason = _reason(reason)
    with transaction.atomic():
        adm = _lock(bill.admission)
        if adm.status in CLOSED:
            raise AdmissionError('The patient has already left; the account is closed.', 'account_closed')
        b = AdmissionBill.objects.select_for_update().get(pk=bill.pk)
        if b.kind != 'final' or b.status != 'active':
            raise AdmissionError('Only an active final bill can be cancelled.', 'not_final')
        b.status = 'cancelled'
        b.cancelled_at = timezone.now()
        b.cancelled_by = by
        b.cancel_reason = reason
        b.save(update_fields=['status', 'cancelled_at', 'cancelled_by', 'cancel_reason'])
        _unclear(adm)
        _event(adm, 'bill_cancelled', f'{b.bill_no} cancelled: {reason}. Account reopened.', by)
        return b


def _unclear(adm):
    if adm.bill_cleared_at:
        adm.bill_cleared_at = None
        adm.bill_cleared_by = None
        adm.clearance_type = ''
        adm.clearance_note = ''
        adm.bill_discharge_status = 0
        adm.save(update_fields=['bill_cleared_at', 'bill_cleared_by', 'clearance_type', 'clearance_note',
                                'bill_discharge_status'])


def clear_for_discharge(adm, *, by, credit_reason='', allow_credit=False):
    """Bill clearance. Paid in full -> 'paid'. Balance owing -> only an administrator, with a reason -> 'credit'."""
    with transaction.atomic():
        adm = _lock(adm)
        if adm.status != 'discharge_ordered':
            raise AdmissionError('Bill clearance is done after the doctor signs the discharge.', 'not_discharge_ordered')
        if adm.bill_cleared_at:
            raise AdmissionError('The bill is already cleared.', 'already_cleared')
        if not active_final_bill(adm):
            raise AdmissionError('Generate the final bill first.', 'no_final_bill')
        t = account_totals(adm)
        if t['balance'] > 0:
            if not allow_credit:
                raise AdmissionError(f'The patient still owes ₦{t["balance"]:,.2f}. Take payment, or an administrator '
                                     f'can release the patient on credit with a reason.', 'balance_owing')
            note = _reason(credit_reason)
            adm.clearance_type = 'credit'
            adm.clearance_note = f'Released owing ₦{t["balance"]:,.2f}: {note}'
        else:
            adm.clearance_type = 'paid'
            adm.clearance_note = (f'Credit of ₦{-t["balance"]:,.2f} to refund.' if t['balance'] < 0 else '')
        adm.bill_cleared_at = timezone.now()
        adm.bill_cleared_by = by
        adm.bill_discharge_status = 1
        adm.save(update_fields=['clearance_type', 'clearance_note', 'bill_cleared_at', 'bill_cleared_by',
                                'bill_discharge_status'])
        _event(adm, 'bill_cleared', ('On credit. ' if adm.clearance_type == 'credit' else 'Paid in full. ')
               + adm.clearance_note, by)
        from .services import _notify, WARD_NURSING_DEPARTMENTS
        _notify(departments=WARD_NURSING_DEPARTMENTS, kind='bill_cleared', actor=by,
                title=f'Bill cleared: {adm.patient.get_full_name()}',
                message=f'{adm.admission_no} · {getattr(adm.ward, "ward_name", "")} {getattr(adm.bed, "bed_name", "")} · '
                        f'the patient can leave. Release the bed when they go.',
                link='/ipd/admitted', level='success', icon='fa-file-invoice-dollar', ref=f'admission:{adm.pk}')
        return adm


def on_discharge_withdrawn(adm, by):
    """Doctor withdrew the discharge: the final bill and clearance no longer apply."""
    b = active_final_bill(adm)
    if b:
        b.status = 'cancelled'
        b.cancelled_at = timezone.now()
        b.cancelled_by = by
        b.cancel_reason = 'Discharge order withdrawn'
        b.save(update_fields=['status', 'cancelled_at', 'cancelled_by', 'cancel_reason'])
        _event(adm, 'bill_cancelled', f'{b.bill_no} cancelled because the discharge was withdrawn. Account reopened.', by)
    _unclear(adm)


def post_to_ledger(adm, by):
    """Patient has left: write the stay to Billings.Invoice (claims + patient invoice). Idempotent."""
    from Billings.models import Invoice
    charges = [c for c in adm.charges.all() if not c.reversed_at]
    if not charges or Invoice.objects.filter(original_source_model='AdmissionCharge',
                                             original_source_id__in=[c.id for c in charges]).exists():
        return
    stamp = (adm.admission_no or str(adm.pk)).replace('ADM-', '')
    rows = []
    for c in charges:
        claim = c.payer == 'sponsor'
        rows.append(Invoice(
            patient=adm.patient, invoice_number=(f'CLM-{stamp}' if claim else f'INV-{stamp}')[:20],
            product=c.description[:60], qty=c.qty, discount=0, price=int(c.amount.to_integral_value(ROUND_HALF_UP)),
            payment_option='Claim' if claim else ('Cash' if adm.clearance_type == 'paid' else 'Credit'),
            category=getattr(adm.patient, 'category', None),
            # claims wait for the HMO approval desk; the patient's share is settled through the account
            completed=0 if claim else (1 if adm.clearance_type == 'paid' else 0),
            pa_code=(c.pa_code or '')[:60] if claim else '',
            original_source_model='AdmissionCharge', original_source_id=c.id, staff=by))
    Invoice.objects.bulk_create(rows)


def change_admission_type(adm, *, by, admission_type):
    from .models import ADMISSION_TYPES
    labels = dict(ADMISSION_TYPES)
    if admission_type not in labels:
        raise AdmissionError('Choose the type of admission.', 'admission_type')
    with transaction.atomic():
        adm = _lock(adm)
        if adm.status in CLOSED:
            raise AdmissionError('This admission is closed.', 'account_closed')
        if adm.admission_type == admission_type:
            raise AdmissionError('The admission is already of this type.', 'same_type')
        old = adm.get_admission_type_display()
        adm.admission_type = admission_type
        adm.save(update_fields=['admission_type', 'updated_at'])
        _event(adm, 'type_changed', f'{old} → {labels[admission_type]}', by)
        return adm

