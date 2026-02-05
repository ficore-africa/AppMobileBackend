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
        
        # Check if user is Admin or Premium subscriber FIRST
        user = self.mongo.db.users.find_one({'_id': user_id})
        is_premium = False
        if user:
            # Admins get unlimited access
            is_admin = user.get('isAdmin', False)
            if is_admin:
                is_premium = True
            else:
                # Check premium subscription
                is_subscribed = user.get('isSubscribed', False)
                subscription_end = user.get('subscriptionEndDate')
                if is_subscribed and subscription_end and subscription_end > datetime.utcnow():
                    is_premium = True
        
        # Count Income entries for current month
        month_start = self._get_month_start()
        month_end = self._get_month_end()
        
        # CRITICAL FIX: Use correct date fields with comprehensive fallback
        # Strategy 1: Try primary date field (dateReceived for income, date for expense)
        income_count = self.mongo.db.incomes.count_documents({
            'userId': user_id,
            'dateReceived': {
                '$gte': month_start,
                '$lt': month_end
            }
        })
        
        expense_count = self.mongo.db.expenses.count_documents({
            'userId': user_id,
            'date': {
                '$gte': month_start,
                '$lt': month_end
            }
        })
        
        # Strategy 2: If count is 0, try with createdAt as fallback
        if income_count == 0:
            income_count = self.mongo.db.incomes.count_documents({
                'userId': user_id,
                'createdAt': {
                    '$gte': month_start,
                    '$lt': month_end
                }
            })
        
        if expense_count == 0:
            expense_count = self.mongo.db.expenses.count_documents({
                'userId': user_id,
                'createdAt': {
                    '$gte': month_start,
                    '$lt': month_end
                }
            })
        
        # Strategy 3: If still 0, try with string userId and primary date field
        if income_count == 0:
            income_count = self.mongo.db.incomes.count_documents({
                'userId': str(user_id),
                'dateReceived': {
                    '$gte': month_start,
                    '$lt': month_end
                }
            })
        
        if expense_count == 0:
            expense_count = self.mongo.db.expenses.count_documents({
                'userId': str(user_id),
                'date': {
                    '$gte': month_start,
                    '$lt': month_end
                }
            })
        
        # Strategy 4: If still 0, try with string userId and createdAt
        if income_count == 0:
            income_count = self.mongo.db.incomes.count_documents({
                'userId': str(user_id),
                'createdAt': {
                    '$gte': month_start,
                    '$lt': month_end
                }
            })
        
        if expense_count == 0:
            expense_count = self.mongo.db.expenses.count_documents({
                'userId': str(user_id),
                'createdAt': {
                    '$gte': month_start,
                    '$lt': month_end
                }
            })
        
        # Strategy 3: If still 0, check if entries exist at all for this user
        if income_count == 0:
            total_income_all_time = self.mongo.db.incomes.count_documents({'userId': user_id})
            if total_income_all_time == 0:
                # Try string userId
                total_income_all_time = self.mongo.db.incomes.count_documents({'userId': str(user_id)})
            
            if total_income_all_time > 0:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"FALLBACK: Found {total_income_all_time} income entries but createdAt query returned 0. Using fallback counting.")
                # Entries exist but createdAt query failed - use comprehensive fallback
                income_count = self._count_by_id_timestamp(self.mongo.db.incomes, user_id, month_start, month_end)
                # print(f"FALLBACK RESULT: Income count after fallback: {income_count}")
        
        if expense_count == 0:
            total_expense_all_time = self.mongo.db.expenses.count_documents({'userId': user_id})
            if total_expense_all_time == 0:
                # Try string userId
                total_expense_all_time = self.mongo.db.expenses.count_documents({'userId': str(user_id)})
            
            if total_expense_all_time > 0:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"FALLBACK: Found {total_expense_all_time} expense entries but createdAt query returned 0. Using fallback counting.")
                # Entries exist but createdAt query failed - use comprehensive fallback
                expense_count = self._count_by_id_timestamp(self.mongo.db.expenses, user_id, month_start, month_end)
                # print(f"FALLBACK RESULT: Expense count after fallback: {expense_count}")
        
        total_count = income_count + expense_count
        
        # Final logging - DISABLED FOR LIQUID WALLET FOCUS
        # print(f"FINAL COUNT: User {user_id} - Income: {income_count}, Expense: {expense_count}, Total: {total_count} for month {month_key}")
        # print(f"DEBUG: is_premium={is_premium}, is_admin={user.get('isAdmin', False) if user else False}")
        
        # CRITICAL FIX: Premium users get unlimited entries
        if is_premium:
            limit = 999999  # Unlimited for Premium users
            remaining = 999999  # Always unlimited remaining
            is_over_limit = False  # Premium users never over limit
        else:
            limit = 20  # REDUCED: Free tier limit reduced from 100 to 20 (Recommendation #3)
            remaining = max(0, limit - total_count)
            is_over_limit = total_count >= limit
        
        # CRITICAL DEBUG: Log the final calculation - DISABLED FOR LIQUID WALLET FOCUS
        # print(f"DEBUG CALCULATION: total_count={total_count}, limit={limit}, remaining={remaining}, is_over_limit={is_over_limit}")
        
        # CRITICAL FIX: Only validate for Free users, Premium users always have unlimited
        if not is_premium:
            # CRITICAL FIX: Ensure remaining is never negative and matches the calculation
            if remaining < 0:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"ERROR: Negative remaining detected! Setting to 0. Original value: {remaining}")
                remaining = 0
            
            # CRITICAL VALIDATION: Double-check the math for Free users only
            expected_remaining = max(0, limit - total_count)
            if remaining != expected_remaining:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"ERROR: Remaining mismatch! Expected: {expected_remaining}, Got: {remaining}. Correcting...")
                remaining = expected_remaining
        
        result = {
            'count': total_count,
            'income_count': income_count,
            'expense_count': expense_count,
            'month_key': month_key,
            'limit': limit,
            'remaining': remaining,
            'is_over_limit': is_over_limit
        }
        
        # DISABLED FOR LIQUID WALLET FOCUS
        # print(f"FINAL RESULT: {result}")
        return result
    
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
        # First check if user exists
        user = self.mongo.db.users.find_one({'_id': user_id})
        if not user:
            return {
                'allowed': False,
                'reason': 'User not found',
                'monthly_data': {}
            }
        
        # Admin users have unlimited entries
        is_admin = user.get('isAdmin', False)
        if is_admin:
            return {
                'allowed': True,
                'reason': 'Admin user - unlimited entries',
                'monthly_data': self.get_user_monthly_count(user_id)
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
                'reason': f'Monthly limit reached ({monthly_data["limit"]} entries). Upgrade to Premium (₦10,000/year) for unlimited entries or purchase FCs.',
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
        # CRITICAL FIX: Check Premium/Admin status FIRST - Premium users and Admins NEVER pay FC for entries
        user = self.mongo.db.users.find_one({'_id': user_id})
        if user:
            # Check if user is admin (admins get unlimited access)
            is_admin = user.get('isAdmin', False)
            if is_admin:
                return {
                    'deduct_fc': False,
                    'reason': 'Admin user - unlimited access',
                    'fc_cost': 0.0,
                    'monthly_data': self.get_user_monthly_count(user_id)
                }
            
            # Check if user is premium subscriber
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
    
    def _count_by_id_timestamp(self, collection, user_id: ObjectId, month_start: datetime, month_end: datetime) -> int:
        """
        Comprehensive fallback method to count entries using multiple strategies:
        1. ObjectId timestamp extraction
        2. Alternative date fields (date, dateReceived, updatedAt)
        3. Both ObjectId and string userId formats
        """
        try:
            # Try with ObjectId userId first
            entries = list(collection.find({'userId': user_id}))
            
            # If no entries found, try with string userId
            if not entries:
                entries = list(collection.find({'userId': str(user_id)}))
            
            # If still no entries, try without userId filter (last resort - check all entries)
            if not entries:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"WARNING: No entries found for user {user_id} in {collection.name}")
                return 0
            
            count = 0
            
            for entry in entries:
                entry_time = None
                
                try:
                    # Strategy 1: Try primary date fields first (dateReceived for income, date for expense)
                    # For income: try 'dateReceived' field
                    if 'dateReceived' in entry and entry['dateReceived']:
                        if isinstance(entry['dateReceived'], datetime):
                            entry_time = entry['dateReceived']
                        elif isinstance(entry['dateReceived'], str):
                            try:
                                entry_time = datetime.fromisoformat(entry['dateReceived'].replace('Z', ''))
                            except:
                                pass
                    
                    # For expenses: try 'date' field
                    if not entry_time and 'date' in entry and entry['date']:
                        if isinstance(entry['date'], datetime):
                            entry_time = entry['date']
                        elif isinstance(entry['date'], str):
                            try:
                                entry_time = datetime.fromisoformat(entry['date'].replace('Z', ''))
                            except:
                                pass
                    
                    # Strategy 2: Try createdAt field as fallback (might be string or datetime)
                    if not entry_time and 'createdAt' in entry and entry['createdAt']:
                        if isinstance(entry['createdAt'], datetime):
                            entry_time = entry['createdAt']
                        elif isinstance(entry['createdAt'], str):
                            # Try parsing ISO format string
                            try:
                                entry_time = datetime.fromisoformat(entry['createdAt'].replace('Z', ''))
                            except:
                                pass
                    
                    # Strategy 3: Extract timestamp from ObjectId (last resort)
                    if not entry_time:
                        entry_time = entry['_id'].generation_time
                    
                    # Normalize timezone (remove timezone info for comparison)
                    if entry_time and entry_time.tzinfo is not None:
                        entry_time = entry_time.replace(tzinfo=None)
                    
                    # Check if entry is in current month
                    if entry_time and month_start <= entry_time < month_end:
                        count += 1
                        
                except Exception as entry_error:
                    # Skip entries with errors but log them - DISABLED FOR LIQUID WALLET FOCUS
                    # print(f"Error processing entry {entry.get('_id')}: {str(entry_error)}")
                    continue
            
            return count
        except Exception as e:
            # DISABLED FOR LIQUID WALLET FOCUS
            # print(f"Error in _count_by_id_timestamp: {str(e)}")
            # import traceback
            # traceback.print_exc()
            return 0
    
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
        
        # Get user subscription and admin status
        user = self.mongo.db.users.find_one({'_id': user_id})
        is_subscribed = False
        is_admin = False
        subscription_type = None
        
        if user:
            # Check admin status
            is_admin = user.get('isAdmin', False)
            
            # Check subscription status
            is_subscribed = user.get('isSubscribed', False)
            subscription_end = user.get('subscriptionEndDate')
            if is_subscribed and subscription_end and subscription_end > datetime.utcnow():
                subscription_type = user.get('subscriptionType')
            else:
                is_subscribed = False
        
        # Determine tier (Admin > Premium > Free)
        if is_admin:
            tier = 'Admin'
        elif is_subscribed:
            tier = 'Premium'
        else:
            tier = 'Free'
        
        # CRITICAL FIX: Premium users and Admins don't have monthly reset dates
        result = {
            **monthly_data,
            'is_subscribed': is_subscribed,
            'is_admin': is_admin,
            'subscription_type': subscription_type,
            'tier': tier
        }
        
        # Only add reset date for Free users (Premium/Admin users don't have monthly resets)
        if not is_subscribed and not is_admin:
            result['next_reset_date'] = self._get_month_end().isoformat() + 'Z'
        else:
            result['next_reset_date'] = None  # No resets for Premium/Admin users
        
        return result