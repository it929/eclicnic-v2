# urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Nursess URLs...
    path('ajax/waiting-list/', views.fetch_waiting_list, name='fetch_waiting_list'),
    path('nurse-waiting-list/', views.load_nurse_queue, name='waiting_list'),
    path('nurse-done-list/', views.nurse_done_list, name='done_list'),
    path('attendance-today/', views.attendants_today, name='attendants_today'),
    path('nurse-waiting-count/', views.nurse_waiting_count, name='nurse_waiting_count'),
    path('patient-details/<str:key>/', views.operations_profile, name='operations_profile'),
    path('patient-details-nur/<str:key>/', views.operations_profile_nur, name='operations_profile_nur'),
    path('patient-details-lab/<str:key>/', views.operations_profile_lab, name='operations_profile_lab'),
    path('patient-details-rad/<str:key>/', views.operations_profile_rad, name='operations_profile_rad'),
    path('background-health/<str:key>/', views.background_health, name='background_health'),
    path('vital-signs/<str:key>/', views.vital_signs, name='vital_signs'),
    path('modify-vital-signs/<str:key>/', views.manage_vital_signs, name='modify_vital_signs'),
    # Front Desk URLs
    path('attendance-all/', views.attendants_all, name='attendants_all'),
    path('export-attendance/', views.export_to_excel, name='export_attendance'),
    # End of Front Desk URLs
    
    # Doctors URLs...
    path('doctor/waiting-list/', views.fetch_doctors_queue, name='doctors_queue_list'),
    path('doctors-queue/', views.load_doctor_queue, name='doctor_waiting_list'),
    path('doctor-waiting-count/', views.doctor_waiting_count, name='doctor_waiting_count'),
    path('doctor-done-list/', views.doctor_done_list, name='doctor_done_list'),
    path('doctor-consultation/<str:key>/', views.doctor_nurse_report, name='doctor_consultation'),
    path('doctors-queue-all/', views.doctor_waiting_list_all, name='doctor_waiting_list_all'),
    

    path('complaints/<str:patient_id>/', views.complaint_search, name='complaint_search'),
    path('ajax/search-complaints/', views.ajax_search_complaints, name='ajax_search_complaints'),
    path('ajax/search-diagnoses/', views.ajax_search_diagnoses, name='ajax_search_diagnoses'),
    path('ajax/save-encounter/', views.save_encounter, name='save_encounter'),
    # PatientEncounter URLs (existing)
    path('edit-encounter/<int:encounter_id>/', views.edit_encounter, name='edit_encounter'),
    path('update-encounter/<int:encounter_id>/', views.update_encounter, name='update_encounter'),
    path('delete-encounter/<int:encounter_id>/', views.delete_encounter, name='delete_encounter'),
    # PatientReferral URLs
    path('edit-referral/<int:referral_id>/', views.edit_referral, name='edit_referral'),
    path('update-referral/<int:referral_id>/', views.update_referral, name='update_referral'),
    path('delete-referral/<int:referral_id>/', views.delete_referral, name='delete_referral'),
    path('ajax/save-referral/', views.save_referral, name='save_referral'),

    # PatientOtherDetails URLs
    path('edit-other-details/<int:details_id>/', views.edit_other_details, name='edit_other_details'),
    path('update-other-details/<int:details_id>/', views.update_other_details, name='update_other_details'),
    path('delete-other-details/<int:details_id>/', views.delete_other_details, name='delete_other_details'),
    # PatientFollowUp URLs
    path('edit-followup/<int:followup_id>/', views.edit_followup, name='edit_followup'),
    path('update-followup/<int:followup_id>/', views.update_followup, name='update_followup'),
    path('delete-followup/<int:followup_id>/', views.delete_followup, name='delete_followup'),
    path('ajax/save-followup/', views.save_followup, name='save_followup'),
    path('ajax/save-otherdetails/', views.save_other_details, name='save_other_details'),
    # patientAppointment URLs
    path('appointments/create/', views.create_appointment, name='create_appointment'),
    path('appointments/<int:pk>/get/', views.get_appointment, name='get_appointment'),
    path('appointments/<int:pk>/update/', views.update_appointment, name='update_appointment'),
    path('appointments/<int:pk>/delete/', views.delete_appointment, name='delete_appointment'),


    # case notes
    path('case_note/<int:patient_id>/', views.get_case_note, name='get_case_note'),
    path('filtered_case_note/<int:patient_id>/', views.get_filtered_case_note, name='get_filtered_case_note'),

    path('save-transcript/<str:patient_id>/', views.save_transcript, name='save_transcript'),
    path('use-transcriptor/<str:patient_id>/', views.use_transcriptor, name='use_transcript'),  
    path('administer-drugs/<int:patient_id>/', views.administer_drugs, name='administer_drugs'),
    path('search-products/', views.search_products, name='search_products'),
    path('add-drug-item/', views.add_drug_item, name='add_drug_item'),
    
    path('update-drug-route/', views.update_drug_route, name='update_drug_route'),
    path('update-drug-frequency/', views.update_drug_frequency, name='update_drug_frequency'),
    path('update-drug-dose/', views.update_drug_dose, name='update_drug_dose'),
    path('update-drug-duration/', views.update_drug_duration, name='update_drug_duration'),
    path('update-drug-quantity/', views.update_drug_quantity, name='update_drug_quantity'), 
    path('update-drug-notes/', views.update_drug_notes, name='update_drug_notes'),
    path('update-drug-start-date/', views.update_drug_start_date, name='update_drug_start_date'),
    path('update-complete-drug-item/', views.update_complete_drug_item, name='update_complete_drug_item'),
    path('update-exception-bill-status/', views.update_exception_bill_status, name='update_exception_bill_status'),

    path('remove-drug-item/', views.remove_drug_item, name='remove_drug_item'),
    path('clear-drug-session/', views.clear_drug_session, name='clear_drug_session'), 
    path('get-session-items/', views.get_session_items, name='get_session_items'),
    path('get-stores/', views.get_stores, name='get_stores'),
    path('delete-drug/<str:store_id>/<int:record_id>/', views.delete_drug_by_store, name='delete_drug_by_store'),

    # Drug Prescriptions II (No charge prescriptions)
    path('search-inventory/', views.search_inventory, name='search_inventory'),
    path('save-prescription/<int:patient_id>/', views.save_prescription, name='save_prescription'),
    path('download-written-prescriptions/<int:patient_id>/', views.download_written_prescriptions, name='download_written_prescriptions'),
    path('send-written-report-email/', views.send_written_prescription_email, name='send_written_prescription_email'),

    # Other service requests
    path('get-visit-purpose-price/', views.get_visit_purpose_price, name='get_visit_purpose_price'),
    path('delete-other-service/<int:service_id>/', views.delete_other_service, name='delete_other_service'),
    
    # lab and radio search by doctor
    path('api/product-search/', views.product_search_api, name='product_search_api'),

    # Lab Request
    path('search-lab-tests/', views.product_search_laboratory, name='search_lab_tests'),
    path('save-lab-requests/', views.save_lab_requests, name='save_lab_requests'),
    path('delete-doctor-to-laboratory-test/<int:product_id>/', views.delete_requested_test, name='delete_doctor_to_laboratory_test'),
    # Lab Results
    path('lab-results-waiting-list', views.load_lab_results_queue, name = "lab_results_waiting"),
    path('lab-results-queue', views.fetch_lab_results_queue, name='fetch_lab_results_queue'),
    path('lab-results-waiting-count/', views.lab_results_waiting_count, name='lab_results_waiting_count'),

    # Scan Request
    path('search-radio-scans/', views.product_search_radiology, name='search_radio_scans'),
    path('save-scan-requests/', views.save_radio_requests, name='save_scan_requests'),
    path('delete-doctor-to-radiology-scan/<int:product_id>/', views.delete_requested_scan, name='delete_doctor_to_radiology_scan'),
    # Scan Results
    path('scan-results-waiting-list', views.load_scan_results_queue, name = "scan_results_waiting"),
    path('scan-results-queue', views.fetch_scan_results_queue, name='fetch_scan_results_queue'),
    path('scan-results-waiting-count/', views.scan_results_waiting_count, name='scan_results_waiting_count'),
    # ICD-11
    path('icd11/search/<int:patient_id>/', views.icd11_search_view, name='icd11_search'),
    path('icd11/autocomplete/', views.icd11_autocomplete, name='icd11_autocomplete'),
    path('patient/<str:patient_id>/diagnosis/add/', views.add_diagnosis, name='add_diagnosis'),
    path('patient/<str:patient_id>/diagnoses/', views.patient_diagnoses, name='patient_diagnoses'),
    
    # clinical results
    path('clinical-results/<int:patient_id>/', views.clinical_results, name='clinical_results'),
    path('print-clinical-results-pdf/<int:patient_id>/', views.print_clinical_results_pdf, name='print_clinical_results_pdf'),
    path('print-clinical-results-browser/<int:patient_id>/', views.print_clinical_results_browser, name='print_clinical_results_browser'),

    # mark for completions
    path('mark-for-completions/<int:patient_id>/', views.mark_for_completion, name='mark_for_completion'),
    path('api/mark-lab-results/<int:patient_id>/', views.mark_lab_results_completed, name='mark_lab_results_completed'),
    path('api/mark-scan-results/<int:patient_id>/', views.mark_scan_results_completed, name='mark_scan_results_completed'),
    path('api/mark-encounter/<int:patient_id>/', views.mark_encounter_completed, name='mark_encounter_completed'),


    # path('drugs/', views.get_drug, name='g_drugs'),
    # path('save-administered-drugs/', views.save_administered_drugs, name='save_administered_drugs'),
    # path('delete-administered-drug/<int:drug_id>/', views.delete_administered_drug, name='delete_administered_drug'),

] 