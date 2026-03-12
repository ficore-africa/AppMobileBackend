"""
Wallet Balance Utilities

Critical wallet balance functions.
"""

from bson import ObjectId
from utils.decimal_helpers import *
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def get_liquid_wallet_balance(mongo, user_id):
    """
    Get liquid wallet balance for user
    
    Args:
        mongo: MongoDB connection
        user_id: User ObjectId
        
    Returns:
        float: Liquid wallet balance
    """
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        # Get from vas_wallets collection (primary source)
        wallet = mongo.db.vas_wallets.find_one({'userId': user_id})
        if wallet:
            return safe_float(wallet.get('balance', 0))
        
        # Fallback to users collection
        user = mongo.db.users.find_one({'_id': user_id})
        if user:
            return safe_float(user.get('liquidWalletBalance', 0))
        
        return 0.0
        
    except Exception as e:
        logger.error(f"Error getting liquid wallet balance: {str(e)}")
        return 0.0

def update_liquid_wallet_balance(mongo, user_id, new_balance):
    """
    Update liquid wallet balance in all relevant fields
    
    Args:
        mongo: MongoDB connection
        user_id: User ObjectId
        new_balance: New balance amount
        
    Returns:
        bool: True if successful
    """
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        new_balance = safe_float(new_balance)
        
        # Update vas_wallets collection (primary)
        mongo.db.vas_wallets.update_one(
            {'userId': user_id},
            {
                '$set': {
                    'balance': new_balance,
                    'updatedAt': datetime.utcnow()
                }
            },
            upsert=True
        )
        
        # Update users collection (legacy fields)
        mongo.db.users.update_one(
            {'_id': user_id},
            {
                '$set': {
                    'liquidWalletBalance': new_balance,
                    'vasWalletBalance': new_balance,
                    'walletBalance': new_balance,
                    'updatedAt': datetime.utcnow()
                }
            }
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Error updating liquid wallet balance: {str(e)}")
        return False
