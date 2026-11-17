from django.db import migrations, models


def backfill(apps, schema_editor):
    Rec = apps.get_model('queue_operations', 'ImmunizationRecord')
    for r in Rec.objects.all():
        r.authorized_by_name = r.administered_by_name
        # Free EPI vaccines were given on the spot; billable ones wait for payment + nurse confirmation
        if r.billing_status == 'not_billable' or not r.is_billable:
            r.administration_confirmed = True
            r.confirmed_at = r.created_at
        r.save(update_fields=['authorized_by_name', 'administration_confirmed', 'confirmed_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('queue_operations', '0029_immunization_billing_trail'),
    ]

    operations = [
        migrations.AddField(
            model_name='immunizationrecord',
            name='authorized_by_name',
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AddField(
            model_name='immunizationrecord',
            name='administration_confirmed',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='immunizationrecord',
            name='confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
