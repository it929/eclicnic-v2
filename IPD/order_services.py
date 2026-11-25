"""
Ward orders that reach other departments and the inpatient bill on their own.

Drug-chart orders  -> MedicationSupply (inpatient pharmacy queue) + a bill line posted at once
                      (priced from the admission's sponsor / plan, or the general price list when the
                      doctor ordered it as "pay from purse"). Stock leaves the store only when pharmacy
                      dispenses; the bill line is then settled to the exact item and quantity given.
Investigations     -> lab / radiology: a RadiologyLab request in the Laboratory / Radiology worklist,
                      already cleared for billing (the stay is on a running account), + a bill line.
                      Services: a bill line.

Nothing is charged twice: OPD billing never sees these requests (billing_waiting_status=0 and no
Billings.Invoice rows until the stay is posted to the ledger at discharge).
"""
from django.db import transaction
from django.utils import timezone

from .billing_services import _event, _lock, _payer, _qty, _require_billable, money, payer_profile
from .models import AdmissionCharge, MedicationSupply
from .services import AdmissionError, staff_name

INVESTIGATION_KINDS = {'lab': 'Laboratory test', 'radiology': 'Radiology / scan', 'service': 'Service / procedure'}


def _quote(adm, kind, *, code, name, purse):
    from api.pricing import quote
    return quote(payer_profile(adm), kind, code=code or None, name=name, pay_from_purse=purse)


def _not_priced(adm, kind, name):
    from api.pricing import not_priced_message
    return not_priced_message(payer_profile(adm), kind, name)


def _ward_store(adm):
    st = getattr(getattr(adm, 'ward', None), 'pharmacy_store', None)
    return st if st is not None and getattr(st, 'is_active', True) else None


# ------------------------------------------------------------------------------------------------
# Pharmacy supply of drug-chart orders
# ------------------------------------------------------------------------------------------------
def _drug_charge(adm, rx, *, by, qty, quote, store, notes):
    return AdmissionCharge.objects.create(
        admission=adm, kind='drug', description=(quote.name or rx.drug_name)[:255], code=(quote.code or '')[:50],
        service_date=timezone.localdate(), qty=qty, unit_price=money(quote.rate), amount=money(quote.rate * qty),
        price_source=quote.source, tariff_id=quote.tariff_id, payer=_payer(adm, quote.source), store=store,
        prescription=rx, notes=notes[:500], posted_by=by)


def raise_supply(adm, rx, *, by, qty, kind='initial', notes=''):
    """Send ``qty`` of a drug-chart order to the pharmacy and bill it. Returns (supply, warning|None)."""
    qty = _qty(qty, 'Quantity to supply', hi=1000)
    with transaction.atomic():
        adm = _lock(adm)
        if adm.status in ('discharged', 'cancelled'):
            raise AdmissionError('This admission is closed.', 'account_closed')
        if not rx.is_active:
            raise AdmissionError('This medication has been stopped.', 'stopped')
        store = _ward_store(adm)
        supply = MedicationSupply.objects.create(admission=adm, prescription=rx, kind=kind, qty=qty, store=store,
                                                 notes=(notes or '').strip()[:500], requested_by=by)
        warning = None
        # A refill of a drug the HMO already declined goes straight to the patient at the General price.
        declined = rx.charges.filter(approval_status='declined', reversed_at__isnull=True).exists()
        q = _quote(adm, 'drug', code=rx.product_code, name=rx.drug_name, purse=rx.pay_source == 'patient' or declined)
        if q is None:
            warning = (f'{rx.drug_name} is not on a price list: it will be billed when pharmacy dispenses it '
                       f'from the catalogue.')
        else:
            try:
                _require_billable(adm)
                supply.charge = _drug_charge(adm, rx, by=by, qty=qty, quote=q, store=store,
                                             notes='Awaiting pharmacy')
                supply.save(update_fields=['charge'])
            except AdmissionError as e:
                warning = f'Not billed yet: {e}'
        _event(adm, 'supply_requested', f'{rx.drug_name} x{qty} sent to {getattr(store, "name", "the inpatient pharmacy")}'
               f' ({supply.get_kind_display().lower()})', by)
        return supply, warning


def cancel_supply(supply, *, by, reason, from_charge=False):
    """Cancel a supply pharmacy has not dispensed; its bill line is reversed with it."""
    from .billing_services import _reason
    reason = _reason(reason)
    with transaction.atomic():
        adm = _lock(supply.admission)
        s = MedicationSupply.objects.select_for_update().get(pk=supply.pk)
        if s.status != 'pending':
            raise AdmissionError(f'This supply is already {s.get_status_display().lower()}.', 'not_pending')
        s.status = 'cancelled'
        s.cancelled_by = by
        s.cancelled_at = timezone.now()
        s.cancel_reason = reason
        s.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'cancel_reason'])
        if s.charge_id and not from_charge:
            c = AdmissionCharge.objects.select_for_update().get(pk=s.charge_id)
            if not c.reversed_at:
                _require_billable(adm)
                c.reversed_at, c.reversed_by, c.reverse_reason = timezone.now(), by, f'Supply cancelled: {reason}'
                c.save(update_fields=['reversed_at', 'reversed_by', 'reverse_reason'])
        _event(adm, 'supply_cancelled', f'{s.prescription.drug_name} x{s.qty} not supplied: {reason}', by)
        return s


def cancel_pending_supplies(rx, *, by, reason):
    """When an order is stopped: undispensed supplies are cancelled and their bill lines reversed.
    Returns a warning when the account is frozen (the line then stays for Accounts to reverse)."""
    warning = None
    for s in rx.supplies.filter(status='pending'):
        try:
            cancel_supply(s, by=by, reason=reason)
        except AdmissionError as e:
            if e.code != 'account_frozen':
                raise
            MedicationSupply.objects.filter(pk=s.pk).update(status='cancelled', cancelled_by=by,
                                                            cancelled_at=timezone.now(), cancel_reason=reason)
            warning = 'The final bill is active, so the undispensed drug is still on it: ask Accounts to reverse it.'
    return warning


def dispense_supply(supply, *, by, store, product, qty):
    """Pharmacy gives the drug: stock leaves ``store`` and the bill line is settled to what was given."""
    from inventory import stock_service
    qty = _qty(qty, 'Quantity dispensed', hi=1000)
    with transaction.atomic():
        adm = _lock(supply.admission)
        _require_billable(adm)
        s = MedicationSupply.objects.select_for_update(of=('self',)).select_related('prescription').get(pk=supply.pk)
        if s.status != 'pending':
            raise AdmissionError(f'This supply is already {s.get_status_display().lower()}.', 'not_pending')
        rx = s.prescription
        if getattr(product, 'merged_into_id', None):
            product = product.merged_into
        charge = AdmissionCharge.objects.select_for_update().get(pk=s.charge_id) if s.charge_id else None
        if charge and charge.reversed_at:
            charge = None
        # Patient pays when the doctor chose "pay from purse" or the HMO declined the line.
        purse = rx.pay_source == 'patient' or (charge is not None and charge.approval_status == 'declined')
        # Same item as billed -> keep the price fixed at ordering; another item -> price that item.
        same = charge is not None and charge.code and charge.code == (product.product_id or '')
        q = None if same else _quote(adm, 'drug', code=product.product_id, name=product.product_name, purse=purse)
        if not same and q is None:
            raise AdmissionError(_not_priced(adm, 'drug', product.product_name), 'not_priced')
        try:
            lots = stock_service.issue(store, product, qty, movement_type='DISPENSE', reference=f'IPD-RX-{rx.id}',
                                       notes=f'Inpatient {adm.admission_no}: {adm.patient.get_full_name()}'[:255],
                                       user=by)
        except stock_service.StockError as e:
            raise AdmissionError(str(e), 'stock')
        batches = ', '.join(f"{l['batch_number'] or 'no batch'} x{l['quantity']}" for l in lots)
        note = f'Dispensed by {staff_name(by)}' + (f'; batches: {batches}' if batches else '')
        if charge is not None:
            charge.qty = qty
            charge.store = store
            charge.product = product
            if not same:
                charge.description, charge.code = (q.name or product.product_name)[:255], (q.code or '')[:50]
                charge.unit_price, charge.price_source, charge.tariff_id = money(q.rate), q.source, q.tariff_id
                charge.payer = _payer(adm, q.source)
                if charge.payer == 'sponsor':   # a different item: the HMO approves it afresh
                    charge.approval_status, charge.pa_code, charge.approval_by, charge.approval_at = 'pending', '', None, None
            charge.amount = money(charge.unit_price * qty)
            charge.notes = note[:500]
            charge.save()
        else:
            charge = _drug_charge(adm, rx, by=by, qty=qty, quote=q, store=store, notes=note)
            charge.product = product
            charge.save(update_fields=['product'])
        s.status, s.store, s.product, s.qty_dispensed = 'dispensed', store, product, qty
        s.dispensed_by, s.dispensed_at, s.batches, s.charge = by, timezone.now(), batches[:500], charge
        s.save()
        _event(adm, 'supply_dispensed', f'{product.product_name} x{qty} dispensed from {store.name} for '
               f'{rx.drug_name} (₦{charge.amount:,.2f})', by)
        return s


# ------------------------------------------------------------------------------------------------
# Lab / radiology / service requests from the ward
# ------------------------------------------------------------------------------------------------
def order_investigation(adm, *, by, kind, name, code='', purse=False, notes='', urgent=False):
    if kind not in INVESTIGATION_KINDS:
        raise AdmissionError('Choose laboratory, radiology or service.', 'kind')
    name = (name or '').strip()
    if not name:
        raise AdmissionError('Choose what is requested.', 'required')
    notes = (notes or '').strip()[:500]
    with transaction.atomic():
        adm = _lock(adm)
        _require_billable(adm)
        q = _quote(adm, kind, code=code, name=name, purse=bool(purse))
        if q is None:
            raise AdmissionError(_not_priced(adm, kind, name), 'not_priced')
        rl = None
        if kind in ('lab', 'radiology'):
            from radio_lab.models import RadiologyLab
            p = adm.patient
            where = ' / '.join(x for x in (getattr(adm.ward, 'ward_name', None), getattr(adm.bed, 'bed_name', None)) if x)
            comment = ' · '.join(x for x in (f'Inpatient {adm.admission_no}', where, notes) if x)
            # bulk_create skips RadiologyLab.save(), which would open an OPD billing transaction for the patient.
            rl = RadiologyLab(item=q.name or name, item_type='L' if kind == 'lab' else 'R', rate=money(q.rate),
                              comment=comment, patient=p, category=getattr(p, 'category', None), plan=adm.plan,
                              staff=by, emergency='Urgent' if urgent else None, billing_waiting_status=0,
                              radiolab_waiting_status=0, completed=0, created_date=timezone.now())
            RadiologyLab.objects.bulk_create([rl])
            if rl.pk is None:
                rl = RadiologyLab.objects.filter(patient=p, item=rl.item).order_by('-id').first()
        c = AdmissionCharge.objects.create(
            admission=adm, kind=kind, description=(q.name or name)[:255], code=(q.code or '')[:50],
            service_date=timezone.localdate(), qty=1, unit_price=money(q.rate), amount=money(q.rate),
            price_source=q.source, tariff_id=q.tariff_id, payer=_payer(adm, q.source), ward=adm.ward,
            notes=notes, posted_by=by, radiolab=rl, urgent=bool(urgent))
        _event(adm, 'investigation_ordered', f'{INVESTIGATION_KINDS[kind]}: {c.description}'
               f'{" (URGENT)" if urgent else ""} · ₦{c.amount:,.2f}', by)
        return c


def radiolab_state(rl):
    """'cancelled' | 'awaiting' | 'in_progress' | 'ready' for a lab / radiology request."""
    if rl is None:
        return 'cancelled'
    if rl.completed == 1:
        return 'ready'
    started = rl.lab_results.exists() or rl.scan_results.exists() or rl.parameter_results.exclude(result_value='').exists()
    return 'in_progress' if started else 'awaiting'


def drop_radiolab_if_unstarted(c):
    """Remove the lab / radiology request of a reversed line when the department has not started it."""
    rl = c.radiolab
    if rl is not None and radiolab_state(rl) == 'awaiting':
        c.radiolab = None
        c.save(update_fields=['radiolab'])
        rl.delete()
        return True
    return False


def cancel_investigation(charge, *, by, reason):
    from .billing_services import _reason
    reason = _reason(reason)
    with transaction.atomic():
        adm = _lock(charge.admission)
        _require_billable(adm)
        c = AdmissionCharge.objects.select_for_update(of=('self',)).select_related('radiolab').get(pk=charge.pk)
        if c.kind not in INVESTIGATION_KINDS:
            raise AdmissionError('This line is not a ward request.', 'not_request')
        if c.reversed_at:
            raise AdmissionError('This request is already cancelled.', 'already_reversed')
        if c.radiolab_id and radiolab_state(c.radiolab) != 'awaiting':
            dept = 'Laboratory' if c.kind == 'lab' else 'Radiology'
            raise AdmissionError(f'{dept} has already started this request, so it cannot be cancelled here. '
                                 f'Ask {dept} or Accounts.', 'started')
        drop_radiolab_if_unstarted(c)
        c.reversed_at, c.reversed_by, c.reverse_reason = timezone.now(), by, f'Request cancelled: {reason}'
        c.save(update_fields=['reversed_at', 'reversed_by', 'reverse_reason'])
        _event(adm, 'investigation_cancelled', f'{INVESTIGATION_KINDS[c.kind]}: {c.description} cancelled: {reason}', by)
        return c
