"""
Notification Utilities

Critical notification functions.
"""

import logging
from datetime import datetime
from bson import ObjectId

logger = logging.getLogger(__name__)

def create_user_notification(mongo, user_id, title, message, notification_type="info"):
    """
    Create user notification
    
    Args:
        mongo: MongoDB connection
        user_id: User ObjectId
        title: Notification title
        message: Notification message
        notification_type: Type of notification
        
    Returns:
        bool: True if created successfully
    """
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        notification = {
            '_id': ObjectId(),
            'userId': user_id,
            'title': title,
            'message': message,
            'type': notification_type,
            'read': False,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.notifications.insert_one(notification)
        logger.info(f"Notification created for user {user_id}: {title}")
        return True
        
    except Exception as e:
        logger.error(f"Error creating notification: {str(e)}")
        return False

def get_notification_context(mongo, user_id, context_type="general"):
    """
    Get notification context for user
    
    Args:
        mongo: MongoDB connection
        user_id: User ObjectId
        context_type: Type of context needed
        
    Returns:
        dict: Notification context
    """
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        user = mongo.db.users.find_one({'_id': user_id})
        if not user:
            return {}
        
        return {
            'user_name': user.get('name', 'User'),
            'user_email': user.get('email', ''),
            'context_type': context_type
        }
        
    except Exception as e:
        logger.error(f"Error getting notification context: {str(e)}")
        return {}
