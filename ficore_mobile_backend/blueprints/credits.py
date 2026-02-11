from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
from werkzeug.utils import secure_filename
import uuid
import os
import base64
import traceback
import requests
import hmac
import hashlib

def init_credits_blueprint(mongo, token_required, serialize_doc):
    from config.test_accounts import is_test_account, get_paystack_keys
    
    credits_bp = Blueprint('credits', __name__, url_prefix='/credits')
    
    # Paystack configuration for FC purchases (defaults - will be overridden per user)
    PAYSTACK_BASE_URL = 'https://api.paystack.co'
    
    # Credit top-up configuration - For NON-SUBSCRIBERS ONLY
    # Premium subscribers (₦10,000/year) get UNLIMITED access without credits
    # Credits are for pay-per-use access to features for non-subscribers
    CREDIT_PACKAGES = [
        {'credits': 5, 'naira': 100, 'tier': 'Starter', 'rate': 20},      # ₦20/FC – Entry level
        {'credits': 10, 'naira': 300, 'tier': 'Baseline', 'rate': 30},    # ₦30/FC – Standard
        {'credits': 50, 'naira': 1500, 'tier': 'Pro', 'rate': 30},        # ₦30/FC – Professional
        {'credits': 100, 'naira': 3000, 'tier': 'Business', 'rate': 30},  # ₦30/FC – Business
        {'credits': 200, 'naira': 5000, 'tier': 'Executive', 'rate': 25}, # ₦25/FC – Bulk saver
    ]
    # NOTE: Removed 200 FCs for ₦10,000 to avoid confusion with Annual Premium subscription
    NAIRA_PER_CREDIT = 30  # Base price: ₦30 per 1 FiCore Credit (bulk discounts available)
    
    # Configure upload settings
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads', 'receipts')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'gif'}
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    
    # Ensure upload directory exists
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    def allowed_file(filename):
        """Check if file extension is allowed"""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

    @credits_bp.route('/topup-options', methods=['GET'])
    @token_required
    def get_topup_options(current_user):
        """Get available credit packages for purchase (for non-subscribers)"""
        try:
            # Check if user is a premium subscriber
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            is_subscribed = user.get('isSubscribed', False)
            
            options = []
            for package in CREDIT_PACKAGES:
                options.append({
                    'creditAmount': package['credits'],
                    'nairaAmount': package['naira'],
                    'tier': package['tier'],
                    'rate': package['rate'],
                    'displayText': f'{package["credits"]} FCs - ₦{package["naira"]:,} ({package["tier"]})'
                })
            
            # Extract allowed Naira amounts for frontend compatibility
            allowed_naira_amounts = [package['naira'] for package in CREDIT_PACKAGES]
            
            return jsonify({
                'success': True,
                'data': {
                    'options': options,
                    'conversionRate': float(NAIRA_PER_CREDIT),
                    'allowedNairaAmounts': allowed_naira_amounts,
                    'pricePerCredit': NAIRA_PER_CREDIT,
                    'packages': CREDIT_PACKAGES,
                    'isSubscribed': is_subscribed,
                    'message': 'Premium subscribers get unlimited access without credits!' if is_subscribed else 'Credits for pay-per-use access'
                },
                'message': 'Credit packages retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve credit packages',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/balance', methods=['GET'])
    @token_required
    def get_credit_balance(current_user):
        """Get user's current FiCore Credits balance"""
        try:
            # Validate user exists and has required fields
            if not current_user or '_id' not in current_user:
                return jsonify({
                    'success': False,
                    'message': 'Invalid user session'
                }), 401

            # Get user's current credit balance with error handling
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Ensure balance is a valid number
            balance = user.get('ficoreCreditBalance', 0.0)
            if not isinstance(balance, (int, float)):
                balance = 0.0
            
            # Get recent credit transactions for context with error handling
            try:
                recent_transactions = list(mongo.db.credit_transactions.find({
                    'userId': current_user['_id']
                }).sort('createdAt', -1).limit(5))
            except Exception as db_error:
                # If transaction query fails, continue with empty list
                recent_transactions = []
                print(f"Warning: Failed to fetch recent transactions: {str(db_error)}")
            
            # Serialize transactions with error handling
            transactions = []
            for transaction in recent_transactions:
                try:
                    trans_data = serialize_doc(transaction.copy())
                    # Ensure createdAt is properly formatted
                    created_at = trans_data.get('createdAt')
                    if isinstance(created_at, datetime):
                        trans_data['createdAt'] = created_at.isoformat() + 'Z'
                    elif created_at is None:
                        trans_data['createdAt'] = datetime.utcnow().isoformat() + 'Z'
                    transactions.append(trans_data)
                except Exception as serialize_error:
                    # Skip problematic transactions
                    print(f"Warning: Failed to serialize transaction: {str(serialize_error)}")
                    continue

            return jsonify({
                'success': True,
                'data': {
                    'balance': float(balance),
                    'formattedBalance': f"{balance:,.0f}",
                    'recentTransactions': transactions,
                    'lastUpdated': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'Credit balance retrieved successfully'
            })

        except Exception as e:
            # Log the error for debugging
            print(f"Error in get_credit_balance: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve credit balance',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/history', methods=['GET'])
    @token_required
    def get_credit_history(current_user):
        """Get user's credit transaction history"""
        try:
            # Get pagination parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            transaction_type = request.args.get('type', 'all')  # all, credit, debit, request
            
            # Build query
            query = {'userId': current_user['_id']}
            if transaction_type != 'all':
                query['type'] = transaction_type

            # Get total count
            total = mongo.db.credit_transactions.count_documents(query)
            
            # Get transactions with pagination
            skip = (page - 1) * limit
            transactions = list(mongo.db.credit_transactions.find(query)
                              .sort('createdAt', -1)
                              .skip(skip)
                              .limit(limit))
            
            # Serialize transactions
            transaction_data = []
            for transaction in transactions:
                trans_data = serialize_doc(transaction.copy())
                trans_data['createdAt'] = trans_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                if 'updatedAt' in trans_data:
                    trans_data['updatedAt'] = trans_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                transaction_data.append(trans_data)

            # Calculate summary statistics
            total_credits = mongo.db.credit_transactions.aggregate([
                {'$match': {'userId': current_user['_id'], 'type': 'credit'}},
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ])
            total_credits = list(total_credits)
            total_credits_amount = total_credits[0]['total'] if total_credits else 0

            total_debits = mongo.db.credit_transactions.aggregate([
                {'$match': {'userId': current_user['_id'], 'type': 'debit'}},
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ])
            total_debits = list(total_debits)
            total_debits_amount = total_debits[0]['total'] if total_debits else 0

            return jsonify({
                'success': True,
                'data': {
                    'transactions': transaction_data,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit,
                        'hasNext': page * limit < total,
                        'hasPrev': page > 1
                    },
                    'summary': {
                        'totalCredits': total_credits_amount,
                        'totalDebits': total_debits_amount,
                        'netBalance': total_credits_amount - total_debits_amount
                    }
                },
                'message': 'Credit history retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve credit history',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/purchase/initialize', methods=['POST'])
    @token_required
    def initialize_credit_purchase(current_user):
        """Initialize automated FC purchase with Paystack (with test mode support)"""
        try:
            data = request.get_json()
            
            # Get user email
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_email = user.get('email', 'user@example.com')
            
            print(f"[CREDITS] Initialize purchase for {user_email}")
            print(f"[CREDITS] Test mode: {is_test_account(user_email)}")
            
            # Validate required fields
            if 'credits' not in data:
                return jsonify({
                    'success': False,
                    'message': 'Missing required field: credits'
                }), 400
            
            credit_amount = float(data['credits'])
            
            # Find the matching package
            selected_package = None
            for package in CREDIT_PACKAGES:
                if package['credits'] == credit_amount:
                    selected_package = package
                    break
            
            if selected_package is None:
                valid_credits = [str(pkg['credits']) for pkg in CREDIT_PACKAGES]
                return jsonify({
                    'success': False,
                    'message': f'Invalid credit amount. Available packages: {", ".join(valid_credits)} FCs'
                }), 400

            naira_amount = selected_package['naira']
            
            # Create transaction reference
            transaction_ref = f"fc_purchase_{current_user['_id']}_{uuid.uuid4().hex[:8]}"
            
            # ==================== TEST MODE CHECK ====================
            # For Google Play review test accounts, simulate instant success
            if is_test_account(user_email):
                print(f'[TEST MODE] Simulating credit purchase for {user_email}')
                print(f'[TEST MODE] Credits: {credit_amount}, Amount: ₦{naira_amount}')
                
                # Store pending transaction
                pending_transaction = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'transactionRef': transaction_ref,
                    'paystackRef': f'TEST_{uuid.uuid4().hex[:10]}',
                    'accessCode': f'TEST_{uuid.uuid4().hex[:10]}',
                    'creditAmount': credit_amount,
                    'nairaAmount': naira_amount,
                    'status': 'pending',
                    'paymentMethod': 'paystack_test',
                    'testMode': True,
                    'createdAt': datetime.utcnow(),
                    'expiresAt': datetime.utcnow() + timedelta(minutes=15)
                }
                
                mongo.db.pending_credit_purchases.insert_one(pending_transaction)
                
                # Return mock authorization URL
                mock_url = f"{request.host_url.rstrip('/')}/credits/verify-callback?reference={transaction_ref}&test_mode=true"
                
                print(f'[TEST MODE] Mock payment URL: {mock_url}')
                
                return jsonify({
                    'success': True,
                    'data': {
                        'transactionRef': transaction_ref,
                        'paystackRef': pending_transaction['paystackRef'],
                        'accessCode': pending_transaction['accessCode'],
                        'authorizationUrl': mock_url,
                        'creditAmount': credit_amount,
                        'nairaAmount': naira_amount,
                        'testMode': True
                    },
                    'message': 'Payment initialized successfully (TEST MODE)'
                }), 200
            # ==================== END TEST MODE CHECK ====================
            
            # LIVE MODE: Normal Paystack flow
            # Initialize Paystack transaction
            paystack_data = {
                'email': user_email,
                'amount': int(naira_amount * 100),  # Paystack expects kobo
                'reference': transaction_ref,
                'currency': 'NGN',
                'callback_url': data.get('callback_url', ''),
                'metadata': {
                    'user_id': str(current_user['_id']),
                    'credit_amount': credit_amount,
                    'naira_amount': naira_amount,
                    'package_type': 'fc_purchase'
                }
            }
            
            paystack_response = _make_paystack_request('/transaction/initialize', 'POST', paystack_data, user_email)
            
            if not paystack_response.get('status'):
                return jsonify({
                    'success': False,
                    'message': 'Failed to initialize payment',
                    'errors': {'payment': [paystack_response.get('message', 'Payment service error')]}
                }), 400
            
            # Store pending transaction
            pending_transaction = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'transactionRef': transaction_ref,
                'paystackRef': paystack_response['data']['reference'],
                'accessCode': paystack_response['data']['access_code'],
                'creditAmount': credit_amount,
                'nairaAmount': naira_amount,
                'status': 'pending',
                'paymentMethod': 'paystack',
                'createdAt': datetime.utcnow(),
                'expiresAt': datetime.utcnow() + timedelta(minutes=15)  # 15 min expiry
            }
            
            mongo.db.pending_credit_purchases.insert_one(pending_transaction)
            
            return jsonify({
                'success': True,
                'data': {
                    'transactionRef': transaction_ref,
                    'paystackRef': paystack_response['data']['reference'],
                    'accessCode': paystack_response['data']['access_code'],
                    'authorizationUrl': paystack_response['data']['authorization_url'],
                    'creditAmount': credit_amount,
                    'nairaAmount': naira_amount,
                    'expiresAt': pending_transaction['expiresAt'].isoformat() + 'Z'
                },
                'message': 'Payment initialized successfully'
            })
            
        except ValueError as e:
            return jsonify({
                'success': False,
                'message': 'Invalid credit amount format'
            }), 400
        except Exception as e:
            print(f"Error initializing credit purchase: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to initialize credit purchase',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/purchase/verify', methods=['POST'])
    @token_required
    def verify_credit_purchase(current_user):
        """Verify Paystack payment and credit user account"""
        try:
            data = request.get_json()
            
            if 'reference' not in data:
                return jsonify({
                    'success': False,
                    'message': 'Missing payment reference'
                }), 400
            
            reference = data['reference']
            
            # Find pending transaction
            pending_transaction = mongo.db.pending_credit_purchases.find_one({
                'userId': current_user['_id'],
                'paystackRef': reference,
                'status': 'pending'
            })
            
            if not pending_transaction:
                return jsonify({
                    'success': False,
                    'message': 'Transaction not found or already processed'
                }), 404
            
            # Check if transaction has expired
            if datetime.utcnow() > pending_transaction['expiresAt']:
                mongo.db.pending_credit_purchases.update_one(
                    {'_id': pending_transaction['_id']},
                    {'$set': {'status': 'expired'}}
                )
                return jsonify({
                    'success': False,
                    'message': 'Transaction has expired'
                }), 400
            
            # Verify payment with Paystack
            paystack_response = _make_paystack_request(f'/transaction/verify/{reference}')
            
            if not paystack_response.get('status'):
                return jsonify({
                    'success': False,
                    'message': 'Payment verification failed',
                    'errors': {'payment': [paystack_response.get('message', 'Verification error')]}
                }), 400
            
            payment_data = paystack_response['data']
            
            # Check payment status
            if payment_data['status'] != 'success':
                mongo.db.pending_credit_purchases.update_one(
                    {'_id': pending_transaction['_id']},
                    {'$set': {'status': 'failed', 'failureReason': payment_data.get('gateway_response', 'Payment failed')}}
                )
                return jsonify({
                    'success': False,
                    'message': f'Payment failed: {payment_data.get("gateway_response", "Unknown error")}'
                }), 400
            
            # Verify amount matches
            expected_amount = int(pending_transaction['nairaAmount'] * 100)  # Convert to kobo
            if payment_data['amount'] != expected_amount:
                return jsonify({
                    'success': False,
                    'message': 'Payment amount mismatch'
                }), 400
            
            # Credit user account
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            current_balance = user.get('ficoreCreditBalance', 0.0)
            new_balance = current_balance + pending_transaction['creditAmount']
            
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {'ficoreCreditBalance': new_balance}}
            )
            
            # Create completed transaction record
            transaction = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'type': 'credit',
                'amount': pending_transaction['creditAmount'],
                'nairaAmount': pending_transaction['nairaAmount'],
                'description': f'FC purchase via Paystack - {pending_transaction["creditAmount"]} FCs',
                'status': 'completed',
                'paymentMethod': 'paystack',
                'paymentReference': reference,
                'paystackTransactionId': payment_data.get('id'),
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'purchaseType': 'paystack_automated',
                    'paystackData': {
                        'transaction_id': payment_data.get('id'),
                        'gateway_response': payment_data.get('gateway_response'),
                        'paid_at': payment_data.get('paid_at'),
                        'channel': payment_data.get('channel')
                    }
                }
            }
            
            mongo.db.credit_transactions.insert_one(transaction)
            
            # Record corporate revenue
            corporate_revenue = {
                '_id': ObjectId(),
                'type': 'CREDITS_PURCHASE',
                'category': 'FICORE_CREDITS',
                'amount': pending_transaction['nairaAmount'],
                'userId': current_user['_id'],
                'relatedTransaction': reference,
                'description': f'FiCore Credits purchase - {pending_transaction["creditAmount"]} FCs',
                'status': 'RECORDED',
                'createdAt': datetime.utcnow(),
                # 💰 UNIT ECONOMICS TRACKING (Phase 2)
                'gatewayFee': round(pending_transaction['nairaAmount'] * 0.016, 2),  # 1.6% Paystack fee
                'gatewayProvider': 'paystack',
                'netRevenue': round(pending_transaction['nairaAmount'] * 0.984, 2),  # Net after gateway fee
                'metadata': {
                    'creditAmount': pending_transaction['creditAmount'],
                    'nairaAmount': pending_transaction['nairaAmount'],
                    'paystackTransactionId': payment_data.get('id'),
                    'paymentChannel': payment_data.get('channel'),
                    'gatewayFeePercentage': 1.6
                }
            }
            mongo.db.corporate_revenue.insert_one(corporate_revenue)
            print(f'💰 Corporate revenue recorded: ₦{pending_transaction["nairaAmount"]} credits (net: ₦{pending_transaction["nairaAmount"] * 0.984:.2f} after gateway) - User {current_user["_id"]}')
            
            # Mark pending transaction as completed
            mongo.db.pending_credit_purchases.update_one(
                {'_id': pending_transaction['_id']},
                {
                    '$set': {
                        'status': 'completed',
                        'completedAt': datetime.utcnow(),
                        'transactionId': str(transaction['_id'])
                    }
                }
            )
            
            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(transaction['_id']),
                    'creditAmount': pending_transaction['creditAmount'],
                    'nairaAmount': pending_transaction['nairaAmount'],
                    'previousBalance': current_balance,
                    'newBalance': new_balance,
                    'paymentReference': reference
                },
                'message': f'Payment successful! {pending_transaction["creditAmount"]} FCs added to your account'
            })
            
        except Exception as e:
            print(f"Error verifying credit purchase: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to verify payment',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/purchase/status/<reference>', methods=['GET'])
    @token_required
    def get_purchase_status(current_user, reference):
        """Get status of a credit purchase transaction"""
        try:
            # Check pending transactions first
            pending_transaction = mongo.db.pending_credit_purchases.find_one({
                'userId': current_user['_id'],
                'paystackRef': reference
            })
            
            if pending_transaction:
                transaction_data = serialize_doc(pending_transaction.copy())
                transaction_data['createdAt'] = transaction_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                transaction_data['expiresAt'] = transaction_data.get('expiresAt', datetime.utcnow()).isoformat() + 'Z'
                
                return jsonify({
                    'success': True,
                    'data': {
                        'status': transaction_data['status'],
                        'transaction': transaction_data
                    },
                    'message': 'Transaction status retrieved'
                })
            
            # Check completed transactions
            completed_transaction = mongo.db.credit_transactions.find_one({
                'userId': current_user['_id'],
                'paymentReference': reference
            })
            
            if completed_transaction:
                transaction_data = serialize_doc(completed_transaction.copy())
                transaction_data['createdAt'] = transaction_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                
                return jsonify({
                    'success': True,
                    'data': {
                        'status': 'completed',
                        'transaction': transaction_data
                    },
                    'message': 'Transaction completed'
                })
            
            return jsonify({
                'success': False,
                'message': 'Transaction not found'
            }), 404
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get transaction status',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/verify-callback', methods=['GET'])
    def verify_credit_callback():
        """Handle Paystack redirect callback for credit purchases (no auth required)"""
        try:
            from flask import redirect, render_template
            
            reference = request.args.get('reference')
            test_mode = request.args.get('test_mode', 'false').lower() == 'true'
            
            if not reference:
                # Return HTML page with error
                return render_template('payment_callback.html', 
                                     status='failed', 
                                     error='missing_reference'), 400
            
            print(f"[CREDITS CALLBACK] Received callback for reference: {reference}, test_mode: {test_mode}")
            
            # Find pending transaction by transactionRef (not paystackRef)
            pending_transaction = mongo.db.pending_credit_purchases.find_one({
                'transactionRef': reference
            })
            
            if not pending_transaction:
                print(f"[CREDITS CALLBACK] Pending transaction not found for reference: {reference}")
                return render_template('payment_callback.html',
                                     status='failed',
                                     reference=reference,
                                     error='not_found'), 404
            
            # Check if already processed
            if pending_transaction['status'] != 'pending':
                print(f"[CREDITS CALLBACK] Transaction already processed: {pending_transaction['status']}")
                return render_template('payment_callback.html',
                                     status=pending_transaction['status'],
                                     reference=reference,
                                     message='Transaction already processed'), 200
            
            user_id = pending_transaction['userId']
            credit_amount = pending_transaction['creditAmount']
            naira_amount = pending_transaction['nairaAmount']
            
            # ==================== TEST MODE AUTO-COMPLETE ====================
            if test_mode or pending_transaction.get('testMode', False):
                print(f'[TEST MODE] Auto-completing credit purchase for user {user_id}')
                
                # Get current user balance
                user = mongo.db.users.find_one({'_id': user_id})
                current_balance = user.get('ficoreCreditBalance', 0.0)
                new_balance = current_balance + credit_amount
                
                # Update user balance
                mongo.db.users.update_one(
                    {'_id': user_id},
                    {'$set': {'ficoreCreditBalance': new_balance}}
                )
                
                # Create completed transaction record
                transaction = {
                    '_id': ObjectId(),
                    'userId': user_id,
                    'type': 'credit',
                    'amount': credit_amount,
                    'nairaAmount': naira_amount,
                    'description': f'FC purchase (TEST MODE) - {credit_amount} FCs',
                    'status': 'completed',
                    'paymentMethod': 'paystack_test',
                    'paymentReference': pending_transaction['paystackRef'],
                    'balanceBefore': current_balance,
                    'balanceAfter': new_balance,
                    'createdAt': datetime.utcnow(),
                    'metadata': {
                        'purchaseType': 'test_mode_auto',
                        'testMode': True
                    }
                }
                
                mongo.db.credit_transactions.insert_one(transaction)
                
                # Mark pending transaction as completed
                mongo.db.pending_credit_purchases.update_one(
                    {'_id': pending_transaction['_id']},
                    {
                        '$set': {
                            'status': 'completed',
                            'completedAt': datetime.utcnow(),
                            'transactionId': str(transaction['_id'])
                        }
                    }
                )
                
                print(f'[TEST MODE] Credit purchase completed: {credit_amount} FCs added to user {user_id}')
                
                # Return success page
                return render_template('payment_callback.html',
                                     status='success',
                                     reference=reference,
                                     amount=f'{credit_amount} FCs',
                                     test_mode=True,
                                     message=f'Payment successful! {credit_amount} FCs have been added to your account.'), 200
            
            # ==================== LIVE MODE: VERIFY WITH PAYSTACK ====================
            paystack_ref = pending_transaction['paystackRef']
            
            # Get user email for Paystack key selection
            user = mongo.db.users.find_one({'_id': user_id})
            user_email = user.get('email', 'user@example.com')
            
            # Verify with Paystack
            paystack_response = _make_paystack_request(f'/transaction/verify/{paystack_ref}', user_email=user_email)
            
            if not paystack_response.get('status'):
                print(f"[CREDITS CALLBACK] Paystack verification failed: {paystack_response}")
                return render_template('payment_callback.html',
                                     status='failed',
                                     reference=reference,
                                     error='verification_failed'), 400
            
            transaction_data = paystack_response['data']
            
            # Check if payment was successful
            if transaction_data['status'] != 'success':
                print(f"[CREDITS CALLBACK] Payment status: {transaction_data['status']}")
                
                # Mark as failed
                mongo.db.pending_credit_purchases.update_one(
                    {'_id': pending_transaction['_id']},
                    {'$set': {'status': 'failed', 'failureReason': transaction_data.get('gateway_response', 'Payment failed')}}
                )
                
                return render_template('payment_callback.html',
                                     status='failed',
                                     reference=reference,
                                     error=transaction_data['status']), 400
            
            # Verify amount matches
            expected_amount = int(naira_amount * 100)  # Convert to kobo
            if transaction_data['amount'] != expected_amount:
                print(f"[CREDITS CALLBACK] Amount mismatch: expected {expected_amount}, got {transaction_data['amount']}")
                return render_template('payment_callback.html',
                                     status='failed',
                                     reference=reference,
                                     error='amount_mismatch'), 400
            
            # Credit user account
            current_balance = user.get('ficoreCreditBalance', 0.0)
            new_balance = current_balance + credit_amount
            
            mongo.db.users.update_one(
                {'_id': user_id},
                {'$set': {'ficoreCreditBalance': new_balance}}
            )
            
            # Create completed transaction record
            transaction = {
                '_id': ObjectId(),
                'userId': user_id,
                'type': 'credit',
                'amount': credit_amount,
                'nairaAmount': naira_amount,
                'description': f'FC purchase via Paystack - {credit_amount} FCs',
                'status': 'completed',
                'paymentMethod': 'paystack',
                'paymentReference': paystack_ref,
                'paystackTransactionId': transaction_data.get('id'),
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'purchaseType': 'paystack_callback',
                    'paystackData': {
                        'transaction_id': transaction_data.get('id'),
                        'gateway_response': transaction_data.get('gateway_response'),
                        'paid_at': transaction_data.get('paid_at'),
                        'channel': transaction_data.get('channel')
                    }
                }
            }
            
            mongo.db.credit_transactions.insert_one(transaction)
            
            # Record corporate revenue
            corporate_revenue = {
                '_id': ObjectId(),
                'type': 'CREDITS_PURCHASE',
                'category': 'FICORE_CREDITS',
                'amount': naira_amount,
                'userId': user_id,
                'relatedTransaction': paystack_ref,
                'description': f'FiCore Credits purchase - {credit_amount} FCs (callback)',
                'status': 'RECORDED',
                'createdAt': datetime.utcnow(),
                'gatewayFee': round(naira_amount * 0.016, 2),
                'gatewayProvider': 'paystack',
                'netRevenue': round(naira_amount * 0.984, 2),
                'metadata': {
                    'creditAmount': credit_amount,
                    'nairaAmount': naira_amount,
                    'paystackTransactionId': transaction_data.get('id'),
                    'paymentChannel': transaction_data.get('channel'),
                    'gatewayFeePercentage': 1.6
                }
            }
            mongo.db.corporate_revenue.insert_one(corporate_revenue)
            print(f'💰 Corporate revenue recorded: ₦{naira_amount} credits (net: ₦{naira_amount * 0.984:.2f} after gateway) via callback - User {user_id}')
            
            # Mark pending transaction as completed
            mongo.db.pending_credit_purchases.update_one(
                {'_id': pending_transaction['_id']},
                {
                    '$set': {
                        'status': 'completed',
                        'completedAt': datetime.utcnow(),
                        'transactionId': str(transaction['_id'])
                    }
                }
            )
            
            print(f'[CREDITS CALLBACK] Credit purchase completed: {credit_amount} FCs added to user {user_id}')
            
            # Return success page
            return render_template('payment_callback.html',
                                 status='success',
                                 reference=reference,
                                 amount=f'{credit_amount} FCs',
                                 message=f'Payment successful! {credit_amount} FCs have been added to your account.'), 200
            
        except Exception as e:
            print(f"[CREDITS CALLBACK] Error: {str(e)}")
            traceback.print_exc()
            return render_template('payment_callback.html',
                                 status='failed',
                                 error='processing_error',
                                 message=str(e)), 500

    @credits_bp.route('/webhook/paystack', methods=['POST'])
    def paystack_webhook():
        """Handle Paystack webhook notifications"""
        try:
            # Verify webhook signature
            signature = request.headers.get('X-Paystack-Signature')
            if not signature:
                return jsonify({'error': 'No signature provided'}), 400
            
            # Compute expected signature
            payload = request.get_data()
            expected_signature = hmac.new(
                PAYSTACK_SECRET_KEY.encode('utf-8'),
                payload,
                hashlib.sha512
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_signature):
                return jsonify({'error': 'Invalid signature'}), 400
            
            # Process webhook event
            event_data = request.get_json()
            event_type = event_data.get('event')
            
            if event_type == 'charge.success':
                data = event_data['data']
                reference = data['reference']
                
                # Find pending transaction
                pending_transaction = mongo.db.pending_credit_purchases.find_one({
                    'paystackRef': reference,
                    'status': 'pending'
                })
                
                if pending_transaction:
                    # Process the successful payment
                    user_id = pending_transaction['userId']
                    credit_amount = pending_transaction['creditAmount']
                    
                    # Update user balance
                    user = mongo.db.users.find_one({'_id': user_id})
                    current_balance = user.get('ficoreCreditBalance', 0.0)
                    new_balance = current_balance + credit_amount
                    
                    mongo.db.users.update_one(
                        {'_id': user_id},
                        {'$set': {'ficoreCreditBalance': new_balance}}
                    )
                    
                    # Create transaction record
                    transaction = {
                        '_id': ObjectId(),
                        'userId': user_id,
                        'type': 'credit',
                        'amount': credit_amount,
                        'nairaAmount': pending_transaction['nairaAmount'],
                        'description': f'FC purchase via Paystack webhook - {credit_amount} FCs',
                        'status': 'completed',
                        'paymentMethod': 'paystack',
                        'paymentReference': reference,
                        'paystackTransactionId': data.get('id'),
                        'balanceBefore': current_balance,
                        'balanceAfter': new_balance,
                        'createdAt': datetime.utcnow(),
                        'metadata': {
                            'purchaseType': 'paystack_webhook',
                            'webhookEvent': event_type
                        }
                    }
                    
                    mongo.db.credit_transactions.insert_one(transaction)
                    
                    # Record corporate revenue
                    corporate_revenue = {
                        '_id': ObjectId(),
                        'type': 'CREDITS_PURCHASE',
                        'category': 'FICORE_CREDITS',
                        'amount': pending_transaction['nairaAmount'],
                        'userId': user_id,
                        'relatedTransaction': reference,
                        'description': f'FiCore Credits purchase - {credit_amount} FCs (webhook)',
                        'status': 'RECORDED',
                        'createdAt': datetime.utcnow(),
                        # 💰 UNIT ECONOMICS TRACKING (Phase 2)
                        'gatewayFee': round(pending_transaction['nairaAmount'] * 0.016, 2),  # 1.6% Paystack fee
                        'gatewayProvider': 'paystack',
                        'netRevenue': round(pending_transaction['nairaAmount'] * 0.984, 2),  # Net after gateway fee
                        'metadata': {
                            'creditAmount': credit_amount,
                            'nairaAmount': pending_transaction['nairaAmount'],
                            'paystackTransactionId': data.get('id'),
                            'webhookEvent': event_type,
                            'gatewayFeePercentage': 1.6
                        }
                    }
                    mongo.db.corporate_revenue.insert_one(corporate_revenue)
                    print(f'💰 Corporate revenue recorded: ₦{pending_transaction["nairaAmount"]} credits (net: ₦{pending_transaction["nairaAmount"] * 0.984:.2f} after gateway) via webhook - User {user_id}')
                    
                    # Mark pending transaction as completed
                    mongo.db.pending_credit_purchases.update_one(
                        {'_id': pending_transaction['_id']},
                        {
                            '$set': {
                                'status': 'completed',
                                'completedAt': datetime.utcnow(),
                                'transactionId': str(transaction['_id'])
                            }
                        }
                    )
            
            return jsonify({'status': 'success'}), 200
            
        except Exception as e:
            print(f"Webhook error: {str(e)}")
            return jsonify({'error': 'Webhook processing failed'}), 500

    @credits_bp.route('/request', methods=['POST'])
    @token_required
    def create_credit_request(current_user):
        """Submit a new credit top-up request"""
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['amount', 'paymentMethod']
            for field in required_fields:
                if field not in data or not data[field]:
                    return jsonify({
                        'success': False,
                        'message': f'Missing required field: {field}',
                        'errors': {field: ['This field is required']}
                    }), 400

            # The 'amount' field now represents the FiCore Credits selected by the user
            credit_amount = float(data['amount'])
            
            # Find the matching package
            selected_package = None
            for package in CREDIT_PACKAGES:
                if package['credits'] == credit_amount:
                    selected_package = package
                    break
            
            if selected_package is None:
                valid_credits = [str(pkg['credits']) for pkg in CREDIT_PACKAGES]
                return jsonify({
                    'success': False,
                    'message': f'Invalid credit amount. Available packages: {", ".join(valid_credits)} FCs',
                    'errors': {'amount': [f'Credit amount must be one of: {", ".join(valid_credits)} FCs']}
                }), 400

            naira_amount = selected_package['naira']

            # Create credit request
            credit_request = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'requestId': str(uuid.uuid4()),
                'amount': credit_amount,  # Store FiCore Credit amount
                'nairaAmount': naira_amount,  # Store original Naira amount
                'paymentMethod': data['paymentMethod'],
                'paymentReference': data.get('paymentReference', ''),
                'receiptUrl': data.get('receiptUrl', ''),
                'notes': data.get('notes', ''),
                'status': 'pending',  # pending, approved, rejected, processing
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
                'processedBy': None,
                'processedAt': None,
                'rejectionReason': None
            }

            # Insert credit request
            result = mongo.db.credit_requests.insert_one(credit_request)
            
            # Create transaction record
            transaction = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'requestId': credit_request['requestId'],
                'type': 'credit',
                'amount': credit_amount,  # Store FiCore Credit amount
                'nairaAmount': naira_amount,  # Store original Naira amount
                'description': f'Credit top-up request for {credit_amount:.1f} FCs ({naira_amount:.0f} NGN) - {data["paymentMethod"]}',
                'status': 'pending',
                'paymentMethod': data['paymentMethod'],
                'paymentReference': data.get('paymentReference', ''),
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'requestType': 'topup',
                    'paymentMethod': data['paymentMethod'],
                    'nairaAmount': naira_amount,
                    'creditAmount': credit_amount
                }
            }
            
            mongo.db.credit_transactions.insert_one(transaction)

            # Return created request
            credit_request = serialize_doc(credit_request)
            credit_request['createdAt'] = credit_request.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            credit_request['updatedAt'] = credit_request.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'

            return jsonify({
                'success': True,
                'data': credit_request,
                'message': f'Credit request submitted successfully for {credit_amount:.1f} FCs ({naira_amount:.0f} NGN)'
            }), 201

        except ValueError as e:
            return jsonify({
                'success': False,
                'message': 'Invalid amount format',
                'errors': {'amount': ['Please enter a valid number']}
            }), 400
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to create credit request',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/request/<request_id>', methods=['PUT'])
    @token_required
    def update_credit_request(current_user, request_id):
        """Update a credit request (user can only update their own pending requests)"""
        try:
            data = request.get_json()
            
            # Find the credit request
            credit_request = mongo.db.credit_requests.find_one({
                'requestId': request_id,
                'userId': current_user['_id']
            })
            
            if not credit_request:
                return jsonify({
                    'success': False,
                    'message': 'Credit request not found'
                }), 404

            # Only allow updates to pending requests
            if credit_request['status'] != 'pending':
                return jsonify({
                    'success': False,
                    'message': 'Cannot update processed credit request'
                }), 400

            # Update allowed fields
            update_data = {
                'updatedAt': datetime.utcnow()
            }
            
            if 'paymentReference' in data:
                update_data['paymentReference'] = data['paymentReference']
            if 'receiptUrl' in data:
                update_data['receiptUrl'] = data['receiptUrl']
            if 'notes' in data:
                update_data['notes'] = data['notes']

            # Update the request
            mongo.db.credit_requests.update_one(
                {'requestId': request_id, 'userId': current_user['_id']},
                {'$set': update_data}
            )

            # Get updated request
            updated_request = mongo.db.credit_requests.find_one({
                'requestId': request_id,
                'userId': current_user['_id']
            })

            # Serialize and return
            request_data = serialize_doc(updated_request)
            request_data['createdAt'] = request_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            request_data['updatedAt'] = request_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'

            return jsonify({
                'success': True,
                'data': request_data,
                'message': 'Credit request updated successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update credit request',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/requests', methods=['GET'])
    @token_required
    def get_user_credit_requests(current_user):
        """Get user's credit requests"""
        try:
            # Get pagination parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            status = request.args.get('status', 'all')  # all, pending, approved, rejected
            
            # Build query
            query = {'userId': current_user['_id']}
            if status != 'all':
                query['status'] = status

            # Get total count
            total = mongo.db.credit_requests.count_documents(query)
            
            # Get requests with pagination
            skip = (page - 1) * limit
            requests = list(mongo.db.credit_requests.find(query)
                          .sort('createdAt', -1)
                          .skip(skip)
                          .limit(limit))
            
            # Serialize requests
            request_data = []
            for req in requests:
                req_data = serialize_doc(req.copy())
                req_data['createdAt'] = req_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                req_data['updatedAt'] = req_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                if req_data.get('processedAt'):
                    req_data['processedAt'] = req_data.get('processedAt', datetime.utcnow()).isoformat() + 'Z'
                request_data.append(req_data)

            return jsonify({
                'success': True,
                'data': {
                    'requests': request_data,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit,
                        'hasNext': page * limit < total,
                        'hasPrev': page > 1
                    }
                },
                'message': 'Credit requests retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve credit requests',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/deduct', methods=['POST'])
    @token_required
    def deduct_credits(current_user):
        """Deduct credits from user account (for app operations)"""
        try:
            data = request.get_json()
            
            # Validate required fields
            if 'amount' not in data or 'operation' not in data:
                return jsonify({
                    'success': False,
                    'message': 'Missing required fields: amount, operation'
                }), 400

            amount = float(data['amount'])
            operation = data['operation']
            description = data.get('description', f'Credits used for {operation}')

            if amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Amount must be greater than zero'
                }), 400

            # Validate operation is a known FC cost operation
            valid_operations = [
                # Income & Expense operations
                'create_income', 'delete_income', 'create_expense', 'delete_expense',
                # Asset Register operations
                'create_asset', 'delete_asset',
                # Inventory operations
                'create_item', 'delete_item', 'create_movement', 'stock_in', 'stock_out', 'adjust_stock',
                # Creditors operations
                'create_vendor', 'delete_vendor', 'create_creditor_transaction', 'delete_creditor_transaction',
                # Debtors operations
                'create_customer', 'delete_customer', 'create_debtor_transaction', 'delete_debtor_transaction',
                # Export operations
                'export_inventory_csv', 'export_inventory_pdf', 'export_creditors_csv', 'export_creditors_pdf',
                'export_debtors_csv', 'export_debtors_pdf', 'export_net_income_report', 'export_financial_report',
                'export_dashboard_summary', 'export_enhanced_profit_report', 'export_complete_data_export',
                'export_movements_csv', 'export_valuation_pdf', 'export_aging_report_pdf', 'export_payments_due_csv',
                'export_debtors_aging_report_pdf', 'export_debtors_payments_due_csv',
                'export_assets_csv', 'export_assets_pdf', 'export_asset_register_pdf', 'export_depreciation_report_pdf'
            ]
            
            if operation not in valid_operations:
                print(f"Warning: Unknown operation '{operation}' for credit deduction")
                # Don't fail, just log for monitoring

            # Get current user balance
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            current_balance = user.get('ficoreCreditBalance', 0.0)

            if current_balance < amount:
                return jsonify({
                    'success': False,
                    'message': 'Insufficient credits',
                    'data': {
                        'currentBalance': current_balance,
                        'requiredAmount': amount,
                        'shortfall': amount - current_balance
                    }
                }), 402  # Payment Required

            # Deduct credits from user account
            new_balance = current_balance - amount
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {'ficoreCreditBalance': new_balance}}
            )

            # Create transaction record
            transaction = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'type': 'debit',
                'amount': amount,
                'description': description,
                'operation': operation,
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'status': 'completed',
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'operation': operation,
                    'deductionType': 'app_usage'
                }
            }
            
            mongo.db.credit_transactions.insert_one(transaction)

            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(transaction['_id']),
                    'amountDeducted': amount,
                    'previousBalance': current_balance,
                    'newBalance': new_balance,
                    'operation': operation
                },
                'message': f'Credits deducted successfully for {operation}'
            })

        except ValueError as e:
            return jsonify({
                'success': False,
                'message': 'Invalid amount format'
            }), 400
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to deduct credits',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/award', methods=['POST'])
    @token_required
    def award_credits(current_user):
        """Award credits to user account (for completing tasks like tax education)"""
        try:
            data = request.get_json()
            
            # Validate required fields
            if 'amount' not in data or 'operation' not in data:
                return jsonify({
                    'success': False,
                    'message': 'Missing required fields: amount, operation'
                }), 400

            amount = float(data['amount'])
            operation = data['operation']
            description = data.get('description', f'Credits earned from {operation}')

            if amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Amount must be greater than zero'
                }), 400

            # Validate operation is a known credit-earning operation
            valid_award_operations = [
                'tax_education_progress',  # Users earn 1 FC per tax education module
                'signup_bonus',           # Initial signup bonus
                'referral_bonus',         # Future referral system
                'admin_award'             # Manual admin awards
            ]
            
            if operation not in valid_award_operations:
                print(f"Warning: Unknown operation '{operation}' for credit award")
                # Don't fail, just log for monitoring

            # Get current user balance
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            current_balance = user.get('ficoreCreditBalance', 0.0)

            # Award credits to user account
            new_balance = current_balance + amount
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {'ficoreCreditBalance': new_balance}}
            )

            # Create transaction record
            transaction = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'type': 'credit',
                'amount': amount,
                'description': description,
                'operation': operation,
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'status': 'completed',
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'operation': operation,
                    'awardType': 'task_completion'
                }
            }
            
            mongo.db.credit_transactions.insert_one(transaction)

            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(transaction['_id']),
                    'amountAwarded': amount,
                    'previousBalance': current_balance,
                    'newBalance': new_balance,
                    'operation': operation
                },
                'message': f'Credits awarded successfully for {operation}'
            })

        except ValueError as e:
            return jsonify({
                'success': False,
                'message': 'Invalid amount format'
            }), 400
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to award credits',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/transactions/recent', methods=['GET'])
    @token_required
    def get_recent_credit_transactions(current_user):
        """Get recent credit transactions"""
        try:
            # Validate user exists and has required fields
            if not current_user or '_id' not in current_user:
                return jsonify({
                    'success': False,
                    'message': 'Invalid user session'
                }), 401

            # Validate and sanitize limit parameter
            try:
                limit = int(request.args.get('limit', 5))
                # Ensure reasonable limits
                if limit < 1:
                    limit = 5
                elif limit > 100:
                    limit = 100
            except (ValueError, TypeError):
                limit = 5
            
            # Get recent transactions with error handling
            try:
                transactions = list(mongo.db.credit_transactions.find({
                    'userId': current_user['_id']
                }).sort('createdAt', -1).limit(limit))
            except Exception as db_error:
                print(f"Database error in get_recent_credit_transactions: {str(db_error)}")
                return jsonify({
                    'success': False,
                    'message': 'Database connection error',
                    'errors': {'database': [str(db_error)]}
                }), 500
            
            # Serialize transactions with error handling
            transaction_data = []
            for transaction in transactions:
                try:
                    trans_data = serialize_doc(transaction.copy())
                    # Ensure createdAt is properly formatted
                    created_at = trans_data.get('createdAt')
                    if isinstance(created_at, datetime):
                        trans_data['createdAt'] = created_at.isoformat() + 'Z'
                    elif created_at is None:
                        trans_data['createdAt'] = datetime.utcnow().isoformat() + 'Z'
                    transaction_data.append(trans_data)
                except Exception as serialize_error:
                    # Skip problematic transactions
                    print(f"Warning: Failed to serialize transaction: {str(serialize_error)}")
                    continue

            return jsonify({
                'success': True,
                'data': {
                    'transactions': transaction_data
                },
                'message': 'Recent credit transactions retrieved successfully'
            })

        except Exception as e:
            # Log the error for debugging
            print(f"Error in get_recent_credit_transactions: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve recent credit transactions',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/transactions', methods=['GET'])
    @token_required
    def get_credit_transactions(current_user):
        """Get credit transactions with pagination"""
        try:
            limit = int(request.args.get('limit', 20))
            offset = int(request.args.get('offset', 0))
            
            # Get transactions with pagination
            transactions = list(mongo.db.credit_transactions.find({
                'userId': current_user['_id']
            }).sort('createdAt', -1).skip(offset).limit(limit))
            
            total = mongo.db.credit_transactions.count_documents({
                'userId': current_user['_id']
            })
            
            # Serialize transactions
            transaction_data = []
            for transaction in transactions:
                trans_data = serialize_doc(transaction.copy())
                trans_data['createdAt'] = trans_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                transaction_data.append(trans_data)

            return jsonify({
                'success': True,
                'data': {
                    'transactions': transaction_data,
                    'pagination': {
                        'limit': limit,
                        'offset': offset,
                        'total': total,
                        'hasMore': offset + limit < total
                    }
                },
                'message': 'Credit transactions retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve credit transactions',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/upload-receipt', methods=['POST'])
    @token_required
    def upload_receipt(current_user):
        """Upload payment receipt for credit request"""
        try:
            # Debug logging for request details
            print(f"Upload receipt request from user: {current_user.get('_id', 'Unknown')}")
            print(f"Request method: {request.method}")
            print(f"Request content type: {request.content_type}")
            print(f"Request files keys: {list(request.files.keys())}")
            print(f"Request is_json: {request.is_json}")
            print(f"Upload folder: {UPLOAD_FOLDER}")
            print(f"Upload folder exists: {os.path.exists(UPLOAD_FOLDER)}")
            print(f"Upload folder permissions: {oct(os.stat(UPLOAD_FOLDER).st_mode)[-3:] if os.path.exists(UPLOAD_FOLDER) else 'N/A'}")
            # Check if file is in request
            if 'receipt' not in request.files:
                # Check if base64 data is provided instead
                data = request.get_json() if request.is_json else {}
                if 'receiptData' in data and 'fileName' in data:
                    # Handle base64 upload
                    try:
                        receipt_data = data['receiptData']
                        file_name = secure_filename(data['fileName'])
                        
                        # Remove data URL prefix if present
                        if ',' in receipt_data:
                            receipt_data = receipt_data.split(',')[1]
                        
                        # Decode base64
                        file_bytes = base64.b64decode(receipt_data)
                        
                        # Check file size
                        if len(file_bytes) > MAX_FILE_SIZE:
                            return jsonify({
                                'success': False,
                                'message': f'File size exceeds maximum allowed size of {MAX_FILE_SIZE / (1024*1024)}MB'
                            }), 400
                        
                        # Generate unique filename
                        file_ext = file_name.rsplit('.', 1)[1].lower() if '.' in file_name else 'jpg'
                        if file_ext not in ALLOWED_EXTENSIONS:
                            return jsonify({
                                'success': False,
                                'message': f'File type not allowed. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
                            }), 400
                        
                        unique_filename = f"{current_user['_id']}_{uuid.uuid4().hex[:8]}.{file_ext}"
                        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
                        
                        # Save file
                        with open(file_path, 'wb') as f:
                            f.write(file_bytes)
                        
                        # Generate URL (relative path)
                        receipt_url = f"/uploads/receipts/{unique_filename}"
                        
                        return jsonify({
                            'success': True,
                            'data': {
                                'receiptUrl': receipt_url,
                                'fileName': unique_filename,
                                'fileSize': len(file_bytes),
                                'uploadedAt': datetime.utcnow().isoformat() + 'Z'
                            },
                            'message': 'Receipt uploaded successfully'
                        }), 201
                        
                    except Exception as e:
                        # Enhanced error logging for base64 processing
                        error_traceback = traceback.format_exc()
                        print(f"Error in base64 upload processing: {error_traceback}")
                        print(f"Exception type: {type(e).__name__}")
                        print(f"Exception message: {str(e)}")
                        
                        return jsonify({
                            'success': False,
                            'message': f'Failed to process base64 file: {str(e)}'
                        }), 400
                else:
                    return jsonify({
                        'success': False,
                        'message': 'No receipt file provided'
                    }), 400
            
            file = request.files['receipt']
            
            # Check if file is selected
            if file.filename == '':
                return jsonify({
                    'success': False,
                    'message': 'No file selected'
                }), 400
            
            # Check file extension
            if not allowed_file(file.filename):
                return jsonify({
                    'success': False,
                    'message': f'File type not allowed. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
                }), 400
            
            # Check file size
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            
            if file_size > MAX_FILE_SIZE:
                return jsonify({
                    'success': False,
                    'message': f'File size exceeds maximum allowed size of {MAX_FILE_SIZE / (1024*1024)}MB'
                }), 400
            
            # Generate unique filename
            file_ext = file.filename.rsplit('.', 1)[1].lower()
            unique_filename = f"{current_user['_id']}_{uuid.uuid4().hex[:8]}.{file_ext}"
            file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            
            # Save file
            file.save(file_path)
            
            # Generate URL (relative path)
            receipt_url = f"/uploads/receipts/{unique_filename}"
            
            return jsonify({
                'success': True,
                'data': {
                    'receiptUrl': receipt_url,
                    'fileName': unique_filename,
                    'fileSize': file_size,
                    'uploadedAt': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'Receipt uploaded successfully'
            }), 201
            
        except Exception as e:
            # Enhanced error logging with full traceback
            error_traceback = traceback.format_exc()
            print(f"Error in upload_receipt: {error_traceback}")
            print(f"Exception type: {type(e).__name__}")
            print(f"Exception message: {str(e)}")
            
            # Log additional context for debugging
            print(f"Upload folder path: {UPLOAD_FOLDER}")
            print(f"Upload folder exists: {os.path.exists(UPLOAD_FOLDER)}")
            print(f"Upload folder writable: {os.access(UPLOAD_FOLDER, os.W_OK) if os.path.exists(UPLOAD_FOLDER) else 'N/A'}")
            
            return jsonify({
                'success': False,
                'message': 'Failed to upload receipt',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/monthly-entries', methods=['GET'])
    @token_required
    def get_monthly_entries_status(current_user):
        """Get user's monthly Income & Expense entry status for free tier"""
        try:
            from utils.monthly_entry_tracker import MonthlyEntryTracker
            
            entry_tracker = MonthlyEntryTracker(mongo)
            monthly_stats = entry_tracker.get_monthly_stats(current_user['_id'])
            
            return jsonify({
                'success': True,
                'data': monthly_stats,
                'message': 'Monthly entry status retrieved successfully'
            })

        except Exception as e:
            print(f"Error in get_monthly_entries_status: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve monthly entry status',
                'errors': {'general': [str(e)]}
            }), 500

    @credits_bp.route('/summary', methods=['GET'])
    @token_required
    def get_credit_summary(current_user):
        """Get credit summary statistics"""
        try:
            # Validate user exists and has required fields
            if not current_user or '_id' not in current_user:
                return jsonify({
                    'success': False,
                    'message': 'Invalid user session'
                }), 401

            # Get user's current balance with error handling
            try:
                user = mongo.db.users.find_one({'_id': current_user['_id']})
                if not user:
                    return jsonify({
                        'success': False,
                        'message': 'User not found'
                    }), 404
                
                current_balance = user.get('ficoreCreditBalance', 0.0)
                if not isinstance(current_balance, (int, float)):
                    current_balance = 0.0
            except Exception as user_error:
                print(f"Error fetching user balance: {str(user_error)}")
                current_balance = 0.0
            
            # Get transaction statistics with error handling
            try:
                total_credits = list(mongo.db.credit_transactions.aggregate([
                    {'$match': {'userId': current_user['_id'], 'type': 'credit'}},
                    {'$group': {'_id': None, 'total': {'$sum': '$amount'}, 'count': {'$sum': 1}}}
                ]))
                credits_amount = total_credits[0]['total'] if total_credits else 0
                credits_count = total_credits[0]['count'] if total_credits else 0
            except Exception as credits_error:
                print(f"Error fetching credits statistics: {str(credits_error)}")
                credits_amount = 0
                credits_count = 0
            
            # Get credits breakdown by source (NEW: Feb 9, 2026)
            try:
                # 1. Credits from BUYING (Paystack purchases)
                purchased_credits = list(mongo.db.credit_transactions.aggregate([
                    {
                        '$match': {
                            'userId': current_user['_id'],
                            'type': 'credit',
                            '$or': [
                                {'metadata.purchaseType': {'$exists': True}},
                                {'paymentMethod': 'paystack'},
                                {'description': {'$regex': 'purchase', '$options': 'i'}}
                            ]
                        }
                    },
                    {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
                ]))
                purchased_amount = purchased_credits[0]['total'] if purchased_credits else 0.0
                
                # 2. Credits from SIGNUP BONUS
                signup_bonus = list(mongo.db.credit_transactions.aggregate([
                    {
                        '$match': {
                            'userId': current_user['_id'],
                            'type': 'credit',
                            'operation': 'signup_bonus'
                        }
                    },
                    {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
                ]))
                signup_bonus_amount = signup_bonus[0]['total'] if signup_bonus else 0.0
                
                # 3. Credits from REWARDS SCREEN (engagement, streaks, exploration)
                rewards_credits = list(mongo.db.credit_transactions.aggregate([
                    {
                        '$match': {
                            'userId': current_user['_id'],
                            'type': 'credit',
                            '$or': [
                                {'operation': 'engagement_reward'},
                                {'operation': 'streak_milestone'},
                                {'operation': 'exploration_bonus'},
                                {'operation': 'profile_completion'},
                                {'description': {'$regex': 'reward|streak|exploration|milestone', '$options': 'i'}}
                            ]
                        }
                    },
                    {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
                ]))
                rewards_amount = rewards_credits[0]['total'] if rewards_credits else 0.0
                
                # 4. Credits from TAX EDUCATION MODULES
                tax_education_credits = list(mongo.db.credit_transactions.aggregate([
                    {
                        '$match': {
                            'userId': current_user['_id'],
                            'type': 'credit',
                            '$or': [
                                {'operation': 'tax_education_progress'},
                                {'description': {'$regex': 'tax education|tax module', '$options': 'i'}}
                            ]
                        }
                    },
                    {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
                ]))
                tax_education_amount = tax_education_credits[0]['total'] if tax_education_credits else 0.0
                
                # 5. Other credits (referral bonuses, admin awards, etc.)
                other_credits_amount = credits_amount - (purchased_amount + signup_bonus_amount + rewards_amount + tax_education_amount)
                if other_credits_amount < 0:
                    other_credits_amount = 0.0  # Safety check
                
            except Exception as breakdown_error:
                print(f"Error fetching credits breakdown: {str(breakdown_error)}")
                purchased_amount = 0.0
                signup_bonus_amount = 0.0
                rewards_amount = 0.0
                tax_education_amount = 0.0
                other_credits_amount = 0.0

            try:
                total_debits = list(mongo.db.credit_transactions.aggregate([
                    {'$match': {'userId': current_user['_id'], 'type': 'debit'}},
                    {'$group': {'_id': None, 'total': {'$sum': '$amount'}, 'count': {'$sum': 1}}}
                ]))
                debits_amount = total_debits[0]['total'] if total_debits else 0
                debits_count = total_debits[0]['count'] if total_debits else 0
            except Exception as debits_error:
                print(f"Error fetching debits statistics: {str(debits_error)}")
                debits_amount = 0
                debits_count = 0

            # Get pending requests with error handling
            try:
                pending_requests = mongo.db.credit_requests.count_documents({
                    'userId': current_user['_id'],
                    'status': 'pending'
                })
            except Exception as requests_error:
                print(f"Error fetching pending requests: {str(requests_error)}")
                pending_requests = 0

            # Ensure all values are proper numbers
            credits_amount = float(credits_amount) if credits_amount else 0.0
            debits_amount = float(debits_amount) if debits_amount else 0.0
            current_balance = float(current_balance)

            summary_data = {
                'currentBalance': current_balance,
                'totalCredits': credits_amount,
                'totalDebits': debits_amount,
                'netCredits': credits_amount - debits_amount,
                # NEW: Credits breakdown by source (Feb 9, 2026)
                'creditsBreakdown': {
                    'purchased': float(purchased_amount),
                    'signupBonus': float(signup_bonus_amount),
                    'rewards': float(rewards_amount),
                    'taxEducation': float(tax_education_amount),
                    'other': float(other_credits_amount)
                },
                'transactionCounts': {
                    'credits': int(credits_count),
                    'debits': int(debits_count),
                    'total': int(credits_count + debits_count)
                },
                'pendingRequests': int(pending_requests),
                'lastUpdated': datetime.utcnow().isoformat() + 'Z'
            }

            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Credit summary retrieved successfully'
            })

        except Exception as e:
            # Log the error for debugging
            print(f"Error in get_credit_summary: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve credit summary',
                'errors': {'general': [str(e)]}
            }), 500

    return credits_bp