import pandas as pd
from django.http import Http404, HttpResponse, JsonResponse
import os
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.core.files.storage import FileSystemStorage
from django.contrib import messages
from openpyxl import load_workbook
from django.db import transaction
import json
from django.db.models import Q, Max, Min, Count
from django.utils import timezone
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from queue_operations.models import  NurseWaitingList, DoctorWaitingList, RegFee, PatientEncounter
from radio_lab.models import  RadiologyLab, ScanResult, LabResult, RadioLabInventory
from users.models import User, VerifyStaff
from IPD.models import Ward
from IPD_pharm.models import  IPDAdministeredDrugs
from IPD_pharm2.models import IPD2AdministeredDrugs
from IPD_pharm3.models import IPD3AdministeredDrugs
from OPD_pharm.models import OPDAdministeredDrugs
from OPD_pharm2.models import OPD2AdministeredDrugs
from inventory.models import PharmacyTariff
from Billings.models import Invoice
from patients.models import PatientCategory, PatientPlan
from .models import UserActivityLog, UserSession, OtherService2
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


# ---------------------- Tariff planning: Registration fee --------------------------


@login_required
def plan_page(request):
    plans = RegFee.objects.all().order_by('-id')
    return render(request, 'myAdmins/tariffs/registration_fee.html', {'plans': plans,'page':'create-plan'})


def create_plan_ajax(request):
    if request.method == 'POST':
        plan_name = request.POST.get('plan_name', '').strip()
        price = request.POST.get('price', 0)  
        
        if not plan_name:
            return JsonResponse({'status': 'error', 'message': 'plan name required'}, status=400)
        
        # Validate price
        try:
            price = int(price)
            if price < 0:
                return JsonResponse({'status': 'error', 'message': 'Price cannot be negative'}, status=400)
        except (ValueError, TypeError):
            return JsonResponse({'status': 'error', 'message': 'Invalid price format'}, status=400)
        
        # Check if plan already exists (case-insensitive)
        if RegFee.objects.filter(plan_name__iexact=plan_name).exists():
            existing = RegFee.objects.filter(plan_name__iexact=plan_name).first()
            return JsonResponse({
                'status': 'error', 
                'message': f'plan already exists as "{existing.plan_name}"'
            }, status=400)
        
        # Create new plan with price
        RegFee.objects.create(
            plan_name=plan_name,
            price=price
        )
        return JsonResponse({'status': 'success'})


def update_plan_ajax(request, id):
    plan = get_object_or_404(RegFee, id=id)
    
    # Get data from POST
    plan_name = request.POST.get('plan_name', '').strip()
    price = request.POST.get('price', plan.price)  
    
    if not plan_name:
        return JsonResponse({'status': 'error', 'message': 'plan name required'}, status=400)
    
    # Validate price
    try:
        price = int(price)
        if price < 0:
            return JsonResponse({'status': 'error', 'message': 'Price cannot be negative'}, status=400)
    except (ValueError, TypeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid price format'}, status=400)
    
    # Checking if another plan with same name exists (excluding current)
    if RegFee.objects.filter(plan_name__iexact=plan_name).exclude(id=id).exists():
        existing = RegFee.objects.filter(plan_name__iexact=plan_name).exclude(id=id).first()
        return JsonResponse({
            'status': 'error', 
            'message': f'plan name already exists as "{existing.plan_name}"'
        }, status=400)
    
    # Update plan
    plan.plan_name = plan_name
    plan.price = price
    plan.save()
    
    return JsonResponse({'status': 'updated'})


def delete_plan_ajax(request, id):
    plan = get_object_or_404(RegFee, id=id)
    plan.delete()
    return JsonResponse({'status': 'deleted'})


@transaction.atomic
def upload_plan_excel_ajax(request):
    if 'excel_file' not in request.FILES:
        return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)

    wb = load_workbook(request.FILES['excel_file'], read_only=True)
    sheet = wb.active

    # 1. PRELOADING all existing plans into memory - 1 query
    existing_plans_map = {p.plan_name.lower(): p for p in RegFee.objects.all()}

    to_create = []
    to_update = []
    errors = []
    created_count = 0
    updated_count = 0

    for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not row[0]:
            continue

        plan_name = str(row[0]).strip()
        raw_price = row[1] if len(row) > 1 else 0

        if not plan_name:
            errors.append(f"Row {index}: plan name is required")
            continue

        try:
            price = int(float(raw_price or 0))
            if price < 0:
                raise ValueError
        except:
            errors.append(f"Row {index}: Invalid price '{raw_price}'")
            continue

        # checking in-memory map
        key = plan_name.lower()
        if key in existing_plans_map:
            obj = existing_plans_map[key]
            if obj.price!= price:
                obj.price = price
                to_update.append(obj)
            updated_count += 1
        else:
            # avoiding duplicate within same Excel file
            if key not in {p.plan_name.lower() for p in to_create}:
                to_create.append(RegFee(plan_name=plan_name, price=price))
                existing_plans_map[key] = to_create[-1] # prevent duplicate in same file
                created_count += 1
            else:
                errors.append(f"Row {index}: Duplicate '{plan_name}' in file")

    # 2. BULK operations - 2 queries
    if to_create:
        RegFee.objects.bulk_create(to_create, ignore_conflicts=True)
    if to_update:
        RegFee.objects.bulk_update(to_update, ['price'], batch_size=500)

    return JsonResponse({
        'status': 'success',
        'message': f'Upload complete. Created: {created_count}, Updated: {len(to_update)}',
        'errors': errors[:10]
    })


def get_plan_details(request, id):
    plan = get_object_or_404(RegFee, id=id)
    return JsonResponse({
        'id': plan.id,
        'plan_name': plan.plan_name,
        'price': plan.price
    })


# ------------ Tariff planning: Laboratory fee ----------------------

@login_required(login_url='login')
@transaction.atomic
def lab_inventory(request):
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']
        fs = FileSystemStorage()
        filename = fs.save(excel_file.name, excel_file)
        file_path = fs.path(filename)

        try:
            df = pd.read_excel(file_path)
            df.columns = df.columns.str.strip().str.lower()

            plan_code_map = {}
            for p in PatientPlan.objects.all():
                if hasattr(p, 'code') and p.code:
                    plan_code_map[str(p.code).strip().lower()] = p
                plan_code_map[str(p.plan).strip().lower()] = p

            existing_map = {
                (obj.item_id.lower(), obj.plan_id): obj
                for obj in RadioLabInventory.objects.filter(type='L')
                if obj.item_id and obj.plan_id
            }
            seen_in_file = set()
            to_create = []
            to_update = []
            errors = []

            for index, row in df.iterrows():
                try:
                    item_id = str(row.get('item_id','')).strip()
                    item = str(row.get('item','')).strip()
                    plan_raw = str(row.get('plan_code', row.get('plan',''))).strip()
                    rate_raw = row.get('rate')

                    if not all([item_id, item, plan_raw, pd.notna(rate_raw)]):
                        errors.append(f"Row {index+2}: Missing item/item_id/rate/plan_code")
                        continue

                    try:
                        rate = Decimal(str(rate_raw))
                        if rate < 0: raise ValueError
                    except:
                        errors.append(f"Row {index+2}: Invalid rate {rate_raw}")
                        continue

                    plan_obj = plan_code_map.get(plan_raw.lower())
                    if not plan_obj:
                        errors.append(f"Row {index+2}: Plan '{plan_raw}' not found")
                        continue

                    key = (item_id.lower(), plan_obj.id)
                    if key in seen_in_file:
                        errors.append(f"Row {index+2}: Duplicate {item_id} for plan {plan_raw}")
                        continue
                    seen_in_file.add(key)

                    if key in existing_map:
                        obj = existing_map[key]
                        obj.item = item
                        obj.rate = rate
                        obj.staff = request.user
                        to_update.append(obj)
                    else:
                        to_create.append(RadioLabInventory(
                            item=item, item_id=item_id, rate=rate,
                            type='L', plan=plan_obj, staff=request.user
                        ))
                except Exception as e:
                    errors.append(f"Row {index+2}: {e}")

            if to_create:
                RadioLabInventory.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)
            if to_update:
                to_update = [o for o in to_update if o.pk]
                if to_update:
                    RadioLabInventory.objects.bulk_update(to_update, ['item', 'rate', 'staff'], batch_size=500)

            fs.delete(file_path)
            messages.success(request, f"Import complete: {len(to_create)} created, {len(to_update)} updated.")
            for err in errors[:10]:
                messages.warning(request, err)

        except Exception as e:
            if fs.exists(filename):
                fs.delete(filename)
            messages.error(request, f"Error processing file: {e}")

        return redirect('lab_inventory')

    
    # Force Single as default if no plan in URL
    if request.method == 'GET' and not request.GET.get('plan'):
        default_id = PatientPlan.objects.filter(plan__iexact='Single').first()
        if default_id:
            return redirect(f"{request.path}?plan={default_id.id}")

    uploaded_plan_ids = RadioLabInventory.objects.filter(type='L').exclude(plan__isnull=True).values_list('plan_id', flat=True).distinct()
    tariff_plans = PatientPlan.objects.filter(id__in=uploaded_plan_ids).order_by('plan')
    if not tariff_plans.exists():
        tariff_plans = PatientPlan.objects.all().order_by('plan')

    selected_plan_id = request.GET.get('plan')
    default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()

    if selected_plan_id:
        try:
            selected_plan = PatientPlan.objects.get(id=selected_plan_id)
        except:
            selected_plan = default_plan
    else:
        selected_plan = default_plan

    if selected_plan:
        lab_records = RadioLabInventory.objects.filter(type='L', plan=selected_plan).select_related('plan').order_by('item')
    else:
        lab_records = RadioLabInventory.objects.filter(type='L').select_related('plan').order_by('item')

    context = {
        'counts': lab_records.count(),
        'lab_records': lab_records,
        'tariff_plans': tariff_plans,
        'selected_plan': selected_plan,
        'default_plan': default_plan,
        'page': 'upload-test',
    }
    return render(request, 'myAdmins/tariffs/lab_inventory.html', context)


@login_required(login_url='login')
def delete_lab_test(request):
    from radio_lab.models import RadioLabInventory 
    
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Not POST'}, status=400)
    
    test_id = request.POST.get('id')
    if not test_id:
        return JsonResponse({'success': False, 'message': 'ID missing'})

    try:
        deleted, _ = RadioLabInventory.objects.filter(id=test_id).delete()
        if deleted:
            return JsonResponse({'success': True, 'message': 'Deleted successfully'})
        else:
            return JsonResponse({'success': False, 'message': 'Test not found - already deleted?'})
    except Exception as e:
        import traceback
        traceback.print_exc() 
        return JsonResponse({'success': False, 'message': str(e)})
    

@login_required(login_url='login')
@require_POST
def update_lab_test(request):
    try:
        test_id = request.POST.get('id')
        item = request.POST.get('item')
        item_id = request.POST.get('item_id')
        rate = request.POST.get('rate')

        test = get_object_or_404(RadioLabInventory, id=test_id)
        test.item = item.strip()
        test.item_id = item_id.strip()
        test.rate = Decimal(rate)
        test.save()

        return JsonResponse({'success': True, 'message': 'Test updated successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required(login_url='login')
def download_import_test_template(request):
    """Serve template Excel file"""
    template_path = os.path.join(settings.BASE_DIR, 'static', 'files', 'lab_test_import_template.xlsx')
    if os.path.exists(template_path):
        with open(template_path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type="application/vnd.ms-excel")
            response['Content-Disposition'] = 'attachment; filename=labTest_import_template.xlsx'
            return response
    raise Http404


@login_required(login_url='login')
@csrf_exempt
def save_lab_inventory(request):
    if request.method!= "POST":
        return JsonResponse({"success": False, "error": "Invalid request method."}, status=405)

    try:
        data = json.loads(request.body)
        items = data.get("items", [])
        if not items:
            return JsonResponse({"success": False, "error": "At least one lab test is required."}, status=400)

        # Preload plan map once
        plan_code_map = {}
        for p in PatientPlan.objects.all():
            if hasattr(p, 'code') and p.code:
                plan_code_map[str(p.code).strip().lower()] = p
            plan_code_map[str(p.plan).strip().lower()] = p

        to_create = []

        with transaction.atomic():
            for item in items:
                item_name = str(item.get("item", "")).strip()
                item_id = str(item.get("item_id", "")).strip() or None
                rate_raw = item.get("rate")
                plan_raw = str(item.get("plan_code", item.get("plan", ""))).strip()

                if not item_name or not rate_raw or not plan_raw:
                    return JsonResponse({"success": False, "error": f"Each test needs item, rate, and plan_code. Missing in: {item_name}"}, status=400)

                try:
                    rate = Decimal(str(rate_raw))
                    if rate <= 0:
                        raise ValueError
                except:
                    return JsonResponse({"success": False, "error": f"Invalid rate for {item_name}"}, status=400)

                plan_obj = plan_code_map.get(plan_raw.lower())
                if not plan_obj:
                    return JsonResponse({"success": False, "error": f"Plan '{plan_raw}' not found."}, status=400)

                # check duplicate
                if RadioLabInventory.objects.filter(item_id__iexact=item_id, plan=plan_obj, type='L').exists():
                    return JsonResponse({"success": False, "error": f"{item_name} already exists for plan {plan_obj.plan}"}, status=400)

                to_create.append(RadioLabInventory(
                    item=item_name,
                    item_id=item_id,
                    rate=rate,
                    type="L",
                    plan=plan_obj,
                    staff=request.user
                ))

            RadioLabInventory.objects.bulk_create(to_create)

        return JsonResponse({"success": True, "created": len(to_create)})

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)



# ------------ Tariff planning: Radiology fee ----------------------


@login_required
@transaction.atomic
def scan_inventory(request):
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']
        fs = FileSystemStorage()
        filename = fs.save(excel_file.name, excel_file)
        file_path = fs.path(filename)

        try:
            df = pd.read_excel(file_path)
            df.columns = df.columns.str.strip().str.lower()

            plan_code_map = {}
            for p in PatientPlan.objects.all():
                if hasattr(p, 'code') and p.code:
                    plan_code_map[str(p.code).strip().lower()] = p
                plan_code_map[str(p.plan).strip().lower()] = p

            existing_map = {
                (obj.item_id.lower(), obj.plan_id): obj
                for obj in RadioLabInventory.objects.filter(type='R')
                if obj.item_id and obj.plan_id
            }
            seen_in_file = set()
            to_create = []
            to_update = []
            errors = []

            for index, row in df.iterrows():
                try:
                    item_id = str(row.get('item_id','')).strip()
                    item = str(row.get('item','')).strip()
                    plan_raw = str(row.get('plan_code', row.get('plan',''))).strip()
                    rate_raw = row.get('rate')

                    if not all([item_id, item, plan_raw, pd.notna(rate_raw)]):
                        errors.append(f"Row {index+2}: Missing item/item_id/rate/plan_code")
                        continue

                    try:
                        rate = Decimal(str(rate_raw))
                        if rate < 0: raise ValueError
                    except:
                        errors.append(f"Row {index+2}: Invalid rate {rate_raw}")
                        continue

                    plan_obj = plan_code_map.get(plan_raw.lower())
                    if not plan_obj:
                        errors.append(f"Row {index+2}: Plan '{plan_raw}' not found")
                        continue

                    key = (item_id.lower(), plan_obj.id)
                    if key in seen_in_file:
                        errors.append(f"Row {index+2}: Duplicate {item_id} for plan {plan_raw}")
                        continue
                    seen_in_file.add(key)

                    if key in existing_map:
                        obj = existing_map[key]
                        obj.item = item
                        obj.rate = rate
                        obj.staff = request.user
                        to_update.append(obj)
                    else:
                        to_create.append(RadioLabInventory(
                            item=item, item_id=item_id, rate=rate,
                            type='R', plan=plan_obj, staff=request.user
                        ))
                except Exception as e:
                    errors.append(f"Row {index+2}: {e}")

            if to_create:
                RadioLabInventory.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)
            if to_update:
                to_update = [o for o in to_update if o.pk]
                if to_update:
                    RadioLabInventory.objects.bulk_update(to_update, ['item', 'rate', 'staff'], batch_size=500)

            fs.delete(file_path)
            messages.success(request, f"Import complete: {len(to_create)} created, {len(to_update)} updated.")
            for err in errors[:10]:
                messages.warning(request, err)

        except Exception as e:
            if fs.exists(filename):
                fs.delete(filename)
            messages.error(request, f"Error processing file: {e}")

        return redirect('scan_inventory')

    
    # Force Single as default if no plan in URL
    if request.method == 'GET' and not request.GET.get('plan'):
        default_id = PatientPlan.objects.filter(plan__iexact='Single').first()
        if default_id:
            return redirect(f"{request.path}?plan={default_id.id}")

    uploaded_plan_ids = RadioLabInventory.objects.filter(type='R').exclude(plan__isnull=True).values_list('plan_id', flat=True).distinct()
    tariff_plans = PatientPlan.objects.filter(id__in=uploaded_plan_ids).order_by('plan')
    if not tariff_plans.exists():
        tariff_plans = PatientPlan.objects.all().order_by('plan')

    selected_plan_id = request.GET.get('plan')
    default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()

    if selected_plan_id:
        try:
            selected_plan = PatientPlan.objects.get(id=selected_plan_id)
        except:
            selected_plan = default_plan
    else:
        selected_plan = default_plan

    if selected_plan:
        scan_records = RadioLabInventory.objects.filter(type='R', plan=selected_plan).select_related('plan').order_by('item')
    else:
        scan_records = RadioLabInventory.objects.filter(type='R').select_related('plan').order_by('item')

    context = {
        'counts': scan_records.count(),
        'scan_records': scan_records,
        'tariff_plans': tariff_plans,
        'selected_plan': selected_plan,
        'default_plan': default_plan,
        'page': 'upload-scan',
    }
    return render(request, 'myAdmins/tariffs/scan_inventory.html', context)


@login_required(login_url='login')
def delete_scan_test(request):
    from radio_lab.models import RadioLabInventory 
    
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Not POST'}, status=400)
    
    test_id = request.POST.get('id')
    if not test_id:
        return JsonResponse({'success': False, 'message': 'ID missing'})

    try:
        deleted, _ = RadioLabInventory.objects.filter(id=test_id).delete()
        if deleted:
            return JsonResponse({'success': True, 'message': 'Deleted successfully'})
        else:
            return JsonResponse({'success': False, 'message': 'Test not found - already deleted?'})
    except Exception as e:
        import traceback
        traceback.print_exc() 
        return JsonResponse({'success': False, 'message': str(e)})
    

@login_required(login_url='login')
@require_POST
def update_scan_test(request):
    try:
        test_id = request.POST.get('id')
        item = request.POST.get('item')
        item_id = request.POST.get('item_id')
        rate = request.POST.get('rate')

        test = get_object_or_404(RadioLabInventory, id=test_id)
        test.item = item.strip()
        test.item_id = item_id.strip()
        test.rate = Decimal(rate)
        test.save()

        return JsonResponse({'success': True, 'message': 'Test updated successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required(login_url='login')
@csrf_exempt
def save_scan_inventory(request):
    if request.method!= "POST":
        return JsonResponse({"success": False, "error": "Invalid request method."}, status=405)

    try:
        data = json.loads(request.body)
        items = data.get("items", [])
        if not items:
            return JsonResponse({"success": False, "error": "At least one lab test is required."}, status=400)

        # Preload plan map once
        plan_code_map = {}
        for p in PatientPlan.objects.all():
            if hasattr(p, 'code') and p.code:
                plan_code_map[str(p.code).strip().lower()] = p
            plan_code_map[str(p.plan).strip().lower()] = p

        to_create = []

        with transaction.atomic():
            for item in items:
                item_name = str(item.get("item", "")).strip()
                item_id = str(item.get("item_id", "")).strip() or None
                rate_raw = item.get("rate")
                plan_raw = str(item.get("plan_code", item.get("plan", ""))).strip()

                if not item_name or not rate_raw or not plan_raw:
                    return JsonResponse({"success": False, "error": f"Each test needs item, rate, and plan_code. Missing in: {item_name}"}, status=400)

                try:
                    rate = Decimal(str(rate_raw))
                    if rate <= 0:
                        raise ValueError
                except:
                    return JsonResponse({"success": False, "error": f"Invalid rate for {item_name}"}, status=400)

                plan_obj = plan_code_map.get(plan_raw.lower())
                if not plan_obj:
                    return JsonResponse({"success": False, "error": f"Plan '{plan_raw}' not found."}, status=400)

                # check duplicate
                if RadioLabInventory.objects.filter(item_id__iexact=item_id, plan=plan_obj, type='R').exists():
                    return JsonResponse({"success": False, "error": f"{item_name} already exists for plan {plan_obj.plan}"}, status=400)

                to_create.append(RadioLabInventory(
                    item=item_name,
                    item_id=item_id,
                    rate=rate,
                    type="R",
                    plan=plan_obj,
                    staff=request.user
                ))

            RadioLabInventory.objects.bulk_create(to_create)

        return JsonResponse({"success": True, "created": len(to_create)})

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)



# ------------ Tariff planning: Other Services fee ----------------------

@login_required
@transaction.atomic
def service_tariff(request):
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']
        fs = FileSystemStorage()
        filename = fs.save(excel_file.name, excel_file)
        file_path = fs.path(filename)

        try:
            df = pd.read_excel(file_path)
            df.columns = df.columns.str.strip().str.lower()

            plan_code_map = {}
            for p in PatientPlan.objects.all():
                if hasattr(p, 'code') and p.code:
                    plan_code_map[str(p.code).strip().lower()] = p
                plan_code_map[str(p.plan).strip().lower()] = p

            existing_map = {
                (obj.service_id.lower(), obj.plan_id): obj
                for obj in OtherService2.objects.all()
                if obj.service_id and obj.plan_id
            }
            seen_in_file = set()
            to_create = []
            to_update = []
            errors = []

            for index, row in df.iterrows():
                try:
                    service_id = str(row.get('service_id','')).strip()
                    service = str(row.get('service','')).strip()
                    plan_raw = str(row.get('plan_code', row.get('plan',''))).strip()
                    rate_raw = row.get('rate')

                    if not all([service_id, service, plan_raw, pd.notna(rate_raw)]):
                        errors.append(f"Row {index+2}: Missing service/service_id/rate/plan_code")
                        continue

                    try:
                        rate = Decimal(str(rate_raw))
                        if rate < 0: raise ValueError
                    except:
                        errors.append(f"Row {index+2}: Invalid rate {rate_raw}")
                        continue

                    plan_obj = plan_code_map.get(plan_raw.lower())
                    if not plan_obj:
                        errors.append(f"Row {index+2}: Plan '{plan_raw}' not found")
                        continue

                    key = (service_id.lower(), plan_obj.id)
                    if key in seen_in_file:
                        errors.append(f"Row {index+2}: Duplicate {service_id} for plan {plan_raw}")
                        continue
                    seen_in_file.add(key)

                    if key in existing_map:
                        obj = existing_map[key]
                        obj.service = service
                        obj.rate = rate
                        obj.staff = request.user
                        to_update.append(obj)
                    else:
                        to_create.append(OtherService2(
                            service=service, service_id=service_id, rate=rate,
                            plan=plan_obj, staff=request.user
                        ))
                except Exception as e:
                    errors.append(f"Row {index+2}: {e}")

            if to_create:
                OtherService2.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)
            if to_update:
                to_update = [o for o in to_update if o.pk]
                if to_update:
                    OtherService2.objects.bulk_update(to_update, ['service', 'rate', 'staff'], batch_size=500)

            fs.delete(file_path)
            messages.success(request, f"Import complete: {len(to_create)} created, {len(to_update)} updated.")
            for err in errors[:10]:
                messages.warning(request, err)

        except Exception as e:
            if fs.exists(filename):
                fs.delete(filename)
            messages.error(request, f"Error processing file: {e}")

        return redirect('service_tariff')

    
    # Usiing Single as default if no plan in URL
    if request.method == 'GET' and not request.GET.get('plan'):
        default_id = PatientPlan.objects.filter(plan__iexact='Single').first()
        if default_id:
            return redirect(f"{request.path}?plan={default_id.id}")

    uploaded_plan_ids = OtherService2.objects.all().exclude(plan__isnull=True).values_list('plan_id', flat=True).distinct()
    tariff_plans = PatientPlan.objects.filter(id__in=uploaded_plan_ids).order_by('plan')
    if not tariff_plans.exists():
        tariff_plans = PatientPlan.objects.all().order_by('plan')

    selected_plan_id = request.GET.get('plan')
    default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()

    if selected_plan_id:
        try:
            selected_plan = PatientPlan.objects.get(id=selected_plan_id)
        except:
            selected_plan = default_plan
    else:
        selected_plan = default_plan

    if selected_plan:
        service_records = OtherService2.objects.filter(plan=selected_plan).select_related('plan').order_by('service')
    else:
        service_records = OtherService2.objects.all().select_related('plan').order_by('service')

    context = {
        'counts': service_records.count(),
        'service_records': service_records,
        'tariff_plans': tariff_plans,
        'selected_plan': selected_plan,
        'default_plan': default_plan,
        'page': 'upload-service',
    }
    return render(request, 'myAdmins/tariffs/service_fee.html', context)


@login_required(login_url='login')
def delete_service2(request):
    from .models import OtherService2 
    
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Not POST'}, status=400)
    
    get_service_id = request.POST.get('id')
    if not get_service_id:
        return JsonResponse({'success': False, 'message': 'ID missing'})

    try:
        deleted, _ = OtherService2.objects.filter(id=get_service_id).delete()
        if deleted:
            return JsonResponse({'success': True, 'message': 'Deleted successfully'})
        else:
            return JsonResponse({'success': False, 'message': 'Service not found - already deleted?'})
    except Exception as e:
        import traceback
        traceback.print_exc() 
        return JsonResponse({'success': False, 'message': str(e)})
    

@login_required(login_url='login')
@require_POST
def update_service2(request):
    try:
        get_service_id = request.POST.get('id')
        service = request.POST.get('service')
        service_id = request.POST.get('service_id')
        rate = request.POST.get('rate')

        get_service = get_object_or_404(OtherService2, id=get_service_id)
        get_service.service = service.strip()
        get_service.service_id = service_id.strip()
        get_service.rate = Decimal(rate)
        get_service.save()

        return JsonResponse({'success': True, 'message': 'Service updated successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required(login_url='login')
@csrf_exempt
def save_service_tariff(request):
    if request.method!= "POST":
        return JsonResponse({"success": False, "error": "Invalid request method."}, status=405)

    try:
        data = json.loads(request.body)
        services = data.get("services", [])
        if not services:
            return JsonResponse({"success": False, "error": "At least one service is required."}, status=400)

        # Preload plan map once
        plan_code_map = {}
        for p in PatientPlan.objects.all():
            if hasattr(p, 'code') and p.code:
                plan_code_map[str(p.code).strip().lower()] = p
            plan_code_map[str(p.plan).strip().lower()] = p

        to_create = []

        with transaction.atomic():
            for service in services:
                service_name = str(service.get("service", "")).strip()
                service_id = str(service.get("service_id", "")).strip() or None
                rate_raw = service.get("rate")
                plan_raw = str(service.get("plan_code", service.get("plan", ""))).strip()

                if not service_name or not rate_raw or not plan_raw:
                    return JsonResponse({"success": False, "error": f"Each record needs service, rate, and plan_code. Missing in: {service_name}"}, status=400)

                try:
                    rate = Decimal(str(rate_raw))
                    if rate <= 0:
                        raise ValueError
                except:
                    return JsonResponse({"success": False, "error": f"Invalid rate for {service_name}"}, status=400)

                plan_obj = plan_code_map.get(plan_raw.lower())
                if not plan_obj:
                    return JsonResponse({"success": False, "error": f"Plan '{plan_raw}' not found."}, status=400)

                # check duplicate
                if OtherService2.objects.filter(service_id__iexact=service_id, plan=plan_obj).exists():
                    return JsonResponse({"success": False, "error": f"{service_name} already exists for plan {plan_obj.plan}"}, status=400)

                to_create.append(OtherService2(
                    service=service_name,
                    service_id=service_id,
                    rate=rate,
                    plan=plan_obj,
                    staff=request.user
                ))

            OtherService2.objects.bulk_create(to_create)

        return JsonResponse({"success": True, "created": len(to_create)})

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@login_required(login_url='login')
def download_import_service2_template(request):
    """Serve template Excel file"""
    template_path = os.path.join(settings.BASE_DIR, 'static', 'files', 'other_service_import_template.xlsx')
    if os.path.exists(template_path):
        with open(template_path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type="application/vnd.ms-excel")
            response['Content-Disposition'] = 'attachment; filename=other_service_import_template.xlsx'
            return response
    raise Http404


# product tariff(Pharmacies)

@login_required(login_url='login')
@transaction.atomic
def pharmacy_tariff_inventory(request):
    # HANDLE EXCEL UPLOAD 
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']
        fs = FileSystemStorage()
        filename = fs.save(excel_file.name, excel_file)
        file_path = fs.path(filename)

        try:
            df = pd.read_excel(file_path)
            df.columns = df.columns.str.strip().str.lower()

            plan_code_map = {}
            for p in PatientPlan.objects.all():
                if hasattr(p, 'code') and p.code:
                    plan_code_map[str(p.code).strip().lower()] = p
                plan_code_map[str(p.plan).strip().lower()] = p

            existing_map = {
                (obj.product_id.lower(), obj.plan_id): obj
                for obj in PharmacyTariff.objects.all()
            }

            to_create = []
            to_update = []
            errors = []
            seen_in_file = set()

            for index, row in df.iterrows():
                try:
                    product_id = str(row.get('product_id','')).strip()
                    product_name = str(row.get('product_name','')).strip()
                    plan_raw = str(row.get('plan_code', row.get('plan',''))).strip()
                    rate_raw = row.get('rate')

                    if not all([product_id, product_name, plan_raw, pd.notna(rate_raw)]):
                        errors.append(f"Row {index+2}: Missing product_id/product_name/plan/rate")
                        continue

                    try:
                        rate = Decimal(str(rate_raw))
                        if rate < 0: raise ValueError
                    except:
                        errors.append(f"Row {index+2}: Invalid rate {rate_raw}")
                        continue

                    plan_obj = plan_code_map.get(plan_raw.lower())
                    if not plan_obj:
                        errors.append(f"Row {index+2}: Plan '{plan_raw}' not found")
                        continue

                    key = (product_id.lower(), plan_obj.id)
                    if key in seen_in_file:
                        errors.append(f"Row {index+2}: Duplicate {product_id} for {plan_raw} in file")
                        continue
                    seen_in_file.add(key)

                    if key in existing_map:
                        obj = existing_map[key]
                        obj.product_name = product_name
                        obj.rate = rate
                        obj.staff = request.user
                        to_update.append(obj)
                    else:
                        to_create.append(PharmacyTariff(
                            product_id=product_id,
                            product_name=product_name,
                            plan=plan_obj,
                            rate=rate,
                            staff=request.user
                        ))
                except Exception as e:
                    errors.append(f"Row {index+2}: {e}")

            if to_create:
                PharmacyTariff.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)
            if to_update:
                to_update = [o for o in to_update if o.pk]
                if to_update:
                    PharmacyTariff.objects.bulk_update(to_update, ['product_name','rate','staff'], batch_size=500)

            fs.delete(file_path)
            messages.success(request, f"Import complete: {len(to_create)} created, {len(to_update)} updated")
            for err in errors[:10]:
                messages.warning(request, err)

        except Exception as e:
            if fs.exists(filename):
                fs.delete(filename)
            messages.error(request, f"Error processing file: {e}")

        return redirect('pharmacy_tariff_inventory')

    # - FILTER BY PLAN ONLY  ---
    if request.method == 'GET' and not request.GET.get('plan'):
        default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()
        if default_plan:
            return redirect(f"{request.path}?plan={default_plan.id}")

    uploaded_plan_ids = PharmacyTariff.objects.exclude(plan__isnull=True).values_list('plan_id', flat=True).distinct()
    tariff_plans = PatientPlan.objects.filter(id__in=uploaded_plan_ids).order_by('plan')
    if not tariff_plans.exists():
        tariff_plans = PatientPlan.objects.all().order_by('plan')

    selected_plan_id = request.GET.get('plan')
    default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()

    if selected_plan_id:
        try:
            selected_plan = PatientPlan.objects.get(id=selected_plan_id)
        except:
            selected_plan = default_plan
    else:
        selected_plan = default_plan

    if selected_plan:
        tariffs = PharmacyTariff.objects.filter(plan=selected_plan).select_related('plan').order_by('product_name')
    else:
        tariffs = PharmacyTariff.objects.all().select_related('plan').order_by('product_name')

    plan_counts = PharmacyTariff.objects.values('plan__plan').annotate(total=Count('id')).order_by('plan__plan')

    context = {
        'counts': tariffs.count(),
        'tariffs': tariffs,
        'tariff_plans': tariff_plans,
        'selected_plan': selected_plan,
        'default_plan': default_plan,
        'plan_counts': plan_counts,
        'page': 'pharm-tariff',
    }
    return render(request, 'myAdmins/tariffs/pharmacy_tariff.html', context)


@login_required
@require_POST
def edit_pharmacy_tariff(request):
    try:
        tariff_id = request.POST.get('id')
        product_name = request.POST.get('product_name','').strip()
        product_id = request.POST.get('product_id','').strip()
        rate = request.POST.get('rate','').strip()

        if not all([tariff_id, product_name, product_id, rate]):
            return JsonResponse({'success': False, 'error': 'All fields required'})

        tariff = PharmacyTariff.objects.get(id=tariff_id)
        
        # Check duplicate product_id + plan (if product_id changed)
        if PharmacyTariff.objects.filter(product_id=product_id, plan=tariff.plan).exclude(id=tariff_id).exists():
            return JsonResponse({'success': False, 'error': f'Product ID {product_id} already exists for {tariff.plan.plan}'})

        tariff.product_name = product_name
        tariff.product_id = product_id
        tariff.rate = Decimal(rate)
        tariff.staff = request.user
        tariff.save()

        return JsonResponse({'success': True, 'message': 'Tariff updated successfully'})
    except PharmacyTariff.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Record not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def delete_pharmacy_tariff(request):
    try:
        tariff_id = request.POST.get('id')
        tariff = PharmacyTariff.objects.get(id=tariff_id)
        name = tariff.product_name
        tariff.delete()
        return JsonResponse({'success': True, 'message': f'{name} deleted'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



# Admission fees (IPD)

@login_required
def ward_page(request):
    wards = Ward.objects.all().order_by('-id')
    return render(request, 'myAdmins/tariffs/admission_fee.html', {'wards': wards,'page':'create-ward'})


def create_ward_ajax(request):
    if request.method == 'POST':
        ward_name = request.POST.get('ward_name', '').strip()
        price = request.POST.get('price', 0)  
        
        if not ward_name:
            return JsonResponse({'status': 'error', 'message': 'ward name required'}, status=400)
        
        # Validate price
        try:
            price = int(price)
            if price < 0:
                return JsonResponse({'status': 'error', 'message': 'Price cannot be negative'}, status=400)
        except (ValueError, TypeError):
            return JsonResponse({'status': 'error', 'message': 'Invalid price format'}, status=400)
        
        # Check if ward already exists (case-insensitive)
        if Ward.objects.filter(ward_name__iexact=ward_name).exists():
            existing = Ward.objects.filter(ward_name__iexact=ward_name).first()
            return JsonResponse({
                'status': 'error', 
                'message': f'ward already exists as "{existing.ward_name}"'
            }, status=400)
        
        # Create new ward with price
        Ward.objects.create(
            ward_name=ward_name,
            price=price
        )
        return JsonResponse({'status': 'success'})


def update_ward_ajax(request, id):
    ward = get_object_or_404(Ward, id=id)
    
    # Get data from POST
    ward_name = request.POST.get('ward_name', '').strip()
    price = request.POST.get('price', ward.price)  
    
    if not ward_name:
        return JsonResponse({'status': 'error', 'message': 'ward name required'}, status=400)
    
    # Validate price
    try:
        price = int(price)
        if price < 0:
            return JsonResponse({'status': 'error', 'message': 'Price cannot be negative'}, status=400)
    except (ValueError, TypeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid price format'}, status=400)
    
    # Checking if another ward with same name exists (excluding current)
    if Ward.objects.filter(ward_name__iexact=ward_name).exclude(id=id).exists():
        existing = Ward.objects.filter(ward_name__iexact=ward_name).exclude(id=id).first()
        return JsonResponse({
            'status': 'error', 
            'message': f'ward name already exists as "{existing.ward_name}"'
        }, status=400)
    
    # Update ward
    ward.ward_name = ward_name
    ward.price = price
    ward.save()
    
    return JsonResponse({'status': 'updated'})


def delete_ward_ajax(request, id):
    ward = get_object_or_404(Ward, id=id)
    ward.delete()
    return JsonResponse({'status': 'deleted'})


@transaction.atomic
def upload_ward_excel_ajax(request):
    if 'excel_file' not in request.FILES:
        return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)

    wb = load_workbook(request.FILES['excel_file'], read_only=True)
    sheet = wb.active

    # PRELOADING all existing wards into memory - 1 query
    existing_wards_map = {p.ward_name.lower(): p for p in Ward.objects.all()}

    to_create = []
    to_update = []
    errors = []
    created_count = 0
    updated_count = 0

    for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not row[0]:
            continue

        ward_name = str(row[0]).strip()
        raw_price = row[1] if len(row) > 1 else 0

        if not ward_name:
            errors.append(f"Row {index}: ward name is required")
            continue

        try:
            price = int(float(raw_price or 0))
            if price < 0:
                raise ValueError
        except:
            errors.append(f"Row {index}: Invalid price '{raw_price}'")
            continue

        # checking in-memory map
        key = ward_name.lower()
        if key in existing_wards_map:
            obj = existing_wards_map[key]
            if obj.price!= price:
                obj.price = price
                to_update.append(obj)
            updated_count += 1
        else:
            # avoiding duplicate within same Excel file
            if key not in {p.ward_name.lower() for p in to_create}:
                to_create.append(Ward(ward_name=ward_name, price=price))
                existing_wards_map[key] = to_create[-1] # prevent duplicate in same file
                created_count += 1
            else:
                errors.append(f"Row {index}: Duplicate '{ward_name}' in file")

    # BULK operations - 2 queries
    if to_create:
        Ward.objects.bulk_create(to_create, ignore_conflicts=True)
    if to_update:
        Ward.objects.bulk_update(to_update, ['price'], batch_size=500)

    return JsonResponse({
        'status': 'success',
        'message': f'Upload complete. Created: {created_count}, Updated: {len(to_update)}',
        'errors': errors[:10]
    })


def get_ward_details(request, id):
    ward = get_object_or_404(Ward, id=id)
    return JsonResponse({
        'id': ward.id,
        'ward_name': ward.ward_name,
        'price': ward.price
    })