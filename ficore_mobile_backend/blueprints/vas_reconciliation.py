"""
VAS Transaction Reconciliation API

Handles manual reconciliation of VAS transactions that need admin review.
Critical for resolving "Failed but Succeeded" transactions.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId

def init_vas_reconciliation_blueprint(mongo, token_required, admin_required):
    """Initialize VAS reconciliation blueprint with dependencies"""
    from utils.atomic_transactions import (
        get_reconciliation_transactions,
        resolve_reconciliation_transaction,
        mark_transaction_for_reconciliation
    )
    
    vas_reconciliation_bp = Blueprint('vas_reconciliation', __name__)

@vas_reconciliation_bp.route('/reconciliation/pending', methods=['GET'])
@token_required
@admin_required
def get_pending_reconciliation(current_user):
    """Get transactions that need manual reconciliation"""
    try:
        limit = int(request.args.get('limit', 50))
        transactions = get_reconciliation_transactions(mongo, limit)
        
        # Convert ObjectIds to strings for JSON serialization
        for txn in transactions:
            txn['_id'] = str(txn['_id'])
            txn['userId'] = str(txn['userId'])
        
        return jsonify({
            'success': True,
            'data': transactions,
            'count': len(transactions)
        })
        
    except Exception as e:
        print(f'Error getting reconciliation transactions: {e}')
        return jsonify({
            'success': False,
            'message': 'Failed to get reconciliation transactions',
            'error': str(e)
        }), 500

@vas_reconciliation_bp.route('/reconciliation/resolve', methods=['POST'])
@token_required
@admin_required
def resolve_reconciliation(current_user):
    """Resolve a transaction marked for reconciliation"""
    try:
        data = request.json
        transaction_id = data.get('transactionId')
        resolution_status = data.get('status')  # SUCCESS or FAILED
        admin_notes = data.get('adminNotes', '')
        
        if not transaction_id or not resolution_status:
            return jsonify({
                'success': False,
                'message': 'Transaction ID and resolution status are required'
            }), 400
        
        if resolution_status not in ['SUCCESS', 'FAILED']:
            return jsonify({
                'success': False,
                'message': 'Resolution status must be SUCCESS or FAILED'
            }), 400
        
        # Get transaction details for wallet adjustment if needed
        transaction = mongo.db.vas_transactions.find_one({'_id': ObjectId(transaction_id)})
        if not transaction:
            return jsonify({
                'success': False,
                'message': 'Transaction not found'
            }), 404
        
        # If resolving as SUCCESS, ensure wallet was properly debited
        if resolution_status == 'SUCCESS':
            user_id = str(transaction['userId'])
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            
            if wallet:
                # Check if wallet balance needs adjustment
                # This handles cases where provider succeeded but wallet wasn't debited
                total_amount = transaction.get('totalAmount', transaction.get('sellingPrice', 0))
                
                # Add transaction to wallet history if not already there
                existing_history = wallet.get('transactionHistory', [])
                transaction_exists = any(
                    hist.get('transactionId') == str(transaction_id) 
                    for hist in existing_history
                )
                
                if not transaction_exists and total_amount > 0:
                    # Debit wallet for successful transaction that wasn't properly processed
                    new_balance = wallet.get('balance', 0) - total_amount
                    
                    mongo.db.vas_wallets.update_one(
                        {'userId': ObjectId(user_id)},
                        {
                            '$set': {'balance': new_balance, 'updatedAt': datetime.utcnow()},
                            '$push': {
                                'transactionHistory': {
                                    'transactionId': str(transaction_id),
                                    'type': 'DEBIT',
                                    'amount': total_amount,
                                    'description': f'Reconciliation: {transaction.get("type", "VAS")} - {transaction.get("phoneNumber", "N/A")}',
                                    'timestamp': datetime.utcnow(),
                                    'reconciliation': True
                                }
                            }
                        }
                    )
                    
                    print(f'Reconciliation: Debited wallet ₦{total_amount} for successful transaction {transaction_id}')
        
        # Resolve the reconciliation
        success = resolve_reconciliation_transaction(
            mongo, 
            ObjectId(transaction_id), 
            resolution_status, 
            f"Resolved by admin {current_user.get('email', 'unknown')}: {admin_notes}"
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Transaction resolved as {resolution_status}'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to resolve transaction'
            }), 500
            
    except Exception as e:
        print(f'Error resolving reconciliation: {e}')
        return jsonify({
            'success': False,
            'message': 'Failed to resolve reconciliation',
            'error': str(e)
        }), 500

@vas_reconciliation_bp.route('/reconciliation/stats', methods=['GET'])
@token_required
@admin_required
def get_reconciliation_stats(current_user):
    """Get reconciliation statistics"""
    try:
        # Count pending reconciliations
        pending_count = mongo.db.vas_transactions.count_documents({
            'status': 'NEEDS_RECONCILIATION'
        })
        
        # Count resolved reconciliations in last 30 days
        resolved_count = mongo.db.vas_transactions.count_documents({
            'reconciliationResolved': True,
            'reconciliationResolvedAt': {'$gte': datetime.utcnow() - timedelta(days=30)}
        })
        
        # Get recent reconciliation activity
        recent_activity = list(mongo.db.vas_transactions.find(
            {
                '$or': [
                    {'status': 'NEEDS_RECONCILIATION'},
                    {'reconciliationResolved': True, 'reconciliationResolvedAt': {'$gte': datetime.utcnow() - timedelta(days=7)}}
                ]
            },
            sort=[('updatedAt', -1)],
            limit=10
        ))
        
        # Convert ObjectIds for JSON serialization
        for activity in recent_activity:
            activity['_id'] = str(activity['_id'])
            activity['userId'] = str(activity['userId'])
        
        return jsonify({
            'success': True,
            'data': {
                'pendingCount': pending_count,
                'resolvedLast30Days': resolved_count,
                'recentActivity': recent_activity
            }
        })
        
    except Exception as e:
        print(f'Error getting reconciliation stats: {e}')
        return jsonify({
            'success': False,
            'message': 'Failed to get reconciliation stats',
            'error': str(e)
        }), 500

@vas_reconciliation_bp.route('/reconciliation/mark', methods=['POST'])
@token_required
@admin_required
def mark_for_reconciliation(current_user):
    """Manually mark a transaction for reconciliation"""
    try:
        data = request.json
        transaction_id = data.get('transactionId')
        reason = data.get('reason', 'Manually marked by admin')
        
        if not transaction_id:
            return jsonify({
                'success': False,
                'message': 'Transaction ID is required'
            }), 400
        
        success = mark_transaction_for_reconciliation(
            mongo, 
            ObjectId(transaction_id), 
            f"{reason} (Admin: {current_user.get('email', 'unknown')})"
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Transaction marked for reconciliation'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to mark transaction for reconciliation'
            }), 500
            
    except Exception as e:
        print(f'Error marking transaction for reconciliation: {e}')
        return jsonify({
            'success': False,
            'message': 'Failed to mark transaction for reconciliation',
            'error': str(e)
        }), 500

    return vas_reconciliation_bp