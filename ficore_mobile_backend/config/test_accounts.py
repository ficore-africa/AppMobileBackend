"""
Test Account Configuration for Google Play Review
Handles test mode detection and API key selection
"""
import os

# Test accounts for Google Play review
TEST_ACCOUNTS = [
    'premiumtester@ficoreafrica.com',
    'newtester@ficoreafrica.com'
]

def is_test_account(email):
    """
    Check if an email belongs to a test account
    
    Args:
        email (str): User email address
        
    Returns:
        bool: True if test account, False otherwise
    """
    if not email:
        return False
    return email.lower() in [acc.lower() for acc in TEST_ACCOUNTS]

def get_paystack_keys(email):
    """
    Get Paystack API keys based on user account type
    
    Args:
        email (str): User email address
        
    Returns:
        dict: Dictionary with 'public_key' and 'secret_key'
    """
    if is_test_account(email):
        return {
            'public_key': os.getenv('PAYSTACK_TEST_PUBLIC_KEY'),
            'secret_key': os.getenv('PAYSTACK_TEST_SECRET_KEY'),
            'mode': 'test'
        }
    else:
        return {
            'public_key': os.getenv('PAYSTACK_PUBLIC_KEY'),
            'secret_key': os.getenv('PAYSTACK_SECRET_KEY'),
            'mode': 'live'
        }

def should_simulate_vas_purchase(email):
    """
    Check if VAS purchases should be simulated (no real API call)
    
    Args:
        email (str): User email address
        
    Returns:
        bool: True if should simulate, False for real API call
    """
    return is_test_account(email)

def should_skip_otp(email):
    """
    Check if OTP verification should be skipped
    
    Args:
        email (str): User email address
        
    Returns:
        bool: True if should skip OTP, False for normal flow
    """
    return is_test_account(email)
