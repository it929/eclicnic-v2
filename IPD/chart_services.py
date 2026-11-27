"""
Inpatient chart rules: clinical notes, medication orders + administration (drug chart / MAR),
treatment orders + execution (treatment chart), observations (with NEWS2) and fluid balance.

Rules
  * The chart is written only while the admission is open (awaiting bed, in ward, discharge ordered).
    After discharge or cancellation it is read-only.
  * Clinical entries are never deleted. A wrong note, observation or fluid entry is marked
    "entered in error" with a reason and stays visible, crossed out.
  * Medication and treatment orders are signed by the prescriber's PIN; each dose given / withheld
    is signed by the nurse's PIN. A dose time can be charted once only.
  * Dose times come from the frequency (FREQUENCY_TIMES); STAT has one dose at the order time and
    PRN has none (each PRN dose is charted when given).
"""
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    CONSCIOUSNESS, FLUID_IN_ROUTES, FLUID_OUT_ROUTES, NOTE_TYPES, TREATMENT_CATEGORIES,
    AdmissionEvent, AdmissionTable, ClinicalNote, DrugAdministration, DrugPrescription, FluidEntry,
    Observation, TreatmentOrder, TreatmentRecord,
)
from .services import AdmissionError, staff_name

# Times kept identical to IPD/utils/drug_schedule.py for od/bd/tds/qds so old schedule rows line up.
FREQUENCY_TIMES = {
    'od': [time(8)], 'mane': [time(8)], 'nocte': [time(22)],
    'bd': [time(8), time(20)], 'q12h': [time(8), time(20)],
    'tds': [time(8), time(14), time(20)], 'q8h': [time(6), time(14), time(22)],
    'qds': [time(6), time(12), time(18), time(22)], 'q6h': [time(0), time(6), time(12), time(18)],
    'q4h': [time(2), time(6), time(10), time(14), time(18), time(22)],
}
FREQUENCY_LABELS = dict(DrugPrescription.FREQUENCY)
ROUTE_LABELS = dict(DrugPrescription.ROUTES)
PRESCRIPTION_TYPES = dict(DrugPrescription.PRESCRIPTION_TYPES)
DOSE_STATUSES = {'administered': 'Given', 'refused': 'Refused', 'held': 'Withheld', 'missed': 'Missed'}
TREATMENT_STATUSES = dict(TreatmentRecord.STATUSES)

DUE_WINDOW = timedelta(hours=1)      # a dose is "due" from 1 h before to 1 h after its time
EARLY_LIMIT = timedelta(hours=2)     # cannot chart a dose more than 2 h before its time
MAX_BACKDATE = timedelta(days=3)     # observations / fluids can be entered up to 3 days late

NOTE_LABELS = dict(NOTE_TYPES)


# ------------------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------------------
def require_open(adm):
    if not adm.is_open:
        raise AdmissionError(
            f'Admission {adm.admission_no or adm.pk} is {adm.get_status_display().lower()}; its chart is read-only.',
            'admission_closed')


def _lock(adm):
    adm = AdmissionTable.objects.select_for_update().get(pk=adm.pk)
    require_open(adm)
    return adm


def _event(adm, event, detail, staff):
    AdmissionEvent.objects.create(admission=adm, event=event, from_status=adm.status, to_status=adm.status,
                                  detail=detail[:2000], staff=staff)


def _text(value, field, required=True, max_len=4000):
    v = (value or '').strip() if isinstance(value, str) or value is None else str(value).strip()
    if required and not v:
        raise AdmissionError(f'{field} is required.', 'required')
    if len(v) > max_len:
        raise AdmissionError(f'{field} is too long (max {max_len} characters).', 'too_long')
    return v


def _num(value, field, lo, hi, integer=False):
    if value in (None, ''):
        return None
    try:
        n = int(str(value).strip()) if integer else Decimal(str(value).strip())
    except (ValueError, InvalidOperation):
        raise AdmissionError(f'{field} must be a number.', 'invalid_number')
    if n < lo or n > hi:
        raise AdmissionError(f'{field} must be between {lo} and {hi}.', 'out_of_range')
    return n


def parse_when(value, adm, field='Time'):
    """A recorded time: default now; not in the future, not before admission, not too old."""
    now = timezone.now()
    if value in (None, ''):
        return now
    dt = value if isinstance(value, datetime) else None
    if dt is None:
        s = str(value).strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise AdmissionError(f'{field} is not a valid date/time.', 'invalid_time')
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    if dt > now + timedelta(minutes=5):
        raise AdmissionError(f'{field} cannot be in the future.', 'future_time')
    if adm.doctor_admit_date and dt < adm.doctor_admit_date - timedelta(minutes=5):
        raise AdmissionError(f'{field} is before the patient was admitted.', 'before_admission')
    if dt < now - MAX_BACKDATE:
        raise AdmissionError(f'{field} is more than {MAX_BACKDATE.days} days ago.', 'too_old')
    return dt


def _date(value, field, default=None):
    if value in (None, ''):
        return default
    if hasattr(value, 'year') and not isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        raise AdmissionError(f'{field} is not a valid date.', 'invalid_date')


def _void(entry, adm, by, reason, label):
    reason = _text(reason, 'Reason', max_len=500)
    if entry.voided_at:
        raise AdmissionError('This entry is already marked as entered in error.', 'already_voided')
    entry.voided_at = timezone.now()
    entry.voided_by = by
    entry.void_reason = reason
    entry.save(update_fields=['voided_at', 'voided_by', 'void_reason'])
    _event(adm, 'entry_voided', f'{label} marked as entered in error: {reason}', by)
    return entry


# ------------------------------------------------------------------------------------------------
# Notes
# ------------------------------------------------------------------------------------------------
def add_note(adm, *, by, note_type, body, title=''):
    if note_type not in NOTE_LABELS:
        raise AdmissionError('Choose the type of note.', 'note_type')
    body = _text(body, 'Note', max_len=20000)
    with transaction.atomic():
        adm = _lock(adm)
        return ClinicalNote.objects.create(admission=adm, note_type=note_type, body=body,
                                           title=_text(title, 'Title', required=False, max_len=200), staff=by)


def void_note(note, *, by, reason):
    with transaction.atomic():
        adm = _lock(note.admission)
        note = ClinicalNote.objects.select_for_update().get(pk=note.pk)
        return _void(note, adm, by, reason, NOTE_LABELS.get(note.note_type, 'Note'))


# ------------------------------------------------------------------------------------------------
# Observations (+ NEWS2)
# ------------------------------------------------------------------------------------------------
def news2(o, patient_age=None):
    """NEWS2 total, or None when a required value is missing or the patient is under 16."""
    if patient_age is not None and patient_age < 16:
        return None
    rr, spo2, sbp, hr, temp = o.resp_rate, o.spo2, o.bp_systolic, o.pulse, o.temperature
    if None in (rr, spo2, sbp, hr, temp):
        return None
    t = float(temp)
    s = 0
    s += 3 if rr <= 8 else 1 if rr <= 11 else 0 if rr <= 20 else 2 if rr <= 24 else 3
    s += 3 if spo2 <= 91 else 2 if spo2 <= 93 else 1 if spo2 <= 95 else 0
    s += 2 if o.on_oxygen else 0
    s += 3 if sbp <= 90 else 2 if sbp <= 100 else 1 if sbp <= 110 else 0 if sbp <= 219 else 3
    s += 3 if hr <= 40 else 1 if hr <= 50 else 0 if hr <= 90 else 1 if hr <= 110 else 2 if hr <= 130 else 3
    s += 0 if (o.consciousness or 'A') == 'A' else 3
    s += 3 if t <= 35.0 else 1 if t <= 36.0 else 0 if t <= 38.0 else 1 if t <= 39.0 else 2
    return s


def news_red_flag(o):
    """Any single parameter scoring 3 (urgent ward review even if the total is low)."""
    checks = [
        o.resp_rate is not None and (o.resp_rate <= 8 or o.resp_rate >= 25),
        o.spo2 is not None and o.spo2 <= 91,
        o.bp_systolic is not None and (o.bp_systolic <= 90 or o.bp_systolic >= 220),
        o.pulse is not None and (o.pulse <= 40 or o.pulse >= 131),
        (o.consciousness or 'A') != 'A',
        o.temperature is not None and float(o.temperature) <= 35.0,
    ]
    return any(checks)


def news_risk(score, red_flag=False):
    if score is None:
        return None
    if score >= 7:
        return {'level': 'high', 'label': 'High risk: emergency response'}
    if score >= 5:
        return {'level': 'medium', 'label': 'Medium risk: urgent review'}
    if red_flag:
        return {'level': 'low_medium', 'label': 'Single red score: urgent ward review'}
    return {'level': 'low', 'label': 'Low risk' if score else 'No concern'}


def add_observation(adm, *, by, data):
    consc = (data.get('consciousness') or 'A').upper()
    if consc not in dict(CONSCIOUSNESS):
        raise AdmissionError('Choose a level of consciousness (ACVPU).', 'consciousness')
    o = Observation(
        temperature=_num(data.get('temperature'), 'Temperature (°C)', 25, 45),
        pulse=_num(data.get('pulse'), 'Pulse', 20, 250, integer=True),
        resp_rate=_num(data.get('resp_rate'), 'Respiratory rate', 2, 80, integer=True),
        bp_systolic=_num(data.get('bp_systolic'), 'Systolic BP', 40, 300, integer=True),
        bp_diastolic=_num(data.get('bp_diastolic'), 'Diastolic BP', 20, 200, integer=True),
        spo2=_num(data.get('spo2'), 'SpO₂', 50, 100, integer=True),
        on_oxygen=bool(data.get('on_oxygen')),
        oxygen_lpm=_num(data.get('oxygen_lpm'), 'Oxygen (L/min)', 0, 60),
        consciousness=consc,
        pain_score=_num(data.get('pain_score'), 'Pain score', 0, 10, integer=True),
        blood_glucose=_num(data.get('blood_glucose'), 'Blood glucose (mmol/L)', Decimal('0.5'), 50),
        weight=_num(data.get('weight'), 'Weight (kg)', Decimal('0.3'), 400),
        notes=_text(data.get('notes'), 'Notes', required=False, max_len=1000),
    )
    if (o.bp_systolic is None) != (o.bp_diastolic is None):
        raise AdmissionError('Enter both systolic and diastolic BP.', 'bp_pair')
    if o.bp_systolic is not None and o.bp_diastolic >= o.bp_systolic:
        raise AdmissionError('Diastolic BP must be lower than systolic BP.', 'bp_order')
    vitals = [o.temperature, o.pulse, o.resp_rate, o.bp_systolic, o.spo2, o.pain_score, o.blood_glucose, o.weight]
    if all(v is None for v in vitals) and consc == 'A':
        raise AdmissionError('Enter at least one observation.', 'empty')
    with transaction.atomic():
        adm = _lock(adm)
        o.admission = adm
        o.recorded_at = parse_when(data.get('recorded_at'), adm)
        o.staff = by
        o.news_score = news2(o, getattr(adm.patient, 'age', None))
        o.save()
    return o


def void_observation(o, *, by, reason):
    with transaction.atomic():
        adm = _lock(o.admission)
        o = Observation.objects.select_for_update().get(pk=o.pk)
        return _void(o, adm, by, reason, f'Observation of {timezone.localtime(o.recorded_at):%d %b %H:%M}')


# ------------------------------------------------------------------------------------------------
# Fluid balance
# ------------------------------------------------------------------------------------------------
def add_fluid(adm, *, by, data):
    kind = data.get('kind')
    route = data.get('route')
    if kind not in ('in', 'out'):
        raise AdmissionError('Choose intake or output.', 'kind')
    allowed = FLUID_IN_ROUTES if kind == 'in' else FLUID_OUT_ROUTES
    if route not in allowed:
        raise AdmissionError('Choose a valid route for this entry.', 'route')
    vol = _num(data.get('volume_ml'), 'Volume (ml)', 1, 10000, integer=True)
    if vol is None:
        raise AdmissionError('Enter the volume in ml.', 'volume')
    with transaction.atomic():
        adm = _lock(adm)
        return FluidEntry.objects.create(
            admission=adm, kind=kind, route=route, volume_ml=vol,
            fluid=_text(data.get('fluid'), 'Fluid', required=False, max_len=120),
            notes=_text(data.get('notes'), 'Notes', required=False, max_len=300),
            recorded_at=parse_when(data.get('recorded_at'), adm), staff=by)


def void_fluid(f, *, by, reason):
    with transaction.atomic():
        adm = _lock(f.admission)
        f = FluidEntry.objects.select_for_update().get(pk=f.pk)
        return _void(f, adm, by, reason, f'Fluid entry ({f.volume_ml} ml)')


def fluid_days(entries):
    """Per-day totals for a list of non-voided FluidEntry rows, newest day first."""
    days = {}
    for e in entries:
        if e.voided_at:
            continue
        d = timezone.localtime(e.recorded_at).date()
        row = days.setdefault(d, {'date': d.isoformat(), 'intake': 0, 'output': 0, 'urine': 0})
        if e.kind == 'in':
            row['intake'] += e.volume_ml
        else:
            row['output'] += e.volume_ml
            if e.route == 'urine':
                row['urine'] += e.volume_ml
    out = []
    for d in sorted(days, reverse=True):
        r = days[d]
        r['balance'] = r['intake'] - r['output']
        out.append(r)
    return out


# ------------------------------------------------------------------------------------------------
# Schedules (shared by medications and treatment orders)
# ------------------------------------------------------------------------------------------------
def _aware(d, t):
    return timezone.make_aware(datetime.combine(d, t))


def order_slots(*, frequency, start_date, stop_date, ordered_at, discontinued_at, date_from, date_to):
    """Scheduled times of a regular order between two dates (inclusive)."""
    if frequency == 'stat':
        return [ordered_at] if ordered_at and date_from <= timezone.localtime(ordered_at).date() <= date_to else []
    times = FREQUENCY_TIMES.get(frequency)
    if not times:
        return []
    first = max(start_date, date_from)
    last = min(stop_date or date_to, date_to)
    out = []
    d = first
    ordered_day = timezone.localtime(ordered_at).date() if ordered_at else None
    while d <= last:
        for t in times:
            slot = _aware(d, t)
            # On the day of the order, times already past when it was written are not owed.
            if ordered_day == d == start_date and slot < ordered_at - timedelta(minutes=30):
                continue
            if discontinued_at and slot > discontinued_at:
                continue
            out.append(slot)
        d += timedelta(days=1)
    return out


def slot_state(slot, recorded_status, now=None):
    if recorded_status:
        return recorded_status
    now = now or timezone.now()
    if slot < now - DUE_WINDOW:
        return 'overdue'
    if slot <= now + DUE_WINDOW:
        return 'due'
    return 'scheduled'


# ------------------------------------------------------------------------------------------------
# Medications (drug chart / MAR)
# ------------------------------------------------------------------------------------------------
def _rx_ct():
    return ContentType.objects.get_for_model(DrugPrescription)


def prescribe(adm, *, by, data):
    ptype = data.get('prescription_type') or 'regular'
    if ptype not in PRESCRIPTION_TYPES:
        raise AdmissionError('Choose the prescription type.', 'prescription_type')
    route = data.get('route')
    if route not in ROUTE_LABELS:
        raise AdmissionError('Choose the route.', 'route')
    freq = data.get('frequency') or ('stat' if ptype == 'stat' else 'prn' if ptype == 'prn' else '')
    if ptype == 'stat':
        freq = 'stat'
    elif ptype == 'prn':
        freq = 'prn'
    if freq not in FREQUENCY_LABELS or (ptype in ('regular', 'glycemic') and freq in ('stat', 'prn')):
        raise AdmissionError('Choose how often the drug is given.', 'frequency')
    today = timezone.localdate()
    start = _date(data.get('start_date'), 'Start date', today)
    if start < today - timedelta(days=1):
        raise AdmissionError('Start date cannot be more than a day in the past.', 'start_date')
    stop = None
    days = _num(data.get('duration_days'), 'Duration (days)', 1, 90, integer=True)
    if days:
        stop = start + timedelta(days=days - 1)
    stop = _date(data.get('stop_date'), 'Stop date', stop)
    if stop and stop < start:
        raise AdmissionError('Stop date is before the start date.', 'stop_date')
    if ptype == 'stat':
        start, stop = today, today
    prn_max = None
    if ptype == 'prn':
        prn_max = _num(data.get('prn_max_per_day'), 'Maximum doses in 24 hours', 1, 24, integer=True)
        if prn_max is None:
            raise AdmissionError('Enter the maximum number of doses allowed in 24 hours.', 'prn_max_required')
    form = _text(data.get('dosage_form'), 'Dosage form', required=False, max_len=30)
    strength = _text(data.get('strength'), 'Strength', required=False, max_len=50)
    unit = _text(data.get('dose_unit'), 'Dose unit', required=False, max_len=20)
    qty = _num(data.get('dose_qty'), 'Dose', Decimal('0.01'), 10000)
    if qty is not None and not unit:
        raise AdmissionError('Choose the dose unit.', 'dose_unit')
    pay = data.get('pay_source') or ''
    if pay not in ('', 'plan', 'patient'):
        raise AdmissionError('Invalid payment source.', 'pay_source')
    if qty is not None:
        q = format(qty.normalize(), 'f')
        dose = f'{q} {unit}' + (f' ({strength})' if strength and strength.lower() != unit.lower() else '')
        dose = dose[:50]
    else:
        dose = _text(data.get('dose'), 'Dose', max_len=50)
    with transaction.atomic():
        adm = _lock(adm)
        rx = DrugPrescription.objects.create(
            patient=adm.patient, admission=adm, prescription_type=ptype,
            drug_name=_text(data.get('drug_name'), 'Drug', max_len=200),
            dose=dose, dosage_form=form, strength=strength, dose_qty=qty, dose_unit=unit,
            product_code=_text(data.get('product_code'), 'Product code', required=False, max_len=60),
            pay_source=pay, prn_max_per_day=prn_max,
            quantity=_num(data.get('quantity'), 'Quantity', 1, 1000, integer=True) or 1,
            route=route, frequency=freq, start_date=start, stop_date=stop, prescribed_by=by,
            notes=_text(data.get('notes'), 'Instructions', required=False, max_len=1000),
        )
        _event(adm, 'med_ordered', f'{rx.drug_name} {rx.dose} {ROUTE_LABELS[route]} {FREQUENCY_LABELS[freq]}'
                                   f'{f", max {prn_max} in 24 h" if prn_max else ""} ({PRESCRIPTION_TYPES[ptype]})', by)
        # Straight to the inpatient pharmacy and the bill.
        from .order_services import raise_supply
        rx.supply, rx.supply_warning = raise_supply(adm, rx, by=by, qty=rx.quantity, kind='initial')
    return rx


def discontinue_medication(rx, *, by, reason):
    reason = _text(reason, 'Reason', max_len=500)
    with transaction.atomic():
        adm = _lock(rx.admission)
        rx = DrugPrescription.objects.select_for_update().get(pk=rx.pk)
        if not rx.is_active:
            raise AdmissionError('This medication is already stopped.', 'already_stopped')
        rx.is_active = False
        rx.discontinued_at = timezone.now()
        rx.discontinued_by = by
        rx.discontinue_reason = reason
        rx.save(update_fields=['is_active', 'discontinued_at', 'discontinued_by', 'discontinue_reason'])
        # Remove still-pending future schedule rows (created by the legacy signal).
        DrugAdministration.objects.filter(content_type=_rx_ct(), object_id=rx.pk, status='pending',
                                          scheduled_time__gt=rx.discontinued_at).delete()
        _event(adm, 'med_stopped', f'{rx.drug_name} {rx.dose} stopped: {reason}', by)
        from .order_services import cancel_pending_supplies
        rx.supply_warning = cancel_pending_supplies(rx, by=by, reason=f'Order stopped: {reason}')
    return rx


def rx_slots(rx, date_from, date_to):
    if rx.prescription_type == 'prn' or rx.frequency == 'prn':
        return []
    return order_slots(frequency=rx.frequency, start_date=rx.start_date, stop_date=rx.stop_date,
                       ordered_at=rx.prescribed_at, discontinued_at=rx.discontinued_at,
                       date_from=date_from, date_to=date_to)


PRN_WINDOW = timedelta(hours=24)


def prn_given_24h(rx, now=None):
    """PRN doses given in the last 24 hours (newest first)."""
    now = now or timezone.now()
    return list(DrugAdministration.objects.filter(
        content_type=_rx_ct(), object_id=rx.pk, status='administered',
        scheduled_time__gt=now - PRN_WINDOW, scheduled_time__lte=now).order_by('-scheduled_time')
        .values_list('scheduled_time', flat=True))


def prn_next_allowed(rx, now=None):
    """When the next PRN dose is allowed, or None if one may be given now (or there is no limit)."""
    if not rx.prn_max_per_day:
        return None
    times = prn_given_24h(rx, now)
    if len(times) < rx.prn_max_per_day:
        return None
    # The window frees up when the oldest dose that keeps it full drops out.
    return times[rx.prn_max_per_day - 1] + PRN_WINDOW


def administer(rx, *, by, data):
    """Chart one dose. data: scheduled_time (ISO, omit for PRN), status, dose_given, comment, given_at."""
    status = data.get('status') or 'administered'
    if status not in DOSE_STATUSES:
        raise AdmissionError('Choose given, refused, withheld or missed.', 'status')
    comment = _text(data.get('comment'), 'Comment', required=False, max_len=1000)
    if status in ('refused', 'held', 'missed') and not comment:
        raise AdmissionError(f'Say why the dose was {DOSE_STATUSES[status].lower()}.', 'reason_required')
    now = timezone.now()
    with transaction.atomic():
        adm = _lock(rx.admission)
        rx = DrugPrescription.objects.select_for_update().get(pk=rx.pk)
        is_prn = rx.prescription_type == 'prn' or rx.frequency == 'prn'
        given_at = parse_when(data.get('given_at'), adm, 'Time given') if data.get('given_at') else now
        ct = _rx_ct()
        if is_prn:
            if not rx.is_active:
                raise AdmissionError('This medication has been stopped.', 'stopped')
            if status != 'administered':
                raise AdmissionError('For an as-needed (PRN) drug, only chart doses that were given.', 'prn_given_only')
            if rx.prn_max_per_day:
                given = DrugAdministration.objects.filter(content_type=ct, object_id=rx.pk, status='administered')
                before = given.filter(scheduled_time__gt=given_at - PRN_WINDOW, scheduled_time__lte=given_at).count()
                after = given.filter(scheduled_time__gte=given_at, scheduled_time__lt=given_at + PRN_WINDOW).count()
                if max(before, after) >= rx.prn_max_per_day:
                    nxt = prn_next_allowed(rx)
                    when = f' The next dose is allowed from {timezone.localtime(nxt):%d/%m/%Y %H:%M}.' if nxt else ''
                    raise AdmissionError(
                        f'Maximum reached: {rx.prn_max_per_day} dose{"s" if rx.prn_max_per_day != 1 else ""} of '
                        f'{rx.drug_name} in 24 hours.{when} Ask the doctor to review if more is needed.',
                        'prn_max_reached')
            slot = given_at
        else:
            raw = data.get('scheduled_time')
            if not raw:
                raise AdmissionError('Choose the dose time.', 'slot_required')
            try:
                slot = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
            except ValueError:
                raise AdmissionError('Invalid dose time.', 'slot_invalid')
            if timezone.is_naive(slot):
                slot = timezone.make_aware(slot)
            d = timezone.localtime(slot).date()
            valid = rx_slots(rx, d, d)
            match = next((s for s in valid if abs((s - slot).total_seconds()) < 60), None)
            if not match:
                raise AdmissionError('That is not a dose time for this medication (stopped or outside its dates).',
                                     'slot_invalid')
            slot = match
            if slot - now > EARLY_LIMIT:
                raise AdmissionError('This dose is not due yet. You can chart it from 2 hours before its time.',
                                     'too_early')
            if DrugAdministration.objects.filter(content_type=ct, object_id=rx.pk, scheduled_time=slot) \
                    .exclude(status='pending').exists():
                raise AdmissionError('This dose has already been charted.', 'already_charted')
            # The time the drug actually went in (nurses often chart after the round):
            # it may be later than the dose time, but not before it could be given.
            if status == 'administered' and given_at < slot - EARLY_LIMIT:
                raise AdmissionError(
                    f'Time given is more than 2 hours before this dose was due '
                    f'({timezone.localtime(slot):%d/%m %H:%M}). Check the time.', 'given_too_early')
        values = dict(status=status, administered_by=by, comments=comment,
                      administered_time=given_at if status == 'administered' else None,
                      dose_given=_text(data.get('dose_given') or rx.dose, 'Dose given', max_len=50),
                      batch_no=_text(data.get('batch_no'), 'Batch no.', required=False, max_len=100),
                      action=status)
        pending = None if is_prn else DrugAdministration.objects.filter(
            content_type=ct, object_id=rx.pk, scheduled_time=slot, status='pending').first()
        if pending:
            for k, v in values.items():
                setattr(pending, k, v)
            pending.save()
            return pending
        return DrugAdministration.objects.create(content_type=ct, object_id=rx.pk, scheduled_time=slot, **values)


BULK_MAX = 30


def administer_bulk(adm, *, by, data):
    """Chart several scheduled doses given together on one round, under one signature.

    data: doses [{prescription_id, scheduled_time, dose_given?}], given_at, comment.
    All or nothing: if any dose fails, none is charted and the error names the drug.
    """
    items = data.get('doses') or []
    if not isinstance(items, list) or not items:
        raise AdmissionError('Choose at least one dose to chart.', 'doses_required')
    if len(items) > BULK_MAX:
        raise AdmissionError(f'Chart at most {BULK_MAX} doses at a time.', 'too_many')
    seen = set()
    for it in items:
        key = (str(it.get('prescription_id')), str(it.get('scheduled_time')))
        if key in seen:
            raise AdmissionError('The same dose was chosen twice.', 'duplicate')
        seen.add(key)
    rx_ids = {it.get('prescription_id') for it in items}
    rxs = {rx.pk: rx for rx in DrugPrescription.objects.filter(admission=adm, pk__in=[i for i in rx_ids if str(i).isdigit()])}
    out = []
    with transaction.atomic():
        for it in items:
            rx = rxs.get(int(it['prescription_id'])) if str(it.get('prescription_id')).isdigit() else None
            if not rx:
                raise AdmissionError('One of the chosen medications is not on this patient\'s chart.', 'rx_not_found')
            if rx.prescription_type == 'prn' or rx.frequency == 'prn':
                raise AdmissionError(f'{rx.drug_name} is as-needed (PRN); chart it on its own with "Give dose".', 'prn_not_bulk')
            try:
                out.append(administer(rx, by=by, data={
                    'status': 'administered', 'scheduled_time': it.get('scheduled_time'),
                    'dose_given': it.get('dose_given') or rx.dose, 'given_at': data.get('given_at'),
                    'comment': data.get('comment'),
                }))
            except AdmissionError as e:
                raise AdmissionError(f'{rx.drug_name}: {e}', getattr(e, 'code', 'invalid'))
    return out


# ------------------------------------------------------------------------------------------------
# Treatment orders (treatment chart / execute order)
# ------------------------------------------------------------------------------------------------
def order_treatment(adm, *, by, data):
    cat = data.get('category') or 'nursing'
    if cat not in dict(TREATMENT_CATEGORIES):
        raise AdmissionError('Choose the type of treatment.', 'category')
    freq = data.get('frequency') or 'od'
    if freq not in FREQUENCY_LABELS:
        raise AdmissionError('Choose how often it is done.', 'frequency')
    today = timezone.localdate()
    start = _date(data.get('start_date'), 'Start date', today)
    if start < today - timedelta(days=1):
        raise AdmissionError('Start date cannot be more than a day in the past.', 'start_date')
    stop = _date(data.get('stop_date'), 'Stop date')
    days = _num(data.get('duration_days'), 'Duration (days)', 1, 90, integer=True)
    if days and not stop:
        stop = start + timedelta(days=days - 1)
    if stop and stop < start:
        raise AdmissionError('Stop date is before the start date.', 'stop_date')
    if freq == 'stat':
        start, stop = today, today
    with transaction.atomic():
        adm = _lock(adm)
        t = TreatmentOrder.objects.create(admission=adm, category=cat, frequency=freq, start_date=start,
                                          stop_date=stop, ordered_by=by,
                                          instruction=_text(data.get('instruction'), 'Instruction', max_len=2000))
        _event(adm, 'treatment_ordered', f'{t.get_category_display()}: {t.instruction[:200]} ({FREQUENCY_LABELS[freq]})', by)
    return t


def discontinue_treatment(t, *, by, reason):
    reason = _text(reason, 'Reason', max_len=500)
    with transaction.atomic():
        adm = _lock(t.admission)
        t = TreatmentOrder.objects.select_for_update().get(pk=t.pk)
        if not t.is_active:
            raise AdmissionError('This order is already stopped.', 'already_stopped')
        t.is_active = False
        t.discontinued_at = timezone.now()
        t.discontinued_by = by
        t.discontinue_reason = reason
        t.save(update_fields=['is_active', 'discontinued_at', 'discontinued_by', 'discontinue_reason'])
        _event(adm, 'treatment_stopped', f'{t.instruction[:200]} stopped: {reason}', by)
    return t


def treatment_slots(t, date_from, date_to):
    if t.frequency == 'prn':
        return []
    return order_slots(frequency=t.frequency, start_date=t.start_date, stop_date=t.stop_date,
                       ordered_at=t.ordered_at, discontinued_at=t.discontinued_at,
                       date_from=date_from, date_to=date_to)


def record_treatment(t, *, by, data):
    status = data.get('status') or 'done'
    if status not in TREATMENT_STATUSES:
        raise AdmissionError('Choose done, not done or refused.', 'status')
    comment = _text(data.get('comment'), 'Comment', required=False, max_len=1000)
    if status != 'done' and not comment:
        raise AdmissionError('Say why it was not done.', 'reason_required')
    now = timezone.now()
    with transaction.atomic():
        adm = _lock(t.admission)
        t = TreatmentOrder.objects.select_for_update().get(pk=t.pk)
        slot = None
        if t.frequency != 'prn':
            raw = data.get('scheduled_time')
            if not raw:
                raise AdmissionError('Choose the scheduled time.', 'slot_required')
            try:
                slot = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
            except ValueError:
                raise AdmissionError('Invalid time.', 'slot_invalid')
            if timezone.is_naive(slot):
                slot = timezone.make_aware(slot)
            d = timezone.localtime(slot).date()
            match = next((s for s in treatment_slots(t, d, d) if abs((s - slot).total_seconds()) < 60), None)
            if not match:
                raise AdmissionError('That is not a scheduled time for this order.', 'slot_invalid')
            slot = match
            if slot - now > EARLY_LIMIT:
                raise AdmissionError('Not due yet. You can chart it from 2 hours before its time.', 'too_early')
        elif not t.is_active:
            raise AdmissionError('This order has been stopped.', 'stopped')
        try:
            with transaction.atomic():
                return TreatmentRecord.objects.create(order=t, scheduled_time=slot, status=status, comment=comment,
                                                      performed_at=now, staff=by)
        except IntegrityError:
            raise AdmissionError('This has already been charted.', 'already_charted')

