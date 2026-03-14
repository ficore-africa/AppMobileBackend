"""
Unified Corporate Revenue Recording System
Handles all types of corporate revenue with consistent patterns
"""

from datetime import datetime
from bson import ObjectId
from typing import Dict, Any, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from decimal_helpers import safe_float
from test_account_filter import is_test_account

# Business account ID (ficoreafrica@gmail.com)
BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')


def record_corporate_revenue_automatically(
    mongo,
    revenue_type: str,
    amount: float,
    user_id: ObjectId,
    transaction_id: Optional[ObjectId] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    UNIFIED CORPORATE REVENUE RECORDING SYSTEM
    
    Handles all types of corporate revenue AND related expenses with consistent patterns:
    - VAS commissions (REVENUE from successful VAS transactions)
    - Deposit fees (REVENUE from wallet deposits)
    - Gateway fees (EXPENSE from payment processing)
    - FC credits sales (REVENUE from Paystack purchases)
    - Subscription sales (REVENUE from Paystack purchases)
    
    CRITICAL: Automatically filters out test accounts to maintain accurate business metrics
    
    Args:
        mongo: MongoDB connection
        revenue_type: Type of revenue/expense ('vas_commission', 'deposit_fee', 'gateway_fee', 'fc_credits_sale', 'subscription_sale')
        amount: Revenue/expense amount in Naira
        user_id: Customer user ID
        transaction_id: Optional transaction ID for linking
        metadata: Optional additional metadata
    
    Returns:
        Dict with success status and transaction details
    """
    try:
        # Get user details
        user = mongo.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # 🚨 CRITICAL: Filter out test accounts to maintain accurate business metrics
        if is_test_account(user_email):
            print(f'⚠️  SKIPPING corporate revenue recording for test account: {user_email} (₦{amount:.2f} {revenue_type})')
            return {
                'success': True,
                'skipped': True,
                'reason': 'test_account',
                'user_email': user_email,
                'amount': amount,
                'revenue_type': revenue_type
            }
        
        # Route to specific revenue handler
        if revenue_type == 'vas_commission':
            return _record_vas_commission_revenue(mongo, amount, user_id, user_email, transaction_id, metadata)
        elif revenue_type == 'deposit_fee':
            return _record_deposit_fee_revenue(mongo, amount, user_id, user_email, transaction_id, metadata)
        elif revenue_type == 'gateway_fee':
            return _record_gateway_fee_expense(mongo, amount, user_id, user_email, transaction_id, metadata)
        elif revenue_type == 'fc_credits_sale':
            return _record_fc_credits_sale_revenue(mongo, amount, user_id, user_email, transaction_id, metadata)
        elif revenue_type == 'subscription_sale':
            return _record_subscription_sale_revenue(mongo, amount, user_id, user_email, transaction_id, metadata)
        else:
            raise ValueError(f"Unknown revenue_type: {revenue_type}")
            
    except Exception as e:
        print(f'❌ Error recording corporate revenue ({revenue_type}): {str(e)}')
        return {'success': False, 'error': str(e)}


def _record_vas_commission_revenue(
    mongo,
    amount: float,
    user_id: ObjectId,
    user_email: str,
    transaction_id: Optional[ObjectId],
    metadata: Optional[Dict]
) -> Dict[str, Any]:
    """
    Record VAS commission revenue - UPDATED to match treasury dashboard expectations
    
    CRITICAL: Treasury dashboard reads VAS commissions from vas_transactions.providerCommission
    This function ensures the VAS transaction record has the correct commission field
    rather than creating duplicate entries in other collections.
    """
    try:
        # Extract metadata
        provider = metadata.get('provider', 'unknown') if metadata else 'unknown'
        transaction_type = metadata.get('transaction_type', 'VAS') if metadata else 'VAS'
        transaction_amount = metadata.get('transaction_amount', 0) if metadata else 0
        
        # Calculate commission rate
        commission_rate = (amount / transaction_amount * 100) if transaction_amount > 0 else 0
        
        # CRITICAL FIX: Update the VAS transaction record with commission
        # Treasury dashboard reads from vas_transactions.providerCommission
        if transaction_id:
            mongo.vas_transactions.update_one(
                {'_id': transaction_id},
                {
                    '$set': {
                        'providerCommission': safe_float(amount),
                        'commissionRate': commission_rate,
                        'commissionRecordedAt': datetime.utcnow()
                    }
                }
            )
            print(f'✅ Updated VAS transaction {transaction_id} with commission: ₦{safe_float(amount):,.2f}')
        
        # Also record in incomes collection for detailed business accounting
        revenue_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': safe_float(amount),
            'category': 'Service Revenue',
            'description': f'VAS Commission - {provider.capitalize()} {transaction_type} (₦{safe_float(transaction_amount):,.2f} @ {commission_rate:.2f}%)',
            'date': datetime.utcnow(),
            'sourceType': 'vas_commission',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'vasTransactionId': str(transaction_id) if transaction_id else None,
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'provider': provider,
                'transactionType': transaction_type,
                'transactionAmount': transaction_amount,
                'commissionRate': commission_rate,
                'automated': True,
                'doubleEntry': False,  # Cash already in provider account
                'revenueType': 'vas_commission'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.incomes.insert_one(revenue_entry)
        
        print(f'✅ VAS commission recorded in both collections: ₦{safe_float(amount):,.2f} from {provider} {transaction_type}')
        
        return {
            'success': True,
            'revenue_id': revenue_entry['_id'],
            'amount': amount,
            'revenue_type': 'vas_commission'
        }
        
    except Exception as e:
        print(f'❌ Error recording VAS commission: {str(e)}')
        raise


def _record_deposit_fee_revenue(
    mongo,
    amount: float,
    user_id: ObjectId,
    user_email: str,
    transaction_id: Optional[ObjectId],
    metadata: Optional[Dict]
) -> Dict[str, Any]:
    """
    Record deposit fee revenue - UPDATED to match treasury dashboard expectations
    
    CRITICAL: Treasury dashboard reads deposit fees from corporate_revenue collection
    with type: 'SERVICE_FEE' and category: 'DEPOSIT_FEE'
    """
    try:
        # Extract metadata
        deposit_amount = metadata.get('deposit_amount', 0) if metadata else 0
        fee_rate = metadata.get('fee_rate', 3.0) if metadata else 3.0  # 3% default
        gateway_fee = metadata.get('gateway_fee', 0) if metadata else 0
        net_revenue = amount - gateway_fee
        
        # CRITICAL FIX: Record in corporate_revenue collection to match treasury expectations
        corporate_revenue_entry = {
            '_id': ObjectId(),
            'userId': user_id,  # Customer user ID (not business)
            'amount': safe_float(amount),
            'type': 'SERVICE_FEE',
            'category': 'DEPOSIT_FEE',
            'description': f'Deposit Fee - ₦{safe_float(deposit_amount):,.2f} deposit by {user_email} ({fee_rate}%)',
            'gatewayFee': safe_float(gateway_fee),
            'netRevenue': safe_float(net_revenue),
            'metadata': {
                'walletTransactionId': str(transaction_id) if transaction_id else None,
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'depositAmount': deposit_amount,
                'feeRate': fee_rate,
                'automated': True,
                'revenueType': 'deposit_fee'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.corporate_revenue.insert_one(corporate_revenue_entry)
        
        # Also record in incomes collection for detailed business accounting
        income_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': safe_float(amount),
            'category': 'Service Revenue',
            'description': f'Deposit Fee - ₦{safe_float(deposit_amount):,.2f} deposit by {user_email} ({fee_rate}%)',
            'date': datetime.utcnow(),
            'sourceType': 'deposit_fee',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'walletTransactionId': str(transaction_id) if transaction_id else None,
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'depositAmount': deposit_amount,
                'feeRate': fee_rate,
                'automated': True,
                'doubleEntry': False,  # Cash already in wallet
                'revenueType': 'deposit_fee'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.incomes.insert_one(income_entry)
        
        print(f'✅ Deposit fee recorded in both collections: ₦{safe_float(amount):,.2f} from {user_email}')
        
        return {
            'success': True,
            'revenue_id': income_entry['_id'],
            'corporate_revenue_id': corporate_revenue_entry['_id'],
            'amount': amount,
            'revenue_type': 'deposit_fee'
        }
        
    except Exception as e:
        print(f'❌ Error recording deposit fee: {str(e)}')
        raise

def _record_gateway_fee_expense(
    mongo,
    amount: float,
    user_id: ObjectId,
    user_email: str,
    transaction_id: Optional[ObjectId],
    metadata: Optional[Dict]
) -> Dict[str, Any]:
    """
    Record gateway fee expense (₦89.26 gap from analysis)
    Note: This is an EXPENSE, not revenue
    """
    try:
        # Extract metadata
        payment_amount = metadata.get('payment_amount', 0) if metadata else 0
        gateway_provider = metadata.get('gateway_provider', 'paystack') if metadata else 'paystack'
        fee_rate = metadata.get('fee_rate', 1.6) if metadata else 1.6  # 1.6% default for Paystack
        
        # Record expense (gateway fees are costs to business)
        expense_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': safe_float(amount),
            'category': 'Payment Processing Fees',
            'description': f'Gateway Fee - {gateway_provider.capitalize()} (₦{safe_float(payment_amount):,.2f} @ {fee_rate}%)',
            'date': datetime.utcnow(),
            'sourceType': 'gateway_fee',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'paymentTransactionId': str(transaction_id) if transaction_id else None,
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'paymentAmount': payment_amount,
                'gatewayProvider': gateway_provider,
                'feeRate': fee_rate,
                'automated': True,
                'doubleEntry': False,  # Cash already deducted by gateway
                'expenseType': 'gateway_fee'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.expenses.insert_one(expense_entry)
        
        print(f'✅ Gateway fee recorded: ₦{safe_float(amount):,.2f} from {gateway_provider}')
        
        return {
            'success': True,
            'expense_id': expense_entry['_id'],
            'amount': amount,
            'revenue_type': 'gateway_fee'  # Keep consistent interface
        }
        
    except Exception as e:
        print(f'❌ Error recording gateway fee: {str(e)}')
        raise


def _record_fc_credits_sale_revenue(
    mongo,
    amount: float,
    user_id: ObjectId,
    user_email: str,
    transaction_id: Optional[ObjectId],
    metadata: Optional[Dict]
) -> Dict[str, Any]:
    """
    Record FC Credits sale revenue - UPDATED to match treasury dashboard expectations
    
    CRITICAL: Treasury dashboard reads FC credits from corporate_revenue collection
    with type: 'CREDITS_PURCHASE'
    """
    try:
        # Extract metadata
        fc_amount = metadata.get('fc_amount', 0) if metadata else 0
        payment_reference = metadata.get('payment_reference', '') if metadata else ''
        gateway_fee = metadata.get('gateway_fee', 0) if metadata else 0
        net_revenue = amount - gateway_fee
        
        # CRITICAL FIX: Record in corporate_revenue collection to match treasury expectations
        corporate_revenue_entry = {
            '_id': ObjectId(),
            'userId': user_id,  # Customer user ID (not business)
            'amount': safe_float(amount),
            'type': 'CREDITS_PURCHASE',
            'description': f'FC Credits Sale - {fc_amount} FCs sold to {user_email} (₦{safe_float(amount):,.2f})',
            'gatewayFee': safe_float(gateway_fee),
            'netRevenue': safe_float(net_revenue),
            'metadata': {
                'fcPurchaseTransactionId': str(transaction_id) if transaction_id else None,
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'fcAmount': fc_amount,
                'paymentReference': payment_reference,
                'fcRate': 30.0,
                'automated': True,
                'revenueType': 'fc_credits_sale'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.corporate_revenue.insert_one(corporate_revenue_entry)
        
        # Also record in incomes collection for detailed business accounting
        income_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': safe_float(amount),
            'category': 'Service Revenue',
            'description': f'FC Credits Sale - {fc_amount} FCs sold to {user_email} (₦{safe_float(amount):,.2f})',
            'date': datetime.utcnow(),
            'sourceType': 'fc_credits_sale',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'fcPurchaseTransactionId': str(transaction_id) if transaction_id else None,
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'fcAmount': fc_amount,
                'paymentReference': payment_reference,
                'gatewayFee': gateway_fee,
                'netRevenue': net_revenue,
                'fcRate': 30.0,
                'automated': True,
                'doubleEntry': False,  # Cash already in account
                'revenueType': 'fc_credits_sale'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.incomes.insert_one(income_entry)
        
        print(f'✅ FC Credits sale recorded in both collections: ₦{safe_float(amount):,.2f} ({fc_amount} FCs) from {user_email}')
        
        return {
            'success': True,
            'revenue_id': income_entry['_id'],
            'corporate_revenue_id': corporate_revenue_entry['_id'],
            'amount': amount,
            'revenue_type': 'fc_credits_sale'
        }
        
    except Exception as e:
        print(f'❌ Error recording FC Credits sale: {str(e)}')
        raise


def _record_subscription_sale_revenue(
    mongo,
    amount: float,
    user_id: ObjectId,
    user_email: str,
    transaction_id: Optional[ObjectId],
    metadata: Optional[Dict]
) -> Dict[str, Any]:
    """
    Record subscription sale revenue - UPDATED to match treasury dashboard expectations
    
    CRITICAL: Treasury dashboard reads subscriptions from corporate_revenue collection
    with type: 'SUBSCRIPTION'
    """
    try:
        # Extract metadata
        plan_type = metadata.get('plan_type', 'UNKNOWN') if metadata else 'UNKNOWN'
        payment_reference = metadata.get('payment_reference', '') if metadata else ''
        gateway_fee = metadata.get('gateway_fee', 0) if metadata else 0
        subscription_id = metadata.get('subscription_id', None) if metadata else None
        net_revenue = amount - gateway_fee
        
        # CRITICAL FIX: Record in corporate_revenue collection to match treasury expectations
        corporate_revenue_entry = {
            '_id': ObjectId(),
            'userId': user_id,  # Customer user ID (not business)
            'amount': safe_float(amount),
            'type': 'SUBSCRIPTION',
            'description': f'Subscription Sale - {plan_type} plan sold to {user_email} (₦{safe_float(amount):,.2f})',
            'gatewayFee': safe_float(gateway_fee),
            'netRevenue': safe_float(net_revenue),
            'metadata': {
                'subscriptionPurchaseTransactionId': str(transaction_id) if transaction_id else None,
                'subscriptionId': str(subscription_id) if subscription_id else None,
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'planType': plan_type,
                'paymentReference': payment_reference,
                'automated': True,
                'revenueType': 'subscription_sale'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.corporate_revenue.insert_one(corporate_revenue_entry)
        
        # Also record in incomes collection for detailed business accounting
        income_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': safe_float(amount),
            'category': 'Service Revenue',
            'description': f'Subscription Sale - {plan_type} plan sold to {user_email} (₦{safe_float(amount):,.2f})',
            'date': datetime.utcnow(),
            'sourceType': 'subscription_sale',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'subscriptionPurchaseTransactionId': str(transaction_id) if transaction_id else None,
                'subscriptionId': str(subscription_id) if subscription_id else None,
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'planType': plan_type,
                'paymentReference': payment_reference,
                'gatewayFee': gateway_fee,
                'netRevenue': net_revenue,
                'automated': True,
                'doubleEntry': False,  # Cash already in account
                'revenueType': 'subscription_sale'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.incomes.insert_one(income_entry)
        
        print(f'✅ Subscription sale recorded in both collections: ₦{safe_float(amount):,.2f} ({plan_type}) from {user_email}')
        
        return {
            'success': True,
            'revenue_id': income_entry['_id'],
            'corporate_revenue_id': corporate_revenue_entry['_id'],
            'amount': amount,
            'revenue_type': 'subscription_sale'
        }
        
    except Exception as e:
        print(f'❌ Error recording subscription sale: {str(e)}')
        raise


# Validation and error handling functions
def validate_revenue_recording_inputs(
    revenue_type: str,
    amount: float,
    user_id: ObjectId,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Validate inputs for revenue recording
    """
    errors = []
    
    # Validate revenue type
    valid_types = ['vas_commission', 'deposit_fee', 'gateway_fee', 'fc_credits_sale', 'subscription_sale']
    if revenue_type not in valid_types:
        errors.append(f"Invalid revenue_type: {revenue_type}. Must be one of: {valid_types}")
    
    # Validate amount
    if not isinstance(amount, (int, float)) or amount <= 0:
        errors.append(f"Invalid amount: {amount}. Must be positive number")
    
    # Validate user_id
    if not isinstance(user_id, ObjectId):
        errors.append(f"Invalid user_id: {user_id}. Must be ObjectId")
    
    # Type-specific validations
    if revenue_type == 'vas_commission' and metadata:
        if not metadata.get('provider'):
            errors.append("VAS commission requires 'provider' in metadata")
        if not metadata.get('transaction_type'):
            errors.append("VAS commission requires 'transaction_type' in metadata")
    
    if revenue_type == 'deposit_fee' and metadata:
        if not metadata.get('deposit_amount'):
            errors.append("Deposit fee requires 'deposit_amount' in metadata")
    
    if revenue_type == 'gateway_fee' and metadata:
        if not metadata.get('payment_amount'):
            errors.append("Gateway fee requires 'payment_amount' in metadata")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors
    }


def get_revenue_recording_summary(mongo, start_date=None, end_date=None) -> Dict[str, Any]:
    """
    Get summary of revenue recordings for audit purposes
    """
    try:
        # Build date filter
        date_filter = {}
        if start_date or end_date:
            date_filter['date'] = {}
            if start_date:
                date_filter['date']['$gte'] = start_date
            if end_date:
                date_filter['date']['$lte'] = end_date
        
        # Query revenue entries
        revenue_filter = {
            'userId': BUSINESS_USER_ID,
            'sourceType': {'$in': ['vas_commission', 'deposit_fee', 'fc_credits_sale', 'subscription_sale']},
            'status': 'active',
            'isDeleted': False
        }
        revenue_filter.update(date_filter)
        
        revenue_entries = list(mongo.incomes.find(revenue_filter))
        
        # Query expense entries (gateway fees)
        expense_filter = {
            'userId': BUSINESS_USER_ID,
            'sourceType': 'gateway_fee',
            'status': 'active',
            'isDeleted': False
        }
        expense_filter.update(date_filter)
        
        expense_entries = list(mongo.expenses.find(expense_filter))
        
        # Summarize by type
        summary = {
            'vas_commission': {
                'count': len([e for e in revenue_entries if e['sourceType'] == 'vas_commission']),
                'total': sum(e['amount'] for e in revenue_entries if e['sourceType'] == 'vas_commission')
            },
            'deposit_fee': {
                'count': len([e for e in revenue_entries if e['sourceType'] == 'deposit_fee']),
                'total': sum(e['amount'] for e in revenue_entries if e['sourceType'] == 'deposit_fee')
            },
            'fc_credits_sale': {
                'count': len([e for e in revenue_entries if e['sourceType'] == 'fc_credits_sale']),
                'total': sum(e['amount'] for e in revenue_entries if e['sourceType'] == 'fc_credits_sale')
            },
            'subscription_sale': {
                'count': len([e for e in revenue_entries if e['sourceType'] == 'subscription_sale']),
                'total': sum(e['amount'] for e in revenue_entries if e['sourceType'] == 'subscription_sale')
            },
            'gateway_fee': {
                'count': len(expense_entries),
                'total': sum(e['amount'] for e in expense_entries)
            }
        }
        
        # Calculate totals
        total_revenue = sum(summary[key]['total'] for key in ['vas_commission', 'deposit_fee', 'fc_credits_sale', 'subscription_sale'])
        total_expenses = summary['gateway_fee']['total']
        net_revenue = total_revenue - total_expenses
        
        return {
            'success': True,
            'summary': summary,
            'totals': {
                'total_revenue': total_revenue,
                'total_expenses': total_expenses,
                'net_revenue': net_revenue
            },
            'period': {
                'start_date': start_date,
                'end_date': end_date
            }
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }