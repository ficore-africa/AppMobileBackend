"""
Wallet Subscription Blueprint
Handles premium subscription activation using wallet balance

Phase 5: Dual-Path Payment System
"""
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId


def init_subscription_wallet_blueprint(mongo, token_required):
    """Initialize the wallet subscription blueprint"""
    subscription_wallet_bp = Blueprint('subscription_wallet', __name__)
    
    @subscription_wallet_bp.route('/subscription/activate-via-wallet', methods=['POST'])
    @token_required
    def activate_via_wallet(current_user):
        """
        Activate premium subscription using wallet balance
        
        Body:
            - planId: 'monthly_premium' or 'yearly_premium'
            - paymentMethod: 'wallet'
        
        Returns:
            - 200: Subscription activated successfully
            - 400: Validation error (invalid plan, already subscribed)
            - 402: Insufficient wallet balance
            - 500: Server error
        """
        try:
            data = request.get_json()
            plan_id = data.get('planId')
            
            # Validate plan ID
            if plan_id not in ['monthly_premium', 'yearly_premium']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid plan ID. Must be "monthly_premium" or "yearly_premium"'
                }), 400
            
            # Get plan details
            plan_price = 1000 if plan_id == 'monthly_premium' else 10000
            plan_duration_days = 30 if plan_id == 'monthly_premium' else 365
            plan_type = 'monthly' if plan_id == 'monthly_premium' else 'yearly'
            
            # Check if user already has active subscription
            existing_sub = mongo.db.subscriptions.find_one({
                'userId': current_user['_id'],
                'status': 'active',
                'endDate': {'$gt': datetime.utcnow()}
            })
            
            if existing_sub:
                return jsonify({
                    'success': False,
                    'message': 'You already have an active subscription'
                }), 400

            
            # Get user's current wallet balance
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            wallet_balance = user.get('walletBalance', 0.0)
            
            # Check if user has sufficient balance
            if wallet_balance < plan_price:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient wallet balance. Required: ₦{plan_price:,.2f}, Available: ₦{wallet_balance:,.2f}',
                    'data': {
                        'required': plan_price,
                        'available': wallet_balance,
                        'shortfall': plan_price - wallet_balance
                    }
                }), 402  # Payment Required
            
            # CRITICAL: Debit all 3 wallet fields simultaneously (Golden Rule #38)
            new_balance = wallet_balance - plan_price
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {
                    'walletBalance': new_balance,
                    'liquidWalletBalance': new_balance,
                    'vasWalletBalance': new_balance
                }}
            )
            
            # Create subscription record
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=plan_duration_days)
            
            subscription = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'planId': plan_id,
                'planType': plan_type,
                'amount': plan_price,
                'currency': 'NGN',
                'status': 'active',
                'paymentMethod': 'wallet',
                'paymentReference': f'wallet_{ObjectId()}',
                'startDate': start_date,
                'endDate': end_date,
                'autoRenew': False,  # Wallet payments don't auto-renew
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.subscriptions.insert_one(subscription)
            
            # Log revenue transaction for accounting
            revenue_log = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'type': 'subscription_payment',
                'amount': plan_price,
                'paymentMethod': 'wallet',
                'planId': plan_id,
                'planType': plan_type,
                'subscriptionId': str(subscription['_id']),
                'timestamp': datetime.utcnow(),
                'metadata': {
                    'source': 'wallet_balance',
                    'balanceBefore': wallet_balance,
                    'balanceAfter': new_balance
                }
            }
            
            mongo.db.revenue_logs.insert_one(revenue_log)
            
            # Create wallet transaction record for user's transaction history
            wallet_transaction = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'type': 'debit',
                'amount': plan_price,
                'description': f'Premium subscription ({plan_type})',
                'operation': 'subscription_payment',
                'balanceBefore': wallet_balance,
                'balanceAfter': new_balance,
                'status': 'completed',
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'planId': plan_id,
                    'planType': plan_type,
                    'subscriptionId': str(subscription['_id']),
                    'paymentMethod': 'wallet'
                }
            }
            
            mongo.db.wallet_transactions.insert_one(wallet_transaction)
            
            print(f'✅ Subscription activated via wallet for user {current_user["_id"]}: {plan_id} (₦{plan_price:,.2f})')
            
            return jsonify({
                'success': True,
                'data': {
                    'subscriptionId': str(subscription['_id']),
                    'startDate': start_date.isoformat() + 'Z',
                    'endDate': end_date.isoformat() + 'Z',
                    'planType': plan_type,
                    'planId': plan_id,
                    'amount': plan_price,
                    'paymentMethod': 'wallet',
                    'newWalletBalance': new_balance,
                    'status': 'active',
                    'autoRenew': False
                },
                'message': 'Premium activated successfully! Welcome to FiCore Premium.'
            })
            
        except Exception as e:
            print(f'❌ Error activating subscription via wallet: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to activate subscription',
                'errors': {'general': [str(e)]}
            }), 500
    
    return subscription_wallet_bp
