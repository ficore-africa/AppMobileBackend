"""
Gateway Fee Accounting - Proper Accounting for Payment Gateway Fees
Integrates with business_bookkeeping.py to record gateway fees as business expenses

This module ensures that gateway fees (Paystack, Monnify) are properly recorded
as business expenses, giving accurate net revenue calculations.
"""

from datetime import datetime, timedelta
from bson import ObjectId
from typing import Dict, Any, Optional
from utils.gateway_fee_calculator import GatewayFeeCalculator


# Business User ID (from business_bookkeeping.py)
BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')


def record_gateway_fee_expense(
    mongo,
    transaction_id: ObjectId,
    user_id: ObjectId,
    provider: str,
    transaction_type: str,
    gross_amount: float,
    gateway_fee: float,
    payment_reference: str = None,
    description_context: str = None
) -> ObjectId:
    """
    Record gateway fee as business expense
    
    This creates the "missing piece" in your accounting - the gateway fee expense
    that reduces your net revenue to match your actual bank deposits.
    
    Args:
        mongo: MongoDB connection
        transaction_id: Related transaction ID (FC purchase, subscription, etc.)
        user_id: Customer user ID
        provider: Gateway provider (paystack, monnify)
        transaction_type: Type of transaction (fc_purchase, subscription, vas)
        gross_amount: Gross transaction amount
        gateway_fee: Fee charged by gateway
        payment_reference: Payment reference from gateway
        description_context: Additional context for description
        
    Returns:
        ObjectId of created expense entry
    """
    try:
        # Get user email for description
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'Unknown') if user else 'Unknown'
        
        # Calculate fee percentage
        fee_percentage = (gateway_fee / gross_amount * 100) if gross_amount > 0 else 0
        
        # Create descriptive context
        if description_context:
            context = f" - {description_context}"
        else:
            context = ""
        
        # Record gateway fee as business expense
        expense_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': gateway_fee,
            'category': 'Payment Processing Fees',  # New category for gateway fees
            'description': f'{provider.capitalize()} Gateway Fee - {transaction_type.replace("_", " ").title()}{context} (₦{gross_amount:,.2f} @ {fee_percentage:.2f}%)',
            'date': datetime.utcnow(),
            'sourceType': f'gateway_fee_{provider}',
            'status': 'active',
            'isDeleted': False,
            'metadata': {
                'relatedTransactionId': str(transaction_id),
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'provider': provider,
                'transactionType': transaction_type,
                'grossAmount': gross_amount,
                'gatewayFee': gateway_fee,
                'feePercentage': fee_percentage,
                'paymentReference': payment_reference,
                'automated': True,
                'doubleEntry': False,  # Single entry - reduces cash/revenue
                'accountingModel': 'expense'
            },
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        mongo.db.expenses.insert_one(expense_entry)
        
        print(f'✅ Recorded gateway fee expense: ₦{gateway_fee:,.2f} ({provider} {fee_percentage:.2f}%)')
        
        return expense_entry['_id']
        
    except Exception as e:
        print(f'❌ Error recording gateway fee expense: {str(e)}')
        raise


def record_fc_purchase_with_gateway_fees(
    mongo,
    user_id: ObjectId,
    fc_amount: float,
    naira_amount: float,
    payment_reference: str,
    paystack_transaction_id: str = None,
    payment_method: str = 'paystack'
) -> Dict[str, Any]:
    """
    Enhanced FC purchase recording with proper gateway fee accounting
    
    This replaces the existing record_paid_fc_purchase_revenue function
    with proper gateway fee expense recording.
    
    INCLUDES IDEMPOTENCY CHECK: Prevents duplicate processing of same payment
    
    Creates 4 transactions:
    1. Cash/Bank Increase (Asset increase from payment received)
    2. Gateway Fee Expense (Business expense for Paystack fee)
    3. FC Liability Creation (Obligation to provide FC Credits service)
    4. Revenue Recognition (Service revenue earned)
    
    Args:
        mongo: MongoDB connection
        user_id: Customer user ID
        fc_amount: Number of FCs purchased
        naira_amount: Amount paid in Naira
        payment_reference: Paystack payment reference
        paystack_transaction_id: Paystack transaction ID
        payment_method: Payment method (default: paystack)
    
    Returns:
        Dict with transaction IDs and success status
    """
    try:
        print(f"💰 FC PURCHASE WITH FEES: Recording {fc_amount} FCs (₦{naira_amount}) from user {user_id}")
        
        # IDEMPOTENCY CHECK: Prevent duplicate processing
        existing_transaction = mongo.db.incomes.find_one({
            'userId': BUSINESS_USER_ID,
            'sourceType': 'fc_purchase_payment_received',
            'metadata.paymentReference': payment_reference,
            'status': 'active'
        })
        
        if existing_transaction:
            print(f"⚠️  IDEMPOTENCY: Payment {payment_reference} already processed")
            print(f"   Existing transaction ID: {existing_transaction['_id']}")
            return {
                'success': True,
                'duplicate': True,
                'message': 'Payment already processed (idempotency check)',
                'existing_transaction_id': existing_transaction['_id'],
                'payment_reference': payment_reference
            }
        
        # Calculate fees using centralized calculator
        fee_calc = GatewayFeeCalculator.calculate_fc_purchase_fees(fc_amount, naira_amount)
        gateway_fee = fee_calc['gateway_fee']
        net_revenue = fee_calc['net_revenue']
        
        # Get user email for descriptions
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'unknown@example.com') if user else 'unknown@example.com'
        
        # Transaction 1: Cash/Bank Increase (Asset increase from payment received)
        cash_increase_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': naira_amount,
            'category': 'Corporate Revenue',
            'description': f'FC Credits Purchase Payment - {fc_amount} FCs by {user_email}',
            'sourceType': 'fc_purchase_payment_received',
            'status': 'active',
            'isDeleted': False,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'fcAmount': fc_amount,
                'nairaAmount': naira_amount,
                'paymentReference': payment_reference,
                'paystackTransactionId': paystack_transaction_id,
                'paymentMethod': payment_method,
                'gatewayFee': gateway_fee,
                'netRevenue': net_revenue,
                'fcRate': 30.0,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'revenue_with_fees',
                'transactionType': 'cash_increase'
            }
        }
        
        mongo.db.incomes.insert_one(cash_increase_entry)
        print(f"✅ Cash increase recorded: ₦{naira_amount} (ID: {cash_increase_entry['_id']})")
        
        # Transaction 2: Gateway Fee Expense using unified system
        from utils.unified_corporate_revenue import record_corporate_revenue_automatically
        gateway_fee_result = record_corporate_revenue_automatically(
            mongo=mongo,
            revenue_type='gateway_fee',
            amount=gateway_fee,
            user_id=user_id,
            transaction_id=cash_increase_entry['_id'],
            metadata={
                'payment_amount': naira_amount,
                'gateway_provider': 'paystack',
                'fee_rate': 1.6,
                'payment_reference': payment_reference
            }
        )
        
        # Transaction 3: FC Liability Creation (Obligation to provide FC Credits service)
        fc_liability_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': fc_amount * 30.0,  # Store liability in Naira equivalent
            'category': 'Deferred Revenue - FC Liability',
            'description': f'FC Credits Liability - {fc_amount} FCs purchased by {user_email}',
            'sourceType': 'fc_purchase_liability_creation',
            'status': 'active',
            'isDeleted': False,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'fcAmount': fc_amount,
                'nairaAmount': naira_amount,
                'paymentReference': payment_reference,
                'paystackTransactionId': paystack_transaction_id,
                'fcRate': 30.0,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'revenue_with_fees',
                'transactionType': 'liability_creation',
                'linkedCashIncreaseId': str(cash_increase_entry['_id']),
                'linkedGatewayFeeId': str(gateway_fee_expense_id)
            }
        }
        
        mongo.db.incomes.insert_one(fc_liability_entry)
        print(f"✅ FC liability created: {fc_amount} FCs (₦{fc_amount * 30.0}) (ID: {fc_liability_entry['_id']})")
        
        # Transaction 4: Revenue Recognition (Service revenue earned immediately)
        revenue_recognition_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': naira_amount,
            'category': 'Corporate Revenue',
            'description': f'FC Credits Revenue Recognition - {fc_amount} FCs sold to {user_email}',
            'sourceType': 'fc_purchase_revenue_recognition',
            'status': 'active',
            'isDeleted': False,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'fcAmount': fc_amount,
                'nairaAmount': naira_amount,
                'paymentReference': payment_reference,
                'paystackTransactionId': paystack_transaction_id,
                'gatewayFee': gateway_fee,
                'netRevenue': net_revenue,
                'fcRate': 30.0,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'revenue_with_fees',
                'transactionType': 'revenue_recognition',
                'linkedCashIncreaseId': str(cash_increase_entry['_id']),
                'linkedLiabilityId': str(fc_liability_entry['_id']),
                'linkedGatewayFeeId': str(gateway_fee_expense_id)
            }
        }
        
        mongo.db.incomes.insert_one(revenue_recognition_entry)
        print(f"✅ Revenue recognized: ₦{naira_amount} (net: ₦{net_revenue}) (ID: {revenue_recognition_entry['_id']})")
        
        return {
            'success': True,
            'fc_amount': fc_amount,
            'gross_revenue': naira_amount,
            'gateway_fee': gateway_fee,
            'net_revenue': net_revenue,
            'transactions': {
                'cash_increase_id': cash_increase_entry['_id'],
                'gateway_fee_expense_id': gateway_fee_expense_id,
                'liability_creation_id': fc_liability_entry['_id'],
                'revenue_recognition_id': revenue_recognition_entry['_id']
            },
            'metadata': {
                'customerUserId': str(user_id),
                'paymentReference': payment_reference,
                'paystackTransactionId': paystack_transaction_id,
                'accountingModel': 'revenue_with_fees'
            }
        }
        
    except Exception as e:
        print(f"❌ Error recording FC purchase with gateway fees: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def record_subscription_purchase_with_gateway_fees(
    mongo,
    user_id: ObjectId,
    subscription_amount: float,
    plan_type: str,
    plan_name: str,
    duration_days: int,
    payment_reference: str,
    paystack_transaction_id: str = None,
    payment_method: str = 'paystack'
) -> Dict[str, Any]:
    """
    Enhanced subscription purchase recording with proper gateway fee accounting
    
    Creates 4 transactions:
    1. Cash/Bank Increase (Asset increase from payment received)
    2. Gateway Fee Expense (Business expense for Paystack fee)
    3. Subscription Liability Creation (Obligation to provide subscription service)
    4. Revenue Recognition (Service revenue earned)
    
    Args:
        mongo: MongoDB connection
        user_id: Customer user ID
        subscription_amount: Amount paid in Naira
        plan_type: Plan type (monthly, annual)
        plan_name: Plan name (e.g., "Premium Monthly")
        duration_days: Subscription duration in days
        payment_reference: Paystack payment reference
        paystack_transaction_id: Paystack transaction ID
        payment_method: Payment method (default: paystack)
    
    Returns:
        Dict with transaction IDs and success status
    """
    try:
        print(f"💰 SUBSCRIPTION WITH FEES: Recording {plan_name} (₦{subscription_amount}) from user {user_id}")
        
        # IDEMPOTENCY CHECK: Prevent duplicate processing
        existing_transaction = mongo.db.incomes.find_one({
            'userId': BUSINESS_USER_ID,
            'sourceType': 'subscription_purchase_payment_received',
            'metadata.paymentReference': payment_reference,
            'status': 'active'
        })
        
        if existing_transaction:
            print(f"⚠️  IDEMPOTENCY: Payment {payment_reference} already processed")
            print(f"   Existing transaction ID: {existing_transaction['_id']}")
            return {
                'success': True,
                'duplicate': True,
                'message': 'Payment already processed (idempotency check)',
                'existing_transaction_id': existing_transaction['_id'],
                'payment_reference': payment_reference
            }
        
        # Calculate fees using centralized calculator
        fee_calc = GatewayFeeCalculator.calculate_subscription_fees(subscription_amount)
        gateway_fee = fee_calc['gateway_fee']
        net_revenue = fee_calc['net_revenue']
        
        # Get user email for descriptions
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'unknown@example.com') if user else 'unknown@example.com'
        
        # Transaction 1: Cash/Bank Increase (Asset increase from payment received)
        cash_increase_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': subscription_amount,
            'category': 'Corporate Revenue',
            'description': f'Subscription Payment - {plan_name} by {user_email}',
            'sourceType': 'subscription_purchase_payment_received',
            'status': 'active',
            'isDeleted': False,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'subscriptionAmount': subscription_amount,
                'planType': plan_type,
                'planName': plan_name,
                'durationDays': duration_days,
                'paymentReference': payment_reference,
                'paystackTransactionId': paystack_transaction_id,
                'paymentMethod': payment_method,
                'gatewayFee': gateway_fee,
                'netRevenue': net_revenue,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'revenue_with_fees',
                'transactionType': 'cash_increase'
            }
        }
        
        mongo.db.incomes.insert_one(cash_increase_entry)
        print(f"✅ Cash increase recorded: ₦{subscription_amount} (ID: {cash_increase_entry['_id']})")
        
        # Transaction 2: Gateway Fee Expense using unified system
        from utils.unified_corporate_revenue import record_corporate_revenue_automatically
        gateway_fee_result = record_corporate_revenue_automatically(
            mongo=mongo,
            revenue_type='gateway_fee',
            amount=gateway_fee,
            user_id=user_id,
            transaction_id=cash_increase_entry['_id'],
            metadata={
                'payment_amount': subscription_amount,
                'gateway_provider': 'paystack',
                'fee_rate': 1.6,
                'payment_reference': payment_reference
            }
        )
        
        # Transaction 3: Subscription Liability Creation (Obligation to provide subscription service)
        subscription_liability_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': subscription_amount,
            'category': 'Deferred Revenue - Subscription Liability',
            'description': f'Subscription Liability - {plan_name} purchased by {user_email}',
            'sourceType': 'subscription_purchase_liability_creation',
            'status': 'active',
            'isDeleted': False,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'subscriptionAmount': subscription_amount,
                'planType': plan_type,
                'planName': plan_name,
                'durationDays': duration_days,
                'paymentReference': payment_reference,
                'paystackTransactionId': paystack_transaction_id,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'revenue_with_fees',
                'transactionType': 'liability_creation',
                'linkedCashIncreaseId': str(cash_increase_entry['_id']),
                'linkedGatewayFeeId': str(gateway_fee_expense_id)
            }
        }
        
        mongo.db.incomes.insert_one(subscription_liability_entry)
        print(f"✅ Subscription liability created: ₦{subscription_amount} (ID: {subscription_liability_entry['_id']})")
        
        # Transaction 4: DEFERRED REVENUE RECOGNITION (ICAN/SBR Compliant)
        # For subscriptions, we should NOT recognize all revenue immediately
        # Instead, recognize only the first month/period and defer the rest
        
        # Calculate daily revenue rate for proper accrual
        daily_revenue_rate = subscription_amount / duration_days if duration_days > 0 else subscription_amount
        
        # For monthly plans: recognize 30 days immediately
        # For annual plans: recognize 30 days immediately, defer the rest
        if plan_type.lower() == 'monthly' or duration_days <= 30:
            # Monthly plan: recognize full amount immediately
            immediate_revenue = subscription_amount
            deferred_revenue = 0
        else:
            # Annual/longer plans: recognize first 30 days, defer the rest
            immediate_revenue = daily_revenue_rate * 30  # First month
            deferred_revenue = subscription_amount - immediate_revenue
        
        # Only create revenue recognition for the immediate portion
        if immediate_revenue > 0:
            revenue_recognition_entry = {
                '_id': ObjectId(),
                'userId': BUSINESS_USER_ID,
                'amount': immediate_revenue,
                'category': 'Corporate Revenue',
                'description': f'Subscription Revenue Recognition (Month 1) - {plan_name} sold to {user_email}',
                'sourceType': 'subscription_purchase_revenue_recognition',
                'status': 'active',
                'isDeleted': False,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
                'metadata': {
                    'customerUserId': str(user_id),
                    'customerEmail': user_email,
                    'subscriptionAmount': subscription_amount,
                    'immediateRevenue': immediate_revenue,
                    'deferredRevenue': deferred_revenue,
                    'dailyRevenueRate': daily_revenue_rate,
                    'planType': plan_type,
                    'planName': plan_name,
                    'durationDays': duration_days,
                    'paymentReference': payment_reference,
                    'paystackTransactionId': paystack_transaction_id,
                    'gatewayFee': gateway_fee,
                    'netRevenue': net_revenue,
                    'automated': True,
                    'doubleEntry': True,
                    'accountingModel': 'deferred_revenue_accrual',
                    'transactionType': 'immediate_revenue_recognition',
                    'linkedCashIncreaseId': str(cash_increase_entry['_id']),
                    'linkedLiabilityId': str(subscription_liability_entry['_id']),
                    'linkedGatewayFeeId': str(gateway_fee_expense_id)
                }
            }
            
            mongo.db.incomes.insert_one(revenue_recognition_entry)
            print(f"✅ Immediate revenue recognized: ₦{immediate_revenue:,.2f} (Month 1 of {duration_days} days) (ID: {revenue_recognition_entry['_id']})")
            
            if deferred_revenue > 0:
                print(f"📅 Deferred revenue: ₦{deferred_revenue:,.2f} (to be recognized over {duration_days - 30} days)")
                print(f"📊 Daily accrual rate: ₦{daily_revenue_rate:,.2f}/day")
        else:
            revenue_recognition_entry = None
            print("⚠️  No immediate revenue recognition (zero-day subscription)")
        
        return {
            'success': True,
            'subscription_amount': subscription_amount,
            'gross_revenue': subscription_amount,
            'gateway_fee': gateway_fee,
            'net_revenue': net_revenue,
            'immediate_revenue': immediate_revenue if 'immediate_revenue' in locals() else subscription_amount,
            'deferred_revenue': deferred_revenue if 'deferred_revenue' in locals() else 0,
            'daily_revenue_rate': daily_revenue_rate if 'daily_revenue_rate' in locals() else 0,
            'plan_type': plan_type,
            'plan_name': plan_name,
            'duration_days': duration_days,
            'transactions': {
                'cash_increase_id': cash_increase_entry['_id'],
                'gateway_fee_expense_id': gateway_fee_expense_id,
                'liability_creation_id': subscription_liability_entry['_id'],
                'revenue_recognition_id': revenue_recognition_entry['_id'] if revenue_recognition_entry else None
            },
            'accrual_info': {
                'requires_daily_accrual': deferred_revenue > 0 if 'deferred_revenue' in locals() else False,
                'accrual_start_date': datetime.utcnow() + timedelta(days=30) if 'deferred_revenue' in locals() and deferred_revenue > 0 else None,
                'accrual_end_date': datetime.utcnow() + timedelta(days=duration_days) if duration_days > 30 else None
            },
            'metadata': {
                'customerUserId': str(user_id),
                'paymentReference': payment_reference,
                'paystackTransactionId': paystack_transaction_id,
                'accountingModel': 'deferred_revenue_accrual'
            }
        }
        
    except Exception as e:
        print(f"❌ Error recording subscription purchase with gateway fees: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def record_vas_transaction_with_fees(
    mongo,
    transaction_id: ObjectId,
    user_id: ObjectId,
    provider: str,
    transaction_type: str,
    amount: float,
    commission: float,
    gateway_fee: float = None
) -> Dict[str, ObjectId]:
    """
    Enhanced VAS transaction recording - CORRECTED VERSION
    
    CRITICAL CORRECTION: VAS providers (Monnify, Peyflex) PAY US commissions.
    We do NOT pay gateway fees on VAS transactions.
    Gateway fees only apply to wallet deposits and Paystack transactions.
    
    Creates 1 transaction:
    1. VAS Commission Revenue (what we earn from provider)
    
    Args:
        mongo: MongoDB connection
        transaction_id: VAS transaction ID
        user_id: Customer user ID
        provider: Provider name (monnify, peyflex)
        transaction_type: Transaction type (AIRTIME, DATA, BILL)
        amount: Transaction amount
        commission: Commission earned from provider
        gateway_fee: NOT APPLICABLE for VAS transactions (ignored)
        
    Returns:
        Dict with commission transaction ID only
    """
    try:
        # Record VAS commission revenue using unified system
        from utils.unified_corporate_revenue import record_corporate_revenue_automatically
        commission_result = record_corporate_revenue_automatically(
            mongo=mongo,
            revenue_type='vas_commission',
            amount=commission,
            user_id=user_id,
            transaction_id=transaction_id,
            metadata={
                'provider': provider,
                'transaction_type': transaction_type,
                'transaction_amount': amount
            }
        )
        
        # NO gateway fee expense for VAS transactions
        # VAS providers PAY US, we don't pay them
        
        print(f'✅ VAS transaction recorded via unified system: Commission ₦{commission:,.2f} (NO gateway fees on VAS)')
        
        return {
            'commission_revenue_id': commission_result.get('revenue_id'),
            'gateway_fee_expense_id': None  # No gateway fees on VAS
        }
        
    except Exception as e:
        print(f'❌ Error recording VAS transaction: {str(e)}')
        raise


def record_wallet_deposit_atomic(
    mongo,
    user_id: ObjectId,
    deposit_amount: float,
    monnify_reference: str,
    deposit_method: str = 'bank_transfer',
    service_fee: float = 30.0
) -> Dict[str, Any]:
    """
    ATOMIC WALLET DEPOSIT: Proper double-entry bookkeeping for wallet deposits
    
    To maintain a balanced ledger, this function creates:
    - Dr. Cash: +₦4,917.50 (Net amount received after Monnify's 1.65% fee)
    - Dr. Gateway Expense: +₦82.50 (The Monnify fee we pay)
    - Cr. User Liability: +₦5,000.00 (Full amount user expects in wallet)
    - Plus ₦30 in-app service fee handling
    
    Example for ₦5,000 deposit:
    - User pays: ₦5,030 (₦5,000 + ₦30 service fee)
    - Monnify charges us: ₦82.50 (1.65% of ₦5,000)
    - We receive net: ₦4,917.50
    - User gets: ₦5,000 in wallet
    - Our service fee: ₦30
    
    Args:
        mongo: MongoDB connection
        user_id: User making deposit
        deposit_amount: Amount user wants in wallet (before service fee)
        monnify_reference: Monnify transaction reference
        deposit_method: Deposit method (bank_transfer, card, etc.)
        service_fee: Our service fee (default ₦30)
        
    Returns:
        Dict with all transaction IDs and accounting details
    """
    try:
        print(f"💰 ATOMIC WALLET DEPOSIT: Recording ₦{deposit_amount} deposit from user {user_id}")
        
        # Calculate fees
        fee_calc = GatewayFeeCalculator.calculate_wallet_deposit_fees(deposit_amount)
        gateway_fee = fee_calc['gateway_fee']  # What Monnify charges us
        net_cash_received = fee_calc['net_received']  # What we actually receive
        
        # Total user paid = deposit_amount + service_fee
        total_user_paid = deposit_amount + service_fee
        
        # Get user email for descriptions
        user = mongo.db.users.find_one({'_id': user_id})
        user_email = user.get('email', 'unknown@example.com') if user else 'unknown@example.com'
        
        print(f"   User paid total: ₦{total_user_paid:,.2f}")
        print(f"   Monnify fee: ₦{gateway_fee:,.2f}")
        print(f"   Net cash received: ₦{net_cash_received:,.2f}")
        print(f"   User wallet credit: ₦{deposit_amount:,.2f}")
        print(f"   Service fee earned: ₦{service_fee:,.2f}")
        
        # Transaction 1: Dr. Cash (Total cash received including service fee)
        total_cash_received = net_cash_received + service_fee
        cash_received_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': total_cash_received,
            'category': 'Cash and Bank',
            'description': f'Wallet Deposit Cash Received (Total) - ₦{deposit_amount:,.2f} + ₦{service_fee:,.2f} fee by {user_email}',
            'sourceType': 'wallet_deposit_cash_received',
            'status': 'active',
            'isDeleted': False,
            'date': datetime.utcnow(),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'depositAmount': deposit_amount,
                'totalUserPaid': total_user_paid,
                'serviceFee': service_fee,
                'gatewayFee': gateway_fee,
                'netCashReceived': net_cash_received,
                'totalCashReceived': total_cash_received,
                'monnifyReference': monnify_reference,
                'depositMethod': deposit_method,
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'atomic_wallet_deposit',
                'transactionType': 'cash_debit'
            }
        }
        
        mongo.db.incomes.insert_one(cash_received_entry)
        print(f"✅ Total cash received recorded: ₦{total_cash_received:,.2f} (Net: ₦{net_cash_received:,.2f} + Fee: ₦{service_fee:,.2f}) (ID: {cash_received_entry['_id']})")
        
        # Transaction 2: Dr. Gateway Expense (The "tax" on the deposit)
        gateway_expense_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': gateway_fee,
            'category': 'Payment Processing Fees',
            'description': f'Monnify Deposit Fee - ₦{deposit_amount:,.2f} deposit by {user_email} ({fee_calc["fee_percentage"]:.2f}%)',
            'sourceType': 'gateway_fee_monnify_deposit',
            'status': 'active',
            'isDeleted': False,
            'date': datetime.utcnow(),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'depositAmount': deposit_amount,
                'gatewayFee': gateway_fee,
                'feePercentage': fee_calc['fee_percentage'],
                'provider': 'monnify',
                'monnifyReference': monnify_reference,
                'relatedCashEntryId': str(cash_received_entry['_id']),
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'atomic_wallet_deposit',
                'transactionType': 'gateway_expense_debit'
            }
        }
        
        mongo.db.expenses.insert_one(gateway_expense_entry)
        print(f"✅ Gateway expense recorded: ₦{gateway_fee:,.2f} (ID: {gateway_expense_entry['_id']})")
        
        # Transaction 3: Cr. User Liability (Full amount user expects in wallet)
        user_liability_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': deposit_amount,
            'category': 'Deferred Revenue - Wallet Liability',
            'description': f'Wallet Liability - ₦{deposit_amount:,.2f} credited to {user_email}',
            'sourceType': 'wallet_deposit_user_liability',
            'status': 'active',
            'isDeleted': False,
            'date': datetime.utcnow(),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'depositAmount': deposit_amount,
                'walletCreditAmount': deposit_amount,
                'monnifyReference': monnify_reference,
                'relatedCashEntryId': str(cash_received_entry['_id']),
                'relatedGatewayExpenseId': str(gateway_expense_entry['_id']),
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'atomic_wallet_deposit',
                'transactionType': 'user_liability_credit'
            }
        }
        
        mongo.db.incomes.insert_one(user_liability_entry)
        print(f"✅ User liability recorded: ₦{deposit_amount:,.2f} (ID: {user_liability_entry['_id']})")
        
        # Transaction 4: Corporate Revenue (Our ₦30 service fee)
        service_fee_entry = {
            '_id': ObjectId(),
            'userId': BUSINESS_USER_ID,
            'amount': service_fee,
            'category': 'Corporate Revenue',
            'description': f'Wallet Deposit Service Fee - ₦{deposit_amount:,.2f} deposit by {user_email}',
            'sourceType': 'wallet_deposit_service_fee',
            'status': 'active',
            'isDeleted': False,
            'date': datetime.utcnow(),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'metadata': {
                'customerUserId': str(user_id),
                'customerEmail': user_email,
                'depositAmount': deposit_amount,
                'serviceFee': service_fee,
                'totalUserPaid': total_user_paid,
                'monnifyReference': monnify_reference,
                'relatedCashEntryId': str(cash_received_entry['_id']),
                'relatedLiabilityId': str(user_liability_entry['_id']),
                'automated': True,
                'doubleEntry': True,
                'accountingModel': 'atomic_wallet_deposit',
                'transactionType': 'service_fee_credit'
            }
        }
        
        mongo.db.incomes.insert_one(service_fee_entry)
        print(f"✅ Service fee recorded: ₦{service_fee:,.2f} (ID: {service_fee_entry['_id']})")
        
        # Verify double-entry balance
        total_debits = total_cash_received + gateway_fee  # Cash + Gateway Expense
        total_credits = deposit_amount + service_fee      # User Liability + Service Fee
        
        print(f"   Double-entry verification:")
        print(f"   Total Debits: ₦{total_debits:,.2f} (Cash: ₦{total_cash_received:,.2f} + Gateway: ₦{gateway_fee:,.2f})")
        print(f"   Total Credits: ₦{total_credits:,.2f} (Liability: ₦{deposit_amount:,.2f} + Service: ₦{service_fee:,.2f})")
        print(f"   Balanced: {'✅' if abs(total_debits - total_credits) < 0.01 else '❌'}")
        
        return {
            'success': True,
            'deposit_amount': deposit_amount,
            'total_user_paid': total_user_paid,
            'service_fee': service_fee,
            'gateway_fee': gateway_fee,
            'net_cash_received': net_cash_received,
            'total_cash_received': total_cash_received,
            'double_entry_balanced': abs(total_debits - total_credits) < 0.01,
            'transactions': {
                'cash_received_id': cash_received_entry['_id'],
                'gateway_expense_id': gateway_expense_entry['_id'],
                'user_liability_id': user_liability_entry['_id'],
                'service_fee_id': service_fee_entry['_id']
            },
            'accounting_summary': {
                'total_debits': total_debits,
                'total_credits': total_credits,
                'net_business_impact': service_fee - gateway_fee,  # Our actual profit/loss
                'cash_flow_impact': total_cash_received  # Total cash we receive
            },
            'metadata': {
                'customerUserId': str(user_id),
                'monnifyReference': monnify_reference,
                'accountingModel': 'atomic_wallet_deposit'
            }
        }
        
    except Exception as e:
        print(f"❌ Error recording atomic wallet deposit: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


# Utility functions for treasury dashboard integration
def get_total_gateway_fees(mongo, start_date=None, end_date=None) -> Dict[str, float]:
    """
    Get total gateway fees by provider for treasury dashboard
    
    Args:
        mongo: MongoDB connection
        start_date: Start date filter (optional)
        end_date: End date filter (optional)
        
    Returns:
        Dict with gateway fees by provider
    """
    try:
        # Build query filter
        query_filter = {
            'userId': BUSINESS_USER_ID,
            'category': 'Payment Processing Fees',
            'status': 'active'
        }
        
        if start_date and end_date:
            query_filter['date'] = {'$gte': start_date, '$lte': end_date}
        
        # Aggregate by provider
        pipeline = [
            {'$match': query_filter},
            {'$group': {
                '_id': '$metadata.provider',
                'total_fees': {'$sum': '$amount'},
                'transaction_count': {'$sum': 1}
            }}
        ]
        
        results = list(mongo.db.expenses.aggregate(pipeline))
        
        # Format results
        gateway_fees = {}
        total_fees = 0
        
        for result in results:
            provider = result['_id'] or 'unknown'
            fees = result['total_fees']
            count = result['transaction_count']
            
            gateway_fees[provider] = {
                'total_fees': fees,
                'transaction_count': count,
                'average_fee': fees / count if count > 0 else 0
            }
            total_fees += fees
        
        gateway_fees['total'] = total_fees
        
        return gateway_fees
        
    except Exception as e:
        print(f'❌ Error getting gateway fees: {str(e)}')
        return {'total': 0}


def get_net_revenue_summary(mongo, start_date=None, end_date=None) -> Dict[str, float]:
    """
    Get net revenue summary (gross revenue - gateway fees) for treasury dashboard
    
    Args:
        mongo: MongoDB connection
        start_date: Start date filter (optional)
        end_date: End date filter (optional)
        
    Returns:
        Dict with gross revenue, gateway fees, and net revenue
    """
    try:
        # Build date filter
        date_filter = {}
        if start_date and end_date:
            date_filter = {'date': {'$gte': start_date, '$lte': end_date}}
        
        # Get gross revenue (all corporate revenue)
        revenue_query = {
            'userId': BUSINESS_USER_ID,
            'category': 'Corporate Revenue',
            'status': 'active',
            **date_filter
        }
        
        gross_revenue = mongo.db.incomes.aggregate([
            {'$match': revenue_query},
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
        ])
        gross_revenue = list(gross_revenue)
        gross_revenue = gross_revenue[0]['total'] if gross_revenue else 0
        
        # Get gateway fees
        gateway_fees_data = get_total_gateway_fees(mongo, start_date, end_date)
        total_gateway_fees = gateway_fees_data.get('total', 0)
        
        # Calculate net revenue
        net_revenue = gross_revenue - total_gateway_fees
        
        return {
            'gross_revenue': gross_revenue,
            'gateway_fees': total_gateway_fees,
            'net_revenue': net_revenue,
            'gateway_fee_percentage': (total_gateway_fees / gross_revenue * 100) if gross_revenue > 0 else 0,
            'gateway_fees_by_provider': {
                k: v for k, v in gateway_fees_data.items() if k != 'total'
            }
        }
        
    except Exception as e:
        print(f'❌ Error getting net revenue summary: {str(e)}')
        return {
            'gross_revenue': 0,
            'gateway_fees': 0,
            'net_revenue': 0,
            'gateway_fee_percentage': 0,
            'gateway_fees_by_provider': {}
        }