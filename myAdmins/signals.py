from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.utils import timezone
from .models import UserSession

@receiver(user_logged_in)
def create_session_on_login(sender, request, user, **kwargs):
    if request and request.session.session_key:
        try:
            now = timezone.now()
            session_key = request.session.session_key
            
            UserSession.objects.update_or_create(
                user=user,
                session_key=session_key,
                defaults={
                    'created_at': now,
                    'last_activity': now,
                    'is_active': True,
                    'ip_address': request.META.get('REMOTE_ADDR', ''),
                    'login_time': now,  # Now this field exists
                }
            )
            print(f'✅ Session created for {user.username}')
        except Exception as e:
            print(f'Error creating session: {e}')

@receiver(user_logged_out)
def deactivate_session_on_logout(sender, request, user, **kwargs):
    if request and request.session.session_key:
        try:
            UserSession.objects.filter(
                user=user,
                session_key=request.session.session_key
            ).update(is_active=False)
        except Exception as e:
            print(f'Error: {e}')
