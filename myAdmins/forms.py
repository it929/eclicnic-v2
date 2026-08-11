from django import forms

class StaffUploadForm(forms.Form):
    # For manual entry
    staff_id = forms.CharField(
        max_length=100, 
        required=False, 
        label="Manual Staff ID",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter Staff ID'
        })
    )
    
    # For Excel upload
    excel_file = forms.FileField(
        required=False, 
        label="Upload Excel File",
        widget=forms.FileInput(attrs={
            'class': 'form-control'
        })
    )