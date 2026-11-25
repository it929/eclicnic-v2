"""
Delete guard for sponsors and coverage plans.

PatientPlan is referenced by patient history (lab/radiology orders, drugs
given, services consumed) with on_delete=CASCADE, and Sponsor cascades to its
plans. Deleting a sponsor or plan that is in use would therefore silently erase
clinical and billing records. These helpers count what is still using them so
the API can refuse the delete with a clear reason.

Price-list rows (tariffs) are *not* treated as "in use": they belong to the
plan and are expected to go with it; the count is reported so the user knows.
"""
from django.db import models
from django.db.models import Q

from patients.models import PatientPlan, PatientProfile

# Patient-history tables that hang off PatientPlan with CASCADE
HISTORY_MODELS = {
    'RadiologyLab',
    'AdministerDrugs',
    'IPDAdministeredDrugs',
    'IPD2AdministeredDrugs',
    'IPD3AdministeredDrugs',
    'OPDAdministeredDrugs',
    'OPD2AdministeredDrugs',
    'OtherServiceConsumed',
}
# Price-list tables that hang off PatientPlan with CASCADE
TARIFF_MODELS = {'PharmacyTariff', 'RadioLabInventory', 'OtherService2', 'VisitPurpose'}


def plan_usage(plan_ids):
    """Counts for the given plan ids: patients, history records and tariff rows."""
    plan_ids = list(plan_ids)
    usage = {'patients': 0, 'history': 0, 'tariffs': 0}
    if not plan_ids:
        return usage
    usage['patients'] = PatientProfile.objects.filter(plan_id__in=plan_ids).count()
    for rel in PatientPlan._meta.related_objects:
        if rel.on_delete is not models.CASCADE:
            continue
        name = rel.related_model.__name__
        if name in HISTORY_MODELS:
            key = 'history'
        elif name in TARIFF_MODELS:
            key = 'tariffs'
        else:
            # Unknown cascading table: be safe and treat it as history
            key = 'history'
        usage[key] += rel.related_model.objects.filter(**{f'{rel.field.name}__in': plan_ids}).count()
    return usage


def plan_delete_block_reason(plan):
    u = plan_usage([plan.pk])
    parts = []
    if u['patients']:
        parts.append(f"{u['patients']} patient(s) are enrolled on it")
    if u['history']:
        parts.append(f"{u['history']} patient record(s) (orders, drugs given, services) were billed under it")
    if not parts:
        return None
    return (
        f'Cannot delete plan "{plan.plan}": ' + ' and '.join(parts) + '. '
        'Deleting it would remove that history. Move the patients to another plan first; '
        'plans with billing history should be kept.'
    )


def sponsor_delete_block_reason(sponsor):
    plan_ids = list(PatientPlan.objects.filter(sponsor=sponsor).values_list('pk', flat=True))
    u = plan_usage(plan_ids)
    patients = PatientProfile.objects.filter(Q(sponsor=sponsor) | Q(plan_id__in=plan_ids)).distinct().count()
    parts = []
    if patients:
        parts.append(f'{patients} patient(s) are enrolled with it')
    if u['history']:
        parts.append(f"{u['history']} patient record(s) were billed under its plans")
    if not parts:
        return None
    return (
        f'Cannot delete sponsor "{sponsor.name}": ' + ' and '.join(parts) + '. '
        'Deleting it would also delete its plans and that history. Move the patients first; '
        'sponsors with billing history should be kept.'
    )
