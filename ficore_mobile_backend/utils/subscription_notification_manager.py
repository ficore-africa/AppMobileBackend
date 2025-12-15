"""
Subscription Notification Manager
Handles all subscription-related notifications with multi-stage communication flow
"""

from datetime import datetime, timedelta
from bson import ObjectId
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class SubscriptionNotificationManager:
    """
    Manages subscription notification lifecycle:
    - Pre-expiry warnings (Day -7, -3, -1)
    - Expiry notifications (Day 0)
    - Re-engagement messages (Day +1, +7, +30)
    """
    
    def __init__(self, mongo_db):
        self.db = mongo_db
    
    def send_expiry_warnings(self) -> Dict[str, Any]:
        """
        Send expiry warnings to users whose subscriptions are expiring soon.
        Runs daily at 10 AM UTC.
        """
        logger.info("Sending expiry warnings...")
        
        stats = {
            'day_7_warnings': 0,
            'day_3_warnings': 0,
            'day_1_warnings': 0,
            'errors': []
        }
        
        now = datetime.utcnow()
        
        # Day -7 warnings (expires in 7 days)
        day_7_users = self._get_users_expiring_in_days(7)
        for user in day_7_users:
            try:
                self._send_notification(
                    user=user,
                    notification_type='expiry_warning_7_days',
                    title='Subscription Expiring Soon',
                    message=f'Your premium subscription expires in 7 days. Renew now to continue enjoying premium features.',
                    urgency='medium'
                )
                stats['day_7_warnings'] += 1
            except Exception as e:
                stats['errors'].append(f"User {user['_id']}: {str(e)}")
        
        # Day -3 warnings (expires in 3 days)
        day_3_users = self._get_users_expiring_in_days(3)
        for user in day_3_users:
            try:
                self._send_notification(
                    user=user,
                    notification_type='expiry_warning_3_days',
                    title='Subscription Expiring in 3 Days',
                    message=f'Your premium subscription expires in 3 days. Don\'t lose access to your premium features!',
                    urgency='high'
                )
                stats['day_3_warnings'] += 1
            except Exception as e:
                stats['errors'].append(f"User {user['_id']}: {str(e)}")
        
        # Day -1 warnings (expires tomorrow)
        day_1_users = self._get_users_expiring_in_days(1)
        for user in day_1_users:
            try:
                self._send_notification(
                    user=user,
                    notification_type='expiry_warning_1_day',
                    title='Subscription Expires Tomorrow',
                    message=f'Your premium subscription expires tomorrow. Renew now to avoid interruption.',
                    urgency='critical'
                )
                stats['day_1_warnings'] += 1
            except Exception as e:
                stats['errors'].append(f"User {user['_id']}: {str(e)}")
        
        logger.info(f"Expiry warnings sent: 7-day={stats['day_7_warnings']}, 3-day={stats['day_3_warnings']}, 1-day={stats['day_1_warnings']}")
        return stats
    
    def send_renewal_reminders(self) -> Dict[str, Any]:
        """
        Send renewal reminders based on subscription type.
        - Annual: 30 days before expiry
        - Monthly: 7 days before expiry
        """
        logger.info("Sending renewal reminders...")
        
        stats = {
            'annual_reminders': 0,
            'monthly_reminders': 0,
            'errors': []
        }
        
        # Annual subscription reminders (30 days before)
        annual_users = self._get_users_expiring_in_days(30, subscription_type='annually')
        for user in annual_users:
            try:
                self._send_notification(
                    user=user,
                    notification_type='renewal_reminder_annual',
                    title='Annual Subscription Renewal Reminder',
                    message=f'Your annual subscription renews in 30 days. Manage your subscription settings if needed.',
                    urgency='low'
                )
                stats['annual_reminders'] += 1
            except Exception as e:
                stats['errors'].append(f"User {user['_id']}: {str(e)}")
        
        # Monthly subscription reminders (7 days before)
        monthly_users = self._get_users_expiring_in_days(7, subscription_type='monthly')
        for user in monthly_users:
            try:
                self._send_notification(
                    user=user,
                    notification_type='renewal_reminder_monthly',
                    title='Monthly Subscription Renewal Reminder',
                    message=f'Your monthly subscription renews in 7 days. Manage your subscription settings if needed.',
                    urgency='low'
                )
                stats['monthly_reminders'] += 1
            except Exception as e:
                stats['errors'].append(f"User {user['_id']}: {str(e)}")
        
        logger.info(f"Renewal reminders sent: annual={stats['annual_reminders']}, monthly={stats['monthly_reminders']}")
        return stats
    
    def send_reengagement_messages(self) -> Dict[str, Any]:
        """
        Send re-engagement messages to users whose subscriptions have expired.
        Multi-stage approach: Day +1, +7, +30
        """
        logger.info("Sending re-engagement messages...")
        
        stats = {
            'day_1_messages': 0,
            'day_7_messages': 0,
            'day_30_messages': 0,
            'errors': []
        }
        
        # Day +1: Immediate re-engagement
        day_1_users = self._get_users_expired_days_ago(1)
        for user in day_1_users:
            try:
                self._send_notification(
                    user=user,
                    notification_type='reengagement_day_1',
                    title='We Miss You Already!',
                    message=f'Renew your premium subscription today and get 10% off your next payment.',
                    urgency='medium',
                    include_offer=True,
                    offer_code='COMEBACK10'
                )
                stats['day_1_messages'] += 1
            except Exception as e:
                stats['errors'].append(f"User {user['_id']}: {str(e)}")
        
        # Day +7: Follow-up with special offer
        day_7_users = self._get_users_expired_days_ago(7)
        for user in day_7_users:
            try:
                self._send_notification(
                    user=user,
                    notification_type='reengagement_day_7',
                    title='Special Offer: Come Back to Premium',
                    message=f'We\'ve saved a special 15% discount for you. Renew within the next 7 days!',
                    urgency='medium',
                    include_offer=True,
                    offer_code='WELCOME15'
                )
                stats['day_7_messages'] += 1
            except Exception as e:
                stats['errors'].append(f"User {user['_id']}: {str(e)}")
        
        # Day +30: Last chance offer
        day_30_users = self._get_users_expired_days_ago(30)
        for user in day_30_users:
            try:
                self._send_notification(
                    user=user,
                    notification_type='reengagement_day_30',
                    title='Last Chance: Renew at Your Old Rate',
                    message=f'This is your last chance to renew at your previous rate. After today, prices may increase.',
                    urgency='high',
                    include_offer=True,
                    offer_code='LASTCHANCE20'
                )
                stats['day_30_messages'] += 1
            except Exception as e:
                stats['errors'].append(f"User {user['_id']}: {str(e)}")
        
        logger.info(f"Re-engagement messages sent: day+1={stats['day_1_messages']}, day+7={stats['day_7_messages']}, day+30={stats['day_30_messages']}")
        return stats
    
    def _get_users_expiring_in_days(self, days: int, subscription_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get users whose subscription expires in exactly N days"""
        target_date = datetime.utcnow() + timedelta(days=days)
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        query = {
            'isSubscribed': True,
            'subscriptionEndDate': {
                '$gte': start_of_day,
                '$lte': end_of_day
            }
        }
        
        if subscription_type:
            query['subscriptionType'] = subscription_type
        
        return list(self.db.users.find(query))
    
    def _get_users_expired_days_ago(self, days: int) -> List[Dict[str, Any]]:
        """Get users whose subscription expired exactly N days ago"""
        target_date = datetime.utcnow() - timedelta(days=days)
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Check if notification was already sent for this stage
        return list(self.db.users.find({
            'wasPremium': True,
            'isSubscribed': False,
            'lastPremiumDate': {
                '$gte': start_of_day,
                '$lte': end_of_day
            }
        }))
    
    def _send_notification(
        self,
        user: Dict[str, Any],
        notification_type: str,
        title: str,
        message: str,
        urgency: str = 'medium',
        include_offer: bool = False,
        offer_code: Optional[str] = None
    ) -> None:
        """
        Send notification and log to notifications collection.
        """
        # Check if notification already sent today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        existing = self.db.notifications.find_one({
            'userId': user['_id'],
            'type': notification_type,
            'sentAt': {'$gte': today_start}
        })
        
        if existing:
            logger.debug(f"Notification {notification_type} already sent to user {user['_id']} today")
            return
        
        # Create notification record
        notification = {
            '_id': ObjectId(),
            'userId': user['_id'],
            'type': notification_type,
            'title': title,
            'message': message,
            'sentAt': datetime.utcnow(),
            'deliveryStatus': 'sent',  # Assume successful for now
            'readAt': None,
            'actionTaken': None,
            'urgency': urgency,
            'metadata': {
                'subscriptionType': user.get('subscriptionType'),
                'endDate': user.get('subscriptionEndDate').isoformat() if user.get('subscriptionEndDate') else None,
                'canRenew': True,
                'renewalUrl': '/subscription/plans',
                'includeOffer': include_offer,
                'offerCode': offer_code
            }
        }
        
        self.db.notifications.insert_one(notification)
        
        # TODO: Integrate with actual notification service (push, email, SMS)
        # For now, just log
        logger.info(f"Notification sent: {notification_type} to user {user['_id']}")
