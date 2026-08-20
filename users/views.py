from django.shortcuts import render, redirect, get_object_or_404
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView, PasswordResetDoneView
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.urls import reverse_lazy
from datetime import datetime, timedelta, date
from django.utils import timezone
import re
from django.db.models.functions import ExtractMonth, ExtractDay
from .forms import MyUserCreationForm, PasswordChangingForm, UserUpdateForm, AdminUpdateForm, UserPinCreationForm, UserPinUpdateForm, PasswordResetForm
from patients.forms import PatientProfileForm
from patients.models import PatientProfile,PatientAppointment
from .models import User, Category
from queue_operations.models import VisitPurpose,RegFee
from IPD.models import AdmissionTable
from myAdmins.utils import log_user_activity
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from django.contrib.auth import user_logged_in, user_logged_out
today = date.today()

# @authenticated_user
@transaction.atomic()
def create_user(request):
    page = 'register'
    form = MyUserCreationForm()
    if request.method == 'POST':
         # Manually adjust the purpose field queryset before validation
        if 'department' in request.POST and 'purpose' in request.POST:
            try:
                department_id = int(request.POST.get('department'))
                purpose_id = int(request.POST.get('purpose'))
                
                category = Category.objects.get(id=department_id)
                if category.department.lower() == 'clinical':
                    # Allow the selected purpose
                    form.fields['purpose'].queryset = VisitPurpose.objects.filter(id=purpose_id)
            except (ValueError, Category.DoesNotExist):
                pass
            
        form = MyUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.active = '1'
            user.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            
            # Redirect based on department
            department_name = user.department.department
            redirect_map = {
                'Front Desk': 'admin-dashboard',
                'Nursing': 'waiting_list',
                'Clinical': 'doctor_waiting_list',
                'Inventory': 'add_product',
                'IPD Pharmacy 1': 'view_ipd_product',
                'IPD Pharmacy 2': 'view_ipd2_product',
                'IPD Pharmacy 3': 'view_ipd3_product',
                'OPD Pharmacy 1': 'view_opd_product',
                'OPD Pharmacy 2': 'view_opd2_product',
                'Laboratory': 'lab_waiting',
                'Radiology': 'scan_waiting',
                'Billings': 'get_transactions',
                'Admin': 'activity_dashboard',
                'CMD': 'doctor_waiting_list',
                'Reporting': 'ambulatory_report',
            }
            
            redirect_url = redirect_map.get(department_name)
            if redirect_url:
                messages.success(request, f'Welcome {user.fullname}, Your Account was successfully created!')
                return redirect(redirect_url)
            else:
                messages.warning(request, f'Welcome {user.fullname}, but no redirect configured for your department.')
                return redirect('admin-dashboard')  
            
    context = {
        'form':form,
        'page':page
    }
    return render(request, 'users/create_user.html', context)


def check_department(request, department_id):
    try:
        category = Category.objects.get(id=department_id)
        is_clinical = category.department.lower() == 'clinical'
        is_cmd = category.department.lower() == 'cmd'
        
        data = {
            'is_clinical': is_clinical,
            'is_cmd': is_cmd,
            'purposes': []
        }
        
        if is_clinical or is_cmd:
            # Get all visit purposes
            visit_purposes = VisitPurpose.objects.order_by('specialist_id')
            
            unique_purposes = []
            specialist_ids_seen = set()
            exclude_keywords = ['select purpose of visit', 'result review', 'out patient']
            
            for purpose_obj in visit_purposes:
                # Skip if purpose is in exclude list (case-insensitive)
                purpose_lower = purpose_obj.purpose.lower() if purpose_obj.purpose else ""
                
                should_exclude = any(keyword in purpose_lower for keyword in exclude_keywords)
                if should_exclude:
                    continue
                
                # Only include unique specialist_id purposes
                if purpose_obj.specialist_id not in specialist_ids_seen and purpose_obj.specialist_id != 0:
                    clean_purpose = re.sub(r'\s*\([^)]*\)', '', purpose_obj.purpose).strip()
                    
                    # Capitalize the cleaned purpose
                    clean_purpose = clean_purpose.title()
                    
                    data['purposes'].append({
                        'id': purpose_obj.id,
                        'purpose': clean_purpose,
                        'specialist_id': purpose_obj.specialist_id
                    })
                    specialist_ids_seen.add(purpose_obj.specialist_id)
            
        return JsonResponse(data)
        
    except Category.DoesNotExist:
        return JsonResponse({'is_clinical': False, 'purposes': []})


def user_login(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)  # Log in the user first
            if user.active == '1':
                if user.department:
                     # Redirect based on department
                    department_name = user.department.department
                    redirect_map = {
                        'Front Desk': 'admin-dashboard',
                        'Nursing': 'waiting_list',
                        'Clinical': 'doctor_waiting_list',
                        'Inventory': 'add_product',
                        'IPD Pharmacy 1': 'ipd_pharm1_queue',
                        'IPD Pharmacy 2': 'ipd2pharm_queue',
                        'IPD Pharmacy 3': 'ipd3pharm_queue',
                        'OPD Pharmacy 1': 'opdpharm_queue',
                        'OPD Pharmacy 2': 'opd2pharm_queue',
                        'Laboratory': 'lab_waiting',
                        'Radiology': 'scan_waiting',
                        'Billings': 'get_transactions',
                        'Admin': 'activity_dashboard',
                        'CMD': 'doctor_waiting_list',
                        'Reporting': 'ambulatory_report',
                    }
                    
                    redirect_url = redirect_map.get(department_name)
                    if redirect_url:
                        messages.success(request, f'Welcome {user.fullname}, Your Login was Successful!')
                        return redirect(redirect_url)
            else:
                messages.error(request, 'This account has been Deactivated, pls see the admin')
                return redirect('login')
        else:
            messages.error(request,'Invalid login credentials')
            return redirect('login')
    return render(request, 'users/login.html')


@login_required(login_url='login')
@transaction.atomic()
def my_admin(request):
    page = 'dashbourd'
    form = PatientProfileForm()
    # all__patients = PatientProfile.objects.all().count
    hmo__patients = PatientProfile.objects.filter(category__category__iexact='HMO').select_related('category').count()
    anc__patients = PatientProfile.objects.filter(category__category__iexact='ANC').select_related('category').count()
    retainership__patients = PatientProfile.objects.filter(category__category__iexact='Retainership').select_related('category').count()
    private__patients = PatientProfile.objects.filter(category__category__iexact='Private').select_related('category').count()
    inactive__patients = PatientProfile.objects.filter(active=0).count()
    active__patients = PatientProfile.objects.filter(active=1).count()
    inpatients__patients = AdmissionTable.objects.filter(nurse_admit_status=1, doctor_discharge_status=0).count()
    today = timezone.localdate()
    appointments = PatientAppointment.objects.filter(
        arrival_date=today,
    )
    appointment_count = appointments.count()
    birthday_patients = PatientProfile.objects.annotate(
    birth_month=ExtractMonth('dob'),birth_day=ExtractDay('dob')
    ).filter(
    birth_month=today.month, birth_day=today.day, active=1
    ).count()

    if request.method == 'POST':

            form = PatientProfileForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request,'Patient Successfully Registered!')
                return redirect('admin-dashboard')
            else:
                messages.error(request,'Error Occurred somewhere!')
                return redirect('admin-dashboard')
        
    return render(request, 'users/dashbourd.html',
    {
        'form':form,
        'hmo':hmo__patients,
        'anc':anc__patients,
        'private':private__patients,
        'retainership':retainership__patients,
        # 'all_patients':all__patients,
        'deactivated':inactive__patients,
        'active':active__patients,
        'inpatients':inpatients__patients,
        'appointments':appointments,
        'appointment_counts':appointment_count,
        'birthday_counts':birthday_patients,
        'page':page,

    })

@login_required(login_url='login')
def waiting_list(request):
    return render(request, 'users/waiting_list.html')

@login_required(login_url='login')
def user_logout(request):
    logout(request)
    return redirect('login')


@login_required(login_url='login')
@transaction.atomic()
def user_profile(request, key):
    users = request.user
    user = User.objects.get(id=key)
    form = UserUpdateForm(instance=user)
    create_pin_form = UserPinCreationForm(instance=user)
    
    if request.method == 'POST':
        # Profile picture upload
        if 'upload' in request.POST:
            if user.pin == int(request.POST.get('pin_code')):
                avatars = request.FILES['avatar']
                if avatars.size > 200000:
                    messages.error(request, 'File Size is too big, maximum of 200 (kb) is required')
                    return redirect('user-profile', key=user.id)
                else:
                    form = UserUpdateForm(request.POST, request.FILES, instance=user)
                    if form.is_valid():
                        old_avatar = user.avatar.name if user.avatar else None
                        form.save()
                        
                        # Log profile picture update
                        log_user_activity(
                            user,
                            'profile_update',
                            request,
                            "User updated their profile picture",
                            {
                                'action': 'profile_picture_update',
                                'old_avatar': old_avatar,
                                'new_avatar': str(user.avatar) if user.avatar else None
                            }
                        )
                        
                        messages.success(request, f'Picture Uploaded Successfully')
                        return redirect('user-profile', key=user.id)
                    else:
                        messages.error(request, 'Error Occured, file format not supported')
                        return redirect('user-profile', key=user.id)
            else:
                # Log failed PIN attempt
                log_user_activity(
                    user,
                    'failed_login',
                    request,
                    "Failed PIN verification for profile picture update",
                    {'action': 'profile_picture_update'}
                )
                messages.error(request, 'Incorrect Pin Code')
                return redirect('user-profile', key=user.id)
        
        # Create PIN code
        elif 'create_pin' in request.POST:
            create_pin_form = UserPinCreationForm(request.POST, instance=user)
            confirm = request.POST.get('confirm')
            pin = request.POST.get('pin')
            
            if pin and pin != confirm:
                messages.error(request, 'Both Pin(s) are not the same')
                return redirect('user-profile', key=user.id)
            
            if create_pin_form.is_valid():
                create_pin_form.save()
                
                # Log PIN creation
                log_user_activity(
                    user,
                    'pin_created',  
                    request,
                    "User created a new PIN for their account",
                    {
                        'action': 'create_pin',
                        'timestamp': timezone.now().isoformat()
                    }
                )
                
                messages.success(request, 'Pin Created Successfully')
                return redirect('user-profile', key=user.id)
            else:
                messages.error(request, 'Error Occured, Pls try again')
                return redirect('user-profile', key=user.id)
        
        # Change PIN
        elif 'change_pin' in request.POST:
            old_pin = int(request.POST.get('old_pin'))
            new_pin = int(request.POST.get('new_pin'))
            confirm = int(request.POST.get('confirm'))
            
            if user.pin != old_pin:
                # Log failed PIN change attempt
                log_user_activity(
                    user,
                    'failed_login',
                    request,
                    "Failed PIN change attempt - incorrect old PIN",
                    {'action': 'change_pin'}
                )
                messages.error(request, 'You entered Incorrect Old Pin')
                return redirect('user-profile', key=user.id)
            elif new_pin and new_pin != confirm:
                messages.error(request, 'Both Pin(s) are not the same')
                return redirect('user-profile', key=user.id)
            else:
                user.pin = new_pin
                user.save()
                
                # Log PIN change
                log_user_activity(
                    user,
                    'pin_change',  
                    request,
                    "User changed their PIN",
                    {
                        'action': 'change_pin',
                        'timestamp': timezone.now().isoformat()
                    }
                )
                
                messages.success(request, 'Pin Changed Successfully')
                return redirect('user-profile', key=user.id)
    
    context = {
        'users': users,
        'user': user,
        'form': form,
        'create_pin_form': create_pin_form,
    }
    return render(request, 'users/user-profile.html', context)

@login_required(login_url='login')
@transaction.atomic()
def get_reg_users(request, key):
    user = User.objects.get(username=key)    
    context = {
        'user': user,
    }
    return render(request, 'users/user-profile.html', context)

@login_required(login_url='login')
@transaction.atomic()
def update_profile(request, key):
    user = get_object_or_404(User, id=key)
    form = AdminUpdateForm(instance=user)
    
    if request.method == 'POST':
        form = AdminUpdateForm(request.POST, request.FILES, instance=user)
        if user.pin == int(request.POST.get('pin_code')):
            if form.is_valid():
                # Get the changes before saving
                old_data = {}
                new_data = {}
                for field in form.changed_data:
                    old_data[field] = getattr(user, field)
                    new_data[field] = form.cleaned_data[field]
                
                form.save()
                
                # Log the profile update activity
                log_user_activity(
                    user,
                    'profile_update',
                    request,
                    f"Admin {request.user.get_full_name() or request.user.username} updated profile",
                    {
                        'action': 'profile_update',
                        'action_by': request.user.id,
                        'action_by_name': request.user.get_full_name() or request.user.username,
                        'updated_fields': form.changed_data,
                        'old_values': str(old_data),
                        'new_values': str(new_data)
                    }
                )
                
                # Also log for the admin who made the change
                if request.user.id != user.id:
                    log_user_activity(
                        request.user,
                        'account_accessed',
                        request,
                        f"Admin updated profile for user: {user.get_full_name() or user.username}",
                        {
                            'target_user': user.id,
                            'target_user_name': user.get_full_name() or user.username,
                            'action': 'profile_update',
                            'updated_fields': form.changed_data
                        }
                    )
                
                messages.success(request, 'Profile Successfully Updated!')
                return redirect('user-profile', key=user.id)
            else:
                messages.error(request, 'Error Occurred! Pls, make sure no field is left blank and try again')
                return redirect('profile-update', key=user.id)
        else:
            # Log failed PIN attempt
            log_user_activity(
                request.user,
                'failed_login',
                request,
                f"Failed PIN verification for profile update on user: {user.get_full_name() or user.username}",
                {
                    'action': 'profile_update',
                    'target_user': user.id
                }
            )
            messages.error(request, 'Incorrect Pin Code')
            return redirect('profile-update', key=user.id)
    
    return render(request, 'users/update-admin.html', {'form': form})


# change password
class MyPasswordChangeView(PasswordChangeView):
    form_class = PasswordChangingForm
    template_name = "users/password_change.html"
    success_url = reverse_lazy('password-change-done')
    
    def form_valid(self, form):
        # Log the password change activity
        response = super().form_valid(form)
        
        # Log activity for password change
        log_user_activity(
            self.request.user,
            'password_change',
            self.request,
            "User changed their password",
            {
                'action': 'password_change',
                'timestamp': timezone.now().isoformat()
            }
        )
        
        return response

class MyPasswordResetDoneView(PasswordResetDoneView):
    template_name = "users/password_change_success.html"

@login_required(login_url='login')
def passwordSuccess(request):
    return render(request, 'users/password_change_success.html')


# for password reset
def custom_password_reset(request):
    if request.method == "POST":
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            new_password = form.cleaned_data['new_password']
            confirm_password = form.cleaned_data['confirm_password']
            date_of_birth = form.cleaned_data['date_of_birth']
            authenticates = User.objects.filter(username=username, dob=date_of_birth)
            
            if not authenticates.exists():
                messages.error(request, 'This Username does not match with the Date of Birth')
            elif new_password and confirm_password and new_password != confirm_password:
                messages.error(request, 'Both Passwords are not the same')
            else:
                try:
                    user = User.objects.get(username=username)
                    user.set_password(new_password)
                    user.save()
                    
                    # Log the password reset activity
                    log_user_activity(
                        user,
                        'password_reset',
                        request,
                        f"User reset their password using password reset form",
                        {
                            'action': 'password_reset',
                            'reset_method': 'custom_password_reset_form',
                            'timestamp': timezone.now().isoformat()
                        }
                    )
                    
                    messages.success(request, "Password reset successfully.")
                    return redirect("login")
                except User.DoesNotExist:
                    messages.error(request, "User not found.")
    else:
        form = PasswordResetForm()
    return render(request, "users/custom_password_reset.html", {"form": form})



# Signal for user login
@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    """Log when user logs in"""
    try:
        log_user_activity(
            user, 
            'login', 
            request, 
            f"User logged in successfully from IP: {request.META.get('REMOTE_ADDR')}",
            {
                'session_key': request.session.session_key,
                'login_method': 'credentials'
            }
        )
        print(f"Login logged for user: {user.username}")  # Debug message
    except Exception as e:
        print(f"Error logging login: {e}")

# Signal for user logout
@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    """Log when user logs out"""
    try:
        if user:
            log_user_activity(
                user, 
                'logout', 
                request, 
                "User logged out",
                {
                    'session_key': request.session.session_key
                }
            )
            print(f"Logout logged for user: {user.username}")  # Debug message
    except Exception as e:
        print(f"Error logging logout: {e}")

#  Log failed login attempts
@receiver(user_login_failed)
def log_failed_login(sender, credentials, request, **kwargs):
    """Log failed login attempts"""
    try:
        # Try to get username from credentials
        username = credentials.get('username') or credentials.get('email')
        if username:
   
            print(f"Failed login attempt for username: {username} from IP: {request.META.get('REMOTE_ADDR')}")
    except Exception as e:
        print(f"Error logging failed login: {e}")
