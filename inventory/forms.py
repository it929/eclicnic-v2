from django import forms
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from .models import  Product, Transaction, Expense


# Beginning of Product form for Inventory
class ProductForm(ModelForm):
    product_name = forms.CharField(
        required=True,
        label='Product\'s Name',
        widget=forms.widgets.TextInput(
            attrs={
                "placeholder": "Enter Product name","class":"form-control",
            }
        ),   
    )
    product_id = forms.CharField(
        required=True,
        label='',
        widget=forms.widgets.TextInput(
            attrs={
                "placeholder": "Barcode will be generated","class":"form-control",
            }
        ),   
    )
    description = forms.CharField(
        required=False,
        label='Product\'s Description', 
        widget=forms.widgets.TextInput(
            attrs={
                "placeholder": "Enter Product's Description",
                "class":"form-control",
                "rows":"3"
            }
        ),   
    )
    price = forms.IntegerField(
        required=True,
        label='Price',
        widget=forms.widgets.NumberInput(
            attrs={
                "placeholder": "Enter Product's Price",
                "class":"form-control",
            }
        ),   
    )
    stock = forms.IntegerField(
        required=True,
        label='Stock',
        widget=forms.widgets.NumberInput(
            attrs={
                "placeholder": "Enter Number of Quantity(s)",
                "class":"form-control",
            }
        ),   
    )
    low_stock_threshold = forms.IntegerField(
        required=True,
        label='Low Stock Threshold',
        widget=forms.widgets.NumberInput(
            attrs={
                "placeholder": "Enter No of Quantity(s)",
                "class":"form-control",
            }
        ),   
    )
    manufacturing_date = forms.DateField(
        required=False,
        label='MfD Date',
        widget=forms.widgets.DateInput(
            attrs={
                "class":"form-control",
                "type":"date"
            }
        ),   
    )
    expiry_date = forms.DateField(
        required=True,
        label='Expiry Date',
        widget=forms.widgets.DateInput(
            attrs={
                "class":"form-control",
                "type":"date"
            }
        ),   
    )

    expiry_flag_in_num = forms.IntegerField(
        required=False,
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control","placeholder":"enter number"}
        ),   
    )
    class Meta:
        model = Product
        fields = ['product_name' ,'product_id', 'description', 'price', 'stock','minimum_UoM','low_stock_threshold', 'manufacturing_date', 'expiry_date','expiry_flag_in_num','expiry_flag_in']
        exclude = ['status','staff']
        widgets = {
            'expiry_flag_in': forms.Select(attrs={'class': 'form-control'}),
            'minimum_UoM': forms.Select(attrs={'class': 'form-control'}),
        }



# Edit product form
class EditProductForm(ModelForm):
    product_name = forms.CharField(
        widget=forms.widgets.TextInput(
            attrs={"class":"form-control", "readonly":"readonly"}
        ),   
    )
    product_id = forms.CharField(
        required=True,
        widget=forms.widgets.TextInput(
            attrs={"class":"form-control", "readonly":"readonly"}
        ),   
    )
    description = forms.CharField(
        required=False,
        widget=forms.widgets.TextInput(
            attrs={"class":"form-control","rows":"3"}
        ),   
    )
    price = forms.IntegerField(
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control",}
        ),   
    )
    stock = forms.IntegerField(
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control",}
        ),   
    )
    low_stock_threshold = forms.IntegerField(
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control",}
        ),   
    )
    manufacturing_date = forms.DateField(
        required=False,
        widget=forms.widgets.DateInput(
            attrs={"class":"form-control","type":"date"}
        ),   
    )
    expiry_date = forms.DateField(
        widget=forms.widgets.DateInput(
            attrs={"class":"form-control","type":"date"}
        ),   
    )
    expiry_flag_in_num = forms.IntegerField(
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control","placeholder":"enter number"}
        ),   
    )
    class Meta:
        model = Product
        fields = ['product_name' ,'product_id', 'description', 'price', 'stock','minimum_UoM','low_stock_threshold', 'manufacturing_date', 'expiry_date','expiry_flag_in_num','expiry_flag_in']
        exclude = ['status','staff']
        widgets = {
            'expiry_flag_in': forms.Select(attrs={'class': 'form-control'}),
            'minimum_UoM': forms.Select(attrs={'class': 'form-control'}),
        }

# Beginning of Transaction form for Inventory
class TransactionForm(ModelForm):
    class Meta:
        model = Transaction
        fields = ['quantity', 'transaction_type']

class ProductForm2(ModelForm):
    expiry_flag_in_num = forms.IntegerField(
        required=False,
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control","placeholder":"enter number"}
        ),   
    )
    class Meta:
        model = Product
        fields = ['product_name' ,'product_id', 'description', 'price', 'stock','minimum_UoM','low_stock_threshold', 'manufacturing_date', 'expiry_date','expiry_flag_in_num','expiry_flag_in']
        exclude = ['status','staff']
        widgets = {
            'expiry_flag_in': forms.Select(attrs={'class': 'form-control'}),
            'minimum_UoM': forms.Select(attrs={'class': 'form-control'}),
        }


# Edit Vendor form
class EditVendorForm(ModelForm):
    vendor_name = forms.CharField(
        widget=forms.widgets.TextInput(
            attrs={"class":"form-control"}
        ),   
    )
    vendor_id = forms.CharField(
        required=True,
        widget=forms.widgets.TextInput(
            attrs={"class":"form-control"}
        ),   
    )
    product_name = forms.CharField(
        widget=forms.widgets.TextInput(
            attrs={"class":"form-control"}
        ),   
    )
    product_id = forms.CharField(
        required=True,
        widget=forms.widgets.TextInput(
            attrs={"class":"form-control"}
        ),   
    )
    unit_price = forms.IntegerField(
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control",}
        ),   
    )
    total_cost = forms.IntegerField(
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control",}
        ),   
    )
    payment = forms.IntegerField(
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control",}
        ),   
    )
    quantity = forms.IntegerField(
        widget=forms.widgets.NumberInput(
            attrs={"class":"form-control",}
        ),   
    )

    class Meta:
        model = Expense
        fields = ['vendor_name' ,'vendor_id','product_name' ,'product_id', 'unit_price', 'quantity','minimum_UoM','total_cost', 'payment']
        exclude = ['due','staff']
        widgets = {
            'minimum_UoM': forms.Select(attrs={'class': 'form-control'}),
        }

# upload vendors form
class VendorsUploadForm(forms.Form):
    file = forms.FileField()