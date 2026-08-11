from django import forms
from django.db import models
from patients.models import PatientAppointment
from django.utils import timezone
from users.models import User
from.models import (
    ObstetricHistory, CurrentPregnancy, GeneralMedical, LabTests, ANCDetails, Examination,
    YES_NO_CHOICES, BLOOD_GROUP_CHOICES, RELATIONSHIP2PP_CHOICES, GENOTYPE_CHOICES, RHYTHM_FACTOR_CHOICES, OTHER_CHOICES, FOETAL_MOVEMENT, FOETAL_HEART, FOETAL_PRESENTATION, URINE_ATTR, POSITION, VAGINA_POSITION
)

# --- 1. Obstetric History Form ---
class ObstetricHistoryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.required = True  


    class Meta:
        model = ObstetricHistory
        # List all fields from ObstetricHistory model
        fields = [
            'is_first_pregnancy', 'history_spontaneous_abortions', 'birthweight_gt_4500g',
            'previous_caesarean_section', 'previous_surgery_reproductive_tract',
            'age_gt_40_years', 'vaginal_bleeding', 'diastolic_bp_gt_90',
            'family_history_twins', 'previous_stillbirth_neonatal_loss',
            'birthweight_lt_2500g', 'last_pregnancy_hospital_admission',
            'multiple_pregnancy', 'age_lt_16_years', 'isoimmunization_rh',
            'pelvic_mass', 'insulin_dependent_diabetes',
        ]
        widgets = {
            'is_first_pregnancy': forms.Select(choices=YES_NO_CHOICES),
            'history_spontaneous_abortions': forms.Select(choices=YES_NO_CHOICES),
            'birthweight_gt_4500g': forms.Select(choices=YES_NO_CHOICES),
            'previous_caesarean_section': forms.Select(choices=YES_NO_CHOICES),
            'previous_surgery_reproductive_tract': forms.Select(choices=OTHER_CHOICES),
            'age_gt_40_years': forms.Select(choices=YES_NO_CHOICES),
            'vaginal_bleeding': forms.Select(choices=YES_NO_CHOICES),
            'diastolic_bp_gt_90': forms.Select(choices=YES_NO_CHOICES),
            'family_history_twins': forms.Select(choices=YES_NO_CHOICES),
            'previous_stillbirth_neonatal_loss': forms.Select(choices=YES_NO_CHOICES),
            'birthweight_lt_2500g': forms.Select(choices=YES_NO_CHOICES),
            'last_pregnancy_hospital_admission': forms.Select(choices=YES_NO_CHOICES),
            'multiple_pregnancy': forms.Select(choices=YES_NO_CHOICES),
            'age_lt_16_years': forms.Select(choices=YES_NO_CHOICES),
            'isoimmunization_rh': forms.Select(choices=YES_NO_CHOICES),
            'pelvic_mass': forms.Select(choices=YES_NO_CHOICES),
            'insulin_dependent_diabetes': forms.Select(choices=YES_NO_CHOICES),
        }

# --- 2. Current Pregnancy Form ---
class CurrentPregnancyForm(forms.ModelForm):
    class Meta:
        model = CurrentPregnancy
        fields = [
            'last_menstrual_period', 'gestational_age_weeks', 'expected_date_of_delivery',
            'number_of_foetus', 'gestational_period_from_ultrasound',
            'bleeding', 'vomiting', 'oedema', 'placenta_previa',
            'blurred_vision', 'breathlessness', 'discharge',
            'history_of_present_pregnancy', 
        ]
        exclude = [
            'staff',
        ]
        widgets = {
            'last_menstrual_period': forms.DateInput(attrs={'type': 'date', 'class': 'date-picker'}),
            'expected_date_of_delivery': forms.DateInput(attrs={'type': 'date', 'readonly': 'readonly'}),
            'gestational_age_weeks': forms.NumberInput(attrs={'readonly': 'readonly'}),
            'bleeding': forms.Select(choices=YES_NO_CHOICES),
            'vomiting': forms.Select(choices=YES_NO_CHOICES),
            'oedema': forms.Select(choices=YES_NO_CHOICES),
            'placenta_previa': forms.Select(choices=YES_NO_CHOICES),
            'blurred_vision': forms.Select(choices=YES_NO_CHOICES),
            'breathlessness': forms.Select(choices=YES_NO_CHOICES),
            'discharge': forms.Select(choices=YES_NO_CHOICES),
            'history_of_present_pregnancy': forms.Textarea(attrs={'rows': 2}),
        }

# --- 3. General Medical Form ---
class GeneralMedicalForm(forms.ModelForm):
    class Meta:
        model = GeneralMedical
        fields = [
            'known_substance_abuse', 'severe_anaemia', 'sickle_cell_disease',
            'hypertension', 'diabetes_mellitus', 'cardiac_disease',
            'chronic_cough_tuberculosis', 'breast_cancer', 'liver_disease_jaundice',
            'gall_bladder_disease', 'thyroid_disease', 'renal_disease',
            'epilepsy', 'asthma', 'others_medical_history', 'family_history',
        ]
        widgets = {
            'known_substance_abuse': forms.Select(choices=YES_NO_CHOICES),
            'severe_anaemia': forms.Select(choices=YES_NO_CHOICES),
            'sickle_cell_disease': forms.Select(choices=YES_NO_CHOICES),
            'hypertension': forms.Select(choices=YES_NO_CHOICES),
            'diabetes_mellitus': forms.Select(choices=YES_NO_CHOICES),
            'cardiac_disease': forms.Select(choices=YES_NO_CHOICES),
            'chronic_cough_tuberculosis': forms.Select(choices=YES_NO_CHOICES),
            'breast_cancer': forms.Select(choices=YES_NO_CHOICES),
            'liver_disease_jaundice': forms.Select(choices=YES_NO_CHOICES),
            'gall_bladder_disease': forms.Select(choices=YES_NO_CHOICES),
            'thyroid_disease': forms.Select(choices=YES_NO_CHOICES),
            'renal_disease': forms.Select(choices=YES_NO_CHOICES),
            'epilepsy': forms.Select(choices=YES_NO_CHOICES),
            'asthma': forms.Select(choices=YES_NO_CHOICES),
            'others_medical_history': forms.Textarea(attrs={'rows': 1}),
            'family_history': forms.Textarea(attrs={'rows': 1}),
        }

# --- 4. Tests Form ---
class TestsForm(forms.ModelForm):
    class Meta:
        model = LabTests
        fields = [
            'vdrl', 'hiv', 'blood_group', 'genotype',
            'hepatitis_b', 'hepatitis_c', 'rhesus_factor',
            'hb', 'urine_protein', 'urine_glucose', 'pregnancy_test',
        ]
        widgets = {
            'vdrl': forms.Select(choices=RHYTHM_FACTOR_CHOICES),
            'hiv': forms.Select(choices=RHYTHM_FACTOR_CHOICES),
            'blood_group': forms.Select(choices=BLOOD_GROUP_CHOICES),
            'genotype': forms.Select(choices=GENOTYPE_CHOICES),
            'hepatitis_b': forms.Select(choices=RHYTHM_FACTOR_CHOICES),
            'hepatitis_c': forms.Select(choices=RHYTHM_FACTOR_CHOICES),
            'rhesus_factor': forms.Select(choices=RHYTHM_FACTOR_CHOICES),
        }



class ANCDetailsForm(forms.ModelForm):
    class Meta:
        model = ANCDetails
        exclude = ("patient", "created", "updated")

        widgets = {
            field: forms.Select(attrs={"class": "form-control"})
            for field in ANCDetails._meta.fields
            if isinstance(field, models.CharField)
        }


class PatientAppointmentForm(forms.ModelForm):
    class Meta:
        model = PatientAppointment
        fields = ['purpose', 'visit_type', 
                 'arrival_date', 'arrival_time', 'comment']
        exclude = ['provider','clinician','anc_weeks']
        label = ''
        widgets = {
            'arrival_date': forms.DateInput(attrs={'type': 'date'}),
            'arrival_time': forms.TimeInput(attrs={'type': 'time'}),
            'comment': forms.Textarea(attrs={'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        self.patient = kwargs.pop('patient', None)
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        
        # Set initial date to today
        self.fields['arrival_date'].initial = timezone.now().date()
        
        
        # Add CSS classes
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control'})
    

class ANCExaminationsForm(forms.ModelForm):
    class Meta:
        model = Examination
        fields = '__all__'
        exclude = ['patient','category', 'plan','staff','created_date','anc_weeks']
        widgets = {
            'weight' : forms.TextInput(attrs={'class': 'form-control'}), 
            'bp' : forms.TextInput(attrs={'class': 'form-control'}), 
            'temperature' : forms.TextInput(attrs={'class': 'form-control'}), 
            'oedema' : forms.Select(choices=YES_NO_CHOICES, attrs={'class': 'form-control'}), 
            'urine_protein' : forms.Select(choices=URINE_ATTR, attrs={'class': 'form-control'}), 
            'urine_sugar' : forms.Select(choices=URINE_ATTR, attrs={'class': 'form-control'}), 
            'foetal_heart' : forms.Select(choices=FOETAL_HEART, attrs={'class': 'form-control'}), 
            'foetal_heart_rate' : forms.TextInput(attrs={'class': 'form-control'}), 
            'foetal_presentation' : forms.Select(choices=FOETAL_PRESENTATION, attrs={'class': 'form-control'}), 
            'foetal_movement' : forms.Select(choices=FOETAL_MOVEMENT, attrs={'class': 'form-control'}), 
            'position' : forms.Select(choices=POSITION, attrs={'class': 'form-control'}), 
            'relationship_of_pp_to_brim' : forms.Select(choices=RELATIONSHIP2PP_CHOICES, attrs={'class': 'form-control'}), 
            'condition_of_vagina' : forms.Select(choices=VAGINA_POSITION, attrs={'class': 'form-control'}), 
            'pvc' : forms.TextInput(attrs={'class': 'form-control'}), 
            'pulse_rate' : forms.TextInput(attrs={'class': 'form-control'}),
            'comment' : forms.Textarea(attrs={'rows': 2,'class':'form-control', 'placeholder':'Remarks or Comments'}),
        }
