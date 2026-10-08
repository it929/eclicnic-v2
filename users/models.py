from django.db import models
from django.core.validators import FileExtensionValidator, RegexValidator
from django.contrib.auth.models import AbstractUser, Group, Permission

# File extension validator for avatar images
img_validator = FileExtensionValidator(['png', 'jpg', 'jpeg'])

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
    purpose = models.ForeignKey('queue_operations.VisitPurpose', on_delete=models.SET_NULL, null=True, blank=True)
    pin = models.PositiveIntegerField(default=0)
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


class VerifyStaff(models.Model):
    staff_id = models.CharField(unique=True, max_length=100)

    def __str__(self):
        return self.staff_id
    
class Category(models.Model):
    department = models.CharField(null=True, max_length=100)
    modules = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.department or ''


