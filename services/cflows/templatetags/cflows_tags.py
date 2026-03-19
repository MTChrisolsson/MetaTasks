from django import template

register = template.Library()

@register.filter
def can_user_execute(transition, args):
    """
    Check if a user can execute a transition
    Usage: {{ transition|can_user_execute:user_profile:work_item }}
    """
    if not hasattr(transition, 'can_user_execute'):
        return True
        
    try:
        # Parse arguments - expecting "user_profile:work_item"
        parts = str(args).split(':')
        user_profile = parts[0] if len(parts) > 0 else None
        work_item = parts[1] if len(parts) > 1 else None
        
        return transition.can_user_execute(user_profile, work_item)
    except (AttributeError, TypeError, ValueError):
        return True

@register.simple_tag
def check_transition_permission(transition, user_profile, work_item=None):
    """Template tag to check transition permissions"""
    if hasattr(transition, 'can_user_execute'):
        return transition.can_user_execute(user_profile, work_item)
    return True

@register.simple_tag
def has_transition(transitions, from_step, to_step):
    """Check if a transition exists between two steps"""
    for transition in transitions:
        if (transition.from_step_id == from_step.id and 
            transition.to_step_id == to_step.id):
            return True
    return False

@register.simple_tag  
def get_transition(transitions, from_step, to_step):
    """Get the transition between two steps if it exists"""
    for transition in transitions:
        if (transition.from_step_id == from_step.id and 
            transition.to_step_id == to_step.id):
            return transition
    return None
