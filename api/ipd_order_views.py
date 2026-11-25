"""
Ward orders API (rules in IPD/order_services.py).

    GET   ipd/admissions/<id>/catalogue/?kind=lab|radiology|service&mode=covered|general&q=
    GET   ipd/admissions/<id>/investigations/                       lab / radiology / service requests
    POST  ipd/admissions/<id>/investigations/   {kind, name, code, purse, notes, urgent, pin}
    POST  ipd/investigations/<charge id>/cancel/ {reason, pin}
    POST  ipd/medications/<rx id>/supply/       {qty, notes}          ward asks pharmacy for more
    POST  ipd/supplies/<id>/cancel/             {reason, pin}
    GET   ipd/pharmacy/queue/?store=&status=pending|dispensed|cancelled&q=
    GET   ipd/pharmacy/products/?store=&q=&supply=                   stock in the dispensing store
    POST  ipd/supplies/<id>/dispense/           {store, product_id, qty, pin}  (store staff PIN)
"""
from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from IPD import order_services as osv
from IPD.billing_services import payer_profile, _payer
from IPD.models import AdmissionCharge, DrugPrescription, MedicationSupply
from IPD.services import AdmissionError, staff_name
from inventory.permissions import store_denied, user_store_ids

from .ipd_views import _admission_qs, _dt, _err, _pin_user

DISPENSING_STORES = ('ipd_pharmacy', 'ward_pharmacy', 'emergency_pharmacy')
SOURCE_LABELS = {'plan': 'Plan price', 'sponsor': 'Sponsor price', 'general': 'General price'}
STATE_LABELS = {'awaiting': 'Awaiting', 'in_progress': 'In progress', 'ready': 'Result ready', 'cancelled': 'Cancelled',
                'ordered': 'Ordered'}


class _Auth(APIView):
    permission_classes = [permissions.IsAuthenticated]


def _f(v):
    return float(v) if v is not None else None


def _adm(pk):
    return get_object_or_404(_admission_qs(), pk=pk)


# ------------------------------------------------------------------------------------------------
# Price-list search for one admission
# ------------------------------------------------------------------------------------------------
class CatalogueView(_Auth):
    LIMIT = 40

    def get(self, request, pk):
        from api.pricing import _spec, quote
        adm = _adm(pk)
        kind = request.query_params.get('kind') or 'lab'
        if kind not in osv.INVESTIGATION_KINDS:
            return Response({'error': 'Unknown kind.'}, status=400)
        mode = request.query_params.get('mode') or 'covered'
        q = (request.query_params.get('q') or '').strip()
        prof = payer_profile(adm)
        qs, code_f, name_f, rate_f, has_sponsor = _spec(kind)
        sponsor, plan = prof.sponsor, prof.plan
        if mode == 'general' or (sponsor is None and plan is None):
            mode = 'general'
            rows = qs.filter(plan__isnull=True, **({'sponsor__isnull': True} if has_sponsor else {}))
        else:
            cond = Q(pk__in=[])
            if plan is not None:
                cond |= Q(plan=plan)
            if has_sponsor and sponsor is not None:
                cond |= Q(sponsor=sponsor, plan__isnull=True)
            rows = qs.filter(cond)
        total = rows.values(code_f or name_f).distinct().count()
        if q:
            rows = rows.filter(Q(**{f'{name_f}__icontains': q}) | (Q(**{code_f: q}) if code_f else Q(pk__in=[])))
        out, seen = [], set()
        for r in rows.order_by(name_f, '-id')[:400]:
            code = str(getattr(r, code_f) or '') if code_f else ''
            name = str(getattr(r, name_f) or '')
            key = (code or name).lower()
            if not name or key in seen:
                continue
            seen.add(key)
            qt = quote(prof, kind, code=code or None, name=name, pay_from_purse=(mode == 'general'))
            if qt is None:
                continue
            out.append({'code': qt.code or code, 'name': qt.name or name, 'rate': _f(qt.rate), 'source': qt.source,
                        'source_label': SOURCE_LABELS.get(qt.source), 'payer': _payer(adm, qt.source)})
            if len(out) >= self.LIMIT:
                break
        return Response({'mode': mode, 'total': total, 'results': out})


# ------------------------------------------------------------------------------------------------
# Lab / radiology / service requests
# ------------------------------------------------------------------------------------------------
def investigation_row(c):
    rl = c.radiolab
    if c.reversed_at:
        state = 'cancelled'
    elif c.kind == 'service':
        state = 'ordered'
    else:
        state = osv.radiolab_state(rl)
    results = []
    if rl is not None and state in ('in_progress', 'ready'):
        for r in rl.lab_results.all():
            results.append({'text': r.results or '', 'file': r.file_upload.url if r.file_upload else None,
                            'by': staff_name(r.staff), 'at': _dt(r.created_date)})
        for r in rl.scan_results.all():
            results.append({'text': r.results or '', 'file': r.scan.url if r.scan else None,
                            'by': staff_name(r.staff), 'at': _dt(r.created_date)})
    params = []
    if rl is not None and state in ('in_progress', 'ready'):
        params = [{'name': p.parameter_name, 'value': p.result_value, 'unit': p.unit,
                   'range': p.reference_range_display, 'flag': p.flag}
                  for p in rl.parameter_results.all() if p.result_value]
    return {
        'id': c.id, 'kind': c.kind, 'kind_label': osv.INVESTIGATION_KINDS.get(c.kind), 'name': c.description,
        'code': c.code, 'amount': _f(c.amount), 'payer': c.payer, 'price_source': c.price_source,
        'urgent': c.urgent, 'notes': c.notes, 'ordered_by': staff_name(c.posted_by), 'ordered_at': _dt(c.posted_at),
        'state': state, 'state_label': STATE_LABELS.get(state, state),
        'request_id': c.radiolab_id, 'results': results, 'parameters': params,
        'cancelled': {'at': _dt(c.reversed_at), 'by': staff_name(c.reversed_by), 'reason': c.reverse_reason}
        if c.reversed_at else None,
    }


class InvestigationsView(_Auth):
    def get(self, request, pk):
        adm = _adm(pk)
        rows = (AdmissionCharge.objects.filter(admission=adm, kind__in=list(osv.INVESTIGATION_KINDS))
                .select_related('posted_by', 'reversed_by', 'radiolab')
                .prefetch_related('radiolab__lab_results__staff', 'radiolab__scan_results__staff',
                                  'radiolab__parameter_results')
                .order_by('-posted_at', '-id'))
        return Response({'results': [investigation_row(c) for c in rows]})

    def post(self, request, pk):
        adm = _adm(pk)
        d = request.data
        user, err = _pin_user(request, 'sign this request')
        if err:
            return err
        try:
            c = osv.order_investigation(adm, by=user, kind=d.get('kind'), name=d.get('name'), code=d.get('code') or '',
                                        purse=str(d.get('purse')).lower() in ('1', 'true', 'yes'),
                                        notes=d.get('notes') or '', urgent=str(d.get('urgent')).lower() in ('1', 'true', 'yes'))
        except AdmissionError as e:
            return _err(e)
        where = {'lab': 'sent to the Laboratory', 'radiology': 'sent to Radiology', 'service': 'ordered'}[c.kind]
        return Response({'detail': f'{c.description} {where} and added to the bill (₦{c.amount:,.2f}).',
                         'request': investigation_row(c)}, status=201)


class InvestigationCancelView(_Auth):
    def post(self, request, pk):
        c = get_object_or_404(AdmissionCharge.objects.select_related('admission', 'radiolab'), pk=pk)
        user, err = _pin_user(request, 'cancel this request')
        if err:
            return err
        try:
            osv.cancel_investigation(c, by=user, reason=request.data.get('reason'))
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': f'{c.description} cancelled and taken off the bill.'})


# ------------------------------------------------------------------------------------------------
# Pharmacy supply
# ------------------------------------------------------------------------------------------------
class SupplyRequestView(_Auth):
    def post(self, request, pk):
        rx = get_object_or_404(DrugPrescription.objects.select_related('admission'), pk=pk)
        if not rx.admission_id:
            return Response({'error': 'This prescription is not linked to an admission.'}, status=400)
        try:
            s, warning = osv.raise_supply(rx.admission, rx, by=request.user, qty=request.data.get('qty'),
                                          kind='refill', notes=request.data.get('notes') or '')
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': f'{rx.drug_name} x{s.qty} requested from {getattr(s.store, "name", "the inpatient pharmacy")}.',
                         'warning': warning}, status=201)


class SupplyCancelView(_Auth):
    def post(self, request, pk):
        s = get_object_or_404(MedicationSupply.objects.select_related('admission', 'prescription'), pk=pk)
        user, err = _pin_user(request, 'cancel this supply')
        if err:
            return err
        try:
            osv.cancel_supply(s, by=user, reason=request.data.get('reason'))
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': f'{s.prescription.drug_name} supply cancelled and taken off the bill.'})


def _dispensing_stores(user):
    from inventory.models import PharmacyStore
    qs = PharmacyStore.objects.filter(is_active=True, is_central=False, store_type__in=DISPENSING_STORES).order_by('name')
    ids = user_store_ids(user)
    return list(qs if ids is None else qs.filter(id__in=ids))


def queue_row(s):
    rx = s.prescription
    adm = s.admission
    p = adm.patient
    c = s.charge if s.charge_id and not s.charge.reversed_at else None
    return {
        'id': s.id, 'status': s.status, 'status_label': s.get_status_display(), 'kind': s.kind,
        'kind_label': s.get_kind_display(), 'qty': s.qty, 'qty_dispensed': s.qty_dispensed,
        'store_id': s.store_id, 'store_name': getattr(s.store, 'name', None),
        'requested_by': staff_name(s.requested_by), 'requested_at': _dt(s.requested_at), 'notes': s.notes,
        'dispensed_by': staff_name(s.dispensed_by), 'dispensed_at': _dt(s.dispensed_at), 'batches': s.batches,
        'product_name': getattr(s.product, 'product_name', None),
        'cancelled_at': _dt(s.cancelled_at), 'cancel_reason': s.cancel_reason,
        'order': {'id': rx.id, 'drug_name': rx.drug_name, 'dose': rx.dose, 'route': rx.get_route_display(),
                  'frequency': rx.get_frequency_display(), 'type': rx.prescription_type, 'notes': rx.notes,
                  'product_code': rx.product_code, 'pay_source': rx.pay_source, 'is_active': rx.is_active,
                  'prescribed_by': staff_name(rx.prescribed_by)},
        'charge': {'id': c.id, 'amount': _f(c.amount), 'unit_price': _f(c.unit_price), 'payer': c.payer,
                   'source': c.price_source} if c else None,
        'admission': {'id': adm.id, 'admission_no': adm.admission_no, 'ward_name': getattr(adm.ward, 'ward_name', None),
                      'bed_name': getattr(adm.bed, 'bed_name', None), 'sponsor_name': getattr(adm.sponsor, 'name', None),
                      'plan_name': getattr(adm.plan, 'plan', None), 'status': adm.status},
        'patient': {'name': p.get_full_name() if p else '', 'hospital_number': getattr(p, 'hospital_number', '')},
    }


def _order_product(rx, cache):
    """The catalogue product a drug-chart order refers to: its product code, else an exact (unambiguous) name."""
    from inventory.models import Product
    from inventory import stock_service
    key = (rx.product_code or '', rx.drug_name or '')
    if key not in cache:
        p = None
        if rx.product_code:
            p = Product.objects.filter(product_id=rx.product_code).select_related('merged_into').order_by('id').first()
            p = p.live if p else None
        if p is None:
            p, _ = stock_service.resolve_product(rx.drug_name)
        cache[key] = p
    return cache[key]


def _attach_stock(supplies, rows, stores, sel):
    """Pending rows: how many usable pieces the dispensing pharmacy holds, so short items can be requested."""
    from inventory import stock_service
    by_id = {s.id: s for s in stores}
    cache = {}
    for s, row in zip(supplies, rows):
        store = by_id.get(int(sel)) if sel and str(sel).isdigit() else None
        store = store or by_id.get(s.store_id) or (stores[0] if len(stores) == 1 else None)
        product = _order_product(s.prescription, cache)
        if not store or not product:
            row['stock'] = {'matched': bool(product), 'store_id': getattr(store, 'id', None),
                            'store_name': getattr(store, 'name', None),
                            'product_id': getattr(product, 'id', None), 'product_name': getattr(product, 'product_name', None),
                            'usable': None, 'enough': None}
            continue
        usable = stock_service.availability(store, product)['usable']
        row['stock'] = {'matched': True, 'store_id': store.id, 'store_name': store.name, 'product_id': product.id,
                        'product_name': product.product_name, 'usable': usable, 'enough': usable >= s.qty}


def _central_stores():
    from inventory.models import PharmacyStore
    return list(PharmacyStore.objects.filter(is_active=True).filter(Q(is_central=True) | Q(store_type='central_store'))
                .order_by('-is_central', 'name'))


class RequestableView(_Auth):
    """GET ipd/pharmacy/requestable/?store=<my pharmacy>&source=<store>&q=  or  &ids=1,2
    Catalogue items for a requisition, with what my pharmacy holds, what the source store holds, and
    every other store holding it. The source is the Central Store (default) or any other pharmacy.
    (Staff cannot browse other stores' shelves, but need their counts to request sensibly.)"""

    def get(self, request):
        from inventory.models import PharmacyStore, Product, StoreStock
        store = PharmacyStore.objects.filter(pk=request.query_params.get('store')).first()
        if not store:
            return Response({'error': 'Choose your pharmacy.', 'code': 'store_required'}, status=400)
        denied = store_denied(request.user, store, 'raise requisitions')
        if denied:
            return denied
        centrals = _central_stores()
        others = list(PharmacyStore.objects.filter(is_active=True).exclude(pk=store.pk)
                      .exclude(pk__in=[c.pk for c in centrals]).order_by('name'))
        sources = [c for c in centrals if c.pk != store.pk] + others
        src_id = request.query_params.get('source')
        source = next((c for c in sources if str(c.id) == str(src_id)), None) or (sources[0] if sources else None)
        products = Product.objects.filter(merged_into__isnull=True)
        ids = [int(x) for x in str(request.query_params.get('ids') or '').split(',') if x.strip().isdigit()]
        q = (request.query_params.get('q') or '').strip()
        if ids:
            products = products.filter(id__in=ids)
        elif len(q) >= 2:
            products = products.filter(Q(product_name__icontains=q) | Q(product_id__icontains=q))
        else:
            products = products.none()
        products = list(products.order_by('product_name')[:40])
        pids = [p.id for p in products]
        mine = dict(StoreStock.objects.filter(store=store, product_id__in=pids).values_list('product_id', 'stock'))
        holders = {}
        for pid, sid, qty in (StoreStock.objects.filter(product_id__in=pids, stock__gt=0, store__in=sources)
                              .values_list('product_id', 'store_id', 'stock')):
            holders.setdefault(pid, {})[sid] = qty
        names = {x.id: x.name for x in sources}
        order = {x.id: i for i, x in enumerate(sources)}
        return Response({
            'source': {'id': source.id, 'name': source.name, 'is_central': source in centrals} if source else None,
            'sources': [{'id': x.id, 'name': x.name, 'is_central': x in centrals, 'store_type': x.store_type} for x in sources],
            'results': [{'product_id': p.id, 'name': p.product_name, 'code': p.product_id or '',
                         'unit': getattr(p, 'minimum_UoM', '') or '', 'mine': mine.get(p.id, 0),
                         'source_stock': holders.get(p.id, {}).get(getattr(source, 'id', None), 0),
                         'holders': [{'id': sid, 'name': names[sid], 'stock': q}
                                     for sid, q in sorted(holders.get(p.id, {}).items(), key=lambda kv: order[kv[0]])]}
                        for p in products],
        })


class PharmacyQueueView(_Auth):
    def get(self, request):
        stores = _dispensing_stores(request.user)
        store_ids = [s.id for s in stores]
        status = request.query_params.get('status') or 'pending'
        qs = (MedicationSupply.objects.select_related(
            'admission', 'admission__patient', 'admission__ward', 'admission__bed', 'admission__sponsor',
            'admission__plan', 'prescription', 'prescription__prescribed_by', 'store', 'product', 'charge',
            'requested_by', 'dispensed_by'))
        if status in ('pending', 'dispensed', 'cancelled'):
            qs = qs.filter(status=status)
        if status != 'pending':
            since = timezone.now() - timedelta(days=int(request.query_params.get('days') or 2))
            qs = qs.filter(Q(dispensed_at__gte=since) | Q(cancelled_at__gte=since))
        sel = request.query_params.get('store')
        if sel:
            qs = qs.filter(Q(store_id=sel) | Q(store__isnull=True)) if status == 'pending' else qs.filter(store_id=sel)
        elif user_store_ids(request.user) is not None:
            qs = qs.filter(Q(store_id__in=store_ids) | Q(store__isnull=True))
        q = (request.query_params.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(prescription__drug_name__icontains=q) | Q(admission__patient__surname__icontains=q)
                           | Q(admission__patient__first_name__icontains=q)
                           | Q(admission__patient__hospital_number__icontains=q) | Q(admission__admission_no__icontains=q))
        qs = list(qs.order_by('requested_at' if status == 'pending' else '-dispensed_at', 'id')[:300])
        rows = [queue_row(s) for s in qs]
        if status == 'pending':
            _attach_stock(qs, rows, stores, sel)
        pending = MedicationSupply.objects.filter(status='pending')
        if user_store_ids(request.user) is not None:
            pending = pending.filter(Q(store_id__in=store_ids) | Q(store__isnull=True))
        return Response({'results': rows, 'pending_count': pending.count(),
                         'stores': [{'id': s.id, 'name': s.name} for s in stores]})


class PharmacyProductsView(_Auth):
    def get(self, request):
        from api.pricing import quote
        from inventory import stock_service
        from inventory.models import PharmacyStore, StoreStock
        store = PharmacyStore.objects.filter(pk=request.query_params.get('store')).first()
        if not store:
            return Response({'error': 'Choose the dispensing pharmacy.', 'code': 'store_required'}, status=400)
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response({'results': []})
        supply = MedicationSupply.objects.select_related('admission', 'prescription').filter(
            pk=request.query_params.get('supply')).first()
        rows = (StoreStock.objects.filter(store=store, product__merged_into__isnull=True)
                .filter(Q(product__product_name__icontains=q) | Q(product__product_id__iexact=q))
                .select_related('product').order_by('-stock', 'product__product_name')[:20])
        out = []
        for r in rows:
            p = r.product
            row = {'product_id': p.id, 'code': p.product_id, 'name': p.product_name,
                   'available': stock_service.availability(store, p)['usable']}
            if supply:
                qt = quote(payer_profile(supply.admission), 'drug', code=p.product_id, name=p.product_name,
                           pay_from_purse=supply.prescription.pay_source == 'patient')
                row.update({'rate': _f(qt.rate) if qt else None, 'source': qt.source if qt else None})
            out.append(row)
        return Response({'results': out})


class SupplyDispenseView(_Auth):
    def post(self, request, pk):
        from api.views import _pin_store_staff
        from inventory.models import PharmacyStore, Product
        s = get_object_or_404(MedicationSupply.objects.select_related('admission', 'prescription'), pk=pk)
        store = PharmacyStore.objects.filter(pk=request.data.get('store'), is_active=True).first()
        if not store:
            return Response({'error': 'Choose the dispensing pharmacy.', 'code': 'store_required'}, status=400)
        if store.is_central:
            return Response({'error': f'{store.name} does not dispense to patients.', 'code': 'central_store'}, status=400)
        denied = store_denied(request.user, store, 'dispense')
        if denied:
            return denied
        product = Product.objects.filter(pk=request.data.get('product_id')).first()
        if not product:
            return Response({'error': 'Choose the exact item being dispensed.', 'code': 'product_required'}, status=400)
        dispenser, err = _pin_store_staff(request, store, 'dispense this medication')
        if err:
            return err
        try:
            s = osv.dispense_supply(s, by=dispenser, store=store, product=product, qty=request.data.get('qty'))
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': f'{product.product_name} x{s.qty_dispensed} dispensed to '
                                   f'{s.admission.patient.get_full_name()} (signed by {staff_name(dispenser)}).'})
