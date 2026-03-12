"""
Subscription Expiration Manager

Manages subscription expiration logic and notifications.
"""

from datetime import datetime, timedelta
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class SubscriptionExpirationManager:
    """
    Manages subscription expiration and renewal logic
    """
    
    def __init__(self, mongo):
        self.mongo = mongo
    
    def check_expired_subscriptions(self):
        """
        Check for expired subscriptions
        
        Returns:
            list: List of expired subscription IDs
        """
        try:
            now = datetime.utcnow()
            
            expired_subscriptions = list(self.mongo.db.subscriptions.find({
                'expiresAt': {'$lt': now},
                'status': 'active'
            }))
            
            return [sub['_id'] for sub in expired_subscriptions]
            
        except Exception as e:
            logger.error(f"Error checking expired subscriptions: {str(e)}")
            return []
    
    def expire_subscription(self, subscription_id):
        """
        Mark a subscription as expired
        
        Args:
            subscription_id: ObjectId of subscription to expire
            
        Returns:
            bool: True if expired successfully
        """
        try:
            result = self.mongo.db.subscriptions.update_one(
                {'_id': ObjectId(subscription_id)},
                {
                    '$set': {
                        'status': 'expired',
                        'expiredAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error expiring subscription {subscription_id}: {str(e)}")
            return False
    
    def get_expiring_soon(self, days_ahead=7):
        """
        Get subscriptions expiring within specified days
        
        Args:
            days_ahead: Number of days to look ahead
            
        Returns:
            list: List of subscriptions expiring soon
        """
        try:
            future_date = datetime.utcnow() + timedelta(days=days_ahead)
            
            expiring_soon = list(self.mongo.db.subscriptions.find({
                'expiresAt': {
                    '$gte': datetime.utcnow(),
                    '$lte': future_date
                },
                'status': 'active'
            }))
            
            return expiring_soon
            
        except Exception as e:
            logger.error(f"Error getting expiring subscriptions: {str(e)}")
            return []
