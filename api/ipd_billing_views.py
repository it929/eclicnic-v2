"""
Inpatient billing API (rules in IPD/billing_services.py).

    GET   ipd/billing/accounts/?bucket=&search=&ward=   every account with totals (the Inpatient Billing page)
    GET   ipd/admissions/<id>/account/              accrues bed-days, then: totals, charges, payments, bills, clearance
    GET   ipd/admissions/<id>/billable/?type=drug|service&q=&store=   priced search
    POST  ipd/admissions/<id>/charges/              {kind: service|drug|other, ..., pin}
    POST  ipd/charges/<id>/reverse/                 {reason, pin}                (Billings Unit / admin)
    POST  ipd/charges/<id>/payer/                   {payer, pin}                 (Billings Unit / admin)
    POST  ipd/charges/<id>/decline/                 {reason, pin}   HMO does not cover it: General price, patient pays
    POST  ipd/admissions/<id>/approvals/            {charge_ids, pa_code, for_admission, note, pin}   HMO approval
    POST  ipd/admissions/<id>/payments/             {kind, amount, method, reference, pin}   (Billings Unit / admin)
    POST  ipd/payments/<id>/reverse/                {reason, pin}                (admin)
    POST  ipd/admissions/<id>/bills/                {kind: interim|final, pin}   (final: Billings Unit / admin)
    POST  ipd/bills/<id>/cancel/                    {reason, pin}                (Billings Unit / admin)
    POST  ipd/admissions/<id>/clear/                {pin, credit_reason?}        (Billings Unit / admin; credit: admin)
    POST  ipd/admissions/<id>/change-type/          {admission_type, pin}
    GET   ipd/wards/<id>/tariffs/  POST {sponsor?, plan?, rate}   DELETE ipd/ward-tariffs/<id>/   (admin)
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Count, DecimalField, Exists, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from IPD import billing_services as bs
from IPD.models import (
    ADMISSION_TYPES, CHARGE_KINDS, PAYMENT_METHODS, AdmissionBill, AdmissionCharge, AdmissionPayment, MedicationSupply, Ward,
    WardTariff,
)
from IPD.services import AdmissionError, staff_name
from inventory.permissions import is_admin

from .ipd_views import _admission_qs, _dt, _err, _pin_user, admission_row

BILLING_DEPTS = ('billings unit', 'billing', 'accounts', 'finance')
KIND_LABELS = dict(CHARGE_KINDS)
SOURCE_LABELS = {'plan': 'Plan price', 'sponsor': 'Sponsor price', 'general': 'General price', 'manual': 'Manual price'}
DISPENSING_STORES = ('ipd_pharmacy', 'ward_pharmacy', 'emergency_pharmacy')


class _Auth(APIView):
    permission_classes = [permissions.IsAuthenticated]


def is_billing(user):
    dept = str(getattr(getattr(user, 'department', None), 'department', '') or '').strip().lower()
    return is_admin(user) or dept in BILLING_DEPTS


def _deny(msg):
    return Response({'error': msg, 'code': 'not_allowed'}, status=403)


def _f(v):
    return float(v) if v is not None else None


def charge_row(c):
    return {
        'id': c.id, 'kind': c.kind, 'kind_label': KIND_LABELS.get(c.kind), 'description': c.description, 'code': c.code,
        'service_date': c.service_date.isoformat(), 'qty': c.qty, 'unit_price': _f(c.unit_price), 'amount': _f(c.amount),
        'price_source': c.price_source, 'price_source_label': SOURCE_LABELS.get(c.price_source, c.price_source),
        'payer': c.payer, 'ward_name': getattr(c.ward, 'ward_name', None), 'store_name': getattr(c.store, 'name', None),
        'notes': c.notes, 'posted_by': staff_name(c.posted_by), 'posted_at': _dt(c.posted_at),
        'awaiting_pharmacy': any(x.status == 'pending' for x in c.supplies.all()),
        'urgent': c.urgent, 'is_request': bool(c.radiolab_id),
        'approval': {'status': c.approval_status, 'label': c.get_approval_status_display() if c.approval_status else '',
                     'pa_code': c.pa_code, 'note': c.approval_note, 'by': staff_name(c.approval_by),
                     'at': _dt(c.approval_at)} if c.approval_status else None,
        'reversed': {'at': _dt(c.reversed_at), 'by': staff_name(c.reversed_by), 'reason': c.reverse_reason}
        if c.reversed_at else None,
    }


def payment_row(p):
    return {
        'id': p.id, 'kind': p.kind, 'kind_label': p.get_kind_display(), 'amount': _f(p.amount), 'method': p.method,
        'reference': p.reference, 'receipt_number': p.receipt_number, 'received_by': staff_name(p.received_by),
        'at': _dt(p.created_at),
        'reversed': {'at': _dt(p.reversed_at), 'by': staff_name(p.reversed_by), 'reason': p.reverse_reason}
        if p.reversed_at else None,
    }


def bill_row(b):
    return {
        'id': b.id, 'bill_no': b.bill_no, 'kind': b.kind, 'kind_label': b.get_kind_display(), 'status': b.status,
        'total': _f(b.total), 'sponsor_total': _f(b.sponsor_total), 'patient_total': _f(b.patient_total),
        'paid_total': _f(b.paid_total), 'balance': _f(b.balance), 'created_by': staff_name(b.created_by),
        'at': _dt(b.created_at), 'cancelled_at': _dt(b.cancelled_at), 'cancel_reason': b.cancel_reason,
    }


def _stores(adm):
    from inventory.models import PharmacyStore
    stores = list(PharmacyStore.objects.filter(is_active=True, store_type__in=DISPENSING_STORES).order_by('name'))
    ward_store = getattr(adm.ward, 'pharmacy_store', None)
    if ward_store and ward_store not in stores:
        stores.insert(0, ward_store)
    return [{'id': s.id, 'name': s.name, 'is_ward_store': bool(ward_store and s.id == ward_store.id)} for s in stores]


def _adm(pk):
    return get_object_or_404(_admission_qs().select_related('sponsor__category', 'ward__pharmacy_store'), pk=pk)


class AccountView(_Auth):
    def get(self, request, pk):
        adm = _adm(pk)
        warnings = []
        if adm.is_open:
            _, warnings = bs.accrue_bed_days(adm)
        adm = _adm(pk)
        charges = list(adm.charges.select_related('posted_by', 'reversed_by', 'ward', 'store', 'approval_by')
                       .prefetch_related('supplies'))
        payments = list(adm.payments.select_related('received_by', 'reversed_by'))
        bills = list(adm.bills.select_related('created_by'))
        totals = bs.account_totals(adm)
        final = next((b for b in bills if b.kind == 'final' and b.status == 'active'), None)
        prof = bs.payer_profile(adm)
        user = request.user
        return Response({
            'admission': admission_row(adm),
            'totals': dict({k: _f(v) for k, v in totals.items() if k not in ('by_kind', 'lines')},
                           by_kind={k: _f(v) for k, v in totals['by_kind'].items()}, lines=totals['lines']),
            'charges': [charge_row(c) for c in charges],
            'payments': [payment_row(p) for p in payments],
            'bills': [bill_row(b) for b in bills],
            'final_bill': bill_row(final) if final else None,
            'frozen': bool(final),
            'clearance': {
                'cleared': bool(adm.bill_cleared_at), 'at': _dt(adm.bill_cleared_at), 'by': staff_name(adm.bill_cleared_by),
                'type': adm.clearance_type, 'note': adm.clearance_note,
            },
            'payer': {'sponsor': getattr(prof.sponsor, 'name', None), 'plan': getattr(prof.plan, 'plan', None),
                      'is_hmo': bs.is_hmo(prof.sponsor)},
            'warnings': warnings,
            'hmo': {
                'pa_code': adm.pa_code,
                'pending': sum(1 for c in charges if not c.reversed_at and c.approval_status == 'pending'),
                'pending_amount': _f(sum((c.amount for c in charges if not c.reversed_at and c.approval_status == 'pending'),
                                         Decimal('0'))),
                'approved_amount': _f(sum((c.amount for c in charges if not c.reversed_at and c.approval_status == 'approved'),
                                          Decimal('0'))),
            },
            'stores': _stores(adm),
            'payment_methods': [{'value': v, 'label': l} for v, l in PAYMENT_METHODS],
            'admission_types': [{'value': v, 'label': l} for v, l in ADMISSION_TYPES],
            'can': {'billing': is_billing(user), 'admin': is_admin(user)},
            'patient_extra': {'address': getattr(adm.patient, 'address', '') or '',
                              'policy': getattr(adm.patient, 'insurance_policy_number', '') or ''},
            'now': _dt(timezone.now()),
        })


def _sum_sub(model, value_filter=None, **extra):
    """Correlated SUM(amount) per admission, so several sums don't multiply each other through joins."""
    qs = model.objects.filter(admission=OuterRef('pk'), reversed_at__isnull=True, **extra)
    if value_filter is not None:
        qs = qs.filter(value_filter)
    money_f = DecimalField(max_digits=14, decimal_places=2)
    return Coalesce(Subquery(qs.order_by().values('admission').annotate(s=Sum('amount')).values('s')[:1],
                             output_field=money_f), Value(Decimal('0')), output_field=money_f)


def _with_money(qs):
    return qs.annotate(
        m_total=_sum_sub(AdmissionCharge), m_sponsor=_sum_sub(AdmissionCharge, payer='sponsor'),
        m_received=_sum_sub(AdmissionPayment, ~Q(kind='refund')), m_refunded=_sum_sub(AdmissionPayment, kind='refund'),
        m_lines=Coalesce(Subquery(AdmissionCharge.objects.filter(admission=OuterRef('pk'), reversed_at__isnull=True)
                                  .order_by().values('admission').annotate(n=Count('id')).values('n')[:1]), Value(0)),
        m_pending=Coalesce(Subquery(MedicationSupply.objects.filter(admission=OuterRef('pk'), status='pending')
                                    .order_by().values('admission').annotate(n=Count('id')).values('n')[:1]), Value(0)),
        m_final=Exists(AdmissionBill.objects.filter(admission=OuterRef('pk'), kind='final', status='active')),
        m_approvals=Coalesce(Subquery(AdmissionCharge.objects.filter(admission=OuterRef('pk'), reversed_at__isnull=True,
                                                                     approval_status='pending')
                                      .order_by().values('admission').annotate(n=Count('id')).values('n')[:1]), Value(0)),
    )


def _money_of(a):
    patient = a.m_total - a.m_sponsor
    paid = a.m_received - a.m_refunded
    return {'total': _f(a.m_total), 'sponsor_total': _f(a.m_sponsor), 'patient_total': _f(patient), 'paid': _f(paid),
            'balance': _f(patient - paid), 'lines': a.m_lines, 'pending_supplies': a.m_pending, 'final_bill': a.m_final,
            'pending_approvals': a.m_approvals}


ACCOUNT_BUCKETS = {
    'open': Q(status__in=('awaiting_bed', 'in_ward', 'discharge_ordered')),
    'in_ward': Q(status__in=('awaiting_bed', 'in_ward')),
    'awaiting_clearance': Q(status='discharge_ordered', bill_cleared_at__isnull=True),
    'cleared': Q(status='discharge_ordered', bill_cleared_at__isnull=False),
    'discharged': Q(status='discharged'),
    'all': Q(),
}


class AccountListView(_Auth):
    """GET ipd/billing/accounts/?bucket=open|in_ward|awaiting_clearance|cleared|discharged|all&search=&ward=&from=&to=
    Every admission's running account with its totals. Bed-days are brought up to date when a bill is opened."""

    def get(self, request):
        from .ipd_views import _parse_date
        qp = request.query_params
        bucket = (qp.get('bucket') or 'open').strip()
        if bucket not in ACCOUNT_BUCKETS:
            return Response({'error': f"Unknown list '{bucket}'."}, status=400)
        base = _admission_qs().exclude(status='cancelled')
        ward = qp.get('ward')
        if ward:
            base = base.filter(ward_id=ward)
        search = (qp.get('search') or '').strip()
        if search:
            base = base.filter(Q(patient__surname__icontains=search) | Q(patient__first_name__icontains=search)
                               | Q(patient__other_name__icontains=search) | Q(patient__hospital_number__icontains=search)
                               | Q(admission_no__icontains=search) | Q(patient__phone_number__icontains=search))
        counts = {k: base.filter(q).count() for k, q in ACCOUNT_BUCKETS.items() if k != 'all'}
        qs = base.filter(ACCOUNT_BUCKETS[bucket])
        if bucket in ('discharged', 'all'):
            d_from, d_to = _parse_date(qp.get('from')), _parse_date(qp.get('to'))
            if d_from:
                qs = qs.filter(discharged_at__date__gte=d_from)
            if d_to:
                qs = qs.filter(discharged_at__date__lte=d_to)
        rows = []
        for a in _with_money(qs).order_by('-doctor_admit_date')[:500]:
            rows.append(dict(admission_row(a), account=_money_of(a)))

        # Headline figures cover every open account (not just the current list).
        owing = sponsor = Decimal('0')
        owing_n = 0
        for a in _with_money(base.filter(ACCOUNT_BUCKETS['open'])):
            bal = (a.m_total - a.m_sponsor) - (a.m_received - a.m_refunded)
            if bal > 0:
                owing += bal
                owing_n += 1
            sponsor += a.m_sponsor
        return Response({'results': rows, 'counts': counts, 'bucket': bucket,
                         'summary': {'owing': _f(owing), 'owing_accounts': owing_n, 'sponsor_open': _f(sponsor)},
                         'can': {'billing': is_billing(request.user), 'admin': is_admin(request.user)}})


class BillableSearchView(_Auth):
    def get(self, request, pk):
        from api.pricing import quote
        adm = _adm(pk)
        prof = bs.payer_profile(adm)
        q = (request.query_params.get('q') or '').strip()
        kind = request.query_params.get('type') or 'service'
        if len(q) < 2:
            return Response({'results': []})
        out = []
        if kind == 'drug':
            from inventory import stock_service
            from inventory.models import PharmacyStore, StoreStock
            store = PharmacyStore.objects.filter(pk=request.query_params.get('store')).first()
            if not store:
                return Response({'error': 'Choose the pharmacy that is issuing.', 'code': 'store_required'}, status=400)
            rows = (StoreStock.objects.filter(store=store, stock__gt=0, product__merged_into__isnull=True)
                    .filter(Q(product__product_name__icontains=q) | Q(product__product_id__iexact=q))
                    .select_related('product').order_by('product__product_name')[:15])
            for r in rows:
                p = r.product
                qt = quote(prof, 'drug', code=p.product_id, name=p.product_name)
                out.append({'product_id': p.id, 'code': p.product_id, 'name': p.product_name,
                            'available': stock_service.availability(store, p)['usable'],
                            'rate': _f(qt.rate) if qt else None,
                            'price_source': SOURCE_LABELS.get(qt.source) if qt else None,
                            'payer': bs._payer(adm, qt.source) if qt else None})
        else:
            from myAdmins.models import OtherService2
            seen = set()
            for s in OtherService2.objects.filter(service__icontains=q).order_by('service')[:80]:
                key = (s.service_id or s.service).lower()
                if key in seen:
                    continue
                seen.add(key)
                qt = quote(prof, 'service', code=s.service_id, name=s.service)
                out.append({'code': s.service_id, 'name': s.service, 'rate': _f(qt.rate) if qt else None,
                            'price_source': SOURCE_LABELS.get(qt.source) if qt else None,
                            'payer': bs._payer(adm, qt.source) if qt else None})
                if len(out) >= 15:
                    break
        return Response({'results': out})


class ChargesView(_Auth):
    def post(self, request, pk):
        from api.views import _pin_store_staff
        from inventory.models import PharmacyStore, Product
        adm = _adm(pk)
        d = request.data
        kind = d.get('kind')
        try:
            if kind == 'drug':
                store = PharmacyStore.objects.filter(pk=d.get('store'), is_active=True).first()
                product = Product.objects.filter(pk=d.get('product')).first()
                if not store or not product:
                    return Response({'error': 'Choose the pharmacy and the drug.', 'code': 'required'}, status=400)
                user, err = _pin_store_staff(request, store, 'issue this drug to the patient')
                if err:
                    return err
                c = bs.post_drug(adm, by=user, store=store, product=product, qty=d.get('qty'), notes=d.get('notes'))
            elif kind == 'service':
                if not (d.get('name') or '').strip():
                    return Response({'error': 'Choose the service.', 'code': 'required'}, status=400)
                user, err = _pin_user(request, 'post this charge')
                if err:
                    return err
                c = bs.post_service(adm, by=user, name=d.get('name'), code=d.get('code'), qty=d.get('qty') or 1,
                                    notes=d.get('notes'))
            elif kind == 'other':
                user, err = _pin_user(request, 'post a manual charge')
                if err:
                    return err
                if not is_billing(user):
                    return _deny('Only the Billings Unit or an administrator can post a manual charge.')
                c = bs.post_manual(adm, by=user, description=d.get('description'), unit_price=d.get('unit_price'),
                                   qty=d.get('qty') or 1, payer=d.get('payer') or 'patient', notes=d.get('notes'))
            else:
                return Response({'error': 'Unknown charge type.', 'code': 'kind'}, status=400)
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': f'{c.description} x{c.qty}: ₦{c.amount:,.2f} charged.', 'charge': charge_row(c)}, status=201)


class ChargeActionView(_Auth):
    def post(self, request, pk, action):
        if action not in ('reverse', 'payer', 'decline'):
            return Response({'error': 'Unknown action.'}, status=404)
        c = get_object_or_404(AdmissionCharge.objects.select_related('admission', 'store', 'product'), pk=pk)
        user, err = _pin_user(request, 'change this charge')
        if err:
            return err
        if not is_billing(user):
            return _deny('Only the Billings Unit or an administrator can change charges.')
        try:
            if action == 'reverse':
                bs.reverse_charge(c, by=user, reason=request.data.get('reason'))
                return Response({'detail': 'Charge reversed.'})
            if action == 'decline':
                c = bs.decline_charge(c, by=user, reason=request.data.get('reason'))
                return Response({'detail': f'{c.description}: not covered. The patient pays ₦{c.amount:,.2f}'
                                           f'{" (General price)" if c.price_source == "general" else ""}.'})
            bs.set_payer(c, by=user, payer=request.data.get('payer'))
            return Response({'detail': 'Payer changed.'})
        except AdmissionError as e:
            return _err(e)


class ApprovalsView(_Auth):
    def post(self, request, pk):
        adm = _adm(pk)
        user, err = _pin_user(request, 'record the HMO approval')
        if err:
            return err
        if not is_billing(user):
            return _deny('Only the Billings Unit or an administrator can record HMO approvals.')
        d = request.data
        ids = d.get('charge_ids') or []
        if not isinstance(ids, list):
            ids = [ids]
        try:
            n = bs.approve_charges(adm, by=user, charge_ids=ids, pa_code=d.get('pa_code'),
                                   for_admission=bool(d.get('for_admission')), note=d.get('note') or '')
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': f'HMO approval recorded on {n} line{"s" if n != 1 else ""}.', 'approved': n})


class PaymentsView(_Auth):
    def post(self, request, pk):
        adm = _adm(pk)
        d = request.data
        user, err = _pin_user(request, 'receive this payment')
        if err:
            return err
        if not is_billing(user):
            return _deny('Payments are taken by the Billings Unit.')
        try:
            p = bs.record_payment(adm, by=user, amount=d.get('amount'), method=d.get('method') or 'Cash',
                                  kind=d.get('kind') or 'deposit', reference=d.get('reference'))
        except AdmissionError as e:
            return _err(e)
        msg = f'{p.get_kind_display()} of ₦{p.amount:,.2f} recorded' + (f' · receipt {p.receipt_number}' if p.receipt_number else '') + '.'
        return Response({'detail': msg, 'payment': payment_row(p)}, status=201)


class PaymentReverseView(_Auth):
    def post(self, request, pk):
        p = get_object_or_404(AdmissionPayment.objects.select_related('admission'), pk=pk)
        user, err = _pin_user(request, 'reverse this payment')
        if err:
            return err
        if not is_admin(user):
            return _deny('Only an administrator can reverse a payment.')
        try:
            bs.reverse_payment(p, by=user, reason=request.data.get('reason'))
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': 'Payment reversed.'})


class BillsView(_Auth):
    def post(self, request, pk):
        adm = _adm(pk)
        kind = request.data.get('kind') or 'interim'
        user, err = _pin_user(request, 'generate this bill')
        if err:
            return err
        if kind == 'final' and not is_billing(user):
            return _deny('The final bill is generated by the Billings Unit.')
        try:
            b = bs.generate_bill(adm, by=user, kind=kind)
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': f'{b.get_kind_display()} {b.bill_no} generated.', 'bill': bill_row(b)}, status=201)


class BillCancelView(_Auth):
    def post(self, request, pk):
        b = get_object_or_404(AdmissionBill.objects.select_related('admission'), pk=pk)
        user, err = _pin_user(request, 'cancel this bill')
        if err:
            return err
        if not is_billing(user):
            return _deny('Only the Billings Unit or an administrator can cancel a final bill.')
        try:
            bs.cancel_final_bill(b, by=user, reason=request.data.get('reason'))
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': f'{b.bill_no} cancelled; the account is open again.'})


class ClearView(_Auth):
    def post(self, request, pk):
        adm = _adm(pk)
        user, err = _pin_user(request, 'clear this bill')
        if err:
            return err
        if not is_billing(user):
            return _deny('Bill clearance is done by the Billings Unit.')
        try:
            bs.clear_for_discharge(adm, by=user, credit_reason=request.data.get('credit_reason') or '',
                                   allow_credit=bool(request.data.get('credit_reason')) and is_admin(user))
        except AdmissionError as e:
            if e.code == 'balance_owing' and request.data.get('credit_reason') and not is_admin(user):
                return _deny('Only an administrator can release a patient who still owes money.')
            return _err(e)
        return Response({'detail': 'Bill cleared. The ward can now release the patient.'})


class ChangeTypeView(_Auth):
    def post(self, request, pk):
        adm = _adm(pk)
        user, err = _pin_user(request, 'change the admission type')
        if err:
            return err
        try:
            bs.change_admission_type(adm, by=user, admission_type=request.data.get('admission_type'))
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': 'Admission type changed.'})


# ---------------------------------------------------------------------------------------------
# Ward bed-day prices (admin)
# ---------------------------------------------------------------------------------------------
def tariff_row(t):
    return {'id': t.id, 'sponsor': t.sponsor_id, 'sponsor_name': getattr(t.sponsor, 'name', None),
            'plan': t.plan_id, 'plan_name': getattr(t.plan, 'plan', None), 'rate': _f(t.rate),
            'updated_by': staff_name(t.updated_by), 'updated_at': _dt(t.updated_at)}


class WardTariffsView(_Auth):
    def get(self, request, pk):
        w = get_object_or_404(Ward, pk=pk)
        rows = w.tariffs.select_related('sponsor', 'plan', 'updated_by')
        return Response({'ward': {'id': w.id, 'ward_name': w.ward_name, 'price': w.price},
                         'results': [tariff_row(t) for t in rows]})

    def post(self, request, pk):
        from patients.models import PatientPlan, Sponsor
        if not is_admin(request.user):
            return _deny('Only an administrator can set ward prices.')
        w = get_object_or_404(Ward, pk=pk)
        d = request.data
        sponsor = Sponsor.objects.filter(pk=d.get('sponsor')).first() if d.get('sponsor') else None
        plan = PatientPlan.objects.filter(pk=d.get('plan')).first() if d.get('plan') else None
        if d.get('sponsor') and not sponsor:
            return Response({'error': 'Sponsor not found.'}, status=400)
        if d.get('plan') and not plan:
            return Response({'error': 'Plan not found.'}, status=400)
        if plan and sponsor and plan.sponsor_id and plan.sponsor_id != sponsor.id:
            return Response({'error': f'{plan.plan} does not belong to {sponsor.name}.', 'code': 'plan_sponsor'}, status=400)
        try:
            rate = Decimal(str(d.get('rate')).strip())
        except (InvalidOperation, ValueError, TypeError):
            return Response({'error': 'Enter the daily price.'}, status=400)
        if rate < 0 or rate > Decimal('100000000'):
            return Response({'error': 'Enter a valid daily price.'}, status=400)
        t = WardTariff.objects.filter(ward=w, sponsor=sponsor, plan=plan).first()
        if t:
            t.rate = rate
            t.updated_by = request.user
            t.save()
        else:
            t = WardTariff.objects.create(ward=w, sponsor=sponsor, plan=plan, rate=rate, updated_by=request.user)
        return Response({'detail': 'Price saved.', 'tariff': tariff_row(t)}, status=201)


class WardTariffDetailView(_Auth):
    def delete(self, request, pk):
        if not is_admin(request.user):
            return _deny('Only an administrator can remove ward prices.')
        get_object_or_404(WardTariff, pk=pk).delete()
        return Response({'detail': 'Price removed.'})
