#!/usr/bin/env python3
"""
Liability Calculator Utility

Calculates outstanding liabilities for FC Credits, Subscriptions, and Fee Waivers
Used by Statement of Affairs and Treasury Dashboard
"""

from bson import ObjectId
from datetime import datetime, timezone


def safe_float(value):
    """
    Safely convert value to float, handling Decimal128 and other types
    """
    if value is None:
        return 0.0
    
    # Handle Decimal128 from MongoDB
    if hasattr(value, 'to_decimal'):
        return float(value.to_decimal())
    
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def calculate_fc_credit_liabilities(mongo, user_id=None):
    """
    Calculate outstanding FC Credit liabilities
    
    Args:
        mongo: MongoDB connection
        user_id: ObjectId of specific user (None for business/admin view)
    
    Returns:
        dict: {
            'total': float,
            'breakdown': [
                {
                    'user_id': str,
                    'user_email': str,
                    'fc_amount': float,
                    'naira_value': float,
                    'created_at': datetime,
                    'source': str
                }
            ]
        }
    """
    try:
        # CRITICAL FIX: Filter by user and exclude business account
        BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')
        
        liability_query = {
            'sourceType': 'fc_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'userId': {'$ne': BUSINESS_USER_ID}  # ✅ Exclude business account
        }
        
        # If specific user requested, filter to that user only
        if user_id:
            liability_query['userId'] = user_id
        
        fc_liabilities = list(mongo.db.incomes.find(liability_query))
        
        # Find all FC Credit consumptions to subtract
        consumption_query = {
            'sourceType': 'fc_consumption',
            'status': 'active',
            'isDeleted': False,
            'userId': {'$ne': BUSINESS_USER_ID}  # ✅ Exclude business account
        }
        
        # If specific user requested, filter to that user only
        if user_id:
            consumption_query['userId'] = user_id
        
        fc_consumptions = list(mongo.db.incomes.find(consumption_query))
        
        # Calculate net outstanding liabilities
        total_accrued = sum(safe_float(liability.get('amount', 0)) for liability in fc_liabilities)
        total_consumed = sum(safe_float(consumption.get('amount', 0)) for consumption in fc_consumptions)
        
        net_outstanding = total_accrued - total_consumed
        
        # Create breakdown (simplified - showing accruals)
        breakdown = []
        for liability in fc_liabilities:
            user_id = liability.get('userId')
            if user_id:
                # Get user email
                user = mongo.db.users.find_one({'_id': user_id}, {'email': 1})
                user_email = user.get('email', 'Unknown') if user else 'Unknown'
                
                # FC Credits are typically valued at ₦30 per FC
                fc_amount = safe_float(liability.get('amount', 0)) / 30.0
                
                breakdown.append({
                    'user_id': str(user_id),
                    'user_email': user_email,
                    'fc_amount': fc_amount,
                    'naira_value': safe_float(liability.get('amount', 0)),
                    'created_at': liability.get('createdAt', datetime.utcnow()),
                    'source': liability.get('description', 'FC Credit Liability')
                })
        
        return {
            'success': True,
            'total': max(0, net_outstanding),  # Don't show negative liabilities
            'breakdown': breakdown,
            'accrued': total_accrued,
            'consumed': total_consumed
        }
        
    except Exception as e:
        print(f"❌ Error calculating FC Credit liabilities: {str(e)}")
        return {
            'success': False,
            'total': 0,
            'breakdown': [],
            'error': str(e)
        }


def calculate_subscription_liabilities(mongo, user_id=None):
    """
    Calculate outstanding Subscription liabilities
    
    Args:
        mongo: MongoDB connection
        user_id: ObjectId of specific user (None for business/admin view)
    
    Returns:
        dict: {
            'total': float,
            'breakdown': [
                {
                    'user_id': str,
                    'user_email': str,
                    'subscription_type': str,
                    'amount': float,
                    'created_at': datetime
                }
            ]
        }
    """
    try:
        # CRITICAL FIX: Filter by user and exclude business account
        BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')
        
        liability_query = {
            'sourceType': 'subscription_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'userId': {'$ne': BUSINESS_USER_ID}  # ✅ Exclude business account
        }
        
        # If specific user requested, filter to that user only
        if user_id:
            liability_query['userId'] = user_id
        
        subscription_liabilities = list(mongo.db.incomes.find(liability_query))
        
        # Find all Subscription consumptions to subtract
        consumption_query = {
            'sourceType': 'subscription_consumption',
            'status': 'active',
            'isDeleted': False,
            'userId': {'$ne': BUSINESS_USER_ID}  # ✅ Exclude business account
        }
        
        # If specific user requested, filter to that user only
        if user_id:
            consumption_query['userId'] = user_id
        
        subscription_consumptions = list(mongo.db.incomes.find(consumption_query))
        
        # Calculate net outstanding liabilities
        total_accrued = sum(safe_float(liability.get('amount', 0)) for liability in subscription_liabilities)
        total_consumed = sum(safe_float(consumption.get('amount', 0)) for consumption in subscription_consumptions)
        
        net_outstanding = total_accrued - total_consumed
        
        # Create breakdown
        breakdown = []
        for liability in subscription_liabilities:
            user_id = liability.get('userId')
            if user_id:
                # Get user email
                user = mongo.db.users.find_one({'_id': user_id}, {'email': 1})
                user_email = user.get('email', 'Unknown') if user else 'Unknown'
                
                breakdown.append({
                    'user_id': str(user_id),
                    'user_email': user_email,
                    'subscription_type': 'Premium',  # Default type
                    'amount': safe_float(liability.get('amount', 0)),
                    'created_at': liability.get('createdAt', datetime.utcnow())
                })
        
        return {
            'success': True,
            'total': max(0, net_outstanding),
            'breakdown': breakdown,
            'accrued': total_accrued,
            'consumed': total_consumed
        }
        
    except Exception as e:
        print(f"❌ Error calculating Subscription liabilities: {str(e)}")
        return {
            'success': False,
            'total': 0,
            'breakdown': [],
            'error': str(e)
        }


def calculate_fee_waiver_liabilities(mongo, user_id=None):
    """
    Calculate outstanding Fee Waiver liabilities
    
    Args:
        mongo: MongoDB connection
        user_id: ObjectId of specific user (None for business/admin view)
    
    Returns:
        dict: {
            'total': float,
            'breakdown': [
                {
                    'user_id': str,
                    'user_email': str,
                    'waiver_type': str,
                    'amount': float,
                    'created_at': datetime
                }
            ]
        }
    """
    try:
        # CRITICAL FIX: Filter by user and exclude business account
        BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')
        
        liability_query = {
            'sourceType': 'fee_waiver_liability_accrual',
            'status': 'active',
            'isDeleted': False,
            'userId': {'$ne': BUSINESS_USER_ID}  # ✅ Exclude business account
        }
        
        # If specific user requested, filter to that user only
        if user_id:
            liability_query['userId'] = user_id
        
        fee_waiver_liabilities = list(mongo.db.incomes.find(liability_query))
        
        # Find all Fee Waiver consumptions to subtract
        consumption_query = {
            'sourceType': 'fee_waiver_consumption',
            'status': 'active',
            'isDeleted': False,
            'userId': {'$ne': BUSINESS_USER_ID}  # ✅ Exclude business account
        }
        
        # If specific user requested, filter to that user only
        if user_id:
            consumption_query['userId'] = user_id
        
        fee_waiver_consumptions = list(mongo.db.incomes.find(consumption_query))
        
        # Calculate net outstanding liabilities
        total_accrued = sum(safe_float(liability.get('amount', 0)) for liability in fee_waiver_liabilities)
        total_consumed = sum(safe_float(consumption.get('amount', 0)) for consumption in fee_waiver_consumptions)
        
        net_outstanding = total_accrued - total_consumed
        
        # Create breakdown
        breakdown = []
        for liability in fee_waiver_liabilities:
            user_id = liability.get('userId')
            if user_id:
                # Get user email
                user = mongo.db.users.find_one({'_id': user_id}, {'email': 1})
                user_email = user.get('email', 'Unknown') if user else 'Unknown'
                
                breakdown.append({
                    'user_id': str(user_id),
                    'user_email': user_email,
                    'waiver_type': 'Deposit Fee Waiver',  # Default type
                    'amount': safe_float(liability.get('amount', 0)),
                    'created_at': liability.get('createdAt', datetime.utcnow())
                })
        
        return {
            'success': True,
            'total': max(0, net_outstanding),
            'breakdown': breakdown,
            'accrued': total_accrued,
            'consumed': total_consumed
        }
        
    except Exception as e:
        print(f"❌ Error calculating Fee Waiver liabilities: {str(e)}")
        return {
            'success': False,
            'total': 0,
            'breakdown': [],
            'error': str(e)
        }


def calculate_total_liabilities(mongo, user_id=None):
    """
    Calculate all outstanding liabilities (FC Credits, Subscriptions, Fee Waivers)
    
    Args:
        mongo: MongoDB connection
        user_id: ObjectId of specific user (None for business/admin view)
    
    Returns:
        dict: {
            'success': bool,
            'fc_credit_liabilities': dict,
            'subscription_liabilities': dict,
            'fee_waiver_liabilities': dict,
            'total_all_liabilities': float
        }
    """
    try:
        # Calculate each liability type with user filtering
        fc_result = calculate_fc_credit_liabilities(mongo, user_id)
        subscription_result = calculate_subscription_liabilities(mongo, user_id)
        fee_waiver_result = calculate_fee_waiver_liabilities(mongo, user_id)
        
        # Calculate total
        total_all = (
            fc_result.get('total', 0) + 
            subscription_result.get('total', 0) + 
            fee_waiver_result.get('total', 0)
        )
        
        return {
            'success': True,
            'fc_credit_liabilities': fc_result,
            'subscription_liabilities': subscription_result,
            'fee_waiver_liabilities': fee_waiver_result,
            'total_all_liabilities': total_all
        }
        
    except Exception as e:
        print(f"❌ Error calculating total liabilities: {str(e)}")
        return {
            'success': False,
            'fc_credit_liabilities': {'total': 0, 'breakdown': []},
            'subscription_liabilities': {'total': 0, 'breakdown': []},
            'fee_waiver_liabilities': {'total': 0, 'breakdown': []},
            'total_all_liabilities': 0,
            'error': str(e)
        }


if __name__ == "__main__":
    # Test the liability calculator
    print("🧪 Testing Liability Calculator...")
    
    # This would need a MongoDB connection to test
    # For now, just verify imports work
    print("✅ All imports successful")
    print("✅ Functions defined:")
    print("  - calculate_fc_credit_liabilities")
    print("  - calculate_subscription_liabilities") 
    print("  - calculate_fee_waiver_liabilities")
    print("  - calculate_total_liabilities")
    print("  - safe_float")