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

def is_test_account(user_id_or_email):
    """
    Check if user ID or email is a test account
    
    Args:
        user_id_or_email: User ObjectId, string, or email
        
    Returns:
        bool: True if test account
    """
    try:
        # If it's an email, check against test emails
        if isinstance(user_id_or_email, str) and '@' in user_id_or_email:
            test_emails = [
                'test@example.com',
                'demo@ficore.africa',
                'admin@ficore.africa'
            ]
            return user_id_or_email.lower() in [email.lower() for email in test_emails]
        
        # If it's a user ID, check against test user IDs
        if isinstance(user_id_or_email, str):
            try:
                user_id = ObjectId(user_id_or_email)
            except:
                return False
        else:
            user_id = user_id_or_email
        
        return user_id in TEST_ACCOUNT_USER_IDS
        
    except Exception as e:
        logger.error(f"Error checking test account: {str(e)}")
        return False

def get_test_account_user_ids():
    """Get list of test account user IDs"""
    return TEST_ACCOUNT_USER_IDS.copy()
