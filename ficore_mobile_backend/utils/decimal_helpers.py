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
    Rounds to 2 decimal places for financial precision.
    
    Args:
        value: Any numeric value (Decimal128, int, float, str, or None)
    
    Returns:
        float: The converted value rounded to 2 decimal places, or 0.0 if conversion fails
    """
    if value is None:
        return 0.0
    if isinstance(value, Decimal128):
        return round(float(value.to_decimal()), 2)
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    try:
        return round(float(value), 2)
    except (ValueError, TypeError):
        return 0.0


def safe_sum(amounts):
    """
    Safely sum a list of amounts, converting Decimal128 to float.
    Guards against type errors when summing mixed types.
    Rounds result to 2 decimal places for financial precision.
    
    Args:
        amounts: List of numeric values (can include Decimal128, int, float)
    
    Returns:
        float: The sum of all amounts rounded to 2 decimal places
    """
    total = 0.0
    for amount in amounts:
        total += safe_float(amount)
    return round(total, 2)
