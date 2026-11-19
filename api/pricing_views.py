"""
POST /api/pricing/check/
Price a doctor's order before anything is saved, with the same rule billing uses
(api/pricing.py). The doctor's screen calls it before signing the consultation so an
item with no price is caught while the doctor is still on the page.

Body: {patient_id, prescriptions, lab_orders, radiology_orders, other_service_orders}
Reply: {ok, problems: [message], lines: [{kind, name, rate, source, covered, ...}]}
"""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.pricing import ORDER_KEYS, price_orders
from patients.models import PatientProfile


class CheckOrderPricesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        pid = request.data.get('patient_id') or request.data.get('patient')
        patient = PatientProfile.objects.select_related('sponsor', 'plan').filter(id=pid).first() if pid else None
        if not patient:
            return Response({'error': 'Patient not found.'}, status=status.HTTP_404_NOT_FOUND)
        groups = [
            ('drug', request.data.get('prescriptions') or []),
            ('lab', request.data.get('lab_orders') or []),
            ('radiology', request.data.get('radiology_orders') or []),
            ('service', request.data.get('other_service_orders') or []),
        ]
        priced, problems = price_orders(patient, groups)
        lines = []
        for kind, orders in groups:
            for o in orders:
                q = priced.get(id(o))
                if q:
                    lines.append(q.as_dict())
        return Response({'ok': not problems, 'problems': problems, 'lines': lines})
