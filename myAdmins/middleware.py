from django.utils import timezone
from .models import UserSession
from user_agents import parse

class OnlineUsersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        if request.user.is_authenticated:
            try:
                session_key = request.session.session_key
                if session_key:
                    # Update or create user session
                    user_session, created = UserSession.objects.update_or_create(
                        user=request.user,
                        session_key=session_key,
                        defaults={
                            'last_activity': timezone.now()
                        }
                    )
                    
                    # Update last activity
                    user_session.last_activity = timezone.now()
                    
                    # Get IP address
                    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
                    if x_forwarded_for:
                        user_session.ip_address = x_forwarded_for.split(',')[0]
                    else:
                        user_session.ip_address = request.META.get('REMOTE_ADDR')
                    
                    # Parse user agent
                    user_agent_string = request.META.get('HTTP_USER_AGENT', '')
                    if user_agent_string:
                        try:
                            user_agent = parse(user_agent_string)
                            user_session.browser_name = user_agent.browser.family if user_agent.browser.family else None
                            user_session.os_name = user_agent.os.family if user_agent.os.family else None
                            
                            if user_agent.is_mobile:
                                user_session.device_type = 'Mobile'
                            elif user_agent.is_tablet:
                                user_session.device_type = 'Tablet'
                            elif user_agent.is_pc:
                                user_session.device_type = 'Desktop'
                            else:
                                user_session.device_type = 'Unknown'
                        except Exception as e:
                            print(f"Error parsing user agent: {e}")
                    
                    user_session.user_agent = user_agent_string
                    user_session.save()
                    
            except Exception as e:
                print(f"Error tracking online user: {e}")
                import traceback
                traceback.print_exc()
        
        return response