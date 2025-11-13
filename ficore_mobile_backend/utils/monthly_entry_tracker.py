"""
Monthly Entry Tracker for Free Tier Implementation
Tracks Income & Expense entries per user per month for the 100 free entries policy
"""

from datetime import datetime, timedelta
from bson import ObjectId
from typing import Dict, Any, Optional
import calendar


class MonthlyEntryTracker:
    """
    Manages monthly entry counting for the free tier (100 Income & Expense entries per month)
    """
    
    def __init__(self, mongo):
        self.mongo = mongo
    
    def get_current_month_key(self) -> str:
        """Get current month key in format YYYY-MM"""
        now = datetime.utcnow()
        return f"{now.year}-{now.month:02d}"
    
    def get_user_monthly_count(self, user_id: ObjectId) -> Dict[str, Any]:
        """
        Get user's current monthly Income & Expense entry count
        Returns: {
            'count': int,
            'month_key': str,
            'limit': int,
            'remaining': int,
            'is_over_limit': bool
        }
        """
        month_key = self.get_current_month_key()
        
        # Check if user is Premium subscriber FIRST
        user = self.mongo.db.users.find_one({'_id': user_id})
        is_premium = False
        if user:
            is_subscribed = user.get('isSubscribed', False)
            subscription_end = user.get('subscriptionEndDate')
            if is_subscribed and subscription_end and subscription_end > datetime.utcnow():
                is_premium = True
        
        # Count Income entries for current month
        income_count = self.mongo.db.incomes.count_documents({
            'userId': user_id,
            'createdAt': {
                '$gte': self._get_month_start(),
                '$lt': self._get_month_end()
            }
        })
        
        # Count Expense entries for current month
        expense_count = self.mongo.db.expenses.count_documents({
            'userId': user_id,
            'createdAt': {
                '$gte': self._get_month_start(),
                '$lt': self._get_month_end()
            }
        })
        
        total_count = income_count + expense_count
        
        # CRITICAL FIX: Premium users get unlimited entries
        if is_premium:
            limit = 999999  # Unlimited for Premium users
            remaining = 999999  # Always unlimited remaining
            is_over_limit = False  # Premium users never over limit
        else:
            limit = 100  # Free tier limit
            remaining = max(0, limit - total_count)
            is_over_limit = total_count >= limit
        
        return {
            'count': total_count,
            'income_count': income_count,
            'expense_count': expense_count,
            'month_key': month_key,
            'limit': limit,
            'remaining': remaining,
            'is_over_limit': is_over_limit
        }
    
    def check_entry_allowed(self, user_id: ObjectId, entry_type: str) -> Dict[str, Any]:
        """
        Check if user can create a new Income or Expense entry
        
        Args:
            user_id: User's ObjectId
            entry_type: 'income' or 'expense'
            
        Returns: {
            'allowed': bool,
            'reason': str,
            'monthly_data': dict
        }
        """
        # First check if user has active subscription
        user = self.mongo.db.users.find_one({'_id': user_id})
        if not user:
            return {
                'allowed': False,
                'reason': 'User not found',
                'monthly_data': {}
            }
        
        # Premium users have unlimited entries
        is_subscribed = user.get('isSubscribed', False)
        subscription_end = user.get('subscriptionEndDate')
        
        if is_subscribed and subscription_end and subscription_end > datetime.utcnow():
            return {
                'allowed': True,
                'reason': 'Premium subscription active - unlimited entries',
                'monthly_data': self.get_user_monthly_count(user_id)
            }
        
        # Check monthly limit for free tier users
        monthly_data = self.get_user_monthly_count(user_id)
        
        if monthly_data['is_over_limit']:
            return {
                'allowed': False,
                'reason': f'Monthly limit reached ({monthly_data["limit"]} entries). Upgrade to Premium for unlimited entries or wait until next month.',
                'monthly_data': monthly_data
            }
        
        return {
            'allowed': True,
            'reason': f'Entry allowed. {monthly_data["remaining"]} entries remaining this month.',
            'monthly_data': monthly_data
        }
    
    def should_deduct_fc(self, user_id: ObjectId, entry_type: str) -> Dict[str, Any]:
        """
        Determine if FC should be deducted for this entry
        
        Returns: {
            'deduct_fc': bool,
            'reason': str,
            'fc_cost': float,
            'monthly_data': dict
        }
        """
        # CRITICAL FIX: Check Premium status FIRST - Premium users NEVER pay FC for entries
        user = self.mongo.db.users.find_one({'_id': user_id})
        if user:
            is_subscribed = user.get('isSubscribed', False)
            subscription_end = user.get('subscriptionEndDate')
            if is_subscribed and subscription_end and subscription_end > datetime.utcnow():
                # Premium users: FC balance is NEVER touched
                return {
                    'deduct_fc': False,
                    'reason': 'Premium subscription active - FC balance preserved',
                    'fc_cost': 0.0,
                    'monthly_data': self.get_user_monthly_count(user_id)
                }
        
        # Check entry allowance for Free users only
        entry_check = self.check_entry_allowed(user_id, entry_type)
        
        if not entry_check['allowed']:
            # If entry not allowed due to limit, user needs to pay FC or upgrade
            if 'Monthly limit reached' in entry_check['reason']:
                return {
                    'deduct_fc': True,
                    'reason': 'Monthly free limit exceeded - FC required',
                    'fc_cost': 1.0,  # 1 FC per entry over limit
                    'monthly_data': entry_check['monthly_data']
                }
            else:
                # Other reasons (user not found, etc.)
                return {
                    'deduct_fc': False,
                    'reason': entry_check['reason'],
                    'fc_cost': 0.0,
                    'monthly_data': entry_check['monthly_data']
                }
        
        # Entry is within free limit
        return {
            'deduct_fc': False,
            'reason': 'Within monthly free limit',
            'fc_cost': 0.0,
            'monthly_data': entry_check['monthly_data']
        }
    
    def _get_month_start(self) -> datetime:
        """Get start of current month"""
        now = datetime.utcnow()
        return datetime(now.year, now.month, 1)
    
    def _get_month_end(self) -> datetime:
        """Get start of next month (end of current month)"""
        now = datetime.utcnow()
        if now.month == 12:
            return datetime(now.year + 1, 1, 1)
        else:
            return datetime(now.year, now.month + 1, 1)
    
    def get_monthly_stats(self, user_id: ObjectId) -> Dict[str, Any]:
        """
        Get comprehensive monthly statistics for user
        """
        monthly_data = self.get_user_monthly_count(user_id)
        
        # Get user subscription status
        user = self.mongo.db.users.find_one({'_id': user_id})
        is_subscribed = False
        subscription_type = None
        
        if user:
            is_subscribed = user.get('isSubscribed', False)
            subscription_end = user.get('subscriptionEndDate')
            if is_subscribed and subscription_end and subscription_end > datetime.utcnow():
                subscription_type = user.get('subscriptionType')
            else:
                is_subscribed = False
        
        # CRITICAL FIX: Premium users don't have monthly reset dates
        result = {
            **monthly_data,
            'is_subscribed': is_subscribed,
            'subscription_type': subscription_type,
            'tier': 'Premium' if is_subscribed else 'Free'
        }
        
        # Only add reset date for Free users (Premium users don't have monthly resets)
        if not is_subscribed:
            result['next_reset_date'] = self._get_month_end().isoformat() + 'Z'
        else:
            result['next_reset_date'] = None  # No resets for Premium users
        
        return result