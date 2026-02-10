"""
Test Account Configuration for Google Play Review
Handles test mode detection and API key selection
"""
import os

# Test account domains for Google Play review
# Any email ending with these domains will be treated as test accounts
TEST_DOMAINS = [
    '@ficoreafrica.com',  # Company domain - all internal accounts
]

# Specific test accounts (for extra safety)
TEST_ACCOUNTS = [
    'premiumtester@ficoreafrica.com',
    'newtester@ficoreafrica.com',
    'testernew@ficoreafrica.com',
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
    
    email_lower = email.lower().strip()
    
    # Check specific test accounts first
    if email_lower in [acc.lower() for acc in TEST_ACCOUNTS]:
        return True
    
    # Check if email ends with any test domain
    for domain in TEST_DOMAINS:
        if email_lower.endswith(domain.lower()):
            return True
    
    return False

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
