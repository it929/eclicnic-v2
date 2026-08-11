from django import forms
from .models import Ward

class WardForm(forms.ModelForm):
    class Meta:
        model = Ward
        fields = ['ward_name', 'ward_number']
