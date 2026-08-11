from django import forms
from .models import Deposit, Refund, PAYMENT_METHOD

class DepositForm(forms.ModelForm):
    
    class Meta:
        model = Deposit
        fields = ['amount', 'payment_type'] 
        exclude = ['invoice_id']
        widgets = {
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'Enter amount'}),
            'payment_type': forms.Select(attrs={'class': 'form-control'}, choices=PAYMENT_METHOD),
        }
    
   
class RefundForm(forms.ModelForm):
    
    class Meta:
        model = Refund
        fields = ['invoice_id', 'amount', 'payment_type'] 
        widgets = {
            'invoice_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter Invoice Number'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'Enter amount'}),
            'payment_type': forms.Select(attrs={'class': 'form-control'}, choices=PAYMENT_METHOD),
        }
