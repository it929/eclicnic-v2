# Adds the stand-alone Inpatient Billing page to the sidebar menus and grants it to every role
# that already holds the parent module (Inpatient, or Billings & Accounts).
from django.db import migrations

ENTRIES = [
    ('inpatient', {'code': 'ipdBilling', 'name': 'Inpatient Billing', 'icon': 'fa-file-invoice-dollar',
                   'tab_key': 'ipd', 'sub_tab': 'billing', 'route': '/ipd/billing', 'order': 3}),
    ('billings', {'code': 'billInpatient', 'name': 'Inpatient Bills', 'icon': 'fa-procedures',
                  'tab_key': 'ipd', 'sub_tab': 'billing', 'route': '/billings/inpatient', 'order': 6}),
]


def add_menu(apps, schema_editor):
    SystemModule = apps.get_model('users', 'SystemModule')
    SubModule = apps.get_model('users', 'SubModule')
    RolePermission = apps.get_model('users', 'RolePermission')
    for mod_code, sub in ENTRIES:
        mod = SystemModule.objects.filter(code=mod_code).first()
        if not mod:
            continue  # the module is created by seed_rbac, which also adds this submodule
        data = dict(sub)
        code = data.pop('code')
        obj, _ = SubModule.objects.update_or_create(module=mod, code=code, defaults=dict(data, is_active=True))
        for perm in RolePermission.objects.filter(module=mod):
            perm.submodules.add(obj)


def remove_menu(apps, schema_editor):
    SubModule = apps.get_model('users', 'SubModule')
    SubModule.objects.filter(code__in=[s['code'] for _, s in ENTRIES]).delete()


class Migration(migrations.Migration):
    dependencies = [('users', '0008_alter_user_pin')]
    operations = [migrations.RunPython(add_menu, remove_menu)]
