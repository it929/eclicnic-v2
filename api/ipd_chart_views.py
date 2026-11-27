"""
Inpatient chart API (rules in IPD/chart_services.py).

    GET   ipd/admissions/<id>/chart/                 overview: patient, latest obs + NEWS2, doses due, fluids today
    GET   ipd/admissions/<id>/notes/?type=           notes (new + legacy, newest first)
    POST  ipd/admissions/<id>/notes/                 {note_type, title?, body}                  signed-in user
    GET   ipd/admissions/<id>/observations/
    POST  ipd/admissions/<id>/observations/          {temperature, pulse, ..., recorded_at?}    signed-in user
    GET   ipd/admissions/<id>/fluids/
    POST  ipd/admissions/<id>/fluids/                {kind, route, volume_ml, fluid?, recorded_at?}
    POST  ipd/chart-entries/<kind>/<id>/void/        {reason, pin}   kind = note | observation | fluid
    GET   ipd/admissions/<id>/medications/?from=&to= orders + dose times + what was charted
    POST  ipd/admissions/<id>/medications/           {drug_name, dose, route, frequency, prescription_type, ..., pin}
    POST  ipd/medications/<rx>/administer/           {scheduled_time?, status, dose_given?, comment?, pin}
    POST  ipd/medications/<rx>/discontinue/          {reason, pin}
    GET   ipd/admissions/<id>/treatments/?from=&to=
    POST  ipd/admissions/<id>/treatments/            {category, instruction, frequency, start_date?, duration_days?, pin}
    POST  ipd/treatments/<t>/record/                 {scheduled_time?, status, comment?, pin}
    POST  ipd/treatments/<t>/discontinue/            {reason, pin}
"""
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from IPD import chart_services as cs
from IPD.models import (
    CONSCIOUSNESS, FLUID_IN_ROUTES, FLUID_OUT_ROUTES, FLUID_ROUTES, NOTE_TYPES, TREATMENT_CATEGORIES,
    AdmissionNote, AdmissionTable, ClinicalNote, DoctorNote, DrugAdministration, DrugPrescription, FluidEntry,
    NurseNote, Observation, TreatmentOrder, WardRound,
)
from IPD.services import AdmissionError, staff_name
from inventory.permissions import is_admin

from .ipd_views import _admission_qs, _dt, _err, _parse_date, _pin_user, admission_row

ROUTE_NAMES = dict(FLUID_ROUTES)
CONSC = dict(CONSCIOUSNESS)


class _Auth(APIView):
    permission_classes = [permissions.IsAuthenticated]


def _adm(pk):
    return get_object_or_404(_admission_qs(), pk=pk)


def _range(request, default_back=5, default_ahead=1, max_days=31):
    today = timezone.localdate()
    d_from = _parse_date(request.query_params.get('from')) or today - timedelta(days=default_back)
    d_to = _parse_date(request.query_params.get('to')) or today + timedelta(days=default_ahead)
    if d_to < d_from:
        d_from, d_to = d_to, d_from
    if (d_to - d_from).days > max_days:
        d_from = d_to - timedelta(days=max_days)
    return d_from, d_to


def _void_info(e):
    if not e.voided_at:
        return None
    return {'at': _dt(e.voided_at), 'by': staff_name(e.voided_by), 'reason': e.void_reason}


# ------------------------------------------------------------------------------------------------
# serializers
# ------------------------------------------------------------------------------------------------
NOTE_LABELS = dict(NOTE_TYPES)


def note_row(n):
    return {'id': n.id, 'kind': 'note', 'note_type': n.note_type, 'note_type_label': NOTE_LABELS.get(n.note_type),
            'title': n.title, 'body': n.body, 'staff': staff_name(n.staff), 'staff_id': n.staff_id,
            'at': _dt(n.created_at), 'voided': _void_info(n), 'legacy': False}


LEGACY_NOTES = [
    (AdmissionNote, 'admission_note', 'admission'),
    (DoctorNote, 'doctor_note', 'doctor'),
    (NurseNote, 'nurse_note', 'nursing'),
    (WardRound, 'notes', 'ward_round'),
]


def legacy_notes(adm):
    out = []
    for model, field, ntype in LEGACY_NOTES:
        for n in model.objects.filter(admission=adm).select_related('staff'):
            out.append({'id': f'legacy-{ntype}-{n.id}', 'kind': 'legacy', 'note_type': ntype,
                        'note_type_label': NOTE_LABELS.get(ntype), 'title': '', 'body': getattr(n, field) or '',
                        'staff': staff_name(n.staff), 'staff_id': n.staff_id, 'at': _dt(n.created_date),
                        'voided': None, 'legacy': True})
    return out


def obs_row(o):
    red = cs.news_red_flag(o)
    return {
        'id': o.id, 'recorded_at': _dt(o.recorded_at),
        'temperature': float(o.temperature) if o.temperature is not None else None,
        'pulse': o.pulse, 'resp_rate': o.resp_rate, 'bp_systolic': o.bp_systolic, 'bp_diastolic': o.bp_diastolic,
        'spo2': o.spo2, 'on_oxygen': o.on_oxygen,
        'oxygen_lpm': float(o.oxygen_lpm) if o.oxygen_lpm is not None else None,
        'consciousness': o.consciousness, 'consciousness_label': CONSC.get(o.consciousness),
        'pain_score': o.pain_score,
        'blood_glucose': float(o.blood_glucose) if o.blood_glucose is not None else None,
        'weight': float(o.weight) if o.weight is not None else None,
        'news_score': o.news_score, 'news_red_flag': red, 'news_risk': cs.news_risk(o.news_score, red),
        'notes': o.notes, 'staff': staff_name(o.staff), 'voided': _void_info(o),
    }


def fluid_row(f):
    return {'id': f.id, 'kind': f.kind, 'route': f.route, 'route_label': ROUTE_NAMES.get(f.route),
            'fluid': f.fluid, 'volume_ml': f.volume_ml, 'recorded_at': _dt(f.recorded_at), 'notes': f.notes,
            'staff': staff_name(f.staff), 'voided': _void_info(f)}


def _dose_row(a):
    return {'id': a.id, 'status': a.status, 'status_label': cs.DOSE_STATUSES.get(a.status, a.status),
            'scheduled_time': _dt(a.scheduled_time), 'given_at': _dt(a.administered_time or a.updated_at),
            'by': staff_name(a.administered_by), 'dose_given': a.dose_given, 'comment': a.comments,
            'batch_no': a.batch_no,
            # When it was entered in the system (can be after the time given).
            'charted_at': _dt(a.updated_at)}


def medication_rows(adm, d_from, d_to, now=None):
    now = now or timezone.now()
    ct = cs._rx_ct()
    rxs = list(DrugPrescription.objects.filter(admission=adm).select_related('prescribed_by', 'discontinued_by')
               .prefetch_related('supplies__store', 'supplies__product', 'supplies__charge', 'supplies__requested_by', 'supplies__dispensed_by')
               .order_by('-is_active', 'prescription_type', 'drug_name', 'id'))
    charted = {}
    for a in (DrugAdministration.objects.filter(content_type=ct, object_id__in=[r.id for r in rxs])
              .exclude(status='pending').select_related('administered_by').order_by('scheduled_time')):
        charted.setdefault(a.object_id, []).append(a)
    out = []
    for rx in rxs:
        recs = charted.get(rx.id, [])
        by_slot = {a.scheduled_time: a for a in recs}
        slots = []
        for s in cs.rx_slots(rx, d_from, d_to):
            a = by_slot.get(s)
            slots.append({'time': _dt(s), 'state': cs.slot_state(s, a.status if a else None, now),
                          'dose': _dose_row(a) if a else None})
        is_prn = rx.prescription_type == 'prn' or rx.frequency == 'prn'
        prn = [_dose_row(a) for a in recs if is_prn and d_from <= timezone.localtime(a.scheduled_time).date() <= d_to]
        last = recs[-1] if recs else None
        out.append({
            'id': rx.id, 'drug_name': rx.drug_name, 'dose': rx.dose, 'quantity': rx.quantity,
            'dosage_form': rx.dosage_form, 'strength': rx.strength, 'pay_source': rx.pay_source,
            'route': rx.route, 'route_label': cs.ROUTE_LABELS.get(rx.route, rx.route),
            'frequency': rx.frequency, 'frequency_label': cs.FREQUENCY_LABELS.get(rx.frequency, rx.frequency),
            'prescription_type': rx.prescription_type,
            'prescription_type_label': cs.PRESCRIPTION_TYPES.get(rx.prescription_type),
            'start_date': rx.start_date.isoformat() if rx.start_date else None,
            'stop_date': rx.stop_date.isoformat() if rx.stop_date else None,
            'notes': rx.notes, 'prescribed_by': staff_name(rx.prescribed_by), 'prescribed_at': _dt(rx.prescribed_at),
            'is_active': rx.is_active and not (rx.stop_date and rx.stop_date < timezone.localdate()),
            'discontinued_at': _dt(rx.discontinued_at), 'discontinued_by': staff_name(rx.discontinued_by),
            'discontinue_reason': rx.discontinue_reason,
            'slots': slots, 'prn_doses': prn, 'is_prn': is_prn,
            'prn_max_per_day': rx.prn_max_per_day,
            'prn_given_24h': len(cs.prn_given_24h(rx, now)) if is_prn else 0,
            'prn_next_at': _dt(cs.prn_next_allowed(rx, now)) if is_prn else None,
            'last_dose': _dose_row(last) if last else None,
            'doses_given': sum(1 for a in recs if a.status == 'administered'),
            'supplies': [supply_row(s) for s in rx.supplies.all()],
        })
    return out


def _record_row(r):
    return {'id': r.id, 'status': r.status, 'status_label': cs.TREATMENT_STATUSES.get(r.status),
            'scheduled_time': _dt(r.scheduled_time), 'at': _dt(r.performed_at), 'by': staff_name(r.staff),
            'comment': r.comment}


def treatment_rows(adm, d_from, d_to, now=None):
    now = now or timezone.now()
    out = []
    cats = dict(TREATMENT_CATEGORIES)
    for t in (TreatmentOrder.objects.filter(admission=adm).select_related('ordered_by', 'discontinued_by')
              .prefetch_related('records__staff').order_by('-is_active', 'category', 'id')):
        recs = list(t.records.all())
        by_slot = {r.scheduled_time: r for r in recs if r.scheduled_time}
        slots = []
        for s in cs.treatment_slots(t, d_from, d_to):
            r = by_slot.get(s)
            slots.append({'time': _dt(s), 'state': cs.slot_state(s, r.status if r else None, now),
                          'record': _record_row(r) if r else None})
        out.append({
            'id': t.id, 'category': t.category, 'category_label': cats.get(t.category),
            'instruction': t.instruction, 'frequency': t.frequency,
            'frequency_label': cs.FREQUENCY_LABELS.get(t.frequency, t.frequency),
            'start_date': t.start_date.isoformat(), 'stop_date': t.stop_date.isoformat() if t.stop_date else None,
            'ordered_by': staff_name(t.ordered_by), 'ordered_at': _dt(t.ordered_at),
            'is_active': t.is_active and not (t.stop_date and t.stop_date < timezone.localdate()),
            'discontinued_at': _dt(t.discontinued_at), 'discontinued_by': staff_name(t.discontinued_by),
            'discontinue_reason': t.discontinue_reason, 'is_prn': t.frequency == 'prn',
            'slots': slots,
            'prn_records': [_record_row(r) for r in recs if not r.scheduled_time
                            and d_from <= timezone.localtime(r.performed_at).date() <= d_to],
        })
    return out


def _options():
    return {
        'note_types': [{'value': v, 'label': l} for v, l in NOTE_TYPES],
        'routes': [{'value': v, 'label': l} for v, l in DrugPrescription.ROUTES],
        'frequencies': [{'value': v, 'label': l} for v, l in DrugPrescription.FREQUENCY],
        'prescription_types': [{'value': v, 'label': l} for v, l in DrugPrescription.PRESCRIPTION_TYPES],
        'treatment_categories': [{'value': v, 'label': l} for v, l in TREATMENT_CATEGORIES],
        'consciousness': [{'value': v, 'label': l} for v, l in CONSCIOUSNESS],
        'fluid_in_routes': [{'value': v, 'label': ROUTE_NAMES[v]} for v in FLUID_IN_ROUTES],
        'fluid_out_routes': [{'value': v, 'label': ROUTE_NAMES[v]} for v in FLUID_OUT_ROUTES],
        'frequency_times': {k: [t.strftime('%H:%M') for t in v] for k, v in cs.FREQUENCY_TIMES.items()},
    }


# ------------------------------------------------------------------------------------------------
# views
# ------------------------------------------------------------------------------------------------
class ChartOverviewView(_Auth):
    def get(self, request, pk):
        adm = _adm(pk)
        now = timezone.now()
        today = timezone.localdate()
        row = admission_row(adm)
        row['notes'] = adm.notes
        row['discharge_summary'] = adm.discharge_summary
        p = adm.patient
        row['patient']['allergies'] = (getattr(p, 'allergies', '') or '').strip()

        obs = [o for o in adm.observations.select_related('staff').filter(voided_at__isnull=True)[:2]]
        meds = medication_rows(adm, today - timedelta(days=1), today, now)
        treats = treatment_rows(adm, today - timedelta(days=1), today, now)
        due = []
        for m in meds:
            for s in m['slots']:
                if s['state'] in ('due', 'overdue'):
                    due.append({'type': 'medication', 'order_id': m['id'], 'time': s['time'], 'state': s['state'],
                                'title': f"{m['drug_name']} {m['dose']}",
                                'sub': f"{m['route_label']} · {m['frequency_label']}",
                                'order': {k: m[k] for k in ('id', 'drug_name', 'dose', 'route_label', 'frequency_label',
                                                            'notes', 'last_dose')}})
        for t in treats:
            for s in t['slots']:
                if s['state'] in ('due', 'overdue'):
                    due.append({'type': 'treatment', 'order_id': t['id'], 'time': s['time'], 'state': s['state'],
                                'title': t['instruction'], 'sub': f"{t['category_label']} · {t['frequency_label']}",
                                'order': {k: t[k] for k in ('id', 'instruction', 'category_label', 'frequency_label')}})
        due.sort(key=lambda x: x['time'])

        fluids = list(adm.fluid_entries.filter(voided_at__isnull=True,
                                               recorded_at__date__gte=today - timedelta(days=1)))
        days = cs.fluid_days(fluids)
        today_fluid = next((d for d in days if d['date'] == today.isoformat()),
                           {'date': today.isoformat(), 'intake': 0, 'output': 0, 'urine': 0, 'balance': 0})
        notes = [note_row(n) for n in adm.clinical_notes.select_related('staff').filter(voided_at__isnull=True)[:3]]
        if len(notes) < 3:
            notes += sorted(legacy_notes(adm), key=lambda n: n['at'] or '', reverse=True)[:3 - len(notes)]

        return Response({
            'admission': row,
            'latest_obs': obs_row(obs[0]) if obs else None,
            'previous_obs': obs_row(obs[1]) if len(obs) > 1 else None,
            'due': due,
            'fluid_today': today_fluid,
            'recent_notes': notes,
            'counts': {
                'active_medications': sum(1 for m in meds if m['is_active']),
                'active_treatments': sum(1 for t in treats if t['is_active']),
                'notes': adm.clinical_notes.filter(voided_at__isnull=True).count(),
                'observations': adm.observations.filter(voided_at__isnull=True).count(),
            },
            'options': _options(),
            'now': _dt(now),
        })


class NotesView(_Auth):
    def get(self, request, pk):
        adm = _adm(pk)
        rows = [note_row(n) for n in adm.clinical_notes.select_related('staff', 'voided_by')] + legacy_notes(adm)
        t = request.query_params.get('type')
        if t:
            rows = [r for r in rows if r['note_type'] == t]
        rows.sort(key=lambda r: r['at'] or '', reverse=True)
        return Response({'results': rows})

    def post(self, request, pk):
        adm = _adm(pk)
        d = request.data
        try:
            n = cs.add_note(adm, by=request.user, note_type=d.get('note_type'), body=d.get('body'), title=d.get('title'))
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': 'Note saved.', 'note': note_row(n)}, status=201)


class ObservationsView(_Auth):
    def get(self, request, pk):
        adm = _adm(pk)
        qs = adm.observations.select_related('staff', 'voided_by')[:300]
        return Response({'results': [obs_row(o) for o in qs],
                         'news_applicable': (adm.patient.age if adm.patient and adm.patient.age is not None else 99) >= 16})

    def post(self, request, pk):
        adm = _adm(pk)
        try:
            o = cs.add_observation(adm, by=request.user, data=request.data)
        except AdmissionError as e:
            return _err(e)
        row = obs_row(o)
        return Response({'detail': 'Observations saved.', 'observation': row}, status=201)


class FluidsView(_Auth):
    def get(self, request, pk):
        adm = _adm(pk)
        rows = list(adm.fluid_entries.select_related('staff', 'voided_by')[:1000])
        return Response({'results': [fluid_row(f) for f in rows], 'days': cs.fluid_days(rows)})

    def post(self, request, pk):
        adm = _adm(pk)
        try:
            f = cs.add_fluid(adm, by=request.user, data=request.data)
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': 'Saved.', 'entry': fluid_row(f)}, status=201)


class VoidEntryView(_Auth):
    MODELS = {'note': (ClinicalNote, cs.void_note), 'observation': (Observation, cs.void_observation),
              'fluid': (FluidEntry, cs.void_fluid)}

    def post(self, request, kind, pk):
        if kind not in self.MODELS:
            return Response({'error': 'Unknown entry type.'}, status=404)
        model, fn = self.MODELS[kind]
        entry = get_object_or_404(model.objects.select_related('admission'), pk=pk)
        user, err = _pin_user(request, 'mark this entry as entered in error')
        if err:
            return err
        author = getattr(entry, 'staff_id', None)
        if author and user.pk != author and not is_admin(user):
            return Response({'error': 'Only the person who made this entry (or an administrator) can mark it as an error.',
                             'code': 'not_author'}, status=403)
        try:
            fn(entry, by=user, reason=request.data.get('reason'))
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': 'Marked as entered in error.'})


class MedicationsView(_Auth):
    def get(self, request, pk):
        adm = _adm(pk)
        d_from, d_to = _range(request)
        return Response({'from': d_from.isoformat(), 'to': d_to.isoformat(), 'now': _dt(timezone.now()),
                         'results': medication_rows(adm, d_from, d_to)})

    def post(self, request, pk):
        adm = _adm(pk)
        if adm.is_open is False:
            return Response({'error': 'This admission is closed.', 'code': 'admission_closed'}, status=400)
        user, err = _pin_user(request, 'sign this medication order')
        if err:
            return err
        try:
            rx = cs.prescribe(adm, by=user, data=request.data)
        except AdmissionError as e:
            return _err(e)
        sent = getattr(rx, 'supply', None)
        msg = f'{rx.drug_name} {rx.dose} added to the drug chart'
        msg += f' and sent to {getattr(sent.store, "name", "the inpatient pharmacy")} ({sent.qty}).' if sent else '.'
        return Response({'detail': msg, 'id': rx.id, 'warning': getattr(rx, 'supply_warning', None)}, status=201)


class MedicationActionView(_Auth):
    PURPOSE = {'administer': 'chart this dose', 'discontinue': 'stop this medication'}

    def post(self, request, pk, action):
        if action not in self.PURPOSE:
            return Response({'error': f"Unknown action '{action}'."}, status=404)
        rx = get_object_or_404(DrugPrescription.objects.select_related('admission'), pk=pk)
        if not rx.admission_id:
            return Response({'error': 'This prescription is not linked to an admission.'}, status=400)
        user, err = _pin_user(request, self.PURPOSE[action])
        if err:
            return err
        try:
            if action == 'administer':
                a = cs.administer(rx, by=user, data=request.data)
                return Response({'detail': f'{rx.drug_name}: {cs.DOSE_STATUSES[a.status].lower()} '
                                           f'(signed by {staff_name(user)}).', 'dose': _dose_row(a)})
            rx = cs.discontinue_medication(rx, by=user, reason=request.data.get('reason'))
            return Response({'detail': f'{rx.drug_name} stopped.', 'warning': getattr(rx, 'supply_warning', None)})
        except AdmissionError as e:
            return _err(e)


class MedicationBulkAdministerView(_Auth):
    """Chart several doses given together on one round, with one PIN. All or nothing."""

    def post(self, request, pk):
        adm = _adm(pk)
        if adm.is_open is False:
            return Response({'error': 'This admission is closed.', 'code': 'admission_closed'}, status=400)
        user, err = _pin_user(request, 'chart these doses')
        if err:
            return err
        try:
            done = cs.administer_bulk(adm, by=user, data=request.data)
        except AdmissionError as e:
            return _err(e)
        n = len(done)
        return Response({'detail': f'{n} dose{"s" if n != 1 else ""} charted as given (signed by {staff_name(user)}).',
                         'doses': [_dose_row(a) for a in done]})


class TreatmentsView(_Auth):
    def get(self, request, pk):
        adm = _adm(pk)
        d_from, d_to = _range(request)
        return Response({'from': d_from.isoformat(), 'to': d_to.isoformat(), 'now': _dt(timezone.now()),
                         'results': treatment_rows(adm, d_from, d_to)})

    def post(self, request, pk):
        adm = _adm(pk)
        user, err = _pin_user(request, 'sign this treatment order')
        if err:
            return err
        try:
            t = cs.order_treatment(adm, by=user, data=request.data)
        except AdmissionError as e:
            return _err(e)
        return Response({'detail': 'Treatment order added.', 'id': t.id}, status=201)


class TreatmentActionView(_Auth):
    PURPOSE = {'record': 'chart this treatment', 'discontinue': 'stop this treatment order'}

    def post(self, request, pk, action):
        if action not in self.PURPOSE:
            return Response({'error': f"Unknown action '{action}'."}, status=404)
        t = get_object_or_404(TreatmentOrder.objects.select_related('admission'), pk=pk)
        user, err = _pin_user(request, self.PURPOSE[action])
        if err:
            return err
        try:
            if action == 'record':
                r = cs.record_treatment(t, by=user, data=request.data)
                return Response({'detail': f'Charted as {r.get_status_display().lower()} (signed by {staff_name(user)}).',
                                 'record': _record_row(r)})
            cs.discontinue_treatment(t, by=user, reason=request.data.get('reason'))
            return Response({'detail': 'Treatment order stopped.'})
        except AdmissionError as e:
            return _err(e)


def supply_row(s):
    return {
        'id': s.id, 'kind': s.kind, 'kind_label': s.get_kind_display(), 'qty': s.qty, 'status': s.status,
        'status_label': s.get_status_display(), 'store_name': getattr(s.store, 'name', None),
        'product_name': getattr(s.product, 'product_name', None), 'qty_dispensed': s.qty_dispensed,
        'requested_by': staff_name(s.requested_by), 'requested_at': _dt(s.requested_at),
        'dispensed_by': staff_name(s.dispensed_by), 'dispensed_at': _dt(s.dispensed_at),
        'cancelled_at': _dt(s.cancelled_at), 'cancel_reason': s.cancel_reason, 'notes': s.notes,
        'amount': float(s.charge.amount) if s.charge_id and not s.charge.reversed_at else None,
        'billed': bool(s.charge_id and not s.charge.reversed_at),
    }
