from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'recipient', 'kind', 'title', 'read_at')
    list_filter = ('kind', 'level')
    search_fields = ('title', 'message', 'recipient__username', 'recipient__fullname')
