"""
Auto Population Utilities

Utilities for auto-populating form fields based on user history and patterns.
"""

from decimal_helpers import safe_float
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def auto_populate_expense_fields(mongo, user_id, category=None, description=None):
    """
    Auto-populate expense fields based on user history
    
    Args:
        mongo: MongoDB connection
        user_id: User ObjectId
        category: Expense category (optional)
        description: Expense description (optional)
        
    Returns:
        dict: Suggested field values
    """
    try:
        from bson import ObjectId
        
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        # Get recent expenses for patterns
        recent_expenses = list(mongo.db.expenses.find({
            'userId': user_id,
            'status': 'active',
            'isDeleted': False
        }).sort('createdAt', -1).limit(50))
        
        suggestions = {}
        
        # If category is provided, find common amounts for that category
        if category:
            category_expenses = [exp for exp in recent_expenses if exp.get('category') == category]
            if category_expenses:
                amounts = [safe_float(exp.get('amount', 0)) for exp in category_expenses]
                # Suggest most common amount
                if amounts:
                    suggestions['suggested_amount'] = max(set(amounts), key=amounts.count)
        
        # If description is provided, find similar descriptions
        if description:
            similar_expenses = [exp for exp in recent_expenses 
                             if description.lower() in exp.get('description', '').lower()]
            if similar_expenses:
                suggestions['similar_entries'] = len(similar_expenses)
                suggestions['last_similar_amount'] = safe_float(similar_expenses[0].get('amount', 0))
        
        # Common categories for this user
        categories = [exp.get('category') for exp in recent_expenses if exp.get('category')]
        if categories:
            category_counts = {}
            for cat in categories:
                category_counts[cat] = category_counts.get(cat, 0) + 1
            
            suggestions['common_categories'] = sorted(category_counts.items(), 
                                                    key=lambda x: x[1], reverse=True)[:5]
        
        # Common payment methods
        payment_methods = [exp.get('paymentMethod') for exp in recent_expenses if exp.get('paymentMethod')]
        if payment_methods:
            suggestions['common_payment_method'] = max(set(payment_methods), key=payment_methods.count)
        
        return suggestions
        
    except Exception as e:
        logger.error(f"Error auto-populating expense fields: {str(e)}")
        return {}

def auto_populate_income_fields(mongo, user_id, category=None, description=None):
    """
    Auto-populate income fields based on user history
    
    Args:
        mongo: MongoDB connection
        user_id: User ObjectId
        category: Income category (optional)
        description: Income description (optional)
        
    Returns:
        dict: Suggested field values
    """
    try:
        from bson import ObjectId
        
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        # Get recent incomes for patterns
        recent_incomes = list(mongo.db.incomes.find({
            'userId': user_id,
            'status': 'active',
            'isDeleted': False
        }).sort('createdAt', -1).limit(50))
        
        suggestions = {}
        
        # If category is provided, find common amounts for that category
        if category:
            category_incomes = [inc for inc in recent_incomes if inc.get('category') == category]
            if category_incomes:
                amounts = [safe_float(inc.get('amount', 0)) for inc in category_incomes]
                if amounts:
                    suggestions['suggested_amount'] = max(set(amounts), key=amounts.count)
        
        # If description is provided, find similar descriptions
        if description:
            similar_incomes = [inc for inc in recent_incomes 
                             if description.lower() in inc.get('description', '').lower()]
            if similar_incomes:
                suggestions['similar_entries'] = len(similar_incomes)
                suggestions['last_similar_amount'] = safe_float(similar_incomes[0].get('amount', 0))
        
        # Common categories for this user
        categories = [inc.get('category') for inc in recent_incomes if inc.get('category')]
        if categories:
            category_counts = {}
            for cat in categories:
                category_counts[cat] = category_counts.get(cat, 0) + 1
            
            suggestions['common_categories'] = sorted(category_counts.items(), 
                                                    key=lambda x: x[1], reverse=True)[:5]
        
        # Common sales types
        sales_types = [inc.get('salesType') for inc in recent_incomes if inc.get('salesType')]
        if sales_types:
            suggestions['common_sales_type'] = max(set(sales_types), key=sales_types.count)
        
        return suggestions
        
    except Exception as e:
        logger.error(f"Error auto-populating income fields: {str(e)}")
        return {}

def get_notification_context(mongo, user_id, notification_type):
    """
    Get context for notifications based on user data
    
    Args:
        mongo: MongoDB connection
        user_id: User ObjectId
        notification_type: Type of notification
        
    Returns:
        dict: Notification context data
    """
    try:
        from bson import ObjectId
        
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        # Get user data
        user = mongo.db.users.find_one({'_id': user_id})
        if not user:
            return {}
        
        context = {
            'user_name': user.get('name', 'User'),
            'user_email': user.get('email', ''),
            'notification_type': notification_type
        }
        
        # Add type-specific context
        if notification_type == 'monthly_summary':
            # Get current month summary
            now = datetime.utcnow()
            from .monthly_tracker import MonthlyEntryTracker
            tracker = MonthlyEntryTracker(mongo)
            monthly_data = tracker.get_monthly_summary(user_id, now.year, now.month)
            context['monthly_data'] = monthly_data
        
        elif notification_type == 'expense_reminder':
            # Get recent expense patterns
            recent_expenses = list(mongo.db.expenses.find({
                'userId': user_id,
                'status': 'active',
                'isDeleted': False
            }).sort('createdAt', -1).limit(10))
            
            context['recent_expense_count'] = len(recent_expenses)
            if recent_expenses:
                context['last_expense_date'] = recent_expenses[0].get('createdAt')
        
        return context
        
    except Exception as e:
        logger.error(f"Error getting notification context: {str(e)}")
        return {}
