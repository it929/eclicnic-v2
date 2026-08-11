from django.urls import path
from . import views

urlpatterns = [
    # Lab test
    path('lab-waiting-list', views.load_lab_queue, name = "lab_waiting"),
    path('lab-queue', views.fetch_lab_queue, name='fetch_lab_queue'),
    path('lab-waiting-count/', views.lab_waiting_count, name='lab_waiting_count'),

    path('lab-investigation/<str:key>/', views.lab_investigations, name='lab_investigation'),
    path('lab-investigation/<str:key>/add/', views.add_lab_result, name='add_lab_result'),
    path('lab-investigation/<str:key>/edit/<int:result_id>/', views.edit_lab_result, name='edit_lab_result'),
    path('lab-investigation/<str:key>/delete/<int:result_id>/', views.delete_lab_result, name='delete_lab_result'),
    path('investigations-history/<str:key>/', views.test_history, name='test_history'),
    path('get-labResult/<str:key>/', views.get_lab_results, name='get_lab_results'),
    path('get-labResult-today/<str:key>/', views.get_lab_results_today, name='get_lab_results_today'),
    path('send-lab-results-email/', views.send_lab_results_email, name='send_lab_results_email'),
    path('save-signature-session/', views.save_signature_session, name='save_signature_session'),
    path('clear-signature-session/', views.clear_signature_session, name='clear_signature_session'),
    path('investigations-completed/', views.completed_lab_results, name='lab_completed_list'),

    
    path('lab-inventory', views.upload_labtest_from_excel, name = "lab_inventory"),
    path('download-test-template', views.download_import_test_template, name = "download_test_template"),
    path("save-lab-inventory/", views.save_lab_inventory, name="save_lab_inventory"),
    path("review-lab-inventory/", views.review_lab_inventory, name="review_lab_inventory"),
    path("lab-test/delete/<int:pk>/", views.delete_lab_test, name="delete_lab_test"),
    path("lab-test/modify/<int:pk>/", views.modify_lab_test, name="modify_lab_test"),

    # Scan test
    path('scan-waiting-list', views.load_scan_queue, name = "scan_waiting"),
    path('scan-queue', views.fetch_scan_queue, name='fetch_scan_queue'),
    path('scan-waiting-count/', views.scan_waiting_count, name='scan_waiting_count'),

    path('scan-investigation/<str:key>/', views.scan_investigations, name='scan_investigation'),
    path('scan-investigation/<str:key>/add/', views.add_scan_result, name='add_scan_result'),
    path('scan-investigation/<str:key>/edit/<int:result_id>/', views.edit_scan_result, name='edit_scan_result'),
    path('scan-investigation/<str:key>/delete/<int:result_id>/', views.delete_scan_result, name='delete_scan_result'),
    path('imaging-history/<str:key>/', views.scan_history, name='scan_history'),
    path('get-scanResult/<str:key>/', views.get_scan_results, name='get_scan_results'),
    path('get-scanResult-today/<str:key>/', views.get_scan_results_today, name='get_scan_results_today'),
    path('send-scan-results-email/', views.send_scan_results_email, name='send_scan_results_email'),
    path('imaging-completed/', views.completed_scan_results, name='scan_completed_list'),

    path('scan-inventory', views.upload_scantest_from_excel, name = "scan_inventory"),
    path('download-test-template', views.download_import_test_template, name = "download_test_template"),
    path("save-scan-inventory/", views.save_scan_inventory, name="save_scan_inventory"),
    path("review-scan-inventory/", views.review_scan_inventory, name="review_scan_inventory"),
    path("scan-test/delete/<int:pk>/", views.delete_scan_test, name="delete_scan_test"),
    path("scan-test/modify/<int:pk>/", views.modify_scan_test, name="modify_scan_test"),


] 