"""
Uploaded files (/media/...) for signed-in staff only.

Lab results, scans and patient photos used to be served to anyone who had the URL. Now every
/media/ request comes here first:

* Who: the Django session cookie the browser sends with <img>/<a>/<iframe> requests (set at
  login and refreshed by /api/auth/me/), or an `Authorization: Token ...` header for API calls.
  Not signed in -> 401. Any signed-in staff member may open any file, the same rule as the
  patient-record API.
* How: in production nginx sends the bytes (X-Accel-Redirect to an `internal` location, so the
  file never passes through Python). In development Django streams it.
* Safety: path traversal is refused, and file types that could run script in the browser
  (HTML, SVG, XML) are sent as downloads inside a sandbox, so an uploaded file cannot act as the
  logged-in user.
"""
import mimetypes
import os
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404, HttpResponse
from django.utils._os import safe_join
from django.views.decorators.http import require_safe

# Types a browser would execute or render as a document: never inline.
ACTIVE_TYPES = {'text/html', 'image/svg+xml', 'application/xhtml+xml', 'text/xml', 'application/xml',
                'application/javascript', 'text/javascript'}


def _media_user(request):
    """Signed-in user from the session, or from an API token header. None if neither."""
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        return user
    header = request.META.get('HTTP_AUTHORIZATION', '')
    if header.startswith('Token '):
        from rest_framework.authtoken.models import Token
        token = Token.objects.select_related('user').filter(key=header[6:].strip()).first()
        if token and token.user.is_active:
            return token.user
    return None


@require_safe
def protected_media(request, path):
    if _media_user(request) is None:
        resp = HttpResponse('Sign in to view this file.', status=401, content_type='text/plain')
        resp['Cache-Control'] = 'no-store'
        return resp

    try:
        full = safe_join(str(settings.MEDIA_ROOT), path)
    except (SuspiciousFileOperation, ValueError):
        raise Http404('File not found')
    if not os.path.isfile(full):
        raise Http404('File not found')

    ctype, encoding = mimetypes.guess_type(full)
    ctype = ctype or 'application/octet-stream'
    active = ctype in ACTIVE_TYPES

    # nginx keeps only some headers on an X-Accel-Redirect (not our sandbox CSP), so the rare
    # active file is streamed by Django to be sure the sandbox header goes out.
    if getattr(settings, 'MEDIA_ACCEL_REDIRECT', False) and not active:
        resp = HttpResponse(content_type=ctype)
        resp['X-Accel-Redirect'] = settings.MEDIA_ACCEL_PREFIX.rstrip('/') + '/' + quote(path)
    else:
        resp = FileResponse(open(full, 'rb'), content_type=ctype)
    if encoding:
        resp['Content-Encoding'] = encoding

    name = quote(os.path.basename(full))
    resp['Content-Disposition'] = f"{'attachment' if active else 'inline'}; filename*=UTF-8''{name}"
    # Private: patient data must not sit in shared caches; the browser may reuse it for an hour.
    resp['Cache-Control'] = 'private, max-age=3600'
    resp['X-Content-Type-Options'] = 'nosniff'
    if active:
        resp['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return resp
