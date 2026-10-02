from django.urls import path
from . import views

urlpatterns = [

    path('opd2-inventory', views.view_opd2_product, name = "view_opd2_product"),
    path('opd2-stock', views.generate_report_opd2, name = "opd2_stock"),
    path('opd2-stock-stock', views.opd2_out_stock_report, name = "opd2_out_stock"),
    path('opd2-returned-stock', views.opd2_return_stock_report, name = "opd2_returned_stock"),
    path('update-opd2-inventory/<str:product_id>/', views.update_opd2_stock, name = "update_opd2_stock"),

    path('opd2-requisitions', views.opd2_requisitions, name='requisition_opd2'),
    path('save-opd2-requisition-form', views.save_opd2_requisition_form, name='save_opd2_requisition_form'),
    path('review-requests-opd2', views.manage_requested_opd2, name='review_requests_opd2'),
    path('delete-requested-opd2-products/<int:product_id>/', views.delete_requested_opd2_products, name='delete_requested_opd2_products'),
    path('edit-requested-opd2-products/<int:product_id>/', views.edit_requested_opd2_products, name='edit_requested_opd2_products'),
    path('history-of-opd2-requests', views.history_of_requested_opd2_products, name='history_requests_opd2'),

    path('scan-barcode/', views.barcodeScan, name="scan_barcode"),

        # requests from Inventory
    path('inventory-requests-to-opd2/', views.inventory_requests_to_opd2, name='inventory_requests_to_opd2'),
    path('opd2-approve-inventory-request/<int:pk>/', views.opd2_approve_inventory_request, name='opd2_approve_inventory_request'),
    path('opd2-approve-all-inventory-requests/', views.opd2_approve_all_inventory_requests, name='opd2_approve_all_inventory_requests'),
    path('opd2-decline-inventory-request/<int:pk>/', views.opd2_decline_inventory_request, name='opd2_decline_inventory_request'),
    path('request-history-to-opd2', views.request_history_to_opd2, name='request_history_to_opd2'),


     # Patient's Waiting list
    path('fetch-opd2pharm-queue', views.fetch_opd2pharm_queue, name='fetch_opd2pharm_queue'),
    path('ipd-opd2pharm-queue', views.load_opd2pharm_queue, name='opd2pharm_queue'),
    path('opd2pharm-waiting-count/', views.opd2pharm_waiting_count, name='opd2pharm_waiting_count'),
    path('opd2-completed/', views.opd2_pharm_complete, name='opd2_pharm_complete'),

    # Drug dispenser

    path('opd2-prescribed-drugs/<int:patient_id>/', views.opd2_doctor_prescriptions, name='opd2_prescribe_drugs'),
    path('opd2-approve-prescription/', views.opd2_approve_prescription, name='opd2_approve_prescription'),
    path('opd2-decline-prescription/', views.opd2_decline_prescription, name='opd2_decline_prescription'),
    path('opd2-dispensed-history/<int:patient_id>/', views.opd2_dispense_history, name='opd2_dispense_history'),

    path('opd2-download-prescriptions-today/<int:patient_id>/', views.opd2_download_prescriptions_today, name='opd2_download_prescriptions_today'),
    path('opd2-download-prescriptions/<int:patient_id>/', views.opd2_download_prescriptions, name='opd2_download_prescriptions'),
    path('send-opd2-report-email/', views.send_opd2_prescription_email, name='send_opd2_prescription_email'),


    path('opd-pharm2-patient-profile/<int:patient_id>/', views.opdpharm2_patient_profile, name='opdpharm2_patient_profile'),

    path('opd2-cancelled-drugs/', views.opd2_cancelled_product_list, name='opd2_cancelled_product_list'),
    path('opd2-staled-drugs/', views.opd2_staled_product_list, name='opd2_staled_product_list'),
    path('opd2-cancelled-drugs/restore/<int:pk>/', views.opd2_restore_single_drug, name='opd2_restore_single_drug'),
    path('opd2-cancelled-drugs/restore-all/', views.opd2_restore_all_drugs, name='opd2_restore_all_drugs'),


]
 