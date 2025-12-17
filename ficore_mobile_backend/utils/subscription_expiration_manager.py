"""
Subscription Expiration Manager
Handles automated expiration processing, historical tracking, and notifications
"""

from datetime import datetime, timedelta
from bson import ObjectId
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class SubscriptionExpirationManager:
    """
    Manages subscription expiration lifecycle including:
    - Automated expiration detection and processing
    - Historical tracking of subscription periods
    - Event logging and audit trails
    - FC balance preservation verification
    """
    
    def __init__(self, mongo_db):
        self.db = mongo_db
        
    def process_expired_subscriptions(self) -> Dict[str, Any]:
        """
        Main scheduled job to process all expired subscriptions.
        Should be run daily (recommended: 2 AM UTC).
        
        Returns:
            Dict with processing statistics
        """
        logger.info("Starting automated subscription expiration processing...")
        
        stats = {
            'total_checked': 0,
            'expired_count': 0,
            'errors': [],
            'processed_users': [],
            'timestamp': datetime.utcnow()
        }
        
        try:
            # Find all users with expired subscriptions (beyond 24-hour grace period)
            grace_period_cutoff = datetime.utcnow() - timedelta(hours=24)
            
            expired_users = self.db.users.find({
                'isSubscribed': True,
                'subscriptionEndDate': {'$lt': grace_period_cutoff}
            })
            
            stats['total_checked'] = self.db.users.count_documents({
                'isSubscribed': True,
                'subscriptionEndDate': {'$exists': True}
            })
            
            for user in expired_users:
                try:
                    self._process_single_expiration(user)
                    stats['expired_count'] += 1
                    stats['processed_users'].append({
                        'user_id': str(user['_id']),
                        'email': user.get('email'),
                        'expired_at': datetime.utcnow().isoformat()
                    })
                except Exception as e:
                    error_msg = f"Error processing user {user['_id']}: {str(e)}"
                    logger.error(error_msg)
                    stats['errors'].append(error_msg)
            
            logger.info(f"Expiration processing complete. Expired: {stats['expired_count']}, Errors: {len(stats['errors'])}")
            
        except Exception as e:
            logger.error(f"Critical error in expiration processing: {str(e)}")
            stats['errors'].append(f"Critical error: {str(e)}")
        
        return stats
    
    def _process_single_expiration(self, user: Dict[str, Any]) -> None:
        """
        Process expiration for a single user.
        
        Steps:
        1. Verify FC balance before changes
        2. Move current subscription to history
        3. Clear active subscription fields
        4. Update isSubscribed to False
        5. Create expiration event
        6. Verify FC balance after changes
        7. Send expiration notification
        """
        user_id = user['_id']
        
        # Step 1: Capture FC balance before changes
        fc_balance_before = user.get('ficoreCreditBalance', 0.0)
        
        # Step 2: Create historical subscription record
        subscription_history_entry = {
            'planType': user.get('subscriptionType'),
            'startDate': user.get('subscriptionStartDate'),
            'endDate': user.get('subscriptionEndDate'),
            'autoRenew': user.get('subscriptionAutoRenew', False),
            'status': 'expired',
            'terminatedAt': datetime.utcnow(),
            'terminationReason': 'natural_expiry',
            'totalDaysActive': self._calculate_days_active(
                user.get('subscriptionStartDate'),
                user.get('subscriptionEndDate')
            ),
            'paymentMethod': user.get('paymentMethodDetails', {}).get('brand', 'unknown')
        }
        
        # Step 3 & 4: Update user document
        # CRITICAL: Clear ALL active subscription fields to prevent stale data
        # These fields are moved to subscriptionHistory for historical tracking
        update_result = self.db.users.update_one(
            {'_id': user_id},
            {
                '$set': {
                    # Clear subscription status
                    'isSubscribed': False,
                    
                    # Clear ALL active subscription fields (set to None)
                    'subscriptionType': None,
                    'subscriptionStartDate': None,
                    'subscriptionEndDate': None,
                    'subscriptionAutoRenew': False,
                    'paymentMethodDetails': None,
                    
                    # Set historical tracking flags
                    'wasPremium': True,
                    'lastPremiumDate': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                },
                '$push': {
                    # Move subscription details to history array
                    'subscriptionHistory': subscription_history_entry
                },
                '$inc': {
                    # Increment counters
                    'totalPremiumDays': subscription_history_entry['totalDaysActive'],
                    'premiumExpiryCount': 1
                }
            }
        )
        
        if update_result.modified_count == 0:
            raise Exception(f"Failed to update user {user_id}")
        
        # Step 5: Create expiration event
        self._create_expiration_event(user, subscription_history_entry)
        
        # Step 6: Verify FC balance preservation
        updated_user = self.db.users.find_one({'_id': user_id})
        fc_balance_after = updated_user.get('ficoreCreditBalance', 0.0)
        
        if fc_balance_before != fc_balance_after:
            # CRITICAL ERROR: FC balance changed during expiration
            logger.error(
                f"CRITICAL: FC balance changed during expiration! "
                f"User: {user_id}, Before: {fc_balance_before}, After: {fc_balance_after}"
            )
            
            # Auto-correct: Restore original balance
            self.db.users.update_one(
                {'_id': user_id},
                {'$set': {'ficoreCreditBalance': fc_balance_before}}
            )
            
            # Log critical event
            self.db.system_alerts.insert_one({
                'type': 'fc_balance_corruption',
                'severity': 'critical',
                'userId': user_id,
                'balanceBefore': fc_balance_before,
                'balanceAfter': fc_balance_after,
                'correctedTo': fc_balance_before,
                'timestamp': datetime.utcnow(),
                'context': 'subscription_expiration'
            })
        
        # Step 7: Create notification record
        self._create_expiration_notification(user)
        
        logger.info(f"Successfully processed expiration for user {user_id}")
    
    def _calculate_days_active(self, start_date: Optional[datetime], end_date: Optional[datetime]) -> int:
        """Calculate total days subscription was active"""
        if not start_date or not end_date:
            return 0
        return max(0, (end_date - start_date).days)
    
    def _create_expiration_event(self, user: Dict[str, Any], history_entry: Dict[str, Any]) -> None:
        """Create subscription_expired event in subscription_events collection"""
        event = {
            '_id': ObjectId(),
            'userId': user['_id'],
            'subscriptionId': None,  # No active subscription ID after expiration
            'eventType': 'subscription_expired',
            'timestamp': datetime.utcnow(),
            'adminId': None,  # System-initiated
            'adminName': 'System (Automated)',
            'reason': 'Subscription end date reached and grace period expired',
            'metadata': {
                'planType': history_entry['planType'],
                'startDate': history_entry['startDate'].isoformat() if history_entry['startDate'] else None,
                'endDate': history_entry['endDate'].isoformat() if history_entry['endDate'] else None,
                'totalDaysActive': history_entry['totalDaysActive'],
                'autoRenew': history_entry['autoRenew'],
                'terminatedAt': history_entry['terminatedAt'].isoformat(),
                'terminationReason': 'natural_expiry',
                'processedBy': 'automated_expiration_manager',
                'gracePeriodEnd': (history_entry['endDate'] + timedelta(hours=24)).isoformat() if history_entry['endDate'] else None
            }
        }
        
        self.db.subscription_events.insert_one(event)
    
    def _create_expiration_notification(self, user: Dict[str, Any]) -> None:
        """Create notification record for expiration"""
        notification = {
            '_id': ObjectId(),
            'userId': user['_id'],
            'type': 'subscription_expired',
            'title': 'Subscription Expired',
            'message': "Your premium subscription has expired. You've been moved to the free tier. Renew anytime to restore premium features.",
            'sentAt': datetime.utcnow(),
            'deliveryStatus': 'pending',  # Will be updated by notification service
            'readAt': None,
            'actionTaken': None,
            'metadata': {
                'subscriptionType': user.get('subscriptionType'),
                'endDate': user.get('subscriptionEndDate').isoformat() if user.get('subscriptionEndDate') else None,
                'canRenew': True,
                'renewalUrl': '/subscription/plans'
            }
        }
        
        self.db.notifications.insert_one(notification)
    
    def check_grace_period_users(self) -> List[Dict[str, Any]]:
        """
        Find users currently in grace period (expired but within 24 hours).
        Useful for sending grace period warnings.
        """
        now = datetime.utcnow()
        grace_period_start = now - timedelta(hours=24)
        
        grace_period_users = list(self.db.users.find({
            'isSubscribed': True,
            'subscriptionEndDate': {
                '$gte': grace_period_start,
                '$lt': now
            }
        }))
        
        return grace_period_users
    
    def get_expiration_statistics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get expiration statistics for the last N days.
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Count expirations in period
        expired_count = self.db.subscription_events.count_documents({
            'eventType': 'subscription_expired',
            'timestamp': {'$gte': cutoff_date}
        })
        
        # Count renewals in period
        renewed_count = self.db.subscription_events.count_documents({
            'eventType': 'subscription_renewed',
            'timestamp': {'$gte': cutoff_date}
        })
        
        # Get users who were premium
        total_was_premium = self.db.users.count_documents({'wasPremium': True})
        
        # Get currently premium
        currently_premium = self.db.users.count_documents({'isSubscribed': True})
        
        # Calculate renewal rate
        renewal_rate = (renewed_count / expired_count * 100) if expired_count > 0 else 0
        
        return {
            'period_days': days,
            'expired_count': expired_count,
            'renewed_count': renewed_count,
            'renewal_rate': round(renewal_rate, 2),
            'total_was_premium': total_was_premium,
            'currently_premium': currently_premium,
            'churn_count': expired_count - renewed_count
        }
