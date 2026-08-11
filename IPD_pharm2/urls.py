from django.urls import path
from . import views

urlpatterns = [

    path('ipd2-inventory', views.view_ipd2_product, name = "view_ipd2_product"),
    path('ipd2-stock', views.generate_report_ipd2, name = "ipd2_stock"),
    path('ipd2-stock-stock', views.ipd2_out_stock_report, name = "ipd2_out_stock"),
    path('ipd2-returned-stock', views.ipd2_return_stock_report, name = "ipd2_returned_stock"),
    path('update-ipd2-inventory/<str:product_id>/', views.update_ipd2_stock, name = "update_ipd2_stock"),

    path('ipd2-requisitions', views.ipd2_requisitions, name='requisition_ipd2'),
    path('save-ipd2-requisition-form', views.save_ipd2_requisition_form, name='save_ipd2_requisition_form'),
    path('review-requests-ipd2', views.manage_requested_ipd2, name='review_requests_ipd2'),
    path('delete-requested-ipd2-products/<int:product_id>/', views.delete_requested_ipd2_products, name='delete_requested_ipd2_products'),
    path('edit-requested-ipd2-products/<int:product_id>/', views.edit_requested_ipd2_products, name='edit_requested_ipd2_products'),
    path('history-of-ipd2-requests', views.history_of_requested_ipd2_products, name='history_requests_ipd2'),

    path('scan-barcode/', views.barcodeScan, name="scan_barcode"),
 
        # requests from Inventory
    path('inventory-requests-to-ipd2/', views.inventory_requests_to_ipd2, name='inventory_requests_to_ipd2'),
    path('ipd2-approve-inventory-request/<int:pk>/', views.ipd2_approve_inventory_request, name='ipd2_approve_inventory_request'),
    path('ipd2-approve-all-inventory-requests/', views.ipd2_approve_all_inventory_requests, name='ipd2_approve_all_inventory_requests'),
    path('ipd2-decline-inventory-request/<int:pk>/', views.ipd2_decline_inventory_request, name='ipd2_decline_inventory_request'),
    path('request-history-to-ipd2', views.request_history_to_ipd2, name='request_history_to_ipd2'),

     # Patient's Waiting list
    path('fetch-ipd2pharm-queue', views.fetch_ipd2pharm_queue, name='fetch_ipd2pharm_queue'),
    path('ipd-ipd2pharm-queue', views.load_ipd2pharm_queue, name='ipd2pharm_queue'),
    path('ipd2pharm-waiting-count/', views.ipd2pharm_waiting_count, name='ipd2pharm_waiting_count'),
    path('ipd2-completed/', views.ipd2_pharm_complete, name='ipd2_pharm_complete'),

    # Drug dispenser

    path('ipd2-prescribed-drugs/<int:patient_id>/', views.ipd2_doctor_prescriptions, name='ipd2_prescribe_drugs'),
    path('ipd2-approve-prescription/', views.ipd2_approve_prescription, name='ipd2_approve_prescription'),
    path('ipd2-decline-prescription/', views.ipd2_decline_prescription, name='ipd2_decline_prescription'),
    path('ipd2-dispensed-history/<int:patient_id>/', views.ipd2_dispense_history, name='ipd2_dispense_history'),

    path('ipd2-download-prescriptions-today/<int:patient_id>/', views.ipd2_download_prescriptions_today, name='ipd2_download_prescriptions_today'),
    path('ipd2-download-prescriptions/<int:patient_id>/', views.ipd2_download_prescriptions, name='ipd2_download_prescriptions'),
    path('send-ipd2-report-email/', views.send_ipd2_prescription_email, name='send_ipd2_prescription_email'),

    path('pharm2-patient-profile/<int:patient_id>/', views.pharm2_patient_profile, name='pharm2_patient_profile'),


]
