"""
Subscription Scheduler

Handles scheduled subscription tasks and automation.
"""

from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class SubscriptionScheduler:
    """
    Handles scheduled subscription operations
    """
    
    def __init__(self, mongo):
        self.mongo = mongo
    
    def run_daily_tasks(self):
        """
        Run daily subscription maintenance tasks
        
        Returns:
            dict: Summary of tasks performed
        """
        try:
            from utils.subscription_expiration_manager import SubscriptionExpirationManager
            from utils.subscription_notification_manager import SubscriptionNotificationManager
            
            expiration_manager = SubscriptionExpirationManager(self.mongo)
            notification_manager = SubscriptionNotificationManager(self.mongo)
            
            # Check for expired subscriptions
            expired_ids = expiration_manager.check_expired_subscriptions()
            expired_count = 0
            
            for subscription_id in expired_ids:
                if expiration_manager.expire_subscription(subscription_id):
                    expired_count += 1
                    
                    # Get user ID for notification
                    subscription = self.mongo.db.subscriptions.find_one({'_id': subscription_id})
                    if subscription:
                        notification_manager.send_expiration_notice(
                            subscription['userId'], 
                            subscription_id
                        )
            
            # Send expiration warnings (7 days ahead)
            expiring_soon = expiration_manager.get_expiring_soon(days_ahead=7)
            warnings_sent = 0
            
            for subscription in expiring_soon:
                days_remaining = (subscription['expiresAt'] - datetime.utcnow()).days
                if notification_manager.send_expiration_warning(
                    subscription['userId'], 
                    subscription['_id'], 
                    days_remaining
                ):
                    warnings_sent += 1
            
            return {
                'expired_subscriptions': expired_count,
                'expiration_warnings_sent': warnings_sent,
                'task_completed_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error running daily subscription tasks: {str(e)}")
            return {'error': str(e)}
    
    def schedule_renewal_reminder(self, subscription_id, reminder_date):
        """
        Schedule a renewal reminder
        
        Args:
            subscription_id: Subscription ObjectId
            reminder_date: Date to send reminder
            
        Returns:
            bool: True if scheduled successfully
        """
        try:
            # This would integrate with a task queue in production
            # For now, just log the scheduling
            logger.info(f"Renewal reminder scheduled for subscription {subscription_id} on {reminder_date}")
            return True
            
        except Exception as e:
            logger.error(f"Error scheduling renewal reminder: {str(e)}")
            return False
