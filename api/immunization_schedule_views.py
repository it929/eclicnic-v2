"""
GET /api/immunizations/schedule/?from=YYYY-MM-DD&to=YYYY-MM-DD&search=&status=

Patients scheduled for immunization in a date range (default: today). Two sources:
  * booked visits    - PatientAppointment whose purpose mentions immunization / vaccine
  * next dose due    - ImmunizationRecord.next_due_date set when the last vaccines were given
                       (only the patient's most recent visit counts - an earlier due date is
                       replaced once the child has been seen again)
One row per patient per date. Status:
  attended  - vaccines were given that day (or the visit was marked completed)
  today     - due today, not yet given
  upcoming  - due later
  missed    - the date has passed and nothing was given
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.db.models import Max, Q
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from patients.models import PatientAppointment
from queue_operations.models import ImmunizationRecord

from .immunization_views import calculate_patient_age_details, compute_next_due_vaccines

MAX_DAYS = 366
IMM_PURPOSE = Q(purpose__icontains='immuniz') | Q(purpose__icontains='vaccin')


def _day(value, default):
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date() if value else default
    except ValueError:
        return default


class ImmunizationScheduleView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        today = date.today()
        d_from = _day(request.query_params.get('from'), today)
        d_to = _day(request.query_params.get('to'), d_from)
        if d_to < d_from:
            d_from, d_to = d_to, d_from
        if (d_to - d_from).days > MAX_DAYS:
            return Response({'error': f'Choose a range of at most {MAX_DAYS} days.'}, status=status.HTTP_400_BAD_REQUEST)
        search = str(request.query_params.get('search') or '').strip().lower()
        want = str(request.query_params.get('status') or '').strip().lower()

        rows = {}   # (patient_id, date) -> row

        def row_for(patient, day):
            key = (patient.id, day)
            if key not in rows:
                rows[key] = {'patient': patient, 'date': day, 'sources': set(), 'appointment_ids': [], 'open_appt': None,
                             'purposes': set(), 'due_from_records': [], 'completed_appt': False}
            return rows[key]

        # 1. Booked immunization visits
        appts = (PatientAppointment.objects.filter(arrival_date__range=(d_from, d_to)).filter(IMM_PURPOSE)
                 .exclude(patient__isnull=True).select_related('patient', 'patient__sponsor', 'patient__sponsor__category', 'patient__plan'))
        for a in appts:
            r = row_for(a.patient, a.arrival_date)
            r['sources'].add('appointment')
            r['appointment_ids'].append(a.id)
            if a.purpose:
                r['purposes'].add(a.purpose)
            if a.completed:
                r['completed_appt'] = True
            elif r['open_appt'] is None:
                r['open_appt'] = a.id      # the encounter is recorded against this booked visit

        # 2. Next dose due, from each patient's most recent vaccination visit
        due_recs = list(ImmunizationRecord.objects.filter(next_due_date__range=(d_from, d_to))
                        .select_related('patient', 'patient__sponsor', 'patient__sponsor__category', 'patient__plan'))
        latest = dict(ImmunizationRecord.objects.filter(patient_id__in={r.patient_id for r in due_recs})
                      .values('patient_id').annotate(last=Max('administered_date')).values_list('patient_id', 'last'))
        for rec in due_recs:
            if rec.patient is None or rec.administered_date != latest.get(rec.patient_id):
                continue
            r = row_for(rec.patient, rec.next_due_date)
            r['sources'].add('next_dose')
            r['last_visit'] = rec.administered_date

        # Vaccines actually given on each scheduled date
        pids = {k[0] for k in rows}
        given = defaultdict(list)
        for pid, day, name, stage in (ImmunizationRecord.objects
                                      .filter(patient_id__in=pids, administered_date__range=(d_from, d_to))
                                      .values_list('patient_id', 'administered_date', 'vaccine_name', 'dose_stage')):
            given[(pid, day)].append(f"{name}" + (f" ({stage})" if stage else ''))

        due_cache = {}
        out = []
        for (pid, day), r in rows.items():
            p = r['patient']
            name = ' '.join(x for x in (p.surname, p.first_name, p.other_name) if x).strip()
            if search and not any(search in str(v or '').lower() for v in
                                  (name, p.hospital_number, p.phone_number, p.next_of_kin_phone)):
                continue
            gv = given.get((pid, day), [])
            seen_on = None
            if gv or r['completed_appt']:
                st = 'attended'
            elif day < today:
                st = 'missed'
                seen_on = (ImmunizationRecord.objects.filter(patient_id=pid, administered_date__gt=day)
                           .order_by('administered_date').values_list('administered_date', flat=True).first())
            elif day == today:
                st = 'today'
            else:
                st = 'upcoming'
            if want and want != 'all' and st != want:
                continue
            if pid not in due_cache:
                try:
                    nd = compute_next_due_vaccines(p)
                    names = [v['name'] for o in nd.get('overdue', []) for v in o['vaccines']]
                    if nd.get('next_milestone'):
                        names += [v['name'] for v in nd['next_milestone']['vaccines']]
                    due_cache[pid] = {'stage': (nd.get('next_milestone') or {}).get('stage'),
                                      'overdue': bool(nd.get('overdue')), 'vaccines': names}
                except Exception:
                    due_cache[pid] = {'stage': None, 'overdue': False, 'vaccines': []}
            try:
                age = calculate_patient_age_details(p).get('display')
            except Exception:
                age = None
            out.append({
                'key': f'{pid}-{day.isoformat()}',
                'patient_id': pid,
                'patient_name': name,
                'hospital_number': p.hospital_number or '',
                'gender': p.gender or '',
                'age': age,
                'phone': p.phone_number or '',
                'guardian_phone': p.next_of_kin_phone or '',
                'sponsor': p.sponsor.name if p.sponsor else '',
                'sponsor_id': p.sponsor_id,
                'sponsor_category': (p.sponsor.category.category if p.sponsor and getattr(p.sponsor, 'category', None) else ''),
                'plan_id': p.plan_id,
                'appointment_id': r['open_appt'] or (r['appointment_ids'][0] if r['appointment_ids'] else None),
                'plan': p.plan.plan if p.plan else '',
                'date': day.isoformat(),
                'sources': sorted(r['sources']),
                'purpose': ', '.join(sorted(r['purposes'])) or ('Next dose due' if 'next_dose' in r['sources'] else ''),
                'last_visit': r.get('last_visit').isoformat() if r.get('last_visit') else None,
                'status': st,
                'seen_on': seen_on.isoformat() if seen_on else None,   # missed, but vaccinated later
                'vaccines_given': gv,
                'vaccines_due': due_cache[pid]['vaccines'] if st != 'attended' else [],
                'due_stage': due_cache[pid]['stage'],
                'has_overdue': due_cache[pid]['overdue'],
            })

        order = {'today': 0, 'missed': 1, 'upcoming': 2, 'attended': 3}
        out.sort(key=lambda x: (x['date'], order[x['status']], x['patient_name'].lower()))
        summary = {k: sum(1 for x in out if x['status'] == k) for k in order}
        summary['total'] = len(out)
        return Response({'from': d_from.isoformat(), 'to': d_to.isoformat(), 'today': today.isoformat(),
                         'summary': summary, 'rows': out})
