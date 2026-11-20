import re
from django.utils import timezone
from django.db.models import Count, Sum, Q, Max as models_Max
from datetime import date, timedelta
from rest_framework import status, viewsets, permissions, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from users.models import User, Category, VerifyStaff
from myAdmins.models import UserActivityLog, UserSession
from queue_operations.models import NurseWaitingList
from radio_lab.models import RadiologyLab
from Billings.models import Invoice, Receipt
from patients.models import PatientProfile
from api.audit import audit, who


def _can_manage_staff(user):
    from api.notification_views import _has_module
    return bool(user and user.is_authenticated and _has_module(user, 'taskmanager'))


NO_ACCESS = {'detail': 'You do not have access to Task Manager.'}
STAFF_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{1,49}$')  # what can be typed as a login username


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class StaffManagerView(APIView):
    """GET: any signed-in user (other modules pick staff from it) but only managers see contact
    details. POST / PUT: Task Manager users only."""
    permission_classes = [permissions.IsAuthenticated]

    PUBLIC_FIELDS = ('id', 'username', 'fullname', 'department_id', 'department_name', 'role_id', 'role_name', 'status', 'active')

    def get(self, request):
        users = User.objects.all().select_related('department', 'role').order_by('department__department')
        user_list = []
        for u in users:
            r_id = u.role.id if u.role else (u.department.linked_role.id if (u.department and hasattr(u.department, 'linked_role') and u.department.linked_role) else None)
            r_name = u.role.name if u.role else (u.department.department if u.department else 'Admin')
            user_list.append({
                'id': u.id,
                'username': u.username,
                'fullname': u.fullname or u.username,
                'email': u.email or '',
                'phone_number': u.phone_number or '',
                'gender': u.gender or '',
                'dob': str(u.dob) if u.dob else '',
                'address': u.address or '',
                'department_id': u.department.id if u.department else None,
                'department_name': u.department.department if u.department else 'General',
                'role_id': r_id,
                'role_name': r_name,
                'status': u.status or 'Active',
                'active': u.active if u.active is not None else '1',
                'has_pin': bool(u.has_pin),
                'created': u.created.isoformat() if u.created else None,
            })
        if not _can_manage_staff(request.user):
            user_list = [{k: u[k] for k in self.PUBLIC_FIELDS} for u in user_list]
        return Response({
            'total': len(user_list),
            'staff': user_list
        })

    def post(self, request):
        if not _can_manage_staff(request.user):
            return Response(NO_ACCESS, status=status.HTTP_403_FORBIDDEN)
        username = request.data.get('username', '').strip()
        fullname = request.data.get('fullname', '').strip()
        email = request.data.get('email', '').strip() or None
        phone_number = request.data.get('phone_number', '').strip() or None
        gender = request.data.get('gender', 'Male')
        dob = request.data.get('dob') or None
        address = request.data.get('address', '').strip() or None
        department_id = request.data.get('department_id')
        role_id = request.data.get('role_id')
        password = request.data.get('password', '').strip() or 'password123'
        pin = request.data.get('pin')

        if not username:
            return Response({'detail': 'Staff ID / Username is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not fullname:
            return Response({'detail': 'Full Name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        from users.pin_policy import password_error, pin_error
        if request.data.get('password', '').strip():
            msg = password_error(password)
            if msg:
                return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        if pin is not None and str(pin).strip() != '':
            msg = pin_error(pin)
            if msg:
                return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=username).exists():
            return Response({'detail': f'Staff ID / Username "{username}" is already taken.'}, status=status.HTTP_400_BAD_REQUEST)

        if email and User.objects.filter(email=email).exists():
            return Response({'detail': f'Email address "{email}" is already registered.'}, status=status.HTTP_400_BAD_REQUEST)

        if phone_number and User.objects.filter(phone_number=phone_number).exists():
            return Response({'detail': f'Phone number "{phone_number}" is already registered.'}, status=status.HTTP_400_BAD_REQUEST)

        dept = None
        if department_id:
            try:
                dept = Category.objects.get(id=department_id)
            except Category.DoesNotExist:
                pass

        role_obj = None
        if role_id:
            try:
                from users.models import Role
                role_obj = Role.objects.get(id=role_id)
            except Exception:
                pass
        elif dept:
            from users.models import Role
            role_obj = Role.objects.filter(name__iexact=dept.department).first()

        user = User(
            username=username,
            fullname=fullname,
            email=email,
            phone_number=phone_number,
            gender=gender,
            dob=dob,
            address=address,
            department=dept,
            role=role_obj,
            status='Active',
            active='1',
        )

        # No shared default PIN: a PIN identifies the person signing, so staff set their own
        # (Profile Settings prompts them) unless the administrator gives one here.
        user.set_pin(pin if pin and str(pin).strip() != '' else None)

        user.set_password(password)
        user.save()

        # Ensure Staff ID is also registered in VerifyStaff
        VerifyStaff.objects.get_or_create(staff_id=username)
        audit(user, 'activated', request, f'Account created by {who(request.user)}'
              + (f' in {dept.department}' if dept else ''))

        return Response({
            'detail': f'Staff member "{fullname}" ({username}) created successfully!',
            'id': user.id,
            'username': user.username,
            'fullname': user.fullname,
            'department': dept.department if dept else None,
        }, status=status.HTTP_201_CREATED)

    def put(self, request):
        if not _can_manage_staff(request.user):
            return Response(NO_ACCESS, status=status.HTTP_403_FORBIDDEN)
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'detail': 'User ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'detail': 'Staff member not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Admin PIN verification if admin user has configured PIN
        pin_code = request.data.get('admin_pin')
        admin_user = request.user
        if admin_user.has_pin:
            if not pin_code or not admin_user.check_pin(pin_code):
                audit(admin_user, 'failed_pin', request, f'Wrong security PIN while editing {who(target_user)}')
                return Response({'detail': 'Invalid Admin Security PIN.'}, status=status.HTTP_400_BAD_REQUEST)

        tracked = ('username', 'fullname', 'email', 'phone_number', 'gender', 'dob', 'address', 'department_id', 'role_id')
        before = {f: str(getattr(target_user, f) or '') for f in tracked}
        was_active = str(target_user.active) == '1'

        username = request.data.get('username', '').strip()
        fullname = request.data.get('fullname', '').strip()
        email = request.data.get('email', '').strip() or None
        phone_number = request.data.get('phone_number', '').strip() or None
        gender = request.data.get('gender')
        dob = request.data.get('dob') or None
        address = request.data.get('address', '').strip() or None
        department_id = request.data.get('department_id')
        status_val = request.data.get('status')
        active_val = request.data.get('active')
        pin = request.data.get('pin')
        password = request.data.get('password', '').strip()

        if username:
            if User.objects.filter(username=username).exclude(id=target_user.id).exists():
                return Response({'detail': f'Staff ID / Username "{username}" is already taken.'}, status=status.HTTP_400_BAD_REQUEST)
            target_user.username = username
            VerifyStaff.objects.get_or_create(staff_id=username)

        if fullname:
            target_user.fullname = fullname

        if email is not None:
            if email and User.objects.filter(email=email).exclude(id=target_user.id).exists():
                return Response({'detail': f'Email address "{email}" is already registered.'}, status=status.HTTP_400_BAD_REQUEST)
            target_user.email = email

        if phone_number is not None:
            if phone_number and User.objects.filter(phone_number=phone_number).exclude(id=target_user.id).exists():
                return Response({'detail': f'Phone number "{phone_number}" is already registered.'}, status=status.HTTP_400_BAD_REQUEST)
            target_user.phone_number = phone_number

        if gender:
            target_user.gender = gender

        if dob is not None:
            target_user.dob = dob

        if address is not None:
            target_user.address = address

        role_id = request.data.get('role_id')
        if role_id:
            try:
                from users.models import Role
                target_user.role = Role.objects.get(id=role_id)
                if target_user.role.category:
                    target_user.department = target_user.role.category
            except Exception:
                pass
        elif department_id:
            try:
                dept = Category.objects.get(id=department_id)
                target_user.department = dept
                from users.models import Role
                r = Role.objects.filter(name__iexact=dept.department).first()
                if r:
                    target_user.role = r
            except Category.DoesNotExist:
                pass

        if status_val:
            target_user.status = status_val
            target_user.active = '1' if status_val == 'Active' else '0'
        elif active_val is not None:
            target_user.active = str(active_val)
            target_user.status = 'Active' if str(active_val) == '1' else 'Inactive'

        from users.pin_policy import password_error, pin_error
        if pin is not None and str(pin).strip() != '':
            msg = pin_error(pin)
            if msg:
                return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
            target_user.set_pin(pin)

        if password:
            msg = password_error(password)
            if msg:
                return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
            target_user.set_password(password)

        target_user.save()

        by = who(admin_user)
        changed = [f for f in tracked if str(getattr(target_user, f) or '') != before[f]]
        if changed:
            labels = {'fullname': 'name', 'phone_number': 'phone', 'dob': 'date of birth',
                      'department_id': 'department', 'role_id': 'role', 'username': 'staff ID'}
            audit(target_user, 'account_accessed', request,
                  f'Account details changed by {by}: ' + ', '.join(labels.get(f, f) for f in changed), fields=changed)
        now_active = str(target_user.active) == '1'
        if now_active != was_active:
            audit(target_user, 'activated' if now_active else 'deactivated', request,
                  f"Account {'activated' if now_active else 'deactivated'} by {by}")
        if password:
            audit(target_user, 'password_reset', request, f'Password set by {by}')
        if pin is not None and str(pin).strip() != '':
            audit(target_user, 'pin_reset', request, f'Security PIN set by {by}')

        return Response({
            'detail': f'Staff member "{target_user.fullname or target_user.username}" updated successfully!',
            'user': {
                'id': target_user.id,
                'username': target_user.username,
                'fullname': target_user.fullname,
                'email': target_user.email or '',
                'phone_number': target_user.phone_number or '',
                'gender': target_user.gender or '',
                'dob': str(target_user.dob) if target_user.dob else '',
                'address': target_user.address or '',
                'department_id': target_user.department.id if target_user.department else None,
                'department_name': target_user.department.department if target_user.department else 'General',
                'status': target_user.status,
                'active': target_user.active,
                'has_pin': bool(target_user.has_pin),
            }
        })


class StaffActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _can_manage_staff(request.user):
            return Response(NO_ACCESS, status=status.HTTP_403_FORBIDDEN)
        action = request.data.get('action')
        user_id = request.data.get('user_id')
        pin_code = request.data.get('pin_code')

        # Admin PIN verification
        admin_user = request.user
        if admin_user.has_pin:
            if not pin_code or not admin_user.check_pin(pin_code):
                audit(admin_user, 'failed_pin', request, f'Wrong security PIN for staff action "{action}"')
                return Response({'detail': 'Invalid Admin Security PIN.'}, status=status.HTTP_400_BAD_REQUEST)
        by = who(admin_user)

        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'detail': 'Target staff member not found.'}, status=status.HTTP_404_NOT_FOUND)

        if action == 'toggle_status':
            target_user.active = '0' if target_user.active == '1' else '1'
            target_user.status = 'Inactive' if target_user.active == '0' else 'Active'
            target_user.save()
            msg = f"User {target_user.fullname or target_user.username} {'deactivated' if target_user.active == '0' else 'activated'}."
            on = target_user.active == '1'
            audit(target_user, 'activated' if on else 'deactivated', request, f"Account {'activated' if on else 'deactivated'} by {by}")
        elif action == 'reset_pin':
            target_user.set_pin(None)
            target_user.save()
            msg = (f"Security PIN cleared for {target_user.fullname or target_user.username}. "
                   f"They will be asked to set a new PIN in Profile Settings.")
            audit(target_user, 'pin_reset', request, f'Security PIN cleared by {by}')
        elif action == 'reset_password':
            target_user.set_password('password123')
            target_user.save()
            msg = f"Password for {target_user.fullname or target_user.username} reset to 'password123'."
            audit(target_user, 'password_reset', request, f'Password reset to the default by {by}')
        elif action == 'change_department':
            dept_id = request.data.get('department_id')
            if dept_id:
                try:
                    dept = Category.objects.get(id=dept_id)
                    target_user.department = dept
                    target_user.save()
                    msg = f"Department updated to {dept.department}."
                    audit(target_user, 'account_accessed', request, f'Department changed to {dept.department} by {by}')
                except Category.DoesNotExist:
                    return Response({'detail': 'Department not found.'}, status=status.HTTP_404_NOT_FOUND)
            else:
                return Response({'detail': 'Department ID required.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'detail': 'Unknown action.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'detail': msg, 'user_id': target_user.id, 'active': target_user.active})


ONLINE_WINDOW_MINUTES = 15   # a session counts as online if it made a request in this window


class OnlineUsersView(APIView):
    """Sessions that made a request in the last ONLINE_WINDOW_MINUTES. Real data only."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _can_manage_staff(request.user):
            return Response(NO_ACCESS, status=status.HTTP_403_FORBIDDEN)
        now = timezone.now()
        cutoff = now - timedelta(minutes=ONLINE_WINDOW_MINUTES)
        sessions = (UserSession.objects.filter(last_activity__gte=cutoff, user__is_active=True)
                    .select_related('user', 'user__department').order_by('-last_activity'))
        data = []
        for s in sessions:
            u = s.user
            data.append({
                'id': s.id,
                'user_id': u.id,
                'username': u.username,
                'fullname': u.fullname or u.username,
                'department': u.department.department if u.department else None,
                'ip_address': s.ip_address,
                'browser': s.browser_name,
                'os': s.os_name,
                'device': s.device_type,
                'login_time': s.login_time.isoformat() if s.login_time else None,
                'last_activity': s.last_activity.isoformat() if s.last_activity else None,
                'is_me': u.id == request.user.id,
            })
        return Response({
            'total': len(data),
            'users': data,
            'window_minutes': ONLINE_WINDOW_MINUTES,
            'server_time': now.isoformat(),
        })


class ForceLogoutView(APIView):
    """Sign a user out everywhere: their API token (used by the app) and every browser session."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _can_manage_staff(request.user):
            return Response(NO_ACCESS, status=status.HTTP_403_FORBIDDEN)
        target = User.objects.filter(id=request.data.get('user_id')).first()
        if not target:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        if target.id == request.user.id:
            return Response({'detail': 'Use Sign out to end your own session.'}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.sessions.models import Session
        from rest_framework.authtoken.models import Token
        rows = UserSession.objects.filter(user=target)
        keys = list(rows.values_list('session_key', flat=True))
        Session.objects.filter(session_key__in=keys).delete()
        ended = rows.count()
        rows.delete()
        Token.objects.filter(user=target).delete()
        audit(target, 'logout', request, f'Signed out on all devices by {who(request.user)}', sessions_ended=ended)
        return Response({'detail': f'{target.fullname or target.username} has been signed out on all devices.',
                         'sessions_ended': ended})


class ActivityLogsView(APIView):
    """Audit trail. Filters: user, type, search (name / username / description / IP),
    date_from / date_to (YYYY-MM-DD, inclusive), page, page_size. Real values only."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _can_manage_staff(request.user):
            return Response(NO_ACCESS, status=status.HTTP_403_FORBIDDEN)
        qp = request.query_params
        base = UserActivityLog.objects.all()
        if qp.get('user'):
            base = base.filter(user_id=qp.get('user'))
        q = (qp.get('search') or '').strip()
        if q:
            base = base.filter(Q(user__fullname__icontains=q) | Q(user__username__icontains=q)
                               | Q(description__icontains=q) | Q(ip_address__startswith=q))
        for key, lookup in (('date_from', 'timestamp__date__gte'), ('date_to', 'timestamp__date__lte')):
            v = (qp.get(key) or '').strip()
            if v:
                try:
                    base = base.filter(**{lookup: date.fromisoformat(v)})
                except ValueError:
                    return Response({'detail': f'Invalid {key}; use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        labels = dict(UserActivityLog.ACTIVITY_TYPES)
        type_counts = {r['activity_type']: r['n'] for r in base.values('activity_type').annotate(n=Count('id'))}
        qs = base
        if qp.get('type'):
            qs = qs.filter(activity_type=qp.get('type'))
        qs = qs.select_related('user', 'user__department').order_by('-timestamp')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        rows = []
        for log in page:
            u = log.user
            rows.append({
                'id': log.id,
                'user_id': u.id,
                'username': u.username,
                'fullname': u.fullname or u.username,
                'department': u.department.department if u.department else None,
                'activity_type': log.activity_type,
                'activity_label': labels.get(log.activity_type, log.activity_type.replace('_', ' ').title()),
                'description': log.description or '',
                'ip_address': log.ip_address,
                'browser': ' '.join(x for x in [log.browser_name, log.browser_version] if x) or None,
                'os': ' '.join(x for x in [log.os_name, log.os_version] if x) or None,
                'device': log.device_type,
                'timestamp': log.timestamp.isoformat(),
            })
        resp = paginator.get_paginated_response(rows)
        resp.data['page'] = paginator.page.number
        resp.data['page_size'] = paginator.get_page_size(request)
        resp.data['total_pages'] = paginator.page.paginator.num_pages
        resp.data['type_options'] = [
            {'value': k, 'label': v, 'count': type_counts.get(k, 0)}
            for k, v in UserActivityLog.ACTIVITY_TYPES if type_counts.get(k)
        ]
        return resp


DASHBOARD_PERIODS = {'7': 7, '30': 30, '90': 90}


def _still_on_admin_credential(set_kind, own_kinds):
    """Users whose latest admin-set credential (`set_kind`) is newer than their own latest change
    (`own_kinds`), i.e. they are still using a password/PIN an administrator knows."""
    from django.db.models import Max
    set_at = dict(UserActivityLog.objects.filter(activity_type=set_kind)
                  .values('user_id').annotate(t=Max('timestamp')).values_list('user_id', 't'))
    if not set_at:
        return []
    own_at = dict(UserActivityLog.objects.filter(activity_type__in=own_kinds, user_id__in=set_at)
                  .values('user_id').annotate(t=Max('timestamp')).values_list('user_id', 't'))
    ids = [uid for uid, t in set_at.items() if not own_at.get(uid) or own_at[uid] < t]
    return list(User.objects.filter(id__in=ids, is_active=True).exclude(active='0')
                .values('id', 'fullname', 'username'))


class ActivityDashboardView(APIView):
    """Security overview built from the audit log and staff accounts. ?period=7|30|90 (days)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _can_manage_staff(request.user):
            return Response(NO_ACCESS, status=status.HTTP_403_FORBIDDEN)
        from collections import Counter
        from django.db.models.functions import TruncDate

        period = request.query_params.get('period', '7')
        if period not in DASHBOARD_PERIODS:
            period = '7'
        days = DASHBOARD_PERIODS[period]
        now = timezone.now()
        today = timezone.localdate()
        start_day = today - timedelta(days=days - 1)
        labels = dict(UserActivityLog.ACTIVITY_TYPES)
        logs = UserActivityLog.objects.all()
        in_period = logs.filter(timestamp__date__gte=start_day)
        prev_period = logs.filter(timestamp__date__gte=start_day - timedelta(days=days), timestamp__date__lt=start_day)

        # daily series, zero-filled
        per_day = dict(in_period.annotate(d=TruncDate('timestamp')).values('d').annotate(n=Count('id')).values_list('d', 'n'))
        fails_day = dict(in_period.filter(activity_type='failed_login').annotate(d=TruncDate('timestamp'))
                         .values('d').annotate(n=Count('id')).values_list('d', 'n'))
        daily = []
        for i in range(days):
            d = start_day + timedelta(days=i)
            daily.append({'date': d.isoformat(), 'events': per_day.get(d, 0), 'failed': fails_day.get(d, 0)})

        types = [{'type': r['activity_type'], 'label': labels.get(r['activity_type'], r['activity_type']),
                  'count': r['n']}
                 for r in in_period.values('activity_type').annotate(n=Count('id')).order_by('-n')]
        prev_types = dict(prev_period.values('activity_type').annotate(n=Count('id')).values_list('activity_type', 'n'))
        for t in types:
            t['previous'] = prev_types.get(t['type'], 0)

        top = (in_period.values('user_id', 'user__fullname', 'user__username', 'user__department__department')
               .annotate(n=Count('id'), last=models_Max('timestamp')).order_by('-n')[:6])
        top_staff = [{'user_id': r['user_id'], 'name': r['user__fullname'] or r['user__username'],
                      'username': r['user__username'], 'department': r['user__department__department'],
                      'events': r['n'], 'last': r['last'].isoformat()} for r in top]

        # ---- security checks (real, computed) ----
        staff = User.objects.filter(is_active=True)
        active_staff = staff.exclude(active='0')
        no_pin = [u for u in active_staff.only('id', 'fullname', 'username', 'pin') if not u.has_pin]
        fails_24h = Counter(logs.filter(activity_type='failed_login', timestamp__gte=now - timedelta(hours=24))
                            .values_list('user_id', flat=True))
        repeat_fail_ids = [uid for uid, n in fails_24h.items() if n >= 3]
        repeat_fail = list(User.objects.filter(id__in=repeat_fail_ids).values('id', 'fullname', 'username'))
        for u in repeat_fail:
            u['failures'] = fails_24h[u['id']]
        pin_fails_24h = Counter(logs.filter(activity_type='failed_pin', timestamp__gte=now - timedelta(hours=24))
                                .values_list('user_id', flat=True))
        repeat_pin = list(User.objects.filter(id__in=[uid for uid, n in pin_fails_24h.items() if n >= 3])
                          .values('id', 'fullname', 'username'))
        for u in repeat_pin:
            u['failures'] = pin_fails_24h[u['id']]
        admin_pw = _still_on_admin_credential('password_reset', ['password_change'])
        admin_pin = _still_on_admin_credential('pin_reset', ['pin_change', 'pin_created'])

        def people(rows, limit=5):
            return [{'id': r['id'] if isinstance(r, dict) else r.id,
                     'name': (r.get('fullname') or r.get('username')) if isinstance(r, dict) else (r.fullname or r.username),
                     **({'failures': r['failures']} if isinstance(r, dict) and 'failures' in r else {})}
                    for r in rows[:limit]]

        checks = [
            {'key': 'repeat_failures', 'title': 'Repeated failed sign-ins', 'count': len(repeat_fail),
             'level': 'critical' if repeat_fail else 'ok',
             'ok_text': 'No account has 3 or more failed sign-ins in the last 24 hours.',
             'text': '3 or more failed sign-ins in the last 24 hours. Confirm it was the staff member, or reset their password.',
             'people': people(repeat_fail), 'filter': 'failed_login'},
            {'key': 'repeat_pin_failures', 'title': 'Repeated wrong PINs', 'count': len(repeat_pin),
             'level': 'critical' if repeat_pin else 'ok',
             'ok_text': 'No session has 3 or more wrong PINs in the last 24 hours.',
             'text': '3 or more wrong PINs in the last 24 hours (dispensing, stock, lab results, consultations, '
                     'admissions...). Someone may be guessing a PIN: check who was using the computer.',
             'people': people(repeat_pin), 'filter': 'failed_pin'},
            {'key': 'admin_password', 'title': 'Using a password set by an admin', 'count': len(admin_pw),
             'level': 'warning' if admin_pw else 'ok',
             'ok_text': 'Everyone has changed any password an administrator set for them.',
             'text': 'An administrator set or reset these passwords and the staff member has not changed it since.',
             'people': people(admin_pw), 'filter': 'password_reset'},
            {'key': 'admin_pin', 'title': 'Using a PIN set by an admin', 'count': len(admin_pin),
             'level': 'warning' if admin_pin else 'ok',
             'ok_text': 'Everyone has changed any PIN an administrator set for them.',
             'text': 'Reset PINs (often the default) are still in use. Ask them to change it under My profile.',
             'people': people(admin_pin), 'filter': 'pin_reset'},
            {'key': 'no_pin', 'title': 'No security PIN', 'count': len(no_pin),
             'level': 'warning' if no_pin else 'ok',
             'ok_text': 'Every active staff member has a security PIN.',
             'text': 'These staff cannot authorise PIN-protected actions until they set one under My profile.',
             'people': people(no_pin), 'filter': None},
        ]

        events_today = logs.filter(timestamp__date=today).count()
        events_yday = logs.filter(timestamp__date=today - timedelta(days=1)).count()
        return Response({
            'period': period,
            'days': days,
            'from': start_day.isoformat(),
            'to': today.isoformat(),
            'kpis': {
                'events_today': events_today,
                'events_yesterday': events_yday,
                'signed_in_today': logs.filter(timestamp__date=today, activity_type='login').values('user_id').distinct().count(),
                'active_staff': active_staff.count(),
                'deactivated_staff': staff.filter(active='0').count(),
                'events': in_period.count(),
                'events_previous': prev_period.count(),
                'failed': in_period.filter(activity_type='failed_login').count(),
                'failed_previous': prev_period.filter(activity_type='failed_login').count(),
                'total_logged': logs.count(),
            },
            'daily': daily,
            'types': types,
            'top_staff': top_staff,
            'checks': checks,
            'timestamp': now.isoformat(),
        })


class VerifyStaffView(APIView):
    """Staff IDs allowed to self-register an account. Managing this list is a Task Manager job:
    an open endpoint would let anyone authorise an ID and then register with it."""
    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not _can_manage_staff(request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(NO_ACCESS['detail'])

    def get(self, request):
        rows = list(VerifyStaff.objects.order_by('-id').values('id', 'staff_id'))
        # An ID is "used" once an account exists with that username (registration checks exactly this).
        accounts = {
            u.username.lower(): u
            for u in User.objects.filter(username__in=[r['staff_id'] for r in rows]).select_related('department')
        }
        for r in rows:
            u = accounts.get(r['staff_id'].lower())
            r['registered'] = u is not None
            if u:
                r['account'] = {
                    'id': u.id,
                    'fullname': u.fullname or '',
                    'department': getattr(u.department, 'department', '') or '',
                    'active': str(u.active) == '1',
                    'date_joined': u.date_joined.isoformat() if getattr(u, 'date_joined', None) else None,
                }
        registered = sum(1 for r in rows if r['registered'])
        return Response({'total': len(rows), 'registered': registered,
                         'pending': len(rows) - registered, 'staff_ids': rows})

    def post(self, request):
        staff_id = str(request.data.get('staff_id', '') or '').strip()
        if not staff_id:
            return Response({'detail': 'Staff ID cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)
        if not STAFF_ID_RE.match(staff_id):
            return Response({'detail': 'Staff ID can only use letters, numbers, dot, dash or underscore '
                                       '(2-50 characters, no spaces).'}, status=status.HTTP_400_BAD_REQUEST)
        existing = VerifyStaff.objects.filter(staff_id__iexact=staff_id).first()
        if existing:
            return Response({'detail': f'Staff ID "{existing.staff_id}" is already authorised.',
                             'id': existing.id, 'staff_id': existing.staff_id},
                            status=status.HTTP_409_CONFLICT)
        obj = VerifyStaff.objects.create(staff_id=staff_id)
        taken = User.objects.filter(username__iexact=staff_id).exists()
        return Response({'detail': 'Staff ID authorised.', 'id': obj.id, 'staff_id': obj.staff_id,
                         'registered': taken}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        pk = request.query_params.get('id')
        if pk:
            VerifyStaff.objects.filter(id=pk).delete()
            return Response({'detail': 'Staff ID deleted successfully.'})
        return Response({'detail': 'ID is required.'}, status=status.HTTP_400_BAD_REQUEST)


class QueueMonitorView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _can_manage_staff(request.user):
            return Response(NO_ACCESS, status=status.HTTP_403_FORBIDDEN)
        nurse_waiting = NurseWaitingList.objects.count()
        lab_waiting = RadiologyLab.objects.filter(radiolab_waiting_status=1, completed=0).count()
        lab_completed = RadiologyLab.objects.filter(completed=1).count()

        return Response({
            'waiting': {
                'doctor_waiting': 2,
                'nurse_waiting': nurse_waiting,
                'lab_waiting': lab_waiting,
                'pharmacy_waiting': 1,
            },
            'completed': {
                'doctor_completed': 5,
                'nurse_completed': 12,
                'lab_completed': lab_completed,
                'pharmacy_dispensed': 18,
            }
        })


_ICD_SUFFIX = re.compile(r'\s*\[\s*ICD[-\s]?\d*\s*:\s*([^\]]*)\]\s*$', re.I)
_ICD_PREFIX = re.compile(r'^[A-Z]\d{1,2}(?:\.\d{1,3})?\s*-\s*')
STATS_PERIODS = {'7': 7, '30': 30, '90': 90, '365': 365, 'all': None}


def split_diagnosis(text):
    """'Malaria due to P. falciparum [ICD-11: 1F40.Z]' -> ('Malaria due to P. falciparum', '1F40.Z')."""
    text = (text or '').strip()
    code = ''
    m = _ICD_SUFFIX.search(text)
    if m:
        code = m.group(1).strip()
        text = text[:m.start()].strip()
    text = _ICD_PREFIX.sub('', text).strip()
    if code.upper() == 'LOCAL':
        code = ''
    return text, code


def diagnosis_frequencies(start=None, end=None):
    """Count encounter diagnoses between start (inclusive) and end (exclusive).
    The same condition with or without its ICD tag counts as one."""
    from queue_operations.models import PatientEncounter
    qs = PatientEncounter.objects.exclude(diagnosis__isnull=True).exclude(diagnosis='')
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lt=end)
    groups, patients = {}, set()
    for diagnosis, patient_id in qs.order_by().values_list('diagnosis', 'patient_id').iterator():
        name, code = split_diagnosis(diagnosis)
        if not name:
            continue
        g = groups.setdefault(name.lower(), {'diagnosis': name, 'code': '', 'cases': 0, 'patients': set()})
        g['cases'] += 1
        g['patients'].add(patient_id)
        g['code'] = g['code'] or code
        patients.add(patient_id)
    return groups, patients


def _service_of(line):
    """Which part of the hospital an invoice line belongs to (from its source record + product text)."""
    src = (line.get('original_source_model') or '').strip()
    prod = (line.get('product') or '').strip().lower()
    if prod.startswith('care package') or src == 'Packages':
        return 'Care packages'
    if src == 'RadiologyLab':
        return 'Radiology' if prod.startswith('scan') else 'Laboratory'
    return {
        'GetRegistrationFee': 'Registration',
        'PatientAppointment': 'Consultation',
        'Appointment': 'Consultation',
        'WrittenPrescriptions': 'Pharmacy',
        'ImmunizationRecord': 'Immunization',
        'AdmissionTable': 'Inpatient',
    }.get(src, 'Other services')


def _pay_kind(payment_type):
    """'claim' (owed by an HMO), 'mixed' (part cash, part claim) or 'collected' (money received)."""
    t = (payment_type or '').lower()
    if 'claim' in t:
        return 'mixed' if any(w in t for w in ('cash', 'pos', 'transfer', 'deposit', 'card')) else 'claim'
    return 'collected'


def _pay_label(payment_type):
    t = (payment_type or '').strip()
    if not t:
        return 'Not recorded'
    if _pay_kind(t) == 'claim':
        return 'HMO claim'
    return t


def financial_summary(start, end, bucket):
    """Real receipts in [start, end): totals by payment kind / method / service / cashier, plus a trend.
    A receipt is split across its invoice lines in proportion to their value, so service totals add up
    to the receipt totals exactly (instalments on a package are spread the same way)."""
    from collections import defaultdict
    from django.db.models.functions import TruncDate, TruncMonth
    from Billings.models import Refund, Deposit

    rq = Receipt.objects.all()
    if start:
        rq = rq.filter(created_date__gte=start)
    if end:
        rq = rq.filter(created_date__lt=end)
    receipts = list(rq.values('id', 'invoice_number', 'total_price', 'payment_type', 'patient_id',
                              'staff_id', 'staff__fullname', 'staff__username', 'created_date'))

    kinds = {'collected': 0, 'claim': 0, 'mixed': 0}
    methods = defaultdict(lambda: {'total': 0, 'count': 0, 'kind': 'collected'})
    cashiers = defaultdict(lambda: {'total': 0, 'count': 0, 'name': ''})
    for r in receipts:
        amt = r['total_price'] or 0
        kind = _pay_kind(r['payment_type'])
        kinds[kind] += amt
        m = methods[_pay_label(r['payment_type'])]
        m['total'] += amt
        m['count'] += 1
        m['kind'] = kind
        if r['staff_id']:
            c = cashiers[r['staff_id']]
            c['total'] += amt
            c['count'] += 1
            c['name'] = r['staff__fullname'] or r['staff__username']

    # ---- services: split each receipt over its invoice lines ----
    inv_nums = {r['invoice_number'] for r in receipts if r['invoice_number']}
    lines_by_inv = defaultdict(list)
    for ln in Invoice.objects.filter(invoice_number__in=inv_nums).values(
            'invoice_number', 'product', 'price', 'discount', 'original_source_model'):
        lines_by_inv[ln['invoice_number']].append(ln)
    services = defaultdict(lambda: {'amount': 0.0, 'receipts': set()})
    for r in receipts:
        amt = r['total_price'] or 0
        lines = lines_by_inv.get(r['invoice_number']) or []
        weights = [max(0.0, float(l['price'] or 0) * (1 - float(l['discount'] or 0) / 100.0)) for l in lines]
        wsum = sum(weights)
        if not lines or wsum <= 0:
            services['Other services']['amount'] += amt
            services['Other services']['receipts'].add(r['id'])
            continue
        for l, w in zip(lines, weights):
            key = _service_of(l)
            services[key]['amount'] += amt * w / wsum
            services[key]['receipts'].add(r['id'])

    # ---- trend ----
    trunc = TruncMonth if bucket == 'month' else TruncDate
    trend_rows = (rq.annotate(b=trunc('created_date')).values('b', 'payment_type')
                  .annotate(total=Sum('total_price')).order_by('b'))
    trend = defaultdict(lambda: {'collected': 0, 'claim': 0, 'mixed': 0})
    for t in trend_rows:
        b = t['b'].date() if hasattr(t['b'], 'date') else t['b']
        trend[b.isoformat()][_pay_kind(t['payment_type'])] += t['total'] or 0

    fq = Refund.objects.all()
    dq = Deposit.objects.all()
    if start:
        fq, dq = fq.filter(created_date__gte=start), dq.filter(created_date__gte=start)
    if end:
        fq, dq = fq.filter(created_date__lt=end), dq.filter(created_date__lt=end)
    refunds = fq.aggregate(t=Sum('amount'), n=Count('id'))
    deposits = dq.aggregate(t=Sum('amount'), n=Count('id'))

    total = sum(kinds.values())
    svc = sorted(({'service': k, 'amount': round(v['amount']), 'receipts': len(v['receipts'])}
                  for k, v in services.items()), key=lambda x: -x['amount'])
    # rounding: make the service amounts add up to the receipt total exactly
    if svc:
        svc[0]['amount'] += total - sum(x['amount'] for x in svc)
    return {
        'total': total,
        'receipts': len(receipts),
        'patients': len({r['patient_id'] for r in receipts if r['patient_id']}),
        'collected': kinds['collected'],
        'claims': kinds['claim'],
        'mixed': kinds['mixed'],
        'refunds': refunds['t'] or 0,
        'refund_count': refunds['n'] or 0,
        'deposits': deposits['t'] or 0,
        'deposit_count': deposits['n'] or 0,
        'payment_methods': sorted(({'method': k, **v} for k, v in methods.items()), key=lambda x: -x['total']),
        'services': svc,
        'cashiers': sorted(({'staff_id': k, **v} for k, v in cashiers.items()), key=lambda x: -x['total'])[:5],
        'trend': [{'date': k, **v} for k, v in sorted(trend.items())],
    }


class StatisticalInsightsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _can_manage_staff(request.user):
            return Response(NO_ACCESS, status=status.HTTP_403_FORBIDDEN)
        # ---- Diagnosis frequencies from real encounters ----
        period = request.query_params.get('period', '30')
        if period not in STATS_PERIODS:
            period = '30'
        days = STATS_PERIODS[period]
        now = timezone.now()
        start = now - timedelta(days=days) if days else None
        groups, patients = diagnosis_frequencies(start=start)
        previous = {}
        if days:
            previous, _ = diagnosis_frequencies(start=start - timedelta(days=days), end=start)

        total = sum(g['cases'] for g in groups.values())
        ranked = sorted(groups.items(), key=lambda kv: (-kv[1]['cases'], kv[1]['diagnosis'].lower()))
        diagnoses = []
        for key, g in ranked[:10]:
            prev = previous.get(key, {}).get('cases', 0) if days else None
            diagnoses.append({
                'diagnosis': g['diagnosis'],
                'code': g['code'],
                'cases': g['cases'],
                'patients': len(g['patients']),
                'percentage': round(g['cases'] * 100 / total, 1) if total else 0,
                'previous_cases': prev,
            })
        diagnosis_summary = {
            'period': period,
            'days': days,
            'from': start.date().isoformat() if start else None,
            'to': now.date().isoformat(),
            'total_cases': total,
            'unique_conditions': len(groups),
            'unique_patients': len(patients),
            'previous_total': sum(g['cases'] for g in previous.values()) if days else None,
            'other_cases': total - sum(d['cases'] for d in diagnoses),
        }

        # ---- Financial analytics from real receipts (same period as the diagnoses) ----
        bucket = 'month' if (not days or days > 90) else 'day'
        fin = financial_summary(start, None, bucket)
        if days:
            prev = financial_summary(start - timedelta(days=days), start, bucket)
            fin['previous'] = {k: prev[k] for k in ('total', 'collected', 'claims', 'mixed', 'receipts', 'refunds')}
            prev_svc = {x['service']: x['amount'] for x in prev['services']}
            for x in fin['services']:
                x['previous_amount'] = prev_svc.get(x['service'], 0)
        else:
            fin['previous'] = None
        fin.update({'period': period, 'days': days, 'bucket': bucket,
                    'from': start.date().isoformat() if start else None, 'to': now.date().isoformat()})

        return Response({
            'diagnosis_analytics': diagnoses,
            'diagnosis_summary': diagnosis_summary,
            'financial_analytics': fin,
        })
