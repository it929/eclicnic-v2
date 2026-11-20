"""
In-patient (IPD) admission rules. Every change to an admission goes through this module,
in the same way every stock change goes through inventory/stock_service.py.

Lifecycle
    awaiting_bed --assign_bed--> in_ward --order_discharge--> discharge_ordered --complete_discharge--> discharged
         |                         ^  |                              |
         |                         |  +--assign_bed (transfer)       +--reverse_discharge--> in_ward
         +--cancel--> cancelled

Guarantees (also enforced by database constraints):
  * a patient has at most one open admission (awaiting_bed / in_ward / discharge_ordered);
  * a bed holds at most one patient, and an admission holds at most one bed;
  * Bed.is_occupied always matches "has an active BedAllocation".

The older 0/1 flags on AdmissionTable (nurse_admit_status, doctor_discharge_status,
bill_discharge_status) are kept in step so legacy screens and reports stay correct.
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    ADMISSION_SOURCES, ADMISSION_TYPES, DISCHARGE_TYPES, OPEN_ADMISSION_STATUSES,
    AdmissionEvent, AdmissionTable, Bed, BedAllocation, Ward,
)


class AdmissionError(Exception):
    """A rule was broken. ``code`` is a stable machine-readable reason for the frontend."""

    def __init__(self, message, code='invalid'):
        super().__init__(message)
        self.message = message
        self.code = code


def staff_name(user):
    if not user:
        return ''
    full = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip()
    return getattr(user, 'fullname', None) or full or getattr(user, 'username', '') or ''


def open_admission(patient):
    """The patient's current (open) admission, or None."""
    if not patient:
        return None
    return (AdmissionTable.objects.filter(patient=patient, status__in=OPEN_ADMISSION_STATUSES)
            .select_related('ward', 'bed').first())


def _log(adm, event, from_status, detail='', staff=None):
    AdmissionEvent.objects.create(admission=adm, event=event, from_status=from_status or '',
                                  to_status=adm.status, detail=detail, staff=staff)


WARD_NURSING_DEPARTMENTS = ['Nursing']


def _notify(users=None, departments=None, **kw):
    from notifications.services import notify, notify_department
    if departments:
        notify_department(departments, **kw)
    if users:
        notify(users, **kw)


def _lock(adm):
    return AdmissionTable.objects.select_for_update().get(pk=adm.pk)


def _sync_legacy(adm):
    """Keep the old 0/1 flags in step with ``status``."""
    s = adm.status
    adm.nurse_admit_status = 1 if s in ('in_ward', 'discharge_ordered', 'discharged') else 0
    adm.doctor_discharge_status = 1 if s in ('discharge_ordered', 'discharged', 'cancelled') else 0
    adm.bill_discharge_status = 1 if s == 'discharged' else 0


def _release_bed(adm, by, now):
    """End the admission's active bed allocation (if any) and free the bed."""
    alloc = BedAllocation.objects.select_for_update().filter(admission_record=adm, is_active=True).first()
    if not alloc:
        return None
    alloc.is_active = False
    alloc.released_at = now
    alloc.released_by = by
    alloc.save(update_fields=['is_active', 'released_at', 'released_by'])
    if alloc.bed_id:
        Bed.objects.filter(pk=alloc.bed_id).update(is_occupied=False)
    return alloc


def _choice(value, choices, field, default=None):
    value = (value or default or '').strip()
    valid = {c for c, _ in choices}
    if value not in valid:
        raise AdmissionError(f"Unknown {field} '{value}'.", 'invalid_' + field)
    return value


def gender_mismatch(ward, patient):
    """Return a message if the patient may not go to this ward because of its gender rule."""
    rule = getattr(ward, 'gender', 'any') or 'any'
    pg = (getattr(patient, 'gender', '') or '').strip().lower()
    if rule == 'any' or not pg:
        return None
    if pg != rule:
        return f"{ward.ward_name} is a {rule}-only ward; this patient is {pg}."
    return None


# --------------------------------------------------------------------------------------------
# Admit
# --------------------------------------------------------------------------------------------
@transaction.atomic
def admit(patient, *, doctor, created_by=None, appointment=None, ward=None, admission_type='elective',
          source='opd', reason='', provisional_diagnosis='', notes='', consultant=None):
    """Open a new admission (status awaiting_bed). ``doctor`` is the PIN-verified admitting doctor."""
    from patients.models import PatientProfile

    if not patient:
        raise AdmissionError('Choose the patient to admit.', 'patient_required')
    if not doctor:
        raise AdmissionError("The admitting doctor's PIN is required.", 'pin_required')
    # Serialise admissions of the same patient (two clicks, two screens).
    patient = PatientProfile.objects.select_for_update().get(pk=patient.pk)

    current = open_admission(patient)
    if current:
        raise AdmissionError(
            f"{patient.get_full_name()} is already admitted ({current.admission_no or current.pk}, "
            f"{current.get_status_display().lower()}).", 'already_admitted')

    reason = (reason or '').strip()
    if not reason:
        raise AdmissionError('Enter the reason for admission.', 'reason_required')
    admission_type = _choice(admission_type, ADMISSION_TYPES, 'admission_type', 'elective')
    source = _choice(source, ADMISSION_SOURCES, 'source', 'opd')

    if ward is not None:
        if not ward.is_active:
            raise AdmissionError(f'{ward.ward_name} is closed.', 'ward_inactive')
        msg = gender_mismatch(ward, patient)
        if msg:
            raise AdmissionError(msg, 'ward_gender')

    now = timezone.now()
    try:
        adm = AdmissionTable.objects.create(
            patient=patient,
            status='awaiting_bed',
            admission_type=admission_type,
            source=source,
            appointment=appointment,
            ward=ward,
            reason=reason,
            provisional_diagnosis=(provisional_diagnosis or '').strip(),
            notes=(notes or '').strip(),
            consultant=consultant or doctor,
            sponsor=getattr(patient, 'sponsor', None),
            plan=getattr(patient, 'plan', None),
            doctor_admitted=doctor,
            created_by=created_by,
        )
    except IntegrityError:
        # The partial unique index caught a race the lock above did not.
        raise AdmissionError(f'{patient.get_full_name()} is already admitted.', 'already_admitted')
    adm.admission_no = f"ADM-{now:%Y}-{adm.pk:05d}"
    _sync_legacy(adm)
    adm.save(update_fields=['admission_no', 'nurse_admit_status', 'doctor_discharge_status', 'bill_discharge_status'])
    detail = f"Admitted by {staff_name(doctor)}"
    if ward:
        detail += f" to {ward.ward_name}"
    _log(adm, 'admitted', '', detail + '.', doctor)
    urgent = admission_type == 'emergency'
    _notify(departments=WARD_NURSING_DEPARTMENTS, kind='admission_new', actor=doctor,
            title=f"{'EMERGENCY: ' if urgent else ''}New admission: {patient.get_full_name()}",
            message=f"{adm.admission_no} · {adm.get_admission_type_display()} · "
                    f"{ward.ward_name if ward else 'any ward'} · admitted by {staff_name(doctor)}. Assign a bed.",
            link='/ipd/admitted', level='danger' if urgent else 'warning', icon='fa-procedures',
            ref=f'admission:{adm.pk}')
    return adm


# --------------------------------------------------------------------------------------------
# Bed: receive into ward, or transfer
# --------------------------------------------------------------------------------------------
@transaction.atomic
def assign_bed(admission, bed, *, by, notes=''):
    """Put the patient on ``bed``. From awaiting_bed this receives the patient into the ward
    (-> in_ward); from in_ward / discharge_ordered it is a bed transfer."""
    adm = _lock(admission)
    if adm.status not in OPEN_ADMISSION_STATUSES:
        raise AdmissionError(f'This admission is {adm.get_status_display().lower()}.', 'not_open')
    if not by:
        raise AdmissionError('A staff PIN is required.', 'pin_required')
    bed = Bed.objects.select_for_update(of=('self',)).select_related('ward').get(pk=bed.pk)
    if adm.bed_id == bed.pk:
        raise AdmissionError(f'The patient is already on {bed.bed_name}.', 'same_bed')
    if not bed.ward:
        raise AdmissionError(f'{bed.bed_name} is not mapped to a ward yet.', 'bed_unmapped')
    if not bed.is_active or not bed.ward.is_active:
        raise AdmissionError(f'{bed.bed_name} is out of service.', 'bed_inactive')
    if BedAllocation.objects.filter(bed=bed, is_active=True).exists():
        raise AdmissionError(f'{bed.bed_name} ({bed.ward.ward_name}) is occupied.', 'bed_occupied')
    msg = gender_mismatch(bed.ward, adm.patient)
    if msg:
        raise AdmissionError(msg, 'ward_gender')

    now = timezone.now()
    from_status = adm.status
    old_bed = adm.bed
    is_transfer = _release_bed(adm, by, now) is not None
    try:
        BedAllocation.objects.create(ward=bed.ward, bed=bed, staff=by, patient=adm.patient, admission_record=adm,
                                     reason='transfer' if is_transfer else 'admission')
    except IntegrityError:
        raise AdmissionError(f'{bed.bed_name} was just taken by another patient.', 'bed_occupied')
    Bed.objects.filter(pk=bed.pk).update(is_occupied=True)

    adm.ward = bed.ward
    adm.bed = bed
    fields = ['ward', 'bed']
    if adm.status == 'awaiting_bed':
        adm.status = 'in_ward'
        adm.received_by = by
        adm.nurse_admitted = staff_name(by)[:50]
        adm.nurse_admit_date = now
        fields += ['status', 'received_by', 'nurse_admitted', 'nurse_admit_date']
    _sync_legacy(adm)
    adm.save(update_fields=fields + ['nurse_admit_status', 'doctor_discharge_status', 'bill_discharge_status', 'updated_at'])

    if is_transfer:
        detail = f"Moved from {old_bed.bed_name if old_bed else '?'} to {bed.bed_name} ({bed.ward.ward_name})"
        _log(adm, 'transferred', from_status, detail + (f'. {notes}' if notes else '.'), by)
    else:
        detail = f"Received into {bed.ward.ward_name}, {bed.bed_name}, by {staff_name(by)}"
        _log(adm, 'bed_assigned', from_status, detail + (f'. {notes}' if notes else '.'), by)
        _notify(users=[adm.doctor_admitted_id], kind='admission_received', actor=by,
                title=f"{adm.patient.get_full_name()} received in {bed.ward.ward_name}",
                message=f"{bed.bed_name} · {adm.admission_no} · by {staff_name(by)}.",
                link='/ipd/admitted', level='success', icon='fa-bed', ref=f'admission:{adm.pk}')
    return adm


# --------------------------------------------------------------------------------------------
# Discharge
# --------------------------------------------------------------------------------------------
@transaction.atomic
def order_discharge(admission, *, by, discharge_type='routine', summary=''):
    """Doctor signs the discharge. The patient keeps the bed until complete_discharge."""
    adm = _lock(admission)
    if adm.status != 'in_ward':
        raise AdmissionError('Only a patient who is in the ward can be discharged.', 'not_in_ward')
    if not by:
        raise AdmissionError("The doctor's PIN is required.", 'pin_required')
    discharge_type = _choice(discharge_type, DISCHARGE_TYPES, 'discharge_type', 'routine')
    now = timezone.now()
    adm.status = 'discharge_ordered'
    adm.discharge_type = discharge_type
    adm.discharge_summary = (summary or '').strip()
    adm.discharge_ordered_by = by
    adm.doctor_discharged = staff_name(by)[:50]
    adm.doctor_discharge_date = now
    _sync_legacy(adm)
    adm.save()
    _log(adm, 'discharge_ordered', 'in_ward', f"{adm.get_discharge_type_display()} signed by {staff_name(by)}.", by)
    _notify(departments=WARD_NURSING_DEPARTMENTS, kind='discharge_ordered', actor=by,
            title=f"Discharge ordered: {adm.patient.get_full_name()}",
            message=f"{adm.admission_no} · {getattr(adm.ward, 'ward_name', '')} {getattr(adm.bed, 'bed_name', '')} · "
                    f"{adm.get_discharge_type_display()} by {staff_name(by)}. Release the bed when the patient leaves.",
            link='/ipd/admitted', level='info', icon='fa-door-open', ref=f'admission:{adm.pk}')
    return adm


@transaction.atomic
def reverse_discharge(admission, *, by, reason=''):
    """Withdraw a discharge order (patient not leaving after all)."""
    adm = _lock(admission)
    if adm.status != 'discharge_ordered':
        raise AdmissionError('There is no discharge order to withdraw.', 'no_discharge_order')
    adm.status = 'in_ward'
    adm.discharge_type = ''
    adm.discharge_ordered_by = None
    adm.doctor_discharged = None
    adm.doctor_discharge_date = None
    _sync_legacy(adm)
    adm.save()
    _log(adm, 'discharge_reversed', 'discharge_ordered', (reason or '').strip(), by)
    return adm


@transaction.atomic
def complete_discharge(admission, *, by):
    """The patient leaves the ward: release the bed and close the admission.
    (Bill clearance checks will be added here when IPD billing is built.)"""
    adm = _lock(admission)
    if adm.status != 'discharge_ordered':
        raise AdmissionError('The doctor has not signed a discharge for this patient.', 'no_discharge_order')
    if not by:
        raise AdmissionError('A staff PIN is required.', 'pin_required')
    now = timezone.now()
    _release_bed(adm, by, now)
    adm.status = 'discharged'
    adm.discharged_at = now
    adm.discharged_by = by
    adm.bill_discharged = staff_name(by)[:50]
    adm.bill_discharge_date = now
    adm.bed = None
    _sync_legacy(adm)
    adm.save()
    _log(adm, 'discharged', 'discharge_ordered', f'Left the ward; released by {staff_name(by)}.', by)
    return adm


# --------------------------------------------------------------------------------------------
# Cancel
# --------------------------------------------------------------------------------------------
@transaction.atomic
def cancel(admission, *, by, reason):
    """Cancel an admission entered in error, before the ward received the patient."""
    adm = _lock(admission)
    if adm.status != 'awaiting_bed':
        raise AdmissionError('Only an admission still awaiting a bed can be cancelled. '
                             'A patient already in the ward must be discharged.', 'cannot_cancel')
    reason = (reason or '').strip()
    if not reason:
        raise AdmissionError('Enter why the admission is being cancelled.', 'reason_required')
    now = timezone.now()
    adm.status = 'cancelled'
    adm.cancelled_at = now
    adm.cancelled_by = by
    adm.cancel_reason = reason
    _sync_legacy(adm)
    adm.save()
    _log(adm, 'cancelled', 'awaiting_bed', reason, by)
    return adm


# --------------------------------------------------------------------------------------------
# Ward / bed setup helpers
# --------------------------------------------------------------------------------------------
def _beds_in(ward):
    """Beds in ``ward``, or the unmapped beds when ward is None."""
    return Bed.objects.filter(ward__isnull=True) if ward is None else Bed.objects.filter(ward=ward)


def _where(ward):
    return ward.ward_name if ward else 'the unmapped beds'


def bed_in_use(bed):
    return BedAllocation.objects.filter(bed=bed, is_active=True).exists()


@transaction.atomic
def create_bed(name, ward=None):
    """Create one bed. ``ward`` may be None: the bed is then created unmapped and mapped later."""
    name = (name or '').strip()[:50]
    if not name:
        raise AdmissionError('Enter the bed name.', 'name_required')
    if _beds_in(ward).filter(bed_name__iexact=name).exists():
        raise AdmissionError(f'{name} already exists in {_where(ward)}.', 'duplicate_name')
    return Bed.objects.create(ward=ward, bed_name=name)


@transaction.atomic
def add_beds(ward, count, prefix='Bed'):
    """Add ``count`` beds named '<prefix> N', continuing the numbering in ``ward`` (None = unmapped)."""
    count = int(count)
    if count < 1 or count > 200:
        raise AdmissionError('Add between 1 and 200 beds at a time.', 'invalid_count')
    prefix = (prefix or 'Bed').strip()[:40] or 'Bed'
    existing = {n.lower() for n in _beds_in(ward).values_list('bed_name', flat=True)}
    made, n = [], 1
    while len(made) < count:
        name = f'{prefix} {n}'
        if name.lower() not in existing:
            made.append(Bed.objects.create(ward=ward, bed_name=name))
        n += 1
    return made


@transaction.atomic
def map_beds(beds, ward):
    """Map beds to ``ward`` (None = unmap). All or nothing: a bed with a patient on it, or a
    name already used in the target ward, stops the whole change."""
    beds = list(Bed.objects.select_for_update(of=('self',)).select_related('ward')
                .filter(pk__in=[b.pk for b in beds]).order_by('id'))
    if not beds:
        raise AdmissionError('Choose at least one bed.', 'bed_required')
    if ward is not None and not ward.is_active:
        raise AdmissionError(f'{ward.ward_name} is closed. Open it before mapping beds to it.', 'ward_inactive')
    moving = [b for b in beds if b.ward_id != (ward.pk if ward else None)]
    busy = [b.bed_name for b in moving if bed_in_use(b)]
    if busy:
        raise AdmissionError(f"{', '.join(busy)} {'has' if len(busy) == 1 else 'have'} a patient on it. "
                             'Transfer the patient to another bed first.', 'bed_in_use')
    taken = {n.lower() for n in _beds_in(ward).exclude(pk__in=[b.pk for b in moving])
             .values_list('bed_name', flat=True)}
    seen = set()
    for b in moving:
        key = b.bed_name.lower()
        if key in taken or key in seen:
            raise AdmissionError(f'{_where(ward)} already has a bed named {b.bed_name}. Rename one of them first.',
                                 'duplicate_name')
        seen.add(key)
    for b in moving:
        b.ward = ward
        b.save(update_fields=['ward'])
    return moving
