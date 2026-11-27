"""
Clinical record protection: what may be changed through the REST API, by whom, and the history of
every change (patients.ClinicalRecordHistory).

Rules
- Clinical records are never deleted through the API. Mistakes are corrected by a new entry, or
  for the few records where removal is allowed (e.g. a vaccine entered in error that was never
  given or billed) through a dedicated endpoint that needs a reason and keeps the removed record.
- Signed records (consultation notes, written prescriptions, vitals) are not editable at all.
- Records that may be edited list the fields that may change; every change keeps the before and
  after values, who made it, when, and the reason given (`change_reason` in the request).
"""
import json

from django.core.serializers.json import DjangoJSONEncoder
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response


def snapshot(instance):
    """All concrete field values of a record, JSON-safe (FKs as ids)."""
    data = {f.attname: getattr(instance, f.attname) for f in instance._meta.concrete_fields}
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder, default=str))


def _patient_id(instance):
    from patients.models import PatientProfile
    if isinstance(instance, PatientProfile):
        return instance.pk
    return getattr(instance, 'patient_id', None)


def _ip(request):
    if request is None:
        return ''
    fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (fwd.split(',')[0].strip() if fwd else request.META.get('REMOTE_ADDR', ''))[:45]


def record_change(instance, *, before, after=None, action='update', by=None, reason='', request=None):
    """Store one history row. `after` None = the record was removed. Returns the row (or None if nothing changed)."""
    from patients.models import ClinicalRecordHistory
    if action == 'update':
        changes = {k: [before.get(k), v] for k, v in (after or {}).items() if before.get(k) != v}
        if not changes:
            return None
    else:
        changes = {}
    return ClinicalRecordHistory.objects.create(
        model=f'{instance._meta.app_label}.{instance.__class__.__name__}', object_id=str(instance.pk),
        patient_id=_patient_id(instance), action=action, changes=changes, snapshot=before,
        reason=str(reason or '').strip()[:300], changed_by=by if getattr(by, 'is_authenticated', False) else None,
        ip_address=_ip(request))


def _reason(request):
    data = getattr(request, 'data', {}) or {}
    try:
        return str(data.get('change_reason') or '').strip()
    except AttributeError:
        return ''


class NoClinicalDeleteMixin:
    """DELETE is refused: clinical records are kept."""
    delete_refusal = ('Clinical records are never deleted. If this was entered in error, record the correction '
                      'as a new entry so the original stays in the patient record.')

    def destroy(self, request, *args, **kwargs):
        return Response({'error': self.delete_refusal, 'code': 'clinical_record_kept'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)


class SignedRecordMixin(NoClinicalDeleteMixin):
    """Signed records: no edits and no deletes through the API."""
    edit_refusal = 'This record was signed and cannot be changed. Add a new entry instead.'

    def update(self, request, *args, **kwargs):
        return Response({'error': self.edit_refusal, 'code': 'signed_record'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)


class TrackedEditMixin(NoClinicalDeleteMixin):
    """
    Edits allowed only for `editable_fields` (None = any field), optionally only for staff with one
    of `edit_modules` (admins always may); every change is kept in ClinicalRecordHistory.
    Subclasses with their own perform_update call `self.save_tracked(serializer, **save_kwargs)`.
    """
    editable_fields = None
    edit_modules = ()
    require_reason = False

    def _check_edit(self, request, serializer):
        if self.edit_modules:
            from api.notification_views import _has_module
            if not any(_has_module(request.user, m) for m in self.edit_modules):
                raise PermissionDenied('You do not have permission to change this record.')
        if self.editable_fields is not None:
            model_fields = {f.name for f in serializer.instance._meta.concrete_fields}
            bad = sorted(k for k in serializer.validated_data if k in model_fields and k not in self.editable_fields)
            if bad:
                raise ValidationError({'error': f"These fields cannot be changed here: {', '.join(bad)}."})
        if self.require_reason and not _reason(request):
            raise ValidationError({'error': 'Say why this record is being changed (change_reason).'})

    def save_tracked(self, serializer, **kwargs):
        request = self.request
        self._check_edit(request, serializer)
        before = snapshot(serializer.instance)
        obj = serializer.save(**kwargs)
        record_change(obj, before=before, after=snapshot(obj), by=request.user, reason=_reason(request), request=request)
        return obj

    def perform_update(self, serializer):
        self.save_tracked(serializer)
