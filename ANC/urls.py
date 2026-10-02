from django.urls import path
from. import views

urlpatterns = [
    path('new-ANC-patient/<int:patient_id>/', views.get_anc, name='get_anc'),

    path(
    'anc/details/<int:patient_id>/',
    views.get_anc_details,
    name='get_anc_details'
),


path(
    "anc/autosave/<int:patient_id>/",
    views.autosave_anc_field,
    name="autosave_anc_field"
),
path('anc/clinical-records/<int:patient_id>/', views.get_clinical_records, name='get_clinical_records'),


]
