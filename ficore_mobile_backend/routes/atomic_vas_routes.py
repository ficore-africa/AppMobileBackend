#!/usr/bin/env python3
"""
🛡️ ATOMIC VAS TRANSACTION ROUTES
Tier-1 Financial Institution Standards Backend Implementation
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId
import traceback
import uuid

from ..utils.atomic_transactions import (
    atomic_vas_transaction,
    validate_tier_freshness,
    check_high_value_transaction,
    log_atomic_operation
)
from ..utils.auth import require_auth
from ..utils.database import get_db_connection

atomic_vas_bp = Blueprint('atomic_vas', __name__)

@atomic_vas_bp.route('/vas/atomic-transaction', methods=['POST'])
@require_auth
def process_atomic_vas_transaction():
    """
    🛡️ ATOMIC VAS TRANSACTION ENDPOINT
    Implements all 4 hardening measures in a single atomic operation
    """
    try:
        data = request.get_json()
        user_id = data.get('userId')
        
        # Validate required fields
        required_fields = ['idempotencyKey', 'userId', 'type', 'amount', 'totalAmount', 'tier']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'message': f'Missing required field: {field}'
                }), 400

        idempotency_key = data['idempotencyKey']
        transaction_type = data['type']
        amount = float(data['amount'])
        total_amount = float(data['totalAmount'])
        user_tier = data['tier']
        
        print(f'🛡️ Processing atomic VAS transaction: {idempotency_key}')
        
        # Get database connection
        mongo_client = get_db_connection()
        db = mongo_client.ficore_db
        
        # Check for duplicate idempotency key
        existing_transaction = db.vas_transactions.find_one({
            'idempotencyKey': idempotency_key
        })
        
        if existing_transaction:
            print(f'📡 Duplicate idempotency key detected: {idempotency_key}')
            return jsonify({
                'success': True,
                'message': 'Transaction already processed',
                'data': {
                    'transactionId': str(existing_transaction['_id']),
                    'status': existing_transaction['status'],
                    'duplicate': True
                }
            })
        
        # Validate tier freshness one more time
        current_tier, tier_changed = validate_tier_freshness(
            user_id, user_tier, db
        )
        
        if tier_changed:
            print(f'⚖️ Tier changed during processing: {user_tier} → {current_tier}')
            # Recalculate fees with new tier
            # This would integrate with your pricing service
            pass
        
        # Start atomic transaction
        with atomic_vas_transaction(mongo_client) as session:
            transaction_id = ObjectId()
            
            # 1. Create VAS transaction record
            vas_transaction = {
                '_id': transaction_id,
                'idempotencyKey': idempotency_key,
                'userId': ObjectId(user_id),
                'type': transaction_type,
                'amount': amount,
                'transactionFee': data.get('transactionFee', 0),
                'totalAmount': total_amount,
                'tier': current_tier,
                'phoneNumber': data.get('phoneNumber'),
                'network': data.get('network'),
                'dataPlan': data.get('dataPlan'),
                'status': 'FAILED',  # 🔒 ATOMIC PATTERN: Start as FAILED, update to SUCCESS only when complete
                'failureReason': 'Transaction in progress',  # Will be updated if it actually fails
                'provider': 'peyflex',  # or determine dynamically
                'transactionReference': idempotency_key,  # CRITICAL: Add this field for unique index
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
                'tierChanged': tier_changed,
                'originalTier': data.get('originalTier'),
                'cbnCompliance': data.get('cbnCompliance', False),
                'emergencyPricing': data.get('emergencyPricing', False),
                'auditLog': [{
                    'action': 'CREATED',
                    'timestamp': datetime.utcnow(),
                    'details': 'Transaction created with atomic protection - starts as FAILED'
                }]
            }
            
            db.vas_transactions.insert_one(vas_transaction, session=session)
            
            # 2. Create expense entry (dual-write protection)
            expense_entry = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'type': 'VAS_TRANSACTION',
                'category': transaction_type,
                'amount': amount,  # Use actual purchase amount, not total_amount (fees eliminated)
                'description': f'{transaction_type} - {data.get("network", "")} {data.get("phoneNumber", "")}',
                'transactionId': transaction_id,
                'idempotencyKey': idempotency_key,
                'status': 'active',
                'isDeleted': False,
                'version': 1,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
                'auditLog': [{
                    'action': 'CREATED',
                    'timestamp': datetime.utcnow(),
                    'details': 'Expense entry created atomically with VAS transaction - fees eliminated'
                }]
            }
            
            db.expense_entries.insert_one(expense_entry, session=session)
            
            # 3. Update user wallet (if applicable)
            if transaction_type != 'WALLET_FUNDING':
                wallet_update_result = db.user_wallets.update_one(
                    {'userId': ObjectId(user_id)},
                    {
                        '$inc': {'balance': -amount},  # Debit actual purchase amount (fees eliminated)
                        '$set': {'updatedAt': datetime.utcnow()},
                        '$push': {
                            'auditLog': {
                                'action': 'VAS_DEBIT',
                                'amount': -amount,  # Debit actual purchase amount
                                'transactionId': transaction_id,
                                'timestamp': datetime.utcnow(),
                                'details': f'VAS transaction: {transaction_type} - fees eliminated'
                            }
                        }
                    },
                    session=session
                )
                
                if wallet_update_result.matched_count == 0:
                    raise Exception(f'User wallet not found: {user_id}')
            
            # 4. Process with external provider (simulate for now)
            # In production, this would call Peyflex/VTPass API
            provider_response = _simulate_provider_call(data)
            
            # 5. Update transaction status based on provider response
            final_status = 'SUCCESS' if provider_response['success'] else 'FAILED'
            
            # Prepare update operation
            update_operation = {
                '$set': {
                    'status': final_status,
                    'providerResponse': provider_response,
                    'updatedAt': datetime.utcnow()
                },
                '$push': {
                    'auditLog': {
                        'action': 'PROVIDER_RESPONSE',
                        'timestamp': datetime.utcnow(),
                        'details': f'Provider returned: {final_status}'
                    }
                }
            }
            
            # 🔒 Clear failureReason on success, update it on failure
            if final_status == 'SUCCESS':
                update_operation['$unset'] = {'failureReason': ""}
            else:
                update_operation['$set']['failureReason'] = provider_response.get('message', 'Provider transaction failed')
            
            db.vas_transactions.update_one(
                {'_id': transaction_id},
                update_operation,
                session=session
            )
            
            # 6. Log atomic operation
            operation_log = log_atomic_operation(
                'VAS_TRANSACTION',
                user_id,
                str(transaction_id),
                {
                    'type': transaction_type,
                    'amount': total_amount,
                    'tier': current_tier,
                    'tierChanged': tier_changed,
                    'idempotencyKey': idempotency_key,
                    'status': final_status
                }
            )
            
            db.atomic_operations.insert_one(operation_log, session=session)
            
            print(f'✅ Atomic VAS transaction completed: {transaction_id}')
            
            # Return success response
            return jsonify({
                'success': True,
                'message': 'Transaction processed successfully',
                'data': {
                    'transactionId': str(transaction_id),
                    'status': final_status,
                    'type': transaction_type,
                    'amount': amount,
                    'transactionFee': 0.0,  # Fees eliminated for VAS purchases
                    'totalAmount': amount,  # Total is now same as amount (fees eliminated)
                    'tier': current_tier,
                    'tierChanged': tier_changed,
                    'network': data.get('network'),
                    'phoneNumber': data.get('phoneNumber'),
                    'dataPlan': data.get('dataPlan'),
                    'provider': 'peyflex',
                    'createdAt': datetime.utcnow().isoformat(),
                    'idempotencyKey': idempotency_key,
                    'feesEliminated': True  # Flag to indicate fees have been eliminated
                }
            })
            
    except Exception as e:
        print(f'❌ Atomic VAS transaction error: {str(e)}')
        print(traceback.format_exc())
        
        return jsonify({
            'success': False,
            'message': f'Transaction processing failed: {str(e)}',
            'error': 'ATOMIC_TRANSACTION_ERROR'
        }), 500

def _simulate_provider_call(data):
    """
    Simulate external provider call
    In production, replace with actual Peyflex/VTPass integration
    """
    import random
    
    # Simulate 95% success rate
    success = random.random() < 0.95
    
    if success:
        return {
            'success': True,
            'providerTransactionId': str(uuid.uuid4()),
            'message': 'Transaction successful',
            'timestamp': datetime.utcnow().isoformat()
        }
    else:
        return {
            'success': False,
            'error': 'PROVIDER_ERROR',
            'message': 'Provider temporarily unavailable',
            'timestamp': datetime.utcnow().isoformat()
        }

@atomic_vas_bp.route('/vas/transactions/<user_id>', methods=['GET'])
@require_auth
def get_user_transactions(user_id):
    """
    Get user's VAS transaction history with atomic operation info
    """
    try:
        mongo_client = get_db_connection()
        db = mongo_client.ficore_db
        
        transactions = list(db.vas_transactions.find(
            {'userId': ObjectId(user_id)},
            sort=[('createdAt', -1)],
            limit=50
        ))
        
        # Convert ObjectIds to strings
        for transaction in transactions:
            transaction['_id'] = str(transaction['_id'])
            transaction['userId'] = str(transaction['userId'])
            if 'transactionId' in transaction:
                transaction['transactionId'] = str(transaction['transactionId'])
        
        return jsonify({
            'success': True,
            'data': transactions
        })
        
    except Exception as e:
        print(f'❌ Error fetching transactions: {str(e)}')
        return jsonify({
            'success': False,
            'message': f'Failed to fetch transactions: {str(e)}'
        }), 500

@atomic_vas_bp.route('/vas/maintenance', methods=['POST'])
@require_auth
def perform_maintenance():
    """
    Perform maintenance operations on atomic transaction system
    """
    try:
        mongo_client = get_db_connection()
        db = mongo_client.ficore_db
        
        # Clean up old pending transactions (older than 1 hour)
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        
        result = db.vas_transactions.update_many(
            {
                'status': 'PENDING',
                'createdAt': {'$lt': cutoff_time}
            },
            {
                '$set': {
                    'status': 'EXPIRED',
                    'updatedAt': datetime.utcnow()
                },
                '$push': {
                    'auditLog': {
                        'action': 'EXPIRED',
                        'timestamp': datetime.utcnow(),
                        'details': 'Transaction expired during maintenance'
                    }
                }
            }
        )
        
        print(f'🧹 Maintenance: Expired {result.modified_count} pending transactions')
        
        return jsonify({
            'success': True,
            'message': f'Maintenance completed. Expired {result.modified_count} transactions.'
        })
        
    except Exception as e:
        print(f'❌ Maintenance error: {str(e)}')
        return jsonify({
            'success': False,
            'message': f'Maintenance failed: {str(e)}'
        }), 500