from .models import UserActivityLog
from django.utils import timezone
import json
from .models import UserSession
from datetime import timedelta
from django.db.models import Max


try:
    from user_agents import parse
except ImportError:
    # Fallback if user_agents is not installed
    def parse(ua_string):
        class FakeUserAgent:
            browser = type('obj', (object,), {'family': None, 'version_string': None})
            os = type('obj', (object,), {'family': None, 'version_string': None})
            device = type('obj', (object,), {'brand': None})
            is_mobile = False
            is_tablet = False
            is_pc = False
            is_bot = False
        return FakeUserAgent()

def log_user_activity(user, activity_type, request, description=None, additional_data=None):
    """
    Log user activity with browser and device information
    """
    try:
        # Parse user agent
        user_agent_string = request.META.get('HTTP_USER_AGENT', '')
        user_agent = parse(user_agent_string)
        
        # Get IP address (handles proxy cases)
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0]
        else:
            ip_address = request.META.get('REMOTE_ADDR')
        
        # Determine device type
        if hasattr(user_agent, 'is_mobile') and user_agent.is_mobile:
            device_type = 'Mobile'
        elif hasattr(user_agent, 'is_tablet') and user_agent.is_tablet:
            device_type = 'Tablet'
        elif hasattr(user_agent, 'is_pc') and user_agent.is_pc:
            device_type = 'Desktop'
        elif hasattr(user_agent, 'is_bot') and user_agent.is_bot:
            device_type = 'Bot'
        else:
            device_type = 'Unknown'
        
        # Get browser and OS info safely
        browser_name = None
        browser_version = None
        if hasattr(user_agent, 'browser') and user_agent.browser:
            browser_name = getattr(user_agent.browser, 'family', None)
            browser_version = getattr(user_agent.browser, 'version_string', None)
        
        os_name = None
        os_version = None
        if hasattr(user_agent, 'os') and user_agent.os:
            os_name = getattr(user_agent.os, 'family', None)
            os_version = getattr(user_agent.os, 'version_string', None)
        
        device_brand = None
        if hasattr(user_agent, 'device') and user_agent.device:
            device_brand = getattr(user_agent.device, 'brand', None)
        
        # Create log entry
        UserActivityLog.objects.create(
            user=user,
            activity_type=activity_type,
            description=description,
            browser_name=browser_name,
            browser_version=browser_version,
            os_name=os_name,
            os_version=os_version,
            device_type=device_type,
            device_brand=device_brand,
            ip_address=ip_address,
            # location=None,  
            # latitude=None,
            # longitude=None,
            session_key=request.session.session_key if request.session.session_key else None,
            referrer_url=request.META.get('HTTP_REFERER'),
            page_accessed=request.path,
            user_agent=user_agent_string,
            additional_data=additional_data
        )
    except Exception as e:
        print(f"Error logging user activity: {e}")


def get_online_users(timeout_minutes=5):
    """
    Get users who have been active within the last X minutes
    """
    time_threshold = timezone.now() - timedelta(minutes=timeout_minutes)
    
    # Get distinct users with their latest session
    online_sessions = UserSession.objects.filter(
        last_activity__gte=time_threshold
    ).select_related('user')  
    
    online_users = []
    for session in online_sessions:
        online_users.append({
            'user': session.user,
            'login_time': session.login_time,
            'last_activity': session.last_activity,
            'ip_address': session.ip_address,
            'browser': session.browser_name,
            'os': session.os_name,
            'device': session.device_type,
            'session_key': session.session_key
        })
    
    return online_users

def get_online_users_count(timeout_minutes=5):
    """Get count of online users (unique users)"""
    time_threshold = timezone.now() - timedelta(minutes=timeout_minutes)
    return UserSession.objects.filter(
        last_activity__gte=time_threshold
    ).values('user').distinct().count()


from decimal import Decimal, ROUND_HALF_UP
def calculate_revenue(price, qty=None, discount_percent=None):
    return Decimal(price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def get_service_type_mapping():
    """Mapping for service types to original_source_model values"""
    return {
        'Medications fee': [
            'IPDAdministeredDrugs', 'IPD2AdministeredDrugs', 
            'IPD3AdministeredDrugs', 'OPDAdministeredDrugs', 'OPD2AdministeredDrugs'
        ],
        'Registration fee': ['GetRegistrationFee'],
        'Consultation fee': ['NurseWaitingList'],
        'Investigations fee': ['RadiologyLab'],
        'Admission fee': ['AdmissionFee'],
        'Antenatal care': ['AntenatalFee'],
        'Other Services': ['OtherService']
    }