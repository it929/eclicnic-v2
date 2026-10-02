from django.urls import path
from . import views

urlpatterns = [

    path('opd-inventory', views.opd_product, name = "view_opd_product"),
    path('opd-stock', views.generate_report_opd, name = "opd_stock"),
    path('opd-out-stock', views.opd_out_stock_report, name = "opd_out_stock"),
    path('update-opd-inventory/<str:product_id>/', views.update_opd_stock, name = "update_opd_stock"),

    path('opd-requisitions', views.requisitions, name='requisition_opd'),
    path('save-opd-requisition-form', views.save_opd_requisition_form, name='save_opd_requisition_form'),
    path('review-requests-opd', views.manage_requested_opd, name='review_requests_opd'),
    path('delete-requested-opd-products/<int:product_id>/', views.delete_requested_opd_products, name='delete_requested_opd_products'),
    path('edit-requested-opd-products/<int:product_id>/', views.edit_requested_opd_products, name='edit_requested_opd_products'),
    path('history-of-opd-requests', views.history_of_requested_opd_products, name='history_requests_opd'),


    path('scan-barcode/', views.barcodeScan, name="scan_barcode"),

    # requests from Inventory
    path('inventory-requests-to-opd/', views.inventory_requests_to_opd, name='inventory_requests_to_opd'),
    path('opd-approve-inventory-request/<int:pk>/', views.opd_approve_inventory_request, name='opd_approve_inventory_request'),
    path('opd-approve-all-inventory-requests/', views.opd_approve_all_inventory_requests, name='opd_approve_all_inventory_requests'),
    path('opd-decline-inventory-request/<int:pk>/', views.opd_decline_inventory_request, name='opd_decline_inventory_request'),
    path('request-history-to-opd', views.request_history_to_opd, name='request_history_to_opd'),


     # Patient's Waiting list
    path('fetch-opdpharm-queue', views.fetch_opdpharm_queue, name='fetch_opdpharm_queue'),
    path('ipd-opdpharm-queue', views.load_opdpharm_queue, name='opdpharm_queue'),
    path('opdpharm-waiting-count/', views.opdpharm_waiting_count, name='opdpharm_waiting_count'),
    path('opd-completed/', views.opd_pharm_complete, name='opd_pharm_complete'),

    # Drug dispenser

    path('opd-prescribed-drugs/<int:patient_id>/', views.opd_doctor_prescriptions, name='opd_prescribe_drugs'),
    path('opd-approve-prescription/', views.opd_approve_prescription, name='opd_approve_prescription'),
    path('opd-decline-prescription/', views.opd_decline_prescription, name='opd_decline_prescription'),
    path('opd-dispensed-history/<int:patient_id>/', views.opd_dispense_history, name='opd_dispense_history'),

    path('opd-download-prescriptions-today/<int:patient_id>/', views.opd_download_prescriptions_today, name='opd_download_prescriptions_today'),
    path('opd-download-prescriptions/<int:patient_id>/', views.opd_download_prescriptions, name='opd_download_prescriptions'),
    path('send-opd-report-email/', views.send_opd_prescription_email, name='send_opd_prescription_email'),

    path('opd-pharm-patient-profile/<int:patient_id>/', views.opdpharm_patient_profile, name='opdpharm_patient_profile'),

    path('opd1-cancelled-drugs/', views.opd1_cancelled_product_list, name='opd1_cancelled_product_list'),
    path('opd1-staled-drugs/', views.opd1_staled_product_list, name='opd1_staled_product_list'),
    path('opd1-cancelled-drugs/restore/<int:pk>/', views.opd1_restore_single_drug, name='opd1_restore_single_drug'),
    path('opd1-cancelled-drugs/restore-all/', views.opd1_restore_all_drugs, name='opd1_restore_all_drugs'),
    
    
] 
