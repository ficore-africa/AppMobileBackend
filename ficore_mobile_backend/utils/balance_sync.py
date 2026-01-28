"""
Balance Synchronization Utility

This module provides centralized balance update functions to maintain
consistency between vas_wallets and users collections.

CRITICAL: This ensures Single Source of Truth (SSOT) for wallet balances.
"""

from datetime import datetime
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

def update_liquid_wallet_balance(mongo, user_id, new_balance, reason="", transaction_id=None, 
                               transaction_reference=None, transaction_type=None, 
                               push_sse_update=False, sse_data=None, skip_wallet_update=False):
    """
    Update liquid wallet balance in both vas_wallets and users collections.
    
    Args:
        mongo: Flask-PyMongo instance
        user_id: User ID (string or ObjectId)
        new_balance: New balance amount (float)
        reason: Reason for balance update (string)
        transaction_id: Associated transaction ID (optional)
        transaction_reference: Transaction reference (optional)
        transaction_type: Type of transaction (optional)
        push_sse_update: Whether to push SSE update (bool)
        sse_data: Additional data for SSE update (dict)
        skip_wallet_update: Skip wallet update if already done atomically (bool)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        user_object_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        timestamp = datetime.utcnow()
        
        # Skip wallet update if already done atomically
        if not skip_wallet_update:
            # Update VAS wallet (primary source)
            vas_wallet_result = mongo.db.vas_wallets.update_one(
                {'userId': user_object_id},
                {
                    '$set': {
                        'balance': new_balance,
                        'updatedAt': timestamp
                    }
                }
            )
            
            # Sync to users table (for backward compatibility)
            users_result = mongo.db.users.update_one(
                {'_id': user_object_id},
                {
                    '$set': {
                        'liquidWalletBalance': new_balance,
                        'updatedAt': timestamp
                    }
                }
            )
            
            # Verify both updates succeeded
            if vas_wallet_result.modified_count == 0:
                logger.error(f"Failed to update vas_wallets balance for user {user_id}")
                return False
                
            if users_result.modified_count == 0:
                logger.warning(f"Failed to update users.liquidWalletBalance for user {user_id} (may not exist)")
                # Don't fail if users update fails - vas_wallets is primary source
        
        # Push SSE update if requested
        if push_sse_update:
            try:
                from blueprints.vas_wallet import push_balance_update
                
                sse_update_data = {
                    'type': 'balance_update',
                    'new_balance': new_balance,
                    'timestamp': timestamp.isoformat(),
                    'transaction_type': transaction_type,
                    'transaction_reference': transaction_reference
                }
                
                # Add additional SSE data if provided
                if sse_data:
                    sse_update_data.update(sse_data)
                
                push_balance_update(str(user_id), sse_update_data)
                logger.info(f"SSE update pushed for user {user_id}: ₦{new_balance:,.2f}")
                
            except Exception as sse_error:
                logger.warning(f"SSE update failed for user {user_id}: {str(sse_error)}")
                # Don't fail the transaction for SSE errors
        
        # Log the update
        logger.info(f"Balance sync: User {user_id}, New balance: ₦{new_balance:,.2f}, Reason: {reason}")
        
        return True
        
    except Exception as e:
        logger.error(f"Balance sync failed for user {user_id}: {str(e)}")
        return False

def get_liquid_wallet_balance(mongo, user_id):
    """
    Get current liquid wallet balance from primary source (vas_wallets).
    
    Args:
        mongo: Flask-PyMongo instance
        user_id: User ID (string or ObjectId)
    
    Returns:
        float: Current balance or 0.0 if not found
    """
    try:
        user_object_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        
        wallet = mongo.db.vas_wallets.find_one({'userId': user_object_id})
        if wallet:
            return wallet.get('balance', 0.0)
        
        # Fallback to users table if vas_wallet doesn't exist
        user = mongo.db.users.find_one({'_id': user_object_id})
        if user:
            return user.get('liquidWalletBalance', 0.0)
            
        return 0.0
        
    except Exception as e:
        logger.error(f"Failed to get balance for user {user_id}: {str(e)}")
        return 0.0

def sync_balance_from_vas_to_users(mongo, user_id):
    """
    One-way sync from vas_wallets to users table.
    Used for data consistency maintenance.
    
    Args:
        mongo: Flask-PyMongo instance
        user_id: User ID (string or ObjectId)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        user_object_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        
        # Get balance from primary source
        wallet = mongo.db.vas_wallets.find_one({'userId': user_object_id})
        if not wallet:
            logger.warning(f"No vas_wallet found for user {user_id}")
            return False
            
        balance = wallet.get('balance', 0.0)
        
        # Sync to users table
        result = mongo.db.users.update_one(
            {'_id': user_object_id},
            {
                '$set': {
                    'liquidWalletBalance': balance,
                    'updatedAt': datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Synced balance ₦{balance:,.2f} from vas_wallets to users for user {user_id}")
        return result.modified_count > 0
        
    except Exception as e:
        logger.error(f"Balance sync failed for user {user_id}: {str(e)}")
        return False