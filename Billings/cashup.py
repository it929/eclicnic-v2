"""
End-of-day cash-up: what money actually came in and went out at the desks, by payment method and
by cashier, so the drawer, the POS terminal and the bank can be reconciled.

Money IN   = OPD receipts paid by cash/POS/transfer/... (not those paid from a deposit)
           + deposits taken (own and family)
           + inpatient deposits and payments (IPD admission account), not reversed
Money OUT  = deposit refunds (OPD) + inpatient refunds, not reversed
Net        = in - out, per method. "Cash" net is what should be in the cash drawer.

Shown for information, NOT counted as money in (it was counted when it came in, or is not cash):
  - bills paid from a deposit (own or family): the deposit was counted the day it was taken;
  - HMO claim "receipts": the HMO pays later.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import Deposit, Receipt, Refund

DEPOSIT_PAID = {'deposit', 'family deposit'}
METHOD_ORDER = ['Cash', 'POS', 'Transfer', 'Cheque', 'Bank Deposit', 'Others']


def _day_range(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def _norm_method(value):
    v = str(value or '').strip()
    low = v.lower()
    for m in METHOD_ORDER:
        if low == m.lower():
            return m
    if low in ('pos / card', 'card', 'debit card'):
        return 'POS'
    if low in ('bank transfer',):
        return 'Transfer'
    return v or 'Others'


def _staff_name(u):
    return (getattr(u, 'fullname', '') or getattr(u, 'username', '')) if u else 'Unknown'


def cash_up(day, staff_id=None, end_day=None):
    """One day, or a range of days (day .. end_day inclusive) for reports."""
    start, _ = _day_range(day)
    _, end = _day_range(end_day or day)
    by_method = defaultdict(lambda: {'opd_receipts': 0, 'deposits_taken': 0, 'ipd_in': 0, 'refunds_out': 0})
    by_staff = defaultdict(lambda: {'name': '', 'money_in': 0, 'money_out': 0, 'count': 0})
    info = {'paid_from_own_deposit': 0, 'paid_from_family_deposit': 0, 'hmo_claims': 0, 'ipd_reversed': 0}
    counts = {'receipts': 0, 'deposits': 0, 'refunds': 0, 'ipd_payments': 0}

    def staff_row(user_id, user):
        row = by_staff[user_id or 0]
        row['name'] = row['name'] or _staff_name(user)
        return row

    # OPD receipts
    rq = Receipt.objects.filter(created_date__gte=start, created_date__lt=end).select_related('staff')
    if staff_id:
        rq = rq.filter(staff_id=staff_id)
    for r in rq:
        amt = int(r.total_price or 0)
        kind = str(r.payment_type or '').strip().lower()
        if kind == 'deposit':
            info['paid_from_own_deposit'] += amt
        elif kind == 'family deposit':
            info['paid_from_family_deposit'] += amt
        elif 'claim' in kind or kind in ('capitation', 'credit'):
            info['hmo_claims'] += amt
        else:
            by_method[_norm_method(r.payment_type)]['opd_receipts'] += amt
            s = staff_row(r.staff_id, r.staff)
            s['money_in'] += amt
            s['count'] += 1
            counts['receipts'] += 1

    # Deposits taken (positive rows only; withdrawals/refunds are negative rows)
    dq = Deposit.objects.filter(created_date__gte=start, created_date__lt=end, amount__gt=0).select_related('staff')
    if staff_id:
        dq = dq.filter(staff_id=staff_id)
    for d in dq:
        amt = int(d.amount or 0)
        by_method[_norm_method(d.payment_type)]['deposits_taken'] += amt
        s = staff_row(d.staff_id, d.staff)
        s['money_in'] += amt
        s['count'] += 1
        counts['deposits'] += 1

    # Deposit refunds paid out
    fq = Refund.objects.filter(created_date__gte=start, created_date__lt=end).select_related('staff')
    if staff_id:
        fq = fq.filter(staff_id=staff_id)
    for f in fq:
        amt = int(f.amount or 0)
        by_method[_norm_method(f.payment_type)]['refunds_out'] += amt
        s = staff_row(f.staff_id, f.staff)
        s['money_out'] += amt
        s['count'] += 1
        counts['refunds'] += 1

    # Inpatient account payments (taken at the IPD / billing desk)
    try:
        from IPD.models import AdmissionPayment
        pq = AdmissionPayment.objects.filter(created_at__gte=start, created_at__lt=end).select_related('received_by')
        if staff_id:
            pq = pq.filter(received_by_id=staff_id)
        for p in pq:
            amt = int(p.amount or 0)
            if p.reversed_at:
                info['ipd_reversed'] += amt
                continue
            m = by_method[_norm_method(p.method)]
            s = staff_row(p.received_by_id, p.received_by)
            if p.kind == 'refund':
                m['refunds_out'] += amt
                s['money_out'] += amt
            else:
                m['ipd_in'] += amt
                s['money_in'] += amt
            s['count'] += 1
            counts['ipd_payments'] += 1
    except Exception:  # IPD app missing in some installs: cash-up still works for OPD
        import logging
        logging.getLogger(__name__).exception('Cash-up: inpatient payments could not be read')

    methods = []
    for name in METHOD_ORDER + sorted(k for k in by_method if k not in METHOD_ORDER):
        if name not in by_method:
            continue
        v = by_method[name]
        money_in = v['opd_receipts'] + v['deposits_taken'] + v['ipd_in']
        methods.append({'method': name, **v, 'money_in': money_in, 'net': money_in - v['refunds_out']})
    totals = {k: sum(m[k] for m in methods) for k in ('opd_receipts', 'deposits_taken', 'ipd_in', 'refunds_out', 'money_in', 'net')}
    cash = next((m for m in methods if m['method'] == 'Cash'), None)
    cashiers = sorted(({'staff_id': k or None, **v, 'net': v['money_in'] - v['money_out']} for k, v in by_staff.items()),
                      key=lambda r: -r['money_in'])
    return {
        'date': day.isoformat(),
        'date_from': day.isoformat(),
        'date_to': (end_day or day).isoformat(),
        'staff_id': staff_id,
        'methods': methods,
        'totals': totals,
        'cash_in_drawer': cash['net'] if cash else 0,
        'cashiers': cashiers,
        'info': info,
        'counts': counts,
        'generated_at': timezone.localtime().isoformat(),
    }
