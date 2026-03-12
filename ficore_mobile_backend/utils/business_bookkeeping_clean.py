"""
Business Bookkeeping Automation Utilities
Handles double-entry bookkeeping for FiCore business account
"""

from datetime import datetime
from bson import ObjectId
from typing import Dict, Any, Optional
from flask import current_app
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from decimal_helpers import safe_float

# Business account ID (ficoreafrica@gmail.com)
BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')

# FC Credit rate (₦30 per FC)
FC_RATE = 30.0


def award_fc_credits_with_accounting(
    mongo,
    user_id: ObjectId,
    fc_amount: float,
    operation: str,
    description: str,
    transaction_id: Optional[ObjectId] = None
) -> Dict[str, Any]:
    """
    CENTRALIZED WRAPPER: Award FC Credits with proper accounting
    
    This function ensures EVERY FC grant creates both:
    1. Credit transaction (user gets FCs)
    2. Marketing expense (business books)
    3. FC liability (business books)
    
    Args:
        mongo: MongoDB connection
        user_id: Recipient user ID
        fc_amount: Number of FCs to award
        operation: Operation type (signup_bonus, referral_bonus, etc.)
        description: Human-readable description
        transaction_id: Optional transaction ID for linking
    
    Returns:
        Dict with credit_transaction_id, expense_id, liability_id
    """
    try:
        # 1. Create credit transaction (user gets FCs)
        credit_transaction = {
            '_id': ObjectId(),
            'userId': user_id,
            'amount': fc_amount,
            'type': operation.upper(),
            'description': description,
            'status': 'completed',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'operation': operation,
                'fcRate': 30.0,  # Hardcoded ₦30/FC rate
                'nairaValue': fc_amount * 30.0,
                'automated': True
            }
        }
        
        if transaction_id:
            credit_transaction['transactionId'] = transaction_id
        
        mongo.db.credit_transactions.insert_one(credit_transaction)
        
        # 2. Record marketing expense + liability (business books)
        accounting_result = record_fc_marketing_expense(
            mongo=mongo,
            user_id=user_id,
            fc_amount=fc_amount,
            operation=operation,
            description=description
        )
        
        print(f'✅ Awarded {fc_amount} FCs to user {user_id} with full accounting')
        
        return {
            'success': True,
            'credit_transaction_id': credit_transaction['_id'],
            'expense_id': accounting_result['expense_id'],
            'liability_id': accounting_result['liability_id'],
            'fc_amount': fc_amount,
            'naira_value': fc_amount * 30.0
        }
        
    except Exception as e:
        print(f'❌ Error awarding FC credits with accounting: {str(e)}')
        return {
            'success': False,
            'error': str(e)
        }


def award_subscription_with_accounting(
    mongo,
    user_id: ObjectId,
    subscription_id: ObjectId,
    amount: float,
    plan_type: str,
    granted_by: str,
    grant_reason: str
) -> Dict[str, Any]:
    """
    CENTRALIZED WRAPPER: Award Subscription with proper accounting
    
    This function ensures EVERY subscription grant creates both:
    1. Subscription record (user gets subscription)
    2. Marketing expense (business books)
    3. Subscription liability (business books)
    
    Args:
        mongo: MongoDB connection
        user_id: Recipient user ID
        subscription_id: Subscription document ID
        amount: Subscription value
        plan_type: Plan type (ANNUAL, MONTHLY)
        granted_by: Admin who granted it
        grant_reason: Reason for grant
    
    Returns:
        Dict with subscription_id, expense_id, liability_id
    """
    try:
        # 1. Subscription record should already exist (created by admin)
        # We just need to add the accounting
        
        # 2. Record marketing expense + liability (business books)
        accounting_result = record_subscription_marketing_expense(
            mongo=mongo,
            user_id=user_id,
            subscription_id=subscription_id,
            amount=amount,
            plan_type=plan_type,
            granted_by=granted_by,
            grant_reason=grant_reason
        )
        
        print(f'✅ Recorded subscription accounting for user {user_id}: ₦{amount:,.2f}')
        
        return {
            'success': True,
            'subscription_id': subscription_id,
            'expense_id': accounting_result['expense_id'],
            'liability_id': accounting_result['liability_id'],
            'amount': amount
        }
        
    except Exception as e:
        print(f'❌ Error recording subscription accounting: {str(e)}')
        return {
            'success': False,
            'error': str(e)
        }


def award_fee_waiver_with_accounting(
    mongo,
    user_id: ObjectId,
    fee_amount: float,
    waiver_reason: str = "Referral deposit fee waiver"
) -> Dict[str, Any]:
    """
    CENTRALIZED WRAPPER: Award Fee Waiver with proper accounting
    
    This function ensures EVERY fee waiver creates both:
    1. Fee waiver benefit (user gets waiver)
    2. Marketing expense (business books)
    3. Fee waiver liability (business books)
    
    Args:
        mongo: MongoDB connection
        user_id: User who gets the fee waiver
        fee_amount: Amount waived (usually ₦30)
        waiver_reason: Reason for waiver
    
    Returns:
        Dict with expense_id, liability_id
    """
    try:
        # Get user email for description
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # 1. Record marketing expense (Debit)
        expense_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': fee_amount,
            'category': 'Marketing Ads and Promotion',
            'description': f'{waiver_reason} for {user_email} (₦{fee_amount:,.2f})',
            'date': datetime.utcnow(),
            'sourceType': 'marketing_expense_fee_waiver',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'recipientUserId': str(user_id),
                'recipientEmail': user_email,
                'waiverReason': waiver_reason,
                'feeAmount': fee_amount,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'liability'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(expense_entry)
        
        # 2. Record fee waiver liability (Credit)
        liability_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': fee_amount,
            'category': 'Deferred Revenue - Fee Waiver Liability',
            'description': f'Fee Waiver Liability - {waiver_reason} for {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'fee_waiver_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'type': 'LIABILITY_INCREASE',
                'linkedExpenseId': str(expense_entry['_id']),
                'recipientUserId': str(user_id),
                'recipientEmail': user_email,
                'waiverReason': waiver_reason,
                'feeAmount': fee_amount,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'liability'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.incomes.insert_one(liability_entry)
        
        print(f'✅ Recorded fee waiver accounting for {user_email}: ₦{fee_amount:,.2f}')
        
        return {
            'success': True,
            'expense_id': expense_entry['_id'],
            'liability_id': liability_entry['_id'],
            'amount': fee_amount
        }
        
    except Exception as e:
        print(f'❌ Error recording fee waiver accounting: {str(e)}')
        return {
            'success': False,
            'error': str(e)
        }


def validate_promotional_award(
    mongo,
    user_id: ObjectId,
    award_type: str,
    amount: float,
    transaction_id: Optional[ObjectId] = None
) -> Dict[str, Any]:
    """
    SAFEGUARD: Validate promotional award has proper bookkeeping
    
    This function ensures no user receives promotional value without
    corresponding entries in the business bookkeeping system.
    
    Args:
        mongo: MongoDB connection
        user_id: User receiving the award
        award_type: Type of award (fc_bonus, subscription, fee_waiver)
        amount: Value of award
        transaction_id: Optional transaction ID for linking
    
    Returns:
        Dict with validation result
    """
    try:
        # Check if corresponding marketing expense exists
        if award_type == 'fc_bonus':
            # Check for FC marketing expense
            marketing_expense = mongo.db.expenses.find_one({
                'userId': BUSINESS_USER_ID,
                'category': 'Marketing Ads and Promotion',
                'metadata.recipientUserId': str(user_id),
                'sourceType': {'$regex': 'marketing_expense'},
                'status': 'active',
                'isDeleted': False
            })
            
            # Check for FC liability
            fc_liability = mongo.db.incomes.find_one({
                'userId': BUSINESS_USER_ID,
                'sourceType': 'fc_liability_accrual',
                'metadata.recipientUserId': str(user_id),
                'status': 'active',
                'isDeleted': False
            })
            
            if not marketing_expense or not fc_liability:
                return {
                    'valid': False,
                    'error': 'FC bonus missing corresponding marketing expense or liability',
                    'marketing_expense_exists': bool(marketing_expense),
                    'fc_liability_exists': bool(fc_liability)
                }
        
        elif award_type == 'subscription':
            # Check for subscription marketing expense
            marketing_expense = mongo.db.expenses.find_one({
                'userId': BUSINESS_USER_ID,
                'category': 'Marketing Ads and Promotion',
                'sourceType': 'marketing_expense_subscription',
                'metadata.recipientUserId': str(user_id),
                'status': 'active',
                'isDeleted': False
            })
            
            # Check for subscription liability
            sub_liability = mongo.db.incomes.find_one({
                'userId': BUSINESS_USER_ID,
                'sourceType': 'subscription_liability_accrual',
                'metadata.recipientUserId': str(user_id),
                'status': 'active',
                'isDeleted': False
            })
            
            if not marketing_expense or not sub_liability:
                return {
                    'valid': False,
                    'error': 'Subscription missing corresponding marketing expense or liability',
                    'marketing_expense_exists': bool(marketing_expense),
                    'subscription_liability_exists': bool(sub_liability)
                }
        
        elif award_type == 'fee_waiver':
            # Check for fee waiver marketing expense
            marketing_expense = mongo.db.expenses.find_one({
                'userId': BUSINESS_USER_ID,
                'category': 'Marketing Ads and Promotion',
                'sourceType': 'marketing_expense_fee_waiver',
                'metadata.recipientUserId': str(user_id),
                'status': 'active',
                'isDeleted': False
            })
            
            # Check for fee waiver liability
            fee_liability = mongo.db.incomes.find_one({
                'userId': BUSINESS_USER_ID,
                'sourceType': 'fee_waiver_liability_accrual',
                'metadata.recipientUserId': str(user_id),
                'status': 'active',
                'isDeleted': False
            })
            
            if not marketing_expense or not fee_liability:
                return {
                    'valid': False,
                    'error': 'Fee waiver missing corresponding marketing expense or liability',
                    'marketing_expense_exists': bool(marketing_expense),
                    'fee_liability_exists': bool(fee_liability)
                }
        
        return {
            'valid': True,
            'message': f'{award_type} has proper bookkeeping entries'
        }
        
    except Exception as e:
        return {
            'valid': False,
            'error': f'Validation error: {str(e)}'
        }


def enforce_bookkeeping_requirement(
    mongo,
    user_id: ObjectId,
    award_type: str,
    amount: float
) -> bool:
    """
    ENFORCEMENT: Block promotional awards without proper bookkeeping
    
    This function should be called BEFORE granting any promotional value.
    It will block the award if proper bookkeeping entries don't exist.
    
    Args:
        mongo: MongoDB connection
        user_id: User who would receive the award
        award_type: Type of award
        amount: Value of award
    
    Returns:
        bool: True if award is allowed, False if blocked
    """
    try:
        validation = validate_promotional_award(
            mongo=mongo,
            user_id=user_id,
            award_type=award_type,
            amount=amount
        )
        
        if not validation['valid']:
            print(f'🚫 BLOCKED: {award_type} for user {user_id}')
            print(f'   Reason: {validation["error"]}')
            return False
        
        print(f'✅ ALLOWED: {award_type} for user {user_id} (proper bookkeeping exists)')
        return True
        
    except Exception as e:
        print(f'❌ Error enforcing bookkeeping requirement: {str(e)}')
        return False  # Block on error (fail-safe)


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
        
        # Determine category and sourceType (using standardized category name)
        category_map = {
            'signup_bonus': ('Marketing Ads and Promotion', 'marketing_expense_signup'),
            'tax_education_progress': ('Marketing Ads and Promotion', 'marketing_expense_tax_education'),
            'exploration_bonus': ('Marketing Ads and Promotion', 'marketing_expense_exploration'),
            'streak_milestone': ('Marketing Ads and Promotion', 'marketing_expense_streak'),
            'engagement_reward': ('Marketing Ads and Promotion', 'marketing_expense_engagement'),
            'admin_award': ('Marketing Ads and Promotion', 'marketing_expense_admin'),
            'referral_bonus': ('Marketing Ads and Promotion', 'marketing_expense_referral'),  # NEW: Referral FC bonuses
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


def record_fee_refund_marketing_expense(
    mongo,
    user_id: ObjectId,
    fee_amount: float,
    refund_reason: str = "Referral deposit fee waiver"
) -> Dict[str, ObjectId]:
    """
    Record fee refund as marketing expense in business books
    
    This is for direct cash refunds (like deposit fee waivers) that are marketing costs.
    Unlike FC bonuses, this is actual cash given back to users.
    
    Implements single-entry expense recording:
    - Dr. Marketing Expense (increases expense on P&L)
    
    Args:
        mongo: MongoDB connection
        user_id: User who received the refund
        fee_amount: Amount refunded (in Naira)
        refund_reason: Reason for refund
        
    Returns:
        Dict with expense_id
    """
    try:
        from bson import ObjectId
        from datetime import datetime
        
        # Get business user ID
        BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')  # ficoreafrica@gmail.com
        
        # Get user info for description
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # Record expense - Direct marketing cost (cash refund)
        expense_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': safe_float(fee_amount),
            'category': 'Marketing Ads and Promotion',
            'description': f'{refund_reason} for {user_email} (₦{safe_float(fee_amount):,.2f})',
            'date': datetime.utcnow(),
            'sourceType': 'marketing_expense_fee_refund',
            'status': 'active',
            'isDeleted': False,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'refundedUserId': str(user_id),
                'refundedUserEmail': user_email,
                'refundReason': refund_reason,
                'refundType': 'deposit_fee_waiver',
                'isMarketingCost': True
            }
        }
        
        mongo.db.expenses.insert_one(expense_entry)
        
        print(f'✅ Recorded fee refund marketing expense: ₦{safe_float(fee_amount):,.2f} for {user_email}')
        print(f'   Dr. Marketing Expense: ₦{safe_float(fee_amount):,.2f} ({refund_reason})')
        
        return {
            'expense_id': expense_entry['_id']
        }
        
    except Exception as e:
        print(f'❌ Error recording fee refund marketing expense: {str(e)}')
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



def record_subscription_consumption_revenue(
    mongo,
    user_id: ObjectId,
    consumption_amount: float,
    description: str,
    service: str
) -> Dict[str, any]:
    """
    Record subscription consumption revenue when services are used
    
    This function:
    1. Checks if user has outstanding subscription liabilities
    2. Consumes available liability (up to consumption_amount)
    3. Records revenue for consumed amount
    4. Records liability reduction
    
    Args:
        mongo: MongoDB connection
        user_id: User who consumed the service
        consumption_amount: Amount of service consumed (in Naira)
        description: Description of the service consumed
        service: Service type (vas_purchase, report_export, etc.)
    
    Returns:
        Dict with consumed_amount, revenue_id, liability_reduction_id
    """
    try:
        # Get user details
        user = mongo.db.users.find_one({'_id': user_id})
        if not user:
            print(f'❌ User not found: {user_id}')
            return {'consumed_amount': 0}
        
        user_email = user.get('email', 'Unknown')
        
        # Calculate total outstanding subscription liabilities for this user
        total_liability = calculate_user_subscription_liabilities(mongo, user_id)
        
        if total_liability <= 0:
            # No subscription liability to consume
            return {'consumed_amount': 0}
        
        # Determine how much to consume (limited by available liability)
        consumed_amount = min(consumption_amount, total_liability)
        
        if consumed_amount <= 0:
            return {'consumed_amount': 0}
        
        # 1. Record revenue (Credit)
        revenue_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': consumed_amount,
            'category': 'Subscription Revenue',
            'description': f'Subscription Service Consumption - {description} for {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'subscription_consumption',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'service': service,
                'consumedAmount': consumed_amount,
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
            'amount': -consumed_amount,  # Negative = liability reduction
            'category': 'Liability Adjustment',
            'description': f'Subscription Liability Reduction - Service consumption for {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'liability_adjustment_subscription',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'linkedRevenueId': str(revenue_entry['_id']),
                'customerUserId': str(user_id),
                'service': service,
                'consumedAmount': consumed_amount,
                'automated': True,
                'doubleEntry': True
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(liability_reduction)
        
        print(f'✅ Subscription consumption recorded: ₦{consumed_amount:,.2f} for {user_email} ({service})')
        
        return {
            'consumed_amount': consumed_amount,
            'revenue_id': revenue_entry['_id'],
            'liability_reduction_id': liability_reduction['_id']
        }
        
    except Exception as e:
        print(f'❌ Error recording subscription consumption: {str(e)}')
        raise


def calculate_user_subscription_liabilities(mongo, user_id: ObjectId) -> float:
    """
    Calculate total outstanding subscription liabilities for a specific user
    
    This sums up all subscription liabilities minus any consumption already recorded.
    
    Args:
        mongo: MongoDB connection
        user_id: User ID to calculate liabilities for
    
    Returns:
        Total outstanding subscription liability amount (in Naira)
    """
    try:
        # Get all subscription liabilities for this user
        subscription_liabilities = list(mongo.db.subscription_liabilities.find({
            'userId': user_id,
            'status': 'active',
            'isDeleted': False
        }))
        
        total_granted = sum(liability.get('amount', 0) for liability in subscription_liabilities)
        
        # Get all subscription consumption for this user
        consumption_entries = list(mongo.db.expenses.find({
            'sourceType': 'liability_adjustment_subscription',
            'metadata.customerUserId': str(user_id),
            'status': 'active',
            'isDeleted': False
        }))
        
        total_consumed = sum(abs(entry.get('amount', 0)) for entry in consumption_entries)
        
        outstanding_liability = total_granted - total_consumed
        
        return max(0, outstanding_liability)  # Never negative
        
    except Exception as e:
        print(f'❌ Error calculating user subscription liabilities: {str(e)}')
        return 0.0

def record_monthly_depreciation(mongo) -> ObjectId:
    """
    Record monthly depreciation for business assets
    Implements double-entry bookkeeping:
    - Dr. Depreciation Expense (increases expense on P&L)
    - Cr. Accumulated Depreciation (reduces asset value on Balance Sheet)
    
    Returns:
        ObjectId of created expense entry
    """
    try:
        # Laptop depreciation: ₦200,000 / 24 months = ₦8,333.33
        # Used laptop, 2-year useful life (clunky, won't last 4 years)
        # Purchased: September 25, 2025
        # Current: March 9, 2026 (5 months elapsed)
        monthly_depreciation = 8333.33
        
        # 1. Record depreciation expense (Debit) - Goes to P&L
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
                'doubleEntry': True,  # FIXED: Now properly double-entry
                'linkedAccumulatedDepreciationId': None  # Will be set below
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(depreciation_entry)
        
        # 2. Record accumulated depreciation (Credit) - Reduces asset value on Balance Sheet
        # Store as negative income to represent contra-asset account
        accumulated_depreciation_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': -monthly_depreciation,  # Negative = contra-asset (reduces asset value)
            'category': 'Accumulated Depreciation - Laptop',
            'description': 'Monthly Accumulated Depreciation - Business Laptop',
            'date': datetime.utcnow(),
            'sourceType': 'accumulated_depreciation',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'type': 'CONTRA_ASSET',  # Reduces asset value
                'linkedDepreciationExpenseId': str(depreciation_entry['_id']),
                'assetName': 'Business Laptop (Used)',
                'assetCost': 200000.0,
                'monthlyRate': monthly_depreciation,
                'automated': True,
                'doubleEntry': True
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        # Store accumulated depreciation in incomes collection (as negative to represent contra-asset)
        mongo.db.incomes.insert_one(accumulated_depreciation_entry)
        
        # 3. Link the two entries
        mongo.db.expenses.update_one(
            {'_id': depreciation_entry['_id']},
            {'$set': {'metadata.linkedAccumulatedDepreciationId': str(accumulated_depreciation_entry['_id'])}}
        )
        
        print(f'✅ Recorded monthly depreciation: ₦{safe_float(monthly_depreciation):,.2f}')
        print(f'   Dr. Depreciation Expense: ₦{safe_float(monthly_depreciation):,.2f} (P&L)')
        print(f'   Cr. Accumulated Depreciation: ₦{safe_float(monthly_depreciation):,.2f} (Balance Sheet)')
        
        return depreciation_entry['_id']
        
    except Exception as e:
        print(f'❌ Error recording monthly depreciation: {str(e)}')
        raise


def consume_fee_waiver_liability(
    mongo,
    user_id: ObjectId,
    deposit_amount: float
) -> Dict[str, ObjectId]:
    """
    Consume fee waiver liability when user makes a deposit
    Implements double-entry bookkeeping:
    - Dr. Fee Waiver Liability (reduces liability)
    - Cr. Revenue (increases income)
    
    Args:
        mongo: MongoDB connection
        user_id: User who made the deposit
        deposit_amount: Amount deposited (triggers consumption)
    
    Returns:
        Dict with revenue_id and liability_reduction_id
    """
    try:
        # Check if user has outstanding fee waiver liability
        fee_waiver_liabilities = list(mongo.db.incomes.find({
            'sourceType': 'fee_waiver_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'metadata.recipientUserId': str(user_id)
        }))
        
        if not fee_waiver_liabilities:
            print(f'ℹ️  No fee waiver liability found for user {user_id}')
            return {}
        
        # Get user email for description
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # Calculate total outstanding liability
        total_liability = sum(l.get('amount', 0) for l in fee_waiver_liabilities)
        
        # Consume the liability (up to the amount available)
        consumption_amount = min(total_liability, 30.0)  # Fee waiver is ₦30
        
        # 1. Record revenue (Credit) - Fee waiver service provided
        revenue_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': consumption_amount,
            'category': 'Service Revenue',
            'description': f'Fee Waiver Service Provided - Deposit by {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'fee_waiver_consumption',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'depositAmount': deposit_amount,
                'liabilityConsumed': consumption_amount,
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
            'amount': -consumption_amount,  # Negative = liability reduction
            'category': 'Liability Adjustment',
            'description': f'Fee Waiver Liability Reduction - Service provided to {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'liability_adjustment_fee_waiver',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'linkedRevenueId': str(revenue_entry['_id']),
                'customerUserId': str(user_id),
                'liabilityConsumed': consumption_amount,
                'automated': True,
                'doubleEntry': True
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(liability_reduction)
        
        print(f'✅ Consumed fee waiver liability: ₦{consumption_amount:,.2f} for {user_email}')
        
        return {
            'revenue_id': revenue_entry['_id'],
            'liability_reduction_id': liability_reduction['_id'],
            'amount': consumption_amount
        }
        
    except Exception as e:
        print(f'❌ Error consuming fee waiver liability: {str(e)}')
        raise


def award_and_consume_fc_credits_atomic(
    mongo,
    user_id: ObjectId,
    fc_amount: float,
    operation: str,
    description: str,
    transaction_id: Optional[ObjectId] = None
) -> Dict[str, Any]:
    """
    ATOMIC FC CREDITS: Create liability and consume it immediately
    
    This function ensures FC credit liability and consumption happen atomically.
    Unlike fee waivers which are consumed on deposit, FC credits are consumed
    immediately when awarded (instant service provided).
    
    Steps:
    1. Create credit transaction (user gets FCs)
    2. Create marketing expense + FC liability
    3. Immediately consume the liability (service provided)
    4. Record revenue for service provided
    
    Args:
        mongo: MongoDB connection
        user_id: Recipient user ID
        fc_amount: Number of FCs to award
        operation: Operation type (signup_bonus, referral_bonus, etc.)
        description: Human-readable description
        transaction_id: Optional transaction ID for linking
    
    Returns:
        Dict with all transaction IDs
    """
    try:
        print(f"🔄 ATOMIC FC CREDITS: Creating and consuming {fc_amount} FCs liability for user {user_id}")
        
        # Step 1: Create credit transaction (user gets FCs)
        credit_transaction = {
            '_id': ObjectId(),
            'userId': user_id,
            'amount': fc_amount,
            'type': operation.upper(),
            'description': description,
            'status': 'completed',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'operation': operation,
                'fcRate': 30.0,  # Hardcoded ₦30/FC rate
                'nairaValue': fc_amount * 30.0,
                'automated': True
            }
        }
        
        if transaction_id:
            credit_transaction['transactionId'] = transaction_id
        
        mongo.db.credit_transactions.insert_one(credit_transaction)
        
        # Step 2: Create liability (expense + liability)
        accounting_result = record_fc_marketing_expense(
            mongo=mongo,
            user_id=user_id,
            fc_amount=fc_amount,
            operation=operation,
            description=description
        )
        
        print(f"✅ Created liability: Expense ID {accounting_result['expense_id']}, Liability ID {accounting_result['liability_id']}")
        
        # Step 3: Immediately consume liability (revenue + liability reduction)
        consume_result = record_fc_consumption_revenue(
            mongo=mongo,
            user_id=user_id,
            fc_amount=fc_amount,
            description=f"FC Credits Service Provided - {description}",
            service=operation
        )
        
        print(f"✅ Consumed liability: Revenue ID {consume_result['revenue_id']}, Reduction ID {consume_result['liability_reduction_id']}")
        
        return {
            'success': True,
            'fc_amount': fc_amount,
            'naira_value': fc_amount * 30.0,
            'credit_transaction_id': credit_transaction['_id'],
            'accounting_result': accounting_result,
            'consume_result': consume_result,
            'transactions': {
                'credit_transaction_id': credit_transaction['_id'],
                'marketing_expense_id': accounting_result['expense_id'],
                'liability_creation_id': accounting_result['liability_id'],
                'revenue_id': consume_result['revenue_id'],
                'liability_reduction_id': consume_result['liability_reduction_id']
            }
        }
        
    except Exception as e:
        print(f"❌ Error in atomic FC credits: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def award_and_consume_subscription_atomic(
    mongo,
    user_id: ObjectId,
    subscription_id: ObjectId,
    amount: float,
    plan_type: str,
    granted_by: str,
    grant_reason: str
) -> Dict[str, Any]:
    """
    ATOMIC SUBSCRIPTION: Create liability and consume it immediately
    
    This function ensures subscription liability and consumption happen atomically.
    For admin-granted subscriptions, the service is provided immediately.
    
    Steps:
    1. Create marketing expense + subscription liability
    2. Immediately consume the liability (service provided)
    3. Record revenue for service provided
    
    Args:
        mongo: MongoDB connection
        user_id: Recipient user ID
        subscription_id: Subscription document ID
        amount: Subscription value
        plan_type: Plan type (ANNUAL, MONTHLY)
        granted_by: Admin who granted it
        grant_reason: Reason for grant
    
    Returns:
        Dict with all transaction IDs
    """
    try:
        print(f"🔄 ATOMIC SUBSCRIPTION: Creating and consuming ₦{amount} liability for user {user_id}")
        
        # Step 1: Create liability (expense + liability)
        award_result = award_subscription_with_accounting(
            mongo=mongo,
            user_id=user_id,
            subscription_id=subscription_id,
            amount=amount,
            plan_type=plan_type,
            granted_by=granted_by,
            grant_reason=grant_reason
        )
        
        if not award_result.get('success'):
            raise Exception(f"Failed to create subscription liability: {award_result.get('error')}")
        
        print(f"✅ Created liability: Expense ID {award_result['expense_id']}, Liability ID {award_result['liability_id']}")
        
        # Step 2: Immediately consume liability (revenue + liability reduction)
        consume_result = record_subscription_consumption_revenue(
            mongo=mongo,
            user_id=user_id,
            consumption_amount=amount,
            description=f"Admin-granted {plan_type} subscription service provided",
            service="admin_subscription"
        )
        
        print(f"✅ Consumed liability: Revenue ID {consume_result['revenue_id']}, Reduction ID {consume_result['liability_reduction_id']}")
        
        return {
            'success': True,
            'subscription_id': subscription_id,
            'amount': amount,
            'award_result': award_result,
            'consume_result': consume_result,
            'transactions': {
                'marketing_expense_id': award_result['expense_id'],
                'liability_creation_id': award_result['liability_id'],
                'revenue_id': consume_result['revenue_id'],
                'liability_reduction_id': consume_result['liability_reduction_id']
            }
        }
        
    except Exception as e:
        print(f"❌ Error in atomic subscription: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def consume_subscription_liability_daily(
    mongo,
    subscription_id: ObjectId,
    user_id: ObjectId,
    daily_amount: float,
    plan_type: str
) -> Dict[str, ObjectId]:
    """
    Consume subscription liability daily (accrual accounting)
    Implements double-entry bookkeeping:
    - Dr. Subscription Liability (reduces liability)
    - Cr. Revenue (increases income)
    
    This should be called daily for each active admin-granted subscription.
    
    Args:
        mongo: MongoDB connection
        subscription_id: Subscription document ID
        user_id: User who has the subscription
        daily_amount: Daily revenue amount (total_amount / days_in_period)
        plan_type: Plan type (ANNUAL, MONTHLY)
    
    Returns:
        Dict with revenue_id and liability_reduction_id
    """
    try:
        # Get user email for description
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # 1. Record daily revenue (Credit)
        revenue_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': daily_amount,
            'category': 'Subscription Revenue',
            'description': f'Daily Subscription Accrual - {plan_type} for {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'subscription_consumption',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'subscriptionId': str(subscription_id),
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'planType': plan_type,
                'dailyAmount': daily_amount,
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
            'amount': -daily_amount,  # Negative = liability reduction
            'category': 'Liability Adjustment',
            'description': f'Subscription Liability Reduction - Daily accrual for {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'liability_adjustment_subscription',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'linkedRevenueId': str(revenue_entry['_id']),
                'subscriptionId': str(subscription_id),
                'customerUserId': str(user_id),
                'planType': plan_type,
                'dailyAmount': daily_amount,
                'automated': True,
                'doubleEntry': True
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(liability_reduction)
        
        print(f'✅ Consumed subscription liability: ₦{daily_amount:,.2f} for {user_email}')
        
        return {
            'revenue_id': revenue_entry['_id'],
            'liability_reduction_id': liability_reduction['_id'],
            'amount': daily_amount
        }
        
    except Exception as e:
        print(f'❌ Error consuming subscription liability: {str(e)}')
        raise


def process_daily_subscription_accruals(mongo) -> list:
    """
    Process daily subscription accruals for all admin-granted subscriptions
    This should be called daily via cron job
    
    Returns:
        List of processed subscription IDs
    """
    try:
        # Get all admin-granted subscriptions (source != 'paystack')
        admin_subscriptions = list(mongo.db.subscriptions.find({
            'status': 'active',
            'isActive': True,
            'isDeleted': False,
            'source': {'$ne': 'paystack'}  # Admin-granted subscriptions only
        }))
        
        processed_ids = []
        
        for subscription in admin_subscriptions:
            subscription_id = subscription['_id']
            user_id = subscription['userId']
            amount = subscription.get('amount', 0)
            plan_type = subscription.get('planType', subscription.get('plan', 'Unknown'))
            
            # Calculate daily amount
            if plan_type == 'ANNUAL':
                daily_amount = amount / 365.0
            elif plan_type == 'MONTHLY':
                daily_amount = amount / 30.0
            else:
                daily_amount = amount / 365.0  # Default to annual
            
            # Check if already processed today
            today = datetime.utcnow().date()
            existing_accrual = mongo.db.incomes.find_one({
                'sourceType': 'subscription_consumption',
                'metadata.subscriptionId': str(subscription_id),
                'date': {
                    '$gte': datetime.combine(today, datetime.min.time()),
                    '$lt': datetime.combine(today, datetime.max.time())
                }
            })
            
            if existing_accrual:
                print(f'ℹ️  Subscription {subscription_id} already processed today')
                continue
            
            # Process daily accrual
            consume_subscription_liability_daily(
                mongo=mongo,
                subscription_id=subscription_id,
                user_id=user_id,
                daily_amount=daily_amount,
                plan_type=plan_type
            )
            
            processed_ids.append(subscription_id)
        
        return processed_ids
        
    except Exception as e:
        print(f'❌ Error processing daily subscription accruals: {str(e)}')
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

