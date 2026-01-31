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
        """Get transactions that need manual reconciliation (not dismissed)"""
        try:
            limit = int(request.args.get('limit', 50))
            
            # Only show transactions that are NOT dismissed
            transactions = list(mongo.db.vas_transactions.find({
                'status': 'NEEDS_RECONCILIATION',
                'reconciliationDismissed': {'$ne': True}  # Exclude dismissed
            }).sort('createdAt', -1).limit(limit))
            
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
            # Count pending reconciliations (not dismissed)
            pending_count = mongo.db.vas_transactions.count_documents({
                'status': 'NEEDS_RECONCILIATION',
                'reconciliationDismissed': {'$ne': True}
            })
            
            # Count dismissed reconciliations
            dismissed_count = mongo.db.vas_transactions.count_documents({
                'status': 'NEEDS_RECONCILIATION',
                'reconciliationDismissed': True
            })
            
            # Count resolved reconciliations in last 30 days
            resolved_count = mongo.db.vas_transactions.count_documents({
                'reconciliationResolved': True,
                'reconciliationResolvedAt': {'$gte': datetime.utcnow() - timedelta(days=30)}
            })
            
            # Get total amount pending reconciliation (not dismissed)
            pending_amount_pipeline = [
                {
                    '$match': {
                        'status': 'NEEDS_RECONCILIATION',
                        'reconciliationDismissed': {'$ne': True}
                    }
                },
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ]
            pending_amount_result = list(mongo.db.vas_transactions.aggregate(pending_amount_pipeline))
            pending_amount = pending_amount_result[0]['total'] if pending_amount_result else 0
            
            # Count affected users (not dismissed)
            affected_users_pipeline = [
                {
                    '$match': {
                        'status': 'NEEDS_RECONCILIATION',
                        'reconciliationDismissed': {'$ne': True}
                    }
                },
                {'$group': {'_id': '$userId'}},
                {'$count': 'uniqueUsers'}
            ]
            affected_users_result = list(mongo.db.vas_transactions.aggregate(affected_users_pipeline))
            affected_users = affected_users_result[0]['uniqueUsers'] if affected_users_result else 0
            
            # Get recent reconciliation activity
            recent_activity = list(mongo.db.vas_transactions.find(
                {
                    '$or': [
                        {
                            'status': 'NEEDS_RECONCILIATION',
                            'reconciliationDismissed': {'$ne': True}
                        },
                        {
                            'reconciliationResolved': True,
                            'reconciliationResolvedAt': {'$gte': datetime.utcnow() - timedelta(days=7)}
                        }
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
                    'dismissedCount': dismissed_count,
                    'resolvedLast30Days': resolved_count,
                    'pendingAmount': pending_amount,
                    'affectedUsers': affected_users,
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

    @vas_reconciliation_bp.route('/reconciliation/dismiss', methods=['POST'])
    @token_required
    @admin_required
    def dismiss_reconciliation(current_user):
        """
        Dismiss a reconciliation item (admin reviewed and determined no action needed)
        Dismissed items can be recovered later if needed
        """
        try:
            data = request.json
            transaction_id = data.get('transactionId')
            dismiss_reason = data.get('reason', 'No action needed')
            admin_notes = data.get('notes', '')
            
            if not transaction_id:
                return jsonify({
                    'success': False,
                    'message': 'Transaction ID is required'
                }), 400
            
            # Get transaction
            transaction = mongo.db.vas_transactions.find_one({'_id': ObjectId(transaction_id)})
            if not transaction:
                return jsonify({
                    'success': False,
                    'message': 'Transaction not found'
                }), 404
            
            # Mark as dismissed
            result = mongo.db.vas_transactions.update_one(
                {'_id': ObjectId(transaction_id)},
                {
                    '$set': {
                        'reconciliationDismissed': True,
                        'reconciliationDismissedAt': datetime.utcnow(),
                        'reconciliationDismissedBy': current_user.get('email', 'unknown'),
                        'reconciliationDismissReason': dismiss_reason,
                        'reconciliationDismissNotes': admin_notes,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                # Log admin action
                admin_action = {
                    '_id': ObjectId(),
                    'adminId': current_user['_id'],
                    'adminEmail': current_user.get('email', 'admin'),
                    'action': 'dismiss_reconciliation',
                    'transactionId': transaction_id,
                    'reason': dismiss_reason,
                    'notes': admin_notes,
                    'timestamp': datetime.utcnow(),
                    'details': {
                        'transaction_type': transaction.get('type'),
                        'amount': transaction.get('amount'),
                        'original_status': transaction.get('status'),
                        'reconciliation_reason': transaction.get('reconciliationReason')
                    }
                }
                mongo.db.admin_actions.insert_one(admin_action)
                
                return jsonify({
                    'success': True,
                    'message': 'Reconciliation item dismissed'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to dismiss reconciliation item'
                }), 500
                
        except Exception as e:
            print(f'Error dismissing reconciliation: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to dismiss reconciliation',
                'error': str(e)
            }), 500

    @vas_reconciliation_bp.route('/reconciliation/dismissed', methods=['GET'])
    @token_required
    @admin_required
    def get_dismissed_reconciliations(current_user):
        """Get all dismissed reconciliation items"""
        try:
            limit = int(request.args.get('limit', 100))
            
            # Get dismissed reconciliations
            dismissed = list(mongo.db.vas_transactions.find({
                'status': 'NEEDS_RECONCILIATION',
                'reconciliationDismissed': True
            }).sort('reconciliationDismissedAt', -1).limit(limit))
            
            # Convert ObjectIds for JSON serialization
            for txn in dismissed:
                txn['_id'] = str(txn['_id'])
                txn['userId'] = str(txn['userId'])
            
            return jsonify({
                'success': True,
                'data': dismissed,
                'count': len(dismissed)
            })
            
        except Exception as e:
            print(f'Error getting dismissed reconciliations: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to get dismissed reconciliations',
                'error': str(e)
            }), 500

    @vas_reconciliation_bp.route('/reconciliation/recover', methods=['POST'])
    @token_required
    @admin_required
    def recover_dismissed_reconciliation(current_user):
        """
        Recover a dismissed reconciliation item (bring it back to pending queue)
        """
        try:
            data = request.json
            transaction_id = data.get('transactionId')
            recovery_reason = data.get('reason', 'Admin decided to review again')
            
            if not transaction_id:
                return jsonify({
                    'success': False,
                    'message': 'Transaction ID is required'
                }), 400
            
            # Get transaction
            transaction = mongo.db.vas_transactions.find_one({'_id': ObjectId(transaction_id)})
            if not transaction:
                return jsonify({
                    'success': False,
                    'message': 'Transaction not found'
                }), 404
            
            # Recover (un-dismiss)
            result = mongo.db.vas_transactions.update_one(
                {'_id': ObjectId(transaction_id)},
                {
                    '$set': {
                        'reconciliationDismissed': False,
                        'reconciliationRecoveredAt': datetime.utcnow(),
                        'reconciliationRecoveredBy': current_user.get('email', 'unknown'),
                        'reconciliationRecoveryReason': recovery_reason,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                # Log admin action
                admin_action = {
                    '_id': ObjectId(),
                    'adminId': current_user['_id'],
                    'adminEmail': current_user.get('email', 'admin'),
                    'action': 'recover_reconciliation',
                    'transactionId': transaction_id,
                    'reason': recovery_reason,
                    'timestamp': datetime.utcnow(),
                    'details': {
                        'transaction_type': transaction.get('type'),
                        'amount': transaction.get('amount'),
                        'previously_dismissed_by': transaction.get('reconciliationDismissedBy'),
                        'previously_dismissed_at': transaction.get('reconciliationDismissedAt')
                    }
                }
                mongo.db.admin_actions.insert_one(admin_action)
                
                return jsonify({
                    'success': True,
                    'message': 'Reconciliation item recovered and moved back to pending queue'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to recover reconciliation item'
                }), 500
                
        except Exception as e:
            print(f'Error recovering reconciliation: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to recover reconciliation',
                'error': str(e)
            }), 500

    @vas_reconciliation_bp.route('/reconciliation/user/<user_email>', methods=['GET'])
    @token_required
    @admin_required
    def get_user_reconciliation_transactions(current_user, user_email):
        """Get reconciliation transactions for a specific user"""
        try:
            # Find user
            user = mongo.db.users.find_one({'email': user_email})
            if not user:
                return jsonify({
                    'success': False,
                    'message': f'User {user_email} not found'
                }), 404
            
            user_id = user['_id']
            
            # Get user's transactions needing reconciliation
            transactions = list(mongo.db.vas_transactions.find({
                'userId': user_id,
                'status': 'NEEDS_RECONCILIATION'
            }).sort('createdAt', -1))
            
            # Get wallet info
            wallet = mongo.db.vas_wallets.find_one({'userId': user_id})
            
            # Convert ObjectIds for JSON serialization
            for txn in transactions:
                txn['_id'] = str(txn['_id'])
                txn['userId'] = str(txn['userId'])
            
            return jsonify({
                'success': True,
                'data': {
                    'user': {
                        'email': user_email,
                        'name': f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(),
                        'id': str(user_id)
                    },
                    'wallet': {
                        'balance': wallet.get('balance', 0) if wallet else 0,
                        'exists': wallet is not None
                    },
                    'transactions': transactions,
                    'count': len(transactions)
                },
                'message': f'Found {len(transactions)} transactions needing reconciliation for {user_email}'
            })
            
        except Exception as e:
            print(f'Error getting user reconciliation transactions: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to get user reconciliation transactions',
                'error': str(e)
            }), 500

    @vas_reconciliation_bp.route('/reconciliation/bulk-resolve', methods=['POST'])
    @token_required
    @admin_required
    def bulk_resolve_reconciliation(current_user):
        """Bulk resolve multiple transactions"""
        try:
            data = request.json
            transaction_ids = data.get('transactionIds', [])
            resolution_status = data.get('status', 'SUCCESS')
            admin_notes = data.get('adminNotes', 'Bulk resolution by admin')
            
            if not transaction_ids:
                return jsonify({
                    'success': False,
                    'message': 'Transaction IDs are required'
                }), 400
            
            if resolution_status not in ['SUCCESS', 'FAILED']:
                return jsonify({
                    'success': False,
                    'message': 'Resolution status must be SUCCESS or FAILED'
                }), 400
            
            # Convert to ObjectIds
            try:
                object_ids = [ObjectId(tid) for tid in transaction_ids]
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid transaction ID format'
                }), 400
            
            # Get transactions
            transactions = list(mongo.db.vas_transactions.find({'_id': {'$in': object_ids}}))
            
            if len(transactions) != len(transaction_ids):
                return jsonify({
                    'success': False,
                    'message': f'Found {len(transactions)} transactions out of {len(transaction_ids)} requested'
                }), 404
            
            # Process each transaction
            results = []
            total_wallet_adjustments = {}
            
            # Process transactions one by one (since resolve_reconciliation_transaction doesn't support sessions)
            for txn in transactions:
                transaction_id = txn['_id']
                user_id = txn['userId']
                
                # Handle wallet adjustments for SUCCESS resolutions
                if resolution_status == 'SUCCESS':
                    wallet = mongo.db.vas_wallets.find_one({'userId': user_id})
                    
                    if wallet:
                        total_amount = txn.get('totalAmount', txn.get('amount', 0))
                        
                        # Check if wallet balance needs adjustment
                        existing_history = wallet.get('transactionHistory', [])
                        transaction_exists = any(
                            hist.get('transactionId') == str(transaction_id) 
                            for hist in existing_history
                        )
                        
                        if not transaction_exists and total_amount > 0:
                            # Apply wallet adjustment immediately
                            new_balance = wallet.get('balance', 0) - total_amount
                            
                            mongo.db.vas_wallets.update_one(
                                {'userId': user_id},
                                {
                                    '$set': {'balance': new_balance, 'updatedAt': datetime.utcnow()},
                                    '$push': {
                                        'transactionHistory': {
                                            'transactionId': str(transaction_id),
                                            'type': 'DEBIT',
                                            'amount': total_amount,
                                            'description': f'Reconciliation: {txn.get("type", "VAS")} - {txn.get("phoneNumber", "N/A")}',
                                            'timestamp': datetime.utcnow(),
                                            'reconciliation': True
                                        }
                                    }
                                }
                            )
                            
                            # Track for summary
                            if user_id not in total_wallet_adjustments:
                                total_wallet_adjustments[user_id] = 0
                            total_wallet_adjustments[user_id] += total_amount
                
                # Resolve the transaction
                success = resolve_reconciliation_transaction(
                    mongo, 
                    transaction_id, 
                    resolution_status, 
                    f"Bulk resolved by admin {current_user.get('email', 'unknown')}: {admin_notes}"
                )
                
                results.append({
                    'transactionId': str(transaction_id),
                    'success': success,
                    'status': resolution_status
                })
            
            # Create admin action log
            admin_action = {
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user.get('email', 'admin'),
                'action': 'bulk_vas_reconciliation',
                'reason': admin_notes,
                'timestamp': datetime.utcnow(),
                'details': {
                    'transactionCount': len(transactions),
                    'transactionIds': transaction_ids,
                    'resolutionStatus': resolution_status,
                    'walletAdjustments': {
                        str(uid): amount 
                        for uid, amount in total_wallet_adjustments.items()
                    },
                    'usersAffected': len(total_wallet_adjustments)
                }
            }
            
            mongo.db.admin_actions.insert_one(admin_action)
            
            successful_resolutions = sum(1 for r in results if r['success'])
            
            return jsonify({
                'success': True,
                'data': {
                    'totalProcessed': len(results),
                    'successful': successful_resolutions,
                    'failed': len(results) - successful_resolutions,
                    'walletAdjustments': len(total_wallet_adjustments),
                    'totalAmountAdjusted': sum(total_wallet_adjustments.values()),
                    'results': results
                },
                'message': f'Bulk resolved {successful_resolutions}/{len(results)} transactions as {resolution_status}'
            })
            
        except Exception as e:
            print(f'Error bulk resolving reconciliation: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to bulk resolve reconciliation',
                'error': str(e)
            }), 500

    return vas_reconciliation_bp