from django import forms
from django.core.validators import FileExtensionValidator
from .models import BackgroundHealth, PatientBackgroundHealth, VisitPurpose, DoctorWaitingList, OtherService, Diagnosis, ICD11Code, ICD11Category

class BackgroundHealthForm(forms.ModelForm):
    class Meta:
        model = BackgroundHealth
        fields = '__all__'
       
class EditPatientBackgroundHealthForm(forms.ModelForm):
    class Meta:
        model = PatientBackgroundHealth
        fields = '__all__'
        exclude = ['patient','staff','status','created_date']

class DoctorWaitingListForm(forms.ModelForm):
    class Meta:
        model = DoctorWaitingList
        fields = '__all__'
        exclude = ['patient','category', 'plan','critical_request','staff','waiting_status','encounter_status','purpose','completed','created_date','anc_weeks']
        widgets = {
            'height' : forms.NumberInput(attrs={'placeholder':'Height (cm)','class': 'form2'}), 
            'weight' : forms.NumberInput(attrs={'placeholder':'Weight (kg)','class': 'form-control'}), 
            'bp' : forms.TextInput(attrs={'placeholder':'BP (e.g. 120/80)','class': 'form-control'}),
            'bmi' : forms.NumberInput(attrs={'placeholder':'BMI (bmi)','class': 'form-control'}), 
            'temperature' : forms.NumberInput(attrs={'placeholder':'Temperature (celcius)','class': 'form-control'}), 
            'respiratory_rate' : forms.NumberInput(attrs={'placeholder':'Respiratory Rate (cpm)','class': 'form-control'}), 
            'urine_ph' : forms.NumberInput(attrs={'placeholder':'Urine PH','class': 'form-control'}), 
            'sp_02' : forms.NumberInput(attrs={'placeholder':'SP 02 (%)','class': 'form-control'}), 
            'oxygen_volume' : forms.NumberInput(attrs={'placeholder':'Oxygen Volume (L/min)','class': 'form-control'}), 
            'urine_glucose' : forms.NumberInput(attrs={'placeholder':'Urine Glucose (mg/dl)','class': 'form-control'}), 
            'blood_glucose' : forms.NumberInput(attrs={'placeholder':'Blood Glucose (mg/dl)','class': 'form-control'}), 
            'urine_protein' : forms.NumberInput(attrs={'placeholder':'Urine Protein (mg/dL)','class': 'form-control'}),
            'pulse' : forms.NumberInput(attrs={'placeholder':'Pulse  (BPM)','class': 'form-control'}),
            'comment' : forms.Textarea(attrs={'rows': 2,'placeholder':'Add your comments (Optional)','class':'form-control'}),
        }


class DoctorWaitingListModifyForm(forms.ModelForm):
    class Meta:
        model = DoctorWaitingList
        fields = '__all__'
        exclude = [
            'patient', 'category', 'plan', 'critical_request', 'purpose', 
            'staff', 'waiting_status', 'encounter_status', 'completed', 
            'created_date', 'anc_weeks'
        ]
        
        widgets = {
            'height': forms.NumberInput(attrs={'class': 'form2'}), 
            'weight': forms.NumberInput(attrs={'class': 'form-control'}), 
            'bp': forms.TextInput(attrs={'class': 'form-control'}), 
            'bmi': forms.NumberInput(attrs={'class': 'form-control', 'readonly': 'readonly', 'placeholder': 'Auto-calculated'}), 
            'temperature': forms.NumberInput(attrs={'class': 'form-control'}), 
            'respiratory_rate': forms.NumberInput(attrs={'class': 'form-control'}), 
            'urine_ph': forms.NumberInput(attrs={'class': 'form-control'}), 
            'sp_02': forms.NumberInput(attrs={'class': 'form-control'}), 
            'oxygen_volume': forms.NumberInput(attrs={'class': 'form-control'}), 
            'urine_glucose': forms.NumberInput(attrs={'class': 'form-control'}), 
            'blood_glucose': forms.NumberInput(attrs={'class': 'form-control'}), 
            'urine_protein': forms.NumberInput(attrs={'class': 'form-control'}),
            'pulse': forms.NumberInput(attrs={'class': 'form-control'}),
            'comment': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }


class DiagnosisForm(forms.ModelForm):
    icd11_code = forms.ModelChoiceField(
        queryset=ICD11Code.objects.all(),
        empty_label="Select ICD-11 Code",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = Diagnosis
        fields = ['icd11_code', 'diagnosis_date', 'confirmed', 'primary_diagnosis', 'notes']
        widgets = {
            'diagnosis_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

class ICD11SearchForm(forms.Form):
    search_term = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search ICD-11 codes...',
            'id': 'icd11-search'
        })
    )
    category = forms.ModelChoiceField(
        queryset=ICD11Category.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

from .models import PatientEncounter, PresentingComplaint

class PresentingComplaintForm(forms.ModelForm):
    chief_complaint = forms.CharField(
        label='Presenting Complaints *',
        widget=forms.TextInput(attrs={
            'placeholder': 'Search here',
            'class': 'form-control',
            'id': 'complaint-search'
        })
    )
    
    history_of_present_illness = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 6,
            'placeholder': 'Describe the history of present illness...',
            'class': 'form-control'
        })
    )
    
    class Meta:
        model = PatientEncounter
        fields = ['chief_complaint', 'history_of_present_illness']


class OtherServiceForm(forms.ModelForm):
    price = forms.IntegerField(required=True,label='',
    widget=forms.widgets.NumberInput(attrs={'class':'form-control','style':'background:none'}))
    purpose = forms.ChoiceField(
    required=True,
    label='',
    choices=[],   
    widget=forms.Select(attrs={
        'class': 'form-control',
        'style': 'background:none; width:100%',
    })
)

    class Meta:
        model = OtherService
        fields = [ 'purpose', 'price']
        exclude = ['patient', 'provider', 'category', 'plan']
        
    def __init__(self, *args, **kwargs): 
        super().__init__(*args, **kwargs) 
        # Setting the purpose choices from VisitPurpose
        purposes = VisitPurpose.objects.all()
        purpose_choices = [(p.purpose, p.purpose) for p in purposes]
        self.fields['purpose'].widget = forms.Select(choices=purpose_choices)
        self.fields['price'].widget.attrs['readonly'] = True