"""
Infection-control alerts on a patient: the single place they are raised, cleared and read.

An alert says which PRECAUTION staff must take (blood & body fluid, contact, droplet,
airborne), never the diagnosis behind it. That lets every list and chart that nurses use show
it, while the result itself stays in the lab report. Nothing is deleted: clearing keeps the
row, with who cleared it and why.
"""
from django.db import transaction
from django.utils import timezone

from .models import INFECTION_PRECAUTIONS, PatientSafetyAlert

PRECAUTION_LABELS = dict(INFECTION_PRECAUTIONS)
# What each precaution means at the bedside (shown with the alert).
PRECAUTION_HINTS = {
    'blood': 'Gloves for any contact with blood or body fluids; safe sharps handling; no re-capping needles.',
    'contact': 'Gloves and gown for patient contact; dedicated equipment where possible.',
    'droplet': 'Surgical mask within 1–2 m of the patient; single room or 1 m spacing.',
    'airborne': 'N95 respirator; single room with door closed; limit movement of the patient.',
}
# Who is told when an alert is raised: the wards and the doctors.
NOTIFY_DEPARTMENTS = ['Nursing', 'Nursing Station', 'Clinical']


class SafetyAlertError(Exception):
    def __init__(self, message, code='invalid'):
        super().__init__(message)
        self.message = message
        self.code = code


def _staff_name(u):
    return (getattr(u, 'fullname', '') or getattr(u, 'username', '')) if u else ''


def alert_row(a):
    return {
        'id': a.id,
        'precaution': a.precaution,
        'label': PRECAUTION_LABELS.get(a.precaution, a.precaution),
        'hint': PRECAUTION_HINTS.get(a.precaution, ''),
        'instruction': a.instruction,
        'source': a.source,
        'raised_by': _staff_name(a.raised_by),
        'raised_at': timezone.localtime(a.raised_at).isoformat() if a.raised_at else None,
        'is_active': a.is_active,
        'cleared_by': _staff_name(a.cleared_by),
        'cleared_at': timezone.localtime(a.cleared_at).isoformat() if a.cleared_at else None,
        'clear_reason': a.clear_reason,
    }


def active_alerts_map(patient_ids):
    """{patient_id: [alert rows]} for many patients in one query (for lists)."""
    ids = [i for i in set(patient_ids) if i]
    out = {}
    if not ids:
        return out
    for a in (PatientSafetyAlert.objects.filter(patient_id__in=ids, is_active=True)
              .select_related('raised_by').order_by('precaution')):
        out.setdefault(a.patient_id, []).append(alert_row(a))
    return out


def active_alerts(patient):
    return active_alerts_map([getattr(patient, 'pk', patient)]).get(getattr(patient, 'pk', patient), [])


def raise_alert(patient, *, precaution, by, instruction='', source='clinician', source_order=None):
    """Raise (or refresh) an alert. Returns (alert, created)."""
    if precaution not in PRECAUTION_LABELS:
        raise SafetyAlertError('Choose the precaution staff must take.', 'precaution')
    instruction = str(instruction or '').strip()
    if len(instruction) > 300:
        raise SafetyAlertError('Keep the instruction to 300 characters or fewer.', 'instruction')
    with transaction.atomic():
        existing = (PatientSafetyAlert.objects.select_for_update()
                    .filter(patient=patient, precaution=precaution, is_active=True).first())
        if existing:
            # Already flagged: keep the original, add a newer instruction if one was given.
            if instruction and instruction != existing.instruction:
                existing.instruction = instruction
                existing.save(update_fields=['instruction'])
            return existing, False
        alert = PatientSafetyAlert.objects.create(
            patient=patient, precaution=precaution, instruction=instruction, source=source,
            source_order=source_order, raised_by=by)
        transaction.on_commit(lambda: _notify_staff(alert, by))
    return alert, True


def clear_alert(alert, *, by, reason):
    reason = str(reason or '').strip()
    if not reason:
        raise SafetyAlertError('Say why the alert is being cleared.', 'reason_required')
    if len(reason) > 500:
        raise SafetyAlertError('Keep the reason to 500 characters or fewer.', 'reason')
    with transaction.atomic():
        alert = PatientSafetyAlert.objects.select_for_update().get(pk=alert.pk)
        if not alert.is_active:
            raise SafetyAlertError('This alert has already been cleared.', 'already_cleared')
        alert.is_active = False
        alert.cleared_by = by
        alert.cleared_at = timezone.now()
        alert.clear_reason = reason
        alert.save(update_fields=['is_active', 'cleared_by', 'cleared_at', 'clear_reason'])
    return alert


def _notify_staff(alert, by):
    """Tell Nursing and the doctors. The message names the precaution only, never the result."""
    try:
        from notifications.services import notify_department
        p = alert.patient
        notify_department(
            NOTIFY_DEPARTMENTS, kind='infection_alert', level='danger', icon='fa-biohazard', actor=by,
            title=f'Infection-control alert: {p.get_full_name()}',
            message=f'{PRECAUTION_LABELS[alert.precaution]} for {p.hospital_number or "this patient"}.'
                    + (f' {alert.instruction}' if alert.instruction else ''),
            link='/ipd/admitted', ref=f'safety_alert:{alert.pk}')
    except Exception:  # a notification failure must never undo the alert
        import logging
        logging.getLogger(__name__).exception('Infection-control alert notification failed')
