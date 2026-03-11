"""
Messaging service for FiCore backend
"""

def create_user_notification(user_id, title, message, notification_type='info'):
    """
    Create a user notification
    
    Args:
        user_id: User ID to notify
        title: Notification title
        message: Notification message
        notification_type: Type of notification
    
    Returns:
        dict: Notification creation result
    """
    print(f"📧 Notification for {user_id}: {title} - {message}")
    return {'success': True, 'notification_id': 'mock_notification_id'}

def get_notification_context(user_id, context_type):
    """
    Get notification context for a user
    
    Args:
        user_id: User ID
        context_type: Type of context needed
    
    Returns:
        dict: Notification context
    """
    return {
        'user_id': user_id,
        'context_type': context_type,
        'preferences': {}
    }
