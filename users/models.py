from django.db import models
from django.core.validators import FileExtensionValidator, RegexValidator
from django.contrib.auth.models import AbstractUser, Group, Permission

from django.contrib.auth.hashers import make_password, check_password

# File extension validator for avatar images
img_validator = FileExtensionValidator(['png', 'jpg', 'jpeg'])


class HashedPin(str):
    """
    A string wrapper representing a hashed security PIN.
    Supports secure constant-time equality checks against raw PINs (both str and int)
    via Django's check_password.
    """
    def __eq__(self, other):
        if other is None or other == '' or other == 0 or other == '0':
            return False
        raw = str(other).strip()
        if str(self).startswith(('pbkdf2_', 'argon2', 'bcrypt', 'sha1_')):
            return check_password(raw, str(self))
        return str(self).strip() == raw

    def __ne__(self, other):
        return not self.__eq__(other)


class HashedPinField(models.CharField):
    """
    Model field that automatically hashes plain-text PIN values before storing
    them as salted PBKDF2-SHA256 hashes in the database.
    """
    description = "A cryptographic hashed security PIN field"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 128)
        kwargs.setdefault('default', '')
        kwargs.setdefault('blank', True)
        super().__init__(*args, **kwargs)

    def from_db_value(self, value, expression, connection):
        if value is None or value == '' or value == '0':
            return ''
        return HashedPin(value)

    def to_python(self, value):
        if isinstance(value, HashedPin):
            return value
        if value is None or value == '' or value == '0':
            return ''
        return HashedPin(value)

    def get_prep_value(self, value):
        if value is None or value == '' or value == 0 or value == '0':
            return ''
        val_str = str(value).strip()
        if val_str.startswith(('pbkdf2_', 'argon2', 'bcrypt', 'sha1_')):
            return val_str
        return make_password(val_str)


class User(AbstractUser):
    # Custom username with regex validation
    username = models.CharField(
        max_length=150,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z0-9/]+$',
                message="Username can only contain letters, numbers, and forward slashes.",
            )
        ],
    )
    
    # Custom fields
    fullname = models.CharField(max_length=200, null=True)
    email = models.EmailField(unique=True, null=True)
    status = models.CharField(null=True, max_length=20)
    avatar = models.ImageField(null=True, default="image/avatar.svg", validators=[img_validator], upload_to='staff-profile/')
    gender = models.CharField(
        null=True,
        max_length=18,
        choices=(("gender", "--Select Gender--"), ("Female", "Female"), ("Male", "Male")),
        default="gender"
    )
    phone_number = models.CharField(unique=True, max_length=100, null=True)
    address = models.CharField(null=True, max_length=200)
    dob = models.DateField(null=True)
    department = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True)
    role = models.ForeignKey('Role', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_users')
    purpose = models.ForeignKey('queue_operations.VisitPurpose', on_delete=models.SET_NULL, null=True, blank=True)
    pin = HashedPinField(max_length=128, default='', blank=True)
    active = models.CharField(null=True, max_length=3)
    created = models.DateTimeField(auto_now_add=True, null=True)

    # Fix for reverse accessor clash (groups & permissions)
    groups = models.ManyToManyField(
        Group,
        related_name="custom_user_groups",  # Unique related_name
        blank=True,
        help_text="The groups this user belongs to.",
        verbose_name="groups",
    )
    user_permissions = models.ManyToManyField(
        Permission,
        related_name="custom_user_permissions",  # Unique related_name
        blank=True,
        help_text="Specific permissions for this user.",
        verbose_name="user permissions",
    )

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f'{self.fullname} : {self.department}'

    def set_pin(self, raw_pin):
        """Set user PIN as a secure salted hash."""
        if not raw_pin or str(raw_pin).strip() in ('', '0'):
            self.pin = ''
        else:
            self.pin = make_password(str(raw_pin).strip())

    def check_pin(self, raw_pin):
        """Verify raw PIN against user's hashed PIN."""
        if not self.pin or str(self.pin).strip() in ('', '0'):
            return False
        if not raw_pin or str(raw_pin).strip() in ('', '0'):
            return False
        if str(self.pin).startswith(('pbkdf2_', 'argon2', 'bcrypt', 'sha1_')):
            return check_password(str(raw_pin).strip(), str(self.pin))
        return str(self.pin).strip() == str(raw_pin).strip()

    @property
    def has_pin(self):
        return bool(self.pin and str(self.pin).strip() not in ('', '0'))  


class VerifyStaff(models.Model):
    staff_id = models.CharField(unique=True, max_length=100)

    def __str__(self):
        return self.staff_id
    

class Category(models.Model):
    department = models.CharField(null=True, max_length=100)
    modules = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.department or ''


class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    category = models.OneToOneField('Category', on_delete=models.SET_NULL, null=True, blank=True, related_name='linked_role')
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class SystemModule(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    icon = models.CharField(max_length=50, default='fa-cubes')
    color = models.CharField(max_length=30, default='#4e73df')
    primary_tab = models.CharField(max_length=50, default='patients')
    description = models.TextField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class SubModule(models.Model):
    module = models.ForeignKey(SystemModule, on_delete=models.CASCADE, related_name='submodules')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50)
    tab_key = models.CharField(max_length=50, blank=True, null=True)
    sub_tab = models.CharField(max_length=50, blank=True, null=True)
    sub_sub_tab = models.CharField(max_length=50, blank=True, null=True)
    route = models.CharField(max_length=200, blank=True, null=True)
    icon = models.CharField(max_length=50, default='fa-circle')
    description = models.TextField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('module', 'code')
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.module.name} -> {self.name} ({self.code})"


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')
    module = models.ForeignKey(SystemModule, on_delete=models.CASCADE, related_name='role_permissions')
    submodules = models.ManyToManyField(SubModule, blank=True, related_name='role_submodule_permissions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('role', 'module')

    def __str__(self):
        return f"{self.role.name} - {self.module.name}"



