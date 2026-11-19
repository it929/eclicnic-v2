"""
One pricing rule for every billable service.

The hospital prices every service per sponsor and plan:
    drugs (PharmacyTariff), lab tests and radiology (RadioLabInventory),
    other services (OtherService2), consultations / visit purposes (VisitPurpose).
Walk-in patients are the "ISALU HOSPITALS PRIVATE" sponsor with their own plans
(PRIVATE PRICELIST, ISALU VIP PRICELIST), so they follow the same rule.

For a patient, an item is priced from the first list that has it:

    1. the patient's sponsor + plan        -> source "plan"
    2. the patient's plan (row stored without a sponsor)  -> source "plan"
    3. the patient's sponsor, all plans    -> source "sponsor"
    4. the General price list              -> source "general"

"Pay from your purse" items (the patient pays cash for something the plan does not
cover) are priced from the General list first.

Never:
  * match by "name contains" (AMLODIPINE 5MG would match AMLODIPINE 5MGNORVASC);
  * fall back to N0 or to a hard-coded amount - an item with no price anywhere
    returns None, and the caller must refuse it or flag it as "not priced".

The registration fee is one hospital-wide fee (it does not vary by sponsor or plan).
"""
import re
from dataclasses import dataclass, asdict
from decimal import Decimal

from django.db.models import Q

KIND_LABELS = {
    'drug': 'Drug',
    'lab': 'Lab test',
    'radiology': 'Radiology scan',
    'service': 'Service',
    'visit': 'Consultation',
}
SOURCE_LABELS = {'plan': 'Plan price', 'sponsor': 'Sponsor price', 'general': 'General price'}


@dataclass
class Quote:
    kind: str
    code: str
    name: str
    rate: Decimal
    source: str           # 'plan' | 'sponsor' | 'general'
    tariff_id: int

    @property
    def covered(self):
        return self.source in ('plan', 'sponsor')

    def as_dict(self):
        d = asdict(self)
        d['rate'] = float(self.rate)
        d['covered'] = self.covered
        d['source_label'] = SOURCE_LABELS.get(self.source, self.source)
        return d


# --------------------------------------------------------------------------- #
# Tariff tables
# --------------------------------------------------------------------------- #
def _spec(kind):
    """(queryset, code field, name field, rate field, has sponsor column)"""
    if kind == 'drug':
        from inventory.models import PharmacyTariff
        return PharmacyTariff.objects.all(), 'product_id', 'product_name', 'rate', True
    if kind in ('lab', 'radiology'):
        from radio_lab.models import RadioLabInventory
        return RadioLabInventory.objects.filter(type='L' if kind == 'lab' else 'R'), 'item_id', 'item', 'rate', True
    if kind == 'service':
        from myAdmins.models import OtherService2
        return OtherService2.objects.all(), 'service_id', 'service', 'rate', False
    if kind == 'visit':
        from queue_operations.models import VisitPurpose
        return VisitPurpose.objects.all(), None, 'purpose', 'price', True
    raise ValueError(f'Unknown price kind: {kind}')


def _norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower()).strip()


def _item_filter(kind, code=None, name=None):
    """
    Q selecting every price row of ONE item (all sponsors/plans), or None when the item
    is not in that price list. Codes win over names; names must match exactly
    (ignoring case, spacing and punctuation).
    """
    qs, code_f, name_f, _, _ = _spec(kind)
    code = str(code or '').strip()
    name = str(name or '').strip()
    if code_f and code and qs.filter(**{code_f: code}).exists():
        return Q(**{code_f: code})
    if not name:
        return None
    if code_f:
        codes = set(qs.filter(**{f'{name_f}__iexact': name}).values_list(code_f, flat=True))
        if not codes:
            target = _norm(name)
            codes = {c for c, n in qs.values_list(code_f, name_f).distinct() if _norm(n) == target}
        codes.discard(None)
        codes.discard('')
        if len(codes) == 1:
            return Q(**{code_f: codes.pop()})
        if len(codes) > 1:
            # Same name under several codes: price by name across them (rows are still
            # chosen sponsor/plan first, newest first).
            return Q(**{f'{code_f}__in': list(codes)})
        return None
    # visit purposes have no code
    if qs.filter(**{f'{name_f}__iexact': name}).exists():
        return Q(**{f'{name_f}__iexact': name})
    target = _norm(name)
    names = {n for n in qs.values_list(name_f, flat=True).distinct() if _norm(n) == target}
    return Q(**{f'{name_f}__in': list(names)}) if names else None


def quote(patient, kind, *, code=None, name=None, pay_from_purse=False):
    """Price one item for one patient -> Quote, or None when it has no price anywhere."""
    qs, code_f, name_f, rate_f, has_sponsor = _spec(kind)
    item_q = _item_filter(kind, code=code, name=name)
    if item_q is None:
        return None
    rows = qs.filter(item_q).order_by('-id')

    sponsor = getattr(patient, 'sponsor', None) if patient else None
    plan = getattr(patient, 'plan', None) if patient else None

    general_q = Q(plan__isnull=True) & (Q(sponsor__isnull=True) if has_sponsor else Q())
    steps = []
    if pay_from_purse:
        steps.append(('general', general_q))
    if plan is not None:
        if has_sponsor and sponsor is not None:
            steps.append(('plan', Q(sponsor=sponsor, plan=plan)))
        if has_sponsor:
            # a plan row stored without a sponsor, or under the plan's own sponsor - never a row
            # mislabelled with another sponsor (e.g. HYGEIA + ISALU VIP PRICELIST)
            own = Q(sponsor__isnull=True) | (Q(sponsor_id=plan.sponsor_id) if plan.sponsor_id else Q(pk__in=[]))
            steps.append(('plan', Q(plan=plan) & own))
        else:
            steps.append(('plan', Q(plan=plan)))
    if has_sponsor and sponsor is not None:
        steps.append(('sponsor', Q(sponsor=sponsor, plan__isnull=True)))
    steps.append(('general', general_q))

    for source, q in steps:
        row = rows.filter(q).first()
        if row is not None and getattr(row, rate_f) is not None:
            return Quote(
                kind=kind,
                code=str(getattr(row, code_f) or '') if code_f else '',
                name=str(getattr(row, name_f) or name or ''),
                rate=Decimal(str(getattr(row, rate_f))),
                source=source,
                tariff_id=row.id,
            )
    return None


def not_priced_message(patient, kind, name):
    sponsor = getattr(getattr(patient, 'sponsor', None), 'name', None)
    plan = getattr(getattr(patient, 'plan', None), 'plan', None)
    where = ' / '.join(x for x in (sponsor, plan) if x) or 'this patient'
    return (f"{KIND_LABELS.get(kind, kind)} \"{name}\" has no price for {where} and none in the "
            f"General price list. Ask Accounts to price it before ordering.")


def registration_fee():
    """The single hospital-wide registration fee (Decimal), or None if it has not been set."""
    from queue_operations.models import RegFee
    rf = RegFee.objects.order_by('id').first()
    return Decimal(str(rf.price)) if rf and rf.price else None


def _purse(order):
    return bool(order.get('is_pay_from_purse') or order.get('payment_mode') == 'pay_from_purse')


ORDER_KEYS = {
    # kind: (name keys, code keys) as the doctor's screen sends them
    'drug': (('drug', 'item'), ('sku', 'product_id', 'item_code')),
    'lab': (('test', 'item'), ('item_id', 'code')),
    'radiology': (('scan', 'item'), ('item_id', 'code')),
    'service': (('service', 'item'), ('service_id', 'code')),
}


def price_orders(patient, groups):
    """
    Price a doctor's whole order on the server.
    ``groups``: [(kind, [order dicts])]. Returns (priced, problems) where priced maps
    id(order) -> Quote. Any client-sent 'tariff_rate' is ignored.
    """
    priced, problems = {}, []
    for kind, orders in groups:
        name_keys, code_keys = ORDER_KEYS[kind]
        for o in orders or []:
            name = next((str(o.get(k)).strip() for k in name_keys if o.get(k)), '')
            if not name:
                continue
            code = next((str(o.get(k)).strip() for k in code_keys if o.get(k)), None)
            q = quote(patient, kind, code=code, name=name, pay_from_purse=_purse(o))
            if q is None:
                problems.append(not_priced_message(patient, kind, name))
            else:
                priced[id(o)] = q
    return priced, problems
