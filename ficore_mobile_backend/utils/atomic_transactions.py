"""
Atomic Transaction Utilities for Financial Operations

This module provides utilities for ensuring financial integrity through atomic operations.
Critical for preventing the "Failed but Succeeded" bug in VAS transactions.
"""

from datetime import datetime, timedelta
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

def execute_vas_transaction_atomically(mongo, transaction_data, wallet_update_data):
    """
    Execute VAS transaction and wallet update atomically
    
    Args:
        mongo: MongoDB connection
        transaction_data: Dict containing transaction update data
        wallet_update_data: Dict containing wallet update data
    
    Returns:
        dict: {'success': bool, 'error': str or None}
    """
    try:
        with mongo.cx.start_session() as session:
            with session.start_transaction():
                # Update transaction status
                transaction_result = mongo.db.vas_transactions.update_one(
                    {'_id': transaction_data['transaction_id']},
                    {'$set': transaction_data['update_fields']},
                    session=session
                )
                
                # Update wallet balance
                wallet_result = mongo.db.vas_wallets.update_one(
                    {'userId': ObjectId(wallet_update_data['user_id'])},
                    {
                        '$set': {
                            'balance': wallet_update_data['new_balance'],
                            'updatedAt': datetime.utcnow()
                        },
                        '$push': {
                            'transactionHistory': wallet_update_data['history_entry']
                        }
                    },
                    session=session
                )
                
                # Verify both updates succeeded
                if transaction_result.modified_count == 0:
                    raise Exception(f"Failed to update transaction {transaction_data['transaction_id']}")
                
                if wallet_result.modified_count == 0:
                    raise Exception(f"Failed to update wallet for user {wallet_update_data['user_id']}")
                
                logger.info(f"Atomic VAS transaction completed successfully: {transaction_data['transaction_id']}")
                return {'success': True, 'error': None}
                
    except Exception as e:
        logger.error(f"Atomic VAS transaction failed: {e}")
        return {'success': False, 'error': str(e)}

def check_recent_duplicate_transaction(mongo, user_id, transaction_type, amount, phone_number=None, minutes=5):
    """
    Check for recent duplicate transactions to prevent double-charging
    
    Args:
        mongo: MongoDB connection
        user_id: User ID
        transaction_type: Type of transaction (AIRTIME, DATA, etc.)
        amount: Transaction amount
        phone_number: Phone number (optional)
        minutes: Time window to check (default 5 minutes)
    
    Returns:
        dict or None: Recent transaction if found, None otherwise
    """
    query = {
        'userId': ObjectId(user_id),
        'type': transaction_type.upper(),
        'amount': amount,
        'status': {'$in': ['SUCCESS', 'NEEDS_RECONCILIATION']},
        'createdAt': {'$gte': datetime.utcnow() - timedelta(minutes=minutes)}
    }
    
    if phone_number:
        query['phoneNumber'] = phone_number
    
    return mongo.db.vas_transactions.find_one(query)

def mark_transaction_for_reconciliation(mongo, transaction_id, reason, provider_response=None):
    """
    Mark a transaction for manual reconciliation when atomic operations fail
    
    Args:
        mongo: MongoDB connection
        transaction_id: Transaction ID
        reason: Reason for reconciliation
        provider_response: Provider response data (optional)
    
    Returns:
        bool: True if marked successfully, False otherwise
    """
    try:
        update_data = {
            'status': 'NEEDS_RECONCILIATION',
            'failureReason': reason,
            'reconciliationRequired': True,
            'reconciliationTimestamp': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        if provider_response:
            update_data['providerResponse'] = provider_response
        
        result = mongo.db.vas_transactions.update_one(
            {'_id': transaction_id},
            {'$set': update_data}
        )
        
        if result.modified_count > 0:
            logger.warning(f"Transaction {transaction_id} marked for reconciliation: {reason}")
            return True
        else:
            logger.error(f"Failed to mark transaction {transaction_id} for reconciliation")
            return False
            
    except Exception as e:
        logger.error(f"Error marking transaction {transaction_id} for reconciliation: {e}")
        return False

def get_reconciliation_transactions(mongo, limit=50):
    """
    Get transactions that need manual reconciliation
    
    Args:
        mongo: MongoDB connection
        limit: Maximum number of transactions to return
    
    Returns:
        list: Transactions needing reconciliation
    """
    return list(mongo.db.vas_transactions.find(
        {'status': 'NEEDS_RECONCILIATION'},
        sort=[('reconciliationTimestamp', -1)],
        limit=limit
    ))

def resolve_reconciliation_transaction(mongo, transaction_id, resolution_status, admin_notes=None):
    """
    Resolve a transaction marked for reconciliation
    
    Args:
        mongo: MongoDB connection
        transaction_id: Transaction ID
        resolution_status: Final status (SUCCESS or FAILED)
        admin_notes: Admin notes about resolution
    
    Returns:
        bool: True if resolved successfully, False otherwise
    """
    try:
        update_data = {
            'status': resolution_status,
            'reconciliationResolved': True,
            'reconciliationResolvedAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        if admin_notes:
            update_data['adminNotes'] = admin_notes
        
        # Remove reconciliation fields
        unset_data = {
            'reconciliationRequired': "",
            'failureReason': ""
        }
        
        result = mongo.db.vas_transactions.update_one(
            {'_id': transaction_id},
            {
                '$set': update_data,
                '$unset': unset_data
            }
        )
        
        if result.modified_count > 0:
            logger.info(f"Transaction {transaction_id} reconciliation resolved as {resolution_status}")
            return True
        else:
            logger.error(f"Failed to resolve reconciliation for transaction {transaction_id}")
            return False
            
    except Exception as e:
        logger.error(f"Error resolving reconciliation for transaction {transaction_id}: {e}")
        return False