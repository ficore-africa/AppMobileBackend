"""
Admin User Transactions API

Provides admin endpoints for viewing and managing user transactions.
Integrates with the reconciliation system for transaction status management.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
from ..auth import token_required, admin_required
from ..database import mongo

def init_admin_user_transactions_blueprint():
    admin_user_transactions_bp = Blueprint('admin_user_transactions', __name__)
    
    @admin_user_transactions_bp.route('/users/<user_id>/transactions', methods=['GET'])
    @token_required
    @admin_required
    def get_user_transactions(current_user, user_id):
        """Get transactions for a specific user with filtering"""
        try:
            # Parse query parameters
            status = request.args.get('status')  # SUCCESS, FAILED, PENDING, NEEDS_RECONCILIATION
            transaction_type = request.args.get('type')  # AIRTIME, DATA, BILLS, etc.
            limit = int(request.args.get('limit', 50))
            skip = int(request.args.get('skip', 0))
            
            # Build query
            query = {'userId': ObjectId(user_id)}
            
            if status:
                if status.upper() == 'FAILED':
                    # Include both FAILED and NEEDS_RECONCILIATION for failed transactions view
                    query['status'] = {'$in': ['FAILED', 'NEEDS_RECONCILIATION']}
                else:
                    query['status'] = status.upper()
            
            if transaction_type:
                query['type'] = transaction_type.upper()
            
            # Get transactions
            transactions = list(mongo.db.vas_transactions.find(
                query,
                sort=[('createdAt', -1)],
                limit=limit,
                skip=skip
            ))
            
            # Convert ObjectIds to strings
            for txn in transactions:
                txn['_id'] = str(txn['_id'])
                txn['userId'] = str(txn['userId'])
            
            # Get total count
            total_count = mongo.db.vas_transactions.count_documents(query)
            
            return jsonify({
                'success': True,
                'data': {
                    'transactions': transactions,
                    'totalCount': total_count,
                    'hasMore': (skip + len(transactions)) < total_count
                }
            })
            
        except Exception as e:
            print(f'Error getting user transactions: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to get user transactions',
                'error': str(e)
            }), 500
    
    @admin_user_transactions_bp.route('/users/<user_id>/reconciliations/pending', methods=['GET'])
    @token_required
    @admin_required
    def get_user_pending_reconciliations(current_user, user_id):
        """Get pending reconciliations for a specific user"""
        try:
            transactions = list(mongo.db.vas_transactions.find(
                {
                    'userId': ObjectId(user_id),
                    'status': 'NEEDS_RECONCILIATION'
                },
                sort=[('reconciliationTimestamp', -1)],
                limit=50
            ))
            
            # Convert ObjectIds to strings
            for txn in transactions:
                txn['_id'] = str(txn['_id'])
                txn['userId'] = str(txn['userId'])
            
            return jsonify({
                'success': True,
                'data': {
                    'transactions': transactions,
                    'count': len(transactions)
                }
            })
            
        except Exception as e:
            print(f'Error getting pending reconciliations: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to get pending reconciliations',
                'error': str(e)
            }), 500
    
    @admin_user_transactions_bp.route('/transactions/<transaction_id>', methods=['GET'])
    @token_required
    @admin_required
    def get_transaction_details(current_user, transaction_id):
        """Get detailed information about a specific transaction"""
        try:
            transaction = mongo.db.vas_transactions.find_one({'_id': ObjectId(transaction_id)})
            
            if not transaction:
                return jsonify({
                    'success': False,
                    'message': 'Transaction not found'
                }), 404
            
            # Convert ObjectIds to strings
            transaction['_id'] = str(transaction['_id'])
            transaction['userId'] = str(transaction['userId'])
            
            # Get user information
            user = mongo.db.users.find_one(
                {'_id': ObjectId(transaction['userId'])},
                {'displayName': 1, 'email': 1, 'name': 1}
            )
            
            if user:
                transaction['userInfo'] = {
                    'displayName': user.get('displayName') or user.get('name'),
                    'email': user.get('email')
                }
            
            return jsonify({
                'success': True,
                'data': transaction
            })
            
        except Exception as e:
            print(f'Error getting transaction details: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to get transaction details',
                'error': str(e)
            }), 500
    
    return admin_user_transactions_bp