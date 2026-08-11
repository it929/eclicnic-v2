# views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from datetime import date, timedelta, datetime
from django.utils import timezone

from .models import AntenatalVisit, ANCDetails, Examination
from patients.models import PatientProfile, PatientAppointment
from queue_operations.models import OtherService, DoctorWaitingList, PatientEncounter
from radio_lab.models import RadiologyLab
from IPD_pharm.models import IPDAdministeredDrugs
from IPD_pharm2.models import IPD2AdministeredDrugs
from IPD_pharm3.models import IPD3AdministeredDrugs
from OPD_pharm.models import OPDAdministeredDrugs
from OPD_pharm2.models import OPD2AdministeredDrugs
from .forms import ObstetricHistoryForm, CurrentPregnancyForm, GeneralMedicalForm, TestsForm, ANCExaminationsForm, PatientAppointmentForm
from django.contrib import messages
from django.views.decorators.http import require_POST
from queue_operations.models import DoctorWaitingList
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string



def get_anc(request, patient_id):

    patient = get_object_or_404(PatientProfile, id=patient_id)
    get_week = None
    anc_weeks = DoctorWaitingList.objects.filter(patient=patient).order_by('-created_date').first()
    if anc_weeks:
        get_week = anc_weeks.anc_weeks

    # ONLY ONE antenatal exists for the first visit
    antenatal_visit, created = AntenatalVisit.objects.get_or_create(
        patient=patient
    )
    # EXISTING RECORDS (if already saved)
    obstetric_instance = getattr(antenatal_visit, "obstetric_history", None)
    pregnancy_instance = getattr(antenatal_visit, "current_pregnancy", None)
    medical_instance = getattr(antenatal_visit, "general_medical", None)
    tests_instance = getattr(antenatal_visit, "tests", None)
    if obstetric_instance is not None and pregnancy_instance is not None and medical_instance is not None and tests_instance is not None:
        return redirect("get_anc_details", patient_id=patient.id)

    # HANDLE FORM SUBMISSION
    if request.method == "POST":

        form_type = request.POST.get("form_type")

        # ---------- OBSTETRIC ----------
        if form_type == "obstetric":

            form = ObstetricHistoryForm(
                request.POST,
                instance=obstetric_instance
            )

            if form.is_valid():
                obj = form.save(commit=False)
                obj.visit = antenatal_visit
                obj.staff = request.user
                obj.save()
                messages.success(request, "Obstetric history saved successfully.")
                return redirect("get_anc", patient_id=patient.id)

        # ---------- CURRENT PREGNANCY ----------
        elif form_type == "current_pregnancy":

            form = CurrentPregnancyForm(
                request.POST,
                instance=pregnancy_instance
            )

            if form.is_valid():
                obj = form.save(commit=False)
                obj.visit = antenatal_visit
                obj.staff = request.user
                obj.save()
                messages.success(request, "Current pregnancy saved successfully.")
                return redirect("get_anc", patient_id=patient.id)

        # ---------- GENERAL MEDICAL ----------
        elif form_type == "general_medical":

            form = GeneralMedicalForm(
                request.POST,
                instance=medical_instance
            )

            if form.is_valid():
                obj = form.save(commit=False)
                obj.visit = antenatal_visit
                obj.staff = request.user
                obj.save()
                messages.success(request, "General medical saved successfully.")
                return redirect("get_anc", patient_id=patient.id)

        # ---------- LAB TESTS ----------
        elif form_type == "tests":

            form = TestsForm(
                request.POST,
                instance=tests_instance
            )

            if form.is_valid():
                obj = form.save(commit=False)
                obj.visit = antenatal_visit
                obj.staff = request.user
                obj.save()
                messages.success(request, "Lab tests saved successfully.")
                return redirect("get_anc", patient_id=patient.id)

    # LOAD FORMS (EDIT MODE IF DATA EXISTS)
    obstetric_form = ObstetricHistoryForm(instance=obstetric_instance)
    current_pregnancy_form = CurrentPregnancyForm(instance=pregnancy_instance)
    general_medical_form = GeneralMedicalForm(instance=medical_instance)
    tests_form = TestsForm(instance=tests_instance)

    context = {
        "patient": patient,
        "antenatal_visit": antenatal_visit,
        "get_week":get_week,
        "obstetric_form": obstetric_form,
        "current_pregnancy_form": current_pregnancy_form,
        "general_medical_form": general_medical_form,
        "tests_form": tests_form,

        # used by template to know completed stages
        "obstetric_done": obstetric_instance is not None,
        "pregnancy_done": pregnancy_instance is not None,
        "medical_done": medical_instance is not None,
        "tests_done": tests_instance is not None,
    }

    return render(request, "ANC/anc_form.html", context)


def get_anc_details(request, patient_id):
    page = 'antenatal'
    patient = get_object_or_404(PatientProfile, id=patient_id)
    appoint = PatientAppointmentForm()
    vital_signs_form = ANCExaminationsForm()

    # create record automatically if not existing
    anc, created = ANCDetails.objects.get_or_create(
        patient=patient
    )
    # ONLY ONE antenatal exists for the first visit
    antenatal_visit, created = AntenatalVisit.objects.get_or_create(
        patient=patient
    )
    # EXISTING RECORDS (if already saved)
    obstetric_instance = getattr(antenatal_visit, "obstetric_history", None)
    pregnancy_instance = getattr(antenatal_visit, "current_pregnancy", None)
    medical_instance = getattr(antenatal_visit, "general_medical", None)
    tests_instance = getattr(antenatal_visit, "tests", None)

    # calculate current gestational age in (weeks)
    current_gestational_age_weeks = None
    if pregnancy_instance and pregnancy_instance.last_menstrual_period:
        current_gestational_age_weeks = pregnancy_instance.calculate_gestational_age(reference_date=timezone.localdate())

    # HANDLE MODAL AJAX LOADING 
    if request.method == "GET" and request.GET.get("load_modal"):
        modal_type = request.GET.get("load_modal")        
        # Creating forms with instances
        obstetric_form = ObstetricHistoryForm(instance=obstetric_instance)
        current_pregnancy_form = CurrentPregnancyForm(instance=pregnancy_instance)
        general_medical_form = GeneralMedicalForm(instance=medical_instance)
        tests_form = TestsForm(instance=tests_instance)
        
        context = {
            'patient': patient,
            'obstetric_form': obstetric_form,
            'current_pregnancy_form': current_pregnancy_form,
            'general_medical_form': general_medical_form,
            'tests_form': tests_form,
            'obstetric_instance': obstetric_instance,
            'pregnancy_instance': pregnancy_instance,
            'medical_instance': medical_instance,
            'tests_instance': tests_instance,
            'anc': anc,
            
        }
        
        # Returning the appropriate modal HTML
        if modal_type == 'obstetric':
            html = render_to_string('ANC/modals/obstetric_modal.html', context, request=request)
            return HttpResponse(html)
        elif modal_type == 'current_pregnancy':
            html = render_to_string('ANC/modals/current_pregnancy_modal.html', context, request=request)
            return HttpResponse(html)
        elif modal_type == 'general_medical':
            html = render_to_string('ANC/modals/general_medical_modal.html', context, request=request)
            return HttpResponse(html)
        elif modal_type == 'tests':
            html = render_to_string('ANC/modals/tests_modal.html', context, request=request)
            return HttpResponse(html)
        elif modal_type == 'treatments':
            html = render_to_string('ANC/modals/treatments_modal.html', context, request=request)
            return HttpResponse(html)
        elif modal_type == 'investigations':
            html = render_to_string('ANC/modals/investigations_modal.html', context, request=request)
            return HttpResponse(html)
        
        return HttpResponse("Invalid modal type")

    # FORM SUBMISSION
    if request.method == "POST":
        if 'appoints' in request.POST:
            appoint = PatientAppointmentForm(request.POST)
            if appoint.is_valid():
                a_form = appoint.save(commit=False)
                a_form.provider = request.user
                a_form.patient = patient
                a_form.clinician = request.user.fullname
                a_form.save()
                messages.success(request, 'Appointment Created')

        elif 'anc_vital_signs' in request.POST:
            vital_signs_form = ANCExaminationsForm(request.POST)
            if vital_signs_form.is_valid():
                vitals = vital_signs_form.save(commit=False)
                vitals.staff = request.user
                vitals.patient = patient
                vitals.category = patient.category
                vitals.plan = patient.plan
                vitals.anc_weeks = 'week ' + str(current_gestational_age_weeks)
                vitals.save()
                messages.success(request,'ANC Examinations Completed')
        else:

            form_type = request.POST.get("form_type")
            
            # Check if this is an AJAX request
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

            # ---------- OBSTETRIC ----------
            if form_type == "obstetric":
                form = ObstetricHistoryForm(
                    request.POST,
                    instance=obstetric_instance
                )
                if form.is_valid():
                    obj = form.save(commit=False)
                    obj.visit = antenatal_visit
                    obj.staff = request.user
                    obj.save()
                    
                    if is_ajax:
                        return JsonResponse({
                            'success': True,
                            'message': 'Obstetric history saved successfully!',
                            'form_type': 'obstetric'
                        })
                    else:
                        messages.success(request, "Obstetric history saved successfully.")
                        return redirect("get_anc_details", patient_id=patient.id)
                else:
                    if is_ajax:
                        return JsonResponse({
                            'success': False,
                            'errors': form.errors,
                            'form_type': 'obstetric'
                        })
                    # Handle non-AJAX form errors here if needed

            # ---------- CURRENT PREGNANCY ----------
            elif form_type == "current_pregnancy":
                form = CurrentPregnancyForm(
                    request.POST,
                    instance=pregnancy_instance
                )
                if form.is_valid():
                    obj = form.save(commit=False)
                    obj.visit = antenatal_visit
                    obj.staff = request.user
                    obj.save()
                    
                    if is_ajax:
                        # Refresh to get calculated values
                        obj.refresh_from_db()
                        return JsonResponse({
                            'success': True,
                            'message': 'Current pregnancy saved successfully!',
                            'form_type': 'current_pregnancy',
                            'gestational_age_weeks': obj.gestational_age_weeks,
                            'expected_date_of_delivery': obj.expected_date_of_delivery.strftime('%Y-%m-%d') if obj.expected_date_of_delivery else ''
                        })
                    else:
                        messages.success(request, "Current pregnancy saved successfully.")
                        return redirect("get_anc_details", patient_id=patient.id)
                else:
                    if is_ajax:
                        return JsonResponse({
                            'success': False,
                            'errors': form.errors,
                            'form_type': 'current_pregnancy'
                        })

            # ---------- GENERAL MEDICAL ----------
            elif form_type == "general_medical":
                form = GeneralMedicalForm(
                    request.POST,
                    instance=medical_instance
                )
                if form.is_valid():
                    obj = form.save(commit=False)
                    obj.visit = antenatal_visit
                    obj.staff = request.user
                    obj.save()
                    
                    if is_ajax:
                        return JsonResponse({
                            'success': True,
                            'message': 'General medical saved successfully!',
                            'form_type': 'general_medical'
                        })
                    else:
                        messages.success(request, "General medical saved successfully.")
                        return redirect("get_anc_details", patient_id=patient.id)
                else:
                    if is_ajax:
                        return JsonResponse({
                            'success': False,
                            'errors': form.errors,
                            'form_type': 'general_medical'
                        })

            # ---------- LAB TESTS ----------
            elif form_type == "tests":
                form = TestsForm(
                    request.POST,
                    instance=tests_instance
                )
                if form.is_valid():
                    obj = form.save(commit=False)
                    obj.visit = antenatal_visit
                    obj.staff = request.user
                    obj.save()
                    
                    if is_ajax:
                        return JsonResponse({
                            'success': True,
                            'message': 'Lab tests saved successfully!',
                            'form_type': 'tests'
                        })
                    else:
                        messages.success(request, "Lab tests saved successfully.")
                        return redirect("get_anc_details", patient_id=patient.id)
                else:
                    if is_ajax:
                        return JsonResponse({
                            'success': False,
                            'errors': form.errors,
                            'form_type': 'tests'
                        })
            
            # If we get here and it's not AJAX, redirect to same page
            if not is_ajax:
                return redirect("get_anc_details", patient_id=patient.id)

    context = {
        'page': page,
        "patient": patient,
        "antenatal_visit": antenatal_visit,
        
        'obstetric_instance': obstetric_instance,
        'pregnancy_instance': pregnancy_instance,
        'medical_instance': medical_instance,
        'tests_instance': tests_instance,
        'anc': anc,

        'current_gestational_age_weeks': current_gestational_age_weeks,
        'today_date': timezone.localdate().isoformat(),
        'appoint':appoint,
        'vital_signs_form':vital_signs_form
    }

    return render(request, "ANC/anc_details.html", context)


# AUTO SAVE (AJAX)
@require_POST
def autosave_anc_field(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)

    anc, created = ANCDetails.objects.get_or_create(
        patient=patient
    )

    field_name = request.POST.get("field")
    value = request.POST.get("value")

    # allow only real model fields
    allowed_fields = [f.name for f in ANCDetails._meta.fields]

    if field_name not in allowed_fields:
        return JsonResponse({"status": "error", "message": "Invalid field"})

    setattr(anc, field_name, value)
    anc.staff = request.user
    anc.save()

    return JsonResponse({
        "status": "success",
        "time": anc.updated.strftime("%H:%M:%S") if hasattr(anc, 'updated') else timezone.now().strftime("%H:%M:%S")
    })



def get_unique_anc_weeks(patient_id):
    """Get unique anc_weeks values from all models in ascending order"""
    patient = PatientProfile.objects.get(id=patient_id)
    
    weeks_set = set()
    
    # Collect weeks from all models
    weeks_set.update(PatientAppointment.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True))
    weeks_set.update(RadiologyLab.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True))
    weeks_set.update(IPDAdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True))
    weeks_set.update(IPD2AdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True))
    weeks_set.update(IPD3AdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True))
    weeks_set.update(OPDAdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True))
    weeks_set.update(OPD2AdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True))
    weeks_set.update(OtherService.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True))
    weeks_set.update(DoctorWaitingList.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True))
    
    # Convert to list and sort naturally (week 1, week 2, week 10, ...)
    weeks_list = list(weeks_set)
    
    # Custom sort function to handle "week X" format
    def week_sort_key(week_str):
        # Extract number from string like "week 12" or "week 3"
        import re
        numbers = re.findall(r'\d+', week_str)
        return int(numbers[0]) if numbers else 0
    
    weeks_list.sort(key=week_sort_key)
    
    return weeks_list


def get_clinical_records(request, patient_id):
    """Get clinical records for a patient filtered by ANC week"""
    try:
        patient = get_object_or_404(PatientProfile, id=patient_id)
        
        # Get filter parameter
        selected_week = request.GET.get('week', '')
        
        print(f"Clinical Records - Patient: {patient.id}, Selected Week: '{selected_week}'")
        
        # Base querysets - start with empty ones (nothing shown until filter selected)
        appointments = PatientAppointment.objects.none()
        radiology_labs = RadiologyLab.objects.none()
        ipd_drugs = IPDAdministeredDrugs.objects.none()
        ipd2_drugs = IPD2AdministeredDrugs.objects.none()
        ipd3_drugs = IPD3AdministeredDrugs.objects.none()
        opd_drugs = OPDAdministeredDrugs.objects.none()
        opd2_drugs = OPD2AdministeredDrugs.objects.none()
        other_services = OtherService.objects.none()
        vitals = DoctorWaitingList.objects.none()
        examinations = Examination.objects.none()
        encounters = PatientEncounter.objects.none()
        
        # Only fetch data if a week is selected
        if selected_week:
            if selected_week == 'all':
                # Show all records with non-null anc_weeks
                appointments = PatientAppointment.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                radiology_labs = RadiologyLab.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                ipd_drugs = IPDAdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                ipd2_drugs = IPD2AdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                ipd3_drugs = IPD3AdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                opd_drugs = OPDAdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                opd2_drugs = OPD2AdministeredDrugs.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                other_services = OtherService.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                vitals = DoctorWaitingList.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                examinations = Examination.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')
                encounters = PatientEncounter.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='')

            else:
                # Show only records matching the selected week
                appointments = PatientAppointment.objects.filter(patient=patient, anc_weeks=selected_week)
                radiology_labs = RadiologyLab.objects.filter(patient=patient, anc_weeks=selected_week)
                ipd_drugs = IPDAdministeredDrugs.objects.filter(patient=patient, anc_weeks=selected_week)
                ipd2_drugs = IPD2AdministeredDrugs.objects.filter(patient=patient, anc_weeks=selected_week)
                ipd3_drugs = IPD3AdministeredDrugs.objects.filter(patient=patient, anc_weeks=selected_week)
                opd_drugs = OPDAdministeredDrugs.objects.filter(patient=patient, anc_weeks=selected_week)
                opd2_drugs = OPD2AdministeredDrugs.objects.filter(patient=patient, anc_weeks=selected_week)
                other_services = OtherService.objects.filter(patient=patient, anc_weeks=selected_week)
                vitals = DoctorWaitingList.objects.filter(patient=patient, anc_weeks=selected_week)
                examinations = Examination.objects.filter(patient=patient, anc_weeks=selected_week)
                encounters = PatientEncounter.objects.filter(patient=patient, anc_weeks=selected_week)
       
        # Order by date (newest first)
        appointments = appointments.order_by('-arrival_date', '-arrival_time')
        radiology_labs = radiology_labs.order_by('-created_date')
        ipd_drugs = ipd_drugs.order_by('-created_date')
        ipd2_drugs = ipd2_drugs.order_by('-created_date')
        ipd3_drugs = ipd3_drugs.order_by('-created_date')
        opd_drugs = opd_drugs.order_by('-created_date')
        opd2_drugs = opd2_drugs.order_by('-created_date')
        other_services = other_services.order_by('-created_date')
        vitals = vitals.order_by('-created_date')
        examinations = examinations.order_by('-created_date')
        encounters = encounters.order_by('-created_at')
        
        # Get unique weeks available for this patient (for the dropdown)
        unique_weeks = set()
        
        # Helper function to add weeks from any model
        def add_weeks(model_class):
            weeks = model_class.objects.filter(patient=patient).exclude(anc_weeks__isnull=True).exclude(anc_weeks='').values_list('anc_weeks', flat=True).distinct()
            unique_weeks.update(weeks)
        
        add_weeks(PatientAppointment)
        add_weeks(RadiologyLab)
        add_weeks(IPDAdministeredDrugs)
        add_weeks(IPD2AdministeredDrugs)
        add_weeks(IPD3AdministeredDrugs)
        add_weeks(OPDAdministeredDrugs)
        add_weeks(OPD2AdministeredDrugs)
        add_weeks(OtherService)
        add_weeks(DoctorWaitingList)
        add_weeks(Examination)
        add_weeks(PatientEncounter)
        
        # Converting to list and sort naturally
        weeks_list = list(unique_weeks)
        
        # sort function that extracts numbers
        def week_sort_key(week_str):
            import re
            numbers = re.findall(r'\d+', week_str)
            return int(numbers[0]) if numbers else 0
        
        weeks_list.sort(key=week_sort_key)
        print(f"Available weeks for patient: {weeks_list}")
        
        # Calculate counts
        total_records = (appointments.count() + radiology_labs.count() + ipd_drugs.count() + 
                         ipd2_drugs.count() + ipd3_drugs.count() + opd_drugs.count() + 
                         opd2_drugs.count() + other_services.count() + vitals.count() + examinations.count() + encounters.count())
        
        context = {
            'patient': patient,
            'appointments': appointments,
            'radiology_labs': radiology_labs,
            'ipd_drugs': ipd_drugs,
            'ipd2_drugs': ipd2_drugs,
            'ipd3_drugs': ipd3_drugs,
            'opd_drugs': opd_drugs,
            'opd2_drugs': opd2_drugs,
            'other_services': other_services,
            'vitals': vitals,
            'examinations': examinations,
            'encounters': encounters,
            'total_records': total_records,
            'unique_weeks': weeks_list,
            'selected_week': selected_week,
            'has_data': selected_week != ''  # Flag to know if filter was applied
        }
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render(request, 'ANC/partials/clinical_records_content.html', context)
        
        return render(request, 'ANC/partials/clinical_records_content.html', context)
        
    except Exception as e:
        print(f"ERROR in get_clinical_records: {str(e)}")
        import traceback
        traceback.print_exc()
        return HttpResponse(f"Error: {str(e)}", status=500)
    


