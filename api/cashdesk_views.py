"""Cash desk: a patient's account (deposit balance, bills still owed), deposits and deposit refunds.
The rules live in Billings/cashdesk.py; these views only check who may do it."""
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from Billings.cashdesk import CashDeskError, account_summary, record_deposit, refund_deposit
from patients.models import PatientProfile


def _billing_staff(user):
    from api.notification_views import _has_module
    return _has_module(user, 'billings') or _has_module(user, 'fd_billing')


def _err(e):
    return Response({'error': e.message, 'code': e.code, **e.extra}, status=e.status)


def _forbidden(what):
    return Response({'error': f'Only billing staff can {what}.'}, status=status.HTTP_403_FORBIDDEN)


class PatientAccountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        if not _billing_staff(request.user):
            return _forbidden('see patient accounts')
        return Response(account_summary(get_object_or_404(PatientProfile, pk=pk)))


class PatientDepositView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not _billing_staff(request.user):
            return _forbidden('record a deposit')
        patient = get_object_or_404(PatientProfile, pk=pk)
        d = request.data
        try:
            dep, balance = record_deposit(patient, by=request.user, amount=d.get('amount'),
                                          method=d.get('payment_type') or 'Cash', reference=d.get('reference'),
                                          note=d.get('note'), request_id=d.get('request_id'),
                                          wallet=d.get('wallet') or 'own')
        except CashDeskError as e:
            return _err(e)
        return Response({
            'status': 'success', 'deposit_id': dep.id, 'slip_number': dep.slip_number,
            'amount': int(dep.amount), 'payment_type': dep.payment_type, 'reference': dep.reference,
            'deposit_balance': balance, 'wallet': 'family' if dep.family_id else 'own',
            'family_name': dep.family.family_name if dep.family_id else '',
            'message': f'{"Family deposit" if dep.family_id else "Deposit"} slip {dep.slip_number}: ₦{int(dep.amount):,} received. Balance on deposit ₦{balance:,}.',
        }, status=status.HTTP_201_CREATED)


class PatientDepositRefundView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not _billing_staff(request.user):
            return _forbidden('refund a deposit')
        patient = get_object_or_404(PatientProfile, pk=pk)
        d = request.data
        try:
            refund, balance = refund_deposit(patient, by=request.user, amount=d.get('amount'),
                                             method=d.get('payment_type') or 'Cash',
                                             reason=d.get('reason'), reference=d.get('reference'),
                                             wallet=d.get('wallet') or 'own')
        except CashDeskError as e:
            return _err(e)
        return Response({
            'status': 'success', 'refund_id': refund.id, 'amount': int(refund.amount), 'deposit_balance': balance,
            'message': (f'₦{int(refund.amount):,} refunded from the {"family " if refund.payment_to == "Family" else ""}deposit. '
                        f'Balance ₦{balance:,}.'),
        }, status=status.HTTP_201_CREATED)


class CashUpView(APIView):
    """GET billing/cash-up/?date=YYYY-MM-DD[&staff=<id>]: end-of-day money in/out by method and cashier.
    For reports: ?from=YYYY-MM-DD&to=YYYY-MM-DD (at most 366 days)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from datetime import date as _date
        from django.utils import timezone
        from api.notification_views import _has_module
        from Billings.cashup import cash_up
        # Cashiers, and management who use Reporting, may see collections.
        if not (_billing_staff(request.user) or _has_module(request.user, 'reporting')):
            return _forbidden('see collections')
        q = request.query_params
        try:
            if q.get('from') or q.get('to'):
                first = _date.fromisoformat(q.get('from') or q.get('to'))
                last = _date.fromisoformat(q.get('to') or q.get('from'))
            else:
                first = last = _date.fromisoformat(q['date']) if q.get('date') else timezone.localdate()
        except ValueError:
            return Response({'error': 'Dates must be YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        if last < first:
            return Response({'error': 'The "to" date is before the "from" date.'}, status=status.HTTP_400_BAD_REQUEST)
        if (last - first).days > 366:
            return Response({'error': 'Choose a period of one year or less.'}, status=status.HTTP_400_BAD_REQUEST)
        staff = q.get('staff')
        return Response(cash_up(first, int(staff) if str(staff or '').isdigit() else None, end_day=last))
