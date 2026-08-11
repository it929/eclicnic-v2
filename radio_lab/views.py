import time
import pandas as pd
import os
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import FileSystemStorage
from decimal import Decimal
from django.db.models import Max
from django.db import transaction
from django.utils import timezone
import json
from datetime import timedelta
from .models import RadioLabInventory,RadiologyLab,LabResult,ScanResult
from patients.models import PatientProfile
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from io import BytesIO
from django.core.mail import EmailMessage
from reportlab.lib.pagesizes import A4

@login_required(login_url='login')
def lab_inventory(request):
    lab_records = RadioLabInventory.objects.filter(type='L')
    counts = 250
    contxt = {
        'counts':counts,
        'lab_records':lab_records,
        'page':'lab-inventory',
    }
    return render(request, 'radio_lab/lab_inventory.html',contxt)


@login_required(login_url='login')
@transaction.atomic()
def upload_labtest_from_excel(request):
    lab_records = RadioLabInventory.objects.filter(type='L')
    counts = lab_records.count()
    page = 'upload-test'
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        try:
            # Save uploaded file temporarily
            fs = FileSystemStorage()
            filename = fs.save(excel_file.name, excel_file)
            file_path = fs.path(filename)

            # Read Excel file
            df = pd.read_excel(file_path)

            created_count = 0
            updated_count = 0

            for index, row in df.iterrows():
                # Required fields
                item_id = str(row.get('item_id')).strip() if pd.notna(row.get('item_id')) else ''
                item = str(row.get('item')).strip() if pd.notna(row.get('item')) else ''


                # Handle required numeric fields
                try:
                    rate = Decimal(row['rate']) if pd.notna(row.get('rate')) else None
                except:
                    messages.warning(request, f"Invalid rate in row {index+2}. Skipping row.")
                    continue

                # Check required
                if not all([item_id, item, rate is not None]):
                    messages.warning(request, f"Missing required fields in row {index+2}. Skipping row.")
                    continue

                test, created = RadioLabInventory.objects.get_or_create(
                    item_id=item_id,
                    item=item,
                    type='L',
                    defaults={
                        'rate': rate,
                    }
                )

                if not created:
                    test.rate = rate

                # Staff assignment
                test.staff = request.user
                test.save()

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            fs.delete(filename)
            messages.success(request, f"Import complete: {created_count} created, {updated_count} updated.")

        except Exception as e:
            messages.error(request, f"Error processing file: {e}")

        return redirect('lab_inventory') 
    context = {
        'page':page,
        'lab_records':lab_records,
        'counts':counts
    }
    return render(request, 'radio_lab/lab_inventory.html',context)


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
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            #  Ensure there's at least one item
            items = data.get("items", [])
            if not items:
                return JsonResponse({"success": False, "error": "At least one lab test is required."}, status=400)

            with transaction.atomic():
                for item in items:
                    item_name = item.get("item") 
                    item_id = item.get("item_id")
                    rate = item.get("rate")

                    #  Validate fields
                    if not item_name or not rate:
                        return JsonResponse({"success": False, "error": "Each lab test must have a name and rate."}, status=400)

                    try:
                        rate = float(rate)
                        if rate <= 0:
                            return JsonResponse({"success": False, "error": "Rate must be greater than zero."}, status=400)
                    except ValueError:
                        return JsonResponse({"success": False, "error": "Invalid rate value."}, status=400)

                    #  Save record
                    RadioLabInventory.objects.create(
                        item=item_name.strip(),
                        item_id=item_id.strip() if item_id else None,
                        rate=rate,
                        type="L",  # Always Lab test
                        staff=request.user
                    )

            return JsonResponse({"success": True})

        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)

    return JsonResponse({"success": False, "error": "Invalid request method."}, status=405)


@login_required(login_url='login')
def review_lab_inventory(request):
    test_items = RadioLabInventory.objects.filter(type='L')
    context = {
        'test_items': test_items,
        'page':'test-items',
    }
    return render(request, 'radio_lab/lab_review.html', context)


# Delete lab test
@login_required(login_url='login')
@require_POST
def delete_lab_test(request, pk):
    try:
        test = get_object_or_404(RadioLabInventory, pk=pk)
        test.delete()
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


# Modify lab test
@login_required(login_url='login')
@require_POST
def modify_lab_test(request, pk):
    test = get_object_or_404(RadioLabInventory, pk=pk)

    item = request.POST.get("item")
    item_id = request.POST.get("item_id")
    rate = request.POST.get("rate")

    if not item or not rate:
        return JsonResponse({"success": False, "error": "Item and Rate are required."}, status=400)

    try:
        test.item = item.strip()
        test.item_id = item_id.strip() if item_id else None
        test.rate = rate
        test.save()
        return JsonResponse({
            "success": True,
            "item": test.item,
            "item_id": test.item_id,
            "rate": str(test.rate)
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


# Patient waiting List (Laboratory)
@login_required(login_url='login')
def fetch_lab_queue(request):
    queue = RadiologyLab.objects.filter(
        radiolab_waiting_status=0,
        billing_waiting_status=0,item_type = 'L',
        created_date__gte=timezone.now() - timedelta(hours=24)
    ).select_related('patient', 'staff').order_by('patient_id', '-created_date')
    
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
            'attendant': f"Dr. {record.staff.fullname}" if record.staff else "N/A",
            'created_date': record.created_date.strftime('%Y-%m-%d %H:%M'),
        })

    return JsonResponse({
        'data': data,
        'count': len(data)
    })


@login_required(login_url='login')
def load_lab_queue(request):
    page = 'lab-queue'
    context = {
        'page':page
    }
    return render(request,'radio_lab/lab_queue.html',context)


@login_required(login_url='login')
def lab_waiting_count(request):
    # Count unique patients
    count = RadiologyLab.objects.filter(
        radiolab_waiting_status=0,
        billing_waiting_status=0,
        item_type='L',
        created_date__gte=timezone.now() - timedelta(hours=24),
        patient__isnull=False  # Exclude records without patients
    ).values('patient').distinct().count()
    
    return JsonResponse({'count': count})



# Test results
@login_required(login_url='login')
def lab_investigations(request, key):
    page = 'lab-results'
    patient = get_object_or_404(PatientProfile, id=key)
    reports = RadiologyLab.objects.filter(
        patient=patient,
        radiolab_waiting_status=0,
        billing_waiting_status=0,
        item_type='L',
        created_date__gte=timezone.now() - timedelta(hours=24)
    ).order_by('-created_date')
    
    # Get available lab investigations from inventory
    lab_investigations = RadioLabInventory.objects.filter(type='L')
    
    # Get existing lab results for this patient
    results = LabResult.objects.filter(patient=patient).order_by('-created_date')
    
    # can_edit_delete flag to each result
    time_limit = timezone.now() - timedelta(hours=24)
    for result in results:
        result.can_edit_delete = result.created_date > time_limit
    
    context = {
        'patient': patient,
        'reports': reports,
        'lab_investigations': lab_investigations,
        'existing_lab_results': results, 
        'page':page,
    }
    return render(request, 'radio_lab/lab_investigations.html', context)


@login_required(login_url='login')
def add_lab_result(request, key):
    if request.method != 'POST':
        return redirect('lab_investigation', key=key)

    patient = get_object_or_404(PatientProfile, id=key)

    if not request.user.pin == int(request.POST.get('pin_code')) or request.user.pin == 0:
        messages.error(request, 'Incorrect Pin Code Entry! Please set your pin')
        return redirect('lab_investigation', key=key)
    
    radiolab_id = request.POST.get('radiolab_id')
    investigation = request.POST.get('investigation')
    results = request.POST.get('results', '')

    if not radiolab_id:
        messages.error(request, 'Invalid investigation selected.')
        return redirect('lab_investigation', key=key)


    # Fetch EXACT row
    radiology_lab = get_object_or_404(
        RadiologyLab,
        id=radiolab_id,
        patient=patient,
        item_type='L',
        radiolab_waiting_status=0
    )

    # Create lab result
    LabResult.objects.create(
        investigation=radiology_lab.item,
        results=results,
        patient=patient,
        staff=request.user
    )

    # Update ONLY this investigation
    radiology_lab.radiolab_waiting_status = 1
    radiology_lab.save(update_fields=['radiolab_waiting_status'])

    messages.success(request, 'Lab result added successfully.')
    return redirect('lab_investigation', key=key)


@login_required(login_url='login')
def edit_lab_result(request, key, result_id):
    lab_result = get_object_or_404(LabResult, id=result_id, patient_id=key)
    
    # Check if within 24-hour edit window
    time_limit = timezone.now() - timedelta(hours=24)
    if lab_result.created_date < time_limit:
        messages.error(request, 'Edit time has expired. Records can only be edited within 24 hours.')
        return redirect('lab_investigation', key=key)
    
    if request.method == 'POST':
        # Get data from form
        results = request.POST.get('results', '')
        
        # Update the lab result
        lab_result.results = results
        lab_result.save()
        
        messages.success(request, 'Lab result updated successfully.')
        return redirect('lab_investigation', key=key)
    
    # GET request - show edit form
    lab_investigations = RadioLabInventory.objects.filter(type='L')
    
    context = {
        'patient': lab_result.patient,
        'lab_result': lab_result,
        'lab_investigations': lab_investigations,
        'is_editing': True,
        'page':'edit-lab-result',
    }
    return render(request, 'radio_lab/lab_investigations.html', context)

@login_required
def delete_lab_result(request, key, result_id):
    lab_result = get_object_or_404(LabResult, id=result_id, patient_id=key)
    
    # Check if within 24-hour delete window
    time_limit = timezone.now() - timedelta(hours=24)
    if lab_result.created_date < time_limit:
        messages.error(request, 'Delete time has expired. Records can only be deleted within 24 hours.')
        return redirect('lab_investigation', key=key)
    
    if request.method == 'POST':
        lab_result.delete()
        messages.success(request, 'Lab result deleted successfully.')
    
    return redirect('lab_investigation', key=key)


@login_required(login_url='login')
def test_history(request, key):
    patient = get_object_or_404(PatientProfile, id=key)
    results = LabResult.objects.filter(patient=patient).order_by('-created_date')
    page = 'test-history'
    context = {
        'patient': patient,
        'existing_lab_results': results, 
        'page':page
    }
    return render(request, 'radio_lab/lab_investigations.html', context)


@login_required(login_url='login')
def get_lab_results(request, key):
    patient = get_object_or_404(PatientProfile, id=key)
    staff = None
    results = LabResult.objects.filter(patient=patient).order_by('-created_date')
    for item in results:
        staff = item.staff.fullname
    context = {
        'patient': patient,
        'lab_results': results, 
        'page':'get_lab_result',
        'staff':staff,
    }
    return render(request,'radio_lab/get_results.html', context)


@login_required(login_url='login')
def get_lab_results_today(request, key):
    patient = get_object_or_404(PatientProfile, id=key)
    staff = None
    results_today = LabResult.objects.filter(patient=patient,created_date__gte=timezone.now() - timedelta(hours=24)).order_by('-created_date')
    for item in results_today:
        staff = item.staff.fullname
    context = {
        'patient': patient,
        'lab_results_today': results_today, 
        'page':'get_lab_result_today',
        'staff':staff,
    }
    return render(request,'radio_lab/get_results.html', context)


def generate_lab_results_pdf(patient, records, request):
    """Generate PDF for lab results using reportlab"""
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                           rightMargin=72, leftMargin=72,
                           topMargin=72, bottomMargin=72)
    
    styles = getSampleStyleSheet()
    story = []
    
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
    
    # Patient Details
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
    
    story.append(Paragraph("LAB RESULTS", title_style))
    story.append(Spacer(1, 10))
    
    if records:
        table_data = [['S/N', 'Test', 'Result', 'Date']]
        
        for idx, record in enumerate(records, 1):
            created_date = record.get('created_date', 'N/A')
        
            if isinstance(created_date, str) and len(created_date) > 16:
                created_date = created_date[:16]
            
            table_data.append([
                str(idx),
                str(record.get('test', 'N/A')),
                str(record.get('result', 'N/A')),
                str(created_date)
            ])
        
        result_table = Table(table_data, colWidths=[50, 150, 250, 120])
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
def send_lab_results_email(request):
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
        pdf_buffer = generate_lab_results_pdf(patient, records, request)
        
        # Build email body
        current_time = time.localtime()  
        date_str = time.strftime("%Y-%m-%d", current_time)
        time_str = time.strftime("%Y%m%d_%H%M%S", current_time)
        datetime_str = time.strftime("%Y-%m-%d %H:%M:%S", current_time)
        
        email_body = f"""
            ISALU HOSPITALS LIMITED
            Email: it@isaluhospitals.com | Phone: 08099902223

            Dear {patient.get_full_name()},

            Please find attached your lab results as requested.

            {'Additional Message: ' + message if message else ''}

            Results Summary:
            - Total Tests: {len(records)}
            - Date Generated: {datetime_str}

            For any questions or concerns, please contact our lab department.

            Best regards,
            Laboratory Department
            ISALU HOSPITALS LIMITED
            """
        
        email = EmailMessage(
            subject=f'Lab Results for {patient.get_full_name()} - {date_str}',
            body=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[patient.email_address],
            reply_to=['it@isaluhospitals.com'],
        )
        
        # Attach the PDF 
        filename = f'lab_results_{patient.hospital_number}_{time_str}.pdf'
        email.attach(filename, pdf_buffer.getvalue(), 'application/pdf')
        
        email.send()
        
        return JsonResponse({
            'success': True, 
            'message': f'Lab results sent to {patient.email_address}'
        })
        
    except PatientProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Patient not found'}, status=404)
    except Exception as e:
        import traceback
        print("FULL ERROR:", traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required(login_url='login')
@csrf_exempt
def save_signature_session(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            request.session['temp_signature'] = data.get('signature')
            request.session['signatory_info'] = {
                'name': data.get('name'),
                'title': data.get('title'),
                'date': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }
            request.session.modified = True
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=400)


@login_required(login_url='login')
def clear_signature_session(request):
    """Clear signature from session"""
    if request.method == 'POST':
        if 'temp_signature' in request.session:
            del request.session['temp_signature']
        if 'signatory_info' in request.session:
            del request.session['signatory_info']
        request.session.modified = True
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=400)

@login_required(login_url='login')
def completed_lab_results(request):
    page = 'completed_lab_result' 
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

    return render(request, 'radio_lab/completed_list.html', {
        'page': page,
        'counts': lab_result_complete.count(), 
        'lab_result_complete': lab_result_complete
    })

# ------------------Radiology----------------

@login_required(login_url='login')
def scan_inventory(request):
    scan_records = RadioLabInventory.objects.filter(type='R')
    counts = 250
    contxt = {
        'counts':counts,
        'scan_records':scan_records,
        'page':'scan-inventory',
    }
    return render(request, 'radio_lab/scan_inventory.html',contxt)


@login_required(login_url='login')
@transaction.atomic()
def upload_scantest_from_excel(request):
    scan_records = RadioLabInventory.objects.filter(type='R')
    counts = scan_records.count()
    page = 'upload-scan'
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        try:
            # Save uploaded file temporarily
            fs = FileSystemStorage()
            filename = fs.save(excel_file.name, excel_file)
            file_path = fs.path(filename)

            # Read Excel file
            df = pd.read_excel(file_path)

            created_count = 0
            updated_count = 0

            for index, row in df.iterrows():
                # Required fields
                item_id = str(row.get('item_id')).strip() if pd.notna(row.get('item_id')) else ''
                item = str(row.get('item')).strip() if pd.notna(row.get('item')) else ''


                # Handle required numeric fields
                try:
                    rate = Decimal(row['rate']) if pd.notna(row.get('rate')) else None
                except:
                    messages.warning(request, f"Invalid rate in row {index+2}. Skipping row.")
                    continue

                # Check required
                if not all([item_id, item, rate is not None]):
                    messages.warning(request, f"Missing required fields in row {index+2}. Skipping row.")
                    continue

                test, created = RadioLabInventory.objects.get_or_create(
                    item_id=item_id,
                    item=item,
                    type='R',
                    defaults={
                        'rate': rate,
                    }
                )

                if not created:
                    test.rate = rate

                # Staff assignment
                test.staff = request.user
                test.save()

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            fs.delete(filename)
            messages.success(request, f"Import complete: {created_count} created, {updated_count} updated.")

        except Exception as e:
            messages.error(request, f"Error processing file: {e}")

        return redirect('scan_inventory') 
    context = {
        'page':page,
        'scan_records':scan_records,
        'counts':counts
    }
    return render(request, 'radio_lab/scan_inventory.html',context)


@login_required(login_url='login')
@csrf_exempt
def save_scan_inventory(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            #  Ensure there's at least one item
            items = data.get("items", [])
            if not items:
                return JsonResponse({"success": False, "error": "At least one scan test is required."}, status=400)

            with transaction.atomic():
                for item in items:
                    item_name = item.get("item") 
                    item_id = item.get("item_id")
                    rate = item.get("rate")

                    #  Validate fields
                    if not item_name or not rate:
                        return JsonResponse({"success": False, "error": "Each scan test must have a name and rate."}, status=400)

                    try:
                        rate = float(rate)
                        if rate <= 0:
                            return JsonResponse({"success": False, "error": "Rate must be greater than zero."}, status=400)
                    except ValueError:
                        return JsonResponse({"success": False, "error": "Invalid rate value."}, status=400)

                    #  Save record
                    RadioLabInventory.objects.create(
                        item=item_name.strip(),
                        item_id=item_id.strip() if item_id else None,
                        rate=rate,
                        type="R",  # Always scan test
                        staff=request.user
                    )

            return JsonResponse({"success": True})

        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)

    return JsonResponse({"success": False, "error": "Invalid request method."}, status=405)


@login_required(login_url='login')
def review_scan_inventory(request):
    test_items = RadioLabInventory.objects.filter(type='R')
    context = {
        'test_items': test_items,
        'page':'scan-review'
    }
    return render(request, 'radio_lab/scan_review.html', context)


# Delete scan test
@login_required(login_url='login')
@require_POST
def delete_scan_test(request, pk):
    try:
        test = get_object_or_404(RadioLabInventory, pk=pk)
        test.delete()
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


# Modify scan test
@login_required(login_url='login')
@require_POST
def modify_scan_test(request, pk):
    test = get_object_or_404(RadioLabInventory, pk=pk)

    item = request.POST.get("item")
    item_id = request.POST.get("item_id")
    rate = request.POST.get("rate")

    if not item or not rate:
        return JsonResponse({"success": False, "error": "Item and Rate are required."}, status=400)

    try:
        test.item = item.strip()
        test.item_id = item_id.strip() if item_id else None
        test.rate = rate
        test.save()
        return JsonResponse({
            "success": True,
            "item": test.item,
            "item_id": test.item_id,
            "rate": str(test.rate)
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


# Patient waiting List (Radiology)
@login_required(login_url='login')
def fetch_scan_queue(request):
    queue = RadiologyLab.objects.filter(
        radiolab_waiting_status=0,
        billing_waiting_status=0,item_type = 'R',
        created_date__gte=timezone.now() - timedelta(hours=24), patient__isnull=False
    ).select_related('patient', 'staff').order_by('patient_id', '-created_date')
    
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
            'attendant': f"Dr. {record.staff.fullname}" if record.staff else "N/A",
            'created_date': record.created_date.strftime('%Y-%m-%d %H:%M'),
        })

    return JsonResponse({
        'data': data,
        'count': len(data)
    })


@login_required(login_url='login')
def load_scan_queue(request):
    page = 'scan-queue'
    context = {
        'page':page
    }
    return render(request,'radio_lab/scan_queue.html',context)


@login_required(login_url='login')
def scan_waiting_count(request):
    # Count unique patients
    count = RadiologyLab.objects.filter(
        radiolab_waiting_status=0,
        billing_waiting_status=0,
        item_type='R',
        created_date__gte=timezone.now() - timedelta(hours=24),
        patient__isnull=False  # Exclude records without patients
    ).values('patient').distinct().count()
    
    return JsonResponse({'count': count})


# scan results
@login_required(login_url='login')
def scan_investigations(request, key):
    page = 'scan-results'
    patient = get_object_or_404(PatientProfile, id=key)
    reports = RadiologyLab.objects.filter(
        patient=patient,
        radiolab_waiting_status=0,
        billing_waiting_status=0,
        item_type='R',
        created_date__gte=timezone.now() - timedelta(hours=24)
    ).order_by('-created_date')
    
    # Get available scan investigations from inventory
    scan_investigations = RadioLabInventory.objects.filter(type='R')
    
    # Get existing scan results for this patient
    results = ScanResult.objects.filter(patient=patient).order_by('-created_date')
    
    # can_edit_delete flag to each result
    time_limit = timezone.now() - timedelta(hours=24)
    for result in results:
        result.can_edit_delete = result.created_date > time_limit
    
    context = {
        'patient': patient,
        'reports': reports,
        'scan_investigations': scan_investigations,
        'existing_scan_results': results, 
        'page':page,
    }
    return render(request, 'radio_lab/scan_investigations.html', context)

@login_required
def add_scan_result(request, key):
    if request.method != 'POST':
        return redirect('scan_investigation', key=key)

    patient = get_object_or_404(PatientProfile, id=key)

    if not request.user.pin == int(request.POST.get('pin_code')) or request.user.pin == 0:
        messages.error(request, 'Incorrect Pin Code Entry! Please set your pin')
        return redirect('scan_investigation', key=key)
    
    radiolab_id = request.POST.get('radiolab_id')
    investigation = request.POST.get('investigation')
    results = request.POST.get('results', '')
    scan_image = request.FILES.get('scan_image')

    if not radiolab_id:
        messages.error(request, 'Invalid investigation selected.')
        return redirect('scan_investigation', key=key)

    if scan_image and scan_image.size > 200000:
        messages.error(request, 'File Size is too big, maximum of 200KB is required')
        return redirect('scan_investigation', key=key)

    # Fetch EXACT row
    radiology_lab = get_object_or_404(
        RadiologyLab,
        id=radiolab_id,
        patient=patient,
        item_type='R',
        radiolab_waiting_status=0
    )

    # Create scan result
    ScanResult.objects.create(
        investigation=radiology_lab.item,
        results=results,
        scan=scan_image,
        patient=patient,
        staff=request.user
    )

    # Update ONLY this investigation
    radiology_lab.radiolab_waiting_status = 1
    radiology_lab.save(update_fields=['radiolab_waiting_status'])

    messages.success(request, 'Scan result added successfully.')
    return redirect('scan_investigation', key=key)


@login_required(login_url='login')
def edit_scan_result(request, key, result_id):
    scan_result = get_object_or_404(ScanResult, id=result_id, patient_id=key)
    
    # Check if within 24-hour edit window
    time_limit = timezone.now() - timedelta(hours=24)
    if scan_result.created_date < time_limit:
        messages.error(request, 'Edit time has expired. Records can only be edited within 24 hours.')
        return redirect('scan_investigation', key=key)
    
    if request.method == 'POST':
        # Get data from form
        results = request.POST.get('results', '')
        
        # Update the scan result
        scan_result.results = results
        scan_result.save()
        
        messages.success(request, 'Scan result updated successfully.')
        return redirect('scan_investigation', key=key)
    
    # GET request - show edit form
    scan_investigations = RadioLabInventory.objects.filter(type='R')
    
    context = {
        'patient': scan_result.patient,
        'scan_result': scan_result,
        'scan_investigations': scan_investigations,
        'is_editing': True,
        'page':'edit-scan-result',
    }
    return render(request, 'radio_lab/scan_investigations.html', context)


@login_required(login_url='login')
def delete_scan_result(request, key, result_id):
    scan_result = get_object_or_404(ScanResult, id=result_id, patient_id=key)
    
    # Check if within 24-hour delete window
    time_limit = timezone.now() - timedelta(hours=24)
    if scan_result.created_date < time_limit:
        messages.error(request, 'Delete time has expired. Records can only be deleted within 24 hours.')
        return redirect('scan_investigation', key=key)
    
    if request.method == 'POST':
        scan_result.delete()
        messages.success(request, 'Scan result deleted successfully.')
    
    return redirect('scan_investigation', key=key)


@login_required(login_url='login')
def scan_history(request, key):
    patient = get_object_or_404(PatientProfile, id=key)
    results = ScanResult.objects.filter(patient=patient).order_by('-created_date')
    page = 'scan-result-history'
    context = {
        'patient': patient,
        'existing_scan_results': results, 
        'page':page
    }
    return render(request, 'radio_lab/scan_investigations.html', context)


@login_required(login_url='login')
def get_scan_results(request, key):
    patient = get_object_or_404(PatientProfile, id=key)
    staff = None
    results = ScanResult.objects.filter(patient=patient).order_by('-created_date')
    for item in results:
        staff = item.staff.fullname
    context = {
        'patient': patient,
        'scan_results': results, 
        'page':'get_scan_result',
        'staff':staff,
    }
    return render(request,'radio_lab/get_scan_results.html', context)


@login_required(login_url='login')
def get_scan_results_today(request, key):
    patient = get_object_or_404(PatientProfile, id=key)
    staff = None
    results_today = ScanResult.objects.filter(patient=patient,created_date__gte=timezone.now() - timedelta(hours=24)).order_by('-created_date')
    for item in results_today:
        staff = item.staff.fullname
    context = {
        'patient': patient,
        'scan_results_today': results_today, 
        'page':'get_scan_result_today',
        'staff':staff,
    }
    return render(request,'radio_lab/get_scan_results.html', context)


def generate_scan_results_pdf(patient, records, request):
    """Generate PDF for scan results using reportlab"""
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                           rightMargin=72, leftMargin=72,
                           topMargin=72, bottomMargin=72)
    
    styles = getSampleStyleSheet()
    story = []
    
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
    
    # Patient Details
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
    
    story.append(Paragraph("SCAN RESULTS", title_style))
    story.append(Spacer(1, 10))
    
    if records:
        table_data = [['S/N', 'Test', 'Result', 'Date']]
        
        for idx, record in enumerate(records, 1):
            created_date = record.get('created_date', 'N/A')
            # Safe handling - don't call len() on int
            if isinstance(created_date, str) and len(created_date) > 16:
                created_date = created_date[:16]
            
            table_data.append([
                str(idx),
                str(record.get('test', 'N/A')),
                str(record.get('result', 'N/A')),
                str(created_date)
            ])
        
        result_table = Table(table_data, colWidths=[50, 150, 250, 120])
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
def send_scan_results_email(request):
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
        pdf_buffer = generate_scan_results_pdf(patient, records, request)
        
        # Build email body
        current_time = time.localtime()  
        date_str = time.strftime("%Y-%m-%d", current_time)
        time_str = time.strftime("%Y%m%d_%H%M%S", current_time)
        datetime_str = time.strftime("%Y-%m-%d %H:%M:%S", current_time)
        
        email_body = f"""
            ISALU HOSPITALS LIMITED
            Email: it@isaluhospitals.com | Phone: 08099902223

            Dear {patient.get_full_name()},

            Please find attached your scan results as requested.

            {'Additional Message: ' + message if message else ''}

            Results Summary:
            - Total Scans: {len(records)}
            - Date Generated: {datetime_str}

            For any questions or concerns, please contact our radiology department.

            Best regards,
            Radiology Department
            ISALU HOSPITALS LIMITED
        """
        
        email = EmailMessage(
            subject=f'Scan Results for {patient.get_full_name()} - {date_str}',
            body=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[patient.email_address],
            reply_to=['it@isaluhospitals.com'],
        )
        
        # Attach the PDF 
        filename = f'scan_results_{patient.hospital_number}_{time_str}.pdf'
        email.attach(filename, pdf_buffer.getvalue(), 'application/pdf')
        
        email.send()
        
        return JsonResponse({
            'success': True, 
            'message': f'Scan results sent to {patient.email_address}'
        })
        
    except PatientProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Patient not found'}, status=404)
    except Exception as e:
        import traceback
        print("FULL ERROR:", traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required(login_url='login')
def completed_scan_results(request):
    page = 'completed_scan_result' 
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

    return render(request, 'radio_lab/completed_list.html', {
        'page': page,
        'counts': scan_result_complete.count(), 
        'scan_result_complete': scan_result_complete
    })


