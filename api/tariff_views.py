from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from decimal import Decimal

from queue_operations.models import RegFee
from patients.models import PatientPlan
from IPD.models import Ward
from radio_lab.models import RadioLabInventory
from inventory.models import PharmacyTariff
from myAdmins.models import OtherService2, Packages, PackagesData
from users.models import User


# ==========================================================
# 1. SERVICE TARIFFS
# ==========================================================

# 1.1 Registration Fees
class RegistrationFeeView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        plans = RegFee.objects.all().order_by('plan_name')
        data = [{'id': p.id, 'plan_name': p.plan_name, 'price': p.price} for p in plans]
        return Response({'total': len(data), 'plans': data})

    def post(self, request):
        plan_name = request.data.get('plan_name', '').strip()
        price = request.data.get('price', 0)

        if not plan_name:
            return Response({'detail': 'Plan name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            price = int(price)
            if price < 0:
                return Response({'detail': 'Price cannot be negative.'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid price format.'}, status=status.HTTP_400_BAD_REQUEST)

        if RegFee.objects.filter(plan_name__iexact=plan_name).exists():
            return Response({'detail': f'Plan "{plan_name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        obj = RegFee.objects.create(plan_name=plan_name, price=price)
        return Response({'detail': f'Plan "{obj.plan_name}" created successfully.', 'id': obj.id, 'plan_name': obj.plan_name, 'price': obj.price})

    def put(self, request, pk=None):
        try:
            plan = RegFee.objects.get(id=pk)
        except RegFee.DoesNotExist:
            return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

        plan_name = request.data.get('plan_name', plan.plan_name).strip()
        price = request.data.get('price', plan.price)

        if RegFee.objects.filter(plan_name__iexact=plan_name).exclude(id=pk).exists():
            return Response({'detail': f'Another plan with name "{plan_name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            plan.price = int(price)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid price format.'}, status=status.HTTP_400_BAD_REQUEST)

        plan.plan_name = plan_name
        plan.save()
        return Response({'detail': 'Plan updated successfully.', 'id': plan.id, 'plan_name': plan.plan_name, 'price': plan.price})

    def delete(self, request, pk=None):
        try:
            plan = RegFee.objects.get(id=pk)
            plan.delete()
            return Response({'detail': 'Plan deleted successfully.'})
        except RegFee.DoesNotExist:
            return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)


# 1.2 Laboratory Charges
class LabChargesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = RadioLabInventory.objects.filter(type='L').select_related('plan').order_by('item')
        plan_id = request.query_params.get('plan')
        if plan_id:
            qs = qs.filter(plan_id=plan_id)

        data = []
        for item in qs:
            data.append({
                'id': item.id,
                'item': item.item,
                'item_id': item.item_id or '',
                'rate': float(item.rate),
                'plan_id': item.plan.id if item.plan else None,
                'plan_name': item.plan.plan if item.plan else 'All Plans',
            })
        return Response({'total': len(data), 'charges': data})

    def post(self, request):
        item_name = request.data.get('item', '').strip()
        item_id = request.data.get('item_id', '').strip()
        rate = request.data.get('rate', 0)
        plan_id = request.data.get('plan_id')

        if not item_name:
            return Response({'detail': 'Test item name required.'}, status=status.HTTP_400_BAD_REQUEST)

        plan = None
        if plan_id:
            try:
                plan = PatientPlan.objects.get(id=plan_id)
            except PatientPlan.DoesNotExist:
                return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

        staff = request.user if request.user.is_authenticated else User.objects.first()

        obj = RadioLabInventory.objects.create(
            item=item_name,
            item_id=item_id or f"LAB-{RadioLabInventory.objects.count()+1:03d}",
            rate=Decimal(str(rate)),
            type='L',
            plan=plan,
            staff=staff
        )
        return Response({
            'detail': f'Lab charge "{obj.item}" created.',
            'id': obj.id,
            'item': obj.item,
            'item_id': obj.item_id,
            'rate': float(obj.rate),
            'plan_name': obj.plan.plan if obj.plan else 'All Plans'
        })

    def put(self, request, pk=None):
        try:
            obj = RadioLabInventory.objects.get(id=pk, type='L')
        except RadioLabInventory.DoesNotExist:
            return Response({'detail': 'Lab charge not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'item' in request.data: obj.item = request.data['item'].strip()
        if 'rate' in request.data: obj.rate = Decimal(str(request.data['rate']))
        if 'item_id' in request.data: obj.item_id = request.data['item_id'].strip()
        if 'plan_id' in request.data and request.data['plan_id']:
            try:
                obj.plan = PatientPlan.objects.get(id=request.data['plan_id'])
            except PatientPlan.DoesNotExist:
                pass

        obj.save()
        return Response({'detail': 'Lab charge updated.', 'id': obj.id, 'item': obj.item, 'rate': float(obj.rate)})

    def delete(self, request, pk=None):
        try:
            RadioLabInventory.objects.filter(id=pk, type='L').delete()
            return Response({'detail': 'Lab charge deleted.'})
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# 1.3 Radiology Charges
class RadiologyChargesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = RadioLabInventory.objects.filter(type='R').select_related('plan').order_by('item')
        plan_id = request.query_params.get('plan')
        if plan_id:
            qs = qs.filter(plan_id=plan_id)

        data = []
        for item in qs:
            data.append({
                'id': item.id,
                'item': item.item,
                'item_id': item.item_id or '',
                'rate': float(item.rate),
                'plan_id': item.plan.id if item.plan else None,
                'plan_name': item.plan.plan if item.plan else 'All Plans',
            })
        return Response({'total': len(data), 'charges': data})

    def post(self, request):
        item_name = request.data.get('item', '').strip()
        item_id = request.data.get('item_id', '').strip()
        rate = request.data.get('rate', 0)
        plan_id = request.data.get('plan_id')

        if not item_name:
            return Response({'detail': 'Scan item name required.'}, status=status.HTTP_400_BAD_REQUEST)

        plan = None
        if plan_id:
            try:
                plan = PatientPlan.objects.get(id=plan_id)
            except PatientPlan.DoesNotExist:
                return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

        staff = request.user if request.user.is_authenticated else User.objects.first()

        obj = RadioLabInventory.objects.create(
            item=item_name,
            item_id=item_id or f"SCN-{RadioLabInventory.objects.count()+1:03d}",
            rate=Decimal(str(rate)),
            type='R',
            plan=plan,
            staff=staff
        )
        return Response({
            'detail': f'Radiology charge "{obj.item}" created.',
            'id': obj.id,
            'item': obj.item,
            'item_id': obj.item_id,
            'rate': float(obj.rate),
            'plan_name': obj.plan.plan if obj.plan else 'All Plans'
        })

    def put(self, request, pk=None):
        try:
            obj = RadioLabInventory.objects.get(id=pk, type='R')
        except RadioLabInventory.DoesNotExist:
            return Response({'detail': 'Radiology charge not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'item' in request.data: obj.item = request.data['item'].strip()
        if 'rate' in request.data: obj.rate = Decimal(str(request.data['rate']))
        if 'item_id' in request.data: obj.item_id = request.data['item_id'].strip()
        if 'plan_id' in request.data and request.data['plan_id']:
            try:
                obj.plan = PatientPlan.objects.get(id=request.data['plan_id'])
            except PatientPlan.DoesNotExist:
                pass

        obj.save()
        return Response({'detail': 'Radiology charge updated.', 'id': obj.id, 'item': obj.item, 'rate': float(obj.rate)})

    def delete(self, request, pk=None):
        try:
            RadioLabInventory.objects.filter(id=pk, type='R').delete()
            return Response({'detail': 'Radiology charge deleted.'})
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# 1.4 Admission Fees (Wards)
class AdmissionFeesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        wards = Ward.objects.all().order_by('ward_name')
        data = [{'id': w.id, 'ward_name': w.ward_name, 'price': w.price} for w in wards]
        return Response({'total': len(data), 'wards': data})

    def post(self, request):
        ward_name = request.data.get('ward_name', '').strip()
        price = request.data.get('price', 0)

        if not ward_name:
            return Response({'detail': 'Ward name required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            price = int(price)
            if price < 0:
                return Response({'detail': 'Price cannot be negative.'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid price format.'}, status=status.HTTP_400_BAD_REQUEST)

        if Ward.objects.filter(ward_name__iexact=ward_name).exists():
            return Response({'detail': f'Ward "{ward_name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        w = Ward.objects.create(ward_name=ward_name, price=price)
        return Response({'detail': f'Ward "{w.ward_name}" created.', 'id': w.id, 'ward_name': w.ward_name, 'price': w.price})

    def put(self, request, pk=None):
        try:
            w = Ward.objects.get(id=pk)
        except Ward.DoesNotExist:
            return Response({'detail': 'Ward not found.'}, status=status.HTTP_404_NOT_FOUND)

        ward_name = request.data.get('ward_name', w.ward_name).strip()
        price = request.data.get('price', w.price)

        if Ward.objects.filter(ward_name__iexact=ward_name).exclude(id=pk).exists():
            return Response({'detail': f'Ward with name "{ward_name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            w.price = int(price)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid price format.'}, status=status.HTTP_400_BAD_REQUEST)

        w.ward_name = ward_name
        w.save()
        return Response({'detail': 'Ward updated.', 'id': w.id, 'ward_name': w.ward_name, 'price': w.price})

    def delete(self, request, pk=None):
        try:
            Ward.objects.filter(id=pk).delete()
            return Response({'detail': 'Ward deleted.'})
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# 1.5 Other Services Fees
class OtherServicesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = OtherService2.objects.all().select_related('plan').order_by('service')
        data = []
        for s in qs:
            data.append({
                'id': s.id,
                'service': s.service,
                'service_id': s.service_id or '',
                'rate': float(s.rate),
                'plan_id': s.plan.id if s.plan else None,
                'plan_name': s.plan.plan if s.plan else 'All Plans',
            })
        return Response({'total': len(data), 'services': data})

    def post(self, request):
        service = request.data.get('service', '').strip()
        service_id = request.data.get('service_id', '').strip()
        rate = request.data.get('rate', 0)
        plan_id = request.data.get('plan_id')

        if not service:
            return Response({'detail': 'Service name required.'}, status=status.HTTP_400_BAD_REQUEST)

        plan = None
        if plan_id:
            try:
                plan = PatientPlan.objects.get(id=plan_id)
            except PatientPlan.DoesNotExist:
                pass

        staff = request.user if request.user.is_authenticated else User.objects.first()

        obj = OtherService2.objects.create(
            service=service,
            service_id=service_id or f"SRV-{OtherService2.objects.count()+1:03d}",
            rate=Decimal(str(rate)),
            plan=plan,
            staff=staff
        )
        return Response({
            'detail': f'Service "{obj.service}" created.',
            'id': obj.id,
            'service': obj.service,
            'service_id': obj.service_id,
            'rate': float(obj.rate),
            'plan_name': obj.plan.plan if obj.plan else 'All Plans'
        })

    def put(self, request, pk=None):
        try:
            obj = OtherService2.objects.get(id=pk)
        except OtherService2.DoesNotExist:
            return Response({'detail': 'Service not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'service' in request.data: obj.service = request.data['service'].strip()
        if 'rate' in request.data: obj.rate = Decimal(str(request.data['rate']))
        if 'service_id' in request.data: obj.service_id = request.data['service_id'].strip()

        obj.save()
        return Response({'detail': 'Service updated.', 'id': obj.id, 'service': obj.service, 'rate': float(obj.rate)})

    def delete(self, request, pk=None):
        OtherService2.objects.filter(id=pk).delete()
        return Response({'detail': 'Service deleted.'})


# ==========================================================
# 2. PRODUCT TARIFFS
# ==========================================================

# 2.1 Medication Fees (Pharmacy Tariff)
class MedicationFeesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = PharmacyTariff.objects.all().select_related('plan').order_by('product_name')
        plan_id = request.query_params.get('plan')
        if plan_id:
            qs = qs.filter(plan_id=plan_id)

        data = []
        for p in qs:
            data.append({
                'id': p.id,
                'product_name': p.product_name,
                'product_id': p.product_id,
                'rate': float(p.rate),
                'plan_id': p.plan.id if p.plan else None,
                'plan_name': p.plan.plan if p.plan else 'Standard',
            })
        return Response({'total': len(data), 'medications': data})

    def post(self, request):
        product_name = request.data.get('product_name', '').strip()
        product_id = request.data.get('product_id', '').strip()
        rate = request.data.get('rate', 0)
        plan_id = request.data.get('plan_id')

        if not product_name:
            return Response({'detail': 'Product name required.'}, status=status.HTTP_400_BAD_REQUEST)

        plan = None
        if plan_id:
            try:
                plan = PatientPlan.objects.get(id=plan_id)
            except PatientPlan.DoesNotExist:
                return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            plan = PatientPlan.objects.first()

        staff = request.user if request.user.is_authenticated else User.objects.first()

        obj = PharmacyTariff.objects.create(
            product_name=product_name,
            product_id=product_id or f"DRG-{PharmacyTariff.objects.count()+1:03d}",
            rate=Decimal(str(rate)),
            plan=plan,
            staff=staff
        )
        return Response({
            'detail': f'Medication tariff "{obj.product_name}" created.',
            'id': obj.id,
            'product_name': obj.product_name,
            'product_id': obj.product_id,
            'rate': float(obj.rate),
            'plan_name': obj.plan.plan if obj.plan else ''
        })

    def put(self, request, pk=None):
        try:
            obj = PharmacyTariff.objects.get(id=pk)
        except PharmacyTariff.DoesNotExist:
            return Response({'detail': 'Medication tariff not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'product_name' in request.data: obj.product_name = request.data['product_name'].strip()
        if 'rate' in request.data: obj.rate = Decimal(str(request.data['rate']))
        if 'product_id' in request.data: obj.product_id = request.data['product_id'].strip()

        obj.save()
        return Response({'detail': 'Medication tariff updated.', 'id': obj.id, 'product_name': obj.product_name, 'rate': float(obj.rate)})

    def delete(self, request, pk=None):
        PharmacyTariff.objects.filter(id=pk).delete()
        return Response({'detail': 'Medication tariff deleted.'})


# ==========================================================
# 3. MANAGE PACKAGES
# ==========================================================

# 3.1 Packages
class PackagesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        packages = Packages.objects.all().select_related('staff').order_by('-created_date')
        data = []
        for p in packages:
            data.append({
                'id': p.id,
                'name': p.name,
                'staff_name': p.staff.fullname if p.staff else 'Admin',
                'created_date': p.created_date.isoformat() if p.created_date else None,
                'items_count': PackagesData.objects.filter(package=p).count()
            })
        return Response({'total': len(data), 'packages': data})

    def post(self, request):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'detail': 'Package name required.'}, status=status.HTTP_400_BAD_REQUEST)

        if Packages.objects.filter(name__iexact=name).exists():
            return Response({'detail': f'Package "{name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        staff = request.user if request.user.is_authenticated else User.objects.first()
        pkg = Packages.objects.create(name=name, staff=staff)
        return Response({'detail': f'Package "{pkg.name}" created.', 'id': pkg.id, 'name': pkg.name})

    def put(self, request, pk=None):
        try:
            pkg = Packages.objects.get(id=pk)
        except Packages.DoesNotExist:
            return Response({'detail': 'Package not found.'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        if not name:
            return Response({'detail': 'Package name required.'}, status=status.HTTP_400_BAD_REQUEST)

        pkg.name = name
        pkg.save()
        return Response({'detail': 'Package updated.', 'id': pkg.id, 'name': pkg.name})

    def delete(self, request, pk=None):
        Packages.objects.filter(id=pk).delete()
        return Response({'detail': 'Package deleted.'})


# 3.2 Package Data Items
class PackageDataView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        package_id = request.query_params.get('package_id')
        qs = PackagesData.objects.all().select_related('package').order_by('type')
        if package_id:
            qs = qs.filter(package_id=package_id)

        data = []
        for item in qs:
            data.append({
                'id': item.id,
                'package_id': item.package.id if item.package else None,
                'package_name': item.package.name if item.package else '',
                'item': item.item,
                'type': item.type,
                'rate': float(item.rate),
            })
        return Response({'total': len(data), 'items': data})

    def post(self, request):
        package_id = request.data.get('package_id')
        item_name = request.data.get('item', '').strip()
        item_type = request.data.get('type', 'SR').strip()
        rate = request.data.get('rate', 0)

        if not package_id or not item_name:
            return Response({'detail': 'Package ID and item name are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            pkg = Packages.objects.get(id=package_id)
        except Packages.DoesNotExist:
            return Response({'detail': 'Package not found.'}, status=status.HTTP_404_NOT_FOUND)

        staff = request.user if request.user.is_authenticated else User.objects.first()

        obj = PackagesData.objects.create(
            package=pkg,
            item=item_name,
            type=item_type,
            rate=Decimal(str(rate)),
            staff=staff
        )
        return Response({
            'detail': f'Item "{obj.item}" added to package "{pkg.name}".',
            'id': obj.id,
            'package_id': pkg.id,
            'item': obj.item,
            'type': obj.type,
            'rate': float(obj.rate)
        })

    def put(self, request, pk=None):
        try:
            item = PackagesData.objects.get(id=pk)
        except PackagesData.DoesNotExist:
            return Response({'detail': 'Package item not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'item' in request.data: item.item = request.data['item'].strip()
        if 'type' in request.data: item.type = request.data['type'].strip()
        if 'rate' in request.data: item.rate = Decimal(str(request.data['rate']))

        item.save()
        return Response({'detail': 'Package item updated.', 'id': item.id, 'item': item.item, 'rate': float(item.rate)})

    def delete(self, request, pk=None):
        PackagesData.objects.filter(id=pk).delete()
        return Response({'detail': 'Package item deleted.'})


# 3.3 Immunization Fees
class ImmunizationFeesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        # Sample immunization catalog fees
        immunizations = [
            {'id': 1, 'vaccine_name': 'BCG (Bacille Calmette-Guérin)', 'target': 'Newborns', 'schedule': 'At Birth', 'fee': 3500},
            {'id': 2, 'vaccine_name': 'OPV (Oral Polio Vaccine)', 'target': 'Infants', 'schedule': 'Birth, 6, 10, 14 Weeks', 'fee': 2500},
            {'id': 3, 'vaccine_name': 'Pentavalent (DTP-HepB-Hib)', 'target': 'Infants', 'schedule': '6, 10, 14 Weeks', 'fee': 6000},
            {'id': 4, 'vaccine_name': 'Rotavirus Vaccine', 'target': 'Infants', 'schedule': '6, 10 Weeks', 'fee': 8500},
            {'id': 5, 'vaccine_name': 'Yellow Fever Vaccine', 'target': 'Infants / Adults', 'schedule': '9 Months / Booster', 'fee': 5000},
            {'id': 6, 'vaccine_name': 'Measles Vaccine', 'target': 'Infants', 'schedule': '9 Months', 'fee': 4000},
            {'id': 7, 'vaccine_name': 'Tetanus Toxoid (TT)', 'target': 'Maternal / Adults', 'schedule': 'Antenatal Schedule', 'fee': 2000},
            {'id': 8, 'vaccine_name': 'Hepatitis B Adult Booster', 'target': 'Adults / Staff', 'schedule': '0, 1, 6 Months', 'fee': 7500},
        ]
        return Response({'total': len(immunizations), 'immunizations': immunizations})
