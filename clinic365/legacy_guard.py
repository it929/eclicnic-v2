"""
Sign-in required for every server page outside the API.

The React app talks to the server only through /api/ (which has its own sign-in and permission
checks), plus /media/ and /static/. The older Django pages (about 110 of them: bed allocation,
discharge, IPD notes, plan/ward prices, invoices, prescription approval, emails...) were written
without sign-in checks. This middleware closes them to anyone who is not signed in, without
touching the React app.

Settings
    LEGACY_PAGES = 'readonly' (default) signed-in staff may VIEW old pages; anything that changes data is
                              refused (POST/PUT/PATCH/DELETE, and old links that delete or update on a plain
                              visit, e.g. plans/delete/<id>). Changes go through the main app, which keeps
                              history and applies the money and clinical-record rules.
    LEGACY_PAGES = 'login'    signed-in staff may use old pages fully (no history kept: avoid)
    LEGACY_PAGES = 'off'      the old pages are closed for everyone (404); use when nobody uses them
"""
import re
from django.conf import settings
from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import redirect

# Paths that do their own access checks, or must work before sign-in.
OPEN_PREFIXES = (
    '/api/',            # DRF: token/session auth + permissions per view
    '/admin/',          # Django admin has its own login
    '/media/',          # protected_media checks the user itself
    '/static/',
    '/health',
    '/favicon.ico',
    '/case_note/', '/filtered_case_note/',   # check the user themselves (kept for old links)
)
OPEN_EXACT = {'/', '/logout/'}               # the old login page and logout

# Old links that change data even on a plain GET (they were written that way).
WRITE_WORDS = re.compile(
    r'(^|[/_-])(delete|remove|update|edit|create|add|upload|approve|decline|allocate|discharge|autosave|save|send|'
    r'email|import|complete|completed|cancel|reset|toggle|change|merge|transfer|dispense|issue|refund|pay|'
    r'requisitions|signature|transcript)([/_-]|$)', re.I)


def _is_open(path):
    return path in OPEN_EXACT or path.startswith(OPEN_PREFIXES)


def _wants_json(request):
    accept = request.META.get('HTTP_ACCEPT', '')
    return (request.method != 'GET' or 'application/json' in accept
            or request.headers.get('x-requested-with') == 'XMLHttpRequest')


class LegacyPagesGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if not _is_open(path):
            mode = str(getattr(settings, 'LEGACY_PAGES', 'readonly')).lower()
            if mode == 'off':
                return HttpResponseNotFound('Not found')
            if not request.user.is_authenticated:
                if _wants_json(request):
                    return JsonResponse({'error': 'Please sign in.'}, status=401)
                return redirect(f"/?next={path}")
            if not request.user.is_active:
                return JsonResponse({'error': 'This account is disabled.'}, status=403)
            if mode != 'login' and (request.method not in ('GET', 'HEAD', 'OPTIONS') or WRITE_WORDS.search(path)):
                return JsonResponse({'error': 'This old page is read-only. Make the change in the main Clinic365 app, '
                                              'which keeps the history of every change.', 'code': 'legacy_read_only'},
                                    status=403)
        return self.get_response(request)
