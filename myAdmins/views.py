import pandas as pd
from django.http import Http404, HttpResponse, JsonResponse
import os
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
import json
from django.db.models import Q, Max, Min
from django.utils import timezone
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from queue_operations.models import  NurseWaitingList, DoctorWaitingList
from radio_lab.models import  RadiologyLab, ScanResult, LabResult
from users.models import User
from IPD_pharm.models import  IPDAdministeredDrugs
from IPD_pharm2.models import IPD2AdministeredDrugs
from IPD_pharm3.models import IPD3AdministeredDrugs
from OPD_pharm.models import OPDAdministeredDrugs
from OPD_pharm2.models import OPD2AdministeredDrugs
from queue_operations.models import PatientEncounter
from Billings.models import Invoice
from patients.models import PatientCategory
from users.models import VerifyStaff
from .models import UserActivityLog, UserSession
from .forms import StaffUploadForm

from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.hashers import make_password
from .utils import log_user_activity, get_online_users, get_online_users_count
from django.views.decorators.http import require_http_methods
from collections import Counter
from decimal import Decimal
from .utils import get_service_type_mapping, calculate_revenue
from django.db.models import Func, IntegerField
from calendar import monthrange

today = timezone.now().date()

@login_required(login_url='login')
def verify_staff(request):
    if request.method == 'POST':
        form = StaffUploadForm(request.POST, request.FILES)
        
        if form.is_valid():
            staff_id_input = form.cleaned_data.get('staff_id')
            excel_file = request.FILES.get('excel_file')

            # Handle Manual Text Input
            if staff_id_input:
                VerifyStaff.objects.get_or_create(staff_id=staff_id_input)
                messages.success(request, f"Added: {staff_id_input}")

            # Handle Excel Upload
            if excel_file:
                try:
                    df = pd.read_excel(excel_file)
                    # Ensure the Excel has a column named 'staff_id'
                    if 'staff_id' in df.columns:
                        for identifier in df['staff_id']:
                            # Clean the data (to remove NaN and convert to string)
                            if pd.notna(identifier):
                                VerifyStaff.objects.get_or_create(staff_id=str(identifier).strip())
                        messages.success(request, "Excel data imported successfully!")
                    else:
                        messages.error(request, "Excel file missing 'staff_id' column.")
                except Exception as e:
                    messages.error(request, f"Error processing file: {e}")

            return redirect('verify_staff')
    else:
        form = StaffUploadForm()

    staff_members = VerifyStaff.objects.all()

    # Getting usernames from the CUSTOM user model
    registered_usernames = User.objects.values_list('username', flat=True)

    for staff in staff_members:
        if staff.staff_id in registered_usernames:
            staff.used = 1
        else:
            staff.used = 0

    context = {
        'form': StaffUploadForm(),
        'staff_members': staff_members,
        'counts': staff_members.count()
    }
    return render(request, 'myAdmins/staff_list.html', context)


@login_required(login_url='login')
def download_import_staffID_template(request):
    """Serve template Excel file"""
    template_path = os.path.join(settings.BASE_DIR, 'static', 'files', 'staffID_import_template.xlsx')
    if os.path.exists(template_path):
        with open(template_path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type="application/vnd.ms-excel")
            response['Content-Disposition'] = 'attachment; filename=staffID_import_template.xlsx'
            return response
    raise Http404


@login_required(login_url='login')
def delete_staff_id(request, pk):
    staff = get_object_or_404(VerifyStaff, pk=pk)
    staff.delete()
    return redirect('verify_staff')

@login_required(login_url='login')
def admin_home(request):
    return render(request, 'myAdmins/my_admin.html')

@login_required(login_url='login')
def staff_manager(request):
    get_users = User.objects.all().order_by('department')
    context={
        'get_users':get_users,
        'counts':get_users.count(),
    }
    return render(request, 'myAdmins/staff_record.html', context)


@login_required(login_url='login')
@csrf_exempt
@require_http_methods(["POST"])
def staff_action(request):
    try:
        data = json.loads(request.body)
        action = data.get('action')
        user_id = data.get('user_id')
        pin_code = data.get('pin_code')
        
        # Verify admin pin
        if not pin_code:
            return JsonResponse({'success': False, 'message': 'PIN code is required'})
        
        try:
            pin_code = int(pin_code)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid PIN format'})
        
        # Authenticate the admin's PIN
        if request.user.pin != pin_code:
            # Log failed PIN attempt by admin
            log_user_activity(
                request.user, 
                'failed_login', 
                request, 
                f"Failed PIN verification attempt for admin action: {action} on user ID: {user_id}"
            )
            return JsonResponse({'success': False, 'message': 'Invalid admin PIN. Please try again.'})
        
        # Get the target user
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'User not found'})
        
        # Perform the requested action with logging
        if action == 'reset_password':
            # Store old password hash for audit 
            old_password = target_user.password
            
            # Reset password
            target_user.password = make_password('password123')
            target_user.save()
            
            # Log the activity for the TARGET user
            log_user_activity(
                target_user, 
                'password_reset', 
                request, 
                f"Password was reset by admin: {request.user.fullname}",
                {
                    'action_by': request.user.id, 
                    'action_by_name': request.user.fullname,
                    'action_by_email': request.user.email
                }
            )
            
            # Log the activity for the ADMIN user
            log_user_activity(
                request.user, 
                'account_accessed', 
                request, 
                f"Admin reset password for user: {target_user.fullname} (ID: {target_user.id})",
                {
                    'target_user': target_user.id,
                    'target_user_name': target_user.fullname,
                    'action': 'reset_password'
                }
            )
            
            return JsonResponse({
                'success': True, 
                'message': f'Password for {target_user.fullname} has been reset to "password123"'
            })
        
        elif action == 'reset_pin':
            old_pin = target_user.pin
            
            # Reset PIN
            target_user.pin = 1234
            target_user.save()
            
            # Log the activity for the TARGET user
            log_user_activity(
                target_user, 
                'pin_reset', 
                request, 
                f"PIN was reset by admin: {request.user.fullname}",
                {
                    'action_by': request.user.id, 
                    'action_by_name': request.user.fullname,
                    'old_pin': '****',  
                    'new_pin': '****'
                }
            )
            
            # Log the activity for the ADMIN user
            log_user_activity(
                request.user, 
                'account_accessed', 
                request, 
                f"Admin reset PIN for user: {target_user.fullname} (ID: {target_user.id})",
                {
                    'target_user': target_user.id,
                    'target_user_name': target_user.fullname,
                    'action': 'reset_pin'
                }
            )
            
            return JsonResponse({
                'success': True, 
                'message': f'PIN for {target_user.fullname} has been reset to "1234"'
            })
        
        elif action == 'deactivate':
            # Check if user is already deactivated
            if target_user.active == '0':
                return JsonResponse({'success': False, 'message': f'{target_user.fullname} is already deactivated'})
            
            # Deactivate user
            target_user.active = '0'
            target_user.save()
            
            # Log the activity for the TARGET user
            log_user_activity(
                target_user, 
                'deactivated', 
                request, 
                f"Account was deactivated by admin: {request.user.fullname}",
                {
                    'action_by': request.user.id, 
                    'action_by_name': request.user.fullname,
                    'previous_status': 'Active',
                    'new_status': 'Deactivated'
                }
            )
            
            # Log the activity for the ADMIN user
            log_user_activity(
                request.user, 
                'account_accessed', 
                request, 
                f"Admin deactivated user: {target_user.fullname} (ID: {target_user.id})",
                {
                    'target_user': target_user.id,
                    'target_user_name': target_user.fullname,
                    'action': 'deactivate'
                }
            )
            
            return JsonResponse({
                'success': True, 
                'message': f'{target_user.fullname} has been deactivated',
                'new_status': 'deactivated'
            })
        
        elif action == 'activate':
            # Check if user is already active
            if target_user.active == '1':
                return JsonResponse({'success': False, 'message': f'{target_user.fullname} is already active'})
            
            # Activate user
            target_user.active = '1'
            target_user.save()
            
            # Log the activity for the TARGET user
            log_user_activity(
                target_user, 
                'activated', 
                request, 
                f"Account was activated by admin: {request.user.fullname}",
                {
                    'action_by': request.user.id, 
                    'action_by_name': request.user.fullname,
                    'previous_status': 'Deactivated',
                    'new_status': 'Active'
                }
            )
            
            # Log the activity for the ADMIN user
            log_user_activity(
                request.user, 
                'account_accessed', 
                request, 
                f"Admin activated user: {target_user.fullname} (ID: {target_user.id})",
                {
                    'target_user': target_user.id,
                    'target_user_name': target_user.fullname,
                    'action': 'activate'
                }
            )
            
            return JsonResponse({
                'success': True, 
                'message': f'{target_user.fullname} has been activated',
                'new_status': 'activated'
            })
        
        else:
            return JsonResponse({'success': False, 'message': f'Invalid action: {action}'})
            
    except Exception as e:
        print(f"Error in staff_action: {str(e)}")
        return JsonResponse({'success': False, 'message': f'An error occurred: {str(e)}'})


@login_required(login_url='login')
def user_activities(request, user_id=None):
    """
    View to display user activities
    """
    if user_id:
        # Show activities for specific user
        user = User.objects.get(id=user_id)
        activities = UserActivityLog.objects.filter(user=user)
        template = 'myAdmins/user_activities.html'
        context = {
            'activities': activities,
            'user': user,
            'total_count': activities.count(),
        }
    else:
        # Show all activities (admin view)
        activities = UserActivityLog.objects.all()
        template = 'myAdmins/all_activities.html'
        
        # Get all users for filter
        all_users = User.objects.all()
        
        # Apply filters
        activity_type = request.GET.get('type')
        if activity_type:
            activities = activities.filter(activity_type=activity_type)
        
        # Date range filter
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        if start_date:
            activities = activities.filter(timestamp__date__gte=start_date)
        if end_date:
            activities = activities.filter(timestamp__date__lte=end_date)
        
        # User filter
        user_filter = request.GET.get('user')
        if user_filter:
            activities = activities.filter(user_id=user_filter)
        
        #  pagination
        from django.core.paginator import Paginator
        paginator = Paginator(activities, 25)  # 25 items per page
        page_number = request.GET.get('page')
        activities_page = paginator.get_page(page_number)
        
        # Build filter params for pagination
        filters_params = ''
        if activity_type:
            filters_params += f'&type={activity_type}'
        if start_date:
            filters_params += f'&start_date={start_date}'
        if end_date:
            filters_params += f'&end_date={end_date}'
        if user_filter:
            filters_params += f'&user={user_filter}'
        
        context = {
            'activities': activities_page,
            'activity_types': UserActivityLog.ACTIVITY_TYPES,
            'current_type': activity_type,
            'start_date': start_date,
            'end_date': end_date,
            'total_count': UserActivityLog.objects.count(),
            'all_users': all_users,
            'filters_params': filters_params,
        }
    
    return render(request, template, context)


@login_required(login_url='login')
def activity_dashboard(request):
    """Dashboard showing activity statistics"""
    from django.db.models import Count, Q
    from datetime import timedelta
    
    # Get current time and start of today
    now = timezone.now()
    today_start = timezone.make_aware(datetime.combine(now.date(), datetime.min.time()))
    today_end = timezone.make_aware(datetime.combine(now.date(), datetime.max.time()))
    
    # Get last 30 days activities
    last_30_days = now - timedelta(days=30)
    
    # Statistics
    total_activities = UserActivityLog.objects.count()
    activities_last_30_days = UserActivityLog.objects.filter(timestamp__gte=last_30_days).count()
    
    # Today's activities - using range
    today_activities = UserActivityLog.objects.filter(
        timestamp__range=[today_start, today_end]
    ).count()
    
    # Activity breakdown by type
    activity_breakdown = UserActivityLog.objects.values('activity_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Top 5 most active users - include user ID
    active_users = UserActivityLog.objects.values(
        'user__id',
        'user__username', 
        'user__fullname'
    ).annotate(
        activity_count=Count('id')
    ).order_by('-activity_count')[:5]
    
    context = {
        'total_activities': total_activities,
        'activities_last_30_days': activities_last_30_days,
        'today_activities': today_activities,
        'activity_breakdown': activity_breakdown,
        'active_users': active_users,
    }
    
    return render(request, 'myAdmins/activity_dashboard.html', context)


@login_required(login_url='login')
def online_users(request):
    """View to display currently online users"""
    
    # Get online users (active within last 5 minutes)
    online_users = get_online_users(timeout_minutes=5)
    
    # Get statistics
    total_online = len(online_users)
    
    # Group by device type
    devices = {
        'Desktop': 0,
        'Mobile': 0,
        'Tablet': 0,
        'Unknown': 0
    }
    
    for user in online_users:
        device_type = user['device'] if user['device'] else 'Unknown'
        devices[device_type] = devices.get(device_type, 0) + 1
    
    context = {
        'online_users': online_users,
        'total_online': total_online,
        'devices': devices,
        'timeout_minutes': 5,
    }
    
    return render(request, 'myAdmins/online_users.html', context)


@login_required(login_url='login')
@require_http_methods(["GET"])
def online_users_api(request):
    """API endpoint to get online users (for real-time updates)"""
    online_users = get_online_users(timeout_minutes=5)
    
    # Prepare data for JSON response
    users_data = []
    for user in online_users:
        users_data.append({
            'id': user['user'].id,
            'username': user['user'].username,
            'fullname': user['user'].fullname or user['user'].username,
            'avatar': user['user'].avatar.url if user['user'].avatar else None,
            'department': str(user['user'].department) if user['user'].department else None,
            'last_activity': user['last_activity'].strftime('%Y-%m-%d %H:%M:%S'),
            'browser': user['browser'],
            'os': user['os'],
            'device': user['device'],
            'ip_address': user['ip_address'],
        })
    
    return JsonResponse({
        'total': len(users_data),
        'users': users_data
    })


@login_required(login_url='login')
@require_http_methods(["POST"])
def force_logout_user(request, user_id):
    """Force logout a specific user"""
    try:
        from django.contrib.sessions.models import Session
        from .models import UserSession
        
        # Prevent self logout
        if request.user.id == user_id:
            return JsonResponse({'error': 'You cannot force logout yourself!'}, status=400)
        
        # Get active sessions for the user
        user_sessions = UserSession.objects.filter(user_id=user_id)
        
        if not user_sessions.exists():
            return JsonResponse({'error': 'No active sessions found for this user.'}, status=404)
        
        # Get all session keys
        session_keys = user_sessions.values_list('session_key', flat=True)
        
        # Delete Django sessions
        Session.objects.filter(session_key__in=session_keys).delete()
        
        # Get user info for response
        target_user = User.objects.get(id=user_id)
        
        try:
            from .utils import log_user_activity
            log_user_activity(
                request.user,
                'account_accessed',
                request,
                f"Admin @{request.user.username} forcefully logged out user @{target_user.username}",
                {
                    'action': 'force_logout',
                    'target_user': target_user.id,
                }
            )
        except:
            pass  # Skip logging if there's an error
        
        # Delete user session records
        user_sessions.delete()
        
        return JsonResponse({
            'success': True, 
            'message': f'{target_user.fullname} has been forcefully logged out.'
        })
        
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def clean_diagnosis(diagnosis_text):
    """Remove ICD-10 codes from diagnosis (e.g., 'O99.019 - Anemia' -> 'Anemia')"""
    if not diagnosis_text:
        return diagnosis_text
    
    import re
    # Pattern matches: letter(s) + numbers + optional dot + numbers + space + dash + space
    pattern = r'^[A-Z]\d{1,2}\.\d{1,3}\s*-\s*'
    cleaned = re.sub(pattern, '', diagnosis_text)
    
    # Also handle cases without space after dash
    pattern2 = r'^[A-Z]\d{1,2}\.\d{1,3}\s*-'
    cleaned = re.sub(pattern2, '', cleaned).strip()
    
    return cleaned if cleaned else diagnosis_text

@login_required(login_url='login')
def diagnosis_analytics(request):
    """Diagnosis analytics dashboard with filters"""
    # print(f"Request type: {type(request)}")
    # print(f"Request object: {request}")
    # print(f"Is authenticated: {request.user.is_authenticated if hasattr(request, 'user') else 'No user attribute'}")
    
    # Get filter parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    patient_category_id = request.GET.get('patient_category')  
    
    # Base queryset
    encounters = PatientEncounter.objects.filter(
        diagnosis__isnull=False
    ).exclude(diagnosis='')
    
    # Apply date filter
    if start_date:
        encounters = encounters.filter(created_at__date__gte=start_date)
    if end_date:
        encounters = encounters.filter(created_at__date__lte=end_date)
    
    # Apply patient category filter - Now filtering by ForeignKey ID
    if patient_category_id and patient_category_id != '' and patient_category_id != 'None':
        try:
            encounters = encounters.filter(patient__category_id=int(patient_category_id))
        except (ValueError, TypeError):
            pass
    
    # Get all diagnosis for counting - clean the diagnosis codes
    all_diagnoses = []
    for encounter in encounters:
        if encounter.diagnosis:
            # Clean the diagnosis first
            cleaned_diagnosis = clean_diagnosis(encounter.diagnosis)
            
            # Split multiple diagnoses if separated by commas
            if ',' in cleaned_diagnosis:
                diagnoses = [d.strip() for d in cleaned_diagnosis.split(',')]
            else:
                diagnoses = [cleaned_diagnosis]
            all_diagnoses.extend(diagnoses)
    
    # Count frequency of each diagnosis
    diagnosis_counts = Counter(all_diagnoses)
    
    # Get top 10 diagnoses
    top_10_diagnoses = diagnosis_counts.most_common(10)
    
    # Get bottom 10 diagnoses (least frequent)
    if len(diagnosis_counts) >= 10:
        bottom_10_diagnoses = diagnosis_counts.most_common()[:-11:-1]
    else:
        bottom_10_diagnoses = list(diagnosis_counts.items())
    
    # Prepare data for charts
    top_labels = [item[0][:35] + '...' if len(item[0]) > 35 else item[0] for item in top_10_diagnoses]
    top_data = [item[1] for item in top_10_diagnoses]
    
    bottom_labels = [item[0][:35] + '...' if len(item[0]) > 35 else item[0] for item in bottom_10_diagnoses]
    bottom_data = [item[1] for item in bottom_10_diagnoses]
    
    # Get unique patient categories for filter - Now using PatientCategory model
    patient_categories = PatientCategory.objects.all().order_by('category')
    
    # Get available date range from data
    date_range = encounters.aggregate(
        min_date=Min('created_at'),
        max_date=Max('created_at')
    )
    
    context = {
        'top_diagnoses': top_10_diagnoses,
        'bottom_diagnoses': bottom_10_diagnoses,
        'top_labels': json.dumps(top_labels),
        'top_data': json.dumps(top_data),
        'bottom_labels': json.dumps(bottom_labels),
        'bottom_data': json.dumps(bottom_data),
        'patient_categories': patient_categories,
        'selected_category_id': patient_category_id,
        'start_date': start_date,
        'end_date': end_date,
        'total_encounters': encounters.count(),
        'unique_diagnoses': len(diagnosis_counts),
        'min_date': date_range['min_date'].strftime('%Y-%m-%d') if date_range['min_date'] else None,
        'max_date': date_range['max_date'].strftime('%Y-%m-%d') if date_range['max_date'] else None,
    }
    
    return render(request, 'myAdmins/diagnosis_analytics.html', context)

@login_required(login_url='login')
@require_http_methods(["GET"])
def diagnosis_analytics_api(request):
    """API endpoint for real-time data updates"""
    
    # Get filter parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    patient_category_id = request.GET.get('patient_category')
    
    # Base queryset
    encounters = PatientEncounter.objects.filter(
        diagnosis__isnull=False
    ).exclude(diagnosis='')
    
    # Apply filters
    if start_date:
        encounters = encounters.filter(created_at__date__gte=start_date)
    if end_date:
        encounters = encounters.filter(created_at__date__lte=end_date)
    if patient_category_id and patient_category_id != '' and patient_category_id != 'None':
        try:
            encounters = encounters.filter(patient__category_id=int(patient_category_id))
        except (ValueError, TypeError):
            pass
    
    # Count diagnoses with cleaning
    all_diagnoses = []
    for encounter in encounters:
        if encounter.diagnosis:
            cleaned_diagnosis = clean_diagnosis(encounter.diagnosis)
            if ',' in cleaned_diagnosis:
                diagnoses = [d.strip() for d in cleaned_diagnosis.split(',')]
            else:
                diagnoses = [cleaned_diagnosis]
            all_diagnoses.extend(diagnoses)
    
    diagnosis_counts = Counter(all_diagnoses)
    top_10 = diagnosis_counts.most_common(10)
    
    if len(diagnosis_counts) >= 10:
        bottom_10 = diagnosis_counts.most_common()[:-11:-1]
    else:
        bottom_10 = list(diagnosis_counts.items())
    
    return JsonResponse({
        'top_diagnoses': [{'name': d[0], 'count': d[1]} for d in top_10],
        'bottom_diagnoses': [{'name': d[0], 'count': d[1]} for d in bottom_10],
        'total_encounters': encounters.count(),
        'unique_diagnoses': len(diagnosis_counts),
        'total_diagnosis_records': len(all_diagnoses),
    })



class YearUTC(Func):
    function = 'YEAR'
    output_field = IntegerField()

@login_required(login_url='login')
def financial_analytics(request):
    view_type = request.GET.get('view_type', 'daily')
    service_type = request.GET.get('service_type', '').strip()

    context = {
        'view_type': view_type,
        'selected_service': service_type,
        'service_types': get_service_type_mapping().keys(),
    }

    base_invoices = Invoice.objects.filter(completed=1)

    if service_type and service_type in get_service_type_mapping():
        service_values = get_service_type_mapping()[service_type]
        base_invoices = base_invoices.filter(original_source_model__in=service_values)

    available_years = Invoice.objects.filter(completed=1).annotate(
        year=YearUTC('created_date')
    ).values_list('year', flat=True).distinct().order_by('-year')

    context['available_years'] = [{'year': y} for y in available_years if y]

    invoices = base_invoices

    if view_type == 'daily':
        start_date_str = request.GET.get('start_date', '').strip()
        end_date_str = request.GET.get('end_date', '').strip()

        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                context['start_date'] = start_date_str
                context['end_date'] = end_date_str
                start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
                end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
                invoices = invoices.filter(created_date__range=(start_dt, end_dt))
            except ValueError:
                pass
        else:
            latest_invoice = base_invoices.order_by('-created_date').first()
            if latest_invoice:
                latest_date = timezone.localtime(latest_invoice.created_date).date()
                context['start_date'] = latest_date.strftime('%Y-%m-%d')
                context['end_date'] = latest_date.strftime('%Y-%m-%d')
                start_dt = timezone.make_aware(datetime.combine(latest_date, datetime.min.time()))
                end_dt = timezone.make_aware(datetime.combine(latest_date, datetime.max.time()))
                invoices = invoices.filter(created_date__range=(start_dt, end_dt))

    elif view_type == 'monthly':
        selected_month_str = request.GET.get('selected_month', '').strip()
        selected_year_str = request.GET.get('selected_year', '').strip()

        try:
            if selected_month_str and selected_year_str:
                context['selected_month'] = int(selected_month_str)
                context['selected_year'] = int(selected_year_str)
            else:
                latest_invoice = base_invoices.order_by('-created_date').first()
                if latest_invoice:
                    latest_dt = timezone.localtime(latest_invoice.created_date)
                    context['selected_month'] = latest_dt.month
                    context['selected_year'] = latest_dt.year
                else:
                    now = timezone.localtime(timezone.now())
                    context['selected_month'] = now.month
                    context['selected_year'] = now.year
        except ValueError:
            now = timezone.localtime(timezone.now())
            context['selected_month'] = now.month
            context['selected_year'] = now.year

        year = context['selected_year']
        month = context['selected_month']
        _, last_day = monthrange(year, month)
        start_dt = timezone.make_aware(datetime(year, month, 1, 0, 0, 0))
        end_dt = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59, 999999))
        invoices = invoices.filter(created_date__range=(start_dt, end_dt))

    elif view_type == 'yearly':
        selected_year_str = request.GET.get('selected_year', '').strip()
        try:
            if selected_year_str:
                context['selected_year'] = int(selected_year_str)
            else:
                latest_invoice = base_invoices.order_by('-created_date').first()
                context['selected_year'] = timezone.localtime(latest_invoice.created_date).year if latest_invoice else timezone.localtime(timezone.now()).year
        except ValueError:
            context['selected_year'] = timezone.localtime(timezone.now()).year

        year = context['selected_year']
        start_dt = timezone.make_aware(datetime(year, 1, 1, 0, 0, 0))
        end_dt = timezone.make_aware(datetime(year, 12, 31, 23, 59, 59, 999999))
        invoices = invoices.filter(created_date__range=(start_dt, end_dt))

    # Revenue calculation 
    categories_with_data = invoices.filter(category__isnull=False).values_list('category', flat=True).distinct()
    all_categories = PatientCategory.objects.filter(id__in=categories_with_data)
    uncategorized_invoices = invoices.filter(category__isnull=True)

    category_revenue = []
    total_revenue = Decimal('0.00')

    # Uncategorized
    if uncategorized_invoices.exists():
        uncat_revenue = sum(calculate_revenue(inv.price) for inv in uncategorized_invoices)
        total_revenue += uncat_revenue
        category_revenue.append({
            'category': 'Uncategorized',
            'revenue': uncat_revenue,
            'count': uncategorized_invoices.count(),
            'percentage': 0
        })

    # By category
    for category in all_categories:
        cat_invoices = invoices.filter(category=category)
        revenue = sum(calculate_revenue(inv.price) for inv in cat_invoices)
        if revenue > 0:
            category_revenue.append({
                'category': category.category,
                'revenue': revenue,
                'count': cat_invoices.count(),
                'percentage': 0
            })
            total_revenue += revenue

    category_revenue.sort(key=lambda x: x['revenue'], reverse=True)
    for item in category_revenue:
        if total_revenue > 0:
            item['percentage'] = round((item['revenue'] / total_revenue) * 100, 2)

    if not category_revenue:
        category_revenue = [{'category': 'No Revenue Data', 'revenue': 0, 'count': 0, 'percentage': 0}]

    chart_data_items = [item for item in category_revenue if item['revenue'] > 0]

    context.update({
        'category_revenue': category_revenue,
        'total_revenue': total_revenue,
        'chart_labels': json.dumps([item['category'] for item in chart_data_items]),
        'chart_data': json.dumps([float(item['revenue']) for item in chart_data_items]),
    })

    return render(request, 'myAdmins/financial_analytics.html', context)
    

@login_required(login_url='login')
def nurse_queues_all(request):
    page = 'nurse_queue_all'
    nurse_queue = NurseWaitingList.objects.filter(
        completed=0,
        waiting_status=0,
        created_date__gte=timezone.now() - timedelta(hours=24)
    )
    return render(request, 'myAdmins/clinical_queue.html',{'page':page,'counts':nurse_queue.count(),'nurse_queue':nurse_queue})


@login_required(login_url='login')
def doctor_queues_all(request):
    page = 'doctor_queue_all'
    doctor_queue = DoctorWaitingList.objects.filter(
        completed=0, 
        waiting_status = 0, 
        created_date__gte=timezone.now() - timedelta(hours=24)
        )
    return render(request, 'myAdmins/clinical_queue.html',{'page':page,'doctor_counts':doctor_queue.count(),'doctor_queue':doctor_queue})


@login_required(login_url='login')
def scan_queues_all(request):
    page = 'scan_queue_all'
    time_threshold = timezone.now() - timedelta(hours=24)

    # Getting the latest unique patient transactions
    latest_ids = RadiologyLab.objects.filter(
        radiolab_waiting_status=0,
        billing_waiting_status=0,
        item_type='R',
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    # Fetch the records
    scan_queue = RadiologyLab.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    # Using a subquery-like logic to grab all items for each patient
    for record in scan_queue:
        # Getting all items for this specific patient within the timeframe
        items = RadiologyLab.objects.filter(
            patient=record.patient,
            item_type='R',
            radiolab_waiting_status=0,
            created_date__gte=time_threshold
        ).values_list('item', flat=True)
        
        # Joining the list into a single string
        record.all_investigations = ", ".join(items)

    return render(request, 'myAdmins/clinical_queue.html', {
        'page': page,
        'counts': scan_queue.count(), 
        'scan_queue': scan_queue
    })

@login_required(login_url='login')
def lab_queues_all(request):
    page = 'lab_queue_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    # Getting the latest unique patient transactions
    latest_ids = RadiologyLab.objects.filter(
        radiolab_waiting_status=0,
        billing_waiting_status=0,
        item_type='L',
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    # Fetch the records
    lab_queue = RadiologyLab.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    # Using a subquery-like logic to grab all items for each patient
    for record in lab_queue:
        # Getting all items for this specific patient within the timeframe
        items = RadiologyLab.objects.filter(
            patient=record.patient,
            item_type='L',
            radiolab_waiting_status=0,
            created_date__gte=time_threshold
        ).values_list('item', flat=True)
        
        # Joining the list into a single string
        record.all_investigations = ", ".join(items)

    return render(request, 'myAdmins/clinical_queue.html', {
        'page': page,
        'counts': lab_queue.count(), 
        'lab_queue': lab_queue
    })

@login_required(login_url='login')
def lab_result_queues_all(request):
    page = 'lab_result_queue_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = LabResult.objects.filter(
        waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    lab_result_queue = LabResult.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in lab_result_queue:
        items = LabResult.objects.filter(
            patient=record.patient,
            waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('investigation', flat=True)
        
        record.all_investigations = ", ".join(items)

    return render(request, 'myAdmins/clinical_queue.html', {
        'page': page,
        'counts': lab_result_queue.count(), 
        'lab_result_queue': lab_result_queue
    })



@login_required(login_url='login')
def scan_result_queues_all(request):
    page = 'scan_result_queue_all' 
    scan_result_queue = ScanResult.objects.filter(
            waiting_status=0,
            created_date__gte=timezone.now() - timedelta(hours=24),
            patient__isnull=False  
        ).values('patient').distinct()
    return render(request, 'myAdmins/clinical_queue.html',{'page':page,'counts':scan_result_queue.count()})

@login_required(login_url='login')
def scan_result_queues_all(request):
    page = 'scan_result_queue_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = ScanResult.objects.filter(
        waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    scan_result_queue = ScanResult.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in scan_result_queue:
        items = ScanResult.objects.filter(
            patient=record.patient,
            waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('investigation', flat=True)
        
        record.all_investigations = ", ".join(items)

    return render(request, 'myAdmins/clinical_queue.html', {
        'page': page,
        'counts': scan_result_queue.count(), 
        'scan_result_queue': scan_result_queue
    })


@login_required(login_url='login')
def drug_requests_ipd1_queues_all(request):
    page = 'drug_requests_ipd1_queues_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = IPDAdministeredDrugs.objects.filter(
        pharm_waiting_status=0,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    ipd1_drug_queue = IPDAdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in ipd1_drug_queue:
        items = IPDAdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=0,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_queue.html', {
        'page': page,
        'counts': ipd1_drug_queue.count(), 
        'ipd1_drug_queue': ipd1_drug_queue
    })


@login_required(login_url='login')
def drug_requests_ipd2_queues_all(request):
    page = 'drug_requests_ipd2_queues_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = IPD2AdministeredDrugs.objects.filter(
        pharm_waiting_status=0,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    ipd2_drug_queue = IPD2AdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in ipd2_drug_queue:
        items = IPD2AdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=0,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_queue.html', {
        'page': page,
        'counts': ipd2_drug_queue.count(), 
        'ipd2_drug_queue': ipd2_drug_queue
    })


@login_required(login_url='login')
def drug_requests_ipd3_queues_all(request):
    page = 'drug_requests_ipd3_queues_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = IPD3AdministeredDrugs.objects.filter(
        pharm_waiting_status=0,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    ipd3_drug_queue = IPD3AdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in ipd3_drug_queue:
        items = IPD3AdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=0,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_queue.html', {
        'page': page,
        'counts': ipd3_drug_queue.count(), 
        'ipd3_drug_queue': ipd3_drug_queue
    })


@login_required(login_url='login')
def drug_requests_opd_queues_all(request):
    page = 'drug_requests_opd_queues_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = OPDAdministeredDrugs.objects.filter(
        pharm_waiting_status=0,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    opd_drug_queue = OPDAdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in opd_drug_queue:
        items = OPDAdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=0,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_queue.html', {
        'page': page,
        'counts': opd_drug_queue.count(), 
        'opd_drug_queue': opd_drug_queue
    })


@login_required(login_url='login')
def drug_requests_opd2_queues_all(request):
    page = 'drug_requests_opd2_queues_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = OPD2AdministeredDrugs.objects.filter(
        pharm_waiting_status=0,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    opd2_drug_queue = OPD2AdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in opd2_drug_queue:
        items = OPD2AdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=0,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_queue.html', {
        'page': page,
        'counts': opd2_drug_queue.count(), 
        'opd2_drug_queue': opd2_drug_queue
    })



# completed list
@login_required(login_url='login')
def nurse_completes_all(request):
    page = 'nurse_complete_all'
    nurse_complete = NurseWaitingList.objects.filter(
        completed=0,
        waiting_status=1,
        created_date__gte=timezone.now() - timedelta(hours=24)
    )
    return render(request, 'myAdmins/clinical_completed.html',{'page':page,'counts':nurse_complete.count(),'nurse_complete':nurse_complete})


@login_required(login_url='login')
def doctor_completes_all(request):
    page = 'doctor_complete_all'
    doctor_complete = DoctorWaitingList.objects.filter(
        completed=0, 
        waiting_status = 1, 
        created_date__gte=timezone.now() - timedelta(hours=24)
        )
    return render(request, 'myAdmins/clinical_completed.html',{'page':page,'doctor_counts':doctor_complete.count(),'doctor_complete':doctor_complete})


@login_required(login_url='login')
def scan_completes_all(request):
    page = 'scan_complete_all'
    time_threshold = timezone.now() - timedelta(hours=24)

    # Getting the latest unique patient transactions
    latest_ids = RadiologyLab.objects.filter(
        radiolab_waiting_status=1,
        billing_waiting_status=0,
        item_type='R',
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    # Fetch the records
    scan_complete = RadiologyLab.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    # Using a subquery-like logic to grab all items for each patient
    for record in scan_complete:
        # Getting all items for this specific patient within the timeframe
        items = RadiologyLab.objects.filter(
            patient=record.patient,
            item_type='R',
            radiolab_waiting_status=1,
            created_date__gte=time_threshold
        ).values_list('item', flat=True)
        
        # Joining the list into a single string
        record.all_investigations = ", ".join(items)

    return render(request, 'myAdmins/clinical_completed.html', {
        'page': page,
        'counts': scan_complete.count(), 
        'scan_complete': scan_complete
    })


@login_required(login_url='login')
def lab_completes_all(request):
    page = 'lab_complete_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    # Getting the latest unique patient transactions
    latest_ids = RadiologyLab.objects.filter(
        radiolab_waiting_status=1,
        billing_waiting_status=0,
        item_type='L',
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    # Fetch the records
    lab_complete = RadiologyLab.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    # Using a subquery-like logic to grab all items for each patient
    for record in lab_complete:
        # Getting all items for this specific patient within the timeframe
        items = RadiologyLab.objects.filter(
            patient=record.patient,
            item_type='L',
            radiolab_waiting_status=1,
            created_date__gte=time_threshold
        ).values_list('item', flat=True)
        
        # Joining the list into a single string
        record.all_investigations = ", ".join(items)

    return render(request, 'myAdmins/clinical_completed.html', {
        'page': page,
        'counts': lab_complete.count(), 
        'lab_complete': lab_complete
    })


@login_required(login_url='login')
def lab_result_completes_all(request):
    page = 'lab_result_complete_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = LabResult.objects.filter(
        waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    lab_result_complete = LabResult.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff'
    ).order_by('-created_date')

    for record in lab_result_complete:
        items = LabResult.objects.filter(
            patient=record.patient,
            waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('investigation', flat=True)
        
        record.all_investigations = ", ".join(items)

    return render(request, 'myAdmins/clinical_completed.html', {
        'page': page,
        'counts': lab_result_complete.count(), 
        'lab_result_complete': lab_result_complete
    })


@login_required(login_url='login')
def scan_result_completes_all(request):
    page = 'scan_result_complete_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = ScanResult.objects.filter(
        waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    scan_result_complete = ScanResult.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff'
    ).order_by('-created_date')

    for record in scan_result_complete:
        items = ScanResult.objects.filter(
            patient=record.patient,
            waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('investigation', flat=True)
        
        record.all_investigations = ", ".join(items)

    return render(request, 'myAdmins/clinical_completed.html', {
        'page': page,
        'counts': scan_result_complete.count(), 
        'scan_result_complete': scan_result_complete
    })


@login_required(login_url='login')
def drug_requests_ipd1_completes_all(request):
    page = 'drug_requests_ipd1_completes_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = IPDAdministeredDrugs.objects.filter(
        pharm_waiting_status=1,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    ipd1_drug_complete = IPDAdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in ipd1_drug_complete:
        items = IPDAdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=1,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_completed.html', {
        'page': page,
        'counts': ipd1_drug_complete.count(), 
        'ipd1_drug_complete': ipd1_drug_complete
    })


@login_required(login_url='login')
def drug_requests_ipd2_completes_all(request):
    page = 'drug_requests_ipd2_completes_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = IPD2AdministeredDrugs.objects.filter(
        pharm_waiting_status=1,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    ipd2_drug_complete = IPD2AdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in ipd2_drug_complete:
        items = IPD2AdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=1,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_completed.html', {
        'page': page,
        'counts': ipd2_drug_complete.count(), 
        'ipd2_drug_complete': ipd2_drug_complete
    })


@login_required(login_url='login')
def drug_requests_ipd3_completes_all(request):
    page = 'drug_requests_ipd3_completes_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = IPD3AdministeredDrugs.objects.filter(
        pharm_waiting_status=1,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    ipd3_drug_complete = IPD3AdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in ipd3_drug_complete:
        items = IPD3AdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=1,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_completed.html', {
        'page': page,
        'counts': ipd3_drug_complete.count(), 
        'ipd3_drug_complete': ipd3_drug_complete
    })


@login_required(login_url='login')
def drug_requests_opd_completes_all(request):
    page = 'drug_requests_opd_completes_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = OPDAdministeredDrugs.objects.filter(
        pharm_waiting_status=1,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    opd_drug_complete = OPDAdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in opd_drug_complete:
        items = OPDAdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=1,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_completed.html', {
        'page': page,
        'counts': opd_drug_complete.count(), 
        'opd_drug_complete': opd_drug_complete
    })


@login_required(login_url='login')
def drug_requests_opd2_completes_all(request):
    page = 'drug_requests_opd2_completes_all' 
    time_threshold = timezone.now() - timedelta(hours=24)

    latest_ids = OPD2AdministeredDrugs.objects.filter(
        pharm_waiting_status=1,
        billing_waiting_status=0,
        created_date__gte=time_threshold,
        patient__isnull=False
    ).values('patient').annotate(latest_id=Max('id')).values_list('latest_id', flat=True)

    opd2_drug_complete = OPD2AdministeredDrugs.objects.filter(id__in=latest_ids).select_related(
        'patient', 'staff', 'patient__category', 'patient__plan'
    ).order_by('-created_date')

    for record in opd2_drug_complete:
        items = OPD2AdministeredDrugs.objects.filter(
            patient=record.patient,
            pharm_waiting_status=1,
            billing_waiting_status=0,
            created_date__gte=time_threshold,
        ).values_list('item', flat=True)
        
        record.all_medications = ", ".join(items)

    return render(request, 'myAdmins/clinical_completed.html', {
        'page': page,
        'counts': opd2_drug_complete.count(), 
        'opd2_drug_complete': opd2_drug_complete
    })