"""
Top-bar bell.

    GET  notifications/summary/        {unread, recent[10], tasks[], tasks_total}   (polled by the bell)
    GET  notifications/?unread=1&offset=0&limit=30
    POST notifications/read/           {ids: [...]} or {all: true}

"Tasks" are not stored: they are counted live from the data the user is responsible for
(stock to accept or send for their store, patients awaiting a bed, ...), so they disappear
by themselves once the work is done.
"""
from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.permissions import is_admin, user_store_ids
from notifications.models import Notification


def _row(n):
    return {
        'id': n.id, 'kind': n.kind, 'title': n.title, 'message': n.message, 'link': n.link,
        'level': n.level, 'icon': n.icon, 'created_at': n.created_at.isoformat(),
        'read': n.read_at is not None,
        'actor': (getattr(n.actor, 'fullname', None) or getattr(n.actor, 'username', None)) if n.actor_id else None,
    }


def _has_module(user, code):
    if is_admin(user):
        return True
    from users.models import Role, RolePermission
    role_id = getattr(user, 'role_id', None)
    if not role_id:   # accounts not yet linked to a role use the role named after their department
        dept = str(getattr(getattr(user, 'department', None), 'department', '') or '').strip()
        role_id = Role.objects.filter(name__iexact=dept).values_list('id', flat=True).first() if dept else None
    return bool(role_id) and RolePermission.objects.filter(role_id=role_id, module__code=code).exists()


def _task(key, title, count, link, icon, level='info', hint=''):
    return {'key': key, 'title': title, 'count': count, 'link': link, 'icon': icon, 'level': level, 'hint': hint}


def waiting_for_vitals_count():
    """Patients with an open appointment today and no vitals yet today (vitals = a DoctorWaitingList row)."""
    from django.utils import timezone
    from patients.models import PatientAppointment
    from queue_operations.models import DoctorWaitingList
    today = timezone.localdate()
    seen = DoctorWaitingList.objects.filter(created_date__date=today).values('patient_id')
    return (PatientAppointment.objects.filter(arrival_date=today, completed=0, patient__isnull=False)
            .exclude(patient_id__in=seen).order_by().values('patient_id').distinct().count())


def tasks_for(user):
    from inventory.models import StockRequisition, StockTransfer, StoreStock, StoreStockBatch
    out = []
    ids = user_store_ids(user)          # None = administrator (every store)

    def scope(qs, field):
        return qs if ids is None else qs.filter(**{f'{field}__in': ids})

    if ids is None or ids:
        n = scope(StockTransfer.objects.filter(status='in_transit'), 'destination_store_id').count()
        if n:
            out.append(_task('stock_to_accept', 'Stock waiting to be accepted', n, '/inventory/transfers', 'fa-truck-loading',
                             'warning', 'Count it and accept with your PIN'))
        qs = scope(StockRequisition.objects.filter(status__in=['pending', 'approved']), 'fulfilling_store_id')
        n = qs.count()
        if n:
            urgent = qs.filter(priority__in=['urgent', 'emergency']).count()
            out.append(_task('requests_to_send', 'Stock requests to send', n, '/inventory/requests', 'fa-dolly',
                             'danger' if urgent else 'warning', f'{urgent} urgent' if urgent else ''))

    if ids:   # store staff only: stock housekeeping for their own stores
        n = (StoreStock.objects.filter(store_id__in=ids, store__is_active=True, product__merged_into__isnull=True,
                                       stock__gt=0, stock__lte=F('low_stock_threshold')).count())
        if n:
            out.append(_task('low_stock', 'Items running low', n, '/inventory/view', 'fa-battery-quarter', 'warning'))
        today = timezone.localdate()
        n = (StoreStockBatch.objects.filter(store_id__in=ids, quantity__gt=0, expiry_date__isnull=False,
                                            expiry_date__lte=today + timedelta(days=60)).count())
        if n:
            out.append(_task('expiring', 'Batches expired or expiring in 60 days', n, '/inventory/view',
                             'fa-hourglass-end', 'danger'))

    if _has_module(user, 'nursing'):
        n = waiting_for_vitals_count()
        if n:
            out.append(_task('waiting_vitals', "Today's patients waiting for vitals", n, '/appointments/today',
                             'fa-heartbeat', 'warning', 'Booked for today, no vitals recorded yet'))
    if _has_module(user, 'inpatient'):
        from IPD.models import AdmissionTable
        n = AdmissionTable.objects.filter(status='awaiting_bed').count()
        if n:
            out.append(_task('awaiting_bed', 'Admitted patients awaiting a bed', n, '/ipd/admitted', 'fa-procedures', 'warning'))
        n = AdmissionTable.objects.filter(status='discharge_ordered').count()
        if n:
            out.append(_task('discharge_ordered', 'Discharges waiting for the patient to leave', n, '/ipd/admitted',
                             'fa-door-open', 'info'))
    return out


class NotificationSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        mine = Notification.objects.filter(recipient=request.user)
        tasks = tasks_for(request.user)
        return Response({
            'unread': mine.filter(read_at__isnull=True).count(),
            'recent': [_row(n) for n in mine.select_related('actor')[:10]],
            'tasks': tasks,
            'tasks_total': sum(t['count'] for t in tasks),
            'server_time': timezone.now().isoformat(),
        })


class NotificationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user).select_related('actor')
        if request.query_params.get('unread') == '1':
            qs = qs.filter(read_at__isnull=True)
        try:
            offset = max(0, int(request.query_params.get('offset', 0)))
            limit = min(100, max(1, int(request.query_params.get('limit', 30))))
        except ValueError:
            offset, limit = 0, 30
        return Response({'count': qs.count(), 'results': [_row(n) for n in qs[offset:offset + limit]]})


class NotificationReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        qs = Notification.objects.filter(recipient=request.user, read_at__isnull=True)
        if not request.data.get('all'):
            ids = request.data.get('ids') or []
            if not isinstance(ids, list):
                ids = [ids]
            qs = qs.filter(pk__in=ids)
        n = qs.update(read_at=timezone.now())
        unread = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
        return Response({'marked': n, 'unread': unread})
