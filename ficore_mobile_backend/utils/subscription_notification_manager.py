"""
Subscription Notification Manager

Manages notifications for subscription events.
"""

from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class SubscriptionNotificationManager:
    """
    Manages subscription-related notifications
    """
    
    def __init__(self, mongo):
        self.mongo = mongo
    
    def send_expiration_warning(self, user_id, subscription_id, days_remaining):
        """
        Send expiration warning notification
        
        Args:
            user_id: User ObjectId
            subscription_id: Subscription ObjectId
            days_remaining: Number of days until expiration
            
        Returns:
            bool: True if notification sent successfully
        """
        try:
            from utils.messaging_service import create_user_notification
            
            message = f"Your subscription expires in {days_remaining} days. Renew now to continue enjoying premium features."
            
            return create_user_notification(
                mongo=self.mongo,
                user_id=user_id,
                title="Subscription Expiring Soon",
                message=message,
                notification_type="subscription_warning"
            )
            
        except Exception as e:
            logger.error(f"Error sending expiration warning: {str(e)}")
            return False
    
    def send_expiration_notice(self, user_id, subscription_id):
        """
        Send subscription expired notification
        
        Args:
            user_id: User ObjectId
            subscription_id: Subscription ObjectId
            
        Returns:
            bool: True if notification sent successfully
        """
        try:
            from utils.messaging_service import create_user_notification
            
            message = "Your subscription has expired. Renew now to restore premium features."
            
            return create_user_notification(
                mongo=self.mongo,
                user_id=user_id,
                title="Subscription Expired",
                message=message,
                notification_type="subscription_expired"
            )
            
        except Exception as e:
            logger.error(f"Error sending expiration notice: {str(e)}")
            return False
    
    def send_renewal_confirmation(self, user_id, subscription_id, new_expiry_date):
        """
        Send subscription renewal confirmation
        
        Args:
            user_id: User ObjectId
            subscription_id: Subscription ObjectId
            new_expiry_date: New expiration date
            
        Returns:
            bool: True if notification sent successfully
        """
        try:
            from utils.messaging_service import create_user_notification
            
            message = f"Your subscription has been renewed until {new_expiry_date.strftime('%B %d, %Y')}. Thank you!"
            
            return create_user_notification(
                mongo=self.mongo,
                user_id=user_id,
                title="Subscription Renewed",
                message=message,
                notification_type="subscription_renewed"
            )
            
        except Exception as e:
            logger.error(f"Error sending renewal confirmation: {str(e)}")
            return False
