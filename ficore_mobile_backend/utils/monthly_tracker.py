"""
Monthly Entry Tracker

Tracks monthly financial entries and provides analytics.
"""

from datetime import datetime, timedelta
from .decimal_helpers import safe_float, safe_sum
import logging

logger = logging.getLogger(__name__)

class MonthlyEntryTracker:
    """
    Tracks and analyzes monthly financial entries
    """
    
    def __init__(self, mongo):
        self.mongo = mongo
    
    def get_monthly_summary(self, user_id, year, month):
        """
        Get monthly summary for a user
        
        Args:
            user_id: User ObjectId
            year: Year (int)
            month: Month (int, 1-12)
            
        Returns:
            dict: Monthly summary data
        """
        try:
            from bson import ObjectId
            
            if isinstance(user_id, str):
                user_id = ObjectId(user_id)
            
            # Create date range for the month
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
            
            # Query for the month
            date_query = {
                'userId': user_id,
                'date': {'$gte': start_date, '$lt': end_date},
                'status': 'active',
                'isDeleted': False
            }
            
            # Get incomes
            incomes = list(self.mongo.db.incomes.find(date_query))
            total_income = safe_sum([safe_float(inc.get('amount', 0)) for inc in incomes])
            
            # Get expenses
            expenses = list(self.mongo.db.expenses.find(date_query))
            total_expenses = safe_sum([safe_float(exp.get('amount', 0)) for exp in expenses])
            
            # Calculate net profit
            net_profit = total_income - total_expenses
            
            return {
                'year': year,
                'month': month,
                'total_income': total_income,
                'total_expenses': total_expenses,
                'net_profit': net_profit,
                'income_count': len(incomes),
                'expense_count': len(expenses),
                'income_entries': incomes,
                'expense_entries': expenses
            }
            
        except Exception as e:
            logger.error(f"Error getting monthly summary: {str(e)}")
            return {'error': str(e)}
    
    def get_monthly_trends(self, user_id, months_back=6):
        """
        Get monthly trends for specified months
        
        Args:
            user_id: User ObjectId
            months_back: Number of months to analyze
            
        Returns:
            list: Monthly trend data
        """
        try:
            trends = []
            now = datetime.utcnow()
            
            for i in range(months_back):
                # Calculate month/year for each period
                target_date = now - timedelta(days=i * 30)
                year = target_date.year
                month = target_date.month
                
                monthly_data = self.get_monthly_summary(user_id, year, month)
                trends.append(monthly_data)
            
            return trends
            
        except Exception as e:
            logger.error(f"Error getting monthly trends: {str(e)}")
            return []
    
    def track_entry(self, user_id, entry_type, amount, category):
        """
        Track a new entry for monthly analytics
        
        Args:
            user_id: User ObjectId
            entry_type: 'income' or 'expense'
            amount: Entry amount
            category: Entry category
            
        Returns:
            bool: True if tracked successfully
        """
        try:
            # This could be used for real-time tracking
            # For now, just log the entry
            logger.info(f"Monthly tracker: {entry_type} of ₦{amount} in {category} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error tracking entry: {str(e)}")
            return False
