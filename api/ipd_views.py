"""
In-patient (IPD) API: admissions, wards and beds.

All rules live in IPD/services.py; these views only parse the request, identify the
staff member by PIN and shape the response.

    GET   ipd/admissions/                      list (status=open|awaiting_bed|in_ward|discharge_ordered|discharged|cancelled|all,
                                                     ward, search, from, to)
    GET   ipd/admissions/check/?patient=<id>   before the Admit modal: open admission (if any) + wards
    POST  ipd/admissions/admit/                {patient, appointment?, ward?, admission_type, source, reason,
                                                provisional_diagnosis?, notes?, pin}
    GET   ipd/admissions/<id>/                 detail + timeline + bed history
    POST  ipd/admissions/<id>/<action>/        assign-bed {bed, pin, notes?} | order-discharge {discharge_type, summary, pin}
                                               | reverse-discharge {reason, pin} | complete-discharge {pin}
                                               | cancel {reason, pin}
    GET   ipd/wards/                           wards with beds and who is on them
    POST  ipd/wards/                           create ward (admin)
    PATCH ipd/wards/<id>/                      edit ward (admin)
    POST  ipd/wards/<id>/add-beds/             {count, prefix} (admin)
    PATCH ipd/beds/<id>/                       {bed_name?, is_active?} (admin)
"""
from datetime import datetime

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from IPD import services
from IPD.models import (
    ADMISSION_SOURCES, ADMISSION_STATUSES, ADMISSION_TYPES, DISCHARGE_TYPES, OPEN_ADMISSION_STATUSES,
    WARD_GENDERS, WARD_TYPES, AdmissionTable, Bed, BedAllocation, Ward,
)
from inventory.permissions import is_admin

STATUS_LABELS = dict(ADMISSION_STATUSES)


def _err(e):
    return Response({'error': e.message, 'code': e.code}, status=status.HTTP_400_BAD_REQUEST)


def _pin_user(request, purpose):
    from .views import _pin_staff
    return _pin_staff(request, purpose)


def _parse_date(v):
    if not v:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            pass
    return None


def _dt(v):
    return v.isoformat() if v else None


def _patient_summary(p):
    if not p:
        return None
    return {
        'id': p.id,
        'name': p.get_full_name(),
        'hospital_number': p.hospital_number,
        'gender': p.gender,
        'age': p.age,
        'phone': p.phone_number,
        'sponsor_name': getattr(p.sponsor, 'name', None),
        'plan_name': getattr(p.plan, 'plan', None),
        'category': getattr(p.category, 'category', None),
    }


def _los_days(a):
    start = a.doctor_admit_date
    if not start:
        return 0
    end = a.discharged_at or a.cancelled_at or timezone.now()
    return max(0, (timezone.localtime(end).date() - timezone.localtime(start).date()).days)


def admission_row(a):
    p = a.patient
    return {
        'id': a.id,
        'admission_no': a.admission_no,
        'status': a.status,
        'status_label': STATUS_LABELS.get(a.status, a.status),
        'admission_type': a.admission_type,
        'admission_type_label': a.get_admission_type_display(),
        'source': a.source,
        'source_label': a.get_source_display(),
        'patient': _patient_summary(p),
        'sponsor_name': getattr(a.sponsor, 'name', None),
        'plan_name': getattr(a.plan, 'plan', None),
        'ward_id': a.ward_id,
        'ward_name': getattr(a.ward, 'ward_name', None),
        'bed_id': a.bed_id,
        'bed_name': getattr(a.bed, 'bed_name', None),
        'reason': a.reason,
        'provisional_diagnosis': a.provisional_diagnosis,
        'admitted_at': _dt(a.doctor_admit_date),
        'admitted_by': services.staff_name(a.doctor_admitted),
        'consultant': services.staff_name(a.consultant),
        'received_at': _dt(a.nurse_admit_date),
        'received_by': services.staff_name(a.received_by),
        'discharge_type': a.discharge_type,
        'discharge_type_label': a.get_discharge_type_display() if a.discharge_type else '',
        'discharge_ordered_at': _dt(a.doctor_discharge_date),
        'discharge_ordered_by': services.staff_name(a.discharge_ordered_by),
        'discharged_at': _dt(a.discharged_at),
        'cancelled_at': _dt(a.cancelled_at),
        'cancel_reason': a.cancel_reason,
        'los_days': _los_days(a),
        'is_open': a.is_open,
    }


def _admission_qs():
    return AdmissionTable.objects.select_related(
        'patient', 'patient__sponsor', 'patient__plan', 'patient__category', 'sponsor', 'plan',
        'ward', 'bed', 'doctor_admitted', 'consultant', 'received_by', 'discharge_ordered_by')


def _ward_payload(ward_qs, include_beds=True):
    wards = list(ward_qs.order_by('ward_name'))
    beds = {}
    occupant = {}
    if include_beds:
        for b in Bed.objects.filter(ward__in=wards).order_by('id'):
            beds.setdefault(b.ward_id, []).append(b)
        for al in (BedAllocation.objects.filter(is_active=True, bed__ward__in=wards)
                   .select_related('patient', 'admission_record')):
            occupant[al.bed_id] = al
    waiting = dict(AdmissionTable.objects.filter(status='awaiting_bed', ward__in=wards).order_by()
                   .values_list('ward_id').annotate(n=Count('id')))
    out = []
    for w in wards:
        wb = beds.get(w.id, [])
        bed_rows = []
        for b in wb:
            al = occupant.get(b.id)
            bed_rows.append({
                'id': b.id, 'bed_name': b.bed_name, 'is_active': b.is_active,
                'is_occupied': bool(al),
                'patient_name': al.patient.get_full_name() if al and al.patient else None,
                'hospital_number': al.patient.hospital_number if al and al.patient else None,
                'admission_id': al.admission_record_id if al else None,
                'admission_status': al.admission_record.status if al and al.admission_record else None,
            })
        active = [r for r in bed_rows if r['is_active']]
        out.append({
            'id': w.id, 'ward_name': w.ward_name, 'price': w.price,
            'ward_type': w.ward_type, 'ward_type_label': w.get_ward_type_display(),
            'gender': w.gender, 'gender_label': w.get_gender_display(), 'is_active': w.is_active,
            'pharmacy_store': w.pharmacy_store_id,
            'pharmacy_store_name': getattr(w.pharmacy_store, 'name', None),
            'total_beds': len(active),
            'occupied_beds': sum(1 for r in active if r['is_occupied']),
            'free_beds': sum(1 for r in active if not r['is_occupied']),
            'out_of_service': len(bed_rows) - len(active),
            'awaiting_bed': waiting.get(w.id, 0),
            'beds': bed_rows if include_beds else None,
        })
    return out


class _Auth(APIView):
    permission_classes = [permissions.IsAuthenticated]


# ---------------------------------------------------------------------------------------------
# Admissions
# ---------------------------------------------------------------------------------------------
class AdmissionListView(_Auth):
    def get(self, request):
        qp = request.query_params
        qs = _admission_qs()
        base = qs
        st = (qp.get('status') or 'open').strip()
        if st == 'open':
            qs = qs.filter(status__in=OPEN_ADMISSION_STATUSES)
        elif st in STATUS_LABELS:
            qs = qs.filter(status=st)
        elif st != 'all':
            return Response({'error': f"Unknown status '{st}'."}, status=400)

        ward = qp.get('ward')
        if ward:
            qs = qs.filter(ward_id=ward)
            base = base.filter(ward_id=ward)
        search = (qp.get('search') or '').strip()
        if search:
            cond = (Q(patient__surname__icontains=search) | Q(patient__first_name__icontains=search)
                    | Q(patient__other_name__icontains=search) | Q(patient__hospital_number__icontains=search)
                    | Q(admission_no__icontains=search) | Q(patient__phone_number__icontains=search))
            qs = qs.filter(cond)
            base = base.filter(cond)
        d_from, d_to = _parse_date(qp.get('from')), _parse_date(qp.get('to'))
        # Date filter applies to closed lists (discharged / cancelled / all); open admissions are always shown in full.
        if (d_from or d_to) and st not in ('open',) + OPEN_ADMISSION_STATUSES:
            if d_from:
                qs = qs.filter(doctor_admit_date__date__gte=d_from)
            if d_to:
                qs = qs.filter(doctor_admit_date__date__lte=d_to)

        counts = dict(base.order_by().values_list('status').annotate(n=Count('id')))
        counts = {k: counts.get(k, 0) for k in STATUS_LABELS}
        counts['open'] = sum(counts[k] for k in OPEN_ADMISSION_STATUSES)

        rows = [admission_row(a) for a in qs.order_by('-doctor_admit_date')[:500]]
        return Response({'results': rows, 'counts': counts, 'status': st})


class AdmissionCheckView(_Auth):
    """Called when the Admit modal opens."""

    def get(self, request):
        from patients.models import PatientProfile
        pid = request.query_params.get('patient')
        if not pid:
            return Response({'error': 'patient is required.'}, status=400)
        p = get_object_or_404(PatientProfile.objects.select_related('sponsor', 'plan', 'category'), pk=pid)
        cur = services.open_admission(p)
        if cur:
            cur = _admission_qs().get(pk=cur.pk)
        return Response({
            'patient': _patient_summary(p),
            'open_admission': admission_row(cur) if cur else None,
            'wards': _ward_payload(Ward.objects.filter(is_active=True).select_related('pharmacy_store'), include_beds=False),
            'admission_types': [{'value': v, 'label': l} for v, l in ADMISSION_TYPES],
            'sources': [{'value': v, 'label': l} for v, l in ADMISSION_SOURCES],
        })


class AdmitView(_Auth):
    def post(self, request):
        from patients.models import PatientAppointment, PatientProfile
        d = request.data
        patient = PatientProfile.objects.filter(pk=d.get('patient')).first()
        if not patient:
            return Response({'error': 'Patient not found.', 'code': 'patient_required'}, status=400)
        ward = None
        if d.get('ward'):
            ward = Ward.objects.filter(pk=d.get('ward')).first()
            if not ward:
                return Response({'error': 'Ward not found.', 'code': 'ward_not_found'}, status=400)
        appointment = None
        if d.get('appointment'):
            appointment = PatientAppointment.objects.filter(pk=d.get('appointment'), patient=patient).first()

        doctor, err = _pin_user(request, 'admit this patient')
        if err:
            return err
        try:
            adm = services.admit(
                patient, doctor=doctor, created_by=request.user, appointment=appointment, ward=ward,
                admission_type=d.get('admission_type') or 'elective', source=d.get('source') or 'opd',
                reason=d.get('reason') or '', provisional_diagnosis=d.get('provisional_diagnosis') or '',
                notes=d.get('notes') or '',
            )
        except services.AdmissionError as e:
            return _err(e)
        adm = _admission_qs().get(pk=adm.pk)
        return Response({'detail': f'{patient.get_full_name()} admitted ({adm.admission_no}).',
                         'admission': admission_row(adm)}, status=201)


class AdmissionDetailView(_Auth):
    def get(self, request, pk):
        a = get_object_or_404(_admission_qs(), pk=pk)
        row = admission_row(a)
        row['notes'] = a.notes
        row['discharge_summary'] = a.discharge_summary
        row['events'] = [{
            'event': e.event, 'event_label': e.get_event_display(), 'from_status': e.from_status,
            'to_status': e.to_status, 'detail': e.detail, 'staff': services.staff_name(e.staff),
            'at': _dt(e.created_at),
        } for e in a.events.select_related('staff')]
        row['beds'] = [{
            'ward_name': getattr(al.ward, 'ward_name', None), 'bed_name': getattr(al.bed, 'bed_name', None),
            'reason': al.reason, 'from': _dt(al.created_date), 'to': _dt(al.released_at), 'is_active': al.is_active,
            'by': services.staff_name(al.staff),
        } for al in a.bedallocation_set.select_related('ward', 'bed', 'staff').order_by('created_date')]
        return Response(row)


class AdmissionActionView(_Auth):
    PURPOSE = {
        'assign-bed': 'assign this bed',
        'order-discharge': 'sign this discharge',
        'reverse-discharge': 'withdraw this discharge',
        'complete-discharge': 'release this patient',
        'cancel': 'cancel this admission',
    }

    def post(self, request, pk, action):
        if action not in self.PURPOSE:
            return Response({'error': f"Unknown action '{action}'."}, status=404)
        adm = get_object_or_404(AdmissionTable, pk=pk)
        d = request.data
        bed = None
        if action == 'assign-bed':
            bed = Bed.objects.filter(pk=d.get('bed')).first()
            if not bed:
                return Response({'error': 'Choose a bed.', 'code': 'bed_required'}, status=400)
        user, err = _pin_user(request, self.PURPOSE[action])
        if err:
            return err
        try:
            if action == 'assign-bed':
                services.assign_bed(adm, bed, by=user, notes=(d.get('notes') or '').strip())
            elif action == 'order-discharge':
                services.order_discharge(adm, by=user, discharge_type=d.get('discharge_type') or 'routine',
                                         summary=d.get('summary') or '')
            elif action == 'reverse-discharge':
                services.reverse_discharge(adm, by=user, reason=d.get('reason') or '')
            elif action == 'complete-discharge':
                services.complete_discharge(adm, by=user)
            elif action == 'cancel':
                services.cancel(adm, by=user, reason=d.get('reason') or '')
        except services.AdmissionError as e:
            return _err(e)
        a = _admission_qs().get(pk=pk)
        return Response({'detail': 'Saved.', 'admission': admission_row(a)})


# ---------------------------------------------------------------------------------------------
# Wards & beds
# ---------------------------------------------------------------------------------------------
def _admin_or_403(request):
    if not is_admin(request.user):
        return Response({'error': 'Only an administrator can change wards and beds.'}, status=403)
    return None


def _apply_ward_fields(w, d):
    if 'ward_name' in d:
        name = (d.get('ward_name') or '').strip()
        if not name:
            raise services.AdmissionError('Enter the ward name.', 'name_required')
        if Ward.objects.filter(ward_name__iexact=name).exclude(pk=w.pk).exists():
            raise services.AdmissionError(f'A ward named "{name}" already exists.', 'duplicate_name')
        w.ward_name = name
    if 'price' in d:
        try:
            price = int(float(d.get('price') or 0))
        except (TypeError, ValueError):
            raise services.AdmissionError('Daily fee must be a number.', 'invalid_price')
        if price < 0:
            raise services.AdmissionError('Daily fee cannot be negative.', 'invalid_price')
        w.price = price
    if 'ward_type' in d:
        w.ward_type = services._choice(d.get('ward_type'), WARD_TYPES, 'ward_type', 'general')
    if 'gender' in d:
        w.gender = services._choice(d.get('gender'), WARD_GENDERS, 'gender', 'any')
    if 'is_active' in d:
        w.is_active = str(d.get('is_active')).lower() in ('1', 'true', 'yes')
    if 'pharmacy_store' in d:
        w.pharmacy_store_id = d.get('pharmacy_store') or None


class WardListView(_Auth):
    def get(self, request):
        qs = Ward.objects.select_related('pharmacy_store')
        if request.query_params.get('active') == '1':
            qs = qs.filter(is_active=True)
        return Response({
            'wards': _ward_payload(qs),
            'ward_types': [{'value': v, 'label': l} for v, l in WARD_TYPES],
            'genders': [{'value': v, 'label': l} for v, l in WARD_GENDERS],
            'is_admin': is_admin(request.user),
        })

    @transaction.atomic
    def post(self, request):
        denied = _admin_or_403(request)
        if denied:
            return denied
        d = request.data
        w = Ward()
        try:
            _apply_ward_fields(w, {**{'ward_name': '', 'price': 0}, **{k: d.get(k) for k in d}})
            w.save()
            if d.get('beds'):
                services.add_beds(w, d.get('beds'), d.get('bed_prefix') or 'Bed')
        except services.AdmissionError as e:
            transaction.set_rollback(True)
            return _err(e)
        return Response({'detail': f'{w.ward_name} created.', 'ward': _ward_payload(Ward.objects.filter(pk=w.pk))[0]},
                        status=201)


class WardDetailView(_Auth):
    def patch(self, request, pk):
        denied = _admin_or_403(request)
        if denied:
            return denied
        w = get_object_or_404(Ward, pk=pk)
        d = request.data
        if 'is_active' in d and str(d.get('is_active')).lower() not in ('1', 'true', 'yes'):
            if BedAllocation.objects.filter(is_active=True, bed__ward=w).exists():
                return Response({'error': f'{w.ward_name} still has patients on beds.', 'code': 'ward_in_use'}, status=400)
        try:
            _apply_ward_fields(w, d)
        except services.AdmissionError as e:
            return _err(e)
        w.save()
        return Response({'detail': 'Ward saved.', 'ward': _ward_payload(Ward.objects.filter(pk=w.pk))[0]})

    def delete(self, request, pk):
        """Delete a ward created by mistake: only when it has no beds and was never used for an admission."""
        denied = _admin_or_403(request)
        if denied:
            return denied
        w = get_object_or_404(Ward, pk=pk)
        if Bed.objects.filter(ward=w).exists():
            return Response({'error': f'{w.ward_name} still has beds. Map them to another ward (or unmap them) first.',
                             'code': 'ward_has_beds'}, status=400)
        if AdmissionTable.objects.filter(ward=w).exists() or BedAllocation.objects.filter(ward=w).exists():
            return Response({'error': f'{w.ward_name} has admission history and cannot be deleted. Close it instead.',
                             'code': 'ward_has_history'}, status=400)
        name = w.ward_name
        w.delete()
        return Response({'detail': f'{name} deleted.'})


class WardAddBedsView(_Auth):
    def post(self, request, pk):
        denied = _admin_or_403(request)
        if denied:
            return denied
        w = get_object_or_404(Ward, pk=pk)
        try:
            made = services.add_beds(w, request.data.get('count') or 1, request.data.get('prefix') or 'Bed')
        except (services.AdmissionError,) as e:
            return _err(e)
        except (TypeError, ValueError):
            return Response({'error': 'Number of beds must be a number.'}, status=400)
        return Response({'detail': f'{len(made)} bed(s) added to {w.ward_name}.',
                         'ward': _ward_payload(Ward.objects.filter(pk=w.pk))[0]})


# ---------------------------------------------------------------------------------------------
# Beds: create, map to a ward, rename, service status, delete
# ---------------------------------------------------------------------------------------------
def _ward_or_none(value):
    """'' / None / 'none' -> (None, None) meaning unmapped; else (Ward, None) or (None, error Response)."""
    if value in (None, '', 'none', 'null', 0, '0'):
        return None, None
    w = Ward.objects.filter(pk=value).first()
    if not w:
        return None, Response({'error': 'Ward not found.', 'code': 'ward_not_found'}, status=400)
    return w, None


def bed_rows(qs):
    beds = list(qs.select_related('ward').order_by('ward__ward_name', 'id'))
    active = {al.bed_id: al for al in BedAllocation.objects.filter(is_active=True, bed__in=beds)
              .select_related('patient', 'admission_record')}
    used = set(BedAllocation.objects.filter(bed__in=beds).values_list('bed_id', flat=True)) | \
        set(AdmissionTable.objects.filter(bed__in=beds).values_list('bed_id', flat=True))
    out = []
    for b in beds:
        al = active.get(b.id)
        out.append({
            'id': b.id, 'bed_name': b.bed_name, 'is_active': b.is_active,
            'ward_id': b.ward_id, 'ward_name': getattr(b.ward, 'ward_name', None),
            'ward_is_active': bool(b.ward and b.ward.is_active),
            'is_occupied': bool(al),
            'patient_name': al.patient.get_full_name() if al and al.patient else None,
            'hospital_number': al.patient.hospital_number if al and al.patient else None,
            'admission_no': al.admission_record.admission_no if al and al.admission_record else None,
            'can_delete': b.id not in used,
        })
    return out


class BedListView(_Auth):
    def get(self, request):
        qs = Bed.objects.all()
        ward = request.query_params.get('ward')
        if ward == 'unmapped':
            qs = qs.filter(ward__isnull=True)
        elif ward:
            qs = qs.filter(ward_id=ward)
        search = (request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(Q(bed_name__icontains=search) | Q(ward__ward_name__icontains=search))
        rows = bed_rows(qs)
        st = request.query_params.get('status')
        if st == 'free':
            rows = [r for r in rows if r['is_active'] and not r['is_occupied']]
        elif st == 'occupied':
            rows = [r for r in rows if r['is_occupied']]
        elif st == 'off':
            rows = [r for r in rows if not r['is_active']]
        return Response({
            'beds': rows,
            'unmapped': Bed.objects.filter(ward__isnull=True).count(),
            'wards': [{'id': w.id, 'ward_name': w.ward_name, 'is_active': w.is_active}
                      for w in Ward.objects.order_by('ward_name')],
            'is_admin': is_admin(request.user),
        })

    def post(self, request):
        """{bed_name, ward?} creates one bed; {count, prefix?, ward?} creates several. No ward = unmapped."""
        denied = _admin_or_403(request)
        if denied:
            return denied
        d = request.data
        ward, err = _ward_or_none(d.get('ward'))
        if err:
            return err
        try:
            if d.get('count'):
                made = services.add_beds(ward, d.get('count'), d.get('prefix') or 'Bed')
            else:
                made = [services.create_bed(d.get('bed_name'), ward)]
        except services.AdmissionError as e:
            return _err(e)
        except (TypeError, ValueError):
            return Response({'error': 'Number of beds must be a number.'}, status=400)
        where = ward.ward_name if ward else 'unmapped (map them to a ward next)'
        return Response({'detail': f"{len(made)} bed{'s' if len(made) != 1 else ''} created: {where}.",
                         'beds': bed_rows(Bed.objects.filter(pk__in=[b.pk for b in made]))}, status=201)


class BedMapView(_Auth):
    def post(self, request):
        """{beds: [ids], ward: id | null} maps the beds to a ward (null = unmap). All or nothing."""
        denied = _admin_or_403(request)
        if denied:
            return denied
        ids = request.data.get('beds') or []
        if not isinstance(ids, list):
            ids = [ids]
        ward, err = _ward_or_none(request.data.get('ward'))
        if err:
            return err
        try:
            moved = services.map_beds(list(Bed.objects.filter(pk__in=ids)), ward)
        except services.AdmissionError as e:
            return _err(e)
        where = ward.ward_name if ward else 'unmapped'
        detail = (f"{len(moved)} bed{'s' if len(moved) != 1 else ''} mapped to {where}." if moved
                  else 'Nothing to change.')
        return Response({'detail': detail, 'beds': bed_rows(Bed.objects.filter(pk__in=ids))})


class BedDetailView(_Auth):
    @transaction.atomic
    def patch(self, request, pk):
        denied = _admin_or_403(request)
        if denied:
            return denied
        b = get_object_or_404(Bed, pk=pk)
        d = request.data
        if 'ward' in d:
            ward, err = _ward_or_none(d.get('ward'))
            if err:
                return err
            try:
                services.map_beds([b], ward)
            except services.AdmissionError as e:
                transaction.set_rollback(True)
                return _err(e)
            b.refresh_from_db()
        if 'bed_name' in d:
            name = (d.get('bed_name') or '').strip()[:50]
            if not name:
                transaction.set_rollback(True)
                return Response({'error': 'Enter the bed name.'}, status=400)
            if services._beds_in(b.ward).filter(bed_name__iexact=name).exclude(pk=b.pk).exists():
                transaction.set_rollback(True)
                return Response({'error': f'{name} already exists in {services._where(b.ward)}.'}, status=400)
            b.bed_name = name
        if 'is_active' in d:
            active = str(d.get('is_active')).lower() in ('1', 'true', 'yes')
            if not active and services.bed_in_use(b):
                transaction.set_rollback(True)
                return Response({'error': f'{b.bed_name} has a patient on it. Move the patient first.',
                                 'code': 'bed_in_use'}, status=400)
            b.is_active = active
        b.save()
        return Response({'detail': 'Bed saved.', 'bed': bed_rows(Bed.objects.filter(pk=b.pk))[0]})

    def delete(self, request, pk):
        """Delete a bed created by mistake. A bed that ever held a patient is kept (take it out of service instead)."""
        denied = _admin_or_403(request)
        if denied:
            return denied
        b = get_object_or_404(Bed, pk=pk)
        if BedAllocation.objects.filter(bed=b).exists() or AdmissionTable.objects.filter(bed=b).exists():
            return Response({'error': f'{b.bed_name} has patient history and cannot be deleted. '
                                      'Take it out of service instead.', 'code': 'bed_has_history'}, status=400)
        name = b.bed_name
        b.delete()
        return Response({'detail': f'{name} deleted.'})
