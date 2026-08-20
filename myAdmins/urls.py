from django.urls import path
from . import views
urlpatterns = [
    # staff managements
    path('myAdmin/', views.admin_home, name='admin_home'),
    path('staff-verification/', views.verify_staff, name='verify_staff'),
    path('staffID-format', views.download_import_staffID_template, name = "download_staffID_format"),
    path('staff/delete/<int:pk>/', views.delete_staff_id, name='delete_staff'),
    path('manage-staff/', views.staff_manager, name='staff_manager'),
    path('staff-action/', views.staff_action, name='staff_action'),
    path('user-activities/', views.user_activities, name='all_activities'),  # All users
    path('user-activities/<int:user_id>/', views.user_activities, name='user_activities_detail'),  # Specific user
    path('activity-dashboard/', views.activity_dashboard, name='activity_dashboard'),
    path('online-users/', views.online_users, name='online_users'),
    path('online-users-api/', views.online_users_api, name='online_users_api'),
    path('force-logout-user/<int:user_id>/', views.force_logout_user, name='force_logout_user'),

    # Statistical Insights
    path('diagnosis-analytics/', views.diagnosis_analytics, name='diagnosis_analytics'),
    path('diagnosis-analytics-api/', views.diagnosis_analytics_api, name='diagnosis_analytics_api'),
    path('financial-analytics/', views.financial_analytics, name='financial_analytics'),

    # Queue Monitor

    # 1 Waiting list
    path('nurse-queue-all/', views.nurse_queues_all, name='nurse_queues_all'),
    path('doctor-queue-all/', views.doctor_queues_all, name='doctor_queues_all'),
    path('lab-queue-all/', views.lab_queues_all, name='lab_queues_all'),
    path('lab-result-queue-all/', views.lab_result_queues_all, name='lab_result_queues_all'),
    path('scan-queue-all/', views.scan_queues_all, name='scan_queues_all'),
    path('scan-result-queue-all/', views.scan_result_queues_all, name='scan_result_queues_all'),
    path('drug-requests-ipd1-queue-all/', views.drug_requests_ipd1_queues_all, name='drug_requests_ipd1_queues_all'),
    path('drug-requests-ipd2-queue-all/', views.drug_requests_ipd2_queues_all, name='drug_requests_ipd2_queues_all'),
    path('drug-requests-ipd3-queue-all/', views.drug_requests_ipd3_queues_all, name='drug_requests_ipd3_queues_all'),
    path('drug-requests-opd1-queue-all/', views.drug_requests_opd_queues_all, name='drug_requests_opd1_queues_all'),
    path('drug-requests-opd2-queue-all/', views.drug_requests_opd2_queues_all, name='drug_requests_opd2_queues_all'),

    # 2 Completed lists
    path('nurse-complete-all/', views.nurse_completes_all, name='nurse_completes_all'),
    path('doctor-complete-all/', views.doctor_completes_all, name='doctor_completes_all'),
    path('lab-complete-all/', views.lab_completes_all, name='lab_completes_all'),
    path('lab-result-complete-all/', views.lab_result_completes_all, name='lab_result_completes_all'),
    path('scan-complete-all/', views.scan_completes_all, name='scan_completes_all'),
    path('scan-result-complete-all/', views.scan_result_completes_all, name='scan_result_completes_all'),
    path('drug-requests-ipd1-complete-all/', views.drug_requests_ipd1_completes_all, name='drug_requests_ipd1_completes_all'),
    path('drug-requests-ipd2-complete-all/', views.drug_requests_ipd2_completes_all, name='drug_requests_ipd2_completes_all'),
    path('drug-requests-ipd3-complete-all/', views.drug_requests_ipd3_completes_all, name='drug_requests_ipd3_completes_all'),
    path('drug-requests-opd1-complete-all/', views.drug_requests_opd_completes_all, name='drug_requests_opd1_completes_all'),
    path('drug-requests-opd2-complete-all/', views.drug_requests_opd2_completes_all, name='drug_requests_opd2_completes_all'),

    # Tariff: Registration fee
    path('plans/', views.plan_page, name='plan-page'),
    path('plans/create/', views.create_plan_ajax),
    path('plans/update/<int:id>/', views.update_plan_ajax),
    path('plans/delete/<int:id>/', views.delete_plan_ajax),
    path('plans/upload-excel/', views.upload_plan_excel_ajax),  

     # Tariff: Laboratory fee
    path('lab-inventory/', views.lab_inventory, name='lab_inventory'),
    path('delete-lab-test/', views.delete_lab_test, name='delete_lab_test'),
    path('update-lab-test/', views.update_lab_test, name='update_lab_test'),
    path('download-test-template', views.download_import_test_template, name = "download_test_template"),
    path("save-lab-inventory/", views.save_lab_inventory, name="save_lab_inventory"),

    # Tariff: Radiology fee
    path('scan-inventory/', views.scan_inventory, name='scan_inventory'),
    path('delete-scan-test/', views.delete_scan_test, name='delete_scan_test'),
    path('update-scan-test/', views.update_scan_test, name='update_scan_test'),
    path("save-scan-inventory/", views.save_scan_inventory, name="save_scan_inventory"),

    # Tariff: Drugs/Product fee
    path('pharmacy-tariff/', views.pharmacy_tariff_inventory, name='pharmacy_tariff_inventory'),
    path('pharmacy-tariff/edit/', views.edit_pharmacy_tariff, name='edit_pharmacy_tariff'),
    path('pharmacy-tariff/delete/', views.delete_pharmacy_tariff, name='delete_pharmacy_tariff'),

    # Tariff: Other Service fee
    path('service-tariff/', views.service_tariff, name='service_tariff'),
    path('delete-service2/', views.delete_service2, name='delete_service2'),
    path('update-service2/', views.update_service2, name='update_service2'),
    path('download-service2-template', views.download_import_service2_template, name = "download_service2_template"),
    path("save-service-tariff/", views.save_service_tariff, name="save_service_tariff"),    

    # Wards: Admission fee
    path('wards/', views.ward_page, name='ward-page'),
    path('wards/create/', views.create_ward_ajax),
    path('wards/update/<int:id>/', views.update_ward_ajax),
    path('wards/delete/<int:id>/', views.delete_ward_ajax),
    path('wards/upload-excel/', views.upload_ward_excel_ajax),

]
