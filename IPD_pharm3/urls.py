from django.urls import path
from . import views

urlpatterns = [

    path('ipd3-inventory', views.view_ipd3_product, name = "view_ipd3_product"),
    path('ipd3-stock', views.generate_report_ipd3, name = "ipd3_stock"),
    path('ipd3-stock-stock', views.ipd3_out_stock_report, name = "ipd3_out_stock"),
    path('ipd3-returned-stock', views.ipd3_return_stock_report, name = "ipd3_returned_stock"),
    path('update-ipd3-inventory/<str:product_id>/', views.update_ipd3_stock, name = "update_ipd3_stock"),

    path('ipd3-requisitions', views.ipd3_requisitions, name='requisition_ipd3'),
    path('save-ipd3-requisition-form', views.save_ipd3_requisition_form, name='save_ipd3_requisition_form'),
    path('review-requests-ipd3', views.manage_requested_ipd3, name='review_requests_ipd3'),
    path('delete-requested-ipd3-products/<int:product_id>/', views.delete_requested_ipd3_products, name='delete_requested_ipd3_products'),
    path('edit-requested-ipd3-products/<int:product_id>/', views.edit_requested_ipd3_products, name='edit_requested_ipd3_products'),
    path('history-of-ipd3-requests', views.history_of_requested_ipd3_products, name='history_requests_ipd3'),
 
    path('scan-barcode/', views.barcodeScan, name="scan_barcode"),
 
        # requests from Inventory
    path('inventory-requests-to-ipd3/', views.inventory_requests_to_ipd3, name='inventory_requests_to_ipd3'),
    path('ipd3-approve-inventory-request/<int:pk>/', views.ipd3_approve_inventory_request, name='ipd3_approve_inventory_request'),
    path('ipd3-approve-all-inventory-requests/', views.ipd3_approve_all_inventory_requests, name='ipd3_approve_all_inventory_requests'),
    path('ipd3-decline-inventory-request/<int:pk>/', views.ipd3_decline_inventory_request, name='ipd3_decline_inventory_request'),
    path('request-history-to-ipd3', views.request_history_to_ipd3, name='request_history_to_ipd3'),


     # Patient's Waiting list
    path('fetch-ipd3pharm-queue', views.fetch_ipd3pharm_queue, name='fetch_ipd3pharm_queue'),
    path('ipd-ipd3pharm-queue', views.load_ipd3pharm_queue, name='ipd3pharm_queue'),
    path('ipd3pharm-waiting-count/', views.ipd3pharm_waiting_count, name='ipd3pharm_waiting_count'),
    path('ipd3-completed/', views.ipd3_pharm_complete, name='ipd3_pharm_complete'),

    # Drug dispenser

    path('ipd3-prescribed-drugs/<int:patient_id>/', views.ipd3_doctor_prescriptions, name='ipd3_prescribe_drugs'),
    path('ipd3-approve-prescription/', views.ipd3_approve_prescription, name='ipd3_approve_prescription'),
    path('ipd3-decline-prescription/', views.ipd3_decline_prescription, name='ipd3_decline_prescription'),
    path('ipd3-dispensed-history/<int:patient_id>/', views.ipd3_dispense_history, name='ipd3_dispense_history'),

    path('ipd3-download-prescriptions-today/<int:patient_id>/', views.ipd3_download_prescriptions_today, name='ipd3_download_prescriptions_today'),
    path('ipd3-download-prescriptions/<int:patient_id>/', views.ipd3_download_prescriptions, name='ipd3_download_prescriptions'),
    path('send-ipd3-report-email/', views.send_ipd3_prescription_email, name='send_ipd3_prescription_email'),


    path('pharm3-patient-profile/<int:patient_id>/', views.pharm3_patient_profile, name='pharm3_patient_profile'),

    path('ipd3-cancelled-drugs/', views.ipd3_cancelled_product_list, name='ipd3_cancelled_product_list'),
    path('ipd3-staled-drugs/', views.ipd3_staled_product_list, name='ipd3_staled_product_list'),
    path('ipd3-cancelled-drugs/restore/<int:pk>/', views.ipd3_restore_single_drug, name='ipd3_restore_single_drug'),
    path('ipd3-cancelled-drugs/restore-all/', views.ipd3_restore_all_drugs, name='ipd3_restore_all_drugs'),


]
