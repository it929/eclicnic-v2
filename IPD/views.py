from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from openpyxl import load_workbook
from django.utils import timezone
from django.db import transaction
from .models import Ward, Bed, BedAllocation, AdmissionTable, DrugPrescription, DrugAdministration, AdmissionFee
from patients.models import PatientProfile
from Billings.models import TransactionUpdate
from django.db import transaction, OperationalError, InterfaceError
from django.views.decorators.csrf import csrf_exempt
import json
from django.core.paginator import Paginator
from datetime import timedelta, datetime
import logging

logger = logging.getLogger(__name__)

# Bed Space managements

# BED VIEWS
def bed_page(request):
    beds = Bed.objects.all().select_related('ward').order_by('-id')
    wards = Ward.objects.all()
    return render(request, 'IPD/bed_ajax.html', {
        'beds': beds,
        'wards': wards,
        'page':'create-bed'
    })


# CREATE / UPDATE BED
def create_bed_ajax(request):
    if request.method == 'POST':
        bed_name = request.POST.get('bed_name', '').strip()
        ward_id = request.POST.get('ward')
        
        if not bed_name or not ward_id:
            return JsonResponse({'status': 'error', 'message': 'Bed name and ward are required'}, status=400)
        
        try:
            ward = Ward.objects.get(id=ward_id)
            
            # Check if bed already exists in this ward
            if Bed.objects.filter(ward=ward, bed_name__iexact=bed_name).exists():
                return JsonResponse({'status': 'error', 'message': 'Bed already exists in this ward'}, status=400)
            
            # Create new bed
            Bed.objects.create(
                ward=ward,
                bed_name=bed_name,
                bed_status=request.POST.get('bed_status', 0),
                is_occupied=request.POST.get('is_occupied') == 'true'
            )
            return JsonResponse({'status': 'success'})
        except Ward.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Ward not found'}, status=400)


def update_bed_ajax(request, id):
    if request.method == 'POST':
        bed = get_object_or_404(Bed, id=id)
        bed_name = request.POST.get('bed_name', '').strip()
        ward_id = request.POST.get('ward')
        
        if not bed_name or not ward_id:
            return JsonResponse({'status': 'error', 'message': 'Bed name and ward are required'}, status=400)
        
        try:
            ward = Ward.objects.get(id=ward_id)
            
            # Check if bed name already exists in this ward (excluding current bed)
            if Bed.objects.filter(ward=ward, bed_name__iexact=bed_name).exclude(id=id).exists():
                return JsonResponse({'status': 'error', 'message': 'Bed already exists in this ward'}, status=400)
            
            bed.ward = ward
            bed.bed_name = bed_name
            bed.bed_status = request.POST.get('bed_status', 0)
            bed.is_occupied = request.POST.get('is_occupied') == 'true'
            bed.save()
            
            return JsonResponse({'status': 'updated'})
        except Ward.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Ward not found'}, status=400)


# DELETE BED
def delete_bed_ajax(request, id):
    bed = get_object_or_404(Bed, id=id)
    bed.delete()
    return JsonResponse({'status': 'deleted'})


# BULK EXCEL UPLOAD FOR BEDS
def upload_bed_excel_ajax(request):
    if 'excel_file' not in request.FILES:
        return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)
    
    excel = request.FILES['excel_file']
    wb = load_workbook(excel)
    sheet = wb.active
    
    created_count = 0
    updated_count = 0
    skipped_count = 0
    errors = []
    
    for row_index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not row or len(row) < 2:
            continue
            
        # Get values from Excel
        ward_name_input = str(row[0]).strip() if row[0] else None
        bed_name_input = str(row[1]).strip() if row[1] else None
        
        if not ward_name_input or not bed_name_input:
            errors.append(f"Row {row_index}: Missing ward name or bed name")
            continue
        
        try:
            # Case-insensitive lookup for existing ward
            ward = None
            try:
                # Exact match first
                ward = Ward.objects.get(ward_name__iexact=ward_name_input)
            except Ward.DoesNotExist:
                ward = Ward.objects.create(ward_name=ward_name_input)
            
            # ensures consistent naming
            """
            # Normalize for lookup (lowercase, strip)
            normalized_name = ward_name_input.lower().strip()
            
            # Try to find existing ward with case-insensitive match
            existing_wards = Ward.objects.filter(ward_name__iexact=normalized_name)
            
            if existing_wards.exists():
                # Use the existing ward (preserve original case)
                ward = existing_wards.first()
            else:
                # Create new ward with the input case
                ward = Ward.objects.create(ward_name=ward_name_input)
            """
            
            # create or update the bed
            bed_name_normalized = bed_name_input.strip()
            
            bed, created = Bed.objects.get_or_create(
                ward=ward,
                bed_name__iexact=bed_name_normalized,  # Case-insensitive bed name check
                defaults={
                    'bed_name': bed_name_input,  # Keep original case
                    'bed_status': int(row[2]) if len(row) > 2 and row[2] is not None else 0,
                    'is_occupied': bool(row[3]) if len(row) > 3 and row[3] is not None else False
                }
            )
            
            if created:
                created_count += 1
            else:
                # Update existing bed
                bed.bed_status = int(row[2]) if len(row) > 2 and row[2] is not None else bed.bed_status
                bed.is_occupied = bool(row[3]) if len(row) > 3 and row[3] is not None else bed.is_occupied
                bed.save()
                updated_count += 1
                
        except Exception as e:
            errors.append(f"Row {row_index}: {str(e)}")
            continue
    
    response_data = {
        'status': 'success',
        'message': f'Upload complete. Created: {created_count}, Updated: {updated_count}, Skipped/Errors: {len(errors)}'
    }
    
    if errors:
        response_data['errors'] = errors[:10]  # Show first 10 errors
    
    return JsonResponse(response_data)

# Bed Allocation

def allocate_bed_page(request, patient_id):
    """Main page for bed allocation for a specific patient"""
    try:
        patient = PatientProfile.objects.get(id=patient_id)
        
        current_allocation = BedAllocation.objects.filter(
            patient=patient,
            is_active=True
        ).select_related('bed', 'ward').first()
        
        wards = Ward.objects.all()
        
        return render(request, 'IPD/allocate_bed.html', {
            'patient': patient,
            'current_allocation': current_allocation,
            'wards': wards,
        })
    except PatientProfile.DoesNotExist:
        return render(request, 'IPD/error.html', {
            'error_message': 'Patient not found'
        })

def get_available_beds(request):
    """Get available beds for a specific ward (AJAX)"""
    ward_id = request.GET.get('ward_id')
    
    if ward_id:
        available_beds = Bed.objects.filter(
            ward_id=ward_id,
            bed_status=0,
            is_occupied=False
        ).order_by('bed_name')
    else:
        available_beds = Bed.objects.none()
    
    beds_data = [{
        'id': bed.id,
        'name': bed.bed_name,
        'ward': bed.ward.ward_name,
    } for bed in available_beds]
    
    return JsonResponse({'beds': beds_data})


@csrf_exempt
def allocate_bed_to_patient(request, patient_id):
    """Allocate bed to patient (Database Agnostic)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        bed_id = data.get('bed_id')
        pin_code = data.get('pin_code')  # Get PIN from request
        
        if not bed_id:
            return JsonResponse({'success': False, 'message': 'Bed ID is required'}, status=400)
        
        # Verify PIN
        if not pin_code:
            return JsonResponse({'success': False, 'message': 'PIN code is required for security verification'}, status=400)
        
        try:
            pin_code = int(pin_code)
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'message': 'Invalid PIN format'}, status=400)
        
        if request.user.pin != pin_code:
            return JsonResponse({'success': False, 'message': 'Incorrect PIN. Access denied.'}, status=403)
        
        with transaction.atomic():
            patient = PatientProfile.objects.select_for_update().get(id=patient_id)
            bed = Bed.objects.select_for_update().get(id=bed_id)
            
            if bed.bed_status != 0 or bed.is_occupied:
                return JsonResponse({'success': False, 'message': f'Bed {bed.bed_name} is unavailable'}, status=400)
            
            if BedAllocation.objects.filter(patient=patient, is_active=True).exists():
                return JsonResponse({'success': False, 'message': 'Patient already has an active allocation'}, status=400)
            
            # Admission Record logic
            admission_record = AdmissionTable.objects.filter(
                patient=patient,
                doctor_discharge_status=0
            ).order_by('-doctor_admit_date').first()

            nurse_name = request.user.fullname
            
            if not admission_record:
                admission_record = AdmissionTable.objects.create(
                    patient=patient,
                    doctor_admitted=request.user,
                    doctor_admit_date=timezone.now(),
                    nurse_admitted=nurse_name,
                    nurse_admit_status=1,
                    nurse_admit_date=timezone.now()
                )
            else:
                admission_record.nurse_admitted = nurse_name
                admission_record.nurse_admit_status = 1
                admission_record.nurse_admit_date = timezone.now()
                admission_record.save(update_fields=['nurse_admitted', 'nurse_admit_status', 'nurse_admit_date'])
            
            # Update Bed
            bed.bed_status = 1
            bed.is_occupied = True
            bed.save()
            
            # Create Allocation
            allocation = BedAllocation.objects.create(
                ward=bed.ward, bed=bed, staff=request.user,
                patient=patient, admission_record=admission_record, is_active=True
            )
            
            # Fees & Billing
            ward_price = bed.ward.price if bed.ward else 0
            admission_fee = AdmissionFee.objects.create(
                ward=bed.ward, price=ward_price, num_of_days=0, completed=0,
                staff=request.user, patient=patient, admission_record=admission_record,
                created_date=timezone.now()
            )
            
            # Transaction update
            TransactionUpdate.objects.get_or_create(
                patient=patient, completed=0,
                defaults={'invoice_raised': 0, 'receipt_given': 0}
            )

            return JsonResponse({
                'success': True,
                'message': f'Bed {bed.bed_name} allocated successfully',
                'redirect_url': f'/allocate-bed/{patient_id}/'
            })
            
    except (PatientProfile.DoesNotExist, Bed.DoesNotExist) as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=404)
    except OperationalError:
        return JsonResponse({'success': False, 'message': 'Database connection error. Please try again.'}, status=500)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'}, status=500)


@csrf_exempt
def discharge_patient(request, patient_id):
    """Discharge patient"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=405)

    try:
        data = json.loads(request.body) if request.body else {}
        pin_code = data.get('pin_code')  # Get PIN from request
        
        # Verify PIN
        if not pin_code:
            return JsonResponse({'success': False, 'message': 'PIN code is required for security verification'}, status=400)
        
        try:
            pin_code = int(pin_code)
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'message': 'Invalid PIN format'}, status=400)
        
        if request.user.pin != pin_code:
            return JsonResponse({'success': False, 'message': 'Incorrect PIN. Access denied.'}, status=403)
        
        with transaction.atomic():
            patient = PatientProfile.objects.select_for_update().get(id=patient_id)
            allocation = BedAllocation.objects.select_for_update().filter(patient=patient, is_active=True).first()
            
            if not allocation:
                return JsonResponse({'success': False, 'message': 'No active allocation found'})
            
            # Free the bed
            bed = allocation.bed
            bed.bed_status = 0
            bed.is_occupied = False
            bed.save()
            
            allocation.is_active = False
            allocation.save(update_fields=['is_active'])
            
            # Update Admission
            admission = AdmissionTable.objects.filter(patient=patient).order_by('-doctor_admit_date').first()
            doctor_name = request.user.fullname
            
            if not admission:
                admission = AdmissionTable.objects.create(
                    patient=patient, doctor_admitted=request.user, doctor_admit_date=timezone.now(),
                    doctor_discharged=doctor_name, doctor_discharge_status=1, doctor_discharge_date=timezone.now()
                )
            else:
                admission.doctor_discharged = doctor_name
                admission.doctor_discharge_status = 1
                admission.doctor_discharge_date = timezone.now()
                admission.save(update_fields=['doctor_discharged', 'doctor_discharge_status', 'doctor_discharge_date'])
            
            # Calculate Days
            num_of_days = 1
            if admission.nurse_admit_date and admission.doctor_discharge_date:
                delta = admission.doctor_discharge_date.date() - admission.nurse_admit_date.date()
                num_of_days = max(delta.days, 1)
            
            # Update Fee
            AdmissionFee.objects.update_or_create(
                patient=patient, ward=bed.ward, completed=0,
                defaults={
                    'num_of_days': num_of_days,
                    'admission_record': admission,
                    'staff': request.user,
                    'price': bed.ward.price if bed.ward else 0
                }
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Discharged successfully. Total days: {num_of_days}',
                'redirect_url': '/admissions/'
            })
                
    except OperationalError:
        return JsonResponse({'success': False, 'message': 'Database connection lost.'}, status=500)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'}, status=500)
        

def admission_table(request):
    page = 'newly-admitted'
    pre_admission = AdmissionTable.objects.filter(nurse_admit_status=0)
    current_admission = AdmissionTable.objects.filter(nurse_admit_status=1, doctor_discharge_status=0)
    marked_for_discharge = AdmissionTable.objects.filter(doctor_discharge_status=1, bill_discharge_status=0)
    fully_discharged = AdmissionTable.objects.filter(bill_discharge_status=1)
    total_admissions = AdmissionTable.objects.all().count() 
    
    context = {
        'page': page,
        'pre_admission': pre_admission,
        'current_admission': current_admission,
        'marked_for_discharge': marked_for_discharge,
        'fully_discharged': fully_discharged,
        'counts': pre_admission.count(),
        'admitted_counts': current_admission.count(),
        'marked_for_discharge_counts': marked_for_discharge.count(),
        'discharge_counts': fully_discharged.count(),
        'total_admissions_count': total_admissions,  
    }
    return render(request, 'IPD/admissions.html', context)


def get_admission_data_ajax(request):
    """AJAX endpoint to fetch admission data with filters"""
    try:
        data_type = request.GET.get('type', '')
        filter_type = request.GET.get('filter', 'all')
        page = int(request.GET.get('page', 1))
        
        print(f"=== DEBUG: data_type={data_type}, filter_type={filter_type}, page={page}")
        
        # Base queryset based on type
        if data_type == 'current':
            queryset = AdmissionTable.objects.filter(
                nurse_admit_status=1, 
                doctor_discharge_status=0
            ).select_related('patient', 'doctor_admitted')
            date_field = 'nurse_admit_date'
            print(f"Current queryset count before filters: {queryset.count()}")
        elif data_type == 'marked':
            queryset = AdmissionTable.objects.filter(
                doctor_discharge_status=1, 
                bill_discharge_status=0
            ).select_related('patient', 'doctor_admitted')
            date_field = 'doctor_discharge_date'
            print(f"Marked queryset count before filters: {queryset.count()}")
        elif data_type == 'discharged':
            queryset = AdmissionTable.objects.filter(
                bill_discharge_status=1
            ).select_related('patient')
            date_field = 'bill_discharge_date'
            print(f"Discharged queryset count before filters: {queryset.count()}")
        elif data_type == 'mastersheet':
            queryset = AdmissionTable.objects.all().select_related(
                'patient', 'doctor_admitted'
            ).order_by('-doctor_admit_date')
            date_field = 'doctor_admit_date'
            print(f"Mastersheet queryset count before filters: {queryset.count()}")
        else:
            return JsonResponse({'error': 'Invalid data type'}, status=400)
        
        # Apply filters
        if filter_type == 'date':
            date = request.GET.get('date')
            if date:
                try:
                    filter_date = datetime.strptime(date, '%Y-%m-%d').date()
                    start_of_day = timezone.make_aware(
                        datetime.combine(filter_date, datetime.min.time()),
                        timezone.get_current_timezone()
                    )
                    end_of_day = timezone.make_aware(
                        datetime.combine(filter_date, datetime.max.time()),
                        timezone.get_current_timezone()
                    )
                    filter_kwargs = {f"{date_field}__range": [start_of_day, end_of_day]}
                    queryset = queryset.filter(**filter_kwargs)
                    print(f"After date filter, count: {queryset.count()}")
                except ValueError as e:
                    print(f"Date parsing error: {e}")
        
        elif filter_type == 'date-range':
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            if start_date and end_date:
                try:
                    start = datetime.strptime(start_date, '%Y-%m-%d').date()
                    end = datetime.strptime(end_date, '%Y-%m-%d').date()
                    start_datetime = timezone.make_aware(
                        datetime.combine(start, datetime.min.time()),
                        timezone.get_current_timezone()
                    )
                    end_datetime = timezone.make_aware(
                        datetime.combine(end, datetime.max.time()),
                        timezone.get_current_timezone()
                    )
                    filter_kwargs = {f"{date_field}__range": [start_datetime, end_datetime]}
                    queryset = queryset.filter(**filter_kwargs)
                    print(f"After date-range filter, count: {queryset.count()}")
                except ValueError as e:
                    print(f"Date range parsing error: {e}")
        
        # Create paginator
        print(f"Creating paginator with count: {queryset.count()}")
        paginator = Paginator(queryset, 10)
        print(f"Paginator total pages: {paginator.num_pages}")
        
        current_page = paginator.get_page(page)
        print(f"Current page: {current_page.number}, has_next: {current_page.has_next()}")
        
        # Prepare data based on type
        data = []
        
        if data_type == 'current':
            print(f"Processing current admissions, page count: {len(current_page)}")
            for admission in current_page:
                bed_allocation = BedAllocation.objects.filter(
                    patient=admission.patient,
                    is_active=True
                ).select_related('ward', 'bed').first()
                
                data.append({
                    'id': admission.id,
                    'patient_id': admission.patient.id,
                    'patient_name': f"{admission.patient.surname} {admission.patient.other_name or ''} {admission.patient.first_name}",
                    'hospital_number': admission.patient.hospital_number or '-',
                    'admitted_by': f"Nurse {admission.nurse_admitted}",
                    'admit_date': admission.nurse_admit_date.isoformat() if admission.nurse_admit_date else None,
                    'time_ago': timesince(admission.nurse_admit_date) if admission.nurse_admit_date else '-',
                    'ward': bed_allocation.ward.ward_name if bed_allocation and bed_allocation.ward else '-',
                    'bed': bed_allocation.bed.bed_name if bed_allocation and bed_allocation.bed else '-',
                })
        
        elif data_type == 'marked':
            for admission in current_page:
                data.append({
                    'id': admission.id,
                    'patient_id': admission.patient.id,
                    'patient_name': f"{admission.patient.surname} {admission.patient.other_name or ''} {admission.patient.first_name}",
                    'hospital_number': admission.patient.hospital_number or '-',
                    'marked_by': f"Dr. {admission.doctor_discharged or '-'}",
                    'mark_date': admission.doctor_discharge_date.isoformat() if admission.doctor_discharge_date else None,
                    'time_ago': timesince(admission.doctor_discharge_date) if admission.doctor_discharge_date else '-',
                })
        
        elif data_type == 'discharged':
            for admission in current_page:
                data.append({
                    'id': admission.id,
                    'patient_id': admission.patient.id,
                    'patient_name': f"{admission.patient.surname} {admission.patient.other_name or ''} {admission.patient.first_name}",
                    'hospital_number': admission.patient.hospital_number or '-',
                    'discharged_by': admission.bill_discharged or '-',
                    'discharge_date': admission.bill_discharge_date.isoformat() if admission.bill_discharge_date else None,
                    'time_ago': timesince(admission.bill_discharge_date) if admission.bill_discharge_date else '-',
                })
        
        elif data_type == 'mastersheet':
            for admission in current_page:
                bed_allocation = admission.bedallocation_set.all().first()
                
                data.append({
                    'id': admission.id,
                    'patient_id': admission.patient.id,
                    'patient_name': f"{admission.patient.surname} {admission.patient.other_name or ''} {admission.patient.first_name}",
                    'hospital_number': admission.patient.hospital_number or '-',
                    'doctor_admitted': f"Dr. {admission.doctor_admitted.fullname if admission.doctor_admitted else '-'}",
                    'doctor_admit_date': admission.doctor_admit_date.isoformat() if admission.doctor_admit_date else None,
                    'nurse_admitted': admission.nurse_admitted or '-',
                    'nurse_admit_date': admission.nurse_admit_date.isoformat() if admission.nurse_admit_date else None,
                    'doctor_discharged': f"{'Dr. '+ admission.doctor_discharged if admission.doctor_discharged else '-'}",
                    'doctor_discharge_date': admission.doctor_discharge_date.isoformat() if admission.doctor_discharge_date else None,
                    'bill_discharged': admission.bill_discharged or '-',
                    'bill_discharge_date': admission.bill_discharge_date.isoformat() if admission.bill_discharge_date else None,
                    'ward': bed_allocation.ward.ward_name if bed_allocation and bed_allocation.ward else '-',
                    'bed': bed_allocation.bed.bed_name if bed_allocation and bed_allocation.bed else '-',
                })
        
        print(f"Final data count: {len(data)}")
        
        response_data = {
            'data': data,
            'has_next': current_page.has_next(),
            'has_previous': current_page.has_previous(),
            'page': current_page.number,
            'total_pages': paginator.num_pages,
            'total_count': paginator.count,
        }
        
        print(f"Response: has_next={response_data['has_next']}, total_pages={response_data['total_pages']}")
        
        return JsonResponse(response_data)
        
    except Exception as e:
        print(f"ERROR in get_admission_data_ajax: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'error': str(e),
            'data': [],
            'has_next': False,
            'has_previous': False,
            'page': 1,
            'total_pages': 0,
            'total_count': 0
        }, status=500)


def timesince(dt):
    """Helper function to calculate time since"""
    from django.utils.timesince import timesince as django_timesince
    from django.utils.timezone import now
    return django_timesince(dt, now()) if dt else '-'


def patient_admission(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    total_admissions = AdmissionTable.objects.filter(patient=patient)
    context = {
        'total_admissions':total_admissions,
        'admission_counts': total_admissions.count(),
        'patient':patient,
    }
    return render(request,'IPD/admission_record.html',context)



# -------------- Notes capturing -------------

from .models import AdmissionNote, DoctorNote, NurseNote, WardRound


def get_notes(request, patient_id):
    """Main notes page and API for getting notes"""
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Check if this is an AJAX request for notes data
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return JSON data for AJAX calls
        admission_notes = AdmissionNote.objects.filter(patient=patient).order_by('-created_date')[:5]
        doctor_notes = DoctorNote.objects.filter(patient=patient).order_by('-created_date')[:5]
        nurse_notes = NurseNote.objects.filter(patient=patient).order_by('-created_date')[:5]
        wardround_notes = WardRound.objects.filter(patient=patient).order_by('-created_date')[:5]
        
        def serialize_notes(notes, note_type=None):
            result = []
            for note in notes:
                # Get content based on note type
                if isinstance(note, AdmissionNote):
                    content = note.admission_note
                elif isinstance(note, DoctorNote):
                    content = note.doctor_note
                elif isinstance(note, NurseNote):
                    content = note.nurse_note
                elif isinstance(note, WardRound):
                    content = note.notes
                else:
                    content = ""
                
                result.append({
                    'id': note.id,
                    'content': content or "",
                    'staff': note.staff.fullname if note.staff else 'Unknown',
                    'created_date': note.created_date.isoformat()
                })
            return result
        
        return JsonResponse({
            'admission_notes': serialize_notes(admission_notes, 'admission'),
            'doctor_notes': serialize_notes(doctor_notes, 'doctor'),
            'nurse_notes': serialize_notes(nurse_notes, 'nurse'),
            'wardround_notes': serialize_notes(wardround_notes, 'wardround')
        })
    
    # Return HTML page for regular request
    return render(request, 'IPD/patient_notes.html', {'patient': patient})

@csrf_exempt
def create_note(request, note_type, patient_id):
    """Create a new note"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            content = data.get('content', '').strip()
            patient = get_object_or_404(PatientProfile, id=patient_id)
            
            if not content:
                return JsonResponse({'success': False, 'message': 'Content is required'})
            
            # Create note based on type
            if note_type == 'admission':
                note = AdmissionNote.objects.create(
                    admission_note=content,
                    staff=request.user,
                    patient=patient
                )
            elif note_type == 'doctor':
                note = DoctorNote.objects.create(
                    doctor_note=content,
                    staff=request.user,
                    patient=patient
                )
            elif note_type == 'nurse':
                note = NurseNote.objects.create(
                    nurse_note=content,
                    staff=request.user,
                    patient=patient
                )
            elif note_type == 'wardround':
                note = WardRound.objects.create(
                    notes=content,  
                    staff=request.user,
                    patient=patient
                )
            else:
                return JsonResponse({'success': False, 'message': 'Invalid note type'})
            
            return JsonResponse({
                'success': True,
                'message': 'Note created successfully',
                'note_id': note.id
            })
            
        except Exception as e:
            print(f"Error creating note: {str(e)}")  # Debug print
            return JsonResponse({'success': False, 'message': str(e)})
    
    return JsonResponse({'success': False, 'message': 'Invalid method'})


@csrf_exempt
def update_note(request, note_id):
    """Update an existing note (only if within 24 hours)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            content = data.get('content')
            
            if not content:
                return JsonResponse({'success': False, 'message': 'Content is required'})
            
            # Try each note type
            note = None
            
            # Check AdmissionNote
            try:
                note = AdmissionNote.objects.get(id=note_id)
            except AdmissionNote.DoesNotExist:
                pass
            
            # Check DoctorNote
            if not note:
                try:
                    note = DoctorNote.objects.get(id=note_id)
                except DoctorNote.DoesNotExist:
                    pass
            
            # Check NurseNote
            if not note:
                try:
                    note = NurseNote.objects.get(id=note_id)
                except NurseNote.DoesNotExist:
                    pass
            
            # Check WardRound
            if not note:
                try:
                    note = WardRound.objects.get(id=note_id)
                except WardRound.DoesNotExist:
                    pass
            
            if not note:
                return JsonResponse({'success': False, 'message': 'Note not found'})
            
            # Check if note is within 24 hours
            time_threshold = timezone.now() - timedelta(hours=24)
            if note.created_date < time_threshold:
                return JsonResponse({
                    'success': False, 
                    'message': 'Cannot edit notes older than 24 hours'
                })
            
            # Update the appropriate field
            if hasattr(note, 'admission_note'):
                note.admission_note = content
            elif hasattr(note, 'doctor_note'):
                note.doctor_note = content
            elif hasattr(note, 'nurse_note'):
                note.nurse_note = content
            elif hasattr(note, 'notes'):
                note.notes = content
            
            note.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Note updated successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    
    return JsonResponse({'success': False, 'message': 'Invalid method'})


@csrf_exempt
def delete_note(request, note_id):
    """Delete a note (only if within 24 hours)"""
    if request.method == 'POST':
        try:
            # Try each note type
            note = None
            
            try:
                note = AdmissionNote.objects.get(id=note_id)
            except AdmissionNote.DoesNotExist:
                try:
                    note = DoctorNote.objects.get(id=note_id)
                except DoctorNote.DoesNotExist:
                    try:
                        note = NurseNote.objects.get(id=note_id)
                    except NurseNote.DoesNotExist:
                        try:
                            note = WardRound.objects.get(id=note_id)
                        except WardRound.DoesNotExist:
                            pass
            
            if not note:
                return JsonResponse({'success': False, 'message': 'Note not found'})
            
            # Check if note is within 24 hours
            time_threshold = timezone.now() - timedelta(hours=24)
            if note.created_date < time_threshold:
                return JsonResponse({
                    'success': False, 
                    'message': 'Cannot delete notes older than 24 hours'
                })
            
            note.delete()
            
            return JsonResponse({
                'success': True,
                'message': 'Note deleted successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    
    return JsonResponse({'success': False, 'message': 'Invalid method'})

def get_note(request, note_id):
    """Get a single note for editing"""
    try:
        # Try each note type
        note = None
        content = None
        
        try:
            note = AdmissionNote.objects.get(id=note_id)
            content = note.admission_note
        except AdmissionNote.DoesNotExist:
            try:
                note = DoctorNote.objects.get(id=note_id)
                content = note.doctor_note
            except DoctorNote.DoesNotExist:
                try:
                    note = NurseNote.objects.get(id=note_id)
                    content = note.nurse_note
                except NurseNote.DoesNotExist:
                    try:
                        note = WardRound.objects.get(id=note_id)
                        content = note.notes
                    except WardRound.DoesNotExist:
                        pass
        
        if not note:
            return JsonResponse({'error': 'Note not found'}, status=404)
        
        return JsonResponse({
            'id': note.id,
            'content': content,
            'staff': note.staff.fullname if note.staff else 'Unknown',
            'created_date': note.created_date.isoformat()
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def get_note_history(request, note_type, patient_id):
    """Get note history with filters and pagination"""
    patient = get_object_or_404(PatientProfile, id=patient_id)
    filter_type = request.GET.get('filter', 'all')
    page = int(request.GET.get('page', 1))
    get_all = request.GET.get('all') == 'true'
    
    # Get queryset based on note type
    if note_type == 'admission':
        queryset = AdmissionNote.objects.filter(patient=patient).select_related('staff')
    elif note_type == 'doctor':
        queryset = DoctorNote.objects.filter(patient=patient).select_related('staff')
    elif note_type == 'nurse':
        queryset = NurseNote.objects.filter(patient=patient).select_related('staff')
    elif note_type == 'wardround':
        queryset = WardRound.objects.filter(patient=patient).select_related('staff')
    else:
        return JsonResponse({'error': 'Invalid note type'}, status=400)
    
    # Apply filters
    if filter_type == 'date':
        date = request.GET.get('date')
        if date:
            try:
                filter_date = datetime.strptime(date, '%Y-%m-%d').date()
                start_of_day = timezone.make_aware(
                    datetime.combine(filter_date, datetime.min.time()),
                    timezone.get_current_timezone()
                )
                end_of_day = timezone.make_aware(
                    datetime.combine(filter_date, datetime.max.time()),
                    timezone.get_current_timezone()
                )
                queryset = queryset.filter(created_date__range=[start_of_day, end_of_day])
            except ValueError:
                pass
    
    elif filter_type == 'date-range':
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                start_datetime = timezone.make_aware(
                    datetime.combine(start, datetime.min.time()),
                    timezone.get_current_timezone()
                )
                end_datetime = timezone.make_aware(
                    datetime.combine(end, datetime.max.time()),
                    timezone.get_current_timezone()
                )
                queryset = queryset.filter(created_date__range=[start_datetime, end_datetime])
            except ValueError:
                pass
    
    # Order by most recent first
    queryset = queryset.order_by('-created_date')
    
    # If get_all is true, return all records (for printing)
    if get_all:
        data = []
        for note in queryset:
            content = getattr(note, 
                'admission_note' if hasattr(note, 'admission_note') else
                ('doctor_note' if hasattr(note, 'doctor_note') else
                 ('nurse_note' if hasattr(note, 'nurse_note') else 'notes')))
            
            data.append({
                'id': note.id,
                'content': content,
                'staff': note.staff.fullname if note.staff else 'Unknown',
                'created_date': note.created_date.isoformat()
            })
        
        return JsonResponse({'data': data})
    
    # Pagination
    paginator = Paginator(queryset, 10)
    current_page = paginator.get_page(page)
    
    data = []
    for note in current_page:
        # Get the content based on note type
        if hasattr(note, 'admission_note'):
            content = note.admission_note
        elif hasattr(note, 'doctor_note'):
            content = note.doctor_note
        elif hasattr(note, 'nurse_note'):
            content = note.nurse_note
        else:
            content = note.notes
        
        data.append({
            'id': note.id,
            'content': content,
            'staff': note.staff.fullname if note.staff else 'Unknown',
            'created_date': note.created_date.isoformat()
        })
    
    return JsonResponse({
        'data': data,
        'has_next': current_page.has_next(),
        'has_previous': current_page.has_previous(),
        'page': current_page.number,
        'total_pages': paginator.num_pages,
        'total_count': paginator.count
    })



# ----------------------Drug Charts------------------


from .utils.drug_chart_utils import get_all_administered_drugs
from django.contrib.contenttypes.models import ContentType
from .models import DrugAdministration
from django.apps import apps
import pytz
NIGERIA_TZ = pytz.timezone('Africa/Lagos')


@login_required
def drug_chart(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Getting Nigeria timezone
    NIGERIA_TZ = pytz.timezone('Africa/Lagos')
    nigeria_now = timezone.now().astimezone(NIGERIA_TZ)
    today = nigeria_now.date()
    
    # Getting date range
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    
    print(f"\n{'='*60}")
    print(f"DRUG CHART - Patient: {patient.get_full_name}")
    print(f"Nigeria Today: {today}")
    print(f"Date Range: {start_date} to {end_date}")
    
    # Get all prescriptions active during this date range
    prescribed_drugs = get_all_administered_drugs(patient, start_date, end_date)
    
    # frequency times mapping
    frequency_times = {
        'od': ['08:00'],
        'om': ['08:00'],
        'mane': ['08:00'],
        'nocte': ['20:00'],
        'bd': ['08:00', '20:00'],
        'tds': ['08:00', '14:00', '20:00'],
        'qds': ['08:00', '12:00', '16:00', '20:00'],
        'weekly': ['08:00'],
        'monthly': ['08:00'],
        'alt_die': ['08:00'],
        'prn': ['08:00', '12:00', '16:00', '20:00'],
        'ac': ['07:30', '12:30', '18:30'],
        'pc': ['08:30', '13:30', '19:30'],
        'stat': ['00:00'],
        'others': ['08:00', '14:00', '20:00'],
        None: ['08:00'],
    }
    
    # Build date range list
    date_range = []
    for i in range((end_date - start_date).days + 1):
        date_range.append(start_date + timedelta(days=i))
    
    # Get existing administration records
    admin_lookup = {}
    for drug in prescribed_drugs:
        try:
            from django.apps import apps
            model = apps.get_model(drug['app_name'], drug['model_name'])
            content_type = ContentType.objects.get_for_model(model)
            
            administrations = DrugAdministration.objects.filter(
                content_type=content_type,
                object_id=drug['id'],
                scheduled_time__date__gte=start_date,
                scheduled_time__date__lte=end_date
            )
            
            for admin in administrations:
                date_str = admin.scheduled_time.strftime('%Y-%m-%d')
                time_str = admin.scheduled_time.strftime('%H:%M')
                key = f"{drug['store_id']}_{drug['id']}_{date_str}_{time_str}"
                admin_lookup[key] = admin
        except Exception as e:
            print(f"Error: {e}")
            continue
    
    # Build HTML table with visual design
    table_html = ""
    
    for drug in prescribed_drugs:
        times = frequency_times.get(drug['frequency'], ['08:00'])
        
        # For special frequencies
        is_weekly = drug['frequency'] == 'weekly'
        is_monthly = drug['frequency'] == 'monthly'
        is_alt_die = drug['frequency'] == 'alt_die'
        
        table_html += f'''
        <tr data-prescription-id="{drug['id']}" data-store="{drug['store_id']}" data-model="{drug['model_name']}">
            <td>
                <strong class="drug-name">{drug['drug_name']}</strong><br>
                <small class="text-muted">Dose: {drug['dose']} {drug['UoM']}</small>
                <br>
                <small class="text-muted">Qty: {drug['quantity']} | Dur: {drug['duration']} days</small>
                {f'<br><small class="text-info"><i class="fas fa-info-circle me-1"></i> {drug["notes"][:30]}</small>' if drug['notes'] else ''}
            </td>
            <td>
                <span class="badge bg-primary" style="color:white">{drug['route'] or 'N/A'}</span>
                <br>
                <span class="badge bg-info" style="color:white">{drug['frequency'] or 'N/A'}</span>
            </td>
            <td>
                {drug['start_date'].strftime('%d/%m/%y') if drug['start_date'] else 'N/A'}<br>
                <small class="text-muted">
                    {f"Stop: {drug['stop_date'].strftime('%d/%m/%y')}" if drug['stop_date'] else 'No stop date'}
                </small>
            </td>
        '''
        
        for date in date_range:
            date_str = date.strftime('%Y-%m-%d')
            # Use Nigeria today for highlighting
            today_class = 'table-warning' if date == today else ''
            
            # Check if date is within prescription active period
            is_active = True
            if drug['start_date'] and date < drug['start_date']:
                is_active = False
            if drug['stop_date'] and date > drug['stop_date']:
                is_active = False
            
            # Handle special frequencies
            if is_active:
                if is_weekly:
                    days_diff = (date - drug['start_date']).days
                    if days_diff % 7 != 0:
                        is_active = False
                elif is_monthly:
                    if date.day != drug['start_date'].day:
                        is_active = False
                elif is_alt_die:
                    days_diff = (date - drug['start_date']).days
                    if days_diff % 2 != 0:
                        is_active = False
            
            table_html += f'<td class="text-center p-1 {today_class}" style="min-width: 100px;">'
            
            for time in times:
                key = f"{drug['store_id']}_{drug['id']}_{date_str}_{time}"
                admin = admin_lookup.get(key)
                
                button_id = f"btn_{drug['store_id']}_{drug['id']}_{date_str}_{time.replace(':', '')}"
                
                if admin:
                    # Color based on status
                    if admin.status == 'administered':
                        bg_color = '#28a745'
                        icon = 'fa-check-circle'
                        text_color = 'white'
                    elif admin.status == 'missed':
                        bg_color = '#dc3545'
                        icon = 'fa-times-circle'
                        text_color = 'white'
                    elif admin.status == 'refused':
                        bg_color = '#ffc107'
                        icon = 'fa-ban'
                        text_color = '#212529'
                    elif admin.status == 'held':
                        bg_color = '#17a2b8'
                        icon = 'fa-pause-circle'
                        text_color = 'white'
                    else:
                        bg_color = '#6c757d'
                        icon = 'fa-circle'
                        text_color = 'white'
                    
                    table_html += f'''
                        <div id="{button_id}" 
                             class="admin-slot {admin.status}" 
                             data-admin-id="{admin.id}"
                             data-prescription-id="{drug['id']}"
                             data-store="{drug['store_id']}"
                             data-date="{date_str}"
                             data-time="{time}"
                             data-status="{admin.status}"
                             style="background-color: {bg_color}; color: {text_color}; border-radius: 4px; padding: 6px 0; margin-bottom: 4px; cursor: pointer; font-weight: 500; font-size: 0.875rem; text-align: center;"
                             onclick="openAdminModal({admin.id}, '{date_str}', '{time}')">
                            <i class="fas {icon} me-1"></i> {time}
                        </div>
                    '''
                elif is_active:
                    table_html += f'''
                        <div id="{button_id}" 
                             class="admin-slot pending" 
                             data-prescription-id="{drug['id']}"
                             data-store="{drug['store_id']}"
                             data-date="{date_str}"
                             data-time="{time}"
                             data-status="pending"
                             style="background-color: #6c757d; color: white; border-radius: 4px; padding: 6px 0; margin-bottom: 4px; cursor: pointer; font-weight: 500; font-size: 0.875rem; text-align: center; opacity: 0.5;"
                             onclick="openScheduledModal('{drug['store_id']}', '{drug['model_name']}', {drug['id']}, '{date_str}', '{time}')">
                            <i class="far fa-clock me-1"></i> {time}
                        </div>
                    '''
                else:
                    table_html += f'''
                        <div style="background-color: #e9ecef; color: #adb5bd; border-radius: 4px; padding: 6px 0; margin-bottom: 4px; font-weight: 500; font-size: 0.875rem; text-align: center; cursor: not-allowed;">
                            <i class="fas fa-ban me-1"></i> {time}
                        </div>
                    '''
            
            table_html += '</td>'
        
        # Signature column
        table_html += f'''
            <td>
                <small class="text-muted">
                    <i class="fas fa-signature me-1"></i> {drug['prescribed_by']}
                </small>
                <br>
                <small class="text-muted">
                    <i class="far fa-calendar-alt me-1"></i> {drug['prescribed_at'].strftime("%d/%m/%y %H:%M") if drug['prescribed_at'] else ''}
                </small>
            </td>
        </tr>
        '''
    
    if not prescribed_drugs:
        colspan = len(date_range) + 4
        table_html += f'''
        <tr>
            <td colspan="{colspan}" class="text-center py-5">
                <div class="empty-state">
                    <i class="fas fa-prescription-bottle fa-4x text-muted mb-3"></i> 
                    <h5>No Active Prescriptions</h5>
                    <p class="text-muted">No prescriptions found for {start_date} to {end_date}</p>
                </div>
            </td>
        </tr>
        '''
    
    context = {
        'patient': patient,
        'table_html': table_html,
        'date_range': date_range,
        'start_date': start_date,
        'end_date': end_date,
        'today': today,  
    }
    
    return render(request, 'IPD/drug_chart.html', context)



@login_required
@csrf_exempt
def add_prescription(request, patient_id):
    if request.method == 'POST':
        try:
            patient = get_object_or_404(PatientProfile, id=patient_id)
            data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
            
            prescription = DrugPrescription.objects.create(
                patient=patient,
                prescription_type=data.get('prescription_type', 'regular'),
                drug_name=data.get('drug_name'),
                dose=data.get('dose'),
                quantity=data.get('quantity', 1),
                route=data.get('route'),
                frequency=data.get('frequency'),
                start_date=data.get('start_date'),
                stop_date=data.get('stop_date') or None,
                prescribed_by=request.user.fullname,
                notes=data.get('notes', ''),
            )
            
            # Create scheduled administrations
            create_scheduled_administrations(prescription)
            
            return JsonResponse({'success': True, 'prescription_id': prescription.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

def create_scheduled_administrations(prescription):
    """Create scheduled administrations based on frequency"""
    from datetime import datetime, timedelta
    
    frequency_times = {
        'od': [(8, 0)],
        'bd': [(8, 0), (20, 0)],
        'tds': [(8, 0), (16, 0), (0, 0)],
        'qds': [(8, 0), (12, 0), (16, 0), (20, 0)],
        'prn': [(8, 0), (12, 0), (16, 0), (20, 0)],
        'stat': [(0, 0)],
    }
    
    times = frequency_times.get(prescription.frequency, [(8, 0)])
    end_date = prescription.stop_date or (prescription.start_date + timedelta(days=7))
    
    current_date = prescription.start_date
    while current_date <= end_date:
        for hour, minute in times:
            scheduled_time = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=hour, minutes=minute)
            DrugAdministration.objects.get_or_create(
                prescription=prescription,
                scheduled_time=scheduled_time,
                defaults={'status': 'pending'}
            )
        current_date += timedelta(days=1)


@login_required
@csrf_exempt
def get_administration_detail(request, administration_id):
    """Get details of a specific administration"""
    try:
        admin = get_object_or_404(DrugAdministration, id=administration_id)
        
        # Get the prescription details from the source model
        drug_name = "Unknown"
        dose = ""
        
        if admin.source_model and admin.source_record_id:
            try:
                from django.apps import apps
                # source_model is stored as "app_name.model_name"
                parts = admin.source_model.split('.')
                if len(parts) == 2:
                    app_name, model_name = parts[0], parts[1]
                    model = apps.get_model(app_name, model_name)
                    source_record = model.objects.filter(id=admin.source_record_id).first()
                    if source_record:
                        drug_name = source_record.item
                        dose = source_record.dose
            except Exception as e:
                print(f"Error fetching source record: {e}")
        
        data = {
            'id': admin.id,
            'prescription': {
                'id': admin.source_record_id,
                'drug_name': drug_name,
                'dose': dose,
            },
            'scheduled_time': admin.scheduled_time.isoformat() if admin.scheduled_time else None,
            'administered_time': admin.administered_time.isoformat() if admin.administered_time else None,
            'status': admin.status,
            'is_patient_owned': admin.is_patient_owned,
            'action': admin.action,
            'bedside_drug': admin.bedside_drug,
            'quantity_administered': admin.quantity_administered,
            'batch_no': admin.batch_no,
            'dose_given': admin.dose_given,
            'comments': admin.comments,
        }
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@csrf_exempt
def create_administration(request):
    """Create a new drug administration record using GenericForeignKey"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            print(f"📝 CREATE - Received data: {data}")
            
            # Get the prescription details from the request
            prescription_id = data.get('prescription_id')
            source_store = data.get('source_store')
            source_model = data.get('source_model')  # This is the model name like "IPDAdministeredDrugs"
            scheduled_date = data.get('scheduled_date')
            scheduled_time = data.get('scheduled_time')
            
            if not prescription_id or not source_store or not source_model:
                return JsonResponse({
                    'success': False, 
                    'error': 'Missing prescription information (store, model, or id)'
                }, status=400)
            
            # Map store_id to app_name
            store_to_app = {
                'ipd_pharm1': 'IPD_pharm',
                'ipd_pharm2': 'IPD_pharm2',
                'ipd_pharm3': 'IPD_pharm3',
                'opd_pharm1': 'OPD_pharm',
                'opd_pharm2': 'OPD_pharm2',
            }
            
            app_name = store_to_app.get(source_store)
            if not app_name:
                return JsonResponse({
                    'success': False, 
                    'error': f'Unknown store: {source_store}'
                }, status=400)
            
            # Get the model class dynamically using app_name and model_name
            from django.apps import apps
            from django.contrib.contenttypes.models import ContentType
            
            try:
                model = apps.get_model(app_name, source_model)
                print(f"✅ Found model: {app_name}.{source_model}")
            except LookupError as e:
                print(f"❌ Model not found: {app_name}.{source_model} - Error: {e}")
                return JsonResponse({
                    'success': False, 
                    'error': f'Model not found: {app_name}.{source_model}'
                }, status=400)
            
            content_type = ContentType.objects.get_for_model(model)
            
            # Parse scheduled datetime
            if scheduled_date and scheduled_time:
                scheduled_datetime = datetime.strptime(
                    f"{scheduled_date} {scheduled_time}",
                    '%Y-%m-%d %H:%M'
                )
            else:
                scheduled_datetime = timezone.now()
            
            # Parse administered time
            administered_time = None
            if data.get('administered_time'):
                try:
                    date_for_admin = scheduled_date or timezone.now().strftime('%Y-%m-%d')
                    administered_time = datetime.strptime(
                        f"{date_for_admin} {data.get('administered_time')}",
                        '%Y-%m-%d %H:%M'
                    )
                except Exception as e:
                    print(f"Error parsing administered time: {e}")
                    administered_time = timezone.now()
            
            # Map action to status
            action = data.get('action', '').lower()
            status_map = {
                'given': 'administered',
                'refused': 'refused',
                'missed': 'missed',
                'held': 'held',
                '': 'pending'
            }
            status = status_map.get(action, 'pending')
            
            # Check if administration already exists
            existing_admin = DrugAdministration.objects.filter(
                content_type=content_type,
                object_id=prescription_id,
                scheduled_time=scheduled_datetime
            ).first()
            
            if existing_admin:
                print(f"🔄 Updating existing administration: {existing_admin.id}")
                existing_admin.administered_time = administered_time
                existing_admin.administered_by = request.user
                existing_admin.status = status
                existing_admin.is_patient_owned = data.get('is_patient_owned', False)
                existing_admin.action = action
                existing_admin.bedside_drug = data.get('bedside_drug', '')
                existing_admin.quantity_administered = data.get('quantity_administered', '')
                existing_admin.batch_no = data.get('batch_no', '')
                existing_admin.dose_given = data.get('dose', '')
                existing_admin.comments = data.get('comments', '')
                existing_admin.save()
                admin = existing_admin
            else:
                print(f"🆕 Creating new administration")
                admin = DrugAdministration.objects.create(
                    content_type=content_type,
                    object_id=prescription_id,
                    source_store=source_store,
                    source_model=f"{app_name}.{source_model}",
                    source_record_id=prescription_id,
                    scheduled_time=scheduled_datetime,
                    administered_time=administered_time,
                    administered_by=request.user,
                    status=status,
                    is_patient_owned=data.get('is_patient_owned', False),
                    action=action,
                    bedside_drug=data.get('bedside_drug', ''),
                    quantity_administered=data.get('quantity_administered', ''),
                    batch_no=data.get('batch_no', ''),
                    dose_given=data.get('dose', ''),
                    comments=data.get('comments', ''),
                )
            
            print(f"✅ Admin ID: {admin.id} with status: {admin.status}")
            
            return JsonResponse({
                'success': True, 
                'administration_id': admin.id,
                'status': admin.status,
                'message': 'Administration recorded successfully'
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)


@login_required
@csrf_exempt
def update_administration(request, administration_id):
    """Update an existing drug administration record"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            admin = get_object_or_404(DrugAdministration, id=administration_id)
            
            # Parse administered time if provided
            administered_time = None
            if data.get('administered_time'):
                try:
                    administered_time = datetime.strptime(
                        f"{admin.scheduled_time.strftime('%Y-%m-%d')} {data.get('administered_time')}",
                        '%Y-%m-%d %H:%M'
                    )
                except:
                    administered_time = timezone.now()
            
            # Map action to status
            action = data.get('action', '').lower()
            status_map = {
                'given': 'administered',
                'refused': 'refused',
                'missed': 'missed',
                'held': 'held',
            }
            status = status_map.get(action, admin.status)
            
            # Update fields
            admin.administered_time = administered_time
            admin.administered_by = request.user
            admin.status = status
            admin.is_patient_owned = data.get('is_patient_owned', admin.is_patient_owned)
            admin.action = action
            admin.bedside_drug = data.get('bedside_drug', admin.bedside_drug)
            admin.quantity_administered = data.get('quantity_administered', admin.quantity_administered)
            admin.batch_no = data.get('batch_no', admin.batch_no)
            admin.dose_given = data.get('dose', admin.dose_given)
            admin.comments = data.get('comments', admin.comments)
            admin.save()
            
            return JsonResponse({
                'success': True, 
                'administration_id': admin.id,
                'message': 'Administration updated successfully'
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
