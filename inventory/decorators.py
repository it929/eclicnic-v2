from functools import wraps
from django.http import HttpResponseRedirect
from django.contrib import messages

def department_required(*allowed_departments):
    """
    Restrict access to specific departments.
    Example:
        @department_required('Inventory', 'Laboratory', 'Radiology')
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper_func(request, *args, **kwargs):
            user_department = getattr(request.user.department, 'department', None)

            if user_department not in allowed_departments:
                # Show feedback
                messages.warning(request, "You are not authorized to access this page.")
                # Redirect to the page the user came from (fallback to '/')
                return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))
            
            return view_func(request, *args, **kwargs)
        return wrapper_func
    return decorator

# def inventory(view_func):
#     def wrapper_func(request, *args, **kwargs):
#         # check department safely
#         if not hasattr(request.user, 'department') or request.user.department.department != 'Inventory':
#             messages.error(request, "Access Denied: You’re not authorized to access this page.")
            
#             # get the previous page URL (fallback to home if none)
#             referer = request.META.get('HTTP_REFERER', '/')
#             return HttpResponseRedirect(referer)
        
#         # if authorized
#         return view_func(request, *args, **kwargs)
#     return wrapper_func


# from django.http import HttpResponseRedirect
# from django.contrib import messages
# from django.utils import timezone
# from django.core.mail import send_mail
# from django.conf import settings
# import logging
# from functools import wraps


# # Setup logger
# logger = logging.getLogger(__name__)


# def restrict_to(department_name):
#     """
#     Restrict access to users belonging to a specific department.
#     Usage:
#         @restrict_to('Inventory')
#         def view_func(request): ...
#     """
#     def decorator(view_func):
#         @wraps(view_func)
#         def wrapper_func(request, *args, **kwargs):
#             user = request.user

#             # Get department name safely
#             user_department = getattr(
#                 getattr(user, 'department', None),
#                 'department',
#                 None
#             )

#             # Check if the user's department matches the required one
#             if user_department != department_name:
#                 # Gather useful details
#                 username = user.fullname or user.username
#                 ip = get_client_ip(request)
#                 path = request.path
#                 timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

#                 # Log attempt
#                 logger.warning(
#                     f"Unauthorized access attempt by {username} "
#                     f"({user_department}) to {path} on {timestamp} from {ip}"
#                 )

#                 # Notify admin (optional)
#                 try:
#                     send_mail(
#                         subject=f"Unauthorized Access Attempt - {department_name} Page",
#                         message=(
#                             f"User '{username}' from department '{user_department}' "
#                             f"attempted to access '{path}' on {timestamp} from {ip}."
#                         ),
#                         from_email=settings.DEFAULT_FROM_EMAIL,
#                         recipient_list=[admin_email for _, admin_email in getattr(settings, 'ADMINS', [])],
#                         fail_silently=True
#                     )
#                 except Exception as e:
#                     logger.error(f"Failed to send admin notification: {e}")

#                 # Flash warning message
#                 messages.warning(
#                     request,
#                     f"You are not authorized to access the {department_name} section."
#                 )

#                 # Redirect back to previous page or home
#                 referer = request.META.get('HTTP_REFERER', '/')
#                 return HttpResponseRedirect(referer)

#             # Authorized
#             return view_func(request, *args, **kwargs)
#         return wrapper_func
#     return decorator


# def get_client_ip(request):
#     """Safely extract client IP."""
#     x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
#     if x_forwarded_for:
#         return x_forwarded_for.split(',')[0]
#     return request.META.get('REMOTE_ADDR')
