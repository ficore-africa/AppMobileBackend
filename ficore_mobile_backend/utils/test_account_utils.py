"""
Test Account Utilities

Critical test account functions.
"""

from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

# Test account user IDs
TEST_ACCOUNT_USER_IDS = [
    ObjectId('507f1f77bcf86cd799439011'),  # Test user 1
    ObjectId('507f1f77bcf86cd799439012'),  # Test user 2
]

def is_test_account(user_id):
    """
    Check if user ID is a test account
    
    Args:
        user_id: User ObjectId or string
        
    Returns:
        bool: True if test account
    """
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        
        return user_id in TEST_ACCOUNT_USER_IDS
        
    except Exception as e:
        logger.error(f"Error checking test account: {str(e)}")
        return False

def get_test_account_user_ids():
    """Get list of test account user IDs"""
    return TEST_ACCOUNT_USER_IDS.copy()
