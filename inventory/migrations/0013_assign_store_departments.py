"""
One-off starting point for store <-> department assignment, using the same name rules the
app used to guess with (so nobody loses access on upgrade). Administrators review and change
it afterwards in Inventory > Pharmacies & Sub-Stores.

    "Medical Store", "Central Store", ... (contains 'store', not 'pharm') -> the Central Medical Store
    "OPD Pharmacy 1"  -> store named "OPD Pharmacy 1"
    "IPD Pharmacy 1"  -> the IPD pharmacy whose code/name carries "1"
"""
import re

from django.db import migrations


def _norm(v):
    return re.sub(r'[^a-z0-9]', '', (v or '').lower())


def _num(v):
    m = re.search(r'(\d+)', v or '')
    return m.group(1) if m else None


def assign(apps, schema_editor):
    Category = apps.get_model('users', 'Category')
    Store = apps.get_model('inventory', 'PharmacyStore')
    stores = list(Store.objects.all())
    central = next((s for s in stores if s.is_central), None)
    for dept in Category.objects.all():
        name = (dept.department or '').strip()
        low = name.lower()
        if not name or low in ('admin', 'cmd', 'administrator'):
            continue  # admins already reach every store
        target = None
        if 'store' in low and 'pharm' not in low:
            target = central
        if target is None:
            target = next((s for s in stores if _norm(s.name) == _norm(name) or _norm(s.code) == _norm(name)), None)
        if target is None and 'pharm' in low:
            kind = 'ipd_pharmacy' if 'ipd' in low else 'opd_pharmacy' if 'opd' in low else 'emergency_pharmacy' if 'emerg' in low else None
            n = _num(name)
            if kind:
                same = [s for s in stores if s.store_type == kind]
                target = next((s for s in same if n and n in (_num(s.code) or '') + (_num(s.name) or '')), None)
        if target is not None:
            target.departments.add(dept)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0012_store_departments'),
    ]

    operations = [migrations.RunPython(assign, migrations.RunPython.noop)]
