from django.db import models


class Notification(models.Model):
    """One message for one staff member (the bell in the top bar). Created through
    notifications/services.py, never directly, so a failure can never break the action
    that raised it."""
    LEVELS = [('info', 'Info'), ('success', 'Success'), ('warning', 'Warning'), ('danger', 'Danger')]

    recipient = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=40, db_index=True)        # e.g. requisition_new, admission_new
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=500, blank=True, default='')
    link = models.CharField(max_length=200, blank=True, default='')  # app route, e.g. /inventory/requests
    level = models.CharField(max_length=10, choices=LEVELS, default='info')
    icon = models.CharField(max_length=40, blank=True, default='')
    actor = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    ref = models.CharField(max_length=60, blank=True, default='')    # e.g. requisition:12
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['recipient', 'read_at'], name='notif_recipient_read')]

    def __str__(self):
        return f"{self.recipient_id}: {self.title}"
