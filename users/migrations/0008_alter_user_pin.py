# Generated manually to alter pin column to HashedPinField and hash all existing PINs
from django.db import migrations
import users.models
from django.contrib.auth.hashers import make_password


def hash_existing_pins(apps, schema_editor):
    User = apps.get_model('users', 'User')
    for user in User.objects.all():
        if user.pin and str(user.pin).strip() not in ('', '0'):
            raw = str(user.pin).strip()
            if not raw.startswith(('pbkdf2_', 'argon2', 'bcrypt', 'sha1_')):
                user.pin = make_password(raw)
                user.save(update_fields=['pin'])
        else:
            if user.pin != '':
                user.pin = ''
                user.save(update_fields=['pin'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_submodule_route'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE users_user DROP CONSTRAINT IF EXISTS users_user_pin_check;
                ALTER TABLE users_user ALTER COLUMN pin TYPE varchar(128) USING CASE WHEN pin = 0 THEN '' ELSE pin::varchar END;
                ALTER TABLE users_user ALTER COLUMN pin SET DEFAULT '';
            """,
            reverse_sql="""
                ALTER TABLE users_user ALTER COLUMN pin TYPE integer USING CASE WHEN pin = '' THEN 0 ELSE 0 END;
                ALTER TABLE users_user ALTER COLUMN pin SET DEFAULT 0;
            """,
        ),
        migrations.AlterField(
            model_name='user',
            name='pin',
            field=users.models.HashedPinField(blank=True, default='', max_length=128),
        ),
        migrations.RunPython(hash_existing_pins, noop_reverse),
    ]
