"""
Decimal128 Helper Functions

Utilities for safely handling Decimal128 conversions to prevent serialization errors.
These functions are used throughout the application to ensure consistent handling
of MongoDB Decimal128 types.
"""

from bson import Decimal128


def safe_float(value):
    """
    Safely convert any numeric value (including Decimal128) to float.
    Guards against Decimal128 serialization errors.
    
    Args:
        value: Any numeric value (Decimal128, int, float, str, or None)
    
    Returns:
        float: The converted value, or 0.0 if conversion fails
    """
    if value is None:
        return 0.0
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def safe_sum(amounts):
    """
    Safely sum a list of amounts, converting Decimal128 to float.
    Guards against type errors when summing mixed types.
    
    Args:
        amounts: List of numeric values (can include Decimal128, int, float)
    
    Returns:
        float: The sum of all amounts
    """
    total = 0.0
    for amount in amounts:
        total += safe_float(amount)
    return total
