"""
CORRECTED Business Bookkeeping Functions
Fixes double-counting issues in consumption entries
"""

from datetime import datetime
from bson import ObjectId
from typing import Dict, Any, Optional

# Business account ID (ficoreafrica@gmail.com)
BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')

# FC Credit rate (₦30 per FC)
FC_RATE = 30.0


def record_fc_consumption_corrected(
    mongo,
    user_id: ObjectId,
    fc_amount: float,
    description: str,
    service: str
) -> Dict[str, ObjectId]:
    """
    CORRECTED: Record FC consumption WITHOUT double-counting revenue
    
    CRITICAL FIX: Consumption entries should ONLY reduce liabilities, NOT create revenue.
    Revenue was already recorded when:
    - Promotional FCs: Marketing expense created the liability (no revenue yet)
    - Paid FCs: Customer payment created the revenue (already recorded)
    
    This function ONLY records liability reduction (negative expense).
    
    Args:
        mongo: MongoDB connection
        user_id: User who spent FCs
        fc_amount: Number of FCs spent
        description: Human-readable description
        service: Service used (report_export, premium_feature, etc.)
    
    Returns:
        Dict with liability_reduction_id only (NO revenue_id)
    """
    try:
        # Calculate total value (₦30 per FC)
        naira_value = fc_amount * FC_RATE
        
        # Get user email for description
        user = mongo.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # ONLY record liability reduction (no revenue - that's the fix!)
        liability_reduction = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': -naira_value,  # Negative = liability reduction
            'category': 'Liability Adjustment',
            'description': f'FC Liability Reduction - {description} ({fc_amount} FCs consumed by {user_email})',
            'date': datetime.utcnow(),
            'sourceType': 'liability_adjustment_fc_consumption',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'fcAmount': fc_amount,
                'fcRate': FC_RATE,
                'service': service,
                'automated': True,
                'doubleEntry': False,  # Single entry - just liability reduction
                'correctedFunction': True  # Flag to identify corrected entries
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.expenses.insert_one(liability_reduction)
        
        print(f'✅ CORRECTED FC consumption: {fc_amount} FCs (₦{naira_value:,.2f}) - LIABILITY REDUCTION ONLY')
        print(f'   No revenue recorded (fixes double-counting)')
        
        return {
            'liability_reduction_id': liability_reduction['_id'],
            'amount': naira_value,
            'revenue_recorded': False  # Explicitly show no revenue
        }
        
    except Exception as e:
        print(f'❌ Error recording corrected FC consumption: {str(e)}')
        raise


def record_subscription_consumption_corrected(
    mongo,
    user_id: ObjectId,
    consumption_amount: float,
    description: str,
    service: str
) -> Dict[str, any]:
    """
    CORRECTED: Record subscription consumption WITHOUT double-counting revenue
    
    CRITICAL FIX: For promotional subscriptions, consumption should ONLY reduce 
    liabilities, NOT create additional revenue. Revenue was already recorded 
    when the subscription was granted (marketing expense + liability).
    
    Args:
        mongo: MongoDB connection
        user_id: User who consumed the service
        consumption_amount: Amount of service consumed (in Naira)
        description: Description of the service consumed
        service: Service type (vas_purchase, report_export, etc.)
    
    Returns:
        Dict with liability_reduction_id only (NO revenue_id)
    """
    try:
        # Get user details
        user = mongo.users.find_one({'_id': user_id})
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
        
        # ONLY record liability reduction (no revenue - that's the fix!)
        liability_reduction = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': -consumed_amount,  # Negative = liability reduction
            'category': 'Liability Adjustment',
            'description': f'Subscription Liability Reduction - {description} for {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'liability_adjustment_subscription',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'service': service,
                'consumedAmount': consumed_amount,
                'automated': True,
                'doubleEntry': False,  # Single entry - just liability reduction
                'correctedFunction': True  # Flag to identify corrected entries
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.expenses.insert_one(liability_reduction)
        
        print(f'✅ CORRECTED subscription consumption: ₦{consumed_amount:,.2f} - LIABILITY REDUCTION ONLY')
        print(f'   No revenue recorded (fixes double-counting)')
        
        return {
            'consumed_amount': consumed_amount,
            'liability_reduction_id': liability_reduction['_id'],
            'revenue_recorded': False  # Explicitly show no revenue
        }
        
    except Exception as e:
        print(f'❌ Error recording corrected subscription consumption: {str(e)}')
        raise


def consume_fee_waiver_liability_corrected(
    mongo,
    user_id: ObjectId,
    deposit_amount: float
) -> Dict[str, ObjectId]:
    """
    CORRECTED: Consume fee waiver liability WITHOUT double-counting revenue
    
    CRITICAL FIX: Fee waiver consumption should ONLY reduce liabilities, NOT 
    create additional revenue. Revenue was already recorded when the fee waiver 
    was granted (marketing expense + liability).
    
    Args:
        mongo: MongoDB connection
        user_id: User who made the deposit
        deposit_amount: Amount deposited (triggers consumption)
    
    Returns:
        Dict with liability_reduction_id only (NO revenue_id)
    """
    try:
        # Check if user has outstanding fee waiver liability
        fee_waiver_liabilities = list(mongo.incomes.find({
            'sourceType': 'fee_waiver_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'metadata.recipientUserId': str(user_id)
        }))
        
        if not fee_waiver_liabilities:
            print(f'ℹ️  No fee waiver liability found for user {user_id}')
            return {}
        
        # Get user email for description
        user = mongo.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # Calculate total outstanding liability
        total_liability = sum(l.get('amount', 0) for l in fee_waiver_liabilities)
        
        # Consume the liability (up to the amount available)
        consumption_amount = min(total_liability, 30.0)  # Fee waiver is ₦30
        
        # ONLY record liability reduction (no revenue - that's the fix!)
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
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'depositAmount': deposit_amount,
                'liabilityConsumed': consumption_amount,
                'automated': True,
                'doubleEntry': False,  # Single entry - just liability reduction
                'correctedFunction': True  # Flag to identify corrected entries
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.expenses.insert_one(liability_reduction)
        
        print(f'✅ CORRECTED fee waiver consumption: ₦{consumption_amount:,.2f} - LIABILITY REDUCTION ONLY')
        print(f'   No revenue recorded (fixes double-counting)')
        
        return {
            'liability_reduction_id': liability_reduction['_id'],
            'amount': consumption_amount,
            'revenue_recorded': False  # Explicitly show no revenue
        }
        
    except Exception as e:
        print(f'❌ Error consuming corrected fee waiver liability: {str(e)}')
        raise


def award_and_consume_fc_credits_atomic_corrected(
    mongo,
    user_id: ObjectId,
    fc_amount: float,
    operation: str,
    description: str,
    transaction_id: Optional[ObjectId] = None
) -> Dict[str, Any]:
    """
    CORRECTED ATOMIC FC CREDITS: Create liability and consume it WITHOUT double-counting
    
    CRITICAL FIX: The atomic pattern should be:
    1. Marketing Expense (Debit) - Cost to business
    2. FC Liability (Credit) - Obligation created
    3. Liability Reduction (Debit) - Obligation fulfilled
    
    NO REVENUE ENTRY - that would be double-counting since this is promotional.
    
    Args:
        mongo: MongoDB connection
        user_id: Recipient user ID
        fc_amount: Number of FCs to award
        operation: Operation type (signup_bonus, referral_bonus, etc.)
        description: Human-readable description
        transaction_id: Optional transaction ID for linking
    
    Returns:
        Dict with 3 transaction IDs (no revenue_id)
    """
    try:
        naira_value = fc_amount * FC_RATE
        print(f"🔄 CORRECTED ATOMIC FC CREDITS: {fc_amount} FCs (₦{naira_value}) for user {user_id}")
        
        # Get user email for description
        user = mongo.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
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
                'fcRate': FC_RATE,
                'nairaValue': naira_value,
                'automated': True,
                'correctedAtomic': True
            }
        }
        
        if transaction_id:
            credit_transaction['transactionId'] = transaction_id
        
        mongo.db.credit_transactions.insert_one(credit_transaction)
        
        # Update user's FC balance
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$inc': {'ficoreCreditBalance': fc_amount}}
        )
        
        # Step 2: Marketing Expense (Debit)
        expense_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': naira_value,
            'category': 'Marketing Ads and Promotion',
            'description': f'{description} ({fc_amount} FCs @ ₦{FC_RATE}/FC) for {user_email}',
            'date': datetime.utcnow(),
            'sourceType': f'marketing_expense_{operation}',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'recipientUserId': str(user_id),
                'recipientEmail': user_email,
                'fcAmount': fc_amount,
                'fcRate': FC_RATE,
                'operation': operation,
                'automated': True,
                'correctedAtomic': True
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.expenses.insert_one(expense_entry)
        
        # Step 3: FC Liability (Credit)
        liability_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': naira_value,
            'category': 'Deferred Revenue - FC Liability',
            'description': f'FC Liability Accrual - {description} for {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'fc_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'linkedExpenseId': str(expense_entry['_id']),
                'recipientUserId': str(user_id),
                'recipientEmail': user_email,
                'fcAmount': fc_amount,
                'fcRate': FC_RATE,
                'operation': operation,
                'automated': True,
                'correctedAtomic': True
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.incomes.insert_one(liability_entry)
        
        # Step 4: Liability Reduction (Debit) - Service provided immediately
        reduction_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': -naira_value,  # Negative = liability reduction
            'category': 'Liability Adjustment',
            'description': f'FC Liability Reduction - Service provided to {user_email}',
            'date': datetime.utcnow(),
            'sourceType': 'liability_adjustment_fc_credits',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'linkedLiabilityId': str(liability_entry['_id']),
                'recipientUserId': str(user_id),
                'recipientEmail': user_email,
                'fcAmount': fc_amount,
                'fcRate': FC_RATE,
                'operation': operation,
                'automated': True,
                'correctedAtomic': True
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.expenses.insert_one(reduction_entry)
        
        print(f'✅ CORRECTED ATOMIC FC CREDITS: 3 transactions created (NO revenue double-counting)')
        print(f'   Net cost to business: ₦{naira_value:,.2f}')
        
        return {
            'success': True,
            'fc_amount': fc_amount,
            'naira_value': naira_value,
            'net_cost': naira_value,  # Actual cost to business
            'transactions': {
                'credit_transaction_id': credit_transaction['_id'],
                'marketing_expense_id': expense_entry['_id'],
                'liability_creation_id': liability_entry['_id'],
                'liability_reduction_id': reduction_entry['_id']
                # NO revenue_id - that's the fix!
            }
        }
        
    except Exception as e:
        print(f"❌ Error in corrected atomic FC credits: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def calculate_user_subscription_liabilities(mongo, user_id: ObjectId) -> float:
    """
    Calculate total outstanding subscription liabilities for a specific user
    """
    try:
        # Get all subscription liability accruals for this user
        liability_accruals = list(mongo.incomes.find({
            'sourceType': 'subscription_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'metadata.recipientUserId': str(user_id)
        }))
        
        # Get all subscription liability reductions for this user
        liability_reductions = list(mongo.expenses.find({
            'sourceType': 'liability_adjustment_subscription',
            'status': 'active',
            'isDeleted': False,
            'metadata.customerUserId': str(user_id)
        }))
        
        # Calculate net liability
        total_accrued = sum(l.get('amount', 0) for l in liability_accruals)
        total_reduced = sum(abs(r.get('amount', 0)) for r in liability_reductions)
        net_liability = total_accrued - total_reduced
        
        return max(0, net_liability)  # Can't be negative
        
    except Exception as e:
        print(f'❌ Error calculating subscription liabilities: {str(e)}')
        return 0.0