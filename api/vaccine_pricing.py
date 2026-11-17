"""
Sponsor / plan aware vaccine pricing for the Immunization Clinic.

Every sponsor + coverage plan can negotiate its own vaccine prices
(PharmacyTariff rows whose product is in the "vaccine" drug category).
For a given patient, each vaccine is priced with this priority:

    1. Patient's sponsor + plan tariff            -> source "plan"
    2. Plan tariff (no sponsor stored on the row) -> source "plan"
    3. Sponsor-wide tariff (no plan)              -> source "sponsor"
    4. Hospital General / self-pay price          -> source "general"

Billing mode follows from the patient's sponsor type:
    * HMO patient + plan/sponsor price  -> "covered"  (billed to the HMO)
    * Private / self-pay patient        -> "cash"

HMO patients do NOT get the General fallback in their plan list: the HMO / Plan price list
holds only what the sponsor + plan actually priced. A vaccine the plan does not cover is
given from the separate General price list (get_general_vaccine_tariffs) and the patient pays.
"""
import re

from django.db.models import Q

from inventory.categories import infer_product_category
from inventory.models import PharmacyTariff, Product

SOURCE_LABELS = {
    'plan': 'Plan Tariff',
    'sponsor': 'Sponsor Tariff',
    'general': 'General Price',
}

# EPI schedule code -> regex that recognises matching products/brands in the tariff list.
# Keep patterns broad: tariff names are typed by hand ("T.TOXIOD", "PENTAVACCINE", ...).
CATALOG_CODE_PATTERNS = [
    (r'^BCG$', r'\bbcg\b'),
    (r'^OPV', r'\bopv\b|oral polio'),
    (r'^IPV', r'\bipv\b|inactivated polio'),
    (r'^HEPB-0$', r'hepatitis b (vaccine )?child|engerix b child|\bhbv\b|hep(atitis)? ?b.*(birth|child|paed)'),
    (r'^HEPB-ADULT$', r'hepatitis b adult|engerix b +adult|genevac'),
    (r'^PENTA', r'pentaval|pentavac|hexaxim|pentaxim'),
    (r'^PCV', r'pneumococcal|prevenar|s[yn]{1,2}florix|\bpcv'),
    (r'^ROTA', r'rota'),
    (r'^VITA', r'vitamin a'),
    (r'^MEASLES', r'measles|mealses|\bmmr'),
    (r'^YF$', r'yellow fever'),
    (r'^MEN', r'menactra|mening|menegitis|menveo|menafri'),
    (r'^HPV$', r'cervarix|cervical vaccine|gardasil|\bhpv\b'),
    (r'^TCV$', r'typhoid'),
    (r'^TT$', r't\.? ?toxi?o?i?d|tetanus'),
    (r'^FLU$', r'vaxigrip|\bflu\b|influenza'),
    (r'^COVID', r'covid|comirnaty|covishield'),
]


def _vaccine_names():
    """Lower-cased names of catalogue products categorised as vaccines."""
    return {
        (n or '').strip().lower()
        for n in Product.objects.filter(category='vaccine').values_list('product_name', flat=True)
    }


def _is_vaccine(name, vaccine_names):
    key = (name or '').strip().lower()
    if key in vaccine_names:
        return True
    try:
        return infer_product_category(name or '', '') == 'vaccine'
    except Exception:
        return False


def patient_pricing_context(patient):
    sponsor = getattr(patient, 'sponsor', None)
    plan = getattr(patient, 'plan', None)
    if plan and not sponsor and getattr(plan, 'sponsor', None):
        sponsor = plan.sponsor
    sponsor_category = ''
    if sponsor is not None and getattr(sponsor, 'category', None) is not None:
        sponsor_category = str(sponsor.category)
    patient_category = str(patient.category) if getattr(patient, 'category', None) else ''
    is_hmo = 'hmo' in sponsor_category.lower() or (not sponsor_category and 'hmo' in patient_category.lower())
    return {
        'sponsor': sponsor,
        'plan': plan,
        'is_hmo': bool(sponsor) and is_hmo,
        'sponsor_id': sponsor.id if sponsor else None,
        'sponsor_name': sponsor.name if sponsor else 'General / Self-Pay',
        'sponsor_code': (sponsor.code if sponsor else '') or '',
        'plan_id': plan.id if plan else None,
        'plan_name': plan.plan if plan else ('General Price' if not sponsor else ''),
        'category': sponsor_category or patient_category or 'Private',
    }


def get_patient_vaccine_tariffs(patient):
    """Return (context, priced_vaccine_list) for the patient's sponsor & plan."""
    ctx = patient_pricing_context(patient)
    sponsor, plan = ctx['sponsor'], ctx['plan']

    # HMO plan list = plan/sponsor tariffs only. Non-HMO sponsors and self-pay fall back to General.
    cond = Q(pk__in=[]) if ctx['is_hmo'] else Q(sponsor__isnull=True, plan__isnull=True)
    if plan:
        cond |= Q(plan=plan)
    if sponsor:
        cond |= Q(sponsor=sponsor, plan__isnull=True)

    vaccine_names = _vaccine_names()
    priority = {'plan': 0, 'sponsor': 1, 'general': 2}
    best = {}

    for t in PharmacyTariff.objects.filter(cond).select_related('sponsor', 'plan'):
        if not _is_vaccine(t.product_name, vaccine_names):
            continue
        if plan and t.plan_id == plan.id:
            # A plan row stored against another sponsor is not this patient's price
            if t.sponsor_id and sponsor and t.sponsor_id != sponsor.id:
                continue
            source = 'plan'
        elif t.plan_id is None and t.sponsor_id is not None:
            source = 'sponsor'
        else:
            if ctx['is_hmo']:
                continue
            source = 'general'

        key = (t.product_name or '').strip().lower()
        current = best.get(key)
        if current is None or priority[source] < priority[current[1]]:
            best[key] = (t, source)

    vaccines = []
    for t, source in best.values():
        covered = ctx['is_hmo'] and source in ('plan', 'sponsor')
        vaccines.append({
            'tariff_id': t.id,
            'name': t.product_name,
            'sku': t.product_id or '',
            'rate': float(t.rate or 0),
            'source': source,
            'source_label': SOURCE_LABELS[source],
            'payment_mode': 'covered' if covered else 'cash',
            'covered': covered,
        })
    vaccines.sort(key=lambda v: (priority[v['source']], v['name'].lower()))
    attach_stock_batches(vaccines)
    return ctx, vaccines


def attach_stock_batches(vaccines):
    """
    Adds 'batches' to each priced vaccine: in-stock, unexpired batches/lots from the
    pharmacy stores, First-Expiry-First-Out (earliest expiry first, central store first on ties).
    Falls back to the StoreStock-level batch/expiry when no batch ledger rows exist.
    """
    from datetime import date
    from inventory.models import StoreStock, StoreStockBatch

    if not vaccines:
        return vaccines
    today = date.today()

    products = list(Product.objects.filter(category='vaccine').values('id', 'product_id', 'product_name'))
    by_sku = {str(p['product_id']).strip().upper(): p['id'] for p in products if p['product_id']}
    by_name = {(p['product_name'] or '').strip().lower(): p['id'] for p in products}

    def product_id_for(v):
        return by_sku.get(str(v.get('sku') or '').strip().upper()) or by_name.get((v.get('name') or '').strip().lower())

    pid_map = {v['tariff_id']: product_id_for(v) for v in vaccines}
    pids = {p for p in pid_map.values() if p}

    def shape(batch_number, expiry, qty, store, source):
        days = (expiry - today).days if expiry else None
        return {
            'batch_number': batch_number,
            'expiry_date': expiry.isoformat() if expiry else None,
            'days_to_expiry': days,
            'expiry_status': 'UNKNOWN' if days is None else ('NEAR_EXPIRY' if days <= 60 else 'GOOD'),
            'quantity': qty,
            'store': store.name,
            'store_is_central': bool(store.is_central),
            'source': source,
        }

    batches = {}
    rows = (
        StoreStockBatch.objects.filter(product_id__in=pids, quantity__gt=0, store__is_active=True)
        .exclude(batch_number__isnull=True).exclude(batch_number='')
        .select_related('store')
    )
    for b in rows:
        if b.expiry_date and b.expiry_date <= today:
            continue  # never offer expired vaccine
        batches.setdefault(b.product_id, []).append(shape(b.batch_number, b.expiry_date, b.quantity, b.store, 'batch'))

    # Fallback: products without batch ledger rows but with batch info on the stock line
    missing = pids - set(batches)
    if missing:
        for ss in (
            StoreStock.objects.filter(product_id__in=missing, stock__gt=0, store__is_active=True)
            .exclude(batch_number__isnull=True).exclude(batch_number='')
            .select_related('store')
        ):
            if ss.expiry_date and ss.expiry_date <= today:
                continue
            batches.setdefault(ss.product_id, []).append(shape(ss.batch_number, ss.expiry_date, ss.stock, ss.store, 'stock'))

    far = date.max.isoformat()
    for v in vaccines:
        lst = batches.get(pid_map.get(v['tariff_id']), [])
        lst.sort(key=lambda b: (b['expiry_date'] or far, not b['store_is_central'], b['batch_number']))
        v['batches'] = lst
        v['in_stock'] = sum(b['quantity'] for b in lst)
    return vaccines


def match_catalog_codes(schedule, vaccines):
    """Map EPI schedule codes -> list of matching tariff_ids (best source first)."""
    compiled = [(re.compile(c, re.I), re.compile(p, re.I)) for c, p in CATALOG_CODE_PATTERNS]
    matches = {}
    for milestone in schedule:
        for v in milestone.get('vaccines', []):
            code = (v.get('code') or '').upper()
            if not code or code in matches:
                continue
            pattern = next((p for c, p in compiled if c.search(code)), None)
            if pattern is None:
                continue
            matches[code] = [x['tariff_id'] for x in vaccines if pattern.search(x['name'] or '')]
    return matches


def get_general_vaccine_tariffs():
    """
    The hospital General (self-pay) vaccine price list. Used when an HMO / sponsor plan does not
    cover a vaccine: the nurse toggles to General price and the patient pays from purse.
    """
    vaccine_names = _vaccine_names()
    vaccines = []
    for t in PharmacyTariff.objects.filter(sponsor__isnull=True, plan__isnull=True):
        if not _is_vaccine(t.product_name, vaccine_names):
            continue
        vaccines.append({
            'tariff_id': t.id,
            'name': t.product_name,
            'sku': t.product_id or '',
            'rate': float(t.rate or 0),
            'source': 'general',
            'source_label': SOURCE_LABELS['general'],
            'payment_mode': 'cash',  # never covered: patient pays from purse
            'covered': False,
        })
    vaccines.sort(key=lambda v: v['name'].lower())
    attach_stock_batches(vaccines)
    return vaccines


def resolve_tariff_for_patient(patient, tariff_id, price_list='plan'):
    """
    Server-side check that a tariff id is a valid price for this patient. Returns dict or None.
    price_list='general' -> must be a General (self-pay) price; billed to the patient, never the HMO.
    """
    try:
        tariff_id = int(tariff_id)
    except (TypeError, ValueError):
        return None
    if price_list == 'general':
        vaccines = get_general_vaccine_tariffs()
    else:
        _ctx, vaccines = get_patient_vaccine_tariffs(patient)
    return next((v for v in vaccines if v['tariff_id'] == tariff_id), None)
