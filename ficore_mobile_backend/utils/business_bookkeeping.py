"""
Business Bookkeeping Automation Utilities
Handles double-entry bookkeeping for FiCore business account
"""

from datetime import datetime
from bson import ObjectId
from typing import Dict, Any, Optional
from flask import current_app
from .decimal_helpers import safe_float

# Business account ID (ficoreafrica@gmail.com)
BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')

# FC Credit rate (₦30 per FC)
FC_RATE = 30.0


def record_fc_marketing_expense(
    mongo,
    user_id: ObjectId,
    fc_amount: float,
    operation: str,
    description: str
) -> Dict[str, ObjectId]:
    """
    Record FC bonus as marketing expense in business books
    Implements double-entry bookkeeping (LIABILITY MODEL):
    - Dr. Marketing Expense (increases expense on P&L)
    - Cr. FC Liability (increases liability on Balance Sheet)
    
    This is the CORRECT accounting treatment because:
    1. We haven't spent cash yet (Capital stays intact)
    2. We've created a promise to provide future service (Liability)
    3. Marketing expense correctly flows to P&L
    4. When user spends FC, we'll Dr. Liability / Cr. Revenue
    
    Args:
        mongo: MongoDB connection
        user_id: Recipient user ID
        fc_amount: Number of FCs awarded
        operation: Operation type (signup_bonus, tax_education_progress, etc.)
        description: Human-readable description
    
    Returns:
        Dict with expense_id and liability_id
    """
    try:
        # Calculate cost (₦30 per FC)
        naira_cost = fc_amount * FC_RATE
        
        # Determine category and sourceType
        category_map = {
            'signup_bonus': ('Marketing Ads and Promotion', 'marketing_expense_signup'),
            'tax_education_progress': ('Marketing Ads and Promotion', 'marketing_expense_tax_education'),
            'exploration_bonus': ('Marketing Ads and Promotion', 'marketing_expense_exploration'),
            'streak_milestone': ('Marketing Ads and Promotion', 'marketing_expense_streak'),
            'engagement_reward': ('Marketing Ads and Promotion', 'marketing_expense_engagement'),
            'admin_award': ('Marketing Ads and Promotion', 'marketing_expense_admin'),
            'marketing_expense_total': ('Marketing Ads and Promotion', 'marketing_expense_total')
        }
        category, source_type = category_map.get(operation, ('Marketing Ads and Promotion', 'marketing_expense_other'))
        
        # 1. Record expense (Debit) - Increases Marketing Expense on P&L
        expense_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': naira_cost,
            'category': category,
            'description': f'{description} ({fc_amount} FCs @ ₦{FC_RATE}/FC)',
            'date': datetime.utcnow(),
            'sourceType': source_type,
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'recipientUserId': str(user_id),
                'fcAmount': fc_amount,
                'fcRate': FC_RATE,
                'operation': operation,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'liability'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(expense_entry)
        
        # 2. Record FC liability (Credit) - Increases Liability on Balance Sheet
        # This represents our obligation to provide future service
        liability_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': naira_cost,  # Positive = liability increase
            'category': 'Deferred Revenue - FC Liability',
            'description': f'FC Liability Accrual - {description}',
            'date': datetime.utcnow(),
            'sourceType': 'fc_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'type': 'LIABILITY_INCREASE',
                'linkedExpenseId': str(expense_entry['_id']),
                'recipientUserId': str(user_id),
                'fcAmount': fc_amount,
                'fcRate': FC_RATE,
                'operation': operation,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'liability'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        # Store in incomes collection with negative amount to represent liability
        # (Alternative: create separate liabilities collection)
        mongo.db.incomes.insert_one(liability_entry)
        
        print(f'✅ Recorded FC marketing expense: {fc_amount} FCs (₦{safe_float(naira_cost):,.2f}) for {operation}')
        print(f'   Dr. Marketing Expense: ₦{safe_float(naira_cost):,.2f}')
        print(f'   Cr. FC Liability: ₦{safe_float(naira_cost):,.2f}')
        
        return {
            'expense_id': expense_entry['_id'],
            'liability_id': liability_entry['_id'],
            'amount': naira_cost
        }
        
    except Exception as e:
        print(f'❌ Error recording FC marketing expense: {str(e)}')
        raise


def record_subscription_marketing_expense(
    mongo,
    user_id: ObjectId,
    subscription_id: ObjectId,
    amount: float,
    plan_type: str,
    granted_by: str,
    grant_reason: str
) -> Dict[str, ObjectId]:
    """
    Record admin-granted subscription as marketing expense
    Implements double-entry bookkeeping (LIABILITY MODEL):
    - Dr. Marketing Expense (increases expense on P&L)
    - Cr. Subscription Liability (increases liability on Balance Sheet)
    
    This is the CORRECT accounting treatment because:
    1. We haven't spent cash yet (Capital stays intact)
    2. We've created a promise to provide future service (Liability)
    3. Marketing expense correctly flows to P&L
    4. When subscription period expires, we'll Dr. Liability / Cr. Revenue
    
    Args:
        mongo: MongoDB connection
        user_id: Recipient user ID
        subscription_id: Subscription document ID
        amount: Subscription value
        plan_type: Plan type (ANNUAL, MONTHLY)
        granted_by: Admin who granted it
        grant_reason: Reason for grant
    
    Returns:
        Dict with expense_id and liability_id
    """
    try:
        # Get user email for description
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # 1. Record expense (Debit) - Increases Marketing Expense on P&L
        expense_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': amount,
            'category': 'Marketing Ads and Promotion',
            'description': f'Admin-granted {plan_type} subscription for {user_email} - {grant_reason}',
            'date': datetime.utcnow(),
            'sourceType': 'marketing_expense_subscription',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'recipientUserId': str(user_id),
                'subscriptionId': str(subscription_id),
                'planType': plan_type,
                'grantedBy': granted_by,
                'grantReason': grant_reason,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'liability'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(expense_entry)
        
        # 2. Record subscription liability (Credit) - Increases Liability on Balance Sheet
        # This represents our obligation to provide future service
        liability_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': amount,  # Positive = liability increase
            'category': 'Deferred Revenue - Subscription Liability',
            'description': f'Subscription Liability Accrual - {plan_type} for {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'subscription_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'type': 'LIABILITY_INCREASE',
                'linkedExpenseId': str(expense_entry['_id']),
                'recipientUserId': str(user_id),
                'subscriptionId': str(subscription_id),
                'planType': plan_type,
                'grantedBy': granted_by,
                'grantReason': grant_reason,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'liability'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        # Store in incomes collection with positive amount to represent liability
        mongo.db.incomes.insert_one(liability_entry)
        
        print(f'✅ Recorded subscription marketing expense: ₦{safe_float(amount):,.2f} for {user_email}')
        print(f'   Dr. Marketing Expense: ₦{safe_float(amount):,.2f}')
        print(f'   Cr. Subscription Liability: ₦{safe_float(amount):,.2f}')
        
        return {
            'expense_id': expense_entry['_id'],
            'liability_id': liability_entry['_id'],
            'amount': amount
        }
        
    except Exception as e:
        print(f'❌ Error recording subscription marketing expense: {str(e)}')
        raise


def record_vas_commission_revenue(
    mongo,
    transaction_id: ObjectId,
    user_id: ObjectId,
    provider: str,
    transaction_type: str,
    amount: float,
    commission: float
) -> ObjectId:
    """
    Record VAS commission as revenue in business books
    Implements single-entry (cash already recorded in provider account)
    - Cr. Revenue (increases income)
    
    Args:
        mongo: MongoDB connection
        transaction_id: VAS transaction ID
        user_id: Customer user ID
        provider: Provider name (monnify, peyflex)
        transaction_type: Transaction type (AIRTIME, DATA, BILL)
        amount: Transaction amount
        commission: Commission earned
    
    Returns:
        ObjectId of created income entry
    """
    try:
        # Get user email for description
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # Calculate commission rate
        commission_rate = (commission / amount * 100) if amount > 0 else 0
        
        # Record revenue
        revenue_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': commission,
            'category': 'Service Revenue',
            'description': f'VAS Commission - {provider.capitalize()} {transaction_type} (₦{safe_float(amount):,.2f} @ {commission_rate:.2f}%)',
            'date': datetime.utcnow(),
            'sourceType': 'vas_commission',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'vasTransactionId': str(transaction_id),
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'provider': provider,
                'transactionType': transaction_type,
                'transactionAmount': amount,
                'commissionRate': commission_rate,
                'automated': True,
                'doubleEntry': False  # Cash already in provider account
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.incomes.insert_one(revenue_entry)
        
        print(f'✅ Recorded VAS commission revenue: ₦{safe_float(commission):,.2f} from {provider} {transaction_type}')
        
        return revenue_entry['_id']
        
    except Exception as e:
        print(f'❌ Error recording VAS commission revenue: {str(e)}')
        raise


def record_fc_consumption_revenue(
    mongo,
    user_id: ObjectId,
    fc_amount: float,
    description: str,
    service: str
) -> Dict[str, ObjectId]:
    """
    Record FC consumption as revenue in business books
    Implements double-entry bookkeeping:
    - Dr. FC Liability (decreases liability)
    - Cr. Revenue (increases income)
    
    Args:
        mongo: MongoDB connection
        user_id: User who spent FCs
        fc_amount: Number of FCs spent
        description: Human-readable description
        service: Service used (report_export, premium_feature, etc.)
    
    Returns:
        Dict with revenue_id and liability_reduction_id
    """
    try:
        # Calculate revenue (₦30 per FC)
        naira_revenue = fc_amount * FC_RATE
        
        # Get user email for description
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # 1. Record revenue (Credit)
        revenue_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': naira_revenue,
            'category': 'Service Revenue',
            'description': f'FC Consumption - {description} ({fc_amount} FCs @ ₦{FC_RATE}/FC) by {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'fc_consumption',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'fcAmount': fc_amount,
                'fcRate': FC_RATE,
                'service': service,
                'automated': True,
                'doubleEntry': True
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.incomes.insert_one(revenue_entry)
        
        # 2. Record liability reduction (Debit - negative expense = liability reduction)
        liability_reduction = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': -naira_revenue,  # Negative = liability reduction
            'category': 'Liability Adjustment',
            'description': f'FC Liability Reduction - {description}',
            'date': datetime.utcnow(),
            'sourceType': 'liability_adjustment_fc_consumption',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'linkedRevenueId': str(revenue_entry['_id']),
                'customerUserId': str(user_id),
                'fcAmount': fc_amount,
                'service': service,
                'automated': True,
                'doubleEntry': True
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(liability_reduction)
        
        print(f'✅ Recorded FC consumption revenue: {fc_amount} FCs (₦{safe_float(naira_revenue):,.2f}) from {user_email}')
        
        return {
            'revenue_id': revenue_entry['_id'],
            'liability_reduction_id': liability_reduction['_id'],
            'amount': naira_revenue
        }
        
    except Exception as e:
        print(f'❌ Error recording FC consumption revenue: {str(e)}')
        raise


def record_monthly_depreciation(mongo) -> ObjectId:
    """
    Record monthly depreciation for business assets
    Implements single-entry (accumulated depreciation tracked separately)
    - Dr. Depreciation Expense (increases expense)
    
    Returns:
        ObjectId of created expense entry
    """
    try:
        # Laptop depreciation: ₦200,000 / 24 months = ₦8,333.33
        # Used laptop, 2-year useful life (clunky, won't last 4 years)
        # Purchased: September 25, 2025
        # Current: March 9, 2026 (5 months elapsed)
        monthly_depreciation = 8333.33
        
        # Record depreciation expense
        depreciation_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': monthly_depreciation,
            'category': 'Depreciation',
            'description': 'Monthly Depreciation - Business Laptop (₦200K over 24 months)',
            'date': datetime.utcnow(),
            'sourceType': 'depreciation',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'assetName': 'Business Laptop (Used)',
                'assetCost': 200000.0,
                'usefulLife': 24,  # 2 years for used laptop
                'monthlyRate': monthly_depreciation,
                'automated': True,
                'doubleEntry': False  # Accumulated depreciation tracked separately
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(depreciation_entry)
        
        print(f'✅ Recorded monthly depreciation: ₦{safe_float(monthly_depreciation):,.2f}')
        
        return depreciation_entry['_id']
        
    except Exception as e:
        print(f'❌ Error recording monthly depreciation: {str(e)}')
        raise


def accrue_daily_subscription_revenue(mongo) -> list:
    """
    Accrue daily subscription revenue for PAID subscribers ONLY
    CRITICAL: Only process subscriptions where source='paystack'
    Do NOT accrue revenue for admin-granted subscriptions (marketing expenses)
    
    Returns:
        List of ObjectIds for created income entries
    """
    try:
        # Get PAID subscriptions only (source='paystack')
        paid_subs = list(mongo.db.subscriptions.find({
            'status': 'active',
            'isActive': True,
            'isDeleted': False,
            'source': 'paystack'  # CRITICAL: Only paid subscriptions
        }))
        
        if not paid_subs:
            print('ℹ️  No paid subscriptions found - skipping daily accrual')
            return []
        
        revenue_ids = []
        
        for sub in paid_subs:
            user_id = sub['userId']
            amount = sub.get('amount', 0)
            plan_type = sub.get('planType', sub.get('plan', 'Unknown'))
            
            # Calculate daily revenue
            if plan_type == 'ANNUAL':
                daily_revenue = amount / 365.0
            elif plan_type == 'MONTHLY':
                daily_revenue = amount / 30.0
            else:
                daily_revenue = amount / 365.0  # Default to annual
            
            # Get user email
            user = mongo.db.users.find_one({'_id': user_id})
            user_email = user.get('email', 'Unknown') if user else 'Unknown'
            
            # Record daily accrual
            revenue_entry = {
                '_id': ObjectId(),
                'userId': BUSINESS_USER_ID,
                'amount': daily_revenue,
                'category': 'Subscription Revenue',
                'description': f'Daily Subscription Accrual - {plan_type} for {user_email}',
                'date': datetime.utcnow(),
                'sourceType': 'subscription_accrual',
                'status': 'active',
                'isDeleted': False,
                'metadata': {
                    'subscriptionId': str(sub['_id']),
                    'customerUserId': str(user_id),
                    'customerEmail': user_email,
                    'planType': plan_type,
                    'dailyRate': daily_revenue,
                    'annualRate': amount,
                    'automated': True,
                    'doubleEntry': False  # Deferred revenue tracked separately
                },
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.incomes.insert_one(revenue_entry)
            revenue_ids.append(revenue_entry['_id'])
            
            print(f'✅ Accrued daily subscription revenue: ₦{safe_float(daily_revenue):,.2f} for {user_email}')
        
        return revenue_ids
        
    except Exception as e:
        print(f'❌ Error accruing daily subscription revenue: {str(e)}')
        raise
