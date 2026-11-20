from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse

def health_check(request):
    return HttpResponse('healthy', content_type='text/plain')

from api.media_views import protected_media

urlpatterns = [
    # Uploaded files: signed-in staff only (lab results, scans, photos). See api/media_views.py.
    re_path(r'^media/(?P<path>.+)$', protected_media, name='protected_media'),
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
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

# Serve static files in debug mode (media is always served by protected_media above)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
