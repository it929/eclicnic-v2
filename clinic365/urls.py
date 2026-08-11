from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse

def health_check(request):
    return HttpResponse('healthy', content_type='text/plain')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('users.urls')),
    path('', include('patients.urls')),
    path('', include('queue_operations.urls')),
    path('', include('inventory.urls')),
    path('', include('IPD_pharm.urls')),
    path('', include('IPD_pharm2.urls')),
    path('', include('IPD_pharm3.urls')),
    path('', include('OPD_pharm.urls')),
    path('', include('OPD_pharm2.urls')),
    path('', include('radio_lab.urls')),
    path('', include('IPD.urls')),
    path('', include('ANC.urls')),
    path('', include('Billings.urls')),
    path('', include('myAdmins.urls')),
    path('', include('Reporting.urls')),
    path('health', health_check, name='health_check'),
]

# Serve static files in debug mode
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
