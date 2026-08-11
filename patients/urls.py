from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
# from cbe import views

urlpatterns = [

    path('upload-patients-plans/', views.upload_patient_plans, name='upload_plans'),
    path('register/', views.patient_registration, name='patient_registration'),
    path('patients/import/', views.import_patients, name='patient_list'),
    path('patients/import/template/', views.download_import_template, name='download_import_template'),
    path('ajax/load-plans/', views.load_plans, name='ajax_load_plans'),
    path('download-plan-template/', views.download_plan_template, name='download_plan_template'),
    path('export/', views.export_all_patient_to_excel, name='export_patients'),
    path('registered-today/', views.patient_registered_today, name='registered_today'),
    path('all-patients/', views.all_patients, name='all_patients'),
    path('single-plan-patients/', views.single_plan_patients, name='single_patients'),
    path('family-plan-patients/', views.family_plan_patients, name='family_patients'), 
    path('anc-patients/', views.anc_patients, name='anc_patients'),
    path('hmo-patients/', views.hmo_patients, name='hmo_patients'),
    path('nhis-patients/', views.nhis_patients, name='nhis_patients'),
    path('retainership-patients/', views.retainership_patients, name='retainership_patients'),
    path('patient-profile/<str:key>/', views.patient_profile, name = "patient_profile"),
    path('patient/<int:patient_id>/capture-webcam/', views.capture_webcam_image, name='capture_webcam'),
    path('edit-patient/<str:key>/', views.edit_patient_profile, name='edit_patient_profile'),
    path('deactivated-patients/', views.deactivated_patients, name='deactivated_patients'),
    path('import/', views.import_visit_purposes, name='import_visit_purposes'),
    path('get-price/', views.get_price, name='get_price'),
    path('service-list/import/template/', views.download_import_template2, name='download_servicelist_template'),

    # ----------- Appointments URLs ----------
    # Front Desk appointments
    path('today-appointment/', views.today_appointment, name='today_appointment'),
    path('upcoming-apppointments/1/', views.upcoming_appointment, name='upcoming_appointment'),
    path('cancelled-apppointments/1/', views.cancelled_appointment, name='cancelled_appointment'),
    path('all-appointments/', views.all_appointment, name='all_appointment'),
    # Doctors appointments
    path('today-apppointment/1/', views.today_appointments, name='today_appointments'),
    path('upcoming-apppointment/1/', views.upcoming_appointments, name='upcoming_appointments'),
    path('all-apppointment/1/', views.all_appointments, name='all_appointments'),
    # Appointment reviews
    path('completed-appointment/<str:key>/', views.appointment_review_today, name='completed_appointment'),
    path('upcoming-appointment/<str:key>/', views.appointment_review_upcoming, name='appointment_review_upcoming'),
    path('review-appointment/<str:key>/', views.appointment_review_all, name='appointment_review_all'),

    path('birthday-celebrants/', views.birthday_celebrants, name='birthday_list'),
    path('patient-search/', views.patient_search, name='patient_search'),
    
    path('search/', views.search_page, name='search_page'),
    # path('ajax/search-patients/', views.patient_search, name='search_patients'),


] 