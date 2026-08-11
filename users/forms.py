from django import forms
from django.forms import ModelForm
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from django.core.exceptions import ValidationError
from .models import  User, VerifyStaff, Category
from queue_operations.models import VisitPurpose

class MyUserCreationForm(UserCreationForm):
    username = forms.CharField(
        required=True,
        widget=forms.widgets.TextInput(
            attrs={
                "placeholder": "Username is the Staff ID",
                "id": "user",
            }
        ),
        
    )

    usable_password = None

    fullname = forms.CharField(
        required=True,
        widget=forms.widgets.TextInput(
            attrs={
                "placeholder": "Enter your Full Names: e.g. Adebayo Uche Ciroma",
                "id": "fullname",
            }
        ),
        
    )
    email = forms.EmailField(
        required=True,
        label='Email',
        widget=forms.EmailInput(attrs={'placeholder': 'User\'s email address'}),
        error_messages={
            'required': 'Email is required.',
            'invalid': 'Enter a valid email address.'
        }
    )
    
    phone_number = forms.CharField(
        required=True,
        widget=forms.widgets.TextInput(
            attrs={
                "placeholder": "User's Phone Number",
                "id": "phone",
            }
        ),
        
    )
    dob = forms.DateField(
        required=True,
        widget=forms.widgets.DateInput(
            attrs={ "type":"date" }
        ),
    )
    department = forms.ModelChoiceField(
        label='',
        queryset=Category.objects.all(), 
        required=True,  
        widget=forms.Select(attrs={'class': 'user1'})
    )
    purpose = forms.ModelChoiceField(
        queryset=VisitPurpose.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'user1'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Populate purpose queryset on POST
        if 'department' in self.data:
            try:
                department_id = int(self.data.get('department'))
                category = Category.objects.get(id=department_id)

                if category.department.lower() in 'clinical, cmd':
                    self.fields['purpose'].queryset = VisitPurpose.objects.all()
            except (ValueError, Category.DoesNotExist):
                pass

        # Populate on edit (instance)
        elif self.instance.pk and self.instance.department:
            if self.instance.department.department.lower() in 'clinical, cmd':
                self.fields['purpose'].queryset = VisitPurpose.objects.all()
                
    address = forms.CharField(
        required=True,
        widget=forms.widgets.TextInput(
            attrs={
                "placeholder": "User's Home Address",
                "id": "address",
            }
        ),
        
    )
    password1 = forms.CharField(
        required=True, min_length=8,
        widget=forms.widgets.PasswordInput(
            attrs={
                "placeholder": "Enter Password",
                "id": "password",
                "onKeyUp": "check_password_length();",
            }
        ),
        
    )
    password2 = forms.CharField(
        required=True, min_length=8,
        widget=forms.widgets.PasswordInput(
            attrs={
                "placeholder": "Confirm Password",
                "id": "password2",
            }
        ),
        
    )
    class Meta:
        model = User
        fields = [ 'username', 'fullname','email','gender','phone_number','address','department','purpose','dob']
        exclude = ['status', 'active','pin']
    
    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2:
            if password1 != password2:
                raise forms.ValidationError("Passwords do not match.")
        return password2
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        # username = username.upper()
        if not VerifyStaff.objects.filter(staff_id = username).exists():
            raise forms.ValidationError("This Staff ID is not valid.")
        elif User.objects.filter(username = username).exists():
            raise forms.ValidationError("This Staff ID is no longer available.")
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        email = email.lower()
        if User.objects.filter(email = email).exists():
            raise forms.ValidationError("This Email is being used by another user.")
        return email
    
    def clean_phone_number(self):
        phone_number = self.cleaned_data.get('phone_number')
        if User.objects.filter(phone_number = phone_number).exists():
            raise forms.ValidationError("This Phone Number is being used by another user.")
        return phone_number

    def clean_gender(self):
        gender = self.cleaned_data.get('gender')
        if gender == 'gender':
            raise forms.ValidationError("Please you need to select the Staff's gender")
        return gender

# Begining of Edit Userform
class AdminUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'fullname', 'email', 'gender', 'phone_number', 'address',
            'dob'
        ]
        excludes = ['password', 'department', 'last_login', 'is_superuser', 'is_staff', 'is_active', 'date_joined', 'groups', 'user_permissions']
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date','class':'form-control'}),
        }

# upload staff profile picture
class UserUpdateForm(ModelForm):
    avatar = forms.ImageField(
        required=True,
        widget=forms.widgets.ClearableFileInput(
            attrs={
                "id": "picturez",
            }
        ),   
    )
    class Meta:
        model = User
        fields = ['avatar']

# create pin code
class UserPinCreationForm(ModelForm):
    pin = forms.IntegerField(
        required=True,
        label='Enter your Pin',
        widget=forms.widgets.NumberInput(
            attrs={
                "placeholder": "Enter Pin",
                "class":"form-control",
            }
        ),   
    )
    class Meta:
        model = User
        fields = ['pin']

# change pin code
class UserPinUpdateForm(ModelForm):
    pin = forms.IntegerField(
        required=True,
        label='Enter New Pin',
        widget=forms.widgets.NumberInput(
            attrs={
                "placeholder": "Enter Pin",
                "class":"form-control",
            }
        ),   
    )
    class Meta:
        model = User
        fields = ['pin']

#   password changing form      
class PasswordChangingForm(PasswordChangeForm):
    old_password = forms.CharField(
        required=True, min_length=8,
        widget=forms.widgets.PasswordInput(
            attrs={
                "placeholder": "Enter your old Password",
                "class": "form-control"
            }
        ),  
    )
    new_password1 = forms.CharField(
        required=True, min_length=8,
        widget=forms.widgets.PasswordInput(
            attrs={
                "placeholder": "Enter your new Password",
                "class": "form-control"
            }
        ),  
    )
    new_password2 = forms.CharField(
        required=True, min_length=8,
        widget=forms.widgets.PasswordInput(
            attrs={
                "placeholder": "Confirm your new Password",
                "class": "form-control"
            }
        ),  
    )
    class Meta:
        model = User
        fields = ['old_password', 'new_password1', 'new_password2']

# password reset without using email
class PasswordResetForm(forms.Form):
    date_of_birth = forms.CharField(widget=forms.DateInput(attrs={'type':'date','class':'login__input'}))
    username = forms.CharField(widget=forms.TextInput(attrs={'placeholder':'Username (Staff ID)','class':'login__input'}))
    new_password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder':'New Password','class':'login__input'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder':'Confirm Password','class':'login__input'}))

    # def clean(self):
    #     cleaned_data = super().clean()
    #     pw1 = cleaned_data.get("new_password")
    #     pw2 = cleaned_data.get("confirm_password")
    #     if pw1 and pw2 and pw1 != pw2:
    #         raise forms.ValidationError("Passwords do not match.")
    #     return cleaned_data