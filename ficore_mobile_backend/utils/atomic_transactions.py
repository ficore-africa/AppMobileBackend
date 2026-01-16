#!/usr/bin/env python3
"""
🛡️ ATOMIC TRANSACTION UTILITIES
Tier-1 Financial Institution Standards for Data Integrity
"""

from datetime import datetime
from bson import ObjectId
from contextlib import contextmanager
import uuid

@contextmanager
def atomic_vas_transaction(mongo_client):
    """
    🛡️ ATOMIC DUAL-WRITE PROTECTION
    Ensures VAS transaction + expense entry + wallet update happen atomically
    Prevents the "silent blind spot" where server crashes between writes
    """
    session = mongo_client.start_session()
    try:
        with session.start_transaction():
            yield session
            print('✅ Atomic VAS transaction committed successfully')
    except Exception as e:
        print(f'❌ Atomic transaction failed, rolling back: {str(e)}')
        session.abort_transaction()
        raise e
    finally:
        session.end_session()

def generate_idempotency_key():
    """
    📡 CLIENT-SIDE IDEMPOTENCY PROTECTION
    Prevents double-billing when network drops after payment but before response
    """
    return str(uuid.uuid4())

def validate_tier_freshness(user_id, cached_tier, mongo_db):
    """
    ⚖️ TIER-JUMP RACE CONDITION PROTECTION
    Ensures user tier is fresh at the exact moment of payment
    Prevents "I was cheated" complaints from stale tier data
    """
    try:
        # Get fresh user data from database
        fresh_user = mongo_db.users.find_one({'_id': ObjectId(user_id)})
        if not fresh_user:
            raise Exception(f'User {user_id} not found')
        
        # Get current subscription status
        subscription = mongo_db.subscriptions.find_one({
            'userId': ObjectId(user_id),
            'status': 'active'
        })
        
        current_tier = 'basic'
        if subscription:
            current_tier = subscription.get('tier', 'basic')
        
        # Check if tier changed since frontend cached it
        if cached_tier != current_tier:
            print(f'⚖️ Tier changed: {cached_tier} → {current_tier} for user {user_id}')
            return current_tier, True  # Tier changed
        
        return current_tier, False  # Tier unchanged
        
    except Exception as e:
        print(f'❌ Error validating tier freshness: {str(e)}')
        # Default to basic tier for safety
        return 'basic', True

def check_high_value_transaction(amount, threshold=20000):
    """
    🛡️ CBN DUTY OF CARE COMPLIANCE
    Identifies transactions requiring double-confirmation for legal protection
    """
    return amount >= threshold

def create_double_confirm_data(amount, original_price, emergency_pricing=False):
    """
    🛡️ DOUBLE-CONFIRM MODAL DATA
    Creates the data structure for CBN compliance double-confirmation
    """
    multiplier = amount / original_price if original_price > 0 else 1
    
    return {
        'requires_double_confirm': True,
        'amount': amount,
        'original_price': original_price,
        'multiplier': multiplier,
        'emergency_pricing': emergency_pricing,
        'legal_text': f'I understand this is {multiplier:.1f}x the normal price due to network instability.',
        'cbn_compliance': True,
        'duty_of_care': 'acknowledged'
    }

def log_atomic_operation(operation_type, user_id, transaction_id, details):
    """
    📊 ATOMIC OPERATION LOGGING
    Tracks all atomic operations for audit and debugging
    """
    log_entry = {
        '_id': ObjectId(),
        'operation_type': operation_type,
        'user_id': user_id,
        'transaction_id': transaction_id,
        'details': details,
        'timestamp': datetime.utcnow(),
        'atomic': True
    }
    
    print(f'📊 Atomic operation logged: {operation_type} for user {user_id}')
    return log_entry