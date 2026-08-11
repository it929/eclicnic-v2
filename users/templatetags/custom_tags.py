from django import template
from datetime import time
import inflect
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe
import re
register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary by key"""
    if dictionary is None:
        return None
    try:
        return dictionary.get(key)
    except (AttributeError, TypeError):
        try:
            return dictionary[int(key)] if hasattr(dictionary, '__getitem__') else None
        except (IndexError, ValueError, TypeError):
            return None

@register.filter
def currency(number):
    """Format number as currency with 2 decimal places"""
    if number is None:
        return "0.00"
    try:
        return "{:,.2f}".format(float(number))
    except (ValueError, TypeError):
        return "0.00"


@register.filter
def get_times(frequency):
    """Get administration times based on frequency"""
    times = {
        'od': ['08:00'],
        'bd': ['08:00', '20:00'],
        'tds': ['08:00', '16:00', '00:00'],
        'qds': ['08:00', '12:00', '16:00', '20:00'],
        'prn': ['08:00', '12:00', '16:00', '20:00'],
        'stat': ['00:00'],
    }
    return times.get(frequency, ['08:00'])

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

def currency(number):
    return "{:,.2f}".format(number)
register.filter('currency', currency)

def strlen25(strings):
    if len(strings) < 26:
        return strings
    else:
        return strings[:25]+"..."
register.filter('strlen25', strlen25)

def strlen20(strings):
    if len(strings) < 20:
        return strings
    else:
        return strings[:19]+"..."
register.filter('strlen20', strlen20)

def strlen70(strings):
    if len(strings) < 71:
        return strings
    else:
        return strings[:70]+"..."
register.filter('strlen70', strlen70)

def currency(number):
    return "{:,.2f}".format(number)
register.filter('currency', currency)

def strlen25(strings):
    if len(strings) < 26:
        return strings
    else:
        return strings[:25]+"..."
register.filter('strlen25', strlen25)

def strlen20(strings):
    if len(strings) < 20:
        return strings
    else:
        return strings[:19]+"..."
register.filter('strlen20', strlen20)

def strlen70(strings):
    if len(strings) < 71:
        return strings
    else:
        return strings[:70]+"..."
register.filter('strlen70', strlen70)

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def wordify(number):
    """Convert a number to words (e.g., 12345 -> Twelve Thousand Three Hundred Forty-Five)"""
    try:
        # Convert to float and then to string to handle decimal
        num = float(number)
        
        # Split into integer and decimal parts
        integer_part = int(num)
        decimal_part = int(round((num - integer_part) * 100))
        
        # Convert integer part to words
        p = inflect.engine()
        words = p.number_to_words(integer_part)
        
        # Capitalize the first letter
        words = words.capitalize()
        
        # Add decimal part if exists
        if decimal_part > 0:
            decimal_words = p.number_to_words(decimal_part)
            words += f" and {decimal_words} Kobo"
        else:
            words += " Naira Only"
        
        return words
    except Exception as e:
        return f"{number} Naira Only"
    
@register.filter
def is_invoiced(obj, invoiced_set):
    model_name = obj.__class__.__name__
    key = f"{model_name},{obj.id}"
    return key in invoiced_set

# Billings day book
@register.filter
def split(value, arg):
    """Split a string by the given delimiter"""
    if value:
        return value.split(arg)
    return []

# Billings transaction summary

@register.filter
def abs(value):
    return abs(value)

# Reporting

@register.filter
@stringfilter
def split(value, arg):
    """
    Split a string by the given delimiter
    Usage: {{ "a,b,c"|split:"," }} -> ['a', 'b', 'c']
    """
    if value:
        return value.split(arg)
    return []

@register.filter
def multiply(value, arg):
    """
    Multiply two numbers
    Usage: {{ value|multiply:2 }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def subtract(value, arg):
    """
    Subtract two numbers
    Usage: {{ value|subtract:5 }}
    """
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def add_class(value, arg):
    """
    Add a CSS class to a form field
    Usage: {{ form.field|add_class:"form-control" }}
    """
    return value.as_widget(attrs={'class': arg})

@register.filter
def divide(value, arg):
    """
    Divide two numbers
    Usage: {{ value|divide:2 }}
    """
    try:
        if float(arg) == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def percentage(value, total):
    """
    Calculate percentage
    Usage: {{ value|percentage:total }}
    """
    try:
        if float(total) == 0:
            return 0
        return (float(value) / float(total)) * 100
    except (ValueError, TypeError):
        return 0

@register.filter
def format_date(value, format_string="%d %b %Y"):
    """
    Format a date object
    Usage: {{ date|format_date:"%Y-%m-%d" }}
    """
    if not value:
        return ''
    try:
        return value.strftime(format_string)
    except AttributeError:
        return value

@register.filter
def format_datetime(value, format_string="%d %b %Y %H:%M"):
    """
    Format a datetime object
    Usage: {{ datetime|format_datetime:"%Y-%m-%d %H:%M" }}
    """
    if not value:
        return ''
    try:
        return value.strftime(format_string)
    except AttributeError:
        return value

@register.filter
def truncate_chars(value, max_length):
    """
    Truncate a string to a certain number of characters
    Usage: {{ text|truncate_chars:50 }}
    """
    if not value:
        return ''
    try:
        max_length = int(max_length)
        if len(value) <= max_length:
            return value
        return value[:max_length] + '...'
    except (ValueError, TypeError):
        return value

@register.filter
def highlight_text(text, query):
    """
    Highlight matching text in a string
    Usage: {{ text|highlight_text:query }}
    """
    if not text or not query:
        return text
    try:
        query_escaped = re.escape(query)
        pattern = re.compile(f'({query_escaped})', re.IGNORECASE)
        highlighted = pattern.sub(r'<mark>\1</mark>', text)
        return mark_safe(highlighted)
    except:
        return text

@register.filter
def get_full_name_parts(value):
    """
    Split a full name into parts
    Usage: {{ full_name|get_full_name_parts }}
    """
    if not value:
        return {'first_name': '', 'last_name': '', 'middle_name': ''}
    parts = value.strip().split()
    if len(parts) == 1:
        return {'first_name': parts[0], 'last_name': '', 'middle_name': ''}
    elif len(parts) == 2:
        return {'first_name': parts[0], 'last_name': parts[1], 'middle_name': ''}
    else:
        return {'first_name': parts[0], 'middle_name': ' '.join(parts[1:-1]), 'last_name': parts[-1]}

@register.filter
def default_if_none(value, default=""):
    """
    Return default if value is None
    Usage: {{ value|default_if_none:"N/A" }}
    """
    if value is None:
        return default
    return value

@register.filter
def to_class_name(value):
    """
    Get the class name of an object
    Usage: {{ object|to_class_name }}
    """
    if not value:
        return ''
    return value.__class__.__name__

@register.filter
def get_attr(obj, attr_name):
    """
    Get an attribute from an object
    Usage: {{ obj|get_attr:"field_name" }}
    """
    if not obj:
        return None
    try:
        return getattr(obj, attr_name, None)
    except AttributeError:
        return None

@register.filter
def list_join(value, delimiter=", "):
    """
    Join a list with a delimiter
    Usage: {{ list|list_join:", " }}
    """
    if not value:
        return ''
    try:
        return delimiter.join(str(item) for item in value if item)
    except TypeError:
        return value

@register.simple_tag
def active_class(request, url_name):
    """
    Return 'active' if the current URL matches the given URL name
    Usage: {% active_class request 'reporting:exception_bills_report' %}
    """
    from django.urls import resolve
    try:
        current_url_name = resolve(request.path_info).url_name
        if current_url_name == url_name:
            return 'active'
    except:
        pass
    return ''
