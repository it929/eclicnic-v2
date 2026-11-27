"""
Hospital reports (the Reporting page). Every report reads the live database for a date range.

Each report returns:
    {title, description, columns: [{key, label, type}], rows: [...], summary: [{label, value, type}],
     count, truncated, note}
Column types: text | money | int | date | datetime | badge.
Rows are capped at MAX_ROWS (the response says `truncated`); filtering by text is done on the server
so the cap never hides a match.

Money rules match the cash desk (Billings/cashdesk.py) and cash-up (Billings/cashup.py):
Invoice.price is the net line total; a line is paid when completed=1, otherwise amount_paid so far.
Clinical diagnoses are NOT included in any report (management reports are not clinical records).
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Max, Q, Sum
from django.utils import timezone

MAX_ROWS = 5000


# ------------------------------------------------------------------ helpers
def _range(first, last):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(first, time.min), tz),
            timezone.make_aware(datetime.combine(last + timedelta(days=1), time.min), tz))


def _dt(v):
    return timezone.localtime(v).isoformat() if v else None


def _name(p):
    if not p:
        return ''
    return ' '.join(x for x in [p.surname, p.first_name, getattr(p, 'other_name', '')] if x).strip()


def _staff(u):
    return (getattr(u, 'fullname', '') or getattr(u, 'username', '')) if u else ''


def _age(p):
    try:
        return p.age() if callable(getattr(p, 'age', None)) else None
    except Exception:
        return None


def _col(key, label, type_='text'):
    return {'key': key, 'label': label, 'type': type_}


def _matches(row, q, keys):
    if not q:
        return True
    q = q.lower()
    return any(q in str(row.get(k) or '').lower() for k in keys)


def _finish(title, description, columns, rows, summary=None, note='', search_keys=None, q=''):
    keys = search_keys or [c['key'] for c in columns if c['type'] in ('text', 'badge')]
    rows = [r for r in rows if _matches(r, q, keys)]
    return {
        'title': title, 'description': description, 'columns': columns,
        'rows': rows[:MAX_ROWS], 'count': len(rows), 'truncated': len(rows) > MAX_ROWS,
        'summary': summary or [], 'note': note,
    }


def _sum(label, value, type_='int'):
    return {'label': label, 'value': value, 'type': type_}


# ------------------------------------------------------------------ ambulatory
def patients_registration(first, last, q=''):
    from patients.models import PatientProfile
    a, b = _range(first, last)
    qs = (PatientProfile.objects.filter(created_date__gte=a, created_date__lt=b)
          .select_related('category', 'plan', 'sponsor', 'created_by').order_by('created_date', 'id'))
    rows, cats = [], Counter()
    for p in qs:
        cat = getattr(p.category, 'category', '') or ''
        cats[cat or 'Uncategorised'] += 1
        rows.append({
            'hospital_number': p.hospital_number, 'name': _name(p), 'gender': p.gender or '', 'age': _age(p),
            'category': cat, 'plan': getattr(p.plan, 'plan', '') or '', 'sponsor': getattr(p.sponsor, 'name', '') or '',
            'registered': _dt(p.created_date), 'registered_by': _staff(p.created_by),
            'status': 'Active' if p.active else 'Deactivated',
        })
    cols = [_col('hospital_number', 'Hospital No'), _col('name', 'Patient'), _col('gender', 'Gender'),
            _col('age', 'Age', 'int'), _col('category', 'Category'), _col('plan', 'Plan'), _col('sponsor', 'Sponsor / HMO'),
            _col('registered', 'Registered', 'datetime'), _col('registered_by', 'Registered by'), _col('status', 'Status', 'badge')]
    summary = [_sum('Registered', len(rows))] + [_sum(k, v) for k, v in cats.most_common(4)]
    return _finish('Patients Registration Report', 'New patient records created in the period.', cols, rows, summary, q=q)


def _visit_rows(first, last, attended_only):
    from patients.models import PatientAppointment
    from queue_operations.models import PatientEncounter, DoctorWaitingList
    a, b = _range(first, last)
    qs = (PatientAppointment.objects.filter(arrival_date__gte=first, arrival_date__lte=last)
          .select_related('patient', 'patient__category', 'provider').order_by('arrival_date', 'arrival_time', 'id'))
    seen = {(pid, timezone.localtime(t).date()) for pid, t in
            PatientEncounter.objects.filter(created_at__gte=a, created_at__lt=b).values_list('patient_id', 'created_at')}
    vitals = {(pid, timezone.localtime(t).date()) for pid, t in
              DoctorWaitingList.objects.filter(created_date__gte=a, created_date__lt=b).values_list('patient_id', 'created_date')}
    today = timezone.localdate()
    rows = []
    for ap in qs:
        p = ap.patient
        key = (ap.patient_id, ap.arrival_date)
        if ap.completed == 2:
            status = 'Cancelled'
        elif key in seen:
            status = 'Seen by doctor'
        elif key in vitals:
            status = 'Vitals taken'
        elif ap.completed == 1:
            status = 'Completed'
        elif ap.arrival_date < today:
            status = 'Did not attend'
        else:
            status = 'Booked'
        if attended_only and status in ('Cancelled', 'Booked', 'Did not attend'):
            continue
        rows.append({
            'date': ap.arrival_date.isoformat() if ap.arrival_date else None,
            'time': ap.arrival_time.strftime('%H:%M') if ap.arrival_time else '',
            'hospital_number': getattr(p, 'hospital_number', '') or '', 'name': _name(p),
            'category': getattr(getattr(p, 'category', None), 'category', '') or '',
            'visit_type': ap.visit_type or '', 'purpose': ap.purpose or '',
            'clinician': ap.clinician or _staff(ap.provider), 'status': status,
        })
    return rows


def visits(first, last, q=''):
    rows = _visit_rows(first, last, attended_only=True)
    kinds = Counter(r['visit_type'] or 'Unspecified' for r in rows)
    cols = [_col('date', 'Date', 'date'), _col('time', 'Time'), _col('hospital_number', 'Hospital No'), _col('name', 'Patient'),
            _col('category', 'Category'), _col('visit_type', 'Visit type'), _col('purpose', 'Purpose'),
            _col('clinician', 'Clinician'), _col('status', 'Status', 'badge')]
    summary = [_sum('Visits attended', len(rows)), _sum('Seen by doctor', sum(r['status'] == 'Seen by doctor' for r in rows))] + \
              [_sum(k, v) for k, v in kinds.most_common(3)]
    return _finish('Visit & Consultation Report', 'Patients who came in (vitals taken or seen by a doctor) in the period.',
                   cols, rows, summary, q=q)


def appointments(first, last, q=''):
    rows = _visit_rows(first, last, attended_only=False)
    st = Counter(r['status'] for r in rows)
    cols = [_col('date', 'Date', 'date'), _col('time', 'Time'), _col('hospital_number', 'Hospital No'), _col('name', 'Patient'),
            _col('visit_type', 'Visit type'), _col('purpose', 'Purpose'), _col('clinician', 'Clinician'), _col('status', 'Status', 'badge')]
    summary = [_sum('Appointments', len(rows))] + [_sum(k, v) for k, v in st.most_common(5)]
    return _finish('Appointments Report', 'All appointments for the period, with what happened to each.', cols, rows, summary, q=q)


def admissions(first, last, q=''):
    from IPD.models import AdmissionTable
    a, b = _range(first, last)
    qs = (AdmissionTable.objects.filter(Q(doctor_admit_date__gte=a, doctor_admit_date__lt=b) |
                                        Q(discharged_at__gte=a, discharged_at__lt=b))
          .select_related('patient', 'ward', 'bed', 'consultant', 'sponsor').order_by('doctor_admit_date', 'id'))
    labels = dict(AdmissionTable._meta.get_field('status').choices)
    types = dict(AdmissionTable._meta.get_field('admission_type').choices)
    now = timezone.now()
    rows, admitted, discharged = [], 0, 0
    for ad in qs:
        if ad.doctor_admit_date and a <= ad.doctor_admit_date < b:
            admitted += 1
        if ad.discharged_at and a <= ad.discharged_at < b:
            discharged += 1
        start = ad.nurse_admit_date or ad.doctor_admit_date
        end = ad.discharged_at or (now if ad.status in ('in_ward', 'discharge_ordered') else None)
        rows.append({
            'admission_no': ad.admission_no or f'#{ad.pk}', 'hospital_number': getattr(ad.patient, 'hospital_number', '') or '',
            'name': _name(ad.patient), 'type': types.get(ad.admission_type, ad.admission_type or ''),
            'ward': ' / '.join(x for x in [getattr(ad.ward, 'ward_name', ''), getattr(ad.bed, 'bed_name', '')] if x),
            'consultant': _staff(ad.consultant), 'payer': getattr(ad.sponsor, 'name', '') or 'Private',
            'admitted': _dt(ad.doctor_admit_date), 'discharged': _dt(ad.discharged_at),
            'days': max(1, (end - start).days + (1 if (end - start).seconds else 0)) if start and end else None,
            'status': labels.get(ad.status, ad.status),
        })
    cols = [_col('admission_no', 'Admission No'), _col('hospital_number', 'Hospital No'), _col('name', 'Patient'),
            _col('type', 'Type'), _col('ward', 'Ward / bed'), _col('consultant', 'Consultant'), _col('payer', 'Payer'),
            _col('admitted', 'Admitted', 'datetime'), _col('discharged', 'Discharged', 'datetime'),
            _col('days', 'Days', 'int'), _col('status', 'Status', 'badge')]
    summary = [_sum('Admitted in period', admitted), _sum('Discharged in period', discharged),
               _sum('Still in ward', sum(r['status'] in (labels.get('in_ward'), labels.get('discharge_ordered')) for r in rows))]
    return _finish('IPD Admission Report', 'Admissions started or discharged in the period.', cols, rows, summary, q=q)


def deactivated(first, last, q=''):
    from patients.models import PatientProfile
    a, b = _range(first, last)
    qs = (PatientProfile.objects.filter(active=0).filter(Q(deactivated_date__gte=a, deactivated_date__lt=b))
          .select_related('category').order_by('-deactivated_date'))
    unknown = PatientProfile.objects.filter(active=0, deactivated_date__isnull=True).count()
    rows = [{
        'hospital_number': p.hospital_number, 'name': _name(p), 'category': getattr(p.category, 'category', '') or '',
        'phone': p.phone_number or '', 'deactivated': _dt(p.deactivated_date), 'by': p.deactivated_by or '',
    } for p in qs]
    cols = [_col('hospital_number', 'Hospital No'), _col('name', 'Patient'), _col('category', 'Category'), _col('phone', 'Phone'),
            _col('deactivated', 'Deactivated', 'datetime'), _col('by', 'Deactivated by')]
    note = f'{unknown} older deactivated record(s) have no date and are not listed.' if unknown else ''
    return _finish('Deactivated Patients', 'Patient records deactivated in the period.', cols, rows,
                   [_sum('Deactivated', len(rows))], note, q=q)


# ------------------------------------------------------------------ billing
def _line_status(inv):
    claim = (inv.invoice_number or '').startswith('CLM-') or (inv.payment_option or '') == 'Claim'
    if claim:
        return 'HMO claim (approved)' if inv.completed else 'HMO claim (pending)'
    if inv.completed:
        return 'Paid'
    return 'Part-paid' if int(inv.amount_paid or 0) > 0 else 'Unpaid'


def invoices(first, last, q=''):
    from Billings.models import Invoice
    a, b = _range(first, last)
    qs = Invoice.objects.filter(created_date__gte=a, created_date__lt=b).select_related('patient', 'staff').order_by('created_date', 'id')
    rows = []
    t = Counter()
    for inv in qs:
        price = int(inv.price or 0)
        status = _line_status(inv)
        claim = status.startswith('HMO')
        paid = 0 if claim else (price if inv.completed else min(price, int(inv.amount_paid or 0)))
        bal = 0 if claim else price - paid
        t['billed'] += price
        t['claims' if claim else 'cash_billed'] += price
        t['paid'] += paid
        t['outstanding'] += bal
        rows.append({
            'invoice_number': inv.invoice_number or f'INV-{inv.id}', 'date': _dt(inv.created_date),
            'hospital_number': getattr(inv.patient, 'hospital_number', '') or '', 'name': _name(inv.patient),
            'item': inv.product or '', 'qty': inv.qty, 'amount': price, 'paid': paid, 'balance': bal,
            'payment_option': inv.payment_option or '', 'status': status, 'billed_by': _staff(inv.staff),
        })
    cols = [_col('invoice_number', 'Bill No'), _col('date', 'Date', 'datetime'), _col('hospital_number', 'Hospital No'),
            _col('name', 'Patient'), _col('item', 'Service / item'), _col('qty', 'Qty', 'int'), _col('amount', 'Amount', 'money'),
            _col('paid', 'Paid', 'money'), _col('balance', 'Balance', 'money'), _col('payment_option', 'Payment'),
            _col('status', 'Status', 'badge'), _col('billed_by', 'Billed by')]
    summary = [_sum('Total billed', t['billed'], 'money'), _sum('Patient bills', t['cash_billed'], 'money'),
               _sum('Paid', t['paid'], 'money'), _sum('Still owed', t['outstanding'], 'money'), _sum('HMO claims', t['claims'], 'money')]
    return _finish('Billing Invoice Listing', 'Every bill line raised in the period, with what has been paid.', cols, rows, summary, q=q)


def exceptions(first, last, q=''):
    """Bills that need a second look: discounts, zero prices, hand-typed prices, HMO-declined items."""
    from Billings.models import Invoice
    from IPD.models import AdmissionCharge
    a, b = _range(first, last)
    rows = []
    for inv in (Invoice.objects.filter(created_date__gte=a, created_date__lt=b).filter(Q(discount__gt=0) | Q(price=0))
                .select_related('patient', 'staff')):
        reason = f'Discount {inv.discount}%' if inv.discount else 'Zero price'
        rows.append({'date': _dt(inv.created_date), 'reference': inv.invoice_number or f'INV-{inv.id}', 'where': 'OPD',
                     'name': _name(inv.patient), 'item': inv.product or '', 'amount': int(inv.price or 0),
                     'exception': reason, 'by': _staff(inv.staff), 'detail': ''})
    for c in (AdmissionCharge.objects.filter(posted_at__gte=a, posted_at__lt=b)
              .filter(Q(price_source='manual') | Q(approval_status='declined') | Q(amount=0))
              .select_related('admission', 'admission__patient', 'posted_by', 'approval_by')):
        if c.approval_status == 'declined':
            reason, by, detail = 'HMO declined (patient pays)', _staff(c.approval_by), c.approval_note or ''
        elif c.price_source == 'manual':
            reason, by, detail = 'Price typed by hand', _staff(c.posted_by), c.notes or ''
        else:
            reason, by, detail = 'Zero price', _staff(c.posted_by), c.notes or ''
        rows.append({'date': _dt(c.posted_at), 'reference': c.admission.admission_no or f'#{c.admission_id}', 'where': 'Inpatient',
                     'name': _name(c.admission.patient), 'item': c.description or '', 'amount': int(c.amount or 0),
                     'exception': reason + (' (reversed)' if c.reversed_at else ''), 'by': by, 'detail': detail})
    rows.sort(key=lambda r: r['date'] or '')
    kinds = Counter('Discount' if r['exception'].startswith('Discount') else r['exception'].replace(' (reversed)', '') for r in rows)
    cols = [_col('date', 'Date', 'datetime'), _col('reference', 'Bill / admission'), _col('where', 'Where'), _col('name', 'Patient'),
            _col('item', 'Item'), _col('amount', 'Amount', 'money'), _col('exception', 'Why it is listed', 'badge'),
            _col('by', 'By'), _col('detail', 'Note / reason')]
    return _finish('Exception Bills Report', 'Discounts, zero prices, hand-typed prices and HMO-declined items, for review.',
                   cols, rows, [_sum('Exceptions', len(rows))] + [_sum(k, v) for k, v in kinds.most_common(4)], q=q)


def cancelled(first, last, q=''):
    """Money entries undone in the period, with who did it and why (nothing is deleted in the system)."""
    from IPD.models import AdmissionBill, AdmissionCharge, AdmissionPayment
    a, b = _range(first, last)
    rows = []
    for c in (AdmissionCharge.objects.filter(reversed_at__gte=a, reversed_at__lt=b)
              .select_related('admission', 'admission__patient', 'reversed_by')):
        rows.append({'date': _dt(c.reversed_at), 'kind': 'Charge reversed', 'reference': c.admission.admission_no or '',
                     'name': _name(c.admission.patient), 'description': c.description or '', 'amount': int(c.amount or 0),
                     'reason': c.reverse_reason or '', 'by': _staff(c.reversed_by)})
    for bl in (AdmissionBill.objects.filter(cancelled_at__gte=a, cancelled_at__lt=b)
               .select_related('admission', 'admission__patient', 'cancelled_by')):
        rows.append({'date': _dt(bl.cancelled_at), 'kind': f'{bl.get_kind_display()} cancelled', 'reference': bl.bill_no,
                     'name': _name(bl.admission.patient), 'description': bl.admission.admission_no or '',
                     'amount': int(bl.total or 0), 'reason': bl.cancel_reason or '', 'by': _staff(bl.cancelled_by)})
    for p in (AdmissionPayment.objects.filter(reversed_at__gte=a, reversed_at__lt=b)
              .select_related('admission', 'admission__patient', 'reversed_by')):
        rows.append({'date': _dt(p.reversed_at), 'kind': f'{p.get_kind_display()} reversed', 'reference': p.receipt_number or '',
                     'name': _name(p.admission.patient), 'description': f'{p.method} · {p.admission.admission_no or ""}',
                     'amount': int(p.amount or 0), 'reason': p.reverse_reason or '', 'by': _staff(p.reversed_by)})
    rows.sort(key=lambda r: r['date'] or '')
    cols = [_col('date', 'When', 'datetime'), _col('kind', 'What', 'badge'), _col('reference', 'Reference'), _col('name', 'Patient'),
            _col('description', 'Detail'), _col('amount', 'Amount', 'money'), _col('reason', 'Reason'), _col('by', 'By')]
    note = ('Outpatient bills, receipts and deposits cannot be cancelled or deleted; mistakes are corrected with a '
            'refund, which appears in the Transaction Book.')
    return _finish('Cancelled Bills Report', 'Inpatient charges, bills and payments reversed in the period.', cols, rows,
                   [_sum('Reversals', len(rows)), _sum('Value', sum(r['amount'] for r in rows), 'money')], note, q=q)


def transaction_book(first, last, q=''):
    """Every money movement in the period, oldest first, from all desks."""
    from Billings.models import Deposit, Receipt, Refund
    a, b = _range(first, last)
    rows = []

    def add(when, kind, ref, patient, method, money_in=0, money_out=0, non_cash=0, by=None, detail=''):
        rows.append({'date': _dt(when), 'kind': kind, 'reference': ref or '', 'name': _name(patient),
                     'hospital_number': getattr(patient, 'hospital_number', '') or '', 'method': method or '',
                     'money_in': money_in, 'money_out': money_out, 'non_cash': non_cash, 'by': _staff(by), 'detail': detail})

    for r in Receipt.objects.filter(created_date__gte=a, created_date__lt=b).select_related('patient', 'staff'):
        amt = int(r.total_price or 0)
        kind_low = str(r.payment_type or '').lower()
        if kind_low in ('deposit', 'family deposit'):
            add(r.created_date, 'Bill paid from deposit', r.receipt_number, r.patient, r.payment_type, non_cash=amt, by=r.staff,
                detail=r.invoice_number or '')
        elif 'claim' in kind_low or kind_low in ('capitation', 'credit'):
            add(r.created_date, 'HMO claim', r.receipt_number, r.patient, r.payment_type, non_cash=amt, by=r.staff,
                detail=r.invoice_number or '')
        else:
            add(r.created_date, 'Receipt', r.receipt_number, r.patient, r.payment_type, money_in=amt, by=r.staff,
                detail=r.invoice_number or '')
    for d in Deposit.objects.filter(created_date__gte=a, created_date__lt=b, amount__gt=0).select_related('patient', 'staff', 'family'):
        add(d.created_date, 'Family deposit' if d.family_id else 'Deposit', d.slip_number, d.patient, d.payment_type,
            money_in=int(d.amount), by=d.staff, detail=(d.family.family_name if d.family_id else '') or d.reference)
    for f in Refund.objects.filter(created_date__gte=a, created_date__lt=b).select_related('patient', 'staff'):
        add(f.created_date, 'Deposit refund', f'RF-{f.id}', f.patient, f.payment_type, money_out=int(f.amount or 0), by=f.staff,
            detail=f.reason or '')
    try:
        from IPD.models import AdmissionPayment
        for p in (AdmissionPayment.objects.filter(created_at__gte=a, created_at__lt=b, reversed_at__isnull=True)
                  .select_related('admission', 'admission__patient', 'received_by')):
            amt = int(p.amount or 0)
            add(p.created_at, f'Inpatient {p.get_kind_display().lower()}', p.receipt_number, p.admission.patient, p.method,
                money_in=0 if p.kind == 'refund' else amt, money_out=amt if p.kind == 'refund' else 0, by=p.received_by,
                detail=p.admission.admission_no or '')
    except Exception:
        pass
    rows.sort(key=lambda r: r['date'] or '')
    tin, tout = sum(r['money_in'] for r in rows), sum(r['money_out'] for r in rows)
    cols = [_col('date', 'When', 'datetime'), _col('kind', 'Type', 'badge'), _col('reference', 'Reference'),
            _col('hospital_number', 'Hospital No'), _col('name', 'Patient'), _col('method', 'Method'),
            _col('money_in', 'Money in', 'money'), _col('money_out', 'Money out', 'money'),
            _col('non_cash', 'Not cash', 'money'), _col('by', 'Cashier'), _col('detail', 'Bill / note')]
    summary = [_sum('Money in', tin, 'money'), _sum('Money out', tout, 'money'), _sum('Net', tin - tout, 'money'),
               _sum('Paid from deposits / claims', sum(r['non_cash'] for r in rows), 'money')]
    note = ('"Not cash" rows are bills paid from a deposit (the deposit was counted when it was taken) and HMO claims; '
            'they are listed for completeness and are not added to money in.')
    return _finish('Complete Transaction Book', 'Every money movement at the desks in the period.', cols, rows, summary, note, q=q)


# ------------------------------------------------------------------ inventory
def _stock_rows():
    from inventory.models import StoreStock
    return (StoreStock.objects.filter(store__is_active=True).select_related('store', 'product')
            .exclude(product__merged_into__isnull=False).order_by('store__name', 'product__product_name'))


def stock_analysis(first, last, q=''):
    from inventory.models import StockMovement
    a, b = _range(first, last)
    moves = defaultdict(Counter)
    for m in (StockMovement.objects.filter(created_date__gte=a, created_date__lt=b)
              .values('store_id', 'product_id', 'movement_type').annotate(qty=Sum('quantity'))):
        moves[(m['store_id'], m['product_id'])][m['movement_type']] += abs(int(m['qty'] or 0))
    last_in = {}
    for m in (StockMovement.objects.filter(movement_type__in=('PURCHASE_GRN', 'TRANSFER_IN'))
              .values('store_id', 'product_id').annotate(latest=Max('created_date'))):
        last_in[(m['store_id'], m['product_id'])] = m['latest']
    rows, value = [], 0
    for s in _stock_rows():
        p = s.product
        mv = moves.get((s.store_id, s.product_id), Counter())
        threshold = s.low_stock_threshold or p.low_stock_threshold or 0
        health = 'Out of stock' if s.stock <= 0 else ('Low' if threshold and s.stock <= threshold else 'Adequate')
        price = int(p.price or 0)
        value += price * max(0, s.stock)
        rows.append({
            'store': s.store.name, 'code': p.product_id or '', 'product': p.product_name, 'category': p.category or '',
            'unit': p.minimum_UoM or p.unit or '', 'stock': s.stock, 'reorder': threshold or None,
            'received': mv['PURCHASE_GRN'] + mv['TRANSFER_IN'], 'dispensed': mv['DISPENSE'], 'transferred_out': mv['TRANSFER_OUT'],
            'adjusted': mv['ADJUSTMENT'], 'value': price * max(0, s.stock),
            'expiry': s.expiry_date.isoformat() if s.expiry_date else None, 'last_received': _dt(last_in.get((s.store_id, s.product_id))),
            'health': health,
        })
    cols = [_col('store', 'Store'), _col('code', 'Code'), _col('product', 'Item'), _col('category', 'Category'), _col('unit', 'Unit'),
            _col('stock', 'In stock', 'int'), _col('reorder', 'Reorder level', 'int'), _col('received', 'Received (period)', 'int'),
            _col('dispensed', 'Dispensed (period)', 'int'), _col('transferred_out', 'Sent out (period)', 'int'),
            _col('adjusted', 'Adjusted (period)', 'int'), _col('value', 'Value (product price)', 'money'),
            _col('expiry', 'Expiry', 'date'), _col('last_received', 'Last received', 'datetime'), _col('health', 'Stock health', 'badge')]
    summary = [_sum('Store items', len(rows)), _sum('Out of stock', sum(r['health'] == 'Out of stock' for r in rows)),
               _sum('Low', sum(r['health'] == 'Low' for r in rows)), _sum('Stock value (at product price)', value, 'money')]
    return _finish('Stock Analysis Report', 'Current stock in every store, with movements in the period.', cols, rows, summary, q=q)


def low_stock(first, last, q=''):
    today = timezone.localdate()
    soon = today + timedelta(days=90)
    rows = []
    for s in _stock_rows():
        p = s.product
        threshold = s.low_stock_threshold or p.low_stock_threshold or 0
        issues = []
        if s.stock <= 0:
            issues.append('Out of stock')
        elif threshold and s.stock <= threshold:
            issues.append('Low stock')
        if s.expiry_date and s.stock > 0:
            if s.expiry_date < today:
                issues.append('Expired')
            elif s.expiry_date <= soon:
                issues.append('Expires within 90 days')
        if not issues:
            continue
        rows.append({
            'store': s.store.name, 'code': p.product_id or '', 'product': p.product_name, 'stock': s.stock, 'reorder': threshold or None,
            'batch': s.batch_number or '', 'expiry': s.expiry_date.isoformat() if s.expiry_date else None,
            'days_left': (s.expiry_date - today).days if s.expiry_date else None, 'issue': ' · '.join(issues),
        })
    rows.sort(key=lambda r: (0 if 'Expired' in r['issue'] else 1 if 'Out' in r['issue'] else 2, r['days_left'] if r['days_left'] is not None else 99999))
    cols = [_col('store', 'Store'), _col('code', 'Code'), _col('product', 'Item'), _col('stock', 'In stock', 'int'),
            _col('reorder', 'Reorder level', 'int'), _col('batch', 'Batch'), _col('expiry', 'Expiry', 'date'),
            _col('days_left', 'Days to expiry', 'int'), _col('issue', 'Issue', 'badge')]
    summary = [_sum('Need attention', len(rows)), _sum('Expired', sum('Expired' in r['issue'] for r in rows)),
               _sum('Out of stock', sum('Out of stock' in r['issue'] for r in rows)),
               _sum('Expiring ≤ 90 days', sum('within 90' in r['issue'] for r in rows))]
    return _finish('Low Stock & Short-Dated', 'Items out of stock, at or below reorder level, expired or expiring within 90 days '
                   '(as of today; the date range does not apply).', cols, rows, summary, q=q)


def requisitions(first, last, q=''):
    from inventory.models import StockRequisition
    a, b = _range(first, last)
    qs = (StockRequisition.objects.filter(created_date__gte=a, created_date__lt=b)
          .select_related('requesting_store', 'fulfilling_store', 'requested_by', 'approved_by')
          .prefetch_related('items__product').order_by('created_date', 'id'))
    rows, st = [], Counter()
    for r in qs:
        st[r.get_status_display() if hasattr(r, 'get_status_display') else r.status] += 1
        for it in r.items.all():
            rows.append({
                'number': r.requisition_number, 'date': _dt(r.created_date),
                'from_store': getattr(r.requesting_store, 'name', ''), 'to_store': getattr(r.fulfilling_store, 'name', ''),
                'product': getattr(it.product, 'product_name', ''), 'requested': it.quantity_requested,
                'approved': it.quantity_approved, 'priority': r.priority or '',
                'status': r.get_status_display() if hasattr(r, 'get_status_display') else r.status,
                'requested_by': _staff(r.requested_by), 'approved_by': _staff(r.approved_by),
            })
    cols = [_col('number', 'Requisition'), _col('date', 'Date', 'datetime'), _col('from_store', 'Requested by store'),
            _col('to_store', 'Supplied by'), _col('product', 'Item'), _col('requested', 'Qty requested', 'int'),
            _col('approved', 'Qty approved', 'int'), _col('priority', 'Priority'), _col('status', 'Status', 'badge'),
            _col('requested_by', 'Requested by'), _col('approved_by', 'Approved by')]
    summary = [_sum('Requisitions', len(qs)), _sum('Item lines', len(rows))] + [_sum(k, v) for k, v in st.most_common(3)]
    return _finish('Requisitions Detail', 'Stock requisitions raised in the period, one row per item.', cols, rows, summary, q=q)


def vendors(first, last, q=''):
    from inventory.models import Expense
    a, b = _range(first, last)
    rows, t = [], Counter()
    for e in Expense.objects.filter(created_date__gte=a, created_date__lt=b).select_related('staff').order_by('created_date', 'id'):
        total, paid = int(e.total_cost or 0), int(e.payment or 0)
        t['total'] += total
        t['paid'] += paid
        t['due'] += int(e.due or 0)
        rows.append({'date': _dt(e.created_date), 'vendor': e.vendor_name or '', 'product': e.product_name or '',
                     'quantity': e.quantity, 'unit': e.minimum_UoM or '', 'unit_price': int(e.unit_price or 0),
                     'total': total, 'paid': paid, 'due': int(e.due or 0), 'by': _staff(e.staff)})
    cols = [_col('date', 'Date', 'datetime'), _col('vendor', 'Vendor'), _col('product', 'Item'), _col('quantity', 'Qty', 'int'),
            _col('unit', 'Unit'), _col('unit_price', 'Unit price', 'money'), _col('total', 'Total cost', 'money'),
            _col('paid', 'Paid', 'money'), _col('due', 'Still owed to vendor', 'money'), _col('by', 'Recorded by')]
    summary = [_sum('Purchases', len(rows)), _sum('Total cost', t['total'], 'money'), _sum('Paid', t['paid'], 'money'),
               _sum('Owed to vendors', t['due'], 'money')]
    return _finish('Vendors & Expenses', 'Purchases recorded against vendors in the period.', cols, rows, summary, q=q)


# ------------------------------------------------------------------ record changes (audit)
_MODEL_LABELS = {
    'patients.PatientProfile': 'Patient details', 'patients.PatientAppointment': 'Appointment',
    'queue_operations.NurseWaitingList': 'Nurse queue', 'ANC.ANCRegistration': 'ANC registration',
    'radio_lab.RadiologyLab': 'Lab / radiology order', 'queue_operations.ImmunizationRecord': 'Vaccine entry',
}
# Fields that are noise in an audit view (timestamps the system sets itself).
_SKIP_FIELDS = {'updated_at', 'updated_date', 'modified', 'last_modified'}


def record_changes(first, last, q=''):
    """Who changed or removed which patient record, when, why, and what the values were."""
    from patients.models import ClinicalRecordHistory
    a, b = _range(first, last)
    qs = (ClinicalRecordHistory.objects.filter(changed_at__gte=a, changed_at__lt=b)
          .select_related('patient', 'changed_by').order_by('-changed_at', '-id'))
    rows = []
    for h in qs[:MAX_ROWS + 1]:
        if h.action == 'delete':
            what = 'Removed: ' + ', '.join(f'{k}={v}' for k, v in (h.snapshot or {}).items()
                                           if k in ('vaccine_name', 'dose_stage', 'administered_date', 'item', 'purpose') and v)
        else:
            parts = [f'{k}: {old if old not in (None, "") else "—"} → {new if new not in (None, "") else "—"}'
                     for k, (old, new) in (h.changes or {}).items() if k not in _SKIP_FIELDS]
            what = '; '.join(parts)
        rows.append({
            'when': _dt(h.changed_at), 'record': _MODEL_LABELS.get(h.model, h.model), 'record_id': h.object_id,
            'hospital_number': getattr(h.patient, 'hospital_number', '') or '', 'name': _name(h.patient),
            'action': h.get_action_display(), 'changes': what[:500], 'reason': h.reason or '',
            'by': _staff(h.changed_by), 'ip': h.ip_address,
        })
    kinds = Counter(r['record'] for r in rows)
    cols = [_col('when', 'When', 'datetime'), _col('record', 'Record'), _col('record_id', 'Record #'),
            _col('hospital_number', 'Hospital No'), _col('name', 'Patient'), _col('action', 'Action', 'badge'),
            _col('changes', 'What changed (before → after)'), _col('reason', 'Reason'), _col('by', 'Changed by'),
            _col('ip', 'From (IP)')]
    note = ('Signed consultation notes, prescriptions and vital signs cannot be changed at all, so they never appear '
            'here; bills and receipts cannot be changed either (see Billing reports).')
    return _finish('Record Changes', 'Every change to, or removal of, a patient record in the period.', cols, rows,
                   [_sum('Changes', len(rows))] + [_sum(k, v) for k, v in kinds.most_common(4)], note, q=q)


# ------------------------------------------------------------------ registry
# key: (category, function, modules that may see it besides 'reporting')
REPORTS = {
    'patients_reg': ('ambulatory', patients_registration, ('fd_registration', 'fd_records')),
    'visits': ('ambulatory', visits, ('fd_appointments', 'clinical', 'nursing')),
    'admissions': ('ambulatory', admissions, ('inpatient',)),
    'deactivated': ('ambulatory', deactivated, ('fd_records',)),
    'record_changes': ('ambulatory', record_changes, ()),          # Reporting module / admins only
    'invoices': ('billing', invoices, ('billings', 'fd_billing')),
    'exceptions': ('billing', exceptions, ('billings', 'fd_billing')),
    'cancelled': ('billing', cancelled, ('billings', 'fd_billing')),
    'transaction_book': ('billing', transaction_book, ('billings', 'fd_billing')),
    'stock_analysis': ('inventory', stock_analysis, ('inventory',)),
    'low_stock': ('inventory', low_stock, ('inventory', 'ipd_pharmacy', 'opd_pharmacy')),
    'requisitions': ('inventory', requisitions, ('inventory', 'ipd_pharmacy', 'opd_pharmacy')),
    'vendors': ('inventory', vendors, ('inventory',)),
    'appointments': ('others', appointments, ('fd_appointments',)),
}


def summary_tiles(first, last):
    """The four tiles at the top of the Reporting page."""
    from patients.models import PatientProfile
    from Billings.models import Invoice
    a, b = _range(first, last)
    reg = PatientProfile.objects.filter(created_date__gte=a, created_date__lt=b).count()
    billed = int(Invoice.objects.filter(created_date__gte=a, created_date__lt=b).aggregate(s=Sum('price'))['s'] or 0)
    attention = 0
    today = timezone.localdate()
    for s in _stock_rows():
        threshold = s.low_stock_threshold or s.product.low_stock_threshold or 0
        if s.stock <= 0 or (threshold and s.stock <= threshold) or (s.expiry_date and s.stock > 0 and s.expiry_date <= today + timedelta(days=90)):
            attention += 1
    return {'registrations': reg, 'invoiced': billed, 'stock_attention': attention}
