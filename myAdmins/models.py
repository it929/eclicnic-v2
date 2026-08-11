from django.contrib.sessions.models import Session
from django.db import models

class UserActivityLog(models.Model):
    ACTIVITY_TYPES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('password_reset', 'Password Reset'),
        ('password_change', 'Password Change'), 
        ('pin_reset', 'PIN Reset'),
        ('pin_created', 'PIN Created'),  
        ('pin_change', 'PIN Changed'),  
        ('deactivated', 'Account Deactivated'),
        ('activated', 'Account Activated'),
        ('profile_update', 'Profile Update'),
        ('profile_picture_update', 'Profile Picture Update'),  
        ('failed_login', 'Failed Login Attempt'),
        ('session_expired', 'Session Expired'),
        ('account_accessed', 'Account Accessed by Admin'),
    ]
    
    user = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='activities')
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    description = models.TextField(null=True, blank=True)
    
    # Browser/Device Information
    browser_name = models.CharField(max_length=100, null=True, blank=True)
    browser_version = models.CharField(max_length=50, null=True, blank=True)
    os_name = models.CharField(max_length=100, null=True, blank=True)
    os_version = models.CharField(max_length=50, null=True, blank=True)
    device_type = models.CharField(max_length=50, null=True, blank=True)  # Mobile, Desktop, Tablet
    device_brand = models.CharField(max_length=100, null=True, blank=True)
    
    # Network Information
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    # location = models.CharField(max_length=200, null=True, blank=True)  # City, Country
    # latitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    # longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    # Session Information
    session_key = models.CharField(max_length=100, null=True, blank=True)
    referrer_url = models.URLField(max_length=500, null=True, blank=True)
    page_accessed = models.CharField(max_length=500, null=True, blank=True)
    
    # Timestamp
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # Additional metadata
    user_agent = models.TextField(null=True, blank=True)  # Full user agent string
    additional_data = models.JSONField(null=True, blank=True)  
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['activity_type']),
            models.Index(fields=['ip_address']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.activity_type} - {self.timestamp}"


class UserSession(models.Model):
    user = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='sessions')
    session_key = models.CharField(max_length=100, db_index=True)
    login_time = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    browser_name = models.CharField(max_length=100, null=True, blank=True)
    os_name = models.CharField(max_length=100, null=True, blank=True)
    device_type = models.CharField(max_length=50, null=True, blank=True)
    
    class Meta:
        ordering = ['-last_activity']
        indexes = [
            models.Index(fields=['user', '-last_activity']),
            models.Index(fields=['last_activity']),
            models.Index(fields=['session_key']),
        ]
        # This ensures one session per user per session_key
        unique_together = ['user', 'session_key']
    
    def __str__(self):
        return f"{self.user.username} - last active: {self.last_activity}"