from django import forms
from django.core.validators import FileExtensionValidator
from .models import PatientProfile, PatientCategory, PatientPlan, PatientAppointment
from queue_operations.models import VisitPurpose, NurseWaitingList
from django.core.exceptions import ValidationError
from django.utils import timezone
from users.models import User

class UploadPatientPlanForm(forms.Form):
    excel_files = forms.FileField()


class PatientPlanUploadForm(forms.Form): 
    excel_file = forms.FileField(
        label='Excel File',
        validators=[FileExtensionValidator(allowed_extensions=['xlsx', 'xls'])],
        help_text='Upload .xlsx or .xls file with Plan Name, Code, and Category columns'
    )
    
    overwrite = forms.BooleanField(
        required=False,
        initial=False,
        label='Overwrite existing plans?',
        help_text='Check to update existing plans with same name and category'
    )
    # Optional: Add category filter if you want to upload plans for specific categories
    category = forms.ModelChoiceField(
        queryset=PatientCategory.objects.all(),
        required=False,
        label='Filter by Category (optional)',
        help_text='Leave blank to upload all plans from the file'
    )


# Adding plans one after the other
class PatientPlanForm(forms.ModelForm):
    class Meta:
        model = PatientPlan
        fields = ['plan', 'code', 'category']
        widgets = {
            'plan': forms.TextInput(attrs={'class': 'form-control','placeholder':'Patients Plan Type'}),
            'code': forms.TextInput(attrs={'id': 'surname', 'placeholder':'Code','class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
         }


# add patient to the database        
class PatientProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Mark required fields
        for field_name, field in self.fields.items():
            if field.required:
                field.label = f"{field.label} *"
                field.widget.attrs['required'] = 'required'

    class Meta:
        model = PatientProfile
        fields = '__all__'
        exclude = ['active', 'created_by', 'deactivated_date', 'deactivated_by', 'avatar']
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date','class': 'form-control'}),
            'surname': forms.TextInput(attrs={'id': 'surname', 'placeholder':'Surname','class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'id': 'first_name', 'placeholder':'First Name','class': 'form-control'}),
            'other_name': forms.TextInput(attrs={'id': 'other_name', 'placeholder':'Middle Name','class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control', 'id': 'category'}),
            'plan': forms.Select(attrs={'class': 'form-control', 'id': 'plan'}),
            'patient_type': forms.Select(attrs={'class': 'form-control', 'id': 'type'}),
            'address': forms.Textarea(attrs={'rows': 2,'placeholder':'Home Address','class':'form-control'}),
            'hospital_number': forms.TextInput(attrs={'id': 'hospital_number', 'placeholder':'Hospital Number','class': 'form-control'}),
            'email_address': forms.EmailInput(attrs={'id': 'email', 'placeholder':'Example: joy@gmail.com','class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'id': 'phone_number', 'placeholder':'Phone Number','class': 'form-control'}),
            'insurance_policy_number': forms.TextInput(attrs={'id': 'insurance_number', 'placeholder':'Insurance Policy/ID Number','class': 'form-control'}),
            'full_name': forms.TextInput(attrs={'id': 'insurance_number', 'placeholder':'Full Name of the person to be contacted','class': 'form-control'}),
            'relationship_to_patient': forms.TextInput(attrs={'id': 'relationship_to_patient', 'placeholder':'Relationship to Patient','class': 'form-control'}),
            'phone_numbers': forms.TextInput(attrs={'id': 'phone_numbers', 'placeholder':'Phone Numbers','class': 'form-control'}),

        }

    def clean_email_address(self):
        email = self.cleaned_data.get('email_address')
        if email:  # Only validate if email is provided (since it's null=True)
            if PatientProfile.objects.filter(email_address__iexact=email).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise ValidationError("This email is already registered to another patient.")
        return email

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if PatientProfile.objects.filter(phone_number=phone).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise ValidationError("This phone number is already in use.")
        return phone

    def clean_hospital_number(self):
        hospital_num = self.cleaned_data.get('hospital_number')
        if hospital_num:  # Only validate if provided
            if PatientProfile.objects.filter(hospital_number=hospital_num).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise ValidationError("This hospital number already exists.")
        return hospital_num

    def clean_phone_numbers(self):
        phone_nums = self.cleaned_data.get('phone_numbers')
        if phone_nums:  # Only validate if provided
            if PatientProfile.objects.filter(phone_numbers=phone_nums).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise ValidationError("This emergency contact number is already in use.")
        return phone_nums

    def clean_insurance_policy_number(self):
        policy_num = self.cleaned_data.get('insurance_policy_number')
        if policy_num:  # Only validate if provided
            if PatientProfile.objects.filter(insurance_policy_number=policy_num).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise ValidationError("This insurance policy number is already registered.")
        return policy_num

# upload patient profile from excel file
class PatientImportForm(forms.Form):
    excel_file = forms.FileField(
        label='Select Excel File',
        help_text='File should be in .xlsx format with column headers matching model fields'
    )

class ImageUploadForm(forms.ModelForm):
    avatar = forms.ImageField(
        required=True,
        widget=forms.widgets.ClearableFileInput(
            attrs={
                "id": "picture",
            }
        ),   
    )
    class Meta:
        model = PatientProfile
        fields = ['avatar']


class PatientProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = PatientProfile
        fields = [
            'surname', 'first_name', 'other_name', 'dob', 'gender', 'patient_type',
            'phone_number', 'address', 'category', 'plan', 'email_address',
            'hospital_number', 'full_name', 'relationship_to_patient', 'phone_numbers',
            'insurance_policy_number', 'avatar'
        ]
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date','class': 'form-control'}),
            'surname': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'other_name': forms.TextInput(attrs={'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'plan': forms.Select(attrs={'class': 'form-control'}),
            'patient_type': forms.Select(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control','rows': 2}),
            'hospital_number': forms.TextInput(attrs={'class': 'form-control'}),
            'email_address': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'insurance_policy_number': forms.TextInput(attrs={'class': 'form-control'}),
            'full_name': forms.TextInput(attrs={'class': 'form-control'}),
            'relationship_to_patient': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_numbers': forms.TextInput(attrs={'class': 'form-control'}),
        }

class PatientAlergyUpdateForm(forms.ModelForm):
    class Meta:
        model = PatientProfile
        fields = [
            'allergies'
        ]
        widgets = {
            'allergies': forms.TextInput(attrs={'class': 'form-control','style':'height:75px; resize: vertical;'}),
        }

# upload purpose of appointment form
class ExcelImportForm(forms.Form):
    upload_purpose = forms.FileField(
        label='Select Excel File',
        help_text='File should be in .xlsx format with column headers matching model fields'
    )

# Adding purpose of appointment one after the other
class ServiceListForm(forms.ModelForm):
    class Meta:
        model = VisitPurpose
        fields = ['purpose', 'price', 'specialist_id']
        widgets = {
            'purpose': forms.TextInput(attrs={'class': 'form-control','placeholder':'Service Name'}),
            'price': forms.NumberInput(attrs={'placeholder':'Enter Price/Amount','class': 'form-control'}),
            'specialist_id': forms.NumberInput(attrs={'placeholder':'Enter Specialist ID','class': 'form-control'}),
         }
        

class NurseWaitingListForm(forms.ModelForm):
    price = forms.IntegerField(required=True,label='',
    widget=forms.widgets.NumberInput(attrs={'class':'hidden'})
    )
    
    exception_bill = forms.BooleanField(
        required=False,
        label='Exception Bill',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    class Meta:
        model = NurseWaitingList
        fields = ['visit_type', 'purpose', 'price', 'exception_bill']  
        exclude = ['patient', 'attendant', 'category', 'plan', 'critical_request']
        widgets = {
            'purpose': forms.Select(attrs={'class': 'form-control'}),
            'visit_type': forms.Select(attrs={'class': 'form-control'}),
        }
        
    def __init__(self, *args, **kwargs): 
        super().__init__(*args, **kwargs) 
        # Set the purpose choices from VisitPurpose
        purposes = VisitPurpose.objects.all()
        purpose_choices = [(p.purpose, p.purpose) for p in purposes]
        self.fields['purpose'].widget = forms.Select(choices=purpose_choices)
        self.fields['price'].widget.attrs['readonly'] = True


class PatientSearchForm(forms.Form):
    search_term = forms.CharField(
        label='Search Patients',
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by name, phone, or hospital number',
            'autocomplete': 'off'
        })
    )


class PatientAppointmentForm(forms.ModelForm):
    class Meta:
        model = PatientAppointment
        fields = ['provider', 'clinician', 'purpose', 'visit_type', 
                 'arrival_date', 'arrival_time', 'comment']
        exclude = ['anc_weeks']
        widgets = {
            'arrival_date': forms.DateInput(attrs={'type': 'date'}),
            'arrival_time': forms.TimeInput(attrs={'type': 'time'}),
            'comment': forms.Textarea(attrs={'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        self.patient = kwargs.pop('patient', None)
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        
        # Set initial date to today
        self.fields['arrival_date'].initial = timezone.now().date()
        
        # Set current user as default provider if available
        if self.request and self.request.user.is_authenticated:
            self.fields['provider'].initial = self.request.user
            self.fields['provider'].queryset = User.objects.filter(
                groups__name__in=['Doctor', 'Nurse', 'Clinician']
            )
        
        # Add CSS classes
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control'})
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.patient:
            instance.patient = self.patient
        if commit:
            instance.save()
        return instance
