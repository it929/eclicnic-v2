import pandas as pd
from openpyxl import load_workbook, Workbook
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.core.files.storage import FileSystemStorage
from io import BytesIO
import os
from django.conf import settings
from .forms import PatientPlanUploadForm, PatientPlanForm, PatientProfileForm, PatientImportForm, ImageUploadForm, PatientProfileUpdateForm, ExcelImportForm, ServiceListForm, NurseWaitingListForm, PatientAppointmentForm
from .models import PatientPlan, PatientCategory, PatientProfile, PatientAppointment
from queue_operations.models import VisitPurpose, NurseWaitingList, RegFee, GetRegistrationFee, DoctorWaitingList
from Billings.models import TransactionUpdate
from myAdmins.models import Packages, PackagesData
from radio_lab.models import RadiologyLab
from queue_operations.models import OtherService
from django.db.models import F
import logging
from django.views.decorators.http import require_POST
from django.core.files.base import ContentFile
import base64
from datetime import datetime, timedelta, date
from django.utils import timezone
from django.db.models.functions import ExtractMonth, ExtractDay
from django.http import Http404, HttpResponse, JsonResponse  
today = date.today()

@login_required(login_url='login')
def download_plan_template(request):
    # Create a new workbook
    wb = Workbook()
    ws = wb.active
    
    # Add headers
    ws.append(['Plan Name', 'Code', 'Category ID'])
    
    # Add sample data
    ws.append(['Single', 'SN', '1'])
    ws.append(['Family', 'FM', '1'])
    ws.append(['Hygia', 'HY', '2'])
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=patient_plan_template.xlsx'
    wb.save(response)
    
    return response


logger = logging.getLogger(__name__)

@login_required(login_url='login')
@transaction.atomic()
def upload_patient_plans(request):
    page = 'patient-plans'
    form = PatientPlanUploadForm()
    add_plan_form = PatientPlanForm()
    errors = request.session.pop('upload_errors', [])
    if request.method == 'POST':
        if 'upload_plan' in request.POST:
            form = PatientPlanUploadForm(request.POST, request.FILES)
            if form.is_valid():
                excel_file = request.FILES['excel_file']
                overwrite = form.cleaned_data['overwrite']
                
                try:
                    # Load workbook and get active sheet
                    wb = load_workbook(excel_file, read_only=True)
                    ws = wb.active
                    
                    # Initialize counters
                    stats = {
                        'created': 0,
                        'updated': 0,
                        'skipped': 0,
                        'errors': []
                    }
                    
                    # Process rows
                    for row_num, row in enumerate(ws.iter_rows(values_only=True), start=1):
                        # Skip header row
                        if row_num == 1:
                            continue
                        
                        # Skip empty rows
                        if not any(cell for cell in row if cell is not None):
                            stats['skipped'] += 1
                            continue
                        
                        try:
                            plan_name = str(row[0]).strip() if row[0] else None  # First column - Plan Name
                            code = str(row[1]).strip() if row[1] else None       # Second column - Code
                            category_input = row[2]                              # Third column - Category (ID or name)
                            
                            # Validate required fields
                            if not all([plan_name, code, category_input]):
                                stats['skipped'] += 1
                                stats['errors'].append(f"Row {row_num}: Missing required fields")
                                continue
                            
                            # Handle category input (accepts both ID and category name)
                            try:
                                if str(category_input).isdigit():
                                    category = PatientCategory.objects.get(id=int(category_input))
                                else:
                                    category = PatientCategory.objects.get(category__iexact=str(category_input).strip())
                            except (PatientCategory.DoesNotExist, ValueError) as e:
                                stats['skipped'] += 1
                                stats['errors'].append(f"Row {row_num}: Invalid category - {str(e)}")
                                continue
                            
                            # Create or update plan
                            if overwrite:
                                plan, created = PatientPlan.objects.update_or_create(
                                    plan=plan_name,
                                    category=category,
                                    defaults={'code': code}
                                )
                            else:
                                if PatientPlan.objects.filter(plan=plan_name, category=category).exists():
                                    stats['skipped'] += 1
                                    stats['errors'].append(f"Row {row_num}: Plan already exists (use overwrite option)")
                                    continue
                                plan = PatientPlan.objects.create(
                                    plan=plan_name,
                                    code=code,
                                    category=category
                                )
                                created = True
                            
                            if created:
                                stats['created'] += 1
                            else:
                                stats['updated'] += 1
                                
                        except Exception as e:
                            stats['skipped'] += 1
                            stats['errors'].append(f"Row {row_num}: Error - {str(e)}")
                            logger.error(f"Error processing row {row_num}: {e}")
                    
                    # Prepare result message
                    result_msg = (
                        f"Processed: {stats['created']} created, "
                        f"{stats['updated']} updated, "
                        f"{stats['skipped']} skipped"
                    )
                    
                    if stats['errors']:
                        messages.warning(request, f"{result_msg} | {len(stats['errors'])} errors occurred")
                        request.session['upload_errors'] = stats['errors'][:20]  # Store first 20 errors
                    else:
                        messages.success(request, result_msg)
                    
                    return redirect('upload_plans')
                
                except Exception as e:
                    messages.error(request, f"Failed to process file: {str(e)}")
                    logger.exception("Excel upload failed")

        elif 'add_plan' in request.POST:
            add_plan_form = PatientPlanForm(request.POST)
            if request.user.pin == int(request.POST.get('pin_code')):
                if add_plan_form.is_valid():
                    add_plan_form.save()
                    messages.success(request, "Plan added successfully.")
                    return redirect('upload_plans')
                else:
                    messages.error(request, "Please correct the errors below.")
            else:
                messages.error(request, "Incorrect Pin Code")
    return render(request, 'patients/upload_patients_plan.html', {
        'form': form,
        'errors': errors,
        'page':'upload-plans',
        'add_plan_form':add_plan_form,
        'page':page,
    })


@login_required(login_url='login')
@transaction.atomic
def patient_registration(request):
    page = 'register-patients'
    
    if request.method == 'POST':
        form = PatientProfileForm(request.POST, request.FILES)
        print("POST DATA:", request.POST)
        print("FILES:", request.FILES) 
        
        if not form.is_valid():
            print("FORM ERRORS:", form.errors) 
            messages.error(request, f"Form error: {form.errors.as_text()}")

            return render(request, 'patients/registration.html', {'form': form, 'page': page})

        # Form is valid from here
        pin_code = request.POST.get('pin_code', '').strip()
        if not pin_code:
            messages.error(request, 'Pls enter your Pin Code!')
            return render(request, 'patients/registration.html', {'form': form, 'page': page})

        if str(request.user.pin) != str(pin_code):
            messages.error(request, 'Incorrect Pin Code!')
            return render(request, 'patients/registration.html', {'form': form, 'page': page})

        try:
            patient = form.save(commit=False)
            patient.created_by = request.user
            patient.save() 

            #  Registration Fee Logic 
            try:
                reg_fee = RegFee.objects.get(plan_name=patient.plan.plan)
                GetRegistrationFee.objects.create(
                    price=reg_fee.price,
                    patient=patient,
                    category=patient.category,
                    plan=patient.plan,
                    staff=request.user,
                )
            except RegFee.DoesNotExist:
                messages.warning(request, f'Patient saved but no RegFee found for plan {patient.plan}')
                # Don't fail registration for this
            except Exception as e:
                print(f"RegFee error: {e}")
                messages.warning(request, f'Patient saved but fee not captured: {e}')

            TransactionUpdate.objects.get_or_create(
                patient=patient,
                completed=0,
                defaults={'invoice_raised': 0, 'receipt_given': 0}
            )

            messages.success(request, 'Patient Successfully Registered!')
            return redirect('registered_today')

        except Exception as e:
            import traceback; traceback.print_exc()
            messages.error(request, f'Error saving patient: {str(e)}')
            return render(request, 'patients/registration.html', {'form': form, 'page': page})

    else:
        form = PatientProfileForm()
    
    return render(request, 'patients/registration.html', {'form': form, 'page': page})

def load_plans(request):
    category_id = request.GET.get('category_id')
    plans = PatientPlan.objects.filter(category_id=category_id).order_by('plan')
    return JsonResponse(list(plans.values('id', 'plan')), safe=False)


# Excel date handling helper function
def parse_excel_date(date_value):
    if date_value is None or date_value == "":
        return None
    try:
        if pd.isna(date_value):
            return None
    except:
        pass
    # Using duck typing method
    if hasattr(date_value, 'date') and callable(date_value.date):
        try:
            # Timestamp or datetime
            return date_value.date()
        except:
            pass
    if isinstance(date_value, date): 
        return date_value

    # Excel serial number e.g. 29221
    if isinstance(date_value, (int, float)) and not isinstance(date_value, bool):
        try:
            return (datetime(1899, 12, 30) + timedelta(days=float(date_value))).date()
        except Exception as e:
            print(f"Failed numeric {date_value}: {e}")
            return None

    # String: '1989-07-22' 
    if isinstance(date_value, str):
        s = date_value.strip()
        if not s:
            return None
        # Trying pandas first 
        try:
            return pd.to_datetime(s, dayfirst=False).date()
        except:
            pass
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%b-%Y', '%b-%d-%Y', '%d.%m.%Y', '%Y/%m/%d'):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue

    print(f"Debug: Unsupported - Value: {date_value}, Type: {type(date_value)}")
    return None

@login_required
@transaction.atomic
def import_patients(request):
    if request.method == 'POST':
        form = PatientImportForm(request.POST, request.FILES)
        if form.is_valid():
            fs = FileSystemStorage()
            filename = fs.save(request.FILES['excel_file'].name, request.FILES['excel_file'])
            file_path = fs.path(filename)

            try:
                df = pd.read_excel(file_path)
                df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')

                # 1. PRE-FETCH unique categories & plans - 2 queries only
                unique_cats = set(df['category'].dropna().astype(str).str.strip().unique())
                unique_plans = set(df['plan'].dropna().astype(str).str.strip().unique())

                cat_map = {}
                for cat_name in unique_cats:
                    cat_obj, _ = PatientCategory.objects.get_or_create(category=cat_name)
                    cat_map[cat_name] = cat_obj

                plan_map = {}
                for plan_name in unique_plans:
                    # find category for this plan from first occurrence
                    first_row = df[df['plan'].astype(str).str.strip() == plan_name].iloc[0]
                    cat_obj = cat_map.get(str(first_row.get('category','')).strip())
                    plan_obj, _ = PatientPlan.objects.get_or_create(
                        plan=plan_name, defaults={'category': cat_obj}
                    )
                    plan_map[plan_name] = plan_obj

                # 2. BUILD objects in memory - zero DB hit
                patients_to_create = []
                errors = []

                for index, row in df.iterrows():
                    try:
                        dob = parse_excel_date(row.get('dob'))
                        if not dob:
                            raise ValueError("dob required")

                        # skip duplicate email in file & in DB
                        email = str(row.get('email_address','')).strip() or None
                        if email and PatientProfile.objects.filter(email_address=email).exists():
                            raise ValueError(f"Email {email} already exists")

                        patients_to_create.append(PatientProfile(
                            surname=str(row['surname']).strip(),
                            first_name=str(row['first_name']).strip(),
                            other_name=str(row.get('other_name','')).strip() or None,
                            dob=dob,
                            gender=str(row.get('gender','')).strip(),
                            patient_type=str(row.get('patient_type','')).strip(),
                            phone_number=str(row.get('phone_number','')).strip(),
                            address=str(row.get('address','')).strip() or None,
                            category=cat_map.get(str(row.get('category','')).strip()),
                            plan=plan_map.get(str(row.get('plan','')).strip()),
                            email_address=email,
                            hospital_number=str(row.get('hospital_number','')).strip() or None,
                            created_by=request.user,
                            active=1
                        ))
                    except Exception as e:
                        errors.append(f"Row {index+2}: {e}")

                # 3. BULK INSERT - 1 query for all
                if patients_to_create:
                    PatientProfile.objects.bulk_create(patients_to_create, batch_size=500, ignore_conflicts=True)

                messages.success(request, f"Imported {len(patients_to_create)} patients, {len(errors)} errors")
                for err in errors[:5]:
                    messages.error(request, err)

                return redirect('patient_list')

            except Exception as e:
                import traceback; traceback.print_exc()
                messages.error(request, f"File error: {e}")
            finally:
                fs.delete(filename)
    else:
        form = PatientImportForm()

    return render(request, 'patients/import_patients.html', {'form': form})


def download_import_template(request):
    """Serve template Excel file"""
    template_path = os.path.join(settings.BASE_DIR, 'static', 'files', 'patient_import_template.xlsx')
    if os.path.exists(template_path):
        with open(template_path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type="application/vnd.ms-excel")
            response['Content-Disposition'] = 'attachment; filename=patient_import_template.xlsx'
            return response
    raise Http404

from django.utils import timezone
import datetime

@login_required(login_url='login')
def patient_registered_today(request):
    # Using localtime to match what is seen on the clock
    now = timezone.localtime(timezone.now())
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    page = 'registered-today'
    
    # Use filter range 
    patients = PatientProfile.objects.select_related('category', 'plan').filter(
        created_date__range=(start_of_day, end_of_day),
        active=1
    ).order_by('-created_date')
    
    print(f"Searching between {start_of_day} and {end_of_day}")
    print(f"Found {patients.count()} patients")

    return render(request, 'patients/patient_table.html', {
        'patients': patients,
        'report_date': now.date(),
        'page': page,
        'title': 'Patients Registered Today',
        'counts': patients.count(), 
    })

@login_required(login_url='login')
def all_patients(request):
    page = 'all-patients'
    all__patients = PatientProfile.objects.filter(active=1).only(
        'id',
        'surname',
        'other_name',
        'first_name',
        'hospital_number',
        'created_date',
        'category__category',
        'plan__plan',
        'phone_number'
    )
    # .order_by('created_date').reverse()
    return render(request, 'patients/patient_table.html', {
        'patients': all__patients,
        'title': 'All Registered Patients',
        'page':page,
        'title':'All Patients',
        'counts':all__patients.count,
    })

@login_required(login_url='login')
def single_plan_patients(request):
    page = 'single-patients'
    single__patients = PatientProfile.objects.filter(
        plan__plan__iexact='Single',active=1  # Case-insensitive match
    ).select_related(
     'plan'
    ).only(
        'id',
        'surname',
        'other_name',
        'first_name',
        'hospital_number',
        'created_date',
        'category__category',
        'plan__plan',
        'phone_number'
    ).order_by('-created_date')
    return render(request, 'patients/patient_table.html', {
        'patients': single__patients,
        'page':page,
        'title': 'Single Plan Patients',
        'counts':single__patients.count
    })

@login_required(login_url='login')
def family_plan_patients(request):
    page = 'family-patients'
    family__patients = PatientProfile.objects.filter(
        plan__plan__iexact='Family', active=1  # Case-insensitive match
    ).select_related(
        'plan'
    ).only(
        'id',
        'surname',
        'other_name',
        'first_name',
        'hospital_number',
        'created_date',
        'category__category',
        'plan__plan',
        'phone_number',
    ).order_by('-created_date')
    return render(request, 'patients/patient_table.html', {
        'patients': family__patients,
        'page':page,
        'title': 'Family Plan Patients',
        'counts':family__patients.count
    })

@login_required(login_url='login')
def anc_patients(request):
    page = 'anc-patients'
    anc__patients = PatientProfile.objects.filter(
        category__category__iexact='ANC',active=1  # Case-insensitive match
    ).select_related(
        'plan'
    ).only(
        'id',
        'surname',
        'other_name',
        'first_name',
        'hospital_number',
        'created_date',
        'category__category',
        'plan__plan',
        'phone_number'
    ).order_by('-created_date')
    return render(request, 'patients/patient_table.html', {
        'patients': anc__patients,
        'page':page,
        'title': 'ANC Patients',
        'counts':anc__patients.count
    })

@login_required(login_url='login')
def hmo_patients(request):
    page = 'hmo-patients'
    hmo__patients = PatientProfile.objects.filter(
        category__category__iexact='HMO',active=1  # Case-insensitive match
    ).select_related(
        'category'
    ).only(
        'id',
        'surname',
        'other_name',
        'first_name',
        'hospital_number',
        'created_date',
        'category__category',
        'plan__plan',
        'phone_number'
    ).order_by('-created_date')
    return render(request, 'patients/patient_table.html', {
        'patients': hmo__patients,
        'page':page,
        'title': 'HMO Patients',
        'counts':hmo__patients.count
    })

@login_required(login_url='login')
def nhis_patients(request):
    page = 'nhis-patients'
    nhis__patients = PatientProfile.objects.filter(
        category__category__iexact='NHIS',active=1  # Case-insensitive match
    ).select_related(
        'category'
    ).only(
        'id',
        'surname',
        'other_name',
        'first_name',
        'hospital_number',
        'created_date',
        'category__category',
        'plan__plan',
        'phone_number'
    ).order_by('-created_date')
    return render(request, 'patients/patient_table.html', {
        'patients': nhis__patients,
        'page':page,
        'title': 'NHIS Patients',
        'counts':nhis__patients.count
    })

@login_required(login_url='login')
def retainership_patients(request):
    page = 'retainership-patients'
    retainership__patients = PatientProfile.objects.filter(
        category__category__iexact='Retainership',active=1  # Case-insensitive match
    ).select_related(
        'category'
    ).only(
        'id',
        'surname',
        'other_name',
        'first_name',
        'hospital_number',
        'created_date',
        'category__category',
        'plan__plan',
        'phone_number'
    ).order_by('-created_date')
    return render(request, 'patients/patient_table.html', {
        'patients': retainership__patients,
        'page':page,
        'title': 'Retainership Patients',
        'counts':retainership__patients.count
    })

 
@login_required
@transaction.atomic
def patient_profile(request, key):
    page = 'patient-profile'
    referer = request.META.get('HTTP_REFERER')
    patient = get_object_or_404(PatientProfile, id=key)

    # get the last five encounters with specialist
    encounters = DoctorWaitingList.objects.filter(
        patient=patient
    ).select_related('patient').order_by('-created_date')[:5]

    # check for transaction that is within 24 hours
    verify_transaction = NurseWaitingList.objects.filter(
        created_date__gte=timezone.now() - timedelta(hours=24), 
        patient=patient
    ).select_related('patient')

    form = ImageUploadForm(instance=patient)
    unique_packages = Packages.objects.all().order_by('name')
    form1 = PatientAppointmentForm()
    queue_form = NurseWaitingListForm()

    if request.method == 'POST':
        if 'upload' in request.POST:
            avatars = request.FILES.get('avatar')
            if avatars and avatars.size > 200000:
                messages.error(request, 'File Size is too big, maximum of 200 (kb) is required')
                return redirect('patient_profile', key=patient.id)
            else:
                form = ImageUploadForm(request.POST, request.FILES, instance=patient)
                if form.is_valid():           
                    form.save()
                    messages.success(request, 'Picture Uploaded Successfully')
                    return redirect('patient_profile', key=patient.id)
                else:
                    messages.error(request, 'Error Occured, file format not supported')
                    return redirect('patient_profile', key=patient.id)

        elif 'deactivate' in request.POST:
            if request.user.pin == int(request.POST.get('pin_code') or 0):
                if patient.active == 1:
                    patient.active = 0
                    patient.deactivated_date = timezone.now()
                    patient.deactivated_by = request.user.fullname
                    patient.save()
                    messages.success(request, 'This patient was successfully deactivated')
                else:
                    patient.active = 1
                    patient.save()
                    messages.success(request, 'This patient was successfully re-activated')
                return redirect('patient_profile', key=patient.id)
            else:
                messages.error(request, 'Incorrect Pin Code')
                return redirect('patient_profile', key=patient.id)

        elif 'queue' in request.POST:
            if request.POST.get('criticality') != 'critic':
                if not verify_transaction.exists():
                    if not (request.POST.get('purpose','').lower() == 'antenatal' and patient.gender != 'Female'):
                        queue_form = NurseWaitingListForm(request.POST)
                        if queue_form.is_valid(): 
                            purpose_selected = queue_form.cleaned_data.get('purpose')
                            package_id = request.POST.get('package')

                            is_package = purpose_selected and purpose_selected.lower() == 'packages'
                            package_obj = None
                            package_items = None

                            if is_package:
                                if not package_id:
                                    messages.error(request, 'Please select a Package')
                                    return redirect('patient_profile', key=patient.id)
                                try:
                                    package_obj = Packages.objects.get(id=package_id)
                                except Packages.DoesNotExist:
                                    messages.error(request, 'Invalid Package selected')
                                    return redirect('patient_profile', key=patient.id)

                                package_items = PackagesData.objects.filter(package=package_obj)
                                if not package_items.exists():
                                    messages.error(request, f'No items found in {package_obj.name} package')
                                    return redirect('patient_profile', key=patient.id)

                            # Create NurseWaitingList
                            update_queue = queue_form.save(commit=False)
                            update_queue.patient = patient
                            update_queue.attendant = request.user
                            update_queue.category = patient.category
                            update_queue.plan = patient.plan
                            update_queue.critical_request = int(request.POST.get('criticality') or 0)

                            if is_package and package_obj:
                                update_queue.purpose = package_obj.name
                            
                            exception_bill = request.POST.get('exception_bill', False)
                            if exception_bill == 'on' or exception_bill == 'True' or exception_bill == '1':
                                update_queue.exception_bill = True
                                update_queue.completed = 3
                            else:
                                update_queue.exception_bill = False
                                update_queue.completed = 0
                            
                            update_queue.save()

                            # Package Billing
                            if is_package and package_items:
                                exception_flag = update_queue.exception_bill
                                for pkg_data in package_items:
                                    if pkg_data.type == 'r':
                                        RadiologyLab.objects.create(
                                            item=pkg_data.item,
                                            item_type='R',
                                            rate=pkg_data.rate,
                                            patient=patient,
                                            category=patient.category,
                                            plan=patient.plan,
                                            staff=request.user,
                                            exception_bill=exception_flag,
                                        )
                                    elif pkg_data.type == 'l':
                                        RadiologyLab.objects.create(
                                            item=pkg_data.item,
                                            item_type='L',
                                            rate=pkg_data.rate,
                                            patient=patient,
                                            category=patient.category,
                                            plan=patient.plan,
                                            staff=request.user,
                                            exception_bill=exception_flag,
                                        )
                                    elif pkg_data.type == 's':
                                        OtherService.objects.create(
                                            purpose=pkg_data.item,
                                            price=pkg_data.rate,
                                            patient=patient,
                                            category=patient.category,
                                            plan=patient.plan,
                                            provider=request.user,
                                            exception_bill=exception_flag,
                                        )

                                if package_obj and package_obj.name.lower() == 'antenatal':
                                    patient.packages = 1
                                    patient.save(update_fields=['packages'])
                                # else:
                                #     if any(d.item.lower() == 'antenatal' for d in package_items):
                                #         patient.packages = 1
                                #         patient.save(update_fields=['packages'])

                                messages.success(request, f'Consultation Activated! {package_obj.name} package billed: {package_items.count()} items')
                            else:
                                if update_queue.exception_bill:
                                    messages.success(request, 'Consultation Activated (EXCEPTION - Not Billable)! Patient sent to Nurse Queue')
                                else:
                                    messages.success(request, 'Consultation Activated! Patient sent to Nurse Queue')

                            # TransactionUpdate
                            obj, created = TransactionUpdate.objects.get_or_create(
                                patient=patient,
                                completed=0,
                                defaults={'invoice_raised': 0, 'receipt_given': 0}
                            )
                            return redirect('patient_profile', key=patient.id)
                        else:
                            messages.error(request, 'Error occurred! Please try again')
                            return redirect('patient_profile', key=patient.id)
                    else:
                        messages.error(request, 'Wrong Selection: Antenatal Patient must be a Female')
                        return redirect('patient_profile', key=patient.id)
                else:
                    messages.error(request, 'This Patient is still on the queue! Please contact the Billing department for clearance')
                    return redirect('patient_profile', key=patient.id)
            else:
                messages.error(request, 'Please select the level of Criticality of this request')
                return redirect('patient_profile', key=patient.id)

    context = {
        'patient':patient,
        'form':form,
        'page':page,
        'form1':form1,
        'referer':referer,
        'unique_packages':unique_packages,
        'queue_form':queue_form,
        'encounters':encounters
    }
    return render(request, 'patients/patient_profile.html', context)


def get_price(request):
    purpose = request.GET.get('purpose')
    try:
        visit_purpose = VisitPurpose.objects.get(purpose=purpose)
        return JsonResponse({'price': visit_purpose.price})
    except VisitPurpose.DoesNotExist:
        return JsonResponse({'price': 0})


@login_required(login_url='login')
@transaction.atomic()
@require_POST
def capture_webcam_image(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    image_data = request.POST.get('image_data')
    if image_data:
        try:
            # Create filename with timestamp
            timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
            filename = f'webcam_{patient_id}_{timestamp}.png'
            
            # Save the image
            patient.avatar.save(
                filename,
                ContentFile(base64.b64decode(image_data)),
                save=True
            )
            
            messages.success(request, "Patient picture uploaded successfully!")
            return JsonResponse({
                'status': 'success',
                'message': 'Picture uploaded successfully'
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error', 
                'message': str(e)
            }, status=400)
    
    return JsonResponse({
        'status': 'error',
        'message': 'No image data received'
    }, status=400)


@login_required(login_url='login')
@transaction.atomic
def edit_patient_profile(request, key):
    patient = get_object_or_404(PatientProfile, id=key)
    
    if request.method == 'POST':
        form = PatientProfileUpdateForm(request.POST, request.FILES, instance=patient)
        if request.POST.get('pin_code') != '':
            if request.user.pin == int(request.POST.get('pin_code')):
                if form.is_valid():
                    form.save()
                    
                    messages.success(request, 'Patient record updated successfully!')
                    return redirect('patient_profile', key=patient.id)  
                else:
                    messages.error(request, 'Please correct the error below.')
            else:
                messages.error(request, 'Incorrect Pin Code')
        else:
            messages.error(request, 'Pls enter your Pin Code')
    else:
        form = PatientProfileUpdateForm(instance=patient)
    
    return render(request, 'patients/edit_patient.html', {'form': form, 'patient': patient})

@login_required(login_url='login')
def deactivated_patients(request):
    patients = PatientProfile.objects.filter(
        active=0
    ).only(
        'id', 
        'surname', 
        'first_name', 
        'other_name',
        'hospital_number',
        'created_date',
        'category__category',  
        'plan__plan',
        'phone_number'          
    ).order_by('-created_date')
    context = {
        'patients':patients,
        'title':'Deactivated Patients',
        'page':'deactivated',
        'counts':patients.count
    }
    return render(request, 'patients/deactivated.html',context)


@login_required(login_url='login')
@transaction.atomic()
def import_visit_purposes(request):
    form = ExcelImportForm()
    add_service_list_form = ServiceListForm()
    
    if request.method == 'POST':
        if 'upload_service' in request.POST:
            form = ExcelImportForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    upload_purpose = request.FILES['upload_purpose']
                    # Read the Excel file directly from memory
                    df = pd.read_excel(BytesIO(upload_purpose.read()))
                    created_count = 0
                    
                    for index, row in df.iterrows():
                        purpose = row.get('purpose')
                        price = row.get('price', 0)
                        specialist_id = row.get('specialist_id', 0)  # Get specialist_id, default to 0
                        
                        obj, created = VisitPurpose.objects.update_or_create(
                            purpose=purpose,
                            defaults={
                                'price': price,
                                'specialist_id': specialist_id
                            }
                        )
                        if created:
                            created_count += 1
                    
                    messages.success(request, f'Successfully imported data. Created {created_count} new records.')            
                except Exception as e:
                    messages.error(request, f'Error: {str(e)}')
                    
        elif 'add_service' in request.POST:
            add_service_list_form = ServiceListForm(request.POST)
            if add_service_list_form.is_valid():
                add_service_list_form.save()
                messages.success(request, "New Service added to Service List.")
            else:
                messages.error(request, "Error Occurred.")

    return render(request, 'patients/appointments.html', {
        'form': form,
        'add_service_list_form': add_service_list_form, 
        'page': 'visit-purpose'
    })

def download_import_template2(request):
    """Serve template Excel file"""
    template_path = os.path.join(settings.BASE_DIR, 'static', 'files', 'service_list_import_template.xlsx')
    if os.path.exists(template_path):
        with open(template_path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type="application/vnd.ms-excel")
            response['Content-Disposition'] = 'attachment; filename=service_list__import_template.xlsx'
            return response
    raise Http404


# ------------ Front Desk appointment reviews --------
@login_required(login_url='login')
def today_appointment(request):
    today = timezone.localdate()
    appointments = PatientAppointment.objects.filter(
        arrival_date=today,
    )
    context = {
        'page':'today-appointment',
        'appointments':appointments,
        'counts':appointments.count,
        'title':"Today's Appointments"
    }
    return render(request, 'patients/appointments.html', context)

@login_required(login_url='login')
def cancelled_appointment(request):
    appointments = PatientAppointment.objects.filter(
        completed=2,
    )
    context = {
        'page':'cancelled-appointment',
        'appointments':appointments,
        'counts':appointments.count,
        'title':"Cancelled Appointments"
    }
    return render(request, 'patients/appointments.html', context)

@login_required(login_url='login')
def all_appointment(request):
    appointments = PatientAppointment.objects.all()
    for appt in appointments:
        if appt.arrival_date:
            appt.days_remaining = (appt.arrival_date - today).days
        else:
            appt.days_remaining = None
    context = {
        'page':'all-appointment',
        'appointments':appointments,
        'counts':appointments.count,
        'title':"All-time Appointments"
    }
    return render(request, 'patients/appointments.html', context)

def upcoming_appointment(request):
    today = timezone.localdate()
    page = 'upcoming-appointment'

    upcoming_appointment = PatientAppointment.objects.filter(
        arrival_date__gt=today,
        completed=0
    )
    for appt in upcoming_appointment:
        if appt.arrival_date:
            appt.days_remaining = (appt.arrival_date - today).days
        else:
            appt.days_remaining = None

    counts = upcoming_appointment.count()
    context = {
        'counts':counts,
        'page':page,
        'upcoming_appointment': upcoming_appointment,
    }
    return render(request, 'patients/appointments.html', context)

# ------------ Doctors appointment reviews --------
def today_appointments(request):
    today = timezone.localdate()
    page = 'today_appointments'
    today_appointments = PatientAppointment.objects.filter(
        arrival_date=today,provider=request.user
    )
    counts = today_appointments.count()
    context = {
        'counts':counts,
        'today_appointments': today_appointments,
        'page':page,
    }
    return render(request, 'patients/get_appointments.html', context)


def upcoming_appointments(request):
    today = timezone.localdate()
    page = 'upcoming_appointments'

    upcoming_appointments = PatientAppointment.objects.filter(
        arrival_date__gt=today,
        completed=0,provider=request.user
    )
    for appt in upcoming_appointments:
        if appt.arrival_date:
            appt.days_remaining = (appt.arrival_date - today).days
        else:
            appt.days_remaining = None

    counts = upcoming_appointments.count()
    context = {
        'counts':counts,
        'page':page,
        'upcoming_appointments': upcoming_appointments,
    }
    return render(request, 'patients/get_appointments.html', context)


def all_appointments(request):
    today = timezone.localdate()
    page = 'all_appointments'
    all_appointments = PatientAppointment.objects.filter(provider=request.user)

    for appt in all_appointments:
        if appt.arrival_date:
            appt.days_remaining = (appt.arrival_date - today).days
        else:
            appt.days_remaining = None
    counts = all_appointments.count()

    context = {
        'counts':counts,
        'page':page,
        'all_appointments': all_appointments,
    }
    return render(request, 'patients/get_appointments.html', context)

# ------------ End Doctors appointment reviews --------

@login_required(login_url='login')
@transaction.atomic()
def appointment_review_today(request,key):
    appointment = PatientAppointment.objects.get(id=key)
    page = 'appointment-today'
    if request.method == 'POST':
        if 'completed' in request.POST:
            appointment.completed = 1
            appointment.save()
            messages.success(request,f'Appointment Completed with ({appointment.patient.surname} {appointment.patient.first_name} {appointment.patient.other_name}), thanks!')
            return redirect('today_appointments')
        elif 'cancelled' in request.POST:
            appointment.completed = 2
            appointment.save()
            messages.success(request,f'Appointment Cancelled with ({appointment.patient.surname} {appointment.patient.first_name} {appointment.patient.other_name}), thanks!')
            return redirect('today_appointments')
    context = {
        'page':page,
        'appointment':appointment,
    }
    return render(request,'patients/appointments.html',context)

from ANC.forms import PatientAppointmentForm

@login_required(login_url='login')
@transaction.atomic()
def appointment_review_upcoming(request,key):
    appointment = PatientAppointment.objects.get(id=key)
    modify_appoint_form = PatientAppointmentForm(instance=appointment)
    page = 'appointment-upcoming'
    if request.method == 'POST':
        if 'modified' in request.POST:
            modify_appoint_form = PatientAppointmentForm(request.POST,instance=appointment)
            if modify_appoint_form.is_valid():
                modify_appoint_form.save()
                messages.success(request,f'Appointment with ({appointment.patient.surname} {appointment.patient.first_name} {appointment.patient.other_name}), changed!')
        elif 'cancelled' in request.POST:
            appointment.completed = 2
            appointment.save()
            messages.success(request,f'Appointment Cancelled with ({appointment.patient.surname} {appointment.patient.first_name} {appointment.patient.other_name}), thanks!')
    context = {
        'page':page,
        'appointment':appointment,
        'modify_appoint_form':modify_appoint_form,
    }
    return render(request,'patients/appointments.html',context)


@login_required(login_url='login')
@transaction.atomic()
def appointment_review_all(request,key):
    appointment = PatientAppointment.objects.get(id=key)
    page = 'appointment-all'
    context = {
        'page':page,
        'appointment':appointment,
    }
    return render(request,'patients/appointments.html',context)

# End of Appointments views

@login_required(login_url='login') 
def export_all_patient_to_excel(request):
    patients = PatientProfile.objects.all().order_by('-created_date')
    data = {
        'Name': [f"{patient.surname} {patient.first_name} {patient.other_name}" for patient in patients],
        'Gender': [patient.gender for patient in patients],
        'Parent\'s Number': [patient.phone_number for patient in patients],
        'Parent\'s Email': [patient.email_address for patient in patients],
        'Home Address': [patient.address for patient in patients],
        'Date of Birth': [patient.dob for patient in patients],
        'Category': [patient.category for patient in patients],
        'Plan': [patient.plan for patient in patients],
        'Patient Type': [patient.patient_type for patient in patients],
        'Hospital Number': [patient.hospital_number for patient in patients],
        'Insurance Policy Number': [patient.insurance_policy_number for patient in patients],    
        'Emmergency Contact Name': [patient.full_name for patient in patients],
        'Emmergency Contact Relationship': [patient.relationship_to_patient for patient in patients],
        'Emmergency Contact Phone': [patient.phone_numbers for patient in patients],
    } 
    df = pd.DataFrame(data)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="Patient-Records.xlsx"'
    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Patients')
    return response


def birthday_celebrants(request):
    birthday_patients = PatientProfile.objects.annotate(
    birth_month=ExtractMonth('dob'),birth_day=ExtractDay('dob')
    ).filter(
    birth_month=today.month, birth_day=today.day, active=1
    ).only(
        'id', 
        'surname', 
        'first_name', 
        'other_name',
        'plan__plan',
        'phone_number',
        'dob'         
    )
    context = {
        'birthday_patients':birthday_patients,
        'title': "Today's Birthday Celebrants",
        'counts':birthday_patients.count()
    }
    return render(request, 'patients/birth_day_list.html', context)



from haystack.query import SearchQuerySet
from django.http import JsonResponse
from .forms import PatientSearchForm
from haystack.query import SQ

@login_required(login_url='login') 
def patient_search(request):
    if request.method == 'GET':
        form = PatientSearchForm(request.GET)
        if form.is_valid():
            search_term = form.cleaned_data['search_term']
            category = request.GET.get('category')
            
            patients = SearchQuerySet().models(PatientProfile).filter(active=1)
            
            if len(search_term) >= 2:
                # Primary: Autocomplete
                patients = patients.filter(autocomplete=search_term)
                
                # Fallback: Explicit fuzzy on surname and first_name
                if patients.count() == 0 and len(search_term) >= 3:
                    # This syntax definitely works with Whoosh
                    fuzzy_surname = f"{search_term}~"  # Add ~ for fuzzy
                    fuzzy_first = f"{search_term}~"
                    
                    patients = SearchQuerySet().models(PatientProfile).filter(
                        active=1
                    ).filter(
                        SQ(surname__contains=fuzzy_surname) | 
                        SQ(first_name__contains=fuzzy_first)
                    )
            
            # Apply category filter
            if category and category != "set" and category != "":
                patients = patients.filter(category=category)
            
            patients = patients[:10]
            
            results = []
            for patient in patients:
                obj = patient.object
                results.append({
                    'id': obj.id,
                    'full_name': f"{obj.surname} {obj.first_name} {obj.other_name or ''}".strip(),
                    'hospital_number': obj.hospital_number,
                    'phone_number': obj.phone_number,
                    'key': obj.id,
                })
            
            print(f"Search term: '{search_term}', Category: {category}, Results: {len(results)}")
            
            return JsonResponse({'results': results})
    
    return JsonResponse({'results': []})


@login_required(login_url='login') 
def search_page(request):
    return render(request, 'patients/patient_search.html')
