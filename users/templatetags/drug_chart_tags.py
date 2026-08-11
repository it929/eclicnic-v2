# yourapp/templatetags/drug_chart_tags.py
from django import template
from datetime import time

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Custom filter to get an item from a dictionary by key
    Usage: {{ my_dict|get_item:key }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def get_times(frequency):
    """
    Returns administration times based on frequency
    Usage: {{ prescription.frequency|get_times }}
    """
    times = {
        'od': [time(8, 0)],      # Once daily at 8 AM
        'bd': [time(8, 0), time(20, 0)],  # Twice daily at 8 AM and 8 PM
        'tds': [time(8, 0), time(16, 0), time(0, 0)],  # Three times daily
        'qds': [time(8, 0), time(12, 0), time(16, 0), time(20, 0)],  # Four times daily
        'prn': [time(8, 0), time(12, 0), time(16, 0), time(20, 0)],  # As required
        'stat': [time(0, 0)],     # Stat (immediate)
    }
    return times.get(frequency, [time(8, 0)])

@register.filter
def get_frequency_display(frequency):
    """
    Returns human-readable frequency display
    """
    frequency_display = {
        'od': 'Once Daily',
        'bd': 'Twice Daily',
        'tds': 'Three Times Daily',
        'qds': 'Four Times Daily',
        'prn': 'As Required',
        'stat': 'Stat',
    }
    return frequency_display.get(frequency, frequency)

@register.filter
def get_route_display(route):
    """
    Returns human-readable route display
    """
    route_display = {
        'oral': 'Oral',
        'iv': 'IV',
        'im': 'IM',
        'sc': 'Subcutaneous',
        'topical': 'Topical',
        'inhalation': 'Inhalation',
    }
    return route_display.get(route, route)

@register.simple_tag
def get_administration_status_class(status):
    """
    Returns CSS class for administration status
    """
    status_classes = {
        'administered': 'success',
        'missed': 'danger',
        'refused': 'warning',
        'pending': 'secondary',
        'held': 'info',
    }
    return status_classes.get(status, 'secondary')

@register.simple_tag
def get_administration_icon(status):
    """
    Returns Font Awesome icon for administration status
    """
    status_icons = {
        'administered': 'fa-check-circle',
        'missed': 'fa-times-circle',
        'refused': 'fa-ban',
        'pending': 'fa-circle',
        'held': 'fa-pause-circle',
    }
    return status_icons.get(status, 'fa-circle')