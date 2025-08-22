# myapp/templatetags/custom_filters.py

from django import template
from stats.platforms import get_platform_display_name
from django.template.base import Node, TemplateSyntaxError

register = template.Library()

@register.filter
def get_item(dictionary, key):
    if hasattr(dictionary, 'get'):
        return dictionary.get(key)
    return None

@register.filter
def platform_display(platform):
    return get_platform_display_name(platform)

@register.filter
def multiply(value, arg):
    try:
        return value * arg
    except (ValueError, TypeError):
        return ''

class SetVarNode(Node):
    def __init__(self, var_name, var_value):
        self.var_name = var_name
        self.var_value = var_value

    def render(self, context):
        try:
            value = self.var_value.resolve(context, True)
        except template.VariableDoesNotExist:
            value = ""
        context[self.var_name] = value
        return u""

@register.tag(name='set_var')
def set_var(parser, token):
    """
    {% set_var <var_name> = <var_value> %}
    """
    parts = token.split_contents()
    if len(parts) < 4:
        raise TemplateSyntaxError("'set_var' tag must be of the form: {% set <var_name> = <var_value> %}")
    return SetVarNode(parts[1], parser.compile_filter(parts[3]))