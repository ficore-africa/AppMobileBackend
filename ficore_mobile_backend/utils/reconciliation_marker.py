"""
Standardized Reconciliation Marker

ALL code that needs to mark transactions for reconciliation should use this module.
This ensures consistency across the entire codebase.
"""

from datetime import datetime
from bson import ObjectId

def mark_transaction_for_reconciliation(
    mongo_db,
    transaction_id,
    reason,
    severity='MEDIUM',
    details=None,
    auto_detected=False
):
    """
    Standard way to mark a transaction for reconciliation
    
    Args:
        mongo_db: MongoDB database instance
        transaction_id: Transaction ID (ObjectId or string)
        reason: Reconciliation reason (e.g., 'PLAN_MISMATCH', 'GHOST_SUCCESS', 'AUTO_SCAN_FAILED_TRANSACTION')
        severity: 'LOW', 'MEDIUM', or 'HIGH'
        details: Additional details dict
        auto_detected: True if detected by automated scanner, False if manually flagged
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Convert to ObjectId if string
        if isinstance(transaction_id, str):
            transaction_id = ObjectId(transaction_id)
        
        # Get existing transaction
        transaction = mongo_db.vas_transactions.find_one({'_id': transaction_id})
        if not transaction:
            print(f'ERROR: Transaction {transaction_id} not found')
            return False
        
        # Check if already marked for reconciliation
        if transaction.get('status') == 'NEEDS_RECONCILIATION' and not transaction.get('reconciliationDismissed'):
            print(f'INFO: Transaction {transaction_id} already marked for reconciliation')
            return True  # Already marked, consider it success
        
        # Prepare reconciliation details
        reconciliation_details = {
            'original_status': transaction.get('status'),
            'provider': transaction.get('provider'),
            'severity': severity,
            'marked_at': datetime.utcnow(),
            'auto_detected': auto_detected,
            'transaction_type': transaction.get('type'),
            'amount': transaction.get('amount'),
            'phone_number': transaction.get('phoneNumber'),
            'network': transaction.get('network'),
            'failure_reason': transaction.get('failureReason')
        }
        
        # Merge with provided details
        if details:
            reconciliation_details.update(details)
        
        # Update transaction
        result = mongo_db.vas_transactions.update_one(
            {'_id': transaction_id},
            {
                '$set': {
                    'status': 'NEEDS_RECONCILIATION',
                    'reconciliationReason': reason,
                    'reconciliationDetails': reconciliation_details,
                    'needsReconciliation': True,
                    'reconciliationDismissed': False,  # Ensure not dismissed
                    'updatedAt': datetime.utcnow()
                }
            }
        )
        
        if result.modified_count > 0:
            print(f'✅ Transaction {transaction_id} marked for reconciliation: {reason}')
            return True
        else:
            print(f'⚠️  Transaction {transaction_id} not modified (might already be marked)')
            return True  # Consider it success if no modification needed
            
    except Exception as e:
        print(f'❌ Failed to mark transaction {transaction_id} for reconciliation: {e}')
        import traceback
        traceback.print_exc()
        return False


def mark_plan_mismatch_for_reconciliation(
    mongo_db,
    transaction_id,
    requested_plan,
    requested_amount,
    delivered_plan,
    delivered_amount,
    provider
):
    """
    Specialized function for plan mismatch reconciliation
    
    This is called when provider succeeds but delivers different plan/price than requested
    """
    details = {
        'action_required': 'Review and potentially refund difference or debit correct amount',
        'requested_plan': requested_plan,
        'requested_amount': requested_amount,
        'delivered_plan': delivered_plan,
        'delivered_amount': delivered_amount,
        'price_difference': delivered_amount - requested_amount,
        'verification_steps': [
            '1. Verify user actually received the delivered plan',
            '2. Check if wallet was debited for requested or delivered amount',
            '3. If user paid less but got more, debit the difference',
            '4. If user paid more but got less, refund the difference'
        ]
    }
    
    return mark_transaction_for_reconciliation(
        mongo_db=mongo_db,
        transaction_id=transaction_id,
        reason='PLAN_MISMATCH',
        severity='HIGH',
        details=details,
        auto_detected=True
    )


def mark_ghost_success_for_reconciliation(
    mongo_db,
    transaction_id,
    user_report=None
):
    """
    Specialized function for ghost success reconciliation
    
    This is called when provider succeeded but backend has no record (crashed before recording)
    """
    details = {
        'action_required': 'Verify if user received service, then debit wallet if confirmed',
        'issue': 'Provider succeeded but backend crashed before recording success',
        'user_report': user_report or 'User confirmed they received the service',
        'verification_steps': [
            '1. Contact user to verify they received the service',
            '2. Check provider logs to confirm transaction succeeded',
            '3. If confirmed, debit wallet for the amount user received',
            '4. Update transaction status to SUCCESS'
        ]
    }
    
    return mark_transaction_for_reconciliation(
        mongo_db=mongo_db,
        transaction_id=transaction_id,
        reason='GHOST_SUCCESS',
        severity='HIGH',
        details=details,
        auto_detected=False  # Usually reported by user
    )


def mark_stuck_pending_for_reconciliation(
    mongo_db,
    transaction_id,
    stuck_duration_minutes
):
    """
    Specialized function for stuck PENDING transactions
    
    This is called when transaction is stuck in PENDING for too long
    """
    details = {
        'action_required': 'Verify actual transaction outcome with provider',
        'issue': f'Transaction stuck in PENDING for {stuck_duration_minutes:.0f} minutes',
        'stuck_duration_minutes': stuck_duration_minutes,
        'verification_steps': [
            '1. Check provider logs for this transaction',
            '2. Contact provider support if needed',
            '3. If provider succeeded, mark as SUCCESS and debit wallet',
            '4. If provider failed, mark as FAILED (no wallet debit)'
        ]
    }
    
    return mark_transaction_for_reconciliation(
        mongo_db=mongo_db,
        transaction_id=transaction_id,
        reason='STUCK_PENDING',
        severity='HIGH',
        details=details,
        auto_detected=True
    )


def mark_provider_none_for_reconciliation(
    mongo_db,
    transaction_id
):
    """
    Specialized function for transactions with Provider: None
    
    This is called when transaction never reached provider (backend crashed early)
    """
    details = {
        'action_required': 'Verify if user received service despite Provider: None',
        'issue': 'Backend crashed before recording provider response',
        'verification_steps': [
            '1. Contact user to verify if they received the service',
            '2. Check if there are any provider logs for this transaction',
            '3. If user got service, mark as SUCCESS and debit wallet',
            '4. If user did not get service, mark as FAILED (no action needed)'
        ]
    }
    
    return mark_transaction_for_reconciliation(
        mongo_db=mongo_db,
        transaction_id=transaction_id,
        reason='PROVIDER_NONE',
        severity='HIGH',
        details=details,
        auto_detected=True
    )


def mark_suspicious_failure_for_reconciliation(
    mongo_db,
    transaction_id,
    suspicious_reason
):
    """
    Specialized function for suspicious FAILED transactions
    
    This is called by automated scanner when it detects suspicious failure patterns
    """
    details = {
        'action_required': 'Verify if user actually received service despite FAILED status',
        'suspicious_pattern': suspicious_reason,
        'verification_steps': [
            '1. Contact user to verify if they received the service',
            '2. Check provider logs for this transaction',
            '3. If user got service, mark as SUCCESS and debit wallet',
            '4. If user did not get service, dismiss this reconciliation item'
        ]
    }
    
    return mark_transaction_for_reconciliation(
        mongo_db=mongo_db,
        transaction_id=transaction_id,
        reason='AUTO_SCAN_SUSPICIOUS_FAILURE',
        severity='MEDIUM',
        details=details,
        auto_detected=True
    )
