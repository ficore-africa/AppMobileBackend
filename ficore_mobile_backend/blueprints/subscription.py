from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta, timedelta
from bson import ObjectId
import os
import requests
import hmac
import hashlib
import traceback
import uuid

def init_subscription_blueprint(mongo, token_required, serialize_doc):
    from utils.analytics_tracker import create_tracker
    from config.test_accounts import is_test_account, get_paystack_keys
    
    subscription_bp = Blueprint('subscription', __name__, url_prefix='/subscription')
    tracker = create_tracker(mongo.db)
    
    # Paystack configuration (defaults - will be overridden per user)
    PAYSTACK_BASE_URL = 'https://api.paystack.co'
    
    # Subscription plans configuration
    SUBSCRIPTION_PLANS = {
        'monthly': {
            'name': 'Monthly Premium',
            'price': 1000.0,  # ₦1,000 per month
            'duration_days': 30,
            'paystack_plan_code': 'PLN_monthly_premium',
            'description': 'Affordable monthly access to all premium features',
            'features': [
                'Unlimited Income/Expense entries',
                'Full DIICE Business Suite access',
                'Unlimited PDF exports & analytics',
                'All premium features unlocked',
                'Priority support',
                'No FC costs for any operations'
            ]
        },
        'annually': {
            'name': 'Annual Premium',
            'price': 10000.0,  # ₦10,000 per year (Save ₦2,000 vs monthly)
            'duration_days': 365,
            'paystack_plan_code': 'PLN_annual_premium',
            'description': 'Best value - Full access for 365 days',
            'features': [
                'Unlimited Income/Expense entries',
                'Full DIICE Business Suite access',
                'Unlimited PDF exports & analytics',
                'All premium features unlocked',
                'Priority support',
                'No FC costs for any operations',
                'Save ₦2,000 compared to monthly',
                'Less than ₦850 per month'
            ]
        }
    }

    def _make_paystack_request(endpoint, method='GET', data=None, user_email=None):
        """Make authenticated request to Paystack API with test mode support"""
        # Get appropriate keys based on user
        paystack_keys = get_paystack_keys(user_email) if user_email else {
            'secret_key': os.getenv('PAYSTACK_SECRET_KEY'),
            'mode': 'live'
        }
        
        headers = {
            'Authorization': f'Bearer {paystack_keys["secret_key"]}',
            'Content-Type': 'application/json'
        }
        
        url = f"{PAYSTACK_BASE_URL}{endpoint}"
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                response = requests.post(url, headers=headers, json=data)
            elif method == 'PUT':
                response = requests.put(url, headers=headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            result = response.json()
            if paystack_keys['mode'] == 'test':
                print(f"[TEST MODE] Paystack {method} {endpoint}: {result}")
            return result
        except Exception as e:
            print(f"Paystack API error: {str(e)}")
            return {'status': False, 'message': f'Payment service error: {str(e)}'}

    @subscription_bp.route('/plans', methods=['GET'])
    @token_required
    def get_subscription_plans(current_user):
        """Get available subscription plans"""
        try:
            # Get user's current subscription status
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            is_subscribed = user.get('isSubscribed', False)
            current_plan = user.get('subscriptionType')
            
            plans = []
            for plan_id, plan_data in SUBSCRIPTION_PLANS.items():
                plan_info = {
                    'id': plan_id,
                    'name': plan_data['name'],
                    'price': plan_data['price'],
                    'duration_days': plan_data['duration_days'],
                    'description': plan_data['description'],
                    'features': plan_data['features'],
                    'is_current': is_subscribed and current_plan == plan_id,
                    'savings': None
                }
                
                # No savings calculation needed - only one plan available
                # Savings messaging is built into the features list
                
                plans.append(plan_info)
            
            return jsonify({
                'success': True,
                'data': {
                    'plans': plans,
                    'current_subscription': {
                        'is_subscribed': is_subscribed,
                        'plan_type': current_plan,
                        'end_date': user.get('subscriptionEndDate')
                    }
                },
                'message': 'Subscription plans retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve subscription plans',
                'errors': {'general': [str(e)]}
            }), 500

    @subscription_bp.route('/initialize', methods=['POST'])
    @token_required
    def initialize_subscription(current_user):
        """Initialize subscription payment with Paystack (with test mode support)"""
        try:
            data = request.get_json()
            
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_email = user.get('email', '')
            
            # Log incoming request for debugging
            print(f"[SUBSCRIPTION INIT] User: {user_email}")
            print(f"[SUBSCRIPTION INIT] Test mode: {is_test_account(user_email)}")
            print(f"[SUBSCRIPTION INIT] Request data: {data}")
            
            # Validate required fields
            if not data:
                error_msg = 'No JSON data provided in request body'
                print(f"[SUBSCRIPTION INIT ERROR] {error_msg}")
                return jsonify({
                    'success': False,
                    'message': error_msg,
                    'errors': {'request': [error_msg]}
                }), 400
            
            if 'plan_type' not in data:
                error_msg = 'Missing required field: plan_type'
                print(f"[SUBSCRIPTION INIT ERROR] {error_msg}")
                print(f"[SUBSCRIPTION INIT ERROR] Available keys: {list(data.keys())}")
                return jsonify({
                    'success': False,
                    'message': error_msg,
                    'errors': {'plan_type': [error_msg]}
                }), 400
            
            plan_type = data['plan_type']
            if plan_type not in SUBSCRIPTION_PLANS:
                error_msg = f'Invalid subscription plan: {plan_type}'
                print(f"[SUBSCRIPTION INIT ERROR] {error_msg}")
                print(f"[SUBSCRIPTION INIT ERROR] Valid plans: {list(SUBSCRIPTION_PLANS.keys())}")
                return jsonify({
                    'success': False,
                    'message': error_msg,
                    'errors': {'plan_type': [f'Must be one of: {", ".join(SUBSCRIPTION_PLANS.keys())}']}
                }), 400
            
            plan = SUBSCRIPTION_PLANS[plan_type]
            
            # Check if user is already subscribed
            if user.get('isSubscribed', False):
                end_date = user.get('subscriptionEndDate')
                if end_date and end_date > datetime.utcnow():
                    error_msg = 'You already have an active subscription'
                    print(f"[SUBSCRIPTION INIT ERROR] {error_msg} - End date: {end_date}")
                    return jsonify({
                        'success': False,
                        'message': error_msg,
                        'errors': {'subscription': [f'Active until {end_date.isoformat()}']}
                    }), 400
            
            # Initialize Paystack transaction
            reference = f"sub_{current_user['_id']}_{plan_type}_{int(datetime.utcnow().timestamp())}"
            
            # TEST MODE: For test accounts, simulate instant success
            if is_test_account(user_email):
                print(f"[TEST MODE] Simulating subscription payment for {user_email}")
                
                # Store pending subscription
                pending_subscription = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'reference': reference,
                    'planType': plan_type,
                    'amount': plan['price'],
                    'status': 'pending',
                    'createdAt': datetime.utcnow(),
                    'testMode': True
                }
                mongo.db.pending_subscriptions.insert_one(pending_subscription)
                
                # Return mock authorization URL that will auto-verify
                mock_url = f"{request.host_url.rstrip('/')}/subscription/verify-callback?reference={reference}&test_mode=true"
                
                print(f"[TEST MODE] Mock payment URL: {mock_url}")
                
                return jsonify({
                    'success': True,
                    'data': {
                        'authorization_url': mock_url,
                        'access_code': f'TEST_{uuid.uuid4().hex[:10]}',
                        'reference': reference,
                        'test_mode': True
                    },
                    'message': 'Payment initialized successfully (TEST MODE)'
                })
            
            # LIVE MODE: Normal Paystack flow
            paystack_data = {
                'email': user['email'],
                'amount': int(plan['price'] * 100),  # Paystack expects kobo
                'currency': 'NGN',
                'reference': reference,
                'callback_url': f"{request.host_url.rstrip('/')}/subscription/verify-callback?reference={reference}",
                'metadata': {
                    'user_id': str(current_user['_id']),
                    'plan_type': plan_type,
                    'plan_name': plan['name']
                }
            }
            
            print(f"[SUBSCRIPTION INIT] Calling Paystack with data: {paystack_data}")
            paystack_response = _make_paystack_request('/transaction/initialize', 'POST', paystack_data, user_email)
            print(f"[SUBSCRIPTION INIT] Paystack response: {paystack_response}")
            
            if paystack_response.get('status'):
                # Store pending subscription
                pending_subscription = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'reference': paystack_data['reference'],
                    'planType': plan_type,
                    'amount': plan['price'],
                    'status': 'pending',
                    'createdAt': datetime.utcnow(),
                    'paystackData': paystack_response['data']
                }
                
                mongo.db.pending_subscriptions.insert_one(pending_subscription)
                print(f"[SUBSCRIPTION INIT] Success - Reference: {paystack_data['reference']}")
                
                return jsonify({
                    'success': True,
                    'data': {
                        'authorization_url': paystack_response['data']['authorization_url'],
                        'access_code': paystack_response['data']['access_code'],
                        'reference': paystack_data['reference']
                    },
                    'message': 'Payment initialized successfully'
                })
            else:
                error_msg = paystack_response.get('message', 'Failed to initialize payment')
                print(f"[SUBSCRIPTION INIT ERROR] Paystack failed: {error_msg}")
                print(f"[SUBSCRIPTION INIT ERROR] Full response: {paystack_response}")
                return jsonify({
                    'success': False,
                    'message': error_msg,
                    'errors': {'paystack': [error_msg]}
                }), 400

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"[SUBSCRIPTION INIT EXCEPTION] {str(e)}")
            print(f"[SUBSCRIPTION INIT EXCEPTION] Traceback:\n{error_trace}")
            return jsonify({
                'success': False,
                'message': 'Failed to initialize subscription',
                'errors': {
                    'general': [str(e)],
                    'type': type(e).__name__
                }
            }), 500

    @subscription_bp.route('/verify-callback', methods=['GET'])
    def verify_subscription_callback():
        """Handle Paystack redirect callback (no auth required)"""
        try:
            from flask import redirect, render_template
            
            reference = request.args.get('reference')
            
            if not reference:
                # Return HTML page with error
                return render_template('payment_callback.html', 
                                     status='failed', 
                                     error='missing_reference'), 400
            
            print(f"[SUBSCRIPTION CALLBACK] Received callback for reference: {reference}")
            
            # Verify with Paystack
            paystack_response = _make_paystack_request(f'/transaction/verify/{reference}')
            
            if not paystack_response.get('status'):
                print(f"[SUBSCRIPTION CALLBACK] Paystack verification failed: {paystack_response}")
                return render_template('payment_callback.html',
                                     status='failed',
                                     reference=reference,
                                     error='verification_failed'), 400
            
            transaction_data = paystack_response['data']
            
            # Check if payment was successful
            if transaction_data['status'] != 'success':
                print(f"[SUBSCRIPTION CALLBACK] Payment status: {transaction_data['status']}")
                return render_template('payment_callback.html',
                                     status='failed',
                                     reference=reference,
                                     error=transaction_data['status']), 400
            
            # Find pending subscription
            pending_sub = mongo.db.pending_subscriptions.find_one({'reference': reference})
            
            if not pending_sub:
                print(f"[SUBSCRIPTION CALLBACK] Pending subscription not found for reference: {reference}")
                return render_template('payment_callback.html',
                                     status='failed',
                                     reference=reference,
                                     error='not_found'), 404
            
            user_id = pending_sub['userId']
            plan_type = pending_sub['planType']
            plan = SUBSCRIPTION_PLANS[plan_type]
            
            # Activate subscription
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=plan['duration_days'])
            
            # Update user subscription
            mongo.db.users.update_one(
                {'_id': user_id},
                {
                    '$set': {
                        'isSubscribed': True,
                        'subscriptionType': plan_type,
                        'subscriptionStartDate': start_date,
                        'subscriptionEndDate': end_date,
                        'subscriptionAutoRenew': True,
                        'paymentMethodDetails': {
                            'last4': transaction_data.get('authorization', {}).get('last4', ''),
                            'brand': transaction_data.get('authorization', {}).get('brand', ''),
                            'authorization_code': transaction_data.get('authorization', {}).get('authorization_code', '')
                        }
                    }
                }
            )
            
            # Track subscription started event
            try:
                tracker.track_subscription_started(
                    user_id=user_id,
                    subscription_type=plan_type,
                    amount=plan['price']
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            # Create subscription record
            subscription_record = {
                '_id': ObjectId(),
                'userId': user_id,
                'planType': plan_type,
                'amount': plan['price'],
                'startDate': start_date,
                'endDate': end_date,
                'status': 'active',
                'paymentReference': reference,
                'paystackTransactionId': transaction_data['id'],
                'createdAt': datetime.utcnow()
            }
            
            mongo.db.subscriptions.insert_one(subscription_record)
            
            # ==================== REFERRAL SYSTEM: SUBSCRIPTION COMMISSION (NEW - Feb 4, 2026) ====================
            # Check if user was referred and grant commission to referrer
            referral = mongo.db.referrals.find_one({'refereeId': user_id})
            
            if referral and not referral.get('referrerSubCommissionGranted', False):
                print(f'💰 SUBSCRIPTION COMMISSION: User {user_id} subscribed, referred by {referral["referrerId"]}')
                
                # Calculate commission (20% of subscription amount)
                commission_amount = plan['price'] * 0.20  # ₦2,000 for ₦10,000 subscription
                
                # Create payout entry (PENDING status with 7-day vesting)
                payout_doc = {
                    '_id': ObjectId(),
                    'referrerId': referral['referrerId'],
                    'refereeId': user_id,
                    'referralId': referral['_id'],
                    'type': 'SUBSCRIPTION_COMMISSION',
                    'amount': commission_amount,
                    'status': 'PENDING',
                    'vestingStartDate': datetime.utcnow(),
                    'vestingEndDate': datetime.utcnow() + timedelta(days=7),
                    'vestedAt': None,
                    'paidAt': None,
                    'paymentMethod': None,
                    'paymentReference': None,
                    'processedBy': None,
                    'sourceTransaction': reference,
                    'sourceType': 'SUBSCRIPTION',
                    'metadata': {
                        'subscriptionPlan': plan_type,
                        'subscriptionAmount': plan['price'],
                        'commissionRate': 0.20,
                        'vestingDays': 7
                    },
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                }
                mongo.db.referral_payouts.insert_one(payout_doc)
                print(f'✅ Created payout entry: ₦{commission_amount} (PENDING, 7-day vesting)')
                
                # Update referrer's pending balance
                mongo.db.users.update_one(
                    {'_id': referral['referrerId']},
                    {
                        '$inc': {
                            'pendingCommissionBalance': commission_amount,
                            'referralEarnings': commission_amount
                        }
                    }
                )
                print(f'✅ Updated referrer pending balance: +₦{commission_amount}')
                
                # Log to corporate_revenue (as expense)
                corporate_revenue_doc = {
                    '_id': ObjectId(),
                    'type': 'REFERRAL_PAYOUT',
                    'category': 'PARTNER_COMMISSION',
                    'amount': -commission_amount,  # Negative (expense for FiCore)
                    'userId': referral['referrerId'],
                    'relatedTransaction': reference,
                    'description': f'Subscription commission for referrer {referral["referrerId"]}',
                    'status': 'PENDING',
                    'metadata': {
                        'referrerId': str(referral['referrerId']),
                        'refereeId': str(user_id),
                        'payoutType': 'SUBSCRIPTION_COMMISSION',
                        'commissionRate': 0.20,
                        'sourceAmount': plan['price'],
                        'vestingEndDate': (datetime.utcnow() + timedelta(days=7)).isoformat()
                    },
                    'createdAt': datetime.utcnow()
                }
                mongo.db.corporate_revenue.insert_one(corporate_revenue_doc)
                print(f'💰 Corporate revenue logged: -₦{commission_amount} (PENDING)')
                
                # Update referral record
                mongo.db.referrals.update_one(
                    {'_id': referral['_id']},
                    {
                        '$set': {
                            'firstSubscriptionDate': datetime.utcnow(),
                            'qualifiedDate': datetime.utcnow(),
                            'referrerSubCommissionGranted': True,
                            'status': 'qualified',
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                print(f'✅ Updated referral status to QUALIFIED')
                
                print(f'🎉 SUBSCRIPTION COMMISSION COMPLETE: Referrer will receive ₦{commission_amount} in 7 days')
            
            # ==================== END REFERRAL SYSTEM ====================
            
            # Record corporate revenue
            corporate_revenue = {
                '_id': ObjectId(),
                'type': 'SUBSCRIPTION',
                'category': 'MONTHLY' if plan_type == 'monthly' else 'ANNUAL',
                'amount': plan['price'],
                'userId': user_id,
                'relatedTransaction': reference,
                'description': f'{plan["name"]} subscription payment',
                'status': 'RECORDED',
                'createdAt': datetime.utcnow(),
                # 💰 UNIT ECONOMICS TRACKING (Phase 2)
                'gatewayFee': round(plan['price'] * 0.016, 2),  # 1.6% Paystack fee
                'gatewayProvider': 'paystack',
                'netRevenue': round(plan['price'] * 0.984, 2),  # Net after gateway fee
                'metadata': {
                    'planType': plan_type,
                    'planName': plan['name'],
                    'durationDays': plan['duration_days'],
                    'paystackTransactionId': transaction_data['id'],
                    'gatewayFeePercentage': 1.6
                }
            }
            mongo.db.corporate_revenue.insert_one(corporate_revenue)
            print(f'💰 Corporate revenue recorded: ₦{plan["price"]} subscription (net: ₦{plan["price"] * 0.984:.2f} after gateway) - User {user_id}')
            
            # Update pending subscription status
            mongo.db.pending_subscriptions.update_one(
                {'_id': pending_sub['_id']},
                {'$set': {'status': 'completed', 'completedAt': datetime.utcnow()}}
            )
            
            print(f"[SUBSCRIPTION CALLBACK] Subscription activated successfully for user: {user_id}")
            
            # Return HTML page with success (includes deep link redirect)
            return render_template('payment_callback.html',
                                 status='success',
                                 reference=reference,
                                 plan=plan_type)

        except Exception as e:
            print(f"[SUBSCRIPTION CALLBACK ERROR] {str(e)}")
            print(f"[SUBSCRIPTION CALLBACK ERROR] Traceback:\n{traceback.format_exc()}")
            return render_template('payment_callback.html',
                                 status='failed',
                                 error='server_error'), 500

    @subscription_bp.route('/verify/<reference>', methods=['GET'])
    @token_required
    def verify_subscription_payment(current_user, reference):
        """Verify subscription payment with Paystack (authenticated endpoint for manual verification)"""
        try:
            print(f"[SUBSCRIPTION VERIFY] User {current_user.get('email')} verifying reference: {reference}")
            
            # Verify with Paystack
            paystack_response = _make_paystack_request(f'/transaction/verify/{reference}')
            
            if not paystack_response.get('status'):
                return jsonify({
                    'success': False,
                    'message': 'Payment verification failed'
                }), 400
            
            transaction_data = paystack_response['data']
            
            # Check if payment was successful
            if transaction_data['status'] != 'success':
                return jsonify({
                    'success': False,
                    'message': f"Payment {transaction_data['status']}"
                }), 400
            
            # Find pending subscription
            pending_sub = mongo.db.pending_subscriptions.find_one({
                'reference': reference,
                'userId': current_user['_id']
            })
            
            if not pending_sub:
                return jsonify({
                    'success': False,
                    'message': 'Subscription record not found'
                }), 404
            
            plan_type = pending_sub['planType']
            plan = SUBSCRIPTION_PLANS[plan_type]
            
            # Check if already activated
            if pending_sub.get('status') == 'completed':
                # Return existing subscription details
                user = mongo.db.users.find_one({'_id': current_user['_id']})
                return jsonify({
                    'success': True,
                    'data': {
                        'subscription_type': user.get('subscriptionType'),
                        'start_date': user.get('subscriptionStartDate').isoformat() + 'Z' if user.get('subscriptionStartDate') else None,
                        'end_date': user.get('subscriptionEndDate').isoformat() + 'Z' if user.get('subscriptionEndDate') else None,
                        'plan_name': plan['name']
                    },
                    'message': 'Subscription already activated'
                })
            
            # Activate subscription
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=plan['duration_days'])
            
            # Update user subscription
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {
                    '$set': {
                        'isSubscribed': True,
                        'subscriptionType': plan_type,
                        'subscriptionStartDate': start_date,
                        'subscriptionEndDate': end_date,
                        'subscriptionAutoRenew': True,
                        'paymentMethodDetails': {
                            'last4': transaction_data.get('authorization', {}).get('last4', ''),
                            'brand': transaction_data.get('authorization', {}).get('brand', ''),
                            'authorization_code': transaction_data.get('authorization', {}).get('authorization_code', '')
                        }
                    }
                }
            )
            
            # Create subscription record
            subscription_record = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'planType': plan_type,
                'amount': plan['price'],
                'startDate': start_date,
                'endDate': end_date,
                'status': 'active',
                'paymentReference': reference,
                'paystackTransactionId': transaction_data['id'],
                'createdAt': datetime.utcnow()
            }
            
            mongo.db.subscriptions.insert_one(subscription_record)
            
            # Record corporate revenue
            corporate_revenue = {
                '_id': ObjectId(),
                'type': 'SUBSCRIPTION',
                'category': 'MONTHLY' if plan_type == 'monthly' else 'ANNUAL',
                'amount': plan['price'],
                'userId': current_user['_id'],
                'relatedTransaction': reference,
                'description': f'{plan["name"]} subscription payment',
                'status': 'RECORDED',
                'createdAt': datetime.utcnow(),
                # 💰 UNIT ECONOMICS TRACKING (Phase 2)
                'gatewayFee': round(plan['price'] * 0.016, 2),  # 1.6% Paystack fee
                'gatewayProvider': 'paystack',
                'netRevenue': round(plan['price'] * 0.984, 2),  # Net after gateway fee
                'metadata': {
                    'planType': plan_type,
                    'planName': plan['name'],
                    'durationDays': plan['duration_days'],
                    'paystackTransactionId': transaction_data['id'],
                    'gatewayFeePercentage': 1.6
                }
            }
            mongo.db.corporate_revenue.insert_one(corporate_revenue)
            print(f'💰 Corporate revenue recorded: ₦{plan["price"]} subscription (net: ₦{plan["price"] * 0.984:.2f} after gateway) - User {current_user["_id"]}')
            
            # Update pending subscription status
            mongo.db.pending_subscriptions.update_one(
                {'_id': pending_sub['_id']},
                {'$set': {'status': 'completed', 'completedAt': datetime.utcnow()}}
            )
            
            print(f"[SUBSCRIPTION VERIFY] Subscription activated successfully")
            
            return jsonify({
                'success': True,
                'data': {
                    'subscription_type': plan_type,
                    'start_date': start_date.isoformat() + 'Z',
                    'end_date': end_date.isoformat() + 'Z',
                    'plan_name': plan['name']
                },
                'message': f'Subscription activated successfully! Welcome to {plan["name"]}!'
            })

        except Exception as e:
            print(f"[SUBSCRIPTION VERIFY ERROR] {str(e)}")
            print(f"[SUBSCRIPTION VERIFY ERROR] Traceback:\n{traceback.format_exc()}")
            return jsonify({
                'success': False,
                'message': 'Failed to verify subscription payment',
                'errors': {'general': [str(e)]}
            }), 500

    @subscription_bp.route('/status', methods=['GET'])
    @token_required
    def get_subscription_status(current_user):
        """
        Get user's current subscription status
        
        ✅ BACKEND FIX: Now uses MonthlyEntryTracker for real-time validation
        This ensures consistency with /credits/monthly-entries endpoint
        and prevents stale subscription data from being returned
        """
        try:
            from utils.monthly_entry_tracker import MonthlyEntryTracker
            
            # ✅ FIX: Use MonthlyEntryTracker for validated subscription status
            # This provides real-time validation against subscriptionEndDate
            # and corrects any stale isSubscribed flags in the database
            entry_tracker = MonthlyEntryTracker(mongo)
            monthly_stats = entry_tracker.get_monthly_stats(current_user['_id'])
            
            # Extract validated subscription info from monthly stats
            is_subscribed = monthly_stats.get('is_subscribed', False)
            is_admin = monthly_stats.get('is_admin', False)
            subscription_type = monthly_stats.get('subscription_type')
            tier = monthly_stats.get('tier', 'Free')
            
            # Get additional details from user document
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            start_date = user.get('subscriptionStartDate')
            end_date = user.get('subscriptionEndDate')
            auto_renew = user.get('subscriptionAutoRenew', False)
            
            # DISABLED FOR LIQUID WALLET FOCUS
            # print(f"[SUBSCRIPTION_STATUS] User {current_user['_id']}: auto_renew from DB = {auto_renew}")
            
            # Build status response with validated data
            status_data = {
                'is_subscribed': is_subscribed,  # ← VALIDATED by MonthlyEntryTracker
                'subscription_type': subscription_type,
                'tier': tier,  # ← NEW: Consistent with /monthly-entries
                'is_admin': is_admin,  # ← NEW: Consistent with /monthly-entries
                'start_date': start_date.isoformat() + 'Z' if start_date else None,
                'end_date': end_date.isoformat() + 'Z' if end_date else None,
                'auto_renew': auto_renew,
                'days_remaining': None,
                'plan_details': None
            }
            
            # Calculate days remaining if subscribed
            if is_subscribed and end_date:
                days_remaining = (end_date - datetime.utcnow()).days
                status_data['days_remaining'] = max(0, days_remaining)
                
                # ✅ FIX: Add plan ID to plan_details for proper frontend parsing
                if subscription_type and subscription_type in SUBSCRIPTION_PLANS:
                    status_data['plan_details'] = {
                        'id': subscription_type,  # ✅ Add the plan ID
                        **SUBSCRIPTION_PLANS[subscription_type]  # Include all plan fields
                    }
            
            return jsonify({
                'success': True,
                'data': status_data,
                'message': 'Subscription status retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve subscription status',
                'errors': {'general': [str(e)]}
            }), 500

    @subscription_bp.route('/manage', methods=['PUT'])
    @token_required
    def manage_subscription(current_user):
        """Manage subscription settings (auto-renew, etc.)"""
        try:
            from utils.monthly_entry_tracker import MonthlyEntryTracker
            
            data = request.get_json()
            
            # ✅ Use MonthlyEntryTracker for validated subscription status
            entry_tracker = MonthlyEntryTracker(mongo)
            monthly_stats = entry_tracker.get_monthly_stats(current_user['_id'])
            is_subscribed = monthly_stats.get('is_subscribed', False)
            
            if not is_subscribed:
                return jsonify({
                    'success': False,
                    'message': 'No active subscription found'
                }), 404
            
            update_data = {}
            
            if 'auto_renew' in data:
                auto_renew_value = bool(data['auto_renew'])
                update_data['subscriptionAutoRenew'] = auto_renew_value
                
                print(f"[MANAGE_SUBSCRIPTION] User {current_user['_id']} setting auto_renew to {auto_renew_value}")
            
            if update_data:
                result = mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': update_data}
                )
                
                print(f"[MANAGE_SUBSCRIPTION] Update result: matched={result.matched_count}, modified={result.modified_count}")
                
                # ✅ FIX: Return complete subscription status after update
                # This eliminates the need for a separate refresh call and prevents race conditions
                updated_user = mongo.db.users.find_one({'_id': current_user['_id']})
                
                # Get validated subscription info
                start_date = updated_user.get('subscriptionStartDate')
                end_date = updated_user.get('subscriptionEndDate')
                auto_renew = updated_user.get('subscriptionAutoRenew', False)
                subscription_type = updated_user.get('subscriptionType')
                
                print(f"[MANAGE_SUBSCRIPTION] Verified auto_renew value in DB: {auto_renew}")
                
                # Calculate days remaining
                days_remaining = None
                if is_subscribed and end_date:
                    days_remaining = (end_date - datetime.utcnow()).days
                    days_remaining = max(0, days_remaining)
                
                # Build complete status response
                # ✅ FIX: Add plan ID to plan_details for proper frontend parsing
                plan_details = None
                if subscription_type and subscription_type in SUBSCRIPTION_PLANS:
                    plan_details = {
                        'id': subscription_type,  # ✅ Add the plan ID
                        **SUBSCRIPTION_PLANS[subscription_type]  # Include all plan fields
                    }
                
                status_data = {
                    'is_subscribed': is_subscribed,
                    'subscription_type': subscription_type,
                    'tier': monthly_stats.get('tier', 'Free'),
                    'is_admin': monthly_stats.get('is_admin', False),
                    'start_date': start_date.isoformat() + 'Z' if start_date else None,
                    'end_date': end_date.isoformat() + 'Z' if end_date else None,
                    'auto_renew': auto_renew,
                    'days_remaining': days_remaining,
                    'plan_details': plan_details
                }
                
                return jsonify({
                    'success': True,
                    'message': 'Subscription settings updated successfully',
                    'data': status_data
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'No valid fields to update'
                }), 400

        except Exception as e:
            print(f"[MANAGE_SUBSCRIPTION] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to update subscription settings',
                'errors': {'general': [str(e)]}
            }), 500

    @subscription_bp.route('/cancel', methods=['POST'])
    @token_required
    def cancel_subscription(current_user):
        """Cancel subscription (disable auto-renew and create cancellation request)"""
        try:
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            if not user.get('isSubscribed', False):
                return jsonify({
                    'success': False,
                    'message': 'No active subscription found'
                }), 404
            
            # Get optional reason from request body
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            # Disable auto-renew (subscription remains active until end date)
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {'subscriptionAutoRenew': False}}
            )
            
            # Create cancellation request for admin review
            cancellation_request = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'userEmail': user.get('email', ''),
                'userName': user.get('displayName', 'Unknown User'),
                'subscriptionType': user.get('subscriptionType', 'Premium'),
                'subscriptionStartDate': user.get('subscriptionStartDate'),
                'subscriptionEndDate': user.get('subscriptionEndDate'),
                'reason': reason if reason else None,
                'status': 'pending',  # pending, approved, rejected, completed
                'requestedAt': datetime.utcnow(),
                'processedAt': None,
                'processedBy': None,
                'processedByName': None,
                'adminNotes': None,
                'autoRenewDisabled': True
            }
            
            mongo.db.cancellation_requests.insert_one(cancellation_request)
            
            # Track analytics event
            tracker.track_event(
                user_id=current_user['_id'],
                event_type='subscription_cancellation_requested',
                event_details={
                    'subscription_type': user.get('subscriptionType', 'Premium'),
                    'has_reason': bool(reason),
                    'days_until_expiry': (user.get('subscriptionEndDate') - datetime.utcnow()).days if user.get('subscriptionEndDate') else 0
                }
            )
            
            end_date = user.get('subscriptionEndDate')
            
            return jsonify({
                'success': True,
                'data': {
                    'end_date': end_date.isoformat() + 'Z' if end_date else None,
                    'message': 'Your cancellation request has been submitted to our admin team. Auto-renewal has been disabled and you will continue to have access until your subscription expires.',
                    'requestId': str(cancellation_request['_id'])
                },
                'message': 'Subscription cancellation request submitted successfully'
            })

        except Exception as e:
            print(f"Error cancelling subscription: {str(e)}")
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to cancel subscription',
                'errors': {'general': [str(e)]}
            }), 500

    @subscription_bp.route('/webhook', methods=['POST'])
    def paystack_webhook():
        """Handle Paystack webhooks for subscription events"""
        try:
            # Verify webhook signature
            signature = request.headers.get('x-paystack-signature')
            if not signature:
                return jsonify({'status': 'error', 'message': 'No signature'}), 400
            
            payload = request.get_data()
            expected_signature = hmac.new(
                PAYSTACK_SECRET_KEY.encode('utf-8'),
                payload,
                hashlib.sha512
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_signature):
                return jsonify({'status': 'error', 'message': 'Invalid signature'}), 400
            
            event = request.get_json()
            event_type = event.get('event')
            
            if event_type == 'charge.success':
                # Handle successful payment
                data = event['data']
                reference = data.get('reference')
                
                if reference and reference.startswith('sub_'):
                    # This is a subscription payment
                    print(f"Subscription payment successful: {reference}")
                    # Additional processing can be added here
            
            elif event_type == 'subscription.create':
                # Handle subscription creation
                print(f"Subscription created: {event['data']}")
            
            elif event_type == 'subscription.disable':
                # Handle subscription cancellation
                print(f"Subscription disabled: {event['data']}")
            
            return jsonify({'status': 'success'}), 200

        except Exception as e:
            print(f"Webhook error: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    return subscription_bp