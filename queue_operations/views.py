import pandas as pd
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.apps import apps
from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import re
import traceback
from django.contrib.auth.decorators import login_required
from inventory.decorators import department_required
from .forms import BackgroundHealthForm,EditPatientBackgroundHealthForm,DoctorWaitingListForm,DoctorWaitingListModifyForm, DiagnosisForm, ICD11SearchForm
from ANC.forms import PatientAppointmentForm
from patients.forms import PatientAlergyUpdateForm
from patients.models import PatientProfile, PatientAppointment, PatientPlan, PatientCategory
from .models import VisitPurpose, NurseWaitingList,PatientBackgroundHealth, DoctorWaitingList,Transcript,PatientFollowUp,PatientReferral,PatientOtherDetails, OtherService, WrittenPrescriptions, ICD11Code
from IPD_pharm.models import IPDAdministeredDrugs
from IPD.models import AdmissionTable
from Billings.models import TransactionUpdate
from radio_lab.models import RadioLabInventory, RadiologyLab, ScanResult, LabResult
from ANC.models import AntenatalVisit
from inventory.models import Product, PharmacyTariff
from myAdmins.models import OtherService2, OtherServiceConsumed
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
import json
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.conf import settings
import os
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import time 
from io import BytesIO
from django.core.mail import EmailMessage
from django.conf import settings
from reportlab.lib.pagesizes import A4

today = timezone.now().date()

# Beginning of Nurse Views 

def fetch_waiting_list(request):
    queue = NurseWaitingList.objects.filter(
        completed__in = [0, 3],
        waiting_status=0,
        created_date__gte=timezone.now() - timedelta(hours=24)
    )
    data = []
 
    for record in queue:
        patient = record.patient
        data.append({
            'patient_id': patient.id if patient else '',
            'name': f"{patient.surname} {patient.other_name} {patient.first_name}" if patient else "N/A",
            'hospital_number': f"{patient.hospital_number} " if patient else "N/A",
            'category': f"{patient.category}" if patient else "N/A",
            'plan': f"{patient.plan} " if patient else "N/A",
            'attendant': f"{record.attendant.fullname} " if record.attendant else "N/A",
            'created_date': record.created_date.strftime('%Y-%m-%d %H:%M'),
            'critical_request': getattr(record, 'critical_request', 0),
        })

    return JsonResponse({
        'data': data,
        'count': len(data)
    })


@login_required
@department_required('Nursing', 'Admin', 'CMD')
def load_nurse_queue(request):
    return render(request, 'queue_operations/waiting_list.html',{'page':'nurse-queue-load'})

def nurse_waiting_count(request):
    count = NurseWaitingList.objects.filter(
        completed__in = [0, 3],
        waiting_status=0,
        created_date__gte=timezone.now() - timedelta(hours=24)
    ).count()
    return JsonResponse({'count': count})

@login_required
@department_required('Nursing', 'Admin', 'CMD')
def nurse_done_list(request):
    my_patients = NurseWaitingList.objects.filter(waiting_status = 1, completed_by=request.user.fullname, created_date__gte=timezone.now() - timedelta(hours=24))
    # all_patients = NurseWaitingList.objects.filter(waiting_status = 1, created_date__gte=timezone.now() - timedelta(hours=24))

    context = {
        # 'all_patients':all_patients,
        # 'all_counts':all_patients.count(),
        'my_patients':my_patients,
        'counts':my_patients.count(),
        'title':'All Vital Signs Completed By you (Today)', 
        'page':'nurse-done-list'
    }
    return render(request, 'queue_operations/done_list.html', context)

@login_required
def attendants_today(request):
    today = timezone.now().date()
    now = timezone.localtime(timezone.now())
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    patients = NurseWaitingList.objects.filter(created_date__range=(start_of_day, end_of_day)).select_related('category')

    context = {
        'patients':patients,
        'counts':patients.count(),
        'title':'Attendance Sheet for Today',
        'page':'attendants-today'
    }
    return render(request, 'queue_operations/attendance.html', context)


@login_required
@department_required('Front Desk', 'Admin', 'CMD')
def attendants_all(request):
    from datetime import datetime, time
    import datetime as dt
    from django.utils import timezone
    from django.db.models import Q

    base_qs = NurseWaitingList.objects.all().select_related('category', 'patient', 'patient__plan')
    last_24_hours = timezone.now() - timedelta(hours=24)
    
    filter_category = request.GET.get('category', '').strip()
    filter_date1 = request.GET.get('date1', '').strip()
    filter_date2 = request.GET.get('date2', '').strip()
    all_categories = PatientCategory.objects.all().order_by('category')

    filters = Q()
    if filter_category:
        filters &= Q(category_id=filter_category)

    if filter_date1 and filter_date2:
        try:
            d1 = dt.datetime.strptime(filter_date1, '%Y-%m-%d').date()
            d2 = dt.datetime.strptime(filter_date2, '%Y-%m-%d').date()
            start = timezone.make_aware(datetime.combine(d1, time.min))
            end = timezone.make_aware(datetime.combine(d2, time.max))
            filters &= Q(created_date__range=(start, end))
        except ValueError:
            pass
    elif filter_date1:
        try:
            d1 = dt.datetime.strptime(filter_date1, '%Y-%m-%d').date()
            start = timezone.make_aware(datetime.combine(d1, time.min))
            end = timezone.make_aware(datetime.combine(d1, time.max))
            filters &= Q(created_date__range=(start, end))
        except ValueError:
            pass
    elif filter_date2:
        try:
            d2 = dt.datetime.strptime(filter_date2, '%Y-%m-%d').date()
            start = timezone.make_aware(datetime.combine(d2, time.min))
            end = timezone.make_aware(datetime.combine(d2, time.max))
            filters &= Q(created_date__range=(start, end))
        except ValueError:
            pass

    if filters:
        patients = base_qs.filter(filters).order_by('-created_date')
    else:
        patients = base_qs.filter(created_date__gte=last_24_hours).order_by('-created_date')

    context = {
        'patients': patients,
        'counts': patients.count(),
        'title': 'Patients Attendance Sheet',
        'page': 'attendants-all',
        'all_categories': all_categories,
        'filter_category': filter_category,
        'filter_date1': filter_date1,
        'filter_date2': filter_date2,
    }
    return render(request, 'queue_operations/attendance.html', context)


def export_to_excel(request):
    import pandas as pd
    import datetime as dt
    from datetime import datetime, time
    from django.utils import timezone
    from django.http import HttpResponse
    from django.db.models import Q

    category_id = request.GET.get('category', '').strip()
    date1 = request.GET.get('date1', '').strip()
    date2 = request.GET.get('date2', '').strip()

    patients = NurseWaitingList.objects.all().select_related(
        'category', 'patient', 'patient__plan'
    ).order_by('-created_date')

    filters = Q()

    # 1. Category - immutable record from NurseWaitingList
    if category_id:
        try:
            filters &= Q(category_id=int(category_id))
        except ValueError:
            pass

    # 2. Date to include whole end day
    if date1 and date2:
        try:
            d1 = dt.datetime.strptime(date1, '%Y-%m-%d').date()
            d2 = dt.datetime.strptime(date2, '%Y-%m-%d').date()
            start = timezone.make_aware(datetime.combine(d1, time.min))
            end = timezone.make_aware(datetime.combine(d2, time.max))
            filters &= Q(created_date__range=(start, end))
        except ValueError:
            pass
    elif date1:
        try:
            d1 = dt.datetime.strptime(date1, '%Y-%m-%d').date()
            start = timezone.make_aware(datetime.combine(d1, time.min))
            end = timezone.make_aware(datetime.combine(d1, time.max))
            filters &= Q(created_date__range=(start, end))
        except ValueError:
            pass
    elif date2:
        try:
            d2 = dt.datetime.strptime(date2, '%Y-%m-%d').date()
            start = timezone.make_aware(datetime.combine(d2, time.min))
            end = timezone.make_aware(datetime.combine(d2, time.max))
            filters &= Q(created_date__range=(start, end))
        except ValueError:
            pass

    if filters:
        patients = patients.filter(filters)
    else:
        # No filter = default last 24 hours
        last_24_hours = timezone.now() - timedelta(hours=24)
        patients = patients.filter(created_date__gte=last_24_hours)

    data = {
        'Fullname': [f"{r.patient.surname} {r.patient.first_name} {r.patient.other_name or ''}".strip() for r in patients],
        'Hospital No': [r.patient.hospital_number for r in patients],
        'Phone No': [r.patient.phone_number for r in patients],
        'Category': [r.category.category if r.category else '' for r in patients],
        'Plan': [r.patient.plan.plan if hasattr(r.patient, 'plan') and r.patient.plan else '' for r in patients],
        'Date Taken': [timezone.localtime(r.created_date).strftime('%Y-%m-%d %H:%M:%S') for r in patients],
    }

    df = pd.DataFrame(data)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="Patients-attendance-sheet.xlsx"'

    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Patients')

    return response


@login_required
def operations_profile(request, key):
    page = 'operations-profile'
    patient = get_object_or_404(PatientProfile, id=key)
    context = {
        'patient':patient,
        'page':page,
    }
    return render(request, 'queue_operations/crumbs/operations_profile_doc.html', context)

@login_required
def operations_profile_nur(request, key):
    page = 'operations-profile-nur'
    patient = get_object_or_404(PatientProfile, id=key)
    context = {
        'page':page,
        'patient':patient,
    }
    return render(request, 'queue_operations/crumbs/operations_profile_nur.html', context)

@login_required
def operations_profile_lab(request, key):
    page = 'operations-profile-lab'
    patient = get_object_or_404(PatientProfile, id=key)
    context = {
        'page':page,
        'patient':patient,
    }
    return render(request, 'queue_operations/crumbs/operations_profile_lab.html', context)

@login_required
def operations_profile_rad(request, key):
    page = 'operations-profile-rad'
    patient = get_object_or_404(PatientProfile, id=key)
    context = {
        'page':page,
        'patient':patient,
    }
    return render(request, 'queue_operations/crumbs/operations_profile_rad.html', context)


@login_required
@department_required('Nursing', 'Clinical', 'Admin', 'CMD')
@transaction.atomic
def background_health(request, key):
    page = 'background-health'
    health_id = 0
    patient = get_object_or_404(PatientProfile, id=key)
    form = BackgroundHealthForm()
    alergy_form = PatientAlergyUpdateForm(instance=patient)
    modify_form = None  # initialize empty

    try:
        update_list = PatientBackgroundHealth.objects.get(patient=patient)
        modify_form = EditPatientBackgroundHealthForm(instance=update_list)
        health_id = 1
    except PatientBackgroundHealth.DoesNotExist:
        update_list = None  # no record yet
        modify_form = EditPatientBackgroundHealthForm()  # empty form

    if request.method == 'POST':
        if 'save_details' in request.POST:
            form = BackgroundHealthForm(request.POST)
            if request.user.pin == int(request.POST.get('pin_code')):
                PatientBackgroundHealth.objects.get_or_create(
                    asthma=request.POST['asthma'],
                    hypertension=request.POST['hypertension'],
                    diabetics=request.POST['diabetics'],
                    epilepsy=request.POST['epilepsy'],
                    tuberculosis=request.POST['tuberculosis'],
                    sickle_cell=request.POST['sickle_cell'],
                    stroke=request.POST['stroke'],
                    eye_problem=request.POST['eye_problem'],
                    kidney_problem=request.POST['kidney_problem'],
                    liver_problem=request.POST['liver_problem'],
                    mental_illness=request.POST['mental_illness'],
                    cancer=request.POST['cancer'],
                    allergies=request.POST['allergies'],
                    latex=request.POST['latex'],
                    drugs=request.POST['drugs'],
                    surgical_operation=request.POST['surgical_operation'],
                    blood_transfution=request.POST['blood_transfution'],
                    patient=patient,
                    staff=request.user
                )
                messages.success(request, 'Background Health History successfully saved!')
                return redirect('vital_signs', key=patient.id)
            else:
                messages.error(request, 'Incorrect Pin Code')
        elif 'allergy' in request.POST:
            alergy_form = PatientAlergyUpdateForm(request.POST, instance=patient)
            if alergy_form.is_valid():
                if request.user.pin == int(request.POST.get('pin_code')):
                    try:
                        alergy_form.save()
                        messages.success(request, 'Patient Allergies successfully updated!')
                        return redirect('vital_signs', key=patient.id)
                    except Exception as e:
                        messages.error(request, f'Error saving patient: {str(e)}')
                else:
                    messages.error(request, 'Incorrect Pin Code Entry')
            else:
                messages.error(request, 'Error Occurred!')
        elif 'modify_details' in request.POST and update_list:
            modify_form = EditPatientBackgroundHealthForm(request.POST, instance=update_list)
            if modify_form.is_valid():
                if request.user.pin == int(request.POST.get('pin_code')):
                    try:
                        modify_form.save()
                        messages.success(request, 'Patient Background Health History successfully modified!')
                        return redirect('vital_signs', key=patient.id)
                    except Exception as e:
                        messages.error(request, f'Error saving patient: {str(e)}')
                else:
                    messages.error(request, 'Incorrect Pin Code Entry')
            else:
                messages.error(request, 'Error Occurred!')

    context = {
        'patient': patient,
        'page': page,
        'form': form,
        'health_id': health_id,
        'modify_form': modify_form,
        'alergy_form': alergy_form,
    }
    return render(request, 'queue_operations/background_health.html', context)


STORES_CONFIG = {
    'ipd_pharm1': {'name': 'IPD Pharmacy 1','app_name': 'IPD_pharm','models_module': 'IPD_pharm.models','drug_model': 'Drugs','transaction_model': 'IPDAdministeredDrugs','display_name': 'IPD Pharmacy 1'},
    'ipd_pharm2': {'name': 'IPD Pharmacy 2','app_name': 'IPD_pharm2','models_module': 'IPD_pharm2.models','drug_model': 'Ipd2Drugs','transaction_model': 'IPD2AdministeredDrugs','display_name': 'IPD Pharmacy 2'},
    'ipd_pharm3': {'name': 'IPD Pharmacy 3','app_name': 'IPD_pharm3','models_module': 'IPD_pharm3.models','drug_model': 'Ipd3Drugs','transaction_model': 'IPD3AdministeredDrugs','display_name': 'IPD Pharmacy 3'},
    'opd_pharm1': {'name': 'OPD Pharmacy 1','app_name': 'OPD_pharm','models_module': 'OPD_pharm.models','drug_model': 'OpdDrugs','transaction_model': 'OPDAdministeredDrugs','display_name': 'OPD Pharmacy 1'},
    'opd_pharm2': {'name': 'OPD Pharmacy 2','app_name': 'OPD_pharm2','models_module': 'OPD_pharm2.models','drug_model': 'Opd2Drugs','transaction_model': 'OPD2AdministeredDrugs','display_name': 'OPD Pharmacy 2'},
}

def get_store_model(store_id, model_type='drug'):
    store_config = STORES_CONFIG.get(store_id)
    if not store_config:
        raise ValueError(f"Store {store_id} not found")
    model_name = store_config['drug_model'] if model_type == 'drug' else store_config['transaction_model']
    return apps.get_model(store_config['app_name'], model_name)


@login_required
@department_required('Nursing', 'Clinical', 'Admin', 'CMD')
@transaction.atomic
def vital_signs(request, key):
    page = 'vital-signs'
    patient = get_object_or_404(PatientProfile, id=key)
    vital_signs_form = DoctorWaitingListForm()
    alergy_form = PatientAlergyUpdateForm(instance=patient)
    appointment = PatientAppointmentForm()

    # Antenatal checks
    current_gestational_age_weeks = ''
    antenatal_visit = AntenatalVisit.objects.filter(patient=patient).select_related('current_pregnancy').first()
    if antenatal_visit:
        pregnancy_instance = getattr(antenatal_visit, 'current_pregnancy', None)
        if pregnancy_instance and pregnancy_instance.last_menstrual_period:
            gest_age = pregnancy_instance.calculate_gestational_age()
            current_gestational_age_weeks = f'week {gest_age}'

    try:
        patient_health_hist = PatientBackgroundHealth.objects.get(patient=patient)
    except PatientBackgroundHealth.DoesNotExist:
        return redirect('background_health', key=patient.id)

    # validate patient's queue
    current_waiting_entry = NurseWaitingList.objects.filter(
        patient=patient, waiting_status = 0,
        completed__in = [0, 3],
    ).order_by('-created_date').first()

    if not current_waiting_entry:
        messages.error(request, "This patient doesn't have an active nurse queue entry.")
        return redirect('waiting_list')

    # For immunization tab - getting previously administered vaccines
    administered_vaccines = []
    for sid in STORES_CONFIG:
        try:
            t_model = get_store_model(sid, 'transaction')
            qs = []
            try:
                qs = list(t_model.objects.filter(patient=patient, UoM__iexact='immuno').order_by('-id')[:5])
            except Exception as e:
                print(f"{sid} UoM filter failed: {e}")


            for obj in qs:
                obj.store_id = sid
                # ensure completed exists
                if not hasattr(obj, 'completed'):
                    obj.completed = getattr(obj, 'completed', 0) or 0
                administered_vaccines.append(obj)
                
            print(f"{sid}: Found {len(qs)} immuno records")

        except Exception as e:
            import traceback
            traceback.print_exc()
            continue

    # Sort newest first
    administered_vaccines.sort(key=lambda x: x.id, reverse=True)

    # getting the nearest upcoming appointments
    nearest_appointment = (
        PatientAppointment.objects.filter(
            patient=patient,
            arrival_date__gte=today,
        )
        .order_by("arrival_date", "arrival_time")
        .first()
    )

    # Hnadling post requests
    if request.method == 'POST':
        if 'save_vitals' in request.POST:
            vital_signs_form = DoctorWaitingListForm(request.POST)
            if request.POST['weight']!= '' and request.POST['height']!= '':
                if request.POST['unit'] == 'cm':
                    get_bmi = round((float(request.POST['weight'])/((float(request.POST['height'])/100)*(float(request.POST['height'])/100))),2)
                else:
                    get_bmi = round((float(request.POST['weight'])/(float(request.POST['height']) * float(request.POST['height']))),2)
            else:
                get_bmi = 0
            if request.user.pin == int(request.POST.get('pin_code')):
                if vital_signs_form.is_valid():
                    get_vitals = vital_signs_form.save(commit=False)
                    get_vitals.patient = patient
                    get_vitals.staff = request.user
                    get_vitals.bmi = get_bmi
                    get_vitals.category = patient.category
                    get_vitals.plan = patient.plan
                    get_vitals.critical_request = current_waiting_entry.critical_request
                    get_vitals.anc_weeks = current_gestational_age_weeks
                    get_vitals.purpose = re.sub(r'\s*\([^)]*\)', '', current_waiting_entry.purpose).strip()
                    get_vitals.save()
                    current_waiting_entry.waiting_status = 1
                    current_waiting_entry.completed_by = request.user.fullname
                    current_waiting_entry.save()
                    messages.success(request, 'Vitals saved! Patient sent to doctor queue.')
                    return redirect('waiting_list')
                else:
                    error_msg = ", ".join([f"{k}: {v[0]}" for k, v in vital_signs_form.errors.items()])
                    messages.error(request, f'Invalid form data: {error_msg}')
            else:
                messages.error(request, 'Incorrect PIN')

        elif 'appoints' in request.POST:
            appointment = PatientAppointmentForm(request.POST)
            if appointment.is_valid():
                if request.user.pin == int(request.POST.get('pin_code')):
                    try:
                        a_form = appointment.save(commit=False)
                        a_form.provider = request.user
                        a_form.patient = patient
                        a_form.clinician = 'Nurse '+ request.user.fullname
                        a_form.save()
                        messages.success(request, f'Appointment Created with {patient.surname} {patient.first_name}')
                    except Exception as e:
                        messages.error(request, f'Error creating request: {str(e)}')
                else:
                    messages.error(request, 'Incorrect Pin Code Entry')
            else:
                messages.error(request, 'Error Occurred!')

        elif 'allergy' in request.POST:
            alergy_form = PatientAlergyUpdateForm(request.POST, instance=patient)
            if alergy_form.is_valid():
                if request.user.pin == int(request.POST.get('pin_code')):
                    try:
                        alergy_form.save()
                        messages.success(request, 'Patient Allergies successfully updated!')
                        return redirect('vital_signs', key=patient.id)
                    except Exception as e:
                        messages.error(request, f'Error saving patient: {str(e)}')
                else:
                    messages.error(request, 'Incorrect Pin Code Entry')
            else:
                messages.error(request, 'Error Occurred!')

    context = {
        'patient': patient,
        'page': page,
        'vital_signs_form': vital_signs_form,
        'patient_health_hist': patient_health_hist,
        'alergy_form': alergy_form,
        'appointment':appointment,
        'nearest_appointment':nearest_appointment,
        'stores': STORES_CONFIG, # for immunization
        'administered_vaccines': administered_vaccines,
    }
    return render(request, 'queue_operations/vital_signs.html', context)


@login_required
@department_required('Nursing', 'Clinical', 'Admin', 'CMD')
def manage_vital_signs(request, key):
    page = 'manage-vitals'
    patient = get_object_or_404(PatientProfile, id=key)

    # check the last modified bg-health-record
    bg_health_last_modified_by = ''


    last_bg_health = PatientBackgroundHealth.objects.filter(patient=patient).last()

    if last_bg_health:
        last_modifed_bg_health = last_bg_health.staff
        
        # Check if the staff has a department before accessing attributes
        if last_modifed_bg_health and last_modifed_bg_health.department:
            dept_name = last_modifed_bg_health.department.department
            
            if dept_name == 'Clinical':
                bg_health_last_modified_by = 'Dr.'
            elif dept_name == 'Nursing':
                bg_health_last_modified_by = 'Nurse'
 
    # check if background health record exists
    try:
        patient_health_hist = PatientBackgroundHealth.objects.get(patient=patient)
    except PatientBackgroundHealth.DoesNotExist:
        return redirect('doctor_waiting_list')

    # Check for waiting list record
    mod_vital_signsform = None

    try: 
        vital_signs = DoctorWaitingList.objects.filter(
        patient=patient, waiting_status=0,
        completed=0  
    ).order_by('-created_date').first()
        mod_vital_signsform = DoctorWaitingListModifyForm(instance=vital_signs)

    except DoctorWaitingList.DoesNotExist:
        vital_signs = None
        mod_vital_signsform = DoctorWaitingListModifyForm()
        messages.error(request, "This patient is not in the doctor waiting list.")
        return redirect('doctor_waiting_list')  

    if request.method == 'POST':

        if 'modify_vital_signs' in request.POST:
            if request.user.pin == int(request.POST.get('pin_code')):
                if request.POST['weight'] != '' and request.POST['height'] != '':
                    if request.POST['unit'] == 'cm':
                        get_bmi = round((float(request.POST['weight'])/((float(request.POST['height'])/100)*(float(request.POST['height'])/100))),2)
                    else:
                        get_bmi = round((float(request.POST['weight'])/(float(request.POST['height']) * float(request.POST['height']))),2)
                else:
                    get_bmi = 0
                mod_vital_signsform = DoctorWaitingListModifyForm(request.POST, instance=vital_signs)
                if mod_vital_signsform.is_valid():
                    mod_user = mod_vital_signsform.save(commit=False)
                    mod_user.staff = request.user
                    mod_user.bmi = get_bmi
                    mod_user.save()
                    messages.success(request, 'Vital signs successfully changed!')
                else:
                    messages.error(request, 'Error occurred, pls try again!')
            else:
                messages.error(request, 'Incorrect Pin supplied!')

        elif 'allergy' in request.POST:
            alergy_form = PatientAlergyUpdateForm(request.POST, instance=patient)
            if alergy_form.is_valid():
                if request.user.pin == int(request.POST.get('pin_code')):
                    try:
                        alergy_form.save()
                        messages.success(request, 'Patient Allergies successfully updated!')
                        return redirect('vital_signs', key=patient.id)
                    except Exception as e:
                        messages.error(request, f'Error saving patient: {str(e)}')
                else:
                    messages.error(request, 'Incorrect Pin Code Entry')
            else:
                messages.error(request, 'Error Occurred!')

    context = {
        'patient': patient,
        'page': page,
        'patient_health_hist': patient_health_hist,
        'vital_signs':vital_signs,
        'mod_vital_signsform':mod_vital_signsform,
        'bg_health_last_modified_by':bg_health_last_modified_by,
    }
    return render(request, 'queue_operations/nurse_vitals_view.html', context)


def search_vaccines(request):
    query = request.GET.get('q', '').strip()
    store_id = request.GET.get('store', 'ipd_pharm1')
    patient_id = request.GET.get('patient_id')
    if len(query) < 2:
        return JsonResponse({'results': []})
    try:
        drug_model = get_store_model(store_id, 'drug')

        products = drug_model.objects.filter(
            activation_status=1,
            minimum_UoM__iexact='immuno',  # ONLY vaccines
            product_name__icontains=query
        )[:20]

        # plan / tariff logic 
        default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()
        patient_plan = default_plan
        if patient_id:
            try:
                p = PatientProfile.objects.select_related('plan').get(id=patient_id)
                patient_plan = p.plan or default_plan
            except: pass
        product_codes = [p.product_id for p in products]
        tariff_map = {t.product_id.lower(): t.rate for t in PharmacyTariff.objects.filter(product_id__in=product_codes, plan=patient_plan)}

        results = []
        for product in products:
            key = (product.product_id or '').lower()
            tariff_price = tariff_map.get(key, product.price)
            results.append({
                'pk_id': product.id,  
                'id': product.id, 
                'text': f"{product.product_name} - ₦{tariff_price} (Stock: {product.stock})",
                'stock': product.stock,
                'price': str(tariff_price),
                'original_name': product.product_name,
                'store_id': store_id,
                'product_code': product.product_id,  
                'uom': product.minimum_UoM,
            })
        return JsonResponse({'results': results})
    except Exception as e:
        return JsonResponse({'results': [], 'error': str(e)})


@login_required
@transaction.atomic
def administer_vaccine(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    try:
        data = json.loads(request.body)
        patient = get_object_or_404(PatientProfile, id=data.get('patient_id'))
        store_id = data.get('store_id')
        product_code = data.get('product_code')  
        product_name = data.get('product_name')
        price = data.get('price')
        qty = int(data.get('quantity', 1))

        drug_model = get_store_model(store_id, 'drug')
        trans_model = get_store_model(store_id, 'transaction')

        product_obj = drug_model.objects.get(product_id=product_code)

        if product_obj.stock < qty:
            return JsonResponse({'success': False, 'error': f'Insufficient stock: {product_obj.stock}'})

        trans_model.objects.create(
            product=product_obj,  
            item=product_name,   
            rate=price,          
            quantity=qty,         
            UoM='immuno',         
            patient=patient,
            category=patient.category,
            plan=patient.plan,
            staff=request.user
        )

        product_obj.stock -= qty
        product_obj.save()

        # update TransactionUpdate model from Billings app
        obj, created = TransactionUpdate.objects.get_or_create(
            patient=patient,
            completed=0,
            defaults={
                'invoice_raised': 0, 
                'receipt_given': 0
                    }
        )

        return JsonResponse({'success': True})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@transaction.atomic
def delete_vaccine(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    try:
        data = json.loads(request.body)
        record_id = data.get('record_id')
        store_id = data.get('store_id')
        
        t_model = get_store_model(store_id, 'transaction')
        record = get_object_or_404(t_model, id=record_id)

        # ONLY allow delete if payment had not been made
        completed_val = getattr(record, 'completed', 0) or 0
        if int(completed_val) != 0:
            return JsonResponse({'success': False, 'error': 'Cannot delete - transaction already completed/billed'})

        # Restore stock
        try:
            drug_model = get_store_model(store_id, 'drug')
            if hasattr(record, 'product') and record.product:
                product_obj = record.product
                product_obj.stock += record.quantity
                product_obj.save()
        except:
            pass

        record.delete()
        return JsonResponse({'success': True})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})
    


# Beginning of Doctor's Views
@login_required
@department_required('Nursing', 'Clinical', 'Admin', 'CMD')
def doctor_waiting_list(request):
    today = timezone.now().date()
    clean_purpose = re.sub(r'\s*\([^)]*\)', '', request.user.purpose.purpose).strip()
    patients = DoctorWaitingList.objects.filter(completed=0, waiting_status = 0, purpose=clean_purpose, created_date__gte=timezone.now() - timedelta(hours=24)).select_related('patient')

    context = {
        'patients':patients,
        'counts':patients.count(),
        'title':'Patients Waiting List',
        'page':'doctor-waiting-list'
    }
    return render(request, 'queue_operations/waiting_list.html', context)


def fetch_doctors_queue(request):
    filter_by_specialty = re.sub(r'\s*\([^)]*\)', '', request.user.purpose.purpose).strip()
    queue = DoctorWaitingList.objects.filter(
        completed=0,
        waiting_status=0, purpose=filter_by_specialty,
        created_date__gte=timezone.now() - timedelta(hours=24)
    ).select_related('patient', 'staff') # faster

    data = []
    for record in queue:
        patient = record.patient
        data.append({
            'patient_id': patient.id if patient else '',
            'name': f"{patient.surname} {patient.other_name} {patient.first_name}" if patient else "N/A",
            'hospital_number': f"{patient.hospital_number} " if patient else "N/A",
            'plan': f"{patient.plan} " if patient else "N/A",
            'attendant': f"{record.staff.fullname} " if record.staff else "N/A",
            'created_date': record.created_date.strftime('%Y-%m-%d %H:%M'),
            'critical_request': getattr(record, 'critical_request', 0),
            'encounter_status': record.encounter_status, 
            'completed_by': f"{record.completed_by} " if record.completed_by else "No Doctor yet",
        })

    return JsonResponse({
        'data': data,
        'count': len(data)
    })


@login_required
@department_required('Clinical', 'Admin', 'CMD')
def load_doctor_queue(request):
    return render(request, 'queue_operations/doctors_queue.html')

def doctor_waiting_count(request):
    # filter_by_specialty = re.sub(r'\s*\([^)]*\)', '', request.user.purpose.purpose).strip()
    count = DoctorWaitingList.objects.filter(
        completed=0,
        waiting_status=0,
        # purpose=filter_by_specialty,
        created_date__gte=timezone.now() - timedelta(hours=24)
    ).count()
    return JsonResponse({'count': count})


@login_required
@department_required('Front Desk', 'Nursing', 'Clinical', 'Admin', 'CMD')
def doctor_waiting_list_all(request): # (Admin and CMD, Doctors, Nursing, and FrontDesk)
    page = 'doctor_queue_all'
    now = timezone.localtime(timezone.now())
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    patients = DoctorWaitingList.objects.filter(completed=0, waiting_status = 0, created_date__gte=timezone.now() - timedelta(hours=24)).select_related('category', 'patient', 'plan')
    context = {
        'page':page,
        'patients':patients
    }
    return render(request, 'queue_operations/waiting_listss.html',context)


# Patient waiting List (Laboratory results)
def fetch_lab_results_queue(request):
    queue = LabResult.objects.filter(
        waiting_status=0,
        created_date__gte=timezone.now() - timedelta(hours=24)
    ).order_by('-created_date')
    
    data = []
    seen_patients = set()
    
    for record in queue:
        patient = record.patient
        if not patient or patient.id in seen_patients:
            continue
            
        seen_patients.add(patient.id)
        data.append({
            'patient_id': patient.id,
            'name': f"{patient.surname} {patient.other_name} {patient.first_name}",
            'hospital_number': f"{patient.hospital_number}",
            'category': f"{patient.category}",
            'plan': f"{patient.plan}",
            'attendant': f"{record.staff.fullname}" if record.staff else "N/A",
            'created_date': record.created_date.strftime('%Y-%m-%d %H:%M'),
        })

    return JsonResponse({
        'data': data,
        'count': len(data)
    })


@login_required
@department_required('Clinical', 'Admin', 'CMD')
def load_lab_results_queue(request):
    page = 'lab-results-queue'
    context = {
        'page':page
    }
    return render(request,'queue_operations/radiolab_queue.html',context)


def lab_results_waiting_count(request):
    # Count unique patients
    count = LabResult.objects.filter(
        waiting_status=0,
        created_date__gte=timezone.now() - timedelta(hours=24),
        patient__isnull=False  # Exclude records without patients
    ).values('patient').distinct().count()
    
    return JsonResponse({'count': count})


# Patient waiting List (Radiology results)
def fetch_scan_results_queue(request):
    queue = ScanResult.objects.filter(
        waiting_status=0,
        created_date__gte=timezone.now() - timedelta(hours=24)
    ).order_by('-created_date')
    
    data = []
    seen_patients = set()
    
    for record in queue:
        patient = record.patient
        if not patient or patient.id in seen_patients:
            continue
            
        seen_patients.add(patient.id)
        data.append({
            'patient_id': patient.id,
            'name': f"{patient.surname} {patient.other_name} {patient.first_name}",
            'hospital_number': f"{patient.hospital_number}",
            'category': f"{patient.category}",
            'plan': f"{patient.plan}",
            'attendant': f"{record.staff.fullname}" if record.staff else "N/A",
            'created_date': record.created_date.strftime('%Y-%m-%d %H:%M'),
        })

    return JsonResponse({
        'data': data,
        'count': len(data)
    })


@login_required
@department_required('Clinical', 'Admin', 'CMD')
def load_scan_results_queue(request):
    page = 'scan-results-queue'
    context = {
        'page':page
    }
    return render(request,'queue_operations/radiolab_queue.html',context)


def scan_results_waiting_count(request):
    # Count unique patients
    count = ScanResult.objects.filter(
        waiting_status=0,
        created_date__gte=timezone.now() - timedelta(hours=24),
        patient__isnull=False  
    ).values('patient').distinct().count()
    
    return JsonResponse({'count': count})


@login_required
@department_required('Clinical', 'Admin', 'CMD')
def doctor_done_list(request):
    patients = DoctorWaitingList.objects.filter(waiting_status = 1, completed_by = request.user.fullname, created_date__gte=timezone.now() - timedelta(hours=24))

    context = {
        'patients':patients,
        'counts':patients.count(),
        'title':'Your completed list for Today',
        'page':'doctor-done-list'
    }
    return render(request, 'queue_operations/done_list.html', context)


@login_required
@department_required('Clinical', 'Admin', 'CMD')
def doctor_nurse_report(request, key):
    page = 'doctor-nurse-report'
    patient = get_object_or_404(PatientProfile, id=key)

    current_waiting_entry = DoctorWaitingList.objects.filter(
            patient=patient, waiting_status = 0,
            completed = 0, encounter_status__in = [0,3]
        ).order_by('-created_date').first()
    
    
    # check the last modified bg-health-record
    bg_health_last_modified_by = ''
    last_bg_health = PatientBackgroundHealth.objects.filter(patient=patient).last()

    if last_bg_health:
        last_modifed_bg_health = last_bg_health.staff
        
        # Check if the staff has a department before accessing attributes
        if last_modifed_bg_health and last_modifed_bg_health.department:
            dept_name = last_modifed_bg_health.department.department
            
            if dept_name == 'Clinical':
                bg_health_last_modified_by = 'Dr.'
            elif dept_name == 'Nursing':
                bg_health_last_modified_by = 'Nurse'
 
    # check if background health record exists
    try:
        patient_health_hist = PatientBackgroundHealth.objects.get(patient=patient)
    except PatientBackgroundHealth.DoesNotExist:
        return redirect('doctor_waiting_list')

    # Check for waiting list record
    mod_vital_signsform = None

    try: 
        vital_signs = DoctorWaitingList.objects.filter(
        patient=patient, waiting_status=0,
        completed=0  
    ).order_by('-created_date').first()
        mod_vital_signsform = DoctorWaitingListModifyForm(instance=vital_signs)

    except DoctorWaitingList.DoesNotExist:
        vital_signs = None
        mod_vital_signsform = DoctorWaitingListModifyForm()
        messages.error(request, "This patient is not in the doctor waiting list.")
        return redirect('doctor_waiting_list')  
    
    modify_bg_healthform = None  # initialize empty

    try:
        update_list = PatientBackgroundHealth.objects.get(patient=patient)
        modify_bg_healthform = EditPatientBackgroundHealthForm(instance=update_list)

    except PatientBackgroundHealth.DoesNotExist:
        update_list = None  # no record yet
        modify_bg_healthform = EditPatientBackgroundHealthForm()  # empty form

    if request.method == 'POST':
        if 'modify_bg_health' in request.POST and update_list:
            modify_bg_healthform = EditPatientBackgroundHealthForm(request.POST, instance=update_list)
            if modify_bg_healthform.is_valid():
                    try:
                        mod_user = modify_bg_healthform.save(commit=False)
                        mod_user.staff = request.user
                        mod_user.save()
                        messages.success(request, 'Background Health History successfully changed!')
                        # return redirect('doctor_consultation', key=patient.id)
                    except Exception as e:
                        messages.error(request, f'Error saving patient: {str(e)}')
            else:
                messages.error(request, 'Error Occurred!')
        elif 'modify_vital_signs' in request.POST:
            if request.POST['weight'] != '' and request.POST['height'] != '':
                if request.POST['unit'] == 'cm':
                    get_bmi = round((float(request.POST['weight'])/((float(request.POST['height'])/100)*(float(request.POST['height'])/100))),2)
                else:
                    get_bmi = round((float(request.POST['weight'])/(float(request.POST['height']) * float(request.POST['height']))),2)
            else:
                get_bmi = 0
            mod_vital_signsform = DoctorWaitingListModifyForm(request.POST, instance=vital_signs)
            if mod_vital_signsform.is_valid():
                mod_user = mod_vital_signsform.save(commit=False)
                mod_user.staff = request.user
                mod_user.bmi = get_bmi
                mod_user.save()
                messages.success(request, 'Vital signs successfully changed!')
                # return redirect('doctor_consultation', key=patient.id)
            else:
                messages.error(request, 'Error occurred, pls try again!')
        elif 'admit_patient' in request.POST:
            if request.user.pin == int(request.POST.get('pin_code')):
                admission = AdmissionTable.objects.create(
                patient=patient,
                doctor_admitted=request.user,
            )
                if admission:
                    messages.success(request,'Successfully admitted!')
                else:
                    messages.error(request,'Error Occurred! try later')
            else:
                messages.error(request,'Incorrect Pin!')


    context = {
        'patient': patient,
        'page': page,
        'modify_bg_healthform':modify_bg_healthform,
        'patient_health_hist': patient_health_hist,
        'vital_signs':vital_signs,
        'mod_vital_signsform':mod_vital_signsform,
        'bg_health_last_modified_by':bg_health_last_modified_by,
        
        #for updating waiting/encounter status
        'current_waiting_entry': current_waiting_entry,
        'current_waiting_entry_id': current_waiting_entry.id if current_waiting_entry else None,
    }
    return render(request, 'queue_operations/doctor_consultation.html', context)


@login_required
@require_POST
def update_encounter_status(request, pk):
    try:
        entry = DoctorWaitingList.objects.select_related('patient').get(pk=pk)
    except DoctorWaitingList.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Waiting list entry not found.'}, status=404)

    # Prevent double click / race condition
    if entry.encounter_status not in [0,3]:
        return JsonResponse({
            'success': False,
            'message': f'Already handled (status={entry.encounter_status}).'
        }, status=400)

    # supports both form-encoded and JSON
    action = request.POST.get('action')
    if not action:
        try:
            action = json.loads(request.body).get('action')
        except:
            pass

    if action == 'confirm':
        entry.encounter_status = 2 # started
        entry.completed_by = request.user.fullname
        msg = f'Encounter started for {entry.patient.get_full_name()}.'
    elif action == 'cancel':
        entry.encounter_status = 0 # cancelled
        msg = f'Encounter cancelled for {entry.patient.get_full_name()}.'
    else:
        return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)

    entry.save(update_fields=['encounter_status'])
    return JsonResponse({'success': True, 'message': msg, 'encounter_status': entry.encounter_status})


@login_required
@department_required('Clinical', 'Admin', 'CMD')
def complaint_search(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    other_details_value = referrals_value = encounters_value = followups_value = appointments_value = ""
     # Get all records for the last 24 hours
    time_threshold = timezone.now() - timedelta(hours=24)
    
    encounters = PatientEncounter.objects.filter(
        patient=patient,
        provider=request.user,
        created_at__gte=time_threshold
    ).order_by('-created_at')[:2]
    if encounters:
        encounters_value = '1'
    
    referrals = PatientReferral.objects.filter(
        patient=patient,
        provider=request.user,
        created_at__gte=time_threshold
    ).order_by('-created_at')[:2]
    if referrals:
        referrals_value = '1'
    
    other_details = PatientOtherDetails.objects.filter(
        patient=patient,
        provider=request.user,
        created_at__gte=time_threshold
    ).order_by('-created_at')[:2]

    if other_details:
        other_details_value = '1'

    followups = PatientFollowUp.objects.filter(
        patient=patient,
        provider=request.user,
        created_at__gte=time_threshold
    ).order_by('-created_at')[:2]
    if followups:
        followups_value = '1'

    appointments = PatientAppointment.objects.filter(patient=patient, created_date__gte=time_threshold
    ).order_by('-created_date')[:2]
    if appointments:
        appointments_value = '1'
    
    
    context = {
        'patient':patient,
        'encounters':encounters,
        'referrals': referrals,
        'other_details': other_details,
        'followups': followups,
        'appointments':appointments,
        'other_details_value':other_details_value,
        'followups_value':followups_value,
        'encounters_value': encounters_value,
        'referrals_value':referrals_value,
        'appointments_value':appointments_value
    }
    return render(request, 'queue_operations/presenting_complaints.html',context)


from .models import PresentingComplaint, PatientEncounter

@login_required
def ajax_search_complaints(request):
    """Search complaints dynamically."""
    term = request.GET.get('term', '').strip()
    results = []

    if term:
        complaints = PresentingComplaint.objects.filter(
            Q(name__icontains=term) | Q(category__icontains=term),
            is_active=True
        ).order_by('category', 'name')[:20]

        results = [
            {'id': c.id, 'name': c.name, 'category': c.get_category_display()}
            for c in complaints
        ]

    return JsonResponse(results, safe=False)


from .models import PatientDiagnosis 

@login_required
def ajax_search_diagnoses(request):
    """Search diagnoses dynamically."""
    term = request.GET.get('term', '').strip()
    print(f"Searching diagnoses for: {term}") 
    results = []
    if term:
        diagnoses = PatientDiagnosis.objects.filter(
            Q(description__icontains=term) | 
            Q(icd10_code__icontains=term) | 
            Q(category__icontains=term),
            is_active=True
        ).order_by('category', 'description')[:20]
        
        results = [
            {
                'id': d.id,
                'name': f"{d.icd10_code} - {d.description}",
                'category': d.category  
            }
            for d in diagnoses
        ]
    print(f"Found {len(results)} results") 
    return JsonResponse(results, safe=False)


@login_required
@require_POST
def save_encounter(request):
    """Saving the encounter via AJAX with all PatientEncounter fields."""
    try:
        data = json.loads(request.body.decode('utf-8'))
        print("Received data:", data)  # Debug print
        
        patient_id = data.get('patient_id')
        complaints = data.get('complaints', [])
        diagnoses = data.get('diagnoses', [])
        history = data.get('history', '').strip()
        diagnosis_comments = data.get('diagnosis_comments', '').strip()

        print(f"Patient ID: {patient_id}")
        print(f"Diagnoses data: {diagnoses}")
        
        patient = PatientProfile.objects.get(id=patient_id)
        provider = request.user

        # Handle complaints 
        saved_complaints = []
        for c in complaints:
            if isinstance(c, dict) and c.get('id'):
                saved_complaints.append(c['name'])
            else:
                name = c if isinstance(c, str) else c['name']
                new_c = PresentingComplaint.objects.create(
                    name=name,
                    category='general',
                    is_active=True
                )
                saved_complaints.append(new_c.name)

        # Handle diagnoses 
        saved_diagnoses = []
        for d in diagnoses:
            print(f"Processing diagnosis: {d}")  # Debug print
            print(f"Type of d: {type(d)}")  # Debug print
            
            if isinstance(d, dict) and d.get('id'):
                # Existing diagnosis
                print(f"Existing diagnosis with id: {d['id']}")
                saved_diagnoses.append(d['name'])
            else:
                # New one typed by user
                if isinstance(d, dict):
                    name = d.get('name', '')
                else:
                    name = str(d)
                
                print(f"Creating new diagnosis: {name}")
                
                new_d = PatientDiagnosis.objects.create(
                    description=name,
                    icd10_code='UNDEF', 
                    category='infectious',  
                    is_active=True
                )
                saved_diagnoses.append(f"{new_d.icd10_code} - {new_d.description}")

        print(f"Saved diagnoses: {saved_diagnoses}")
        
        # Save encounter
        encounter = PatientEncounter.objects.create(
            patient=patient,
            provider=provider,
            chief_complaint=', '.join(saved_complaints),
            history_of_present_illness=history,
            diagnosis=', '.join(saved_diagnoses),
            comments_on_diagnosis=diagnosis_comments
        )
        
        print("Encounter saved successfully!")
        
        return JsonResponse({'success': True, 'message': '✅✅ Primary Encounter saved successfully.'})
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
@require_POST
def save_referral(request):
    """Save referral via AJAX."""
    data = json.loads(request.body.decode('utf-8'))
    patient_id = data.get('patient_id')
    
    patient = PatientProfile.objects.get(id=patient_id)
    provider = request.user

    # Create referral
    referral = PatientReferral.objects.create(
        patient=patient,
        provider=provider,
        referring_clinic=data.get('referring_clinic'),
        referrer_phone=data.get('referrer_phone'),
        referrer_address=data.get('referrer_address'),
        referring_physician=data.get('referring_physician'),
        referrer_email=data.get('referrer_email'),
        clinic_referred_to=data.get('clinic_referred_to'),
        referred_to_phone=data.get('referred_to_phone'),
        referred_to_address=data.get('referred_to_address'),
        physician_referred_to=data.get('physician_referred_to'),
        referred_to_email=data.get('referred_to_email'),
        referred_department_clinic=data.get('referred_department_clinic'),
        refer_to_clinician=data.get('refer_to_clinician'),
        reason_for_referring=data.get('reason_for_referring')
    )

    return JsonResponse({'success': True, 'message': '✅ Referral saved successfully.'})

@login_required
@require_POST
def save_other_details(request):
    """Save referral via AJAX."""
    data = json.loads(request.body.decode('utf-8'))
    patient_id = data.get('patient_id')
    
    patient = PatientProfile.objects.get(id=patient_id)
    provider = request.user

    # Create Other Details
    other_details = PatientOtherDetails.objects.create(
        patient=patient,
        provider=provider,
        condition_status=data.get('condition_status'),
        to_be_admitted=data.get('to_be_admitted'),
        assigned_doctor=data.get('assigned_doctor'),
        be_referred_out=data.get('be_referred_out'),
    )

    return JsonResponse({'success': True, 'message': '✅ Other Details saved successfully.'})

@login_required
@require_POST
def save_followup(request):
    """Save follow-up via AJAX."""
    data = json.loads(request.body.decode('utf-8'))
    patient_id = data.get('patient_id')
    summary_notes = data.get('summary_notes', '').strip()
    visit_type = data.get('visit_type')
    treatment_progress = data.get('treatment_progress')
    drugs_compliance = data.get('drugs_compliance')

    patient = PatientProfile.objects.get(id=patient_id)
    provider = request.user

    # Create follow-up
    followup = PatientFollowUp.objects.create(
        patient=patient,
        provider=provider,
        summary_notes=summary_notes,
        visit_type=visit_type,
        treatment_progress=treatment_progress,
        drugs_compliance=drugs_compliance
    )

    return JsonResponse({'success': True, 'message': '✅ Follow-up and final report saved successfully.'})


@login_required
def edit_encounter(request, encounter_id):
    """Get encounter data for editing within 24 hours"""
    try:
        # Get encounter within 24 hours for current provider
        time_threshold = timezone.now() - timedelta(hours=24)
        
        encounter = PatientEncounter.objects.filter(
            id=encounter_id,
            provider=request.user,
            created_at__gte=time_threshold
        ).first()  # This returns None if no match found
        
        if encounter:
            data = {
                'success': True,
                'encounter': {
                    'id': encounter.id,
                    'chief_complaint': encounter.chief_complaint,
                    'history_of_present_illness': encounter.history_of_present_illness,
                    'diagnosis': encounter.diagnosis,
                    'comments_on_diagnosis': encounter.comments_on_diagnosis,
                    'patient_id': encounter.patient.id,
                    'created_at': encounter.created_at.strftime('%Y-%m-%d %H:%M:%S')
                }
            }
        else:
            data = {
                'success': False,
                'message': 'Encounter not found or cannot be edited (older than 24 hours or not your patient)'
            }
        
    except Exception as e:
        data = {
            'success': False,
            'message': f'Error: {str(e)}'
        }
    
    return JsonResponse(data)


@login_required
@csrf_exempt
def update_encounter(request, encounter_id):
    """Update encounter data within 24 hours"""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            
            # Get encounter within 24 hours for current provider
            time_threshold = timezone.now() - timedelta(hours=24)
            
            encounter = PatientEncounter.objects.filter(
                id=encounter_id,
                provider=request.user,
                created_at__gte=time_threshold
            ).first()
            
            if encounter:
                # Update fields
                encounter.chief_complaint = data.get('chief_complaint', '')
                encounter.history_of_present_illness = data.get('history', '')
                encounter.diagnosis = data.get('diagnosis', '')
                encounter.comments_on_diagnosis = data.get('comments_on_diagnosis', '')
                encounter.save()
                
                data = {
                    'success': True,
                    'message': 'Encounter updated successfully'
                }
            else:
                data = {
                    'success': False,
                    'message': 'Encounter not found or cannot be edited (older than 24 hours)'
                }
            
        except Exception as e:
            data = {
                'success': False,
                'message': f'Error updating encounter: {str(e)}'
            }
        
        return JsonResponse(data)
    

@login_required
@csrf_exempt
def delete_encounter(request, encounter_id):
    """Delete encounter within 24 hours"""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            
            # Get encounter within 24 hours for current provider
            time_threshold = timezone.now() - timedelta(hours=24)
            
            encounter = PatientEncounter.objects.filter(
                id=encounter_id,
                provider=request.user,
                created_at__gte=time_threshold
            ).first()
            
            if encounter:
                # Store encounter info for confirmation message
                encounter_info = f"'{encounter.chief_complaint}' from {encounter.created_at.strftime('%Y-%m-%d %H:%M')}"
                encounter.delete()
                
                data = {
                    'success': True,
                    'message': f'Encounter {encounter_info} has been deleted successfully'
                }
            else:
                data = {
                    'success': False,
                    'message': 'Encounter not found or cannot be deleted (older than 24 hours)'
                }
            
        except Exception as e:
            data = {
                'success': False,
                'message': f'Error deleting encounter: {str(e)}'
            }
        
        return JsonResponse(data)


@login_required
def edit_referral(request, referral_id):
    """Get referral data for editing within 24 hours"""
    try:
        time_threshold = timezone.now() - timedelta(hours=24)
        
        referral = PatientReferral.objects.filter(
            id=referral_id,
            provider=request.user,
            created_at__gte=time_threshold
        ).first()
        
        if referral:
            data = {
                'success': True,
                'referral': {
                    'id': referral.id,
                    'referring_clinic': referral.referring_clinic,
                    'referrer_phone': referral.referrer_phone,
                    'referrer_address': referral.referrer_address,
                    'referring_physician': referral.referring_physician,
                    'referrer_email': referral.referrer_email,
                    'clinic_referred_to': referral.clinic_referred_to,
                    'referred_to_phone': referral.referred_to_phone,
                    'referred_to_address': referral.referred_to_address,
                    'physician_referred_to': referral.physician_referred_to,
                    'referred_to_email': referral.referred_to_email,
                    'referred_department_clinic': referral.referred_department_clinic,
                    'refer_to_clinician': referral.refer_to_clinician,
                    'reason_for_referring': referral.reason_for_referring,
                }
            }
        else:
            data = {
                'success': False,
                'message': 'Referral not found or cannot be edited (older than 24 hours)'
            }
        
    except Exception as e:
        data = {
            'success': False,
            'message': f'Error: {str(e)}'
        }
    
    return JsonResponse(data)

@login_required
@csrf_exempt
def update_referral(request, referral_id):
    """Update referral data within 24 hours"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            time_threshold = timezone.now() - timedelta(hours=24)
            
            referral = PatientReferral.objects.filter(
                id=referral_id,
                provider=request.user,
                created_at__gte=time_threshold
            ).first()
            
            if referral:
                # Update all referral fields
                referral.referring_clinic = data.get('referring_clinic', '')
                referral.referrer_phone = data.get('referrer_phone', '')
                referral.referrer_address = data.get('referrer_address', '')
                referral.referring_physician = data.get('referring_physician', '')
                referral.referrer_email = data.get('referrer_email', '')
                referral.clinic_referred_to = data.get('clinic_referred_to', '')
                referral.referred_to_phone = data.get('referred_to_phone', '')
                referral.referred_to_address = data.get('referred_to_address', '')
                referral.physician_referred_to = data.get('physician_referred_to', '')
                referral.referred_to_email = data.get('referred_to_email', '')
                referral.referred_department_clinic = data.get('referred_department_clinic', '')
                referral.refer_to_clinician = data.get('refer_to_clinician', '')
                referral.reason_for_referring = data.get('reason_for_referring', '')
                referral.save()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Referral updated successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Referral not found or cannot be edited (older than 24 hours)'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error updating referral: {str(e)}'
            })

@login_required
@csrf_exempt
def delete_referral(request, referral_id):
    """Delete referral within 24 hours"""
    if request.method == 'POST':
        try:
            time_threshold = timezone.now() - timedelta(hours=24)
            
            referral = PatientReferral.objects.filter(
                id=referral_id,
                provider=request.user,
                created_at__gte=time_threshold
            ).first()
            
            if referral:
                referral_info = f"Referral from {referral.created_at.strftime('%Y-%m-%d %H:%M')}"
                referral.delete()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Referral {referral_info} has been deleted successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Referral not found or cannot be deleted (older than 24 hours)'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error deleting referral: {str(e)}'
            })

# PATIENT OTHER DETAILS VIEWS

@login_required
def edit_other_details(request, details_id):
    """Get other details data for editing within 24 hours"""
    try:
        time_threshold = timezone.now() - timedelta(hours=24)
        
        details = PatientOtherDetails.objects.filter(
            id=details_id,
            provider=request.user,
            created_at__gte=time_threshold
        ).first()
        
        if details:
            data = {
                'success': True,
                'details': {
                    'id': details.id,
                    'condition_status': details.condition_status,
                    'to_be_admitted': details.to_be_admitted,
                    'assigned_doctor': details.assigned_doctor,
                    'be_referred_out': details.be_referred_out,
                }
            }
        else:
            data = {
                'success': False,
                'message': 'Details not found or cannot be edited (older than 24 hours)'
            }
        
    except Exception as e:
        data = {
            'success': False,
            'message': f'Error: {str(e)}'
        }
    
    return JsonResponse(data)

@login_required
@csrf_exempt
def update_other_details(request, details_id):
    """Update other details data within 24 hours"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            time_threshold = timezone.now() - timedelta(hours=24)
            
            details = PatientOtherDetails.objects.filter(
                id=details_id,
                provider=request.user,
                created_at__gte=time_threshold
            ).first()
            
            if details:
                details.condition_status = data.get('condition_status', '')
                details.to_be_admitted = data.get('to_be_admitted', '')
                details.assigned_doctor = data.get('assigned_doctor', '')
                details.be_referred_out = data.get('be_referred_out', '')
                details.save()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Other details updated successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Details not found or cannot be edited (older than 24 hours)'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error updating details: {str(e)}'
            })

@login_required
@csrf_exempt
def delete_other_details(request, details_id):
    """Delete other details within 24 hours"""
    if request.method == 'POST':
        try:
            time_threshold = timezone.now() - timedelta(hours=24)
            
            details = PatientOtherDetails.objects.filter(
                id=details_id,
                provider=request.user,
                created_at__gte=time_threshold
            ).first()
            
            if details:
                details_info = f"Details from {details.created_at.strftime('%Y-%m-%d %H:%M')}"
                details.delete()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Other details {details_info} has been deleted successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Details not found or cannot be deleted (older than 24 hours)'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error deleting details: {str(e)}'
            })

# PATIENT FOLLOW-UP VIEWS

@login_required
def edit_followup(request, followup_id):
    """Get follow-up data for editing within 24 hours"""
    try:
        time_threshold = timezone.now() - timedelta(hours=24)
        
        followup = PatientFollowUp.objects.filter(
            id=followup_id,
            provider=request.user,
            created_at__gte=time_threshold
        ).first()
        
        if followup:
            data = {
                'success': True,
                'followup': {
                    'id': followup.id,
                    'summary_notes': followup.summary_notes,
                    'visit_type': followup.visit_type,
                    'treatment_progress': followup.treatment_progress,
                    'drugs_compliance': followup.drugs_compliance,
                }
            }
        else:
            data = {
                'success': False,
                'message': 'Follow-up not found or cannot be edited (older than 24 hours)'
            }
        
    except Exception as e:
        data = {
            'success': False,
            'message': f'Error: {str(e)}'
        }
    
    return JsonResponse(data)

@login_required
@csrf_exempt
def update_followup(request, followup_id):
    """Update follow-up data within 24 hours"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            time_threshold = timezone.now() - timedelta(hours=24)
            
            followup = PatientFollowUp.objects.filter(
                id=followup_id,
                provider=request.user,
                created_at__gte=time_threshold
            ).first()
            
            if followup:
                followup.summary_notes = data.get('summary_notes', '')
                followup.visit_type = data.get('visit_type', '')
                followup.treatment_progress = data.get('treatment_progress', '')
                followup.drugs_compliance = data.get('drugs_compliance', '')
                followup.save()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Follow-up updated successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Follow-up not found or cannot be edited (older than 24 hours)'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error updating follow-up: {str(e)}'
            })

@login_required
@csrf_exempt
def delete_followup(request, followup_id):
    """Delete follow-up within 24 hours"""
    if request.method == 'POST':
        try:
            time_threshold = timezone.now() - timedelta(hours=24)
            
            followup = PatientFollowUp.objects.filter(
                id=followup_id,
                provider=request.user,
                created_at__gte=time_threshold
            ).first()
            
            if followup:
                followup_info = f"Follow-up from {followup.created_at.strftime('%Y-%m-%d %H:%M')}"
                followup.delete()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Follow-up {followup_info} has been deleted successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Follow-up not found or cannot be deleted (older than 24 hours)'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error deleting follow-up: {str(e)}'
            })



@login_required
@require_POST
def create_appointment(request):
    try:
        appointment = PatientAppointment.objects.create(
            patient_id=request.POST.get('patient_id'),
            provider=request.user,
            clinician=request.POST.get('clinician'),
            purpose=request.POST.get('purpose'),
            visit_type=request.POST.get('visit_type'),
            arrival_date=request.POST.get('arrival_date'),
            arrival_time=request.POST.get('arrival_time'),
            comment=request.POST.get('comment'),
        )

        return JsonResponse({
            'success': True,
            'message': 'Appointment created successfully',
            'id': appointment.id,
            'can_modify': True
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error creating appointment: {e}'
        }, status=400)


@login_required
def get_appointment(request, pk):
    app = get_object_or_404(PatientAppointment, pk=pk)

    return JsonResponse({
        'id': app.id,
        'clinician': app.clinician,
        'purpose': app.purpose,
        'visit_type': app.visit_type,
        'arrival_date': app.arrival_date,
        'arrival_time': app.arrival_time,
        'comment': app.comment
    })


@login_required
def update_appointment(request, pk):
    appointment = get_object_or_404(PatientAppointment, pk=pk)

    #  block editing after 24 hours
    if timezone.now() > appointment.created_date + timedelta(hours=24):
        return JsonResponse({
            'error': 'Editing period (24 hours) has expired'
        }, status=403)

    if request.method == "POST":
        appointment.clinician = request.POST.get('clinician')
        appointment.purpose = request.POST.get('purpose')
        appointment.visit_type = request.POST.get('visit_type')
        appointment.arrival_date = request.POST.get('arrival_date')
        appointment.arrival_time = request.POST.get('arrival_time')
        appointment.comment = request.POST.get('comment')
        appointment.save()

        return JsonResponse({'success': True})

    return JsonResponse({'error': 'Invalid request'}, status=400)



@login_required
@require_POST
def delete_appointment(request, pk):
    appointment = get_object_or_404(PatientAppointment, pk=pk)

    if not appointment.can_modify():
        return JsonResponse({
            'success': False,
            'message': 'Delete time expired (24 hours exceeded)'
        }, status=403)

    appointment.delete()

    return JsonResponse({
        'success': True,
        'message': 'Appointment deleted successfully'
    })


@login_required
@department_required('Nursing', 'Clinical', 'Billings', 'Admin', 'CMD')
def get_case_note(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    last_bg_health = (
        DoctorWaitingList.objects.filter(patient=patient)
        .select_related('staff__department')
        .last()
    )
    
    bg_health_last_modified_by = ''
    
    # Defensive Check: to ensure last_bg_health and staff exists before accessing attributes
    if last_bg_health and last_bg_health.staff:
        # access the department name string
        dept_name = getattr(last_bg_health.staff.department, 'department', None)
        
        if dept_name == 'Clinical':
            bg_health_last_modified_by = 'Dr.'
        elif dept_name == 'Nursing':
            bg_health_last_modified_by = 'Nurse'

    # 2. Handle POST Request (Admission Logic)
    if request.method == 'POST':
        if 'admit_patient' in request.POST:
            pin_input = request.POST.get('pin_code')
            
            try:
                # Ensuring that pin_input is a valid integer before comparison
                if pin_input and int(request.user.pin) == int(pin_input):
                    admission = AdmissionTable.objects.create(
                        patient=patient,
                        doctor_admitted=request.user,
                    )
                    messages.success(request, 'Successfully admitted!')
                else:
                    messages.error(request, 'Incorrect Pin!')
            except (ValueError, TypeError):
                messages.error(request, 'Invalid Pin Format!')

    # 3. Data Retrieval for Template
    today = timezone.now().date()
    one_day_ago = timezone.now() - timedelta(hours=24)

    vital_signs = DoctorWaitingList.objects.filter(patient=patient).order_by('-created_date')[:1]
    patient_encounters = PatientEncounter.objects.filter(patient=patient).order_by('-created_at')[:1]
    patient_other_details = PatientOtherDetails.objects.filter(patient=patient).order_by('-created_at')[:1]
    followups = PatientFollowUp.objects.filter(patient=patient).order_by('-created_at')[:1]
    referrals_information = PatientReferral.objects.filter(patient=patient).order_by('-created_at')[:1]
    appointments = PatientAppointment.objects.filter(patient=patient).order_by('-created_date')[:1]
    


    #  FETCH DRUGS FROM ALL STORES in the last 24 hours 
    administered_drugs = []
    
    # Get drugs from all stores (for doctor's requests)
    for store_id, config in STORES_CONFIG.items():
        try:
            transaction_model = get_store_model(store_id, 'transaction')
            
            # Fetch drugs for this patient from this store
            drugs = transaction_model.objects.filter(
                staff=request.user,
                patient=patient,
                # pharm_waiting_status=0,
                completed=1,
                created_date__gte=timezone.now() - timedelta(hours=24)
            ).select_related('product')
            
            # Add store information to each drug
            for drug in drugs:
                drug.store_id = store_id
                drug.store_name = config['display_name']
                drug.store_color = 'primary' if 'IPD' in config['display_name'] else 'success'
                administered_drugs.append(drug)
                
        except Exception as e:
            print(f"Error fetching drugs from {config['display_name']}: {str(e)}")
            continue
    
    # Sort by created date (newest first)
    administered_drugs.sort(key=lambda x: x.created_date, reverse=True)

    radiology_scan = RadiologyLab.objects.filter(
        patient=patient, 
        item_type='R',
        completed=1,
        created_date__gte=one_day_ago
    )
    laboratory_lab = RadiologyLab.objects.filter(
        patient=patient, 
        completed=1,
        item_type='L',
        created_date__gte=one_day_ago
    )
    other_services = OtherService.objects.filter(
        patient=patient,
        completed=1,
        created_date__gte=one_day_ago
    )

    written_prescriptions = WrittenPrescriptions.objects.filter(
        patient=patient,
        created_date__gte=one_day_ago
        
    )

    context = {
        'patient': patient,
        'vital_signs': vital_signs,
        'patient_encounters': patient_encounters,
        'patient_other_details': patient_other_details,
        'followups': followups,
        'referrals_information': referrals_information,
        'administered_drugs': administered_drugs,
        'radiology_scan': radiology_scan,
        'laboratory_lab': laboratory_lab,
        'current_date': today,
        'bg_health_last_modified_by': bg_health_last_modified_by,
        'appointments': appointments,
        'other_services': other_services,
        'written_prescriptions': written_prescriptions,
    }
    
    return render(request, 'queue_operations/case_note.html', context)


@csrf_exempt
def get_filtered_case_note(request, patient_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)
        
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    try:
        # GET FILTER PARAMETERS FROM FRONTEND
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        filter_type = request.POST.get('filter_type', 'single')
        
        # CONVERT DATE TO TIMEZONE-AWARE DATETIME RANGE
        def to_datetime_range(start_date, end_date=None):
            tz = timezone.get_current_timezone()  
            start_dt = timezone.make_aware(
                datetime.combine(start_date, datetime.min.time()), tz
            )
            if end_date is None:
                # Single date: from 00:00:00 to 23:59:59
                end_dt = start_dt + timedelta(days=1)
            else:
                # Date range: from start 00:00:00 to end+1 00:00:00
                end_dt = timezone.make_aware(
                    datetime.combine(end_date, datetime.min.time()), tz
                ) + timedelta(days=1)
            return start_dt, end_dt

        #  BASE QUERYSETS - GET EVERYTHING FOR THIS PATIENT FIRST
        vital_signs_qs = DoctorWaitingList.objects.filter(patient=patient).order_by('created_date')
        encounters_qs = PatientEncounter.objects.filter(patient=patient).order_by('created_at')
        investigations_qs = RadiologyLab.objects.filter(patient=patient,completed=1).order_by('created_date')
        other_details_qs = PatientOtherDetails.objects.filter(patient=patient).order_by('created_at')
        followups_qs = PatientFollowUp.objects.filter(patient=patient).order_by('created_at')
        referrals_qs = PatientReferral.objects.filter(patient=patient).order_by('created_at')
        appointments_qs = PatientAppointment.objects.filter(patient=patient).order_by('created_date')
        other_services_qs = OtherService.objects.filter(patient=patient,completed=1).order_by('created_date')
        written_prescriptions_qs = WrittenPrescriptions.objects.filter(patient=patient).order_by('created_date')

        #  FETCH DRUGS FROM ALL STORES
        drugs_list = []
        for store_id, config in STORES_CONFIG.items():
            try:
                transaction_model = get_store_model(store_id, 'transaction')
                drugs = transaction_model.objects.filter(patient=patient,completed=1).select_related('product').order_by('created_date')
                
                for drug in drugs:
                    drug.store_id = store_id
                    drug.store_name = config['display_name']
                    drug.store_color = 'primary' if 'IPD' in config['display_name'] else 'success'
                    drugs_list.append(drug)
            except Exception as e:
                print(f"Error fetching drugs from {config['display_name']}: {str(e)}")
                continue

        # APPLY DATE FILTERING IF NOT 'ALL'
        if filter_type == 'single':
            if not start_date_str:
                return JsonResponse({'error': 'Start date is required'}, status=400)
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            start_dt, end_dt = to_datetime_range(start_date)
            
        elif filter_type == 'range':
            if not start_date_str or not end_date_str:
                return JsonResponse({'error': 'Both start and end dates are required for date range'}, status=400)
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            start_dt, end_dt = to_datetime_range(start_date, end_date)
        
        # Only filter if not 'all'
        if filter_type in ['single', 'range']:
            vital_signs_qs = vital_signs_qs.filter(created_date__gte=start_dt, created_date__lt=end_dt)
            encounters_qs = encounters_qs.filter(created_at__gte=start_dt, created_at__lt=end_dt)
            investigations_qs = investigations_qs.filter(created_date__gte=start_dt, created_date__lt=end_dt)
            other_details_qs = other_details_qs.filter(created_at__gte=start_dt, created_at__lt=end_dt)
            followups_qs = followups_qs.filter(created_at__gte=start_dt, created_at__lt=end_dt)
            referrals_qs = referrals_qs.filter(created_at__gte=start_dt, created_at__lt=end_dt)
            appointments_qs = appointments_qs.filter(created_date__gte=start_dt, created_date__lt=end_dt)
            other_services_qs = other_services_qs.filter(created_date__gte=start_dt, created_date__lt=end_dt)
            written_prescriptions_qs = written_prescriptions_qs.filter(
                created_date__gte=start_dt, 
                created_date__lt=end_dt
            )
            
            # Filter drugs list - only keep drugs within date range
            drugs_list = [d for d in drugs_list if d.created_date and start_dt <= d.created_date < end_dt]
        
        # Sort drugs newest first
        drugs_list.sort(key=lambda x: x.created_date, reverse=True)
        
        # CONVERT QUERYSETS TO LISTS FOR GROUPING
        vital_signs_list = list(vital_signs_qs)
        patient_encounters = list(encounters_qs)
        administered_drugs = drugs_list
        radiology_labs = list(investigations_qs)
        other_details = list(other_details_qs)
        followups = list(followups_qs)
        referrals = list(referrals_qs)
        appointments = list(appointments_qs)
        other_services = list(other_services_qs)
        written_prescriptions = list(written_prescriptions_qs)
        
        # GROUP ALL DATA BY DATE 
        grouped_data = {}
        
        def get_date_str(dt):
            if hasattr(dt, 'date'):
                return dt.date().strftime('%Y-%m-%d')
            return dt.strftime('%Y-%m-%d')
        
        # Process vital signs
        for vital in vital_signs_list:
            date_str = get_date_str(vital.created_date)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }
            
            vital_provider_prefix = ""
            if vital.staff and hasattr(vital.staff, 'department') and vital.staff.department:
                if vital.staff.department.department in 'Clinical, CMD':
                    vital_provider_prefix = 'Dr. '
                elif vital.staff.department.department == 'Nursing':
                    vital_provider_prefix = 'Nurse '
                elif vital.staff.department.department == 'Admin':
                    vital_provider_prefix = 'Admin, '
                else:
                    vital_provider_prefix = 'Intruder '
            
            grouped_data[date_str]['vital_signs'].append({
                'height': str(vital.height) if vital.height else None,
                'weight': str(vital.weight) if vital.weight else None,
                'bmi': str(vital.bmi) if vital.bmi else None,
                'bp': str(vital.bp) if vital.bp else None,
                'pulse': str(vital.pulse) if vital.pulse else None,
                'temperature': str(vital.temperature) if vital.temperature else None,
                'respiratory_rate': str(vital.respiratory_rate) if vital.respiratory_rate else None,
                'sp_02': str(vital.sp_02) if vital.sp_02 else None,
                'oxygen_volume': str(vital.oxygen_volume) if vital.oxygen_volume else None,
                'urine_ph': str(vital.urine_ph) if vital.urine_ph else None,
                'blood_glucose': str(vital.blood_glucose) if vital.blood_glucose else None,
                'urine_glucose': str(vital.urine_glucose) if vital.urine_glucose else None,
                'urine_protein': str(vital.urine_protein) if vital.urine_protein else None,
                'comment': str(vital.comment) if vital.comment else None,
                'staff': f"{vital_provider_prefix}{vital.staff.fullname}" if vital.staff else None,
                'created_date': vital.created_date.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Process patient encounters
        for encounter in patient_encounters:
            date_str = get_date_str(encounter.created_at)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }
            
            grouped_data[date_str]['patient_encounters'].append({
                'chief_complaint': encounter.chief_complaint or 'Not specified',
                'history_of_present_illness': encounter.history_of_present_illness or 'Not specified',
                'diagnosis': getattr(encounter, 'diagnosis', 'Not specified') or 'Not specified',
                'comments_on_diagnosis': getattr(encounter, 'comments_on_diagnosis', 'Not specified') or 'Not specified',
                'provider_name': f"Dr. {encounter.provider.fullname}" if encounter.provider else 'Unknown',
                'created_at': encounter.created_at.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Process administered drugs
        for drug in administered_drugs:
            date_str = get_date_str(drug.created_date)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }

            vital_provider_prefix = ""
            if drug.staff and hasattr(drug.staff, 'department') and drug.staff.department:
                if drug.staff.department.department in 'Clinical, CMD':
                    drug_provider_prefix = 'Dr. '
                elif drug.staff.department.department == 'Nursing':
                    drug_provider_prefix = 'Nurse '
                elif drug.staff.department.department == 'Admin':
                    drug_provider_prefix = 'Admin, '
                else:
                    drug_provider_prefix = 'Intruder '

            grouped_data[date_str]['administered_drugs'].append({
                'item': drug.item or 'Unknown',
                'UoM': drug.UoM or '',
                'route': drug.route or '',
                'dose': drug.dose or '',
                'frequency': drug.frequency or '',
                'duration': drug.duration or '',
                'quantity': str(drug.quantity) if drug.quantity else '',
                'start_date': str(drug.start_date) if drug.start_date else '',
                'provider': f"{drug_provider_prefix}{drug.staff.fullname}" if drug.staff else 'Unknown',
                'created_date': drug.created_date.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Process investigations
        for test in radiology_labs:
            date_str = get_date_str(test.created_date)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }
            
            grouped_data[date_str]['investigations'].append({
                'item': test.item or 'Unknown',
                'item_type': test.item_type or '',
                'samples': test.samples or '',
                'emergency': test.emergency or '',
                'comment': test.comment or '',
                'provider': f"Dr. {test.staff.fullname}" if test.staff else 'Unknown',
                'created_date': test.created_date.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Process other details
        for detail in other_details:
            date_str = get_date_str(detail.created_at)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }

            grouped_data[date_str]['other_details'].append({
                'condition_status': detail.condition_status or 'Not specified',
                'to_be_admitted': detail.to_be_admitted or 'Not specified',
                'assigned_doctor': detail.assigned_doctor or 'Not specified',
                'be_referred_out': detail.be_referred_out or 'Not specified',
                'provider': f"Dr. {detail.provider.fullname}" if detail.provider else 'Unknown',
                'created_at': detail.created_at.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Process followups
        for followup in followups:
            date_str = get_date_str(followup.created_at)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }
            
            grouped_data[date_str]['followups'].append({
                'summary_notes': followup.summary_notes or 'Not specified',
                'visit_type': followup.visit_type or 'Not specified',
                'treatment_progress': followup.treatment_progress or 'Not specified',
                'drugs_compliance': followup.drugs_compliance or 'Not specified',
                'provider': f"Dr. {followup.provider.fullname}" if followup.provider else 'Unknown',
                'created_at': followup.created_at.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Process referrals
        for referral in referrals:
            date_str = get_date_str(referral.created_at)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }
            
            grouped_data[date_str]['referrals'].append({
                'referring_clinic': referral.referring_clinic or 'Not specified',
                'referrer_phone': referral.referrer_phone or 'Not specified',
                'referrer_address': referral.referrer_address or 'Not specified',
                'referring_physician': referral.referring_physician or 'Not specified',
                'referrer_email': referral.referrer_email or 'Not specified',
                'clinic_referred_to': referral.clinic_referred_to or 'Not specified',
                'referred_to_phone': referral.referred_to_phone or 'Not specified',
                'referred_to_address': referral.referred_to_address or 'Not specified',
                'physician_referred_to': referral.physician_referred_to or 'Not specified',
                'referred_to_email': referral.referred_to_email or 'Not specified',
                'referred_department_clinic': referral.referred_department_clinic or 'Not specified',
                'refer_to_clinician': referral.refer_to_clinician or 'Not specified',
                'reason_for_referring': referral.reason_for_referring or 'Not specified',
                'provider': f"Dr. {referral.provider.fullname}" if referral.provider else 'Unknown',
                'created_at': referral.created_at.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Process appointments
        for appointment in appointments:
            date_str = get_date_str(appointment.created_date)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }
            
            grouped_data[date_str]['appointments'].append({
                'clinician': appointment.clinician or 'Not specified',
                'purpose': appointment.purpose or 'Not specified',
                'visit_type': appointment.visit_type or 'Not specified',
                'arrival_date': str(appointment.arrival_date) if appointment.arrival_date else 'Not specified',
                'arrival_time': str(appointment.arrival_time) if appointment.arrival_time else 'Not specified',
                'provider': f"Dr. {appointment.provider.fullname}" if appointment.provider else 'Unknown',
                'created_date': appointment.created_date.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Process other services
        for service in other_services:
            date_str = get_date_str(service.created_date)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }
            
            grouped_data[date_str]['other_services'].append({
                'purpose': service.purpose or 'Not specified',
                'provider': f"Dr. {service.provider.fullname}" if service.provider else 'Unknown',
                'created_date': service.created_date.strftime('%Y-%m-%d %H:%M'),
            })

        # Process written prescriptions
        for prescription in written_prescriptions:
            if not prescription.created_date:
                continue
            date_str = get_date_str(prescription.created_date)
            if date_str not in grouped_data:
                grouped_data[date_str] = {
                    'vital_signs': [], 'patient_encounters': [], 'administered_drugs': [],
                    'investigations': [], 'other_details': [], 'followups': [],
                    'referrals': [], 'appointments': [], 'other_services': [],
                    'written_prescriptions': [],
                }
            
            grouped_data[date_str]['written_prescriptions'].append({
                'item': prescription.item or 'Unknown',
                'quantity': prescription.quantity or 0,
                'instruction': prescription.instruction or '',
                'provider': f"Dr. {prescription.provider.fullname}" if prescription.provider else 'Unknown',
                'created_date': prescription.created_date.strftime('%Y-%m-%d %H:%M'),
            })
        
        # 8. RETURN FINAL DATA
        sorted_dates = sorted(grouped_data.keys(), reverse=True)
        
        data = {
            'grouped_by_date': grouped_data,
            'sorted_dates': sorted_dates,
        }
        
        return JsonResponse(data)
        
    except ValueError as e:
        return JsonResponse({'error': f'Invalid date format: {str(e)}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}\n{traceback.format_exc()}'}, status=500)


@csrf_exempt
def save_transcript(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    if request.method == 'POST':
        data = json.loads(request.body)
        text = data.get('text')

        if text:
            Transcript.objects.create(content=text, staff=request.user, patient=patient)
            return JsonResponse({"status": "success", "message": "Transcript saved"})
        else:
            return JsonResponse({"status": "error", "message": "No text provided"})

    return JsonResponse({"status": "error", "message": "Invalid request"})


def use_transcriptor(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    context = {
        'patient':patient
    }
    return render(request, 'queue_operations/transcriptions.html',context)


@login_required
@department_required('Clinical', 'Admin', 'CMD')
def clinical_results(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Get filter parameters from request
    filter_type = request.GET.get('filter_type', 'latest')
    selected_date = request.GET.get('selected_date', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # Get all records without any filtering first
    all_scan_results = ScanResult.objects.filter(patient=patient).order_by('-created_date')
    all_lab_results = LabResult.objects.filter(patient=patient).order_by('-created_date')
    
    # Get drugs dispensed from all stores
    all_dispensed_drugs = []
    for store_id, config in STORES_CONFIG.items():
        try:
            transaction_model = get_store_model(store_id, 'transaction')
            drugs = transaction_model.objects.filter(
                patient_id=patient_id,
                pharm_waiting_status=1
            ).select_related('product')
            
            for drug in drugs:
                drug.store_name = config['display_name']
                all_dispensed_drugs.append(drug)
        except Exception as e:
            continue
    
    all_dispensed_drugs.sort(key=lambda x: x.created_date, reverse=True)
    
    # Apply filters based on filter_type
    filtered_scan_results = all_scan_results
    filtered_lab_results = all_lab_results
    filtered_dispensed_drugs = all_dispensed_drugs
    
    if filter_type == 'single_record' and selected_date:
        try:
            filter_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
            filtered_scan_results = [result for result in all_scan_results if result.created_date.date() == filter_date]
            filtered_lab_results = [result for result in all_lab_results if result.created_date.date() == filter_date]
            filtered_dispensed_drugs = [drug for drug in all_dispensed_drugs if drug.created_date.date() == filter_date]
        except (ValueError, TypeError) as e:
            print(f"Error parsing date: {e}")
            
    elif filter_type == 'date_range' and start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            filtered_scan_results = [result for result in all_scan_results if start <= result.created_date.date() <= end]
            filtered_lab_results = [result for result in all_lab_results if start <= result.created_date.date() <= end]
            filtered_dispensed_drugs = [drug for drug in all_dispensed_drugs if start <= drug.created_date.date() <= end]
        except (ValueError, TypeError) as e:
            print(f"Error parsing date range: {e}")
    
    # Group records by date
    grouped_records = {}
    
    for result in filtered_scan_results:
        date_key = result.created_date.date()
        if date_key not in grouped_records:
            grouped_records[date_key] = {'scans': [], 'labs': [], 'drugs': []}
        grouped_records[date_key]['scans'].append(result)
    
    for result in filtered_lab_results:
        date_key = result.created_date.date()
        if date_key not in grouped_records:
            grouped_records[date_key] = {'scans': [], 'labs': [], 'drugs': []}
        grouped_records[date_key]['labs'].append(result)
    
    for drug in filtered_dispensed_drugs:
        date_key = drug.created_date.date()
        if date_key not in grouped_records:
            grouped_records[date_key] = {'scans': [], 'labs': [], 'drugs': []}
        grouped_records[date_key]['drugs'].append(drug)
    
    # Sort dates in descending order
    sorted_dates = sorted(grouped_records.keys(), reverse=True)
    sorted_grouped_records = {}
    for date_key in sorted_dates:
        sorted_grouped_records[date_key] = grouped_records[date_key]
    
    if filter_type == 'latest' and sorted_dates:
        latest_date = sorted_dates[0]
        sorted_grouped_records = {latest_date: grouped_records[latest_date]}
    
    context = {
        'patient': patient,
        'grouped_records': sorted_grouped_records,
        'filter_type': filter_type,
        'selected_date': selected_date,
        'start_date': start_date,
        'end_date': end_date,
        'print_view': False,  # For regular view
    }
    
    return render(request, 'queue_operations/clinical_results.html', context)


def print_clinical_results_pdf(request, patient_id):
    """Generate PDF for printing clinical results"""
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Get filter parameters from request
    filter_type = request.GET.get('filter_type', 'latest')
    selected_date = request.GET.get('selected_date', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # Get all records
    all_scan_results = ScanResult.objects.filter(patient=patient).order_by('-created_date')
    all_lab_results = LabResult.objects.filter(patient=patient).order_by('-created_date')
    
    # Get drugs dispensed
    all_dispensed_drugs = []
    for store_id, config in STORES_CONFIG.items():
        try:
            transaction_model = get_store_model(store_id, 'transaction')
            drugs = transaction_model.objects.filter(
                patient_id=patient_id,
                pharm_waiting_status=1
            ).select_related('product')
            
            for drug in drugs:
                drug.store_name = config['display_name']
                all_dispensed_drugs.append(drug)
        except Exception as e:
            continue
    
    all_dispensed_drugs.sort(key=lambda x: x.created_date, reverse=True)
    
    # Apply filters
    filtered_scan_results = all_scan_results
    filtered_lab_results = all_lab_results
    filtered_dispensed_drugs = all_dispensed_drugs
    
    if filter_type == 'single_record' and selected_date:
        try:
            filter_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
            filtered_scan_results = [result for result in all_scan_results if result.created_date.date() == filter_date]
            filtered_lab_results = [result for result in all_lab_results if result.created_date.date() == filter_date]
            filtered_dispensed_drugs = [drug for drug in all_dispensed_drugs if drug.created_date.date() == filter_date]
        except (ValueError, TypeError):
            pass
            
    elif filter_type == 'date_range' and start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            filtered_scan_results = [result for result in all_scan_results if start <= result.created_date.date() <= end]
            filtered_lab_results = [result for result in all_lab_results if start <= result.created_date.date() <= end]
            filtered_dispensed_drugs = [drug for drug in all_dispensed_drugs if start <= drug.created_date.date() <= end]
        except (ValueError, TypeError):
            pass
    
    # Group records by date
    grouped_records = {}
    
    for result in filtered_scan_results:
        date_key = result.created_date.date()
        if date_key not in grouped_records:
            grouped_records[date_key] = {'scans': [], 'labs': [], 'drugs': []}
        grouped_records[date_key]['scans'].append(result)
    
    for result in filtered_lab_results:
        date_key = result.created_date.date()
        if date_key not in grouped_records:
            grouped_records[date_key] = {'scans': [], 'labs': [], 'drugs': []}
        grouped_records[date_key]['labs'].append(result)
    
    for drug in filtered_dispensed_drugs:
        date_key = drug.created_date.date()
        if date_key not in grouped_records:
            grouped_records[date_key] = {'scans': [], 'labs': [], 'drugs': []}
        grouped_records[date_key]['drugs'].append(drug)
    
    # Sort dates in descending order
    sorted_dates = sorted(grouped_records.keys(), reverse=True)
    sorted_grouped_records = {}
    for date_key in sorted_dates:
        sorted_grouped_records[date_key] = grouped_records[date_key]
    
    if filter_type == 'latest' and sorted_dates:
        latest_date = sorted_dates[0]
        sorted_grouped_records = {latest_date: grouped_records[latest_date]}
    
    context = {
        'patient': patient,
        'grouped_records': sorted_grouped_records,
        'filter_type': filter_type,
        'selected_date': selected_date,
        'start_date': start_date,
        'end_date': end_date,
        'print_date': datetime.now(),
        'MEDIA_URL': settings.MEDIA_URL,
        'print_view': True,  # For print view
    }
    
    # Render HTML template for PDF
    template = get_template('queue_operations/clinical_results_print.html')
    html = template.render(context)
    
    # Create PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="clinical_results_{patient.hospital_number}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
    
    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback, encoding='UTF-8')
    
    if pisa_status.err:
        return HttpResponse(f'Error generating PDF: {pisa_status.err}', status=500)
    
    return response


@login_required
@department_required('Clinical', 'Admin', 'CMD')
def print_clinical_results_browser(request, patient_id):
    """Browser print version (backup plan)"""
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Get filter parameters from request
    filter_type = request.GET.get('filter_type', 'latest')
    selected_date = request.GET.get('selected_date', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # Get all records
    all_scan_results = ScanResult.objects.filter(patient=patient).order_by('-created_date')
    all_lab_results = LabResult.objects.filter(patient=patient).order_by('-created_date')
    
    # Get drugs dispensed
    all_dispensed_drugs = []
    for store_id, config in STORES_CONFIG.items():
        try:
            transaction_model = get_store_model(store_id, 'transaction')
            drugs = transaction_model.objects.filter(
                patient_id=patient_id,
                pharm_waiting_status=1
            ).select_related('product')
            
            for drug in drugs:
                drug.store_name = config['display_name']
                all_dispensed_drugs.append(drug)
        except Exception as e:
            continue
    
    all_dispensed_drugs.sort(key=lambda x: x.created_date, reverse=True)
    
    # Apply filters
    filtered_scan_results = all_scan_results
    filtered_lab_results = all_lab_results
    filtered_dispensed_drugs = all_dispensed_drugs
    
    if filter_type == 'single_record' and selected_date:
        try:
            filter_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
            filtered_scan_results = [result for result in all_scan_results if result.created_date.date() == filter_date]
            filtered_lab_results = [result for result in all_lab_results if result.created_date.date() == filter_date]
            filtered_dispensed_drugs = [drug for drug in all_dispensed_drugs if drug.created_date.date() == filter_date]
        except (ValueError, TypeError):
            pass
            
    elif filter_type == 'date_range' and start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            filtered_scan_results = [result for result in all_scan_results if start <= result.created_date.date() <= end]
            filtered_lab_results = [result for result in all_lab_results if start <= result.created_date.date() <= end]
            filtered_dispensed_drugs = [drug for drug in all_dispensed_drugs if start <= drug.created_date.date() <= end]
        except (ValueError, TypeError):
            pass
    
    # Group records by date
    grouped_records = {}
    
    for result in filtered_scan_results:
        date_key = result.created_date.date()
        if date_key not in grouped_records:
            grouped_records[date_key] = {'scans': [], 'labs': [], 'drugs': []}
        grouped_records[date_key]['scans'].append(result)
    
    for result in filtered_lab_results:
        date_key = result.created_date.date()
        if date_key not in grouped_records:
            grouped_records[date_key] = {'scans': [], 'labs': [], 'drugs': []}
        grouped_records[date_key]['labs'].append(result)
    
    for drug in filtered_dispensed_drugs:
        date_key = drug.created_date.date()
        if date_key not in grouped_records:
            grouped_records[date_key] = {'scans': [], 'labs': [], 'drugs': []}
        grouped_records[date_key]['drugs'].append(drug)
    
    # Sort dates in descending order
    sorted_dates = sorted(grouped_records.keys(), reverse=True)
    sorted_grouped_records = {}
    for date_key in sorted_dates:
        sorted_grouped_records[date_key] = grouped_records[date_key]
    
    if filter_type == 'latest' and sorted_dates:
        latest_date = sorted_dates[0]
        sorted_grouped_records = {latest_date: grouped_records[latest_date]}
    
    context = {
        'patient': patient,
        'grouped_records': sorted_grouped_records,
        'filter_type': filter_type,
        'selected_date': selected_date,
        'start_date': start_date,
        'end_date': end_date,
        'print_date': datetime.now(),
        'MEDIA_URL': settings.MEDIA_URL,
        'print_view': True,
    }
    
    return render(request, 'queue_operations/clinical_results_print.html', context)



def link_callback(uri, rel):
    """
    Convert HTML URIs to absolute system paths for xhtml2pdf
    """
    if uri.startswith(settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, ""))
    elif uri.startswith(settings.STATIC_URL):
        path = finders.find(uri.replace(settings.STATIC_URL, ""))
        if not path:
            path = os.path.join(settings.STATIC_ROOT, uri.replace(settings.STATIC_URL, ""))
    else:
        return uri
    
    # Ensure the file exists
    if not os.path.exists(path):
        raise Exception(f"media file '{path}' does not exist")
    
    return path

    
# Beginning of Drugs prescriptions from doctors

from importlib import import_module
import uuid

STORES_CONFIG = {
    'ipd_pharm1': {
        'name': 'IPD Pharmacy 1',
        'app_name': 'IPD_pharm',  
        'models_module': 'IPD_pharm.models',  
        'drug_model': 'Drugs',
        'transaction_model': 'IPDAdministeredDrugs',
        'display_name': 'IPD Pharmacy 1'
    },
    'ipd_pharm2': {
        'name': 'IPD Pharmacy 2',
        'app_name': 'IPD_pharm2',
        'models_module': 'IPD_pharm2.models',
        'drug_model': 'Ipd2Drugs',
        'transaction_model': 'IPD2AdministeredDrugs',
        'display_name': 'IPD Pharmacy 2'
    },
    'ipd_pharm3': {
        'name': 'IPD Pharmacy 3',
        'app_name': 'IPD_pharm3',
        'models_module': 'IPD_pharm3.models',
        'drug_model': 'Ipd3Drugs',
        'transaction_model': 'IPD3AdministeredDrugs',
        'display_name': 'IPD Pharmacy 3'
    },
    'opd_pharm1': {
        'name': 'OPD Pharmacy 1',
        'app_name': 'OPD_pharm',
        'models_module': 'OPD_pharm.models',
        'drug_model': 'OpdDrugs',
        'transaction_model': 'OPDAdministeredDrugs',
        'display_name': 'OPD Pharmacy 1'
    },
    'opd_pharm2': {
        'name': 'OPD Pharmacy 2',
        'app_name': 'OPD_pharm2',
        'models_module': 'OPD_pharm2.models',
        'drug_model': 'Opd2Drugs',
        'transaction_model': 'OPD2AdministeredDrugs',
        'display_name': 'OPD Pharmacy 2'
    },
}

def get_store_model(store_id, model_type='drug'):
    """
    Dynamically import and return model class for a store.
    """
    store_config = STORES_CONFIG.get(store_id)
    if not store_config:
        raise ValueError(f"Store {store_id} not found")
    
    # Get model name
    if model_type == 'drug':
        model_name = store_config['drug_model']
    elif model_type == 'transaction':
        model_name = store_config['transaction_model']
    else:
        raise ValueError(f"Invalid model_type: {model_type}")
    
    # Import the models module
    try:
        models_module = import_module(store_config['models_module'])
        model_class = getattr(models_module, model_name)
        return model_class
    except (ImportError, AttributeError) as e:
        # Fallback to Django's app registry
        from django.apps import apps
        try:
            return apps.get_model(store_config['app_name'], model_name)
        except LookupError:
            raise ImportError(f"Cannot import {model_name} from {store_config['models_module']}: {e}")



@login_required
def search_products(request):
    query = request.GET.get('q', '').strip()
    store_id = request.GET.get('store', 'ipd_pharm1')
    patient_id = request.GET.get('patient_id')

    if len(query) < 2:
        return JsonResponse({'results': []})

    store_config = STORES_CONFIG.get(store_id, STORES_CONFIG['ipd_pharm1'])

    # Get patient plan
    patient_plan = None
    default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()
    if patient_id:
        try:
            patient = PatientProfile.objects.select_related('plan').get(id=patient_id)
            patient_plan = patient.plan or default_plan
        except PatientProfile.DoesNotExist:
            patient_plan = default_plan
    else:
        patient_plan = default_plan

    try:
        drug_model = get_store_model(store_id, 'drug')
        products = drug_model.objects.filter(activation_status=1, product_name__icontains=query)[:10]

        # Preload tariffs for these products for this plan (1 query only)
        product_codes = [p.product_id for p in products]
        tariff_map = {
            t.product_id.lower(): t.rate
            for t in PharmacyTariff.objects.filter(product_id__in=product_codes, plan=patient_plan)
        }
        # Fallback map for Single if plan not found
        fallback_map = {}
        if patient_plan != default_plan:
            fallback_map = {
                t.product_id.lower(): t.rate
                for t in PharmacyTariff.objects.filter(product_id__in=product_codes, plan=default_plan)
            }

        results = []
        for product in products:
            key = product.product_id.lower() if product.product_id else ''
            tariff_price = tariff_map.get(key)
            if tariff_price is None:
                tariff_price = fallback_map.get(key, product.price)

            results.append({
                'id': product.id,
                'text': f"{product.product_name} ({product.minimum_UoM}) - {store_config['display_name']} - ₦{tariff_price}",
                'stock': product.stock,
                'price': str(tariff_price), # tariff price
                'uom': product.minimum_UoM,
                'original_name': product.product_name,
                'store_id': store_id,
                'store_name': store_config['display_name'],
                'product_code': product.product_id,
                'plan': patient_plan.plan if patient_plan else 'Single'
            })

        return JsonResponse({'results': results})

    except Exception as e:
        return JsonResponse({'results': [], 'error': str(e)})


@login_required
def get_stores(request):
    stores = [
        {'id': store_id, 'name': config['display_name']}
        for store_id, config in STORES_CONFIG.items()
    ]
    return JsonResponse({'stores': stores})


def get_store_model(store_id, model_type='drug'):
    from django.apps import apps
    store_config = STORES_CONFIG.get(store_id)
    if not store_config:
        raise ValueError(f"Store {store_id} not found")
    
    model_name = store_config['drug_model'] if model_type == 'drug' else store_config['transaction_model']
    app_name = store_config['app_name']
    
    return apps.get_model(app_name, model_name)


#  UPDATE FUNCTIONS 

@login_required
@csrf_exempt
def update_drug_route(request):
    if request.method == 'POST':
        unique_id = request.POST.get('unique_id')
        route = request.POST.get('route')
        patient_id = request.POST.get('patient_id')
        
        session_key = f'drug_items_{patient_id}'
        if session_key in request.session:
            items = request.session[session_key]
            
            for item in items:
                if item.get('unique_id') == unique_id:
                    item['route'] = route
                    request.session[session_key] = items
                    request.session.modified = True
                    return JsonResponse({'success': True})
        
        return JsonResponse({'success': False, 'error': 'Item not found'})


@login_required
@csrf_exempt
def update_drug_frequency(request):
    if request.method == 'POST':
        unique_id = request.POST.get('unique_id')
        freq = request.POST.get('freq')
        patient_id = request.POST.get('patient_id')
        
        session_key = f'drug_items_{patient_id}'
        if session_key in request.session:
            items = request.session[session_key]
            
            for item in items:
                if item.get('unique_id') == unique_id:
                    item['freq'] = freq
                    request.session[session_key] = items
                    request.session.modified = True
                    return JsonResponse({'success': True})
        
        return JsonResponse({'success': False, 'error': 'Item not found'})


@login_required
@csrf_exempt
def update_drug_dose(request):
    if request.method == 'POST':
        unique_id = request.POST.get('unique_id')
        dose = request.POST.get('dose')
        patient_id = request.POST.get('patient_id')
        
        session_key = f'drug_items_{patient_id}'
        if session_key in request.session:
            items = request.session[session_key]
            
            for item in items:
                if item.get('unique_id') == unique_id:
                    item['dose'] = int(dose) if dose else 0
                    request.session[session_key] = items
                    request.session.modified = True
                    return JsonResponse({'success': True})
        
        return JsonResponse({'success': False, 'error': 'Item not found'})


@login_required
@csrf_exempt
def update_drug_duration(request):
    if request.method == 'POST':
        unique_id = request.POST.get('unique_id')
        duration = request.POST.get('duration')
        patient_id = request.POST.get('patient_id')
        
        session_key = f'drug_items_{patient_id}'
        if session_key in request.session:
            items = request.session[session_key]
            
            for item in items:
                if item.get('unique_id') == unique_id:
                    item['duration'] = int(duration) if duration else 0
                    request.session[session_key] = items
                    request.session.modified = True
                    return JsonResponse({'success': True})
        
        return JsonResponse({'success': False, 'error': 'Item not found'})


@login_required
@csrf_exempt
def update_drug_notes(request):
    if request.method == 'POST':
        unique_id = request.POST.get('unique_id')
        notes = request.POST.get('notes')
        patient_id = request.POST.get('patient_id')
        
        session_key = f'drug_items_{patient_id}'
        if session_key in request.session:
            items = request.session[session_key]
            
            for item in items:
                if item.get('unique_id') == unique_id:
                    item['notes'] = notes
                    request.session[session_key] = items
                    request.session.modified = True
                    return JsonResponse({'success': True})
        
        return JsonResponse({'success': False, 'error': 'Item not found'})


@login_required
@csrf_exempt
def update_drug_start_date(request):
    if request.method == 'POST':
        unique_id = request.POST.get('unique_id')
        start_date = request.POST.get('start_date')
        patient_id = request.POST.get('patient_id')
        
        session_key = f'drug_items_{patient_id}'
        if session_key in request.session:
            items = request.session[session_key]
            
            for item in items:
                if item.get('unique_id') == unique_id:
                    item['start_date'] = start_date if start_date else ''
                    request.session[session_key] = items
                    request.session.modified = True
                    return JsonResponse({'success': True})
        
        return JsonResponse({'success': False, 'error': 'Item not found'})


@login_required
@transaction.atomic
def update_drug_quantity(request):
    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        unique_id = request.POST.get('unique_id')
        new_quantity = int(request.POST.get('quantity', 1))
        route = request.POST.get('route', '')
        freq = request.POST.get('freq', '')
        dose = request.POST.get('dose', 0)
        duration = request.POST.get('duration', 0)
        start_date = request.POST.get('start_date', '')
        notes = request.POST.get('notes', '')
        
        try:
            session_key = f'drug_items_{patient_id}'
            if session_key in request.session:
                items = request.session[session_key]
                
                for item in items:
                    if item.get('unique_id') == unique_id:
                        item['quantity'] = new_quantity
                        if route:
                            item['route'] = route
                        if freq:
                            item['freq'] = freq
                        if dose:
                            item['dose'] = int(dose) if dose else 0
                        if duration:
                            item['duration'] = int(duration) if duration else 0
                        if start_date:
                            item['start_date'] = start_date
                        if notes:
                            item['notes'] = notes
                        
                        request.session[session_key] = items
                        request.session.modified = True
                        return JsonResponse({'success': True})
                
                return JsonResponse({'success': False, 'error': 'Item not found'})
            else:
                return JsonResponse({'success': False, 'error': 'Session not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
@csrf_exempt
def update_complete_drug_item(request):
    """Save complete state of a drug item to session"""
    if request.method == 'POST':
        unique_id = request.POST.get('unique_id')
        patient_id = request.POST.get('patient_id')
        
        if not unique_id or not patient_id:
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        
        session_key = f'drug_items_{patient_id}'
        if session_key in request.session:
            items = request.session[session_key]
            
            for item in items:
                if item.get('unique_id') == unique_id:
                    item['route'] = request.POST.get('route', '')
                    item['freq'] = request.POST.get('freq', '')
                    item['dose'] = int(request.POST.get('dose', 0)) if request.POST.get('dose') else 0
                    item['duration'] = int(request.POST.get('duration', 0)) if request.POST.get('duration') else 0
                    item['start_date'] = request.POST.get('start_date', '')
                    item['notes'] = request.POST.get('notes', '')
                    item['quantity'] = int(request.POST.get('quantity', 1))
                    item['exception_bill'] = int(request.POST.get('exception_bill', 0))  # Add this
                    
                    request.session[session_key] = items
                    request.session.modified = True
                    
                    return JsonResponse({
                        'success': True, 
                        'message': 'Item state saved',
                        'item': item
                    })
            
            return JsonResponse({'success': False, 'error': 'Item not found by unique_id'})
        
        return JsonResponse({'success': False, 'error': 'Session not found'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
@csrf_exempt
def update_exception_bill_status(request):
    """Update the exception bill status for a drug item"""
    if request.method == 'POST':
        unique_id = request.POST.get('unique_id')
        patient_id = request.POST.get('patient_id')
        exception_bill = request.POST.get('exception_bill', 0)
        
        session_key = f'drug_items_{patient_id}'
        if session_key in request.session:
            items = request.session[session_key]
            
            for item in items:
                if item.get('unique_id') == unique_id:
                    item['exception_bill'] = int(exception_bill)
                    request.session[session_key] = items
                    request.session.modified = True
                    return JsonResponse({
                        'success': True,
                        'message': 'Exception status updated'
                    })
            
            return JsonResponse({'success': False, 'error': 'Item not found'})
        
        return JsonResponse({'success': False, 'error': 'Session not found'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


# REMOVE ITEM 

@login_required
def remove_drug_item(request):
    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        unique_id = request.POST.get('unique_id')
        session_key = f'drug_items_{patient_id}'
        items = request.session.get(session_key, [])
        # Keeping only items that DON'T match
        new_items = [item for item in items if str(item.get('unique_id')) != str(unique_id)]
        request.session[session_key] = new_items
        request.session.modified = True
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})


#  CLEAR SESSION 

@login_required
@transaction.atomic
def clear_drug_session(request):
    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        session_key = f'drug_items_{patient_id}'
        
        print(f"=== CLEARING SESSION ===")
        print(f"Patient ID: {patient_id}")
        print(f"Session key: {session_key}")
        
        if session_key in request.session:
            del request.session[session_key]
            request.session.modified = True
            print("Session cleared successfully")
            return JsonResponse({'success': True, 'message': 'Session cleared'})
        else:
            print("No session to clear")
            return JsonResponse({'success': True, 'message': 'No session to clear'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


#  ADD DRUG ITEM 

@login_required
@transaction.atomic
def add_drug_item(request):
    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        product_id = request.POST.get('product_id')
        store_id = request.POST.get('store_id', 'ipd_pharm1')
        quantity = int(request.POST.get('quantity') or 1)
        tariff_price = request.POST.get('price')

        try:
            store_config = STORES_CONFIG.get(store_id, STORES_CONFIG['ipd_pharm1'])
            drug_model = get_store_model(store_id, 'drug')
            product = drug_model.objects.get(id=product_id)

            is_bottle = str(product.minimum_UoM).lower() == 'bottles'
            unit_vol = int(getattr(product, 'unit', 0) or 0)

            price_to_use = Decimal(tariff_price) if tariff_price else product.price

            if quantity > product.stock:
                return JsonResponse({'success': False, 'error': f'Insufficient stock. Available: {product.stock}, Requested: {quantity}'})

            session_key = f'drug_items_{patient_id}'
            if session_key not in request.session:
                request.session[session_key] = []

            unique_id = str(uuid.uuid4())
            today = timezone.now().date().isoformat()

            request.session[session_key].append({
                'unique_id': unique_id,
                'product_id': product_id,
                'store_id': store_id,
                'store_name': store_config['display_name'],
                'store_app': store_config['app_name'],
                'quantity': quantity, # initial 1, will be auto recalculated in JS
                'price': str(price_to_use),
                'uom': product.minimum_UoM,
                'name': product.product_name,
                'stock': product.stock,
                'route': '',
                'freq': 'bd',
                'unit': unit_vol,
                'is_bottle': is_bottle,
                'dose': 1,
                'duration': 1,
                'start_date': today,
                'notes': '',
                'exception_bill': 0,
            })
            request.session.modified = True

            return JsonResponse({
                'success': True,
                'item': {
                    'unique_id': unique_id,
                    'name': product.product_name,
                    'uom': product.minimum_UoM,
                    'quantity': quantity,
                    'rate': str(price_to_use),
                    'total': str(quantity * price_to_use),
                    'id': len(request.session[session_key]) - 1,
                    'stock': product.stock,
                    'store_name': store_config['display_name'],
                    'unit': unit_vol,
                    'is_bottle': is_bottle,
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

#  GET SESSION ITEMS

@login_required
def update_drug_session_item(request):
    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        unique_id = request.POST.get('unique_id')
        
        if not patient_id or not unique_id:
            return JsonResponse({'success': False, 'error': 'Missing data'})
        
        session_key = f'drug_items_{patient_id}'
        items = request.session.get(session_key, [])
        
        for item in items:
            if item['unique_id'] == unique_id:
                # Update all editable fields
                if request.POST.get('quantity'):
                    item['quantity'] = int(request.POST.get('quantity'))
                if request.POST.get('dose'):
                    item['dose'] = int(request.POST.get('dose') or 1)
                if request.POST.get('duration'):
                    item['duration'] = int(request.POST.get('duration') or 1)
                if request.POST.get('freq') is not None:
                    item['freq'] = request.POST.get('freq')
                if request.POST.get('route') is not None:
                    item['route'] = request.POST.get('route')
                if request.POST.get('start_date'):
                    item['start_date'] = request.POST.get('start_date')
                if request.POST.get('notes') is not None:
                    item['notes'] = request.POST.get('notes')
                if request.POST.get('exception_bill') is not None:
                    item['exception_bill'] = int(request.POST.get('exception_bill'))
                break
        
        request.session[session_key] = items
        request.session.modified = True
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

@login_required
@csrf_exempt
def get_session_items(request):
    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        session_key = f'drug_items_{patient_id}'
        items = request.session.get(session_key, [])
        
        return JsonResponse({
            'success': True,
            'items': items,
            'count': len(items)
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
@department_required('Clinical', 'Admin', 'CMD')
@transaction.atomic
@csrf_exempt
def administer_drugs(request, patient_id):
    page = 'doc-request'
    patient = PatientProfile.objects.get(id=patient_id)
    from .constants import PrescriptionStatus
    requested_scans = RadiologyLab.objects.filter(item_type='R', staff=request.user, patient=patient, radiolab_waiting_status=0, completed__in=PrescriptionStatus.ACTIVE_STATUSES(), created_date__gte=timezone.now() - timedelta(hours=24))
    requested_tests = RadiologyLab.objects.filter(item_type='L', staff=request.user, patient=patient, radiolab_waiting_status=0, completed__in=PrescriptionStatus.ACTIVE_STATUSES(), created_date__gte=timezone.now() - timedelta(hours=24))

    #  FETCH DRUGS FROM ALL STORES 
    requested_drugs = []
    
    # Get drugs from all stores (for doctor's requests)
    for store_id, config in STORES_CONFIG.items():
        try:
            transaction_model = get_store_model(store_id, 'transaction')
            
            # Fetch drugs for this patient from this store
            drugs = transaction_model.objects.filter(
                staff=request.user,
                patient=patient,
                pharm_waiting_status=0,
                completed__in=PrescriptionStatus.ACTIVE_STATUSES(),
                created_date__gte=timezone.now() - timedelta(hours=24)
            ).select_related('product')
            
            # Add store information to each drug
            for drug in drugs:
                drug.store_id = store_id
                drug.store_name = config['display_name']
                drug.store_color = 'primary' if 'IPD' in config['display_name'] else 'success'
                requested_drugs.append(drug)
                
        except Exception as e:
            print(f"Error fetching drugs from {config['display_name']}: {str(e)}")
            continue
    
    # Sort by created date (newest first)
    requested_drugs.sort(key=lambda x: x.created_date, reverse=True)

    # other service taken
    visit_purposes = VisitPurpose.objects.all()

     # Antenatal week checks
    current_gestational_age_weeks = ''

    antenatal_visit = AntenatalVisit.objects.filter(
        patient=patient
    ).select_related('current_pregnancy').first()

    if antenatal_visit:
        pregnancy_instance = getattr(antenatal_visit, 'current_pregnancy', None)

        if pregnancy_instance and pregnancy_instance.last_menstrual_period:
            gest_age = pregnancy_instance.calculate_gestational_age()
            current_gestational_age_weeks = f'week {gest_age}'  
        # End Antenatal checks

    # Get existing OtherService records for this patient
    other_service = NurseWaitingList.objects.filter(patient=patient)
    other_services = other_service.filter(completed__in=PrescriptionStatus.ACTIVE_STATUSES(),created_date__gte=timezone.now() - timedelta(hours=60))


    # Get drugs dispensed fetch from all stores
    dispensed_drugs = []
    for store_id, config in STORES_CONFIG.items():
        try:
            transaction_model = get_store_model(store_id, 'transaction')
            drugs = transaction_model.objects.filter(
                patient_id=patient_id,
                pharm_waiting_status=1
            ).select_related('product')
            
            for drug in drugs:
                drug.store_name = config['display_name']
                dispensed_drugs.append(drug)
        except Exception as e:
            continue
    
    dispensed_drugs.sort(key=lambda x: x.created_date, reverse=True)

    # Get session data if exists
    session_items = request.session.get(f'drug_items_{patient_id}', [])
    
    if request.method == 'POST': 
        if 'process_casting' in request.POST:
            session_items = request.session.get(f'drug_items_{patient_id}', [])
            
            if not session_items:
                return JsonResponse({
                    'success': False,
                    'error': 'No items to process',
                    'redirect': False
                })
            
            try:
                for item_data in session_items:
                    try:
                        # Get store configuration
                        store_id = item_data.get('store_id', 'ipd_pharm1')
                        store_config = STORES_CONFIG.get(store_id, STORES_CONFIG['ipd_pharm1'])
                        
                        # Get models
                        drug_model = get_store_model(store_id, 'drug')
                        transaction_model = get_store_model(store_id, 'transaction')
                        
                        product = drug_model.objects.get(id=item_data['product_id'])
                        
                        # Check stock
                        if product.stock < item_data['quantity']:
                            raise ValueError(f"Insufficient stock for {product.product_name}")
                        
                        # Get values with proper defaults
                        dose = item_data.get('dose', 0)
                        duration = item_data.get('duration', 0)
                        notes = item_data.get('notes', '')
                        route = item_data.get('route', '')
                        frequency = item_data.get('freq', '')
                        
                        # Handle start_date 
                        start_date_raw = item_data.get('start_date', '')
                        start_date = None
                        if start_date_raw and start_date_raw != '':
                            try:
                                start_date = datetime.strptime(str(start_date_raw), '%Y-%m-%d').date()
                            except ValueError:
                                start_date = None

                        # verifying exceptional bills
                        exception_bill = item_data.get('exception_bill', 0)
                        completed = 3 if exception_bill == 1 else 0
                        # Create record
                        transaction_model.objects.create(
                            product=product,
                            item=product.product_name,
                            UoM=product.minimum_UoM,
                            route=route,
                            frequency=frequency,
                            dose=int(dose) if dose else 0,
                            duration=int(duration) if duration else 0,
                            notes=notes,
                            quantity=item_data['quantity'],
                            rate=Decimal(item_data['price']), 
                            start_date=start_date,
                            completed=completed,
                            patient=patient,
                            staff=request.user,
                            category=patient.category,
                            plan=patient.plan,
                            anc_weeks=current_gestational_age_weeks,
                        )
                        
                        # Update stock
                        product.stock -= item_data['quantity']
                        product.save()

                        # update TransactionUpdate model from Billings app
                        obj, created = TransactionUpdate.objects.get_or_create(
                            patient=patient,
                            completed=0,
                            defaults={
                                'invoice_raised': 0, 
                                'receipt_given': 0
                                    }
                        )
                        
                    except Exception as e:
                        return JsonResponse({
                            'success': False,
                            'error': str(e),
                            'redirect': False
                        })
                
                # Clearing session after successful processing
                if f'drug_items_{patient_id}' in request.session:
                    del request.session[f'drug_items_{patient_id}']
                    request.session.modified = True
                
                return JsonResponse({
                    'success': True,
                    'redirect': True,
                    'message': 'Drugs administered successfully'
                })
            
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e),
                    'redirect': False
                })
            
        elif 'service' in request.POST:
            purpose_id = request.POST.get('purpose')
            price = request.POST.get('price')
            exception_bill = request.POST.get('exception_bill', '0')
            
            # Check if it's an AJAX request
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

            try:
                # Get the selected visit purpose
                selected_purpose = VisitPurpose.objects.get(id=purpose_id)
                
                # Get category and plan
                category = patient.category if hasattr(patient, 'category') else None
                plan = patient.plan if hasattr(patient, 'plan') else None
                
                # Determine completed status
                completed = 3 if exception_bill == '1' else 0
                
                # Create the OtherService record
                NurseWaitingList.objects.create(
                    patient=patient,
                    attendant=request.user,
                    category=category,
                    plan=plan,
                    purpose=selected_purpose.purpose,
                    price=selected_purpose.price,
                    visit_type='Review',
                    waiting_status=0,
                    completed=completed,
                    exception_bill=exception_bill == '1',
                )
                
                # Update TransactionUpdate model
                obj, created = TransactionUpdate.objects.get_or_create(
                    patient=patient,
                    completed=0,
                    defaults={
                        'invoice_raised': 0, 
                        'receipt_given': 0
                    }
                )
                
                if is_ajax:
                    # Return JSON response for AJAX
                    return JsonResponse({
                        'success': True,
                        'redirect': request.path,
                        'message': f'Service {selected_purpose.purpose} added successfully'
                    })
                
                # Regular response
                if exception_bill == '1':
                    messages.success(
                        request, 
                        f'Service {selected_purpose.purpose} added as EXCEPTION (Not Billable) for {patient.first_name} {patient.surname}'
                    )
                else:
                    messages.success(
                        request, 
                        f'Service {selected_purpose.purpose} added successfully for {patient.first_name} {patient.surname}'
                    )
                
                return redirect('administer_drugs', patient_id=patient_id)
                
            except VisitPurpose.DoesNotExist:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'Selected service not found'}, status=404)
                messages.error(request, 'Selected service not found')
                return redirect('administer_drugs', patient_id=patient_id)
            except ValueError as e:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(e)}, status=400)
                messages.error(request, f'Invalid data: {str(e)}')
                return redirect('administer_drugs', patient_id=patient_id)
            except Exception as e:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(e)}, status=500)
                messages.error(request, f'An error occurred: {str(e)}')
                return redirect('administer_drugs', patient_id=patient_id)
            
        elif 'admit_patient' in request.POST:
            if request.user.pin == int(request.POST.get('pin_code')):
                admission = AdmissionTable.objects.create(
                patient=patient,
                doctor_admitted=request.user,
            )
                if admission:
                    messages.success(request,'Successfully admitted!')
                else:
                    messages.error(request,'Error Occurred! try later')
            else:
                messages.error(request,'Incorrect Pin!')
                
    return render(request, 'queue_operations/prescriptions.html', {
        'patient': patient,
        'requested_drugs':requested_drugs,
        'requested_scans':requested_scans,
        'requested_tests':requested_tests,
        'session_items': session_items,
        'page':page,
        'visit_purposes': visit_purposes,
        'other_services': other_services,
        'other_service': other_service,
        'dispensed_drugs':dispensed_drugs,
    })



@login_required
@transaction.atomic
def delete_drug_by_store(request, store_id, record_id):
    """
    Delete a drug record from a specific store
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        if store_id not in STORES_CONFIG:
            return JsonResponse({'error': 'Invalid store'}, status=400)
        
        store_config = STORES_CONFIG[store_id]
        transaction_model = get_store_model(store_id, 'transaction')
        
        print(f"\n=== DELETING FROM {store_config['display_name']} ===")
        print(f"Record ID: {record_id}")
        
        # Get the record
        try:
            record = transaction_model.objects.get(id=record_id)
        except transaction_model.DoesNotExist:
            return JsonResponse({'error': f'Record {record_id} not found in {store_config["display_name"]}'}, status=404)
        
        # Get the drug from the record's foreign key
        drug = record.product
        
        if not drug:
            return JsonResponse({'error': f'No associated drug found in {store_config["display_name"]}'}, status=404)
        
        print(f"Drug: {drug.product_name}")
        print(f"Current stock: {drug.stock}")
        print(f"Restoring: {record.quantity}")
        
        # Restore stock
        drug.stock += record.quantity
        
        if hasattr(drug, 'status'):
            drug.status = drug.stock - getattr(drug, 'low_stock_threshold', 0)
        
        drug.save()
        
        # Delete the record
        record.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Deleted "{drug.product_name}" from {store_config["display_name"]} and restored {record.quantity} unit(s)',
            'drug_name': drug.product_name,
            'restored_quantity': record.quantity
        })
        
    except Exception as e:
        import traceback
        print(f"Error: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@transaction.atomic
def edit_administered_ipd_products(request, product_id):
    try:
        export_record = IPDAdministeredDrugs.objects.get(id=product_id)
        drug = export_record.product  # from Drugs model

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - export_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and drug.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)

        #  Update Drug inventory stock
        drug.stock -= diff
        drug.status = drug.stock - drug.low_stock_threshold
        drug.save()

        #  Update export record (IPDAdministeredDrugs)
        export_record.quantity = new_quantity
        export_record.save()

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except IPDAdministeredDrugs.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    
# End of Drugs prescriptions from doctor

# Begining of Drugs prescriptions II - Write Drug Prescription (with no charges)

@login_required
@transaction.atomic
def search_inventory(request):
    query = request.GET.get('term', '')
    if not query:
        return JsonResponse([], safe=False)

    # Filter by product_name or product_id 
    all_drugs = Product.objects.filter(
        Q(product_name__icontains=query) | Q(product_id__icontains=query)
    )[:10]

    data = []
    for drug in all_drugs:
        data.append({
            'id': drug.id,
            'drug_id': drug.product_id,
            'label': f"{drug.product_name} ({drug.product_id})",
            'drug_name': drug.product_name,
        })

    return JsonResponse(data, safe=False)


@login_required
@require_POST  
@transaction.atomic
def save_prescription(request, patient_id):
    """
    Dedicated endpoint to save prescriptions independently.
    """
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    try:
        data = json.loads(request.body)
        prescriptions_list = data.get('prescriptions', [])
        
        if not prescriptions_list:
            return JsonResponse({'success': False, 'error': 'No prescription data received.'}, status=400)
        
        # list of instances to use bulk_create 
        instances = [
            WrittenPrescriptions(
                item=p['item'],
                quantity=p['quantity'],
                instruction=p['instruction'],
                patient=patient,
                provider=request.user
            )
            for p in prescriptions_list
        ]
        
        # Saving all rows in a single SQL query
        WrittenPrescriptions.objects.bulk_create(instances)
            
        return JsonResponse({'success': True})
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid format.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def download_written_prescriptions(request, patient_id):
    page = 'download_written_prescription'
    patient = get_object_or_404(PatientProfile, id=patient_id)
    prescribed_drugs = WrittenPrescriptions.objects.filter(
        patient=patient,
    ).order_by('-created_date')

    context = {
        'prescribed_drugs': prescribed_drugs,
        'page':page,
        'patient':patient,
        'date_printed': timezone.now()
    }
    return render(request, 'queue_operations/download_written_prescriptions.html', context)


def generate_written_prescription_pdf(patient, records, request):
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                           rightMargin=36, leftMargin=36,
                           topMargin=50, bottomMargin=50)
    
    styles = getSampleStyleSheet()
    story = []
    
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        wordWrap='CJK'  
    )
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        alignment=1,
        spaceAfter=30
    )
    
    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#7f8c8d'),
        alignment=1,
        spaceAfter=20
    )
    
    story.append(Paragraph("ISALU HOSPITALS LIMITED", title_style))
    story.append(Paragraph("Email: it@isaluhospitals.com | Phone: 08099902223", header_style))
    story.append(Spacer(1, 20))
    
    patient_data = [
        ['Patient Name:', patient.get_full_name(), 'Hospital #:', patient.hospital_number],
        ['Sponsor:', patient.plan.plan if patient.plan else 'N/A', 'Plan Type:', patient.category.category if patient.category else 'N/A'],
        ['Gender:', patient.gender or 'N/A', 'Age:', str(patient.get_age) if patient.get_age is not None else 'N/A'],
        ['Address:', patient.address or 'N/A', 'Phone:', patient.phone_number or 'N/A'],
    ]
    
    patient_table = Table(patient_data, colWidths=[100, 150, 100, 150])
    patient_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#2c3e50')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(patient_table)
    story.append(Spacer(1, 20))
    
    story.append(Paragraph("DRUG PRESCRIPTIONS", title_style))
    story.append(Spacer(1, 10))
    
    if records:
        # Header row
        table_data = [['S/N', 'Medications', 'Instructions']]
        
        # Wrap long text in Paragraph so it actually wraps in the cell
        for idx, record in enumerate(records, 1):
            table_data.append([
                str(idx),
                Paragraph(str(record.get('test', 'N/A')), cell_style),      # Medications 
                Paragraph(str(record.get('result', 'N/A')), cell_style),   # Instructions 
            ])
        
        result_table = Table(table_data, colWidths=[35, 180, 308])
        result_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),  
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        story.append(result_table)
        story.append(Spacer(1, 20))
        
        staff_name = "Unknown"
        if hasattr(request, 'user') and request.user.is_authenticated:
            staff_name = request.user.fullname
        
        story.append(Paragraph(f"Prepared by: {staff_name}", styles['Normal']))
        story.append(Spacer(1, 30))
        
        footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, 
                                     textColor=colors.HexColor('#95a5a6'), alignment=1)
        current_datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        story.append(Paragraph(f"Generated on: {current_datetime}", footer_style))
    
    doc.build(story)
    buffer.seek(0)
    return buffer


@csrf_exempt  
def send_written_prescription_email(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        patient_id = data.get('patient_id')
        records = data.get('records', [])
        message = data.get('message', '')
        
        if not records:
            return JsonResponse({'success': False, 'error': 'No records selected'}, status=400)
        
        patient = PatientProfile.objects.get(id=patient_id)
        
        # Generate PDF 
        pdf_buffer = generate_ipd_prescription_pdf(patient, records, request)
        
        # Build email body
        current_time = time.localtime()  
        date_str = time.strftime("%Y-%m-%d", current_time)
        time_str = time.strftime("%Y%m%d_%H%M%S", current_time)
        datetime_str = time.strftime("%Y-%m-%d %H:%M:%S", current_time)
        
        email_body = f"""
            ISALU HOSPITALS LIMITED
            Email: it@isaluhospitals.com | Phone: 08099902223

            Dear {patient.get_full_name()},

            Please find attached your drug prescriptions as requested.

            {'Additional Message: ' + message if message else ''}

            Results Summary:
            - Total Drugs: {len(records)}
            - Date Generated: {datetime_str}

            For any questions or concerns, please contact our Department of Inpatient Pharmacy.

            Best regards,
            Department of Inpatient Pharmacy
            ISALU HOSPITALS LIMITED
        """
        
        email = EmailMessage(
            subject=f'Drug Prescriptions for {patient.get_full_name()} - {date_str}',
            body=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[patient.email_address],
            reply_to=['it@isaluhospitals.com'],
        )
        
        # Attach the PDF 
        filename = f'prescriptions_{patient.hospital_number}_{time_str}.pdf'
        email.attach(filename, pdf_buffer.getvalue(), 'application/pdf')
        
        email.send()
        
        return JsonResponse({
            'success': True, 
            'message': f'Drug Prescriptions sent to {patient.email_address}'
        })
        
    except PatientProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Patient not found'}, status=404)
    except Exception as e:
        import traceback
        print("FULL ERROR:", traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
# End of Drugs prescriptions II - Write Drug Prescriptions (with no charges)



def product_search_api(request):
    query = request.GET.get('term', '')
    if not query:
        return JsonResponse([], safe=False)

    tests = VisitPurpose.objects.filter(purpose__icontains=query)[:10]

    data = []
    for test in tests:
        data.append({
            'id': test.id,
            'test_name': test.purpose,
            'price': float(test.price),
        })

    return JsonResponse(data, safe=False)


# Lab Request
@login_required
def product_search_laboratory(request):
    query = request.GET.get('term', '')
    patient_id = request.GET.get('patient_id')

    if not query:
        return JsonResponse([], safe=False)

    qs = RadioLabInventory.objects.filter(item__icontains=query, type='L')

    # filter by patient plan
    if patient_id:
        try:
            patient = PatientProfile.objects.select_related('plan').get(id=patient_id)
            if patient.plan:
                qs = qs.filter(plan=patient.plan)
            # fallback if patient has no plan or tariff not found for plan
            if not qs.exists() and patient.plan:
                # fallback to Single/Private default
                default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()
                if default_plan:
                    qs = RadioLabInventory.objects.filter(
                        item__icontains=query, type='L', plan=default_plan
                    )
        except PatientProfile.DoesNotExist:
            pass

    all_tets = qs[:10]

    data = []
    for test in all_tets:
        data.append({
            'id': test.id,
            'test_id': test.item_id,
            'label': f"{test.item} ({test.item_id}) - {test.plan.plan if test.plan else ''} - ₦{test.rate}",
            'test_name': test.item,
            'price': float(test.rate),
            'plan_id': test.plan_id, 
        })

    return JsonResponse(data, safe=False)



@login_required
@transaction.atomic
def save_lab_requests(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method"})

    try:
        data = json.loads(request.body)
        tests = data.get("tests", [])
        patient_id = data.get("patient_id")
        category_id = data.get("category_id")
        plan_id = data.get("plan_id")

        if not tests or not patient_id:
            return JsonResponse({"success": False, "error": "No tests or patient."})

        patient = PatientProfile.objects.select_related('plan').get(id=patient_id)
        actual_plan = patient.plan

        for t in tests:
            item_id = t.get("test_id") 
            exception_bill = t.get("exception_bill", False)

            tariff = RadioLabInventory.objects.filter(
                item_id=item_id,
                plan=actual_plan,
                type='L'
            ).first()

            if not tariff:
                # fallback to default
                default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()
                tariff = RadioLabInventory.objects.filter(
                    item_id=item_id, plan=default_plan, type='L'
                ).first()

            real_rate = tariff.rate if tariff else Decimal(t.get("rate", 0))

            RadiologyLab.objects.create(
                item=t["test_name"],
                item_type='L',
                rate=real_rate, 
                samples=data.get("samples",""),
                emergency=data.get("emergency",""),
                comment=data.get("comment",""),
                patient=patient,
                category_id=category_id,
                plan=actual_plan, 
                staff=request.user,
                exception_bill=exception_bill,
                completed=3 if exception_bill else 0
            )

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})
    


@login_required
@transaction.atomic
def delete_requested_test(request, product_id):
    try:
        export_record = RadiologyLab.objects.get(id=product_id)

        #  delete the exported record
        export_record.delete()

        return JsonResponse({'success': True})
    except RadiologyLab.DoesNotExist:
        return JsonResponse({'error': 'Scan not found'}, status=404)
    
# End of Lab Requests


# Scan Request
@login_required
def product_search_radiology(request):
    query = request.GET.get('term', '')
    patient_id = request.GET.get('patient_id')

    if not query:
        return JsonResponse([], safe=False)

    # Base query
    qs = RadioLabInventory.objects.filter(item__icontains=query, type='R')

    # filter by patient plan
    if patient_id:
        try:
            patient = PatientProfile.objects.select_related('plan').get(id=patient_id)
            if patient.plan:
                qs = qs.filter(plan=patient.plan)
            # fallback if patient has no plan or tariff not found for plan
            if not qs.exists() and patient.plan:
                # fallback to Single/Private default
                default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()
                if default_plan:
                    qs = RadioLabInventory.objects.filter(
                        item__icontains=query, type='R', plan=default_plan
                    )
        except PatientProfile.DoesNotExist:
            pass

    all_scans = qs[:10]

    data = []
    for test in all_scans:
        data.append({
            'id': test.id,
            'test_id': test.item_id,
            'label': f"{test.item} ({test.item_id}) - {test.plan.plan if test.plan else ''} - ₦{test.rate}",
            'test_name': test.item,
            'price': float(test.rate),
            'plan_id': test.plan_id, 
        })

    return JsonResponse(data, safe=False)

@login_required
@transaction.atomic
def save_radio_requests(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method"})

    try:
        data = json.loads(request.body)
        scans = data.get("scans", [])
        patient_id = data.get("patient_id")
        category_id = data.get("category_id")
        plan_id = data.get("plan_id")

        if not scans or not patient_id:
            return JsonResponse({"success": False, "error": "No scans or patient."})

        patient = PatientProfile.objects.select_related('plan').get(id=patient_id)

        actual_plan = patient.plan

        for t in scans:
            item_id = t.get("scan_id") 
            exception_bill = t.get("exception_bill", False)

            # get real tariff price
            tariff = RadioLabInventory.objects.filter(
                item_id=item_id,
                plan=actual_plan,
                type='R'
            ).first()

            if not tariff:
                # fallback to default
                default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()
                tariff = RadioLabInventory.objects.filter(
                    item_id=item_id, plan=default_plan, type='R'
                ).first()

            real_rate = tariff.rate if tariff else Decimal(t.get("rate", 0))

            RadiologyLab.objects.create(
                item=t["scan_name"],
                item_type='R',
                rate=real_rate, 
                samples=data.get("samples",""),
                emergency=data.get("emergency",""),
                comment=data.get("comment",""),
                patient=patient,
                category_id=category_id,
                plan=actual_plan, 
                staff=request.user,
                exception_bill=exception_bill,
                completed=3 if exception_bill else 0
            )

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


@login_required
@transaction.atomic
def delete_requested_scan(request, product_id):
    try:
        export_record = RadiologyLab.objects.get(id=product_id)

        #  delete the exported record
        export_record.delete()

        return JsonResponse({'success': True})
    except RadiologyLab.DoesNotExist:
        return JsonResponse({'error': 'Scan not found'}, status=404)
    
# End of Scan Requests

# Beginning of Other Specialist consultation request

@require_GET
@login_required
def get_visit_purpose_price(request):
    """API endpoint to get price for selected visit purpose"""
    purpose_id = request.GET.get('purpose_id')
    
    if not purpose_id:
        return JsonResponse({'error': 'Purpose ID is required'}, status=400)
    
    try:
        visit_purpose = VisitPurpose.objects.get(id=purpose_id)
        return JsonResponse({
            'success': True,
            'purpose': visit_purpose.purpose,
            'price': visit_purpose.price
        })
    except VisitPurpose.DoesNotExist:
        return JsonResponse({'error': 'Visit purpose not found'}, status=404)
    except ValueError:
        return JsonResponse({'error': 'Invalid purpose ID'}, status=400)

@login_required
def delete_other_service(request, service_id):
    """Delete Specialist Consultation record"""
    if request.method == 'POST':
        try:
            service = NurseWaitingList.objects.get(id=service_id)
            patient_id = service.patient.id
            service.delete()
            messages.success(
                request, 
                f'Service {service.purpose} deleted successfully'
            )
            return redirect('administer_drugs', patient_id=patient_id)
        except NurseWaitingList.DoesNotExist:
            messages.error(request, 'Service not found')
    return JsonResponse({'error': 'Invalid request method'}, status=405)

# End of Other specialist consultation request


# Other Services Requests
@login_required
def services_search(request):
    query = request.GET.get('term', '')
    patient_id = request.GET.get('patient_id')

    if not query:
        return JsonResponse([], safe=False)

    qs = OtherService2.objects.filter(service__icontains=query)

    # Filter by patient plan
    if patient_id:
        try:
            patient = PatientProfile.objects.select_related('plan').get(id=patient_id)
            if patient.plan:
                qs = qs.filter(plan=patient.plan)
            # Fallback if patient has no plan or tariff not found for plan
            if not qs.exists() and patient.plan:
                default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()
                if default_plan:
                    qs = OtherService2.objects.filter(
                        service__icontains=query, plan=default_plan
                    )
        except PatientProfile.DoesNotExist:
            pass

    all_services = qs[:10]

    data = []
    for service in all_services:
        data.append({
            'id': service.id,
            'service_id': service.service_id or '',
            'label': f"{service.service} ({service.service_id or 'N/A'}) - {service.plan.plan if service.plan else ''} - ₦{service.rate}",
            'service_name': service.service,
            'price': float(service.rate),
            'plan_id': service.plan_id, 
        })

    return JsonResponse(data, safe=False)

@login_required
@transaction.atomic
def save_service_requests(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method"})

    try:
        data = json.loads(request.body)
        services = data.get("services", [])
        patient_id = data.get("patient_id")
        category_id = data.get("category_id")
        plan_id = data.get("plan_id")

        if not services or not patient_id:
            return JsonResponse({"success": False, "error": "No services or patient."})

        patient = PatientProfile.objects.select_related('plan').get(id=patient_id)
        actual_plan = patient.plan

        for t in services:
            service_id = t.get("service_id") 
            exception_bill = t.get("exception_bill", False)

            tariff = OtherService2.objects.filter(
                service_id=service_id,
                plan=actual_plan
            ).first()

            if not tariff:
                # fallback to default
                default_plan = PatientPlan.objects.filter(plan__iexact='Single').first()
                tariff = OtherService2.objects.filter(
                    service_id=service_id, plan=default_plan
                ).first()

            real_rate = tariff.rate if tariff else Decimal(t.get("rate", 0))

            OtherService.objects.create(
                purpose=t["service_name"],
                price=real_rate, 
                patient=patient,
                category=patient.category,
                plan=actual_plan, 
                provider=request.user,
                exception_bill=exception_bill,
                completed=3 if exception_bill else 0
            )
            # Update TransactionUpdate model
            obj, created = TransactionUpdate.objects.get_or_create(
                patient=patient,
                completed=0,
                defaults={
                    'invoice_raised': 0, 
                    'receipt_given': 0
                }
            )

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})
    


@login_required
@transaction.atomic
def delete_requested_service(request, product_id):
    try:
        export_record = OtherServiceConsumed.objects.get(id=product_id)

        #  delete the exported record
        export_record.delete()

        return JsonResponse({'success': True})
    except OtherServiceConsumed.DoesNotExist:
        return JsonResponse({'error': 'Service not found'}, status=404)

    
# End of Other Service requesets

@login_required
@department_required('Clinical', 'Admin', 'CMD')
def mark_for_completion(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    current_waiting_entry = DoctorWaitingList.objects.filter(
        patient=patient, waiting_status = 0,
        completed = 0
    ).order_by('-created_date').first()

    if request.method == 'POST':
        if 'cancel_encounter' in request.POST:
            current_waiting_entry.encounter_status = 0
            current_waiting_entry.save()
            messages.success(request, f'Encounter for {patient.surname} {patient.first_name} successfully cancelled')
        elif 'update_encounter' in request.POST:
            if current_waiting_entry.encounter_status == 3:
                current_waiting_entry.encounter_status = 2
                current_waiting_entry.save()
                messages.success(request, f'Encounter for {patient.surname} {patient.first_name} successfully restarted')
            else:
                current_waiting_entry.encounter_status = 3
                current_waiting_entry.save()
                messages.success(request, f'Encounter for {patient.surname} {patient.first_name} successfully paused')

    context = {
        'patient':patient,
        'page':'mark_for_completion',
        'current_waiting_entry':current_waiting_entry
    }

    return render(request, 'queue_operations/mark_for_completion.html',context)


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def mark_lab_results_completed(request, patient_id):
    try:
        data = json.loads(request.body)
        user_pin = data.get('pin')
        
        # Verify PIN
        if int(user_pin) != int(request.user.pin):
            return JsonResponse({
                'success': False,
                'message': 'Invalid PIN. Please try again.'
            }, status=400)
        
        # Update LabResult
        patient = get_object_or_404(PatientProfile, id=patient_id)
        updated_count = LabResult.objects.filter(
            patient=patient
        ).update(waiting_status=1)
        
        if updated_count > 0:
            return JsonResponse({
                'success': True,
                'message': f'Lab results marked as completed successfully! ({updated_count} record(s) updated)'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'No lab results found for this patient.'
            }, status=404)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid request data.'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def mark_scan_results_completed(request, patient_id):
    try:
        data = json.loads(request.body)
        user_pin = data.get('pin')
        
        # Verify PIN
        if int(user_pin) != int(request.user.pin):
            return JsonResponse({
                'success': False,
                'message': 'Invalid PIN. Please try again.'
            }, status=400)
        
        # Update ScanResult
        patient = get_object_or_404(PatientProfile, id=patient_id)
        updated_count = ScanResult.objects.filter(
            patient=patient
        ).update(waiting_status=1)
        
        if updated_count > 0:
            return JsonResponse({
                'success': True,
                'message': f'Scan results marked as completed successfully! ({updated_count} record(s) updated)'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'No scan results found for this patient.'
            }, status=404)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid request data.'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def mark_encounter_completed(request, patient_id):
    try:
        data = json.loads(request.body)
        user_pin = data.get('pin')
        
        # Verify PIN
        if int(user_pin) != int(request.user.pin):
            return JsonResponse({
                'success': False,
                'message': 'Invalid PIN. Please try again.'
            }, status=400)
        
        # Update DoctorWaitingList
        patient = get_object_or_404(PatientProfile, id=patient_id)
        updated_count = DoctorWaitingList.objects.filter(
            patient=patient
        ).update(
            waiting_status=1,
            completed_by=request.user.fullname or request.user.username
        )
        
        if updated_count > 0:
            return JsonResponse({
                'success': True,
                'message': f'Encounter marked as completed successfully! ({updated_count} record(s) updated)'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'No encounter records found for this patient.'
            }, status=404)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid request data.'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)

def icd11_search_view(request, patient_id):
    """ searching ICD-11 codes"""
    patient = get_object_or_404(PatientProfile, id=patient_id)
    form = ICD11SearchForm(request.GET or None)
    codes = ICD11Code.objects.all()
    
    if form.is_valid():
        search_term = form.cleaned_data.get('search_term')
        category = form.cleaned_data.get('category')
        
        if search_term:
            codes = codes.filter(
                Q(title__icontains=search_term) |
                Q(code__icontains=search_term) |
                Q(description__icontains=search_term)
            )
        
        if category:
            codes = codes.filter(category=category)
    
    context = {
        'patient':patient,
        'form': form,
        'codes': codes[:50]  # Limit results
    }
    return render(request, 'queue_operations/icd11_search.html', context)

@require_http_methods(["GET"])
def icd11_autocomplete(request):
    """AJAX endpoint for ICD-11 autocomplete"""
    query = request.GET.get('q', '')
    
    if len(query) < 2:
        return JsonResponse({'results': []})
    
    codes = ICD11Code.objects.filter(
        Q(title__icontains=query) |
        Q(code__icontains=query)
    )[:10]
    
    results = []
    for code in codes:
        results.append({
            'id': code.id,
            'code': code.code,
            'title': code.title,
            'description': code.description or '',
            'category': code.category.title if code.category else ''
        })
    
    return JsonResponse({'results': results})

def add_diagnosis(request, patient_id):
    """adding diagnosis with ICD-11 code"""
    patient = get_object_or_404(PatientProfile, patient_id=patient_id)
    
    if request.method == 'POST':
        form = DiagnosisForm(request.POST)
        if form.is_valid():
            diagnosis = form.save(commit=False)
            diagnosis.patient = patient
            diagnosis.created_by = request.user
            diagnosis.save()
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False, 'errors': form.errors})
    
    form = DiagnosisForm()
    context = {
        'form': form,
        'patient': patient
    }
    return render(request, 'queue_operations/add_diagnosis.html', context)

def patient_diagnoses(request, patient_id):
    """ displaying patient diagnoses"""
    patient = get_object_or_404(PatientProfile, patient_id=patient_id)
    diagnoses = patient.diagnoses.select_related('icd11_code').all()
    
    context = {
        'patient': patient,
        'diagnoses': diagnoses
    }
    return render(request, 'queue_operations/patient_diagnoses.html', context)


def suggest_icd11_codes(request):
    """Suggest ICD-11 codes based on transcription text"""
    transcription_text = request.GET.get('text', '')
    
    if not transcription_text:
        return JsonResponse({'suggestions': []})
    
    keywords = transcription_text.lower().split()
    
    suggestions = ICD11Code.objects.filter(
        Q(title__icontains=transcription_text) |
        Q(description__icontains=transcription_text)
    )[:5]
    
    results = []
    for suggestion in suggestions:
        results.append({
            'code': suggestion.code,
            'title': suggestion.title,
            'match_score': 0.8  
        })
    
    return JsonResponse({'suggestions': results})