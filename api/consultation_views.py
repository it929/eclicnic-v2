"""
Orders sent during an open consultation.

A doctor may send drugs, lab tests, scans and services before finishing the consultation note
(e.g. order an FBC, wait for the result, then decide). Orders are signed with the doctor's
security PIN (save-consultation-orders); this view shows the doctor what happened to them:
billed / paid / result ready / dispensed, with the lab and scan results.
"""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.notification_views import _has_module

RESULT_MODULES = ('clinical', 'nursing', 'inpatient')


def verify_signing_pin(request, action):
    """The signed-in user's own security PIN, required to sign `action`. Returns an error Response or None."""
    user = request.user
    pin = str(request.data.get('pin_code') or '').strip()
    if not pin:
        return Response({'error': 'Your security PIN is required to sign these orders.', 'code': 'pin_required'},
                        status=status.HTTP_400_BAD_REQUEST)
    if not user.has_pin:
        return Response({'error': 'You have no security PIN. Set one in Profile Settings first.', 'code': 'no_pin'},
                        status=status.HTTP_400_BAD_REQUEST)
    if not pin.isdigit() or not user.check_pin(pin):
        from api.audit import pin_failed
        pin_failed(request, action, pin_owner=user)
        return Response({'error': 'Incorrect security PIN.', 'code': 'bad_pin'}, status=status.HTTP_400_BAD_REQUEST)
    return None


def _who(u):
    return (getattr(u, 'fullname', '') or u.get_full_name() or u.username) if u else ''


def _bill_state(inv):
    """(code, label) from the invoice line billing made for an order (None = not billed yet)."""
    if inv is None:
        return 'unbilled', 'Awaiting billing'
    if inv.completed:
        return 'paid', 'HMO approved' if (inv.payment_option or '').lower() == 'claim' else 'Paid'
    if inv.amount_paid:
        return 'part_paid', 'Part-paid'
    if (inv.payment_option or '').lower() == 'claim':
        return 'billed', 'HMO claim pending'
    return 'billed', 'Awaiting payment'


def _invoices(patient, model, ids):
    from Billings.models import Invoice
    out = {}
    for inv in Invoice.objects.filter(patient=patient, original_source_model=model,
                                      original_source_id__in=list(ids)).order_by('created_date'):
        out[inv.original_source_id] = inv
    return out


def _file_url(f):
    try:
        return f.url if f else ''
    except Exception:
        return ''


class ConsultationVisitOrdersView(APIView):
    """
    GET /api/consultation/visit-orders/?patient=<id>&since=<ISO time>
    Orders for this patient placed since `since` (default: start of today; at most 30 days back).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from patients.models import PatientProfile
        from queue_operations.models import WrittenPrescriptions, OtherService
        from radio_lab.models import RadiologyLab

        if not any(_has_module(request.user, m) for m in RESULT_MODULES):
            return Response({'error': 'You do not have access to clinical results.'}, status=status.HTTP_403_FORBIDDEN)

        patient = PatientProfile.objects.filter(id=request.query_params.get('patient') or 0).first()
        if not patient:
            return Response({'error': 'Patient not found.'}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        since = parse_datetime(request.query_params.get('since') or '')
        if since and timezone.is_naive(since):
            since = timezone.make_aware(since)
        start_of_today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        if not since or since > now:
            since = start_of_today
        since = max(since - timedelta(minutes=5), now - timedelta(days=30))   # 5 min: clock differences

        orders = []

        labs = list(RadiologyLab.objects.filter(patient=patient, created_date__gte=since)
                    .select_related('staff').prefetch_related('parameter_results', 'lab_results', 'scan_results')
                    .order_by('created_date'))
        bills = _invoices(patient, 'RadiologyLab', [o.id for o in labs])
        for o in labs:
            is_lab = (o.item_type or '').upper().startswith('L')
            code, label = _bill_state(bills.get(o.id))
            result = None
            if o.completed:
                result = {
                    'parameters': [
                        {'name': r.parameter_name, 'value': r.result_value, 'unit': r.unit,
                         'range': r.reference_range_display, 'flag': r.flag}
                        for r in o.parameter_results.all() if (r.result_value or '').strip()
                    ],
                    'notes': [
                        {'text': r.results or '', 'file': _file_url(getattr(r, 'file_upload', None) or getattr(r, 'scan', None))}
                        for r in (list(o.lab_results.all()) + list(o.scan_results.all()))
                    ],
                }
                state, state_label = 'result_ready', 'Result ready'
            else:
                state, state_label = code, label
                if code == 'paid':
                    state, state_label = 'in_progress', ('In the lab' if is_lab else 'In radiology')
            orders.append({
                'kind': 'lab' if is_lab else 'radiology', 'id': o.id, 'name': o.item,
                'ordered_at': o.created_date, 'ordered_by': _who(o.staff),
                'billing': code, 'state': state, 'state_label': state_label, 'result': result,
            })

        rxs = list(WrittenPrescriptions.objects.filter(patient=patient, created_date__gte=since)
                   .exclude(is_anc_template=True).select_related('provider').order_by('created_date'))
        bills = _invoices(patient, 'WrittenPrescriptions', [r.id for r in rxs])
        for r in rxs:
            code, label = _bill_state(bills.get(r.id))
            st = (r.status or '').lower()
            if st == 'dispensed':
                state, state_label = 'done', 'Dispensed'
            elif st in ('cancelled', 'declined'):
                state, state_label = 'cancelled', st.capitalize()
            else:
                state, state_label = code, label
                if code == 'paid':
                    state, state_label = 'in_progress', 'At pharmacy'
            orders.append({
                'kind': 'prescription', 'id': r.id, 'name': r.item,
                'detail': r.dispense_detail or r.instruction or '',
                'ordered_at': r.created_date, 'ordered_by': _who(r.provider),
                'billing': code, 'state': state, 'state_label': state_label,
                'dispensed_at': r.dispensed_at,
            })

        svcs = list(OtherService.objects.filter(patient=patient, created_date__gte=since)
                    .select_related('provider').order_by('created_date'))
        bills = _invoices(patient, 'OtherService', [s.id for s in svcs])
        for s in svcs:
            code, label = _bill_state(bills.get(s.id))
            state, state_label = ('done', 'Done') if s.completed else (code, label)
            orders.append({
                'kind': 'service', 'id': s.id, 'name': s.purpose or '',
                'ordered_at': s.created_date, 'ordered_by': _who(s.provider),
                'billing': code, 'state': state, 'state_label': state_label,
            })

        orders.sort(key=lambda x: x['ordered_at'] or now)
        return Response({
            'since': since,
            'checked_at': now,
            'results_ready': sum(1 for o in orders if o['state'] == 'result_ready'),
            'orders': orders,
        })
