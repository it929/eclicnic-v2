from django.urls import path
from . import views

urlpatterns = [

    path('ipd-inventory', views.view_product, name = "view_ipd_product"),
    path('ipd-stock', views.generate_report_ipd, name = "ipd_stock"),
    path('ipd-stock-stock', views.ipd_out_stock_report, name = "ipd_out_stock"),
    path('ipd-returned-stock', views.ipd_return_stock_report, name = "ipd_returned_stock"),
    path('update-ipd-inventory/<str:product_id>/', views.update_ipd_stock, name = "update_ipd_stock"),

    path('ipd-requisitions', views.requisitions, name='requisition_ipd'),
    path('save-ipd-requisition-form', views.save_ipd_requisition_form, name='save_ipd_requisition_form'),
    path('review-requests-ipd', views.manage_requested_ipd, name='review_requests_ipd'),
    path('delete-requested-ipd-products/<int:product_id>/', views.delete_requested_ipd_products, name='delete_requested_ipd_products'),
    path('edit-requested-ipd-products/<int:product_id>/', views.edit_requested_ipd_products, name='edit_requested_ipd_products'),
    path('history-of-ipd-requests', views.history_of_requested_ipd_products, name='history_requests_ipd'),

    path('scan-barcode/', views.barcodeScan, name="scan_barcode"),

        # requests from Inventory
    path('inventory-requests-to-ipd1/', views.inventory_requests_to_ipd1, name='inventory_requests_to_ipd1'),
    path('ipd1-approve-inventory-request/<int:pk>/', views.ipd1_approve_inventory_request, name='ipd1_approve_inventory_request'),
    path('ipd1-approve-all-inventory-requests/', views.ipd1_approve_all_inventory_requests, name='ipd1_approve_all_inventory_requests'),
    path('ipd1-decline-inventory-request/<int:pk>/', views.ipd1_decline_inventory_request, name='ipd1_decline_inventory_request'),
    path('request-history-to-ipd1', views.request_history_to_ipd1, name='request_history_to_ipd1'),

    # Patient's Waiting list
    path('fetch-pharm1-queue', views.fetch_pharm1_queue, name='fetch_pharm1_queue'),
    path('ipd-pharm1-queue', views.load_pharm1_queue, name='ipd_pharm1_queue'),
    path('pharm1-waiting-count/', views.pharm1_waiting_count, name='pharm1_waiting_count'),
    path('ipd1-completed/', views.ipd1_pharm_complete, name='ipd1_pharm_complete'),

    # Drug dispenser

    path('prescribed-drugs/<int:patient_id>/', views.doctor_prescriptions, name='prescribe_drugs'),
    path('approve-prescription/', views.approve_prescription, name='approve_prescription'),
    path('decline-prescription/', views.decline_prescription, name='decline_prescription'),
    path('dispensed-history/<int:patient_id>/', views.ipd1_dispense_history, name='ipd1_dispense_history'),

    path('ipd-download-prescriptions-today/<int:patient_id>/', views.ipd_download_prescriptions_today, name='ipd_download_prescriptions_today'),
    path('ipd-download-prescriptions/<int:patient_id>/', views.ipd_download_prescriptions, name='ipd_download_prescriptions'),
    path('send-ipd-report-email/', views.send_ipd_prescription_email, name='send_ipd_prescription_email'),

    path('pharm-patient-profile/<int:patient_id>/', views.pharm_patient_profile, name='pharm_patient_profile'),

    path('ipd1-cancelled-drugs/', views.ipd1_cancelled_product_list, name='ipd1_cancelled_product_list'),
    path('ipd1-staled-drugs/', views.ipd1_staled_product_list, name='ipd1_staled_product_list'),
    path('ipd1-cancelled-drugs/restore/<int:pk>/', views.ipd1_restore_single_drug, name='ipd1_restore_single_drug'),
    path('ipd1-cancelled-drugs/restore-all/', views.ipd1_restore_all_drugs, name='ipd1_restore_all_drugs'),

]
