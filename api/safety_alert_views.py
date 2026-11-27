"""Infection-control alerts on a patient (see patients/safety_alerts.py)."""
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from api.audit import audit
from api.pin_identity import display_name, staff_by_pin
from patients import safety_alerts as sa
from patients.models import PatientProfile, PatientSafetyAlert

# Who may sign: raising is a bedside / clinical / lab call; clearing is a clinical decision.
RAISE_MODULES = ('nursing', 'clinical', 'laboratory', 'inpatient')
CLEAR_MODULES = ('clinical', 'laboratory')


def _err(e, http=400):
    return Response({'detail': e.message, 'error': e.message, 'code': e.code}, status=http)


def _precautions():
    return [{'value': k, 'label': v, 'hint': sa.PRECAUTION_HINTS.get(k, '')} for k, v in sa.PRECAUTION_LABELS.items()]


class PatientSafetyAlertsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        patient = get_object_or_404(PatientProfile, pk=pk)
        rows = [sa.alert_row(a) for a in PatientSafetyAlert.objects.filter(patient=patient)
                .select_related('raised_by', 'cleared_by')]
        return Response({'active': [r for r in rows if r['is_active']],
                         'history': [r for r in rows if not r['is_active']],
                         'precautions': _precautions()})

    def post(self, request, pk):
        patient = get_object_or_404(PatientProfile, pk=pk)
        user, err = staff_by_pin(request, RAISE_MODULES, 'clinical or nursing', 'raise an infection-control alert')
        if err:
            return err
        try:
            alert, created = sa.raise_alert(patient, precaution=request.data.get('precaution'), by=user,
                                            instruction=request.data.get('instruction'), source='clinician')
        except sa.SafetyAlertError as e:
            return _err(e)
        audit(user, 'safety_alert_raised', request,
              f'{sa.PRECAUTION_LABELS[alert.precaution]} for patient {patient.hospital_number}')
        label = sa.PRECAUTION_LABELS[alert.precaution]
        return Response({'detail': f'{label} alert {"raised" if created else "already active"} '
                                   f'(signed by {display_name(user)}).',
                         'alert': sa.alert_row(alert), 'active': sa.active_alerts(patient)},
                        status=201 if created else 200)


class SafetyAlertClearView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        alert = get_object_or_404(PatientSafetyAlert.objects.select_related('patient'), pk=pk)
        user, err = staff_by_pin(request, CLEAR_MODULES, 'clinical or laboratory', 'clear an infection-control alert')
        if err:
            return err
        try:
            sa.clear_alert(alert, by=user, reason=request.data.get('reason'))
        except sa.SafetyAlertError as e:
            return _err(e)
        audit(user, 'safety_alert_cleared', request,
              f'{sa.PRECAUTION_LABELS[alert.precaution]} for patient {alert.patient.hospital_number}: '
              f'{str(request.data.get("reason") or "")[:200]}')
        return Response({'detail': f'Alert cleared (signed by {display_name(user)}).',
                         'active': sa.active_alerts(alert.patient)})
