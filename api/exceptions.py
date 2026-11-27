"""API-wide error handling."""
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def api_exception_handler(exc, context):
    # Records that other records depend on (patients, staff, bills, family folders with deposits...)
    # are protected from deletion. Say so plainly instead of failing with a server error.
    if isinstance(exc, ProtectedError):
        kinds = sorted({str(o._meta.verbose_name_plural) for o in list(exc.protected_objects)[:50]})
        return Response({
            'error': ('This cannot be deleted because other records depend on it'
                      + (f" ({', '.join(kinds[:5])})" if kinds else '') + '. Deactivate it instead.'),
            'code': 'protected',
        }, status=status.HTTP_409_CONFLICT)
    return drf_exception_handler(exc, context)
