"""
VAS (Value Added Services) Blueprint - Production Grade
Handles wallet management and utility purchases (Airtime, Data, etc.)

Security: API keys in environment variables, idempotency protection, webhook verification
Providers: Monnify (wallet), Peyflex (primary VAS), VTpass (backup)
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
import os
import requests
import hmac
import hashlib
import uuid

def init_vas_blueprint(mongo, token_required, serialize_doc):
    vas_bp = Blueprint('vas', __name__, url_prefix='/api/vas')
    
    # Environment variables (NEVER hardcode these)
    MONNIFY_API_KEY = os.environ.get('MONNIFY_API_KEY', '')
    MONNIFY_SECRET_KEY = os.environ.get('MONNIFY_SECRET_KEY', '')
    MONNIFY_CONTRACT_CODE = os.environ.get('MONNIFY_CONTRACT_CODE', '')
    MONNIFY_BASE_URL = os.environ.get('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')
    
    PEYFLEX_API_TOKEN = os.environ.get('PEYFLEX_API_TOKEN', '')
    PEYFLEX_BASE_URL = os.environ.get('PEYFLEX_BASE_URL', 'https://client.peyflex.com.ng')
    
    VTPASS_API_KEY = os.environ.get('VTPASS_API_KEY', '')
    VTPASS_PUBLIC_KEY = os.environ.get('VTPASS_PUBLIC_KEY', '')
    VTPASS_SECRET_KEY = os.environ.get('VTPASS_SECRET_KEY', '')
    VTPASS_BASE_URL = os.environ.get('VTPASS_BASE_URL', 'https://sandbox.vtpass.com')
    
    VAS_TRANSACTION_FEE = 30.0
    ACTIVATION_FEE = 100.0
    BVN_VERIFICATION_COST = 10.0
    NIN_VERIFICATION_COST = 60.0
    
    # ==================== HELPER FUNCTIONS ====================
    
    def generate_request_id(user_id, transaction_type):
        """Generate unique request ID for idempotency"""
        timestamp = int(datetime.utcnow().timestamp())
        unique_suffix = str(uuid.uuid4())[:8]
        return f'FICORE_{transaction_type}_{user_id}_{timestamp}_{unique_suffix}'
    
    def check_eligibility(user_id):
        """
        Check if user is eligible for dedicated account (Path B)
        User must meet ONE of these criteria:
        1. Used app for 3+ consecutive days
        2. Recorded 10+ transactions (income/expense)
        3. Completed 5+ Quick Pay VAS transactions
        """
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        # Check 1: Consecutive days
        login_streak = user.get('loginStreak', 0)
        if login_streak >= 3:
            return True, "3-day streak"
        
        # Check 2: Total transactions
        total_txns = mongo.db.income.count_documents({'userId': ObjectId(user_id)})
        total_txns += mongo.db.expenses.count_documents({'userId': ObjectId(user_id)})
        if total_txns >= 10:
            return True, "10+ transactions"
        
        # Check 3: Quick Pay usage
        quick_pay_count = mongo.db.vas_transactions.count_documents({
            'userId': ObjectId(user_id),
            'type': {'$in': ['AIRTIME', 'DATA']},
            'status': 'SUCCESS'
        })
        if quick_pay_count >= 5:
            return True, "5+ Quick Pay"
        
        return False, None
    
    def get_eligibility_progress(user_id):
        """Get user's progress towards eligibility"""
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        login_streak = user.get('loginStreak', 0)
        total_txns = mongo.db.income.count_documents({'userId': ObjectId(user_id)})
        total_txns += mongo.db.expenses.count_documents({'userId': ObjectId(user_id)})
        quick_pay_count = mongo.db.vas_transactions.count_documents({
            'userId': ObjectId(user_id),
            'type': {'$in': ['AIRTIME', 'DATA']},
            'status': 'SUCCESS'
        })
        
        # Return flat structure that matches frontend expectations
        return {
            'loginDays': login_streak,  # Frontend expects 'loginDays', not 'loginStreak'
            'totalTransactions': total_txns,
            'quickPayCount': quick_pay_count
        }
    
    def call_monnify_auth():
        """Get Monnify authentication token"""
        try:
            auth_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/auth/login',
                auth=(MONNIFY_API_KEY, MONNIFY_SECRET_KEY),
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if auth_response.status_code != 200:
                raise Exception(f'Monnify auth failed: {auth_response.text}')
            
            return auth_response.json()['responseBody']['accessToken']
        except Exception as e:
            print(f'❌ Monnify auth error: {str(e)}')
            raise
    
    def call_monnify_bvn_verification(bvn, name, dob, mobile):
        """
        Call Monnify BVN verification API
        Cost: ₦10 per successful request
        """
        try:
            access_token = call_monnify_auth()
            
            response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/vas/bvn-details-match',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json={
                    'bvn': bvn,
                    'name': name,
                    'dateOfBirth': dob,
                    'mobileNo': mobile
                },
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f'BVN verification failed: {response.text}')
            
            data = response.json()
            if not data.get('requestSuccessful'):
                raise Exception(f'BVN verification failed: {data.get("responseMessage")}')
            
            return data['responseBody']
        except Exception as e:
            print(f'❌ BVN verification error: {str(e)}')
            raise
    
    def call_monnify_nin_verification(nin):
        """
        Call Monnify NIN verification API
        Cost: ₦60 per successful request
        Returns NIN holder's details for validation
        """
        try:
            access_token = call_monnify_auth()
            
            response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/vas/nin-details',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json={'nin': nin},
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f'NIN verification failed: {response.text}')
            
            data = response.json()
            if not data.get('requestSuccessful'):
                raise Exception(f'NIN verification failed: {data.get("responseMessage")}')
            
            return data['responseBody']
        except Exception as e:
            print(f'❌ NIN verification error: {str(e)}')
            raise
    
    def call_monnify_init_payment(transaction_reference, amount, customer_name, customer_email, payment_description='FiCore Liquid Cash Payment'):
        """
        Call Monnify's One-Time Payment API for Quick Pay
        Returns temporary account number for this specific transaction
        """
        try:
            access_token = call_monnify_auth()
            
            payment_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/merchant/bank-transfer/init-payment',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json={
                    'transactionReference': transaction_reference,
                    'amount': amount,
                    'customerName': customer_name,
                    'customerEmail': customer_email,
                    'paymentDescription': payment_description,
                    'currencyCode': 'NGN',
                    'contractCode': MONNIFY_CONTRACT_CODE,
                    'paymentMethods': ['ACCOUNT_TRANSFER'],
                    'bankCode': '058'  # GTBank for USSD generation
                },
                timeout=30
            )
            
            if payment_response.status_code != 200:
                raise Exception(f'Payment init failed: {payment_response.text}')
            
            response_data = payment_response.json()['responseBody']
            
            return {
                'accountNumber': response_data['accountNumber'],
                'accountName': response_data['accountName'],
                'bankName': response_data['bankName'],
                'bankCode': response_data['bankCode'],
                'ussdCode': response_data.get('ussdCode', '')
            }
        except Exception as e:
            print(f'❌ Monnify init payment error: {str(e)}')
            raise
    
    def check_pending_transaction(user_id, transaction_type, amount, phone_number):
        """Check for pending duplicate transactions (idempotency)"""
        cutoff_time = datetime.utcnow() - timedelta(minutes=5)
        
        pending_txn = mongo.db.vas_transactions.find_one({
            'userId': ObjectId(user_id),
            'type': transaction_type,
            'amount': amount,
            'phoneNumber': phone_number,
            'status': 'PENDING',
            'createdAt': {'$gte': cutoff_time}
        })
        
        return pending_txn
    
    def call_peyflex_airtime(network, amount, phone_number, request_id):
        """Call Peyflex Airtime API with proper headers and bypass flag"""
        payload = {
            'network': network.lower(),
            'amount': int(amount),
            'mobile_number': phone_number,
            'bypass': False,
            'request_id': request_id
        }
        
        response = requests.post(
            f'{PEYFLEX_BASE_URL}/api/airtime/topup/',
            headers={
                'Authorization': f'Token {PEYFLEX_API_TOKEN}',
                'Content-Type': 'application/json'
            },
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f'Peyflex API error: {response.status_code} - {response.text}')
    
    def call_vtpass_airtime(network, amount, phone_number, request_id):
        """Call VTpass Airtime API (fallback)"""
        network_map = {
            'MTN': 'mtn',
            'AIRTEL': 'airtel',
            'GLO': 'glo',
            '9MOBILE': 'etisalat'
        }
        
        payload = {
            'serviceID': network_map.get(network, network.lower()),
            'amount': int(amount),
            'phone': phone_number,
            'request_id': request_id
        }
        
        response = requests.post(
            f'{VTPASS_BASE_URL}/api/pay',
            headers={
                'api-key': VTPASS_API_KEY,
                'public-key': VTPASS_PUBLIC_KEY,
                'Content-Type': 'application/json'
            },
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '000':
                return data
            else:
                raise Exception(f'VTpass error: {data.get("response_description", "Unknown error")}')
        else:
            raise Exception(f'VTpass API error: {response.status_code} - {response.text}')
    
    def call_peyflex_data(network, data_plan_code, phone_number, request_id):
        """Call Peyflex Data API with proper headers"""
        payload = {
            'network': network.lower(),
            'plan_code': data_plan_code,  # Changed from plan_id to plan_code
            'mobile_number': phone_number,
            'bypass': False,
            'request_id': request_id
        }
        
        print(f'📤 Peyflex data purchase payload: {payload}')
        
        response = requests.post(
            f'{PEYFLEX_BASE_URL}/api/data/purchase/',
            headers={
                'Authorization': f'Token {PEYFLEX_API_TOKEN}',
                'Content-Type': 'application/json'
            },
            json=payload,
            timeout=30
        )
        
        print(f'📥 Peyflex data purchase response: {response.status_code} - {response.text[:500]}')
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f'Peyflex API error: {response.status_code} - {response.text}')
    
    def call_vtpass_data(network, data_plan_code, phone_number, request_id):
        """Call VTpass Data API (fallback)"""
        network_map = {
            'MTN': 'mtn-data',
            'AIRTEL': 'airtel-data',
            'GLO': 'glo-data',
            '9MOBILE': 'etisalat-data'
        }
        
        payload = {
            'serviceID': network_map.get(network, f'{network.lower()}-data'),
            'billersCode': phone_number,
            'variation_code': data_plan_code,
            'phone': phone_number,
            'request_id': request_id
        }
        
        response = requests.post(
            f'{VTPASS_BASE_URL}/api/pay',
            headers={
                'api-key': VTPASS_API_KEY,
                'public-key': VTPASS_PUBLIC_KEY,
                'Content-Type': 'application/json'
            },
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '000':
                return data
            else:
                raise Exception(f'VTpass error: {data.get("response_description", "Unknown error")}')
        else:
            raise Exception(f'VTpass API error: {response.status_code} - {response.text}')
    
    # ==================== WALLET ENDPOINTS ====================
    
    @vas_bp.route('/wallet/create', methods=['POST'])
    @token_required
    def create_wallet(current_user):
        """Create virtual account number (VAN) for user via Monnify"""
        try:
            user_id = str(current_user['_id'])
            
            existing_wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if existing_wallet:
                return jsonify({
                    'success': True,
                    'data': serialize_doc(existing_wallet),
                    'message': 'Wallet already exists'
                }), 200
            
            auth_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/auth/login',
                auth=(MONNIFY_API_KEY, MONNIFY_SECRET_KEY),
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if auth_response.status_code != 200:
                raise Exception(f'Monnify auth failed: {auth_response.text}')
            
            access_token = auth_response.json()['responseBody']['accessToken']
            
            account_data = {
                'accountReference': f'FICORE_{user_id}',
                'accountName': f"{current_user.get('firstName', '')} {current_user.get('lastName', '')}".strip(),
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'customerEmail': current_user.get('email', ''),
                'customerName': f"{current_user.get('firstName', '')} {current_user.get('lastName', '')}".strip(),
                'getAllAvailableBanks': False,
                'preferredBanks': ['035']
            }
            
            van_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json=account_data,
                timeout=30
            )
            
            if van_response.status_code != 200:
                raise Exception(f'VAN creation failed: {van_response.text}')
            
            van_data = van_response.json()['responseBody']
            
            wallet = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'balance': 0.0,
                'accountReference': van_data['accountReference'],
                'accountName': van_data['accountName'],
                'accounts': van_data['accounts'],
                'status': 'active',
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.vas_wallets.insert_one(wallet)
            
            return jsonify({
                'success': True,
                'data': serialize_doc(wallet),
                'message': 'Wallet created successfully'
            }), 201
            
        except Exception as e:
            print(f'❌ Error creating wallet: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to create wallet',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/wallet/balance', methods=['GET'])
    @token_required
    def get_wallet_balance(current_user):
        """Get user's wallet balance"""
        try:
            user_id = str(current_user['_id'])
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found. Please create a wallet first.'
                }), 404
            
            return jsonify({
                'success': True,
                'data': {
                    'balance': wallet.get('balance', 0.0),
                    'accounts': wallet.get('accounts', []),
                    'accountName': wallet.get('accountName', ''),
                    'status': wallet.get('status', 'active')
                },
                'message': 'Wallet balance retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'❌ Error getting wallet balance: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve wallet balance',
                'errors': {'general': [str(e)]}
            }), 500
    
    # ==================== ELIGIBILITY & KYC ENDPOINTS ====================
    
    @vas_bp.route('/check-eligibility', methods=['GET'])
    @token_required
    def check_eligibility_endpoint(current_user):
        """Check if user is eligible for dedicated account (Path B)"""
        try:
            user_id = str(current_user['_id'])
            eligible, reason = check_eligibility(user_id)
            progress = get_eligibility_progress(user_id)
            
            return jsonify({
                'success': True,
                'data': {
                    'eligible': eligible,
                    'reason': reason,
                    'progress': progress
                },
                'message': 'Eligibility checked successfully'
            }), 200
            
        except Exception as e:
            print(f'❌ Error checking eligibility: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to check eligibility',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/verify-bvn', methods=['POST'])
    @token_required
    def verify_bvn(current_user):
        """
        Verify BVN, NIN, and DOB - return name for user confirmation
        This is where you pay ₦70 to Monnify (₦10 BVN + ₦60 NIN)
        """
        try:
            data = request.json
            bvn = data.get('bvn', '').strip()
            nin = data.get('nin', '').strip()
            dob = data.get('dateOfBirth', '').strip()  # Format: DD-MMM-YYYY
            
            # Validate
            if len(bvn) != 11 or not bvn.isdigit():
                return jsonify({
                    'success': False,
                    'message': 'Invalid BVN. Must be 11 digits.'
                }), 400
            
            if len(nin) != 11 or not nin.isdigit():
                return jsonify({
                    'success': False,
                    'message': 'Invalid NIN. Must be 11 digits.'
                }), 400
            
            if not dob:
                return jsonify({
                    'success': False,
                    'message': 'Date of birth is required.'
                }), 400
            
            # Check eligibility first (prevent ₦70 waste)
            user_id = str(current_user['_id'])
            eligible, _ = check_eligibility(user_id)
            if not eligible:
                return jsonify({
                    'success': False,
                    'message': 'Not eligible yet. Complete more transactions to unlock.'
                }), 403
            
            # Check if user already has verified wallet
            existing_wallet = mongo.db.vas_wallets.find_one({
                'userId': ObjectId(user_id),
                'kycStatus': 'verified'
            })
            if existing_wallet:
                return jsonify({
                    'success': False,
                    'message': 'You already have a verified account.'
                }), 400
            
            # Call Monnify BVN verification (₦10 cost)
            user_name = f"{current_user.get('firstName', '')} {current_user.get('lastName', '')}".strip()
            bvn_response = call_monnify_bvn_verification(
                bvn=bvn,
                name=user_name,
                dob=dob,
                mobile=current_user.get('phoneNumber', '')
            )
            
            # Check BVN match status
            name_match = bvn_response.get('name', {})
            if name_match.get('matchStatus') != 'FULL_MATCH':
                return jsonify({
                    'success': False,
                    'message': 'BVN verification failed. Name does not match.'
                }), 400
            
            dob_match = bvn_response.get('dateOfBirth', 'NO_MATCH')
            if dob_match == 'NO_MATCH':
                return jsonify({
                    'success': False,
                    'message': 'BVN verification failed. Date of birth does not match.'
                }), 400
            
            # Call Monnify NIN verification (₦60 cost)
            nin_response = call_monnify_nin_verification(nin=nin)
            
            # Validate NIN response
            nin_first_name = nin_response.get('firstName', '').upper()
            nin_last_name = nin_response.get('lastName', '').upper()
            nin_full_name = f"{nin_first_name} {nin_last_name}".strip()
            
            # Cross-check: NIN name should match user's name
            user_first = current_user.get('firstName', '').upper()
            user_last = current_user.get('lastName', '').upper()
            
            if nin_first_name not in user_first and nin_last_name not in user_last:
                return jsonify({
                    'success': False,
                    'message': 'NIN verification failed. Name does not match your profile.'
                }), 400
            
            # Store verification result temporarily (don't create account yet)
            # Delete any existing pending verifications
            mongo.db.kyc_verifications.delete_many({
                'userId': ObjectId(user_id),
                'status': 'pending_confirmation'
            })
            
            # Create new verification record with BOTH BVN and NIN
            mongo.db.kyc_verifications.insert_one({
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'bvn': bvn,
                'nin': nin,
                'verifiedName': user_name,
                'ninName': nin_full_name,
                'status': 'pending_confirmation',
                'createdAt': datetime.utcnow(),
                'expiresAt': datetime.utcnow() + timedelta(minutes=10)
            })
            
            print(f'✅ BVN & NIN verified for user {user_id}: {user_name}')
            
            return jsonify({
                'success': True,
                'data': {
                    'verifiedName': user_name,
                    'ninName': nin_full_name,
                    'matchStatus': 'FULL_MATCH'
                },
                'message': 'BVN and NIN verified successfully'
            }), 200
            
        except Exception as e:
            print(f'❌ Error verifying BVN/NIN: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Verification failed',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/confirm-kyc', methods=['POST'])
    @token_required
    def confirm_kyc(current_user):
        """
        User confirmed the name is correct
        Now create the reserved account with KYC
        """
        try:
            user_id = str(current_user['_id'])
            
            # Get pending verification
            verification = mongo.db.kyc_verifications.find_one({
                'userId': ObjectId(user_id),
                'status': 'pending_confirmation',
                'expiresAt': {'$gt': datetime.utcnow()}
            })
            
            if not verification:
                return jsonify({
                    'success': False,
                    'message': 'Verification expired. Please try again.'
                }), 400
            
            # Check if wallet already exists
            existing_wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if existing_wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet already exists.'
                }), 400
            
            # Create reserved account with BVN and NIN (reuse existing wallet creation logic)
            access_token = call_monnify_auth()
            
            account_data = {
                'accountReference': f'FICORE_{user_id}',
                'accountName': verification['verifiedName'],
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'customerEmail': current_user.get('email', ''),
                'customerName': verification['verifiedName'],
                'bvn': verification['bvn'],
                'nin': verification['nin'],  # Include NIN for full Tier 2 compliance
                'getAllAvailableBanks': False,
                'preferredBanks': ['035']  # Wema Bank
            }
            
            van_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json=account_data,
                timeout=30
            )
            
            if van_response.status_code != 200:
                raise Exception(f'Reserved account creation failed: {van_response.text}')
            
            van_data = van_response.json()['responseBody']
            
            # Create wallet with KYC info (BVN + NIN for full Tier 2)
            wallet = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'balance': 0.0,
                'accountReference': van_data['accountReference'],
                'accountName': van_data['accountName'],
                'accounts': van_data['accounts'],
                'kycStatus': 'verified',
                'kycTier': 2,  # Full Tier 2 compliance with BVN + NIN
                'bvnVerified': True,
                'ninVerified': True,
                'verifiedName': verification['verifiedName'],
                'verificationDate': datetime.utcnow(),
                'isActivated': False,
                'activationFeeDeducted': False,
                'activationDate': None,
                'status': 'active',
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.vas_wallets.insert_one(wallet)
            
            # Update verification status
            mongo.db.kyc_verifications.update_one(
                {'_id': verification['_id']},
                {'$set': {'status': 'confirmed', 'updatedAt': datetime.utcnow()}}
            )
            
            print(f'✅ Reserved account created for user {user_id}')
            
            return jsonify({
                'success': True,
                'data': serialize_doc(wallet),
                'message': 'Account created successfully'
            }), 201
            
        except Exception as e:
            print(f'❌ Error confirming KYC: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to create account',
                'errors': {'general': [str(e)]}
            }), 500
    
    # ==================== QUICK PAY ENDPOINTS ====================
    
    @vas_bp.route('/quick-pay/initiate', methods=['POST'])
    @token_required
    def initiate_quick_pay(current_user):
        """
        Initiate a Quick Pay transaction using Monnify One-Time Payment
        Supports: WALLET_FUNDING, AIRTIME, DATA
        No wallet needed - direct payment to one-time account
        """
        try:
            data = request.json
            transaction_type = data.get('type', '').upper()  # 'WALLET_FUNDING', 'AIRTIME', or 'DATA'
            amount = float(data.get('amount', 0))
            phone_number = data.get('phoneNumber', '').strip()
            network = data.get('network', '').upper()
            
            # Validate transaction type
            if transaction_type not in ['WALLET_FUNDING', 'AIRTIME', 'DATA']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid transaction type. Must be WALLET_FUNDING, AIRTIME, or DATA'
                }), 400
            
            # For wallet funding, amount can be 0 (user decides later)
            # For VAS purchases, amount must be > 0
            if transaction_type in ['AIRTIME', 'DATA'] and amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Invalid amount'
                }), 400
            
            # Phone number and network only required for VAS purchases
            if transaction_type in ['AIRTIME', 'DATA'] and (not phone_number or not network):
                return jsonify({
                    'success': False,
                    'message': 'Phone number and network are required'
                }), 400
            
            user_id = str(current_user['_id'])
            
            # Generate unique transaction reference
            transaction_ref = f'FICORE_QP_{user_id}_{int(datetime.utcnow().timestamp())}'
            
            # For wallet funding, use a placeholder amount (user decides actual amount)
            # Monnify will accept any amount >= this value
            monnify_amount = amount if amount > 0 else 100.0  # Minimum ₦100
            
            # Store pending transaction (before payment)
            pending_txn = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'type': transaction_type,
                'amount': amount,  # 0 for wallet funding means "any amount"
                'transactionReference': transaction_ref,
                'status': 'PENDING_PAYMENT',
                'paymentMethod': 'QUICK_PAY',
                'createdAt': datetime.utcnow(),
                'expiresAt': datetime.utcnow() + timedelta(minutes=30)
            }
            
            # Add phone/network for VAS purchases only
            if transaction_type in ['AIRTIME', 'DATA']:
                pending_txn['phoneNumber'] = phone_number
                pending_txn['network'] = network
            
            if transaction_type == 'DATA':
                pending_txn['dataPlanId'] = data.get('dataPlanId', '')
                pending_txn['dataPlanName'] = data.get('dataPlanName', '')
            
            mongo.db.vas_transactions.insert_one(pending_txn)
            
            # Call Monnify to generate one-time payment account
            customer_name = f"{current_user.get('firstName', '')} {current_user.get('lastName', '')}".strip()
            
            # For wallet funding, set description appropriately
            payment_description = 'FiCore Liquid Wallet Funding'
            if transaction_type == 'AIRTIME':
                payment_description = f'FiCore Airtime Purchase - {network}'
            elif transaction_type == 'DATA':
                payment_description = f'FiCore Data Purchase - {network}'
            
            monnify_response = call_monnify_init_payment(
                transaction_reference=transaction_ref,
                amount=monnify_amount,
                customer_name=customer_name,
                customer_email=current_user.get('email', ''),
                payment_description=payment_description
            )
            
            print(f'✅ Quick Pay initiated: {transaction_ref} (Type: {transaction_type})')
            
            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(pending_txn['_id']),
                    'transactionReference': transaction_ref,
                    'accountNumber': monnify_response['accountNumber'],
                    'accountName': monnify_response['accountName'],
                    'bankName': monnify_response['bankName'],
                    'bankCode': monnify_response['bankCode'],
                    'ussdCode': monnify_response.get('ussdCode', ''),
                    'amount': monnify_amount,  # Return the actual Monnify amount
                    'expiresAt': pending_txn['expiresAt'].isoformat() + 'Z'
                },
                'message': 'Payment account generated. Transfer to complete purchase.'
            }), 200
            
        except Exception as e:
            print(f'❌ Error initiating quick pay: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to initiate payment',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/wallet/webhook', methods=['POST'])
    def monnify_webhook():
        """Handle Monnify webhook with HMAC-SHA512 signature verification"""
        try:
            # Optional: IP Whitelisting (uncomment for production)
            # Monnify webhook IP: 35.242.133.146
            # client_ip = request.headers.get('X-Real-IP', request.remote_addr)
            # MONNIFY_WEBHOOK_IP = '35.242.133.146'
            # if client_ip != MONNIFY_WEBHOOK_IP:
            #     print(f'⚠️ Unauthorized webhook IP: {client_ip}')
            #     return jsonify({'success': False, 'message': 'Unauthorized'}), 403
            
            signature = request.headers.get('monnify-signature', '')
            payload = request.get_data(as_text=True)
            
            # CRITICAL: Verify webhook signature to prevent fake payments
            computed_signature = hmac.new(
                MONNIFY_SECRET_KEY.encode(),
                payload.encode(),
                hashlib.sha512
            ).hexdigest()
            
            if signature != computed_signature:
                print(f'⚠️ Invalid webhook signature. Expected: {computed_signature}, Got: {signature}')
                return jsonify({'success': False, 'message': 'Invalid signature'}), 401
            
            data = request.json
            event_type = data.get('eventType')
            
            print(f'📥 Monnify webhook received: {event_type}')
            
            if event_type == 'SUCCESSFUL_TRANSACTION':
                transaction_data = data.get('eventData', {})
                account_reference = transaction_data.get('accountReference', '')
                amount_paid = float(transaction_data.get('amountPaid', 0))
                transaction_reference = transaction_data.get('transactionReference', '')
                
                print(f'💳 Processing payment: Ref={transaction_reference}, Amount=₦{amount_paid}')
                
                # Handle Quick Pay transactions (starts with FICORE_QP_)
                if transaction_reference.startswith('FICORE_QP_'):
                    # Extract user ID from transaction reference
                    parts = transaction_reference.split('_')
                    if len(parts) >= 3:
                        user_id = parts[2]
                    else:
                        print(f'⚠️ Invalid Quick Pay reference format: {transaction_reference}')
                        return jsonify({'success': False, 'message': 'Invalid reference format'}), 400
                    
                    # Find the pending transaction
                    pending_txn = mongo.db.vas_transactions.find_one({
                        'transactionReference': transaction_reference,
                        'status': 'PENDING_PAYMENT'
                    })
                    
                    if not pending_txn:
                        print(f'⚠️ No pending transaction found for: {transaction_reference}')
                        return jsonify({'success': False, 'message': 'Transaction not found'}), 404
                    
                    txn_type = pending_txn.get('type')
                    
                    # Handle WALLET_FUNDING
                    if txn_type == 'WALLET_FUNDING':
                        wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
                        if not wallet:
                            print(f'❌ Wallet not found for user: {user_id}')
                            return jsonify({'success': False, 'message': 'Wallet not found'}), 404
                        
                        # Check if user is premium (no deposit fee)
                        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                        is_premium = user.get('subscriptionStatus') == 'active' if user else False
                        
                        # Apply deposit fee (₦30 for non-premium users)
                        deposit_fee = 0.0 if is_premium else VAS_TRANSACTION_FEE
                        amount_to_credit = amount_paid - deposit_fee
                        
                        # Ensure we don't credit negative amounts
                        if amount_to_credit <= 0:
                            print(f'⚠️ Amount too small after fee: ₦{amount_paid} - ₦{deposit_fee} = ₦{amount_to_credit}')
                            return jsonify({'success': False, 'message': 'Amount too small to process'}), 400
                        
                        new_balance = wallet.get('balance', 0.0) + amount_to_credit
                        
                        mongo.db.vas_wallets.update_one(
                            {'userId': ObjectId(user_id)},
                            {'$set': {'balance': new_balance, 'updatedAt': datetime.utcnow()}}
                        )
                        
                        # Update transaction status
                        mongo.db.vas_transactions.update_one(
                            {'_id': pending_txn['_id']},
                            {'$set': {
                                'status': 'SUCCESS',
                                'amountPaid': amount_paid,
                                'depositFee': deposit_fee,
                                'amountCredited': amount_to_credit,
                                'reference': transaction_reference,
                                'provider': 'monnify',
                                'metadata': transaction_data,
                                'completedAt': datetime.utcnow()
                            }}
                        )
                        
                        # Record corporate revenue (₦30 fee)
                        if deposit_fee > 0:
                            corporate_revenue = {
                                '_id': ObjectId(),
                                'type': 'SERVICE_FEE',
                                'category': 'DEPOSIT_FEE',
                                'amount': deposit_fee,
                                'userId': ObjectId(user_id),
                                'relatedTransaction': transaction_reference,
                                'description': f'Deposit fee from user {user_id}',
                                'status': 'RECORDED',
                                'createdAt': datetime.utcnow(),
                                'metadata': {
                                    'amountPaid': amount_paid,
                                    'amountCredited': amount_to_credit,
                                    'isPremium': is_premium
                                }
                            }
                            mongo.db.corporate_revenue.insert_one(corporate_revenue)
                            print(f'💰 Corporate revenue recorded: ₦{deposit_fee} from user {user_id}')
                        
                        print(f'✅ Quick Pay Wallet Funding: User {user_id}, Paid: ₦{amount_paid}, Fee: ₦{deposit_fee}, Credited: ₦{amount_to_credit}, New Balance: ₦{new_balance}')
                        return jsonify({'success': True, 'message': 'Wallet funded successfully'}), 200
                    
                    # Handle AIRTIME/DATA purchases (to be implemented)
                    elif txn_type in ['AIRTIME', 'DATA']:
                        print(f'⚠️ Quick Pay VAS purchase not yet implemented: {txn_type}')
                        return jsonify({'success': False, 'message': 'VAS purchase via Quick Pay not yet implemented'}), 501
                    
                    else:
                        print(f'⚠️ Unknown transaction type: {txn_type}')
                        return jsonify({'success': False, 'message': 'Unknown transaction type'}), 400
                
                # Handle Reserved Account transactions (existing logic)
                elif account_reference and account_reference.startswith('FICORE_'):
                    user_id = account_reference.replace('FICORE_', '')
                    
                    # Check for duplicate webhook (idempotency)
                    existing_txn = mongo.db.vas_transactions.find_one({
                        'reference': transaction_reference,
                        'type': 'WALLET_FUNDING'
                    })
                    
                    if existing_txn:
                        print(f'⚠️ Duplicate webhook ignored: {transaction_reference}')
                        return jsonify({'success': True, 'message': 'Already processed'}), 200
                    
                    wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
                    if not wallet:
                        print(f'❌ Wallet not found for user: {user_id}')
                        return jsonify({'success': False, 'message': 'Wallet not found'}), 404
                    
                    # Check if user is premium (no deposit fee)
                    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                    is_premium = user.get('subscriptionStatus') == 'active' if user else False
                    
                    # Apply deposit fee (₦30 for non-premium users)
                    deposit_fee = 0.0 if is_premium else VAS_TRANSACTION_FEE
                    amount_to_credit = amount_paid - deposit_fee
                    
                    # Ensure we don't credit negative amounts
                    if amount_to_credit <= 0:
                        print(f'⚠️ Amount too small after fee: ₦{amount_paid} - ₦{deposit_fee} = ₦{amount_to_credit}')
                        return jsonify({'success': False, 'message': 'Amount too small to process'}), 400
                    
                    new_balance = wallet.get('balance', 0.0) + amount_to_credit
                    
                    mongo.db.vas_wallets.update_one(
                        {'userId': ObjectId(user_id)},
                        {'$set': {'balance': new_balance, 'updatedAt': datetime.utcnow()}}
                    )
                    
                    transaction = {
                        '_id': ObjectId(),
                        'userId': ObjectId(user_id),
                        'type': 'WALLET_FUNDING',
                        'amount': amount_to_credit,
                        'amountPaid': amount_paid,
                        'depositFee': deposit_fee,
                        'reference': transaction_reference,
                        'status': 'SUCCESS',
                        'provider': 'monnify',
                        'metadata': transaction_data,
                        'createdAt': datetime.utcnow()
                    }
                    
                    mongo.db.vas_transactions.insert_one(transaction)
                    
                    # Record corporate revenue (₦30 fee)
                    if deposit_fee > 0:
                        corporate_revenue = {
                            '_id': ObjectId(),
                            'type': 'SERVICE_FEE',
                            'category': 'DEPOSIT_FEE',
                            'amount': deposit_fee,
                            'userId': ObjectId(user_id),
                            'relatedTransaction': transaction_reference,
                            'description': f'Deposit fee from user {user_id}',
                            'status': 'RECORDED',
                            'createdAt': datetime.utcnow(),
                            'metadata': {
                                'amountPaid': amount_paid,
                                'amountCredited': amount_to_credit,
                                'isPremium': is_premium
                            }
                        }
                        mongo.db.corporate_revenue.insert_one(corporate_revenue)
                        print(f'💰 Corporate revenue recorded: ₦{deposit_fee} from user {user_id}')
                    
                    print(f'✅ Reserved Account Wallet Funding: User {user_id}, Paid: ₦{amount_paid}, Fee: ₦{deposit_fee}, Credited: ₦{amount_to_credit}, New Balance: ₦{new_balance}')
                    return jsonify({'success': True, 'message': 'Wallet funded successfully'}), 200
                
                else:
                    print(f'⚠️ Invalid transaction reference format: {transaction_reference}')
                    return jsonify({'success': False, 'message': 'Invalid transaction reference'}), 400
            
            return jsonify({'success': True, 'message': 'Event received'}), 200
            
        except Exception as e:
            print(f'❌ Error processing webhook: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Webhook processing failed',
                'errors': {'general': [str(e)]}
            }), 500
    
    # ==================== VAS PURCHASE ENDPOINTS ====================
    
    @vas_bp.route('/buy-airtime', methods=['POST'])
    @token_required
    def buy_airtime(current_user):
        """Purchase airtime with idempotency protection"""
        try:
            data = request.json
            phone_number = data.get('phoneNumber', '').strip()
            network = data.get('network', '').upper()
            amount = float(data.get('amount', 0))
            
            if not phone_number or not network or amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Invalid request data',
                    'errors': {'general': ['Phone number, network, and amount are required']}
                }), 400
            
            if amount < 100 or amount > 5000:
                return jsonify({
                    'success': False,
                    'message': 'Amount must be between ₦100 and ₦5,000'
                }), 400
            
            user_id = str(current_user['_id'])
            
            # CRITICAL: Check for pending duplicate transaction (idempotency)
            pending_txn = check_pending_transaction(user_id, 'AIRTIME', amount, phone_number)
            if pending_txn:
                print(f'⚠️ Duplicate airtime request blocked for user {user_id}')
                return jsonify({
                    'success': False,
                    'message': 'A similar transaction is already being processed. Please wait.',
                    'errors': {'general': ['Duplicate transaction detected']}
                }), 409
            
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found. Please create a wallet first.'
                }), 404
            
            # NO transaction fee on purchases (fee is only on deposits)
            transaction_fee = 0.0
            total_amount = amount
            
            if wallet.get('balance', 0.0) < total_amount:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient wallet balance. Required: ₦{total_amount:.2f}, Available: ₦{wallet.get("balance", 0.0):.2f}'
                }), 400
            
            # Generate unique request ID
            request_id = generate_request_id(user_id, 'AIRTIME')
            
            # Create PENDING transaction first (idempotency lock)
            vas_transaction = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'type': 'AIRTIME',
                'network': network,
                'phoneNumber': phone_number,
                'amount': amount,
                'transactionFee': transaction_fee,
                'totalAmount': total_amount,
                'status': 'PENDING',
                'provider': None,
                'requestId': request_id,
                'createdAt': datetime.utcnow()
            }
            
            mongo.db.vas_transactions.insert_one(vas_transaction)
            transaction_id = vas_transaction['_id']
            
            success = False
            provider = 'peyflex'
            error_message = ''
            api_response = None
            
            try:
                api_response = call_peyflex_airtime(network, amount, phone_number, request_id)
                success = True
                print(f'✅ Peyflex airtime purchase successful: {request_id}')
            except Exception as peyflex_error:
                print(f'⚠️ Peyflex failed: {str(peyflex_error)}')
                error_message = str(peyflex_error)
                
                try:
                    api_response = call_vtpass_airtime(network, amount, phone_number, request_id)
                    provider = 'vtpass'
                    success = True
                    print(f'✅ VTpass airtime purchase successful (fallback): {request_id}')
                except Exception as vtpass_error:
                    print(f'❌ VTpass failed: {str(vtpass_error)}')
                    error_message = f'Both providers failed. Peyflex: {peyflex_error}, VTpass: {vtpass_error}'
            
            if not success:
                # Update transaction to FAILED
                mongo.db.vas_transactions.update_one(
                    {'_id': transaction_id},
                    {'$set': {'status': 'FAILED', 'errorMessage': error_message, 'updatedAt': datetime.utcnow()}}
                )
                return jsonify({
                    'success': False,
                    'message': 'Purchase failed',
                    'errors': {'general': [error_message]}
                }), 500
            
            # Deduct from wallet
            new_balance = wallet.get('balance', 0.0) - total_amount
            mongo.db.vas_wallets.update_one(
                {'userId': ObjectId(user_id)},
                {'$set': {'balance': new_balance, 'updatedAt': datetime.utcnow()}}
            )
            
            # Update transaction to SUCCESS
            mongo.db.vas_transactions.update_one(
                {'_id': transaction_id},
                {
                    '$set': {
                        'status': 'SUCCESS',
                        'provider': provider,
                        'providerResponse': api_response,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # Auto-create expense entry (auto-bookkeeping)
            expense_entry = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'amount': amount,
                'category': 'Utilities',
                'description': f'Airtime - {network} for {phone_number[-4:]}****',
                'date': datetime.utcnow(),
                'tags': ['VAS', 'Airtime', network],
                'vasTransactionId': transaction_id,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.expenses.insert_one(expense_entry)
            
            print(f'✅ Airtime purchase complete: User {user_id}, Amount: ₦{amount}, Provider: {provider}')
            
            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(transaction_id),
                    'requestId': request_id,
                    'amount': amount,
                    'transactionFee': transaction_fee,
                    'totalAmount': total_amount,
                    'newBalance': new_balance,
                    'provider': provider,
                    'expenseRecorded': True
                },
                'message': 'Airtime purchased successfully! Transaction recorded as expense.'
            }), 200
            
        except Exception as e:
            print(f'❌ Error buying airtime: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to purchase airtime',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/buy-data', methods=['POST'])
    @token_required
    def buy_data(current_user):
        """Purchase data with idempotency protection"""
        try:
            data = request.json
            phone_number = data.get('phoneNumber', '').strip()
            network = data.get('network', '').upper()
            data_plan_id = data.get('dataPlanId', '')
            data_plan_name = data.get('dataPlanName', '')
            amount = float(data.get('amount', 0))
            
            if not phone_number or not network or not data_plan_id or amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Invalid request data',
                    'errors': {'general': ['Phone number, network, data plan, and amount are required']}
                }), 400
            
            user_id = str(current_user['_id'])
            
            # CRITICAL: Check for pending duplicate transaction (idempotency)
            pending_txn = check_pending_transaction(user_id, 'DATA', amount, phone_number)
            if pending_txn:
                print(f'⚠️ Duplicate data request blocked for user {user_id}')
                return jsonify({
                    'success': False,
                    'message': 'A similar transaction is already being processed. Please wait.',
                    'errors': {'general': ['Duplicate transaction detected']}
                }), 409
            
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found. Please create a wallet first.'
                }), 404
            
            # NO transaction fee on purchases (fee is only on deposits)
            transaction_fee = 0.0
            total_amount = amount
            
            if wallet.get('balance', 0.0) < total_amount:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient wallet balance. Required: ₦{total_amount:.2f}, Available: ₦{wallet.get("balance", 0.0):.2f}'
                }), 400
            
            # Generate unique request ID
            request_id = generate_request_id(user_id, 'DATA')
            
            # Create PENDING transaction first (idempotency lock)
            vas_transaction = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'type': 'DATA',
                'network': network,
                'phoneNumber': phone_number,
                'dataPlan': data_plan_name,
                'dataPlanId': data_plan_id,
                'amount': amount,
                'transactionFee': transaction_fee,
                'totalAmount': total_amount,
                'status': 'PENDING',
                'provider': None,
                'requestId': request_id,
                'createdAt': datetime.utcnow()
            }
            
            mongo.db.vas_transactions.insert_one(vas_transaction)
            transaction_id = vas_transaction['_id']
            
            success = False
            provider = 'peyflex'
            error_message = ''
            api_response = None
            
            try:
                api_response = call_peyflex_data(network, data_plan_id, phone_number, request_id)
                success = True
                print(f'✅ Peyflex data purchase successful: {request_id}')
            except Exception as peyflex_error:
                print(f'⚠️ Peyflex failed: {str(peyflex_error)}')
                error_message = str(peyflex_error)
                
                try:
                    api_response = call_vtpass_data(network, data_plan_id, phone_number, request_id)
                    provider = 'vtpass'
                    success = True
                    print(f'✅ VTpass data purchase successful (fallback): {request_id}')
                except Exception as vtpass_error:
                    print(f'❌ VTpass failed: {str(vtpass_error)}')
                    error_message = f'Both providers failed. Peyflex: {peyflex_error}, VTpass: {vtpass_error}'
            
            if not success:
                # Update transaction to FAILED
                mongo.db.vas_transactions.update_one(
                    {'_id': transaction_id},
                    {'$set': {'status': 'FAILED', 'errorMessage': error_message, 'updatedAt': datetime.utcnow()}}
                )
                return jsonify({
                    'success': False,
                    'message': 'Purchase failed',
                    'errors': {'general': [error_message]}
                }), 500
            
            # Deduct from wallet
            new_balance = wallet.get('balance', 0.0) - total_amount
            mongo.db.vas_wallets.update_one(
                {'userId': ObjectId(user_id)},
                {'$set': {'balance': new_balance, 'updatedAt': datetime.utcnow()}}
            )
            
            # Update transaction to SUCCESS
            mongo.db.vas_transactions.update_one(
                {'_id': transaction_id},
                {
                    '$set': {
                        'status': 'SUCCESS',
                        'provider': provider,
                        'providerResponse': api_response,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # Auto-create expense entry (auto-bookkeeping)
            expense_entry = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'amount': amount,
                'category': 'Utilities',
                'description': f'Data - {network} {data_plan_name} for {phone_number[-4:]}****',
                'date': datetime.utcnow(),
                'tags': ['VAS', 'Data', network],
                'vasTransactionId': transaction_id,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.expenses.insert_one(expense_entry)
            
            print(f'✅ Data purchase complete: User {user_id}, Amount: ₦{amount}, Provider: {provider}')
            
            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(transaction_id),
                    'requestId': request_id,
                    'amount': amount,
                    'transactionFee': transaction_fee,
                    'totalAmount': total_amount,
                    'newBalance': new_balance,
                    'provider': provider,
                    'expenseRecorded': True
                },
                'message': 'Data purchased successfully! Transaction recorded as expense.'
            }), 200
            
        except Exception as e:
            print(f'❌ Error buying data: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to purchase data',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/networks/airtime', methods=['GET'])
    def get_airtime_networks():
        """Get list of supported airtime networks"""
        try:
            response = requests.get(
                f'{PEYFLEX_BASE_URL}/api/airtime/networks/',
                timeout=10
            )
            
            if response.status_code == 200:
                return jsonify({
                    'success': True,
                    'data': response.json(),
                    'message': 'Networks retrieved successfully'
                }), 200
            else:
                return jsonify({
                    'success': True,
                    'data': [
                        {'id': 'mtn', 'name': 'MTN'},
                        {'id': 'airtel', 'name': 'Airtel'},
                        {'id': 'glo', 'name': 'Glo'},
                        {'id': '9mobile', 'name': '9mobile'}
                    ],
                    'message': 'Default networks list'
                }), 200
        except Exception as e:
            print(f'⚠️ Error getting networks: {str(e)}')
            return jsonify({
                'success': True,
                'data': [
                    {'id': 'mtn', 'name': 'MTN'},
                    {'id': 'airtel', 'name': 'Airtel'},
                    {'id': 'glo', 'name': 'Glo'},
                    {'id': '9mobile', 'name': '9mobile'}
                ],
                'message': 'Default networks list'
            }), 200
    
    @vas_bp.route('/networks/data', methods=['GET'])
    def get_data_networks():
        """Get list of supported data networks"""
        try:
            response = requests.get(
                f'{PEYFLEX_BASE_URL}/api/data/networks/',
                timeout=10
            )
            
            if response.status_code == 200:
                peyflex_data = response.json()
                print(f'✅ Peyflex data networks response: {peyflex_data}')
                return jsonify({
                    'success': True,
                    'data': peyflex_data,
                    'message': 'Data networks retrieved successfully'
                }), 200
            else:
                print(f'⚠️ Peyflex data networks failed: {response.status_code}')
                # Return default data networks based on Peyflex documentation
                return jsonify({
                    'success': True,
                    'data': [
                        {'id': 'mtn_sme_data', 'name': 'MTN SME Data'},
                        {'id': 'mtn_gifting_data', 'name': 'MTN Gifting Data'},
                        {'id': 'airtel_data', 'name': 'Airtel Data'},
                        {'id': 'glo_data', 'name': 'Glo Data'},
                        {'id': '9mobile_data', 'name': '9mobile Data'},
                    ],
                    'message': 'Default data networks list'
                }), 200
        except Exception as e:
            print(f'⚠️ Error getting data networks: {str(e)}')
            return jsonify({
                'success': True,
                'data': [
                    {'id': 'mtn_sme_data', 'name': 'MTN SME Data'},
                    {'id': 'mtn_gifting_data', 'name': 'MTN Gifting Data'},
                    {'id': 'airtel_data', 'name': 'Airtel Data'},
                    {'id': 'glo_data', 'name': 'Glo Data'},
                    {'id': '9mobile_data', 'name': '9mobile Data'},
                ],
                'message': 'Default data networks list'
            }), 200
        except Exception as e:
            print(f'⚠️ Error getting networks: {str(e)}')
            return jsonify({
                'success': True,
                'data': [
                    {'id': 'mtn', 'name': 'MTN'},
                    {'id': 'airtel', 'name': 'Airtel'},
                    {'id': 'glo', 'name': 'Glo'},
                    {'id': '9mobile', 'name': '9mobile'}
                ],
                'message': 'Default networks list'
            }), 200
    
    @vas_bp.route('/data-plans/<network>', methods=['GET'])
    def get_data_plans(network):
        """Get data plans for a specific network"""
        try:
            # Network should be full ID like 'mtn_sme_data', not just 'mtn'
            url = f'{PEYFLEX_BASE_URL}/api/data/plans/?network={network.lower()}'
            print(f'🔍 Fetching data plans from: {url}')
            
            response = requests.get(url, timeout=10)
            
            print(f'📡 Peyflex response status: {response.status_code}')
            print(f'📡 Peyflex response body: {response.text[:500]}')
            
            if response.status_code == 200:
                plans_data = response.json()
                
                # Check if Peyflex returned empty array
                if isinstance(plans_data, list) and len(plans_data) == 0:
                    print(f'⚠️ Peyflex returned empty array for {network}')
                    print(f'⚠️ Using fallback data plans')
                    plans_data = _get_fallback_data_plans(network)
                
                # Transform plan structure to ensure consistency
                # Peyflex uses 'plan_code' but we need 'id' for frontend
                transformed_plans = []
                for plan in plans_data:
                    transformed_plan = {
                        'id': plan.get('plan_code', plan.get('id', '')),
                        'name': plan.get('name', plan.get('plan_name', '')),
                        'price': plan.get('price', plan.get('amount', 0)),
                        'validity': plan.get('validity', plan.get('validity_days', 30)),
                        'plan_code': plan.get('plan_code', plan.get('id', '')),
                    }
                    transformed_plans.append(transformed_plan)
                
                print(f'✅ Returning {len(transformed_plans)} data plans for {network}')
                
                return jsonify({
                    'success': True,
                    'data': transformed_plans,
                    'message': 'Data plans retrieved successfully'
                }), 200
            else:
                print(f'❌ Peyflex returned error: {response.status_code} - {response.text}')
                print(f'⚠️ Using fallback data plans')
                fallback_plans = _get_fallback_data_plans(network)
                return jsonify({
                    'success': True,
                    'data': fallback_plans,
                    'message': 'Using fallback data plans'
                }), 200
        except Exception as e:
            print(f'❌ Error getting data plans: {str(e)}')
            import traceback
            traceback.print_exc()
            print(f'⚠️ Using fallback data plans')
            fallback_plans = _get_fallback_data_plans(network)
            return jsonify({
                'success': True,
                'data': fallback_plans,
                'message': 'Using fallback data plans'
            }), 200
    
    def _get_fallback_data_plans(network):
        """Return fallback data plans when Peyflex API fails or returns empty"""
        network_lower = network.lower()
        
        # MTN SME Data Plans (most popular)
        if 'mtn_sme' in network_lower or network_lower == 'mtn':
            return [
                {'id': 'M500MBS', 'name': '500MB - 30 Days', 'price': 140, 'validity': 30, 'plan_code': 'M500MBS'},
                {'id': 'M1GB', 'name': '1GB - 30 Days', 'price': 270, 'validity': 30, 'plan_code': 'M1GB'},
                {'id': 'M2GB', 'name': '2GB - 30 Days', 'price': 540, 'validity': 30, 'plan_code': 'M2GB'},
                {'id': 'M3GB', 'name': '3GB - 30 Days', 'price': 810, 'validity': 30, 'plan_code': 'M3GB'},
                {'id': 'M5GB', 'name': '5GB - 30 Days', 'price': 1350, 'validity': 30, 'plan_code': 'M5GB'},
                {'id': 'M10GB', 'name': '10GB - 30 Days', 'price': 2700, 'validity': 30, 'plan_code': 'M10GB'},
            ]
        
        # MTN Gifting Data Plans
        elif 'mtn_gifting' in network_lower:
            return [
                {'id': 'MTN_GIFT_500MB', 'name': '500MB - 30 Days', 'price': 150, 'validity': 30, 'plan_code': 'MTN_GIFT_500MB'},
                {'id': 'MTN_GIFT_1GB', 'name': '1GB - 30 Days', 'price': 280, 'validity': 30, 'plan_code': 'MTN_GIFT_1GB'},
                {'id': 'MTN_GIFT_2GB', 'name': '2GB - 30 Days', 'price': 560, 'validity': 30, 'plan_code': 'MTN_GIFT_2GB'},
                {'id': 'MTN_GIFT_5GB', 'name': '5GB - 30 Days', 'price': 1400, 'validity': 30, 'plan_code': 'MTN_GIFT_5GB'},
            ]
        
        # Airtel Data Plans
        elif 'airtel' in network_lower:
            return [
                {'id': 'AIRTEL_500MB', 'name': '500MB - 30 Days', 'price': 150, 'validity': 30, 'plan_code': 'AIRTEL_500MB'},
                {'id': 'AIRTEL_1GB', 'name': '1GB - 30 Days', 'price': 300, 'validity': 30, 'plan_code': 'AIRTEL_1GB'},
                {'id': 'AIRTEL_2GB', 'name': '2GB - 30 Days', 'price': 600, 'validity': 30, 'plan_code': 'AIRTEL_2GB'},
                {'id': 'AIRTEL_5GB', 'name': '5GB - 30 Days', 'price': 1500, 'validity': 30, 'plan_code': 'AIRTEL_5GB'},
            ]
        
        # Glo Data Plans
        elif 'glo' in network_lower:
            return [
                {'id': 'GLO_500MB', 'name': '500MB - 30 Days', 'price': 150, 'validity': 30, 'plan_code': 'GLO_500MB'},
                {'id': 'GLO_1GB', 'name': '1GB - 30 Days', 'price': 300, 'validity': 30, 'plan_code': 'GLO_1GB'},
                {'id': 'GLO_2GB', 'name': '2GB - 30 Days', 'price': 600, 'validity': 30, 'plan_code': 'GLO_2GB'},
                {'id': 'GLO_5GB', 'name': '5GB - 30 Days', 'price': 1500, 'validity': 30, 'plan_code': 'GLO_5GB'},
            ]
        
        # 9mobile Data Plans
        elif '9mobile' in network_lower:
            return [
                {'id': '9MOB_500MB', 'name': '500MB - 30 Days', 'price': 150, 'validity': 30, 'plan_code': '9MOB_500MB'},
                {'id': '9MOB_1GB', 'name': '1GB - 30 Days', 'price': 300, 'validity': 30, 'plan_code': '9MOB_1GB'},
                {'id': '9MOB_2GB', 'name': '2GB - 30 Days', 'price': 600, 'validity': 30, 'plan_code': '9MOB_2GB'},
                {'id': '9MOB_5GB', 'name': '5GB - 30 Days', 'price': 1500, 'validity': 30, 'plan_code': '9MOB_5GB'},
            ]
        
        # Default fallback
        return [
            {'id': 'DEFAULT_1GB', 'name': '1GB - 30 Days', 'price': 300, 'validity': 30, 'plan_code': 'DEFAULT_1GB'},
            {'id': 'DEFAULT_2GB', 'name': '2GB - 30 Days', 'price': 600, 'validity': 30, 'plan_code': 'DEFAULT_2GB'},
        ]
    
    @vas_bp.route('/transactions', methods=['GET'])
    @token_required
    def get_vas_transactions(current_user):
        """Get user's VAS transaction history"""
        try:
            user_id = str(current_user['_id'])
            
            limit = int(request.args.get('limit', 50))
            skip = int(request.args.get('skip', 0))
            transaction_type = request.args.get('type', None)
            
            query = {'userId': ObjectId(user_id)}
            if transaction_type:
                query['type'] = transaction_type.upper()
            
            transactions = list(
                mongo.db.vas_transactions.find(query)
                .sort('createdAt', -1)
                .skip(skip)
                .limit(limit)
            )
            
            serialized_transactions = []
            for txn in transactions:
                txn_data = serialize_doc(txn)
                txn_data['createdAt'] = txn.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                serialized_transactions.append(txn_data)
            
            return jsonify({
                'success': True,
                'data': serialized_transactions,
                'message': 'Transactions retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'❌ Error getting transactions: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve transactions',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/reserved-account', methods=['GET'])
    @token_required
    def get_reserved_account(current_user):
        """Get user's reserved account details"""
        try:
            user_id = str(current_user['_id'])
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Reserved account not found. Please create a wallet first.'
                }), 404
            
            return jsonify({
                'success': True,
                'data': {
                    'accountReference': wallet.get('accountReference', ''),
                    'accountName': wallet.get('accountName', ''),
                    'accounts': wallet.get('accounts', []),
                    'status': wallet.get('status', 'active'),
                    'createdAt': wallet.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                },
                'message': 'Reserved account retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'❌ Error getting reserved account: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve reserved account',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/reserved-account/transactions', methods=['GET'])
    @token_required
    def get_reserved_account_transactions(current_user):
        """Get user's reserved account transaction history (wallet funding transactions)"""
        try:
            user_id = str(current_user['_id'])
            
            limit = int(request.args.get('limit', 50))
            skip = int(request.args.get('skip', 0))
            
            # Get only WALLET_FUNDING transactions
            transactions = list(
                mongo.db.vas_transactions.find({
                    'userId': ObjectId(user_id),
                    'type': 'WALLET_FUNDING'
                })
                .sort('createdAt', -1)
                .skip(skip)
                .limit(limit)
            )
            
            serialized_transactions = []
            for txn in transactions:
                txn_data = serialize_doc(txn)
                # Ensure createdAt is a string for frontend compatibility
                txn_data['createdAt'] = txn.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                # Add reference and description for frontend display
                txn_data['reference'] = txn.get('reference', '')
                txn_data['description'] = f"Wallet Funding - ₦{txn.get('amount', 0):.2f}"
                serialized_transactions.append(txn_data)
            
            return jsonify({
                'success': True,
                'data': serialized_transactions,
                'message': 'Reserved account transactions retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'❌ Error getting reserved account transactions: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve reserved account transactions',
                'errors': {'general': [str(e)]}
            }), 500
    
    return vas_bp
