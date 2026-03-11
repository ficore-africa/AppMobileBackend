"""
Payment Method Validation

Utilities for validating and normalizing payment methods.
"""

import logging

logger = logging.getLogger(__name__)

# Valid payment methods
VALID_PAYMENT_METHODS = [
    'cash', 'bank_transfer', 'card', 'mobile_money', 
    'wallet', 'credit', 'cheque', 'other'
]

def validate_payment_method(payment_method):
    """
    Validate payment method
    
    Args:
        payment_method: Payment method string
        
    Returns:
        bool: True if valid
    """
    if not payment_method:
        return False
    
    return payment_method.lower() in VALID_PAYMENT_METHODS

def normalize_payment_method(payment_method):
    """
    Normalize payment method to standard format
    
    Args:
        payment_method: Payment method string
        
    Returns:
        str: Normalized payment method
    """
    if not payment_method:
        return 'cash'  # Default
    
    method = payment_method.lower().strip()
    
    # Handle common variations
    if method in ['transfer', 'bank transfer', 'bank_transfer']:
        return 'bank_transfer'
    elif method in ['debit card', 'credit card', 'card payment']:
        return 'card'
    elif method in ['momo', 'mobile money', 'mobile_money']:
        return 'mobile_money'
    elif method in ['ficore wallet', 'wallet']:
        return 'wallet'
    elif method in ['cash payment', 'cash']:
        return 'cash'
    
    # Return as-is if already valid
    if validate_payment_method(method):
        return method
    
    return 'other'  # Fallback

# Valid sales types
VALID_SALES_TYPES = [
    'product_sale', 'service_income', 'rental_income', 
    'commission', 'interest', 'dividend', 'other_income'
]

def validate_sales_type(sales_type):
    """
    Validate sales type
    
    Args:
        sales_type: Sales type string
        
    Returns:
        bool: True if valid
    """
    if not sales_type:
        return False
    
    return sales_type.lower() in VALID_SALES_TYPES

def normalize_sales_type(sales_type):
    """
    Normalize sales type to standard format
    
    Args:
        sales_type: Sales type string
        
    Returns:
        str: Normalized sales type
    """
    if not sales_type:
        return 'product_sale'  # Default
    
    sales_type = sales_type.lower().strip()
    
    # Handle common variations
    if sales_type in ['product', 'goods', 'merchandise']:
        return 'product_sale'
    elif sales_type in ['service', 'services']:
        return 'service_income'
    elif sales_type in ['rent', 'rental']:
        return 'rental_income'
    elif sales_type in ['commission', 'referral']:
        return 'commission'
    
    # Return as-is if already valid
    if validate_sales_type(sales_type):
        return sales_type
    
    return 'other_income'  # Fallback
