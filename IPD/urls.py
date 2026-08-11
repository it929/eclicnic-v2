from django.urls import path
from . import views
from django.http import JsonResponse
urlpatterns = [
    # Ward URLs
    path('wards/', views.ward_page, name='ward-page'),
    path('wards/create/', views.create_ward_ajax),
    path('wards/update/<int:id>/', views.update_ward_ajax),
    path('wards/delete/<int:id>/', views.delete_ward_ajax),
    path('wards/upload-excel/', views.upload_ward_excel_ajax),

    # Bed URLs
    path('beds/', views.bed_page, name='bed_page'),
    path('beds/create/', views.create_bed_ajax, name='create_bed'),
    path('beds/update/<int:id>/', views.update_bed_ajax, name='update_bed'),
    path('beds/delete/<int:id>/', views.delete_bed_ajax, name='delete_bed'),
    path('beds/upload-excel/', views.upload_bed_excel_ajax, name='upload_bed_excel'),

    # Bed Allocation URLs
    path('allocate-bed/<int:patient_id>/', views.allocate_bed_page, name='allocate_bed_page'),
    path('allocations/available-beds/', views.get_available_beds, name='available_beds'),
    path('allocations/allocate/<int:patient_id>/', views.allocate_bed_to_patient, name='allocate_bed'),
    path('allocations/discharge/<int:patient_id>/', views.discharge_patient, name='discharge_patient'),

    # AdmissionTable
    path('admissions/', views.admission_table, name='admission_table'),
    path('admissions/ajax/', views.get_admission_data_ajax, name='admission_data_ajax'),
    path('admission-record/<int:patient_id>/', views.patient_admission, name='patient_admission'),


    # Admission Notes
    path('get-notes/<int:patient_id>/', views.get_notes, name='get_notes'),
    path('notes/create/<str:note_type>/<int:patient_id>/', views.create_note, name='create_note'),
    path('notes/update/<int:note_id>/', views.update_note, name='update_note'),
    path('notes/delete/<int:note_id>/', views.delete_note, name='delete_note'),
    path('notes/get/<int:note_id>/', views.get_note, name='get_note'),
    path('notes/history/<str:note_type>/<int:patient_id>/', views.get_note_history, name='note_history'),

    # Drug Charts
    path('drug-charts/<int:patient_id>/', views.drug_chart, name='drug_chart'),
    path('api/drug-administration/<int:administration_id>/', views.get_administration_detail, name='get_administration'),
    path('api/drug-administration/create/', views.create_administration, name='create_administration'),
    path('api/drug-administration/update/<int:administration_id>/', views.update_administration, name='update_administration'),
]
