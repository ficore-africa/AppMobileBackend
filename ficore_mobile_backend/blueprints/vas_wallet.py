"""
VAS Wallet Management Module - Production Grade
Handles wallet creation, funding, balance management, and reserved accounts

Security: API keys in environment variables, idempotency protection, webhook verification
Providers: Monnify (primary wallet provider)
Features: Reserved accounts, KYC verification, multi-bank support, webhook processing
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
import os
import requests
import hmac
import hashlib
import sys

# Force immediate output flushing for print statements in production
def debug_print(message):
    """Print with immediate flush for production debugging"""
    print(message)
    sys.stdout.flush()

# VAS Debug logging function
def vas_log(message):
    """VAS-specific logging that works in production"""
    debug_print(f"VAS_DEBUG: {message}")
    # Also try app logger if available
    try:
        from flask import current_app
        if current_app:
            current_app.logger.info(f"VAS_DEBUG: {message}")
    except:
        pass
import uuid
import json
import pymongo
import time
import queue
import threading
from utils.email_service import get_email_service
from blueprints.notifications import create_user_notification

import threading
import queue
import json
import time
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
import os
import requests
from bson import ObjectId

# 🚀 INSTANT BALANCE UPDATE INFRASTRUCTURE - GLOBAL
# REMOVED: Memory-intensive SSE infrastructure replaced with simple polling
# The following SSE components were causing server memory exhaustion:
# - balance_update_queues: Per-user queues consuming memory
# - active_connections: Connection tracking with threading overhead  
# - balance_update_lock: Threading synchronization overhead
# - Persistent connections lasting 15+ minutes each
# - Heartbeat mechanisms consuming CPU cycles
#
# SOLUTION: Simple polling endpoint /balance/current that clients call every few seconds
# Benefits: No persistent connections, no memory buildup, much simpler architecture

def init_vas_wallet_blueprint(mongo, token_required, serialize_doc):
    vas_wallet_bp = Blueprint('vas_wallet', __name__, url_prefix='/api/vas/wallet')
    
    # CRITICAL FIX (Feb 12, 2026): Create alias blueprint for PIN endpoints without /api prefix
    # Frontend calls /vas/wallet/pin/* but backend has /api/vas/wallet/pin/*
    # App already submitted to Play Store, so we add backend aliases instead of changing frontend
    vas_wallet_alias_bp = Blueprint('vas_wallet_alias', __name__, url_prefix='/vas/wallet')
    
    # Environment variables (NEVER hardcode these)
    MONNIFY_API_KEY = os.environ.get('MONNIFY_API_KEY', '')
    MONNIFY_SECRET_KEY = os.environ.get('MONNIFY_SECRET_KEY', '')
    MONNIFY_CONTRACT_CODE = os.environ.get('MONNIFY_CONTRACT_CODE', '')
    MONNIFY_BASE_URL = os.environ.get('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')
    
    VAS_TRANSACTION_FEE = 30.0
    ACTIVATION_FEE = 100.0
    BVN_VERIFICATION_COST = 10.0
    NIN_VERIFICATION_COST = 60.0
    
    # ==================== HELPER FUNCTIONS ====================
    
    def get_wallet_by_user_id(user_id_str, auto_fetch_accounts=True):
        """
        Get wallet by user ID with automatic string-to-ObjectId fix and account fetching.
        
        BUGFIX: Some wallets were created with string userId instead of ObjectId.
        This function tries both formats and auto-fixes string userId to ObjectId.
        
        AUTO-RECOVERY: If wallet has no accounts, automatically fetches from Monnify.
        
        Args:
            user_id_str: User ID as string
            auto_fetch_accounts: If True, automatically fetch accounts from Monnify if empty
            
        Returns:
            Wallet document or None
        """
        user_id_obj = ObjectId(user_id_str)
        
        # Try ObjectId first (correct format)
        wallet = mongo.db.vas_wallets.find_one({'userId': user_id_obj})
        
        if not wallet:
            # Fallback: Try string format (the bug)
            wallet = mongo.db.vas_wallets.find_one({'userId': user_id_str})
            
            if wallet:
                # Found with string - fix it immediately
                print(f'🔧 AUTO-FIX: Wallet {wallet["_id"]} has string userId, converting to ObjectId')
                mongo.db.vas_wallets.update_one(
                    {'_id': wallet['_id']},
                    {'$set': {'userId': user_id_obj}}
                )
                wallet['userId'] = user_id_obj  # Update in-memory
        
        # AUTO-RECOVERY: Fetch accounts from Monnify if empty
        if wallet and auto_fetch_accounts:
            accounts = wallet.get('accounts', [])
            if not accounts or len(accounts) == 0:
                print(f'🔧 AUTO-RECOVERY: Wallet {wallet["_id"]} has no accounts, fetching from Monnify...')
                try:
                    access_token = call_monnify_auth()
                    account_ref = wallet.get('accountReference', user_id_str)
                    
                    fetch_response = requests.get(
                        f'{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts/{account_ref}',
                        headers={'Authorization': f'Bearer {access_token}'},
                        timeout=30
                    )
                    
                    if fetch_response.status_code == 200:
                        fetch_data = fetch_response.json()
                        if fetch_data.get('requestSuccessful'):
                            monnify_accounts = fetch_data['responseBody'].get('accounts', [])
                            if monnify_accounts:
                                # Update wallet with fetched accounts
                                mongo.db.vas_wallets.update_one(
                                    {'_id': wallet['_id']},
                                    {'$set': {
                                        'accounts': monnify_accounts,
                                        'updatedAt': datetime.utcnow(),
                                        'accountsRecoveredAt': datetime.utcnow()
                                    }}
                                )
                                wallet['accounts'] = monnify_accounts  # Update in-memory
                                print(f'✅ AUTO-RECOVERY: Restored {len(monnify_accounts)} accounts from Monnify')
                            else:
                                print(f'⚠️ AUTO-RECOVERY: Monnify returned no accounts')
                        else:
                            print(f'⚠️ AUTO-RECOVERY: Monnify error: {fetch_data.get("responseMessage")}')
                    else:
                        print(f'⚠️ AUTO-RECOVERY: Monnify fetch failed (status {fetch_response.status_code})')
                except Exception as e:
                    print(f'⚠️ AUTO-RECOVERY: Failed to fetch accounts: {str(e)}')
        
        return wallet
    
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
            print(f'ERROR: Monnify auth error: {str(e)}')
            raise
    
    def check_eligibility(user_id):
        """
        Check if user is eligible for dedicated account (Path B)
        User must meet ONE of these criteria:
        1. Used app for 3+ consecutive days
        2. Recorded 10+ transactions (income/expense)
        """
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        # Check 1: Consecutive days - Use rewards.streak as authoritative source
        rewards_record = mongo.db.rewards.find_one({'user_id': ObjectId(user_id)})
        login_streak = rewards_record.get('streak', 0) if rewards_record else 0
        if login_streak >= 3:
            return True, "3-day streak"
        
        # Check 2: Total transactions
        total_txns = mongo.db.income.count_documents({'userId': ObjectId(user_id)})
        total_txns += mongo.db.expenses.count_documents({'userId': ObjectId(user_id)})
        if total_txns >= 10:
            return True, "10+ transactions"
        
        return False, None
    
    def get_eligibility_progress(user_id):
        """Get user's progress towards eligibility"""
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        # Use rewards.streak as authoritative source for login streak
        rewards_record = mongo.db.rewards.find_one({'user_id': ObjectId(user_id)})
        login_streak = rewards_record.get('streak', 0) if rewards_record else 0
        total_txns = mongo.db.income.count_documents({'userId': ObjectId(user_id)})
        total_txns += mongo.db.expenses.count_documents({'userId': ObjectId(user_id)})
        
        # Return flat structure that matches frontend expectations
        return {
            'loginDays': login_streak,  # Frontend expects 'loginDays', not 'loginStreak'
            'totalTransactions': total_txns
        }
    
    def call_monnify_bvn_verification(bvn, name, dob, mobile):
        """
        Call Monnify BVN verification API
        Cost: ₦ 10 per successful request
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
            print(f'ERROR: BVN verification error: {str(e)}')
            raise
    
    def call_monnify_nin_verification(nin):
        """
        Call Monnify NIN verification API
        Cost: ₦ 60 per successful request
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
            print(f'ERROR: NIN verification error: {str(e)}')
            raise
    
    # ==================== WALLET ENDPOINTS ====================
    
    @vas_wallet_bp.route('/create', methods=['POST'])
    @token_required
    def create_wallet(current_user):
        """Create virtual account number (VAN) for user via Monnify - REQUIRES KYC for compliance"""
        try:
            user_id = str(current_user['_id'])
            
            existing_wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if existing_wallet:
                return jsonify({
                    'success': True,
                    'data': serialize_doc(existing_wallet),
                    'message': 'Wallet already exists'
                }), 200
            
            # CRITICAL COMPLIANCE FIX: Check if user has completed KYC verification
            # REMOVED: BVN/NIN check for wallet creation
            # Since we now use internal KYC system, users can create wallets
            # and submit KYC separately. The closed-loop system has minimal risk.
            
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
                'accountReference': user_id,  # STANDARDIZED: Use ObjectId string only
                'accountName': f"{current_user.get('firstName', '')} {current_user.get('lastName', '')}".strip()[:50],  # Monnify 50-char limit
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'customerEmail': current_user.get('email', ''),
                'customerName': f"{current_user.get('firstName', '')} {current_user.get('lastName', '')}".strip()[:50],  # Monnify 50-char limit
                # BVN/NIN removed - using internal KYC system
                'getAllAvailableBanks': True
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
            
            van_data = None
            
            if van_response.status_code != 200:
                # Parse Monnify error response
                error_data = van_response.json()
                error_message = error_data.get('responseMessage', 'Unknown error')
                error_code = error_data.get('responseCode', '99')
                
                # Check if account already exists (duplicate error)
                if 'already' in error_message.lower() or 'duplicate' in error_message.lower() or 'exists' in error_message.lower():
                    print(f'INFO: Account already exists in Monnify for user {user_id}, fetching existing account...')
                    
                    # Fetch existing account from Monnify
                    fetch_response = requests.get(
                        f'{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts/{user_id}',
                        headers={'Authorization': f'Bearer {access_token}'},
                        timeout=30
                    )
                    
                    if fetch_response.status_code == 200:
                        fetch_data = fetch_response.json()
                        if fetch_data.get('requestSuccessful'):
                            van_data = fetch_data['responseBody']
                            print(f'✅ Successfully fetched existing account from Monnify')
                        else:
                            raise Exception(f'Failed to fetch existing account: {fetch_data.get("responseMessage")}')
                    else:
                        raise Exception(f'Failed to fetch existing account: {fetch_response.text}')
                
                # Check if error is BVN/NIN requirement
                elif 'BVN' in error_message or 'NIN' in error_message or error_code == '99':
                    print(f'INFO: Monnify requires KYC for user {user_id}')
                    return jsonify({
                        'success': False,
                        'requiresKyc': True,
                        'message': 'Identity verification required',
                        'userMessage': {
                            'title': 'Verification Required',
                            'message': 'To use VAS features, we need to verify your identity. Please submit your BVN or NIN.',
                            'action': 'submit_kyc',
                            'type': 'info'
                        },
                        'errors': {'kyc': ['BVN or NIN verification required']}
                    }), 400  # 400 instead of 500 - this is a client action required
                else:
                    # Other Monnify errors
                    raise Exception(f'VAN creation failed: {van_response.text}')
            else:
                # Success - account created
                van_data = van_response.json()['responseBody']
            
            # Ensure we have van_data at this point
            if not van_data:
                raise Exception('Failed to create or fetch account from Monnify')
            
            wallet = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'balance': 0.0,
                'accountReference': van_data['accountReference'],
                'accountName': van_data['accountName'],
                'accounts': van_data['accounts'],
                'status': 'active',
                'tier': 'TIER_1',  # Basic account - will upgrade when KYC verified
                'kycTier': 1,  # Will be updated to 2 when internal KYC is verified
                'kycVerified': False,  # Will be updated when internal KYC is verified
                'kycStatus': 'pending',  # Will be updated by internal KYC system
                # BVN/NIN removed - using internal KYC system
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
            error_str = str(e)
            print(f'ERROR: Error creating wallet: {error_str}')
            
            # Check if error is BVN/NIN related (fallback check)
            if 'BVN' in error_str or 'NIN' in error_str:
                return jsonify({
                    'success': False,
                    'requiresKyc': True,
                    'message': 'Identity verification required',
                    'userMessage': {
                        'title': 'Verification Required',
                        'message': 'To use VAS features, we need to verify your identity. Please submit your BVN or NIN for verification.',
                        'action': 'submit_kyc',
                        'type': 'info'
                    },
                    'errors': {'kyc': ['BVN or NIN verification required']}
                }), 400
            
            # Generic error
            return jsonify({
                'success': False,
                'message': 'Failed to create wallet',
                'userMessage': {
                    'title': 'Wallet Creation Failed',
                    'message': 'We couldn\'t create your VAS wallet at this time. Please try again later or contact support.',
                    'type': 'error'
                },
                'errors': {'general': [error_str]}
            }), 500
    
    @vas_wallet_bp.route('/balance', methods=['GET'])
    @token_required
    def get_wallet_balance(current_user):
        """Get user's wallet balance with available balance calculation"""
        try:
            user_id = str(current_user['_id'])
            wallet = get_wallet_by_user_id(user_id)
            
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found. Please create a wallet first.'
                }), 404
            
            # Import the available balance function
            from utils.transaction_task_queue import get_user_available_balance
            
            total_balance = wallet.get('balance', 0.0)
            reserved_amount = wallet.get('reservedAmount', 0.0)
            available_balance = get_user_available_balance(mongo.db, user_id)
            
            return jsonify({
                'success': True,
                'data': {
                    'totalBalance': total_balance,
                    'reservedAmount': reserved_amount,
                    'availableBalance': available_balance,
                    'accounts': wallet.get('accounts', []),
                    'accountName': wallet.get('accountName', ''),
                    'status': wallet.get('status', 'active')
                },
                'message': 'Wallet balance retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting wallet balance: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve wallet balance',
                'errors': {'general': [str(e)]}
            }), 500
    
    # 🚀 SIMPLE BALANCE POLLING - REPLACES MEMORY-INTENSIVE SSE
    @vas_wallet_bp.route('/balance/current', methods=['GET'])
    @token_required
    def get_current_balance(current_user):
        """Get current wallet balance - lightweight polling endpoint
        
        Returns 404 with helpful message if wallet doesn't exist yet.
        Frontend should handle this by triggering wallet creation.
        """
        try:
            user_id = str(current_user['_id'])
            wallet = get_wallet_by_user_id(user_id)
            
            if not wallet:
                # ENHANCED ERROR RESPONSE: Provide actionable information
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found',
                    'userMessage': {
                        'title': 'Wallet Setup Required',
                        'message': 'Your VAS wallet needs to be set up. This will only take a moment.',
                        'action': 'create_wallet',
                        'type': 'info'
                    },
                    'errors': {'wallet': ['No wallet found for user']},
                    'requiresSetup': True  # Flag for frontend to trigger wallet creation
                }), 404
            
            from utils.transaction_task_queue import get_user_available_balance
            
            total_balance = wallet.get('balance', 0.0)
            reserved_amount = wallet.get('reservedAmount', 0.0)
            available_balance = get_user_available_balance(mongo.db, user_id)
            
            # Also get liquid wallet balance for complete picture
            user_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            liquid_wallet_balance = user_doc.get('liquidWalletBalance', 0.0) if user_doc else 0.0
            
            balance_data = {
                'success': True,
                'data': {
                    'totalBalance': total_balance,
                    'reservedAmount': reserved_amount,
                    'availableBalance': available_balance,
                    'liquidWalletBalance': liquid_wallet_balance,
                    'timestamp': datetime.utcnow().isoformat(),
                    'source': 'polling_endpoint',
                    'walletStatus': wallet.get('status', 'active'),
                    'hasReservedAccount': len(wallet.get('accounts', [])) > 0
                }
            }
            
            return jsonify(balance_data)
            
        except Exception as e:
            print(f'ERROR: Failed to get current balance: {str(e)}')
            import traceback
            traceback.print_exc()  # Print full stack trace for debugging
            
            return jsonify({
                'success': False,
                'message': 'Failed to get balance',
                'userMessage': {
                    'title': 'Unable to Load Balance',
                    'message': 'We couldn\'t load your wallet balance. Please try again or contact support if the issue persists.',
                    'type': 'error'
                },
                'errors': {'general': [str(e)]},
                'stackTrace': traceback.format_exc() if os.environ.get('FLASK_ENV') == 'development' else None
            }), 500
    
    @vas_wallet_bp.route('/pending-tasks', methods=['GET'])
    @token_required
    def get_pending_tasks(current_user):
        """Get user's pending transaction tasks for frontend display"""
        try:
            user_id = str(current_user['_id'])
            
            # Find pending tasks for this user
            pending_tasks = list(mongo.db.transaction_tasks.find({
                'data.user_id': user_id,
                'status': 'PENDING'
            }).sort('created_at', -1).limit(10))
            
            # Transform tasks for frontend
            tasks_data = []
            for task in pending_tasks:
                task_data = task.get('data', {})
                tasks_data.append({
                    'taskId': task.get('id', str(task['_id'])),
                    'transactionId': task_data.get('transaction_id'),
                    'amount': task_data.get('amount_to_debit', 0),
                    'description': task_data.get('description', 'Processing...'),
                    'provider': task_data.get('provider', 'Unknown'),
                    'createdAt': task.get('created_at', datetime.utcnow()).isoformat(),
                    'attempts': task.get('attempts', 0),
                    'status': 'PROCESSING'
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'pendingTasks': tasks_data,
                    'totalPending': len(tasks_data)
                },
                'message': 'Pending tasks retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting pending tasks: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve pending tasks',
                'errors': {'general': [str(e)]}
            }), 500
    
    # ==================== ELIGIBILITY & KYC ENDPOINTS ====================
    
    @vas_wallet_bp.route('/check-eligibility', methods=['GET'])
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
            print(f'ERROR: Error checking eligibility: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to check eligibility',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_wallet_bp.route('/check-existing-bvn-nin', methods=['POST'])
    @token_required
    def check_existing_bvn_nin(current_user):
        """
        Check if BVN or NIN already exists in the database
        """
        try:
            data = request.json
            bvn = data.get('bvn', '').strip()
            nin = data.get('nin', '').strip()
            
            # Validate input
            if len(bvn) != 11 or not bvn.isdigit():
                return jsonify({
                    'success': False,
                    'exists': False,
                    'message': 'Invalid BVN format'
                }), 400
            
            if len(nin) != 11 or not nin.isdigit():
                return jsonify({
                    'success': False,
                    'exists': False,
                    'message': 'Invalid NIN format'
                }), 400
            
            # Check if BVN exists in any wallet
            bvn_exists = mongo.db.vas_wallets.find_one({
                'bvn': bvn,
                'status': 'ACTIVE'
            })
            
            # Check if NIN exists in any wallet
            nin_exists = mongo.db.vas_wallets.find_one({
                'nin': nin,
                'status': 'ACTIVE'
            })
            
            # Also check in user profiles
            bvn_in_profile = mongo.db.users.find_one({
                'bvn': bvn
            })
            
            nin_in_profile = mongo.db.users.find_one({
                'nin': nin
            })
            
            exists = bool(bvn_exists or nin_exists or bvn_in_profile or nin_in_profile)
            
            if exists:
                message = 'This BVN or NIN has already been used for account creation.'
            else:
                message = 'BVN and NIN are available for use.'
            
            return jsonify({
                'success': True,
                'exists': exists,
                'message': message,
                'details': {
                    'bvn_in_wallet': bool(bvn_exists),
                    'nin_in_wallet': bool(nin_exists),
                    'bvn_in_profile': bool(bvn_in_profile),
                    'nin_in_profile': bool(nin_in_profile)
                }
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error checking existing BVN/NIN: {str(e)}')
            return jsonify({
                'success': False,
                'exists': False,
                'message': 'Error checking records',
                'error': str(e)
            }), 500
    @vas_wallet_bp.route('/verify-bvn', methods=['POST'])
    @token_required
    def verify_bvn(current_user):
        """
        Submit KYC information internally - NO external charges
        Uses new internal KYC system instead of external verification
        """
        try:
            data = request.json
            bvn = data.get('bvn', '').strip()
            nin = data.get('nin', '').strip()
            phone_number = data.get('phoneNumber', '').strip()
            
            print(f"INFO: Internal KYC Submission Request - BVN: {bvn[:3]}***, NIN: {nin[:3]}***, Phone: {phone_number}")
            
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
            
            if not phone_number:
                return jsonify({
                    'success': False,
                    'message': 'Phone number is required.'
                }), 400
            
            # Validate phone number format
            if len(phone_number) < 10 or len(phone_number) > 14:
                return jsonify({
                    'success': False,
                    'message': 'Invalid phone number format.'
                }), 400
            
            user_id = str(current_user['_id'])
            
            # Check if user already has a KYC submission
            existing_submission = mongo.db.kyc_submissions.find_one({'userId': ObjectId(user_id)})
            if existing_submission and existing_submission.get('status') in ['VERIFIED']:
                return jsonify({
                    'success': False,
                    'message': 'Your KYC is already verified.',
                    'status': 'ALREADY_VERIFIED'
                }), 400
            
            # Use user profile data
            user_name = f"{current_user.get('firstName', '')} {current_user.get('lastName', '')}".strip()
            user_email = current_user.get('email', '').strip()
            
            # Submit KYC internally using the internal KYC blueprint
            from utils.kyc_encryption import encrypt_sensitive_data
            
            submission_data = {
                'userId': ObjectId(user_id),
                'submissionType': 'BVN',
                'bvnNumber': encrypt_sensitive_data(bvn),
                'ninNumber': encrypt_sensitive_data(nin),
                'firstName': current_user.get('firstName', '').strip(),
                'lastName': current_user.get('lastName', '').strip(),
                'phoneNumber': phone_number,
                'submittedAt': datetime.utcnow(),
                'status': 'SUBMITTED',
                'metadata': {
                    'ipAddress': request.remote_addr,
                    'userAgent': request.headers.get('User-Agent', ''),
                    'submissionSource': 'vas_verification',
                    'encryptionUsed': True
                }
            }
            
            # Insert or update submission
            if existing_submission:
                mongo.db.kyc_submissions.update_one(
                    {'userId': ObjectId(user_id)},
                    {
                        '$set': submission_data,
                        '$unset': {'verifiedAt': '', 'verifiedBy': '', 'rejectionReason': ''}
                    }
                )
                submission_id = existing_submission['_id']
            else:
                result = mongo.db.kyc_submissions.insert_one(submission_data)
                submission_id = result.inserted_id
            
            # Update user status to show KYC submitted
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {
                    '$set': {
                        'kycStatus': 'SUBMITTED',
                        'kycSubmittedAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            print(f"SUCCESS: KYC submitted internally for user {user_id} - NO external charges")
            
            return jsonify({
                'success': True,
                'data': {
                    'submissionId': str(submission_id),
                    'status': 'SUBMITTED',
                    'submittedAt': submission_data['submittedAt'].isoformat() + 'Z',
                    'message': 'Your KYC information is under review. You will be notified once verified.'
                },
                'message': 'KYC information submitted successfully! Your verification is under review.'
            }), 200
            
            # If no name in profile, use a default
            if not user_name:
                user_name = f"FiCore User {user_id[:8]}"
            
            print(f"INFO: Account creation details - Name: '{user_name}', Phone: '{phone_number}', Email: '{user_email}'")
            
            # Create dedicated account immediately using Monnify account creation (not verification)
            # This is the original working approach - send BVN directly to create account
            access_token = call_monnify_auth()
            
            account_data = {
                'accountReference': user_id,  # STANDARDIZED: Use ObjectId string only
                'accountName': user_name[:50],  # Monnify 50-char limit
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'customerEmail': user_email,
                'customerName': user_name[:50],  # Monnify 50-char limit
                'bvn': bvn,
                'nin': nin,
                'getAllAvailableBanks': True  # Get all available banks for user choice
            }
            
            # print(f"DEBUG: Creating Monnify reserved account with BVN: {bvn[:3]}***{bvn[-3:]}")
            
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
                print(f"ERROR: Monnify account creation failed: {van_response.status_code} - {van_response.text}")
                raise Exception(f'Reserved account creation failed: {van_response.text}')
            
            van_data = van_response.json()['responseBody']
            print(f"SUCCESS: Monnify account created successfully with {len(van_data.get('accounts', []))} banks")
            
            # Update user profile with KYC data including BVN/NIN
            profile_update = {
                'phone': phone_number,  # Save phone number to profile
                'bvn': bvn,          # Save BVN (for future reference)
                'nin': nin,          # Save NIN (for future reference)
                'kycStatus': 'verified',  # Mark KYC as completed
                'kycVerifiedAt': datetime.utcnow(),
                'bvnVerified': True,
                'ninVerified': True,
                'verificationStatus': 'VERIFIED',
                'updatedAt': datetime.utcnow()
            }
            
            # Only update full name if it's more complete than current profile
            current_display_name = current_user.get('displayName', '').strip()
            if len(user_name) > len(current_display_name):
                profile_update['displayName'] = user_name
            
            # Update user profile (single update with all data)
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': profile_update}
            )
            
            print(f"SUCCESS: Updated user profile with KYC data: phone={phone_number}, BVN/NIN stored, KYC=verified")
            
            # Create wallet record with KYC verification
            wallet_data = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'balance': 0.0,
                'accountReference': van_data['accountReference'],
                'contractCode': van_data['contractCode'],
                'accounts': van_data['accounts'],
                'status': 'ACTIVE',
                'tier': 'TIER_2',  # Full KYC verified account
                'kycTier': 2,  # CRITICAL FIX: Set kycTier for proper frontend display
                'kycVerified': True,
                'kycStatus': 'verified',
                'bvn': bvn,
                'nin': nin,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.vas_wallets.insert_one(wallet_data)
            
            # Record business expense for account creation (business absorbs verification costs)
            business_expense = {
                '_id': ObjectId(),
                'type': 'ACCOUNT_CREATION_COSTS',
                'amount': 70.0,  # ₦ 10 BVN + ₦ 60 NIN (absorbed by business)
                'userId': ObjectId(user_id),
                'description': f'Account creation costs for user {user_id} (BVN/NIN verification absorbed by business)',
                'status': 'RECORDED',
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'bvnCost': 10.0,
                    'ninCost': 60.0,
                    'businessExpense': True,
                    'userCharged': False,
                    'accountCreation': True
                }
            }
            mongo.db.business_expenses.insert_one(business_expense)
            
            print(f'SUCCESS: FREE account creation completed for user {user_id}: {user_name}')
            print(f'EXPENSE: Business expense recorded: ₦ 70 verification costs (absorbed by business)')
            
            # Return all accounts for frontend to choose from
            return jsonify({
                'success': True,
                'data': {
                    'accounts': van_data['accounts'],  # All available bank accounts
                    'accountReference': van_data['accountReference'],
                    'contractCode': van_data['contractCode'],
                    'tier': 'TIER_2',
                    'kycVerified': True,
                    'verifiedName': user_name,
                    'createdAt': wallet_data['createdAt'].isoformat() + 'Z',
                    # Keep backward compatibility - return first account as default
                    'defaultAccount': {
                        'accountNumber': van_data['accounts'][0].get('accountNumber', '') if van_data['accounts'] else '',
                        'accountName': van_data['accounts'][0].get('accountName', '') if van_data['accounts'] else '',
                        'bankName': van_data['accounts'][0].get('bankName', 'Wema Bank') if van_data['accounts'] else 'Wema Bank',
                        'bankCode': van_data['accounts'][0].get('bankCode', '035') if van_data['accounts'] else '035',
                    }
                },
                'message': f'Account created successfully with {len(van_data["accounts"])} available banks!'
            }), 201
            
        except Exception as e:
            print(f'ERROR: Error verifying BVN/NIN: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Verification failed',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_wallet_bp.route('/validation/validate-details', methods=['POST'])
    @token_required
    def validate_kyc_details(current_user):
        """Pre-validate BVN/NIN format before payment to reduce errors"""
        try:
            data = request.get_json()
            
            bvn = data.get('bvn', '').strip()
            nin = data.get('nin', '').strip()
            
            errors = []
            
            # Validate BVN format
            if not bvn:
                errors.append('BVN is required')
            elif len(bvn) != 11 or not bvn.isdigit():
                errors.append('BVN must be exactly 11 digits')
            
            # Validate NIN format
            if not nin:
                errors.append('NIN is required')
            elif len(nin) != 11 or not nin.isdigit():
                errors.append('NIN must be exactly 11 digits')
            
            # Check if BVN and NIN are the same (common mistake)
            if bvn and nin and bvn == nin:
                errors.append('BVN and NIN cannot be the same number')
            
            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Please correct the following errors before proceeding',
                    'errors': {'validation': errors},
                    'warning': 'Double-check your details to avoid losing the ₦ 70 non-refundable government verification fee'
                }), 400
            
            return jsonify({
                'success': True,
                'message': 'Details format validated successfully',
                'data': {
                    'bvnValid': True,
                    'ninValid': True,
                    'readyForPayment': True
                },
                'disclaimer': {
                    'nonRefundable': True,
                    'governmentFee': True,
                    'warning': 'IMPORTANT: The ₦ 70 verification fee is a government charge and is NON-REFUNDABLE. If your BVN/NIN details are incorrect, you will need to pay again.',
                    'advice': 'Please triple-check your BVN and NIN numbers before proceeding to payment.'
                }
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error validating KYC details: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': {'general': [str(e)]}
            }), 500

    @vas_wallet_bp.route('/confirm-kyc', methods=['POST'])
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
                'accountReference': user_id,  # STANDARDIZED: Use ObjectId string only
                'accountName': verification['verifiedName'][:50],  # Monnify 50-char limit
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'customerEmail': current_user.get('email', ''),
                'customerName': verification['verifiedName'][:50],  # Monnify 50-char limit
                'bvn': verification['bvn'],
                'nin': verification['nin'],  # Include NIN for full Tier 2 compliance
                'getAllAvailableBanks': True  # Moniepoint default, user choice
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
            
            # CRITICAL FIX: Update user profile with BVN/NIN to prevent future linked account issues
            user_profile_update = {
                'bvn': verification['bvn'],
                'nin': verification['nin'],
                'kycStatus': 'verified',
                'kycVerifiedAt': datetime.utcnow(),
                'bvnVerified': True,
                'ninVerified': True,
                'verificationStatus': 'VERIFIED',
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': user_profile_update}
            )
            
            print(f'SUCCESS: Updated user profile with BVN/NIN verification: {user_id}')
            print(f'SUCCESS: Reserved account created for user {user_id}')
            
            return jsonify({
                'success': True,
                'data': serialize_doc(wallet),
                'message': 'Account created successfully'
            }), 201
            
        except Exception as e:
            print(f'ERROR: Error confirming KYC: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to create account',
                'errors': {'general': [str(e)]}
            }), 500
    
    # ==================== RESERVED ACCOUNT ENDPOINTS ====================
    
    @vas_wallet_bp.route('/reserved-account/create', methods=['POST'])
    @token_required
    def create_reserved_account(current_user):
        """Create a reserved account - REQUIRES KYC verification for compliance"""
        try:
            user_id = str(current_user['_id'])
            
            # Check if wallet already exists
            existing_wallet = get_wallet_by_user_id(user_id)
            if existing_wallet:
                # CRITICAL FIX: Check if accounts array exists and has elements
                accounts = existing_wallet.get('accounts', [])
                if accounts and len(accounts) > 0:
                    # Wallet has valid accounts, return existing
                    return jsonify({
                        'success': True,
                        'data': {
                            'accountNumber': accounts[0].get('accountNumber', ''),
                            'accountName': accounts[0].get('accountName', ''),
                            'bankName': accounts[0].get('bankName', 'Wema Bank'),
                            'bankCode': accounts[0].get('bankCode', '035'),
                            'createdAt': existing_wallet.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                        },
                        'message': 'Reserved account already exists'
                    }), 200
                else:
                    # CRITICAL: NEVER DELETE WALLETS!
                    # If wallet exists but has no accounts, try to fetch from Monnify and update
                    print(f'⚠️ WARNING: Wallet exists but has no accounts for user {user_id}')
                    print(f'   Attempting to fetch accounts from Monnify...')
                    
                    # Try to fetch existing reserved accounts from Monnify
                    try:
                        access_token = call_monnify_auth()
                        account_ref = existing_wallet.get('accountReference', user_id)
                        
                        fetch_response = requests.get(
                            f'{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts/{account_ref}',
                            headers={'Authorization': f'Bearer {access_token}'},
                            timeout=30
                        )
                        
                        if fetch_response.status_code == 200:
                            fetch_data = fetch_response.json()
                            if fetch_data.get('requestSuccessful'):
                                monnify_accounts = fetch_data['responseBody'].get('accounts', [])
                                if monnify_accounts:
                                    # Update wallet with fetched accounts
                                    mongo.db.vas_wallets.update_one(
                                        {'_id': existing_wallet['_id']},
                                        {'$set': {'accounts': monnify_accounts, 'updatedAt': datetime.utcnow()}}
                                    )
                                    print(f'✅ Successfully restored {len(monnify_accounts)} accounts from Monnify')
                                    
                                    return jsonify({
                                        'success': True,
                                        'data': {
                                            'accountNumber': monnify_accounts[0].get('accountNumber', ''),
                                            'accountName': monnify_accounts[0].get('accountName', ''),
                                            'bankName': monnify_accounts[0].get('bankName', 'Wema Bank'),
                                            'bankCode': monnify_accounts[0].get('bankCode', '035'),
                                            'createdAt': existing_wallet.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                                        },
                                        'message': 'Reserved account restored successfully'
                                    }), 200
                    except Exception as e:
                        print(f'ERROR: Failed to fetch accounts from Monnify: {str(e)}')
                    
                    # If we couldn't fetch accounts, return error but NEVER delete wallet
                    return jsonify({
                        'success': False,
                        'message': 'Wallet exists but accounts are missing. Please contact support.',
                        'errors': {'wallet': ['Wallet configuration issue - contact support']}
                    }), 500
            
            # REMOVED: BVN/NIN check for reserved account creation
            # Since we now use internal KYC system, users can create accounts
            # and submit KYC separately. The closed-loop system has minimal risk.
            
            # Get Monnify access token
            access_token = call_monnify_auth()
            
            # Create basic reserved account (will upgrade when KYC verified)
            account_data = {
                'accountReference': user_id,  # STANDARDIZED: Use ObjectId string only
                'accountName': current_user.get('fullName', f"FiCore User {user_id[:8]}")[:50],  # Monnify 50-char limit
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'customerEmail': current_user.get('email', ''),
                'customerName': current_user.get('fullName', f"FiCore User {user_id[:8]}")[:50],  # Monnify 50-char limit
                # BVN/NIN removed - using internal KYC system
                'getAllAvailableBanks': True  # Request all available banks
            }
            
            print(f'DEBUG: Requesting reserved account with getAllAvailableBanks=True for user {user_id}')
            
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
                # Parse Monnify error response
                try:
                    error_data = van_response.json()
                    error_message = error_data.get('responseMessage', 'Unknown error')
                    error_code = error_data.get('responseCode', '99')
                    
                    print(f'ERROR: Monnify error - Code: {error_code}, Message: {error_message}')
                    
                    # Check if error is BVN/NIN requirement (Monnify changed policy Feb 2026)
                    if 'BVN' in error_message.upper() or 'NIN' in error_message.upper():
                        print(f'INFO: Monnify requires KYC for user {user_id} (new policy since Feb 2026)')
                        
                        # Check if user already has BVN/NIN in profile
                        user_bvn = current_user.get('bvn', '').strip()
                        user_nin = current_user.get('nin', '').strip()
                        
                        if user_bvn or user_nin:
                            # User HAS BVN/NIN but we didn't send it - AUTO-RETRY with credentials
                            print(f'INFO: User has BVN/NIN in profile, auto-retrying with credentials...')
                            
                            # Add BVN/NIN to request
                            account_data['bvn'] = user_bvn
                            account_data['nin'] = user_nin
                            
                            # Retry with BVN/NIN
                            van_response_retry = requests.post(
                                f'{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts',
                                headers={
                                    'Authorization': f'Bearer {access_token}',
                                    'Content-Type': 'application/json'
                                },
                                json=account_data,
                                timeout=30
                            )
                            
                            if van_response_retry.status_code == 200:
                                print(f'SUCCESS: Account created with BVN/NIN on auto-retry')
                                van_response = van_response_retry  # Use retry response
                                # Continue to process successful response below
                            else:
                                # Retry also failed
                                retry_error = van_response_retry.json()
                                retry_message = retry_error.get('responseMessage', 'Unknown error')
                                print(f'ERROR: Auto-retry failed: {retry_message}')
                                raise Exception(f'Account creation failed even with BVN/NIN: {retry_message}')
                        else:
                            # User does NOT have BVN/NIN - guide them to KYC
                            print(f'INFO: User has no BVN/NIN in profile - returning KYC requirement')
                            return jsonify({
                                'success': False,
                                'requiresKyc': True,
                                'kycType': 'bvn_or_nin',
                                'message': 'Identity verification required to create wallet',
                                'userMessage': {
                                    'title': 'Verification Required',
                                    'message': 'To create your wallet, we need to verify your identity with your BVN or NIN. This is a one-time requirement to comply with financial regulations.',
                                    'action': 'submit_kyc',
                                    'actionLabel': 'Submit BVN/NIN',
                                    'type': 'info'
                                },
                                'errors': {'kyc': ['BVN or NIN verification required']}
                            }), 400  # 400 = client action required, not server error
                    else:
                        # Other Monnify error (not BVN/NIN related)
                        raise Exception(f'Monnify error: {error_message}')
                        
                except ValueError:
                    # Response is not JSON
                    raise Exception(f'Reserved account creation failed: {van_response.text}')
            
            # If we reach here, van_response.status_code == 200 (success)
            van_data = van_response.json()['responseBody']
            
            # Log what Monnify actually returned
            print(f'DEBUG: Monnify returned {len(van_data.get("accounts", []))} accounts')
            for i, acc in enumerate(van_data.get('accounts', [])):
                print(f'  Account {i+1}: {acc.get("bankName")} ({acc.get("bankCode")}) - {acc.get("accountNumber")}')
            
            # CRITICAL FIX: Validate that Monnify returned accounts
            if not van_data.get('accounts') or len(van_data['accounts']) == 0:
                raise Exception('Monnify returned no accounts in response')
            
            # Check if BVN/NIN was sent in this request (for tracking)
            bvn_sent = bool(account_data.get('bvn', '').strip())
            nin_sent = bool(account_data.get('nin', '').strip())
            
            # Create wallet record with KYC verification and Monnify metadata
            wallet_data = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'balance': 0.0,
                'accountReference': van_data['accountReference'],
                'contractCode': van_data['contractCode'],
                'accounts': van_data['accounts'],
                
                # NEW: Store customer info from Monnify response (for audit trail)
                'customerEmail': van_data.get('customerEmail', account_data.get('customerEmail')),
                'customerName': van_data.get('customerName', account_data.get('customerName')),
                
                # NEW: Store Monnify metadata (from response)
                'reservationReference': van_data.get('reservationReference'),
                'reservedAccountType': van_data.get('reservedAccountType', 'GENERAL'),
                'collectionChannel': van_data.get('collectionChannel', 'RESERVED_ACCOUNT'),
                'monnifyStatus': van_data.get('status', 'ACTIVE'),
                'monnifyCreatedOn': van_data.get('createdOn'),
                
                # NEW: Track BVN/NIN submission (CRITICAL - prevents duplicate submissions)
                'bvnSubmittedToMonnify': bvn_sent,
                'ninSubmittedToMonnify': nin_sent,
                'kycSubmittedAt': datetime.utcnow() if (bvn_sent or nin_sent) else None,
                
                # NEW: Payment restrictions (from Monnify response)
                'restrictPaymentSource': van_data.get('restrictPaymentSource', False),
                'allowedPaymentSources': van_data.get('allowedPaymentSources'),
                
                'status': 'ACTIVE',
                'tier': 'TIER_1',  # Basic account - will upgrade when KYC verified
                'kycTier': 1,  # Will be updated to 2 when internal KYC is verified
                'kycVerified': False,  # Will be updated when internal KYC is verified
                'kycStatus': 'pending',  # Will be updated by internal KYC system
                # BVN/NIN removed - using internal KYC system
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.vas_wallets.insert_one(wallet_data)
            
            if bvn_sent or nin_sent:
                print(f'SUCCESS: Reserved account created for user {user_id} WITH BVN/NIN submission')
            else:
                print(f'SUCCESS: Basic reserved account created for user {user_id} - KYC can be submitted separately')
            
            # Return all accounts for frontend to choose from
            return jsonify({
                'success': True,
                'data': {
                    'accounts': van_data['accounts'],  # All available bank accounts
                    'accountReference': van_data['accountReference'],
                    'contractCode': van_data['contractCode'],
                    'tier': 'TIER_1',  # Will upgrade when KYC verified
                    'kycVerified': False,  # Will be updated when KYC verified
                    'createdAt': wallet_data['createdAt'].isoformat() + 'Z',
                    # Keep backward compatibility - return first account as default
                    'defaultAccount': {
                        'accountNumber': van_data['accounts'][0].get('accountNumber', ''),
                        'accountName': van_data['accounts'][0].get('accountName', ''),
                        'bankName': van_data['accounts'][0].get('bankName', 'Wema Bank'),
                        'bankCode': van_data['accounts'][0].get('bankCode', '035'),
                    }
                },
                'message': f'Reserved account created successfully with {len(van_data["accounts"])} available banks. Submit KYC for full verification.'
            }), 201
            
        except Exception as e:
            print(f'ERROR: Error creating reserved account: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to create reserved account',
                'errors': {'general': [str(e)]}
            }), 500
    
    def _get_reserved_accounts_with_banks_logic(current_user):
        """Business logic for getting user's reserved accounts with available banks"""
        try:
            user_id = str(current_user['_id'])
            
            # Get user's reserved account
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                return {
                    'success': False,
                    'message': 'No wallet found',
                    'data': None
                }, 404
            
            # Get accounts from wallet (correct field name)
            accounts = wallet.get('accounts', [])
            if not accounts:
                return {
                    'success': False,
                    'message': 'No accounts found',
                    'data': None
                }, 404
            
            # Get preferred bank info
            preferred_bank_code = wallet.get('preferredBankCode')
            preferred_bank = None
            
            if preferred_bank_code:
                for account in accounts:
                    if account.get('bankCode') == preferred_bank_code:
                        preferred_bank = account
                        break
            
            # If no preferred bank set, use first account as default
            if not preferred_bank and accounts:
                preferred_bank = accounts[0]
            
            # Return accounts with bank information
            return {
                'success': True,
                'data': {
                    'accounts': accounts,
                    'availableBanks': accounts,  # Same as accounts for compatibility
                    'preferredBank': preferred_bank,
                    'preferredBankCode': wallet.get('preferredBankCode'),
                    'hasMultipleBanks': len(accounts) > 1
                },
                'message': 'Reserved accounts retrieved successfully'
            }, 200
            
        except Exception as e:
            print(f'ERROR: Error getting reserved accounts with banks: {str(e)}')
            return {
                'success': False,
                'message': 'Failed to retrieve reserved accounts',
                'errors': {'general': [str(e)]}
            }, 500

    @vas_wallet_bp.route('/reserved-accounts', methods=['GET'])
    @token_required
    def get_reserved_accounts(current_user):
        """Get user's reserved accounts (alias for backward compatibility)"""
        # Call the business logic function
        result, status_code = _get_reserved_accounts_with_banks_logic(current_user)
        return jsonify(result), status_code
    
    @vas_wallet_bp.route('/reserved-accounts/with-banks', methods=['GET'])
    @token_required
    def get_reserved_accounts_with_banks(current_user):
        """Get user's reserved accounts with available banks (explicit endpoint for frontend compatibility)"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info('═══════════════════════════════════════════════════════')
        logger.info('🔍 GET /api/vas/wallet/reserved-accounts/with-banks')
        logger.info(f'   User ID: {current_user.get("_id")}')
        logger.info(f'   User Email: {current_user.get("email", "N/A")}')
        logger.info(f'   Request Time: {datetime.utcnow().isoformat()}Z')
        logger.info(f'   IP Address: {request.remote_addr}')
        logger.info(f'   User Agent: {request.headers.get("User-Agent", "N/A")}')
        
        # Call the same business logic function as /reserved-accounts
        result, status_code = _get_reserved_accounts_with_banks_logic(current_user)
        
        logger.info(f'📤 Response Status: {status_code}')
        logger.info(f'   Success: {result.get("success")}')
        logger.info(f'   Message: {result.get("message")}')
        if result.get('success') and result.get('data'):
            accounts = result['data'].get('accounts', [])
            logger.info(f'   Accounts Count: {len(accounts)}')
            for i, acc in enumerate(accounts):
                logger.info(f'   Account {i}: {acc.get("bankName")} - {acc.get("accountNumber")}')
        logger.info('═══════════════════════════════════════════════════════')
        
        return jsonify(result), status_code
    
    def _get_reserved_accounts_with_banks_logic(current_user):
        """Business logic for getting user's reserved accounts with available banks"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            user_id = str(current_user['_id'])
            logger.info(f'📝 Step 1: Looking up wallet for user {user_id}...')
            
            wallet = get_wallet_by_user_id(user_id)
            
            if not wallet:
                logger.warning(f'⚠️ No wallet found for user {user_id}')
                logger.info('   User needs to create a wallet first')
                return {
                    'success': False,
                    'message': 'Reserved account not found. Please create a wallet first.'
                }, 404
            
            logger.info(f'✅ Wallet found: {wallet.get("_id")}')
            logger.info(f'   Wallet Status: {wallet.get("status")}')
            logger.info(f'   Wallet Tier: {wallet.get("tier")}')
            logger.info(f'   KYC Verified: {wallet.get("kycVerified")}')
            logger.info(f'   Account Reference: {wallet.get("accountReference")}')
            
            # Get all available accounts
            logger.info(f'📝 Step 2: Extracting accounts from wallet...')
            accounts = wallet.get('accounts', [])
            logger.info(f'   Accounts field type: {type(accounts)}')
            logger.info(f'   Accounts count: {len(accounts) if accounts else 0}')
            
            if not accounts:
                logger.warning(f'⚠️ No accounts found in wallet for user {user_id}')
                logger.info('   Wallet exists but accounts array is empty')
                logger.info(f'   Wallet data keys: {list(wallet.keys())}')
                return {
                    'success': False,
                    'message': 'No accounts found in wallet'
                }, 404
            
            logger.info(f'✅ Found {len(accounts)} accounts')
            for i, acc in enumerate(accounts):
                logger.info(f'   Account {i}:')
                logger.info(f'     - Bank: {acc.get("bankName")} ({acc.get("bankCode")})')
                logger.info(f'     - Account Number: {acc.get("accountNumber")}')
                logger.info(f'     - Account Name: {acc.get("accountName")}')
                logger.info(f'     - Status: {acc.get("status", "N/A")}')
            
            # Return all accounts for frontend to choose from
            logger.info(f'📝 Step 3: Preparing response...')
            response_data = {
                'success': True,
                'data': {
                    'accounts': accounts,  # All available bank accounts
                    'accountReference': wallet.get('accountReference', ''),
                    'status': wallet.get('status', 'active'),
                    'tier': wallet.get('tier', 'TIER_1'),
                    'kycVerified': wallet.get('kycVerified', False),
                    'createdAt': wallet.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                    # Keep backward compatibility - return first account as default
                    'defaultAccount': {
                        'accountNumber': accounts[0].get('accountNumber', ''),
                        'accountName': accounts[0].get('accountName', ''),
                        'bankName': accounts[0].get('bankName', 'Wema Bank'),
                        'bankCode': accounts[0].get('bankCode', '035'),
                    }
                },
                'message': f'Reserved account retrieved successfully with {len(accounts)} available banks'
            }
            
            logger.info(f'✅ Response prepared successfully')
            logger.info(f'   Returning {len(accounts)} accounts to frontend')
            return response_data, 200
            
        except Exception as e:
            logger.error(f'❌ EXCEPTION in _get_reserved_accounts_with_banks_logic')
            logger.error(f'   Error Type: {type(e).__name__}')
            logger.error(f'   Error Message: {str(e)}')
            logger.error(f'   User ID: {current_user.get("_id")}')
            
            import traceback
            logger.error('   Stack Trace:')
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    logger.error(f'     {line}')
            
            return {
                'success': False,
                'message': 'Failed to retrieve reserved accounts',
                'errors': {'general': [str(e)]}
            }, 500

    @vas_wallet_bp.route('/reserved-account', methods=['GET'])
    @token_required
    def get_reserved_account(current_user):
        """Get user's reserved account details with all available banks"""
        try:
            user_id = str(current_user['_id'])
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Reserved account not found. Please create a wallet first.'
                }), 404
            
            # Get all available accounts
            accounts = wallet.get('accounts', [])
            
            if not accounts:
                return jsonify({
                    'success': False,
                    'message': 'No accounts found in wallet'
                }), 404
            
            # Return all accounts for frontend to choose from
            return jsonify({
                'success': True,
                'data': {
                    'accounts': accounts,  # All available bank accounts
                    'accountReference': wallet.get('accountReference', ''),
                    'status': wallet.get('status', 'active'),
                    'tier': wallet.get('tier', 'TIER_1'),
                    'kycVerified': wallet.get('kycVerified', False),
                    'createdAt': wallet.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                    # Keep backward compatibility - return first account as default
                    'defaultAccount': {
                        'accountNumber': accounts[0].get('accountNumber', ''),
                        'accountName': accounts[0].get('accountName', ''),
                        'bankName': accounts[0].get('bankName', 'Wema Bank'),
                        'bankCode': accounts[0].get('bankCode', '035'),
                    }
                },
                'message': f'Reserved account retrieved successfully with {len(accounts)} available banks'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting reserved account: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve reserved account',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_wallet_bp.route('/reserved-account/set-preferred-bank', methods=['POST'])
    @token_required
    def set_preferred_bank(current_user):
        """Set user's preferred bank for their reserved account"""
        try:
            user_id = str(current_user['_id'])
            data = request.get_json()
            
            if not data or 'bankCode' not in data:
                return jsonify({
                    'success': False,
                    'message': 'Bank code is required'
                }), 400
            
            bank_code = data['bankCode']
            
            # Get user's wallet
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found'
                }), 404
            
            # Find the selected bank account
            accounts = wallet.get('accounts', [])
            selected_account = None
            
            for account in accounts:
                if account.get('bankCode') == bank_code:
                    selected_account = account
                    break
            
            if not selected_account:
                return jsonify({
                    'success': False,
                    'message': 'Bank not found in your available accounts'
                }), 404
            
            # Update user's preferred bank
            mongo.db.vas_wallets.update_one(
                {'userId': ObjectId(user_id)},
                {
                    '$set': {
                        'preferredBankCode': bank_code,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            print(f'SUCCESS: User {user_id} set preferred bank to {selected_account.get("bankName")} ({bank_code})')
            
            return jsonify({
                'success': True,
                'data': {
                    'preferredAccount': selected_account,
                    'message': f'Preferred bank set to {selected_account.get("bankName")}'
                },
                'message': 'Preferred bank updated successfully'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error setting preferred bank: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to set preferred bank',
                'errors': {'general': [str(e)]}
            }), 500
    @vas_wallet_bp.route('/reserved-account/add-linked-accounts', methods=['POST'])
    @token_required
    def add_linked_accounts(current_user):
        """Add additional bank accounts to existing reserved account for verified users"""
        try:
            print(f'DEBUG: Function started, current_user: {current_user}')
            
            user_id = str(current_user['_id'])
            print(f'DEBUG: user_id extracted: {user_id}')
            
            data = request.get_json() or {}
            print(f'DEBUG: request data: {data}')
            
            # Support both parameter formats for flexibility
            get_all_available_banks = data.get('getAllAvailableBanks', False)
            preferred_banks = data.get('preferredBanks', data.get('bankCodes', ['50515', '101']))
            
            print(f'DEBUG: Adding linked accounts for user {user_id}')
            print(f'DEBUG: getAllAvailableBanks: {get_all_available_banks}')
            print(f'DEBUG: preferredBanks: {preferred_banks}')
            
            # Get user's wallet
            print(f'DEBUG: Looking up user document...')
            user_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user_doc:
                print(f'DEBUG: User not found for ID: {user_id}')
                return jsonify({'success': False, 'message': 'User not found'}), 404
            
            print(f'DEBUG: User found, looking up wallet...')
            try:
                wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
                print(f'DEBUG: Wallet query completed, result: {wallet is not None}')
                if wallet:
                    print(f'DEBUG: Wallet found with keys: {list(wallet.keys())}')
                else:
                    print(f'DEBUG: No wallet found for user: {user_id}')
            except Exception as wallet_error:
                print(f'DEBUG: Wallet lookup failed with error: {str(wallet_error)}')
                raise wallet_error
                
            if not wallet:
                print(f'DEBUG: No wallet found for user: {user_id}')
                return jsonify({'success': False, 'message': 'No wallet found. Please create one first.'}), 404
            
            print(f'DEBUG: Wallet found, checking account reference...')
            account_reference = wallet.get('accountReference')
            print(f'DEBUG: Account reference: {account_reference}')
            
            if not account_reference:
                print(f'DEBUG: No account reference found')
                return jsonify({'success': False, 'message': 'No existing account reference found.'}), 400
            
            # REMOVED: BVN verification check for adding linked accounts
            # Since we now use internal KYC system, users can add accounts
            # and submit KYC separately. The closed-loop system has minimal risk.
            
            print(f'INFO: User has existing account reference: {account_reference}')
            
            # Check which banks are already present (avoid duplicate requests)
            existing_accounts = wallet.get('accounts', [])
            existing_bank_codes = {acc.get('bankCode') for acc in existing_accounts if acc.get('bankCode')}
            banks_to_add = [code for code in preferred_banks if code not in existing_bank_codes]
            
            if not banks_to_add and not get_all_available_banks:
                print("All requested banks already present")
                return jsonify({
                    'success': True,
                    'data': {
                        'added': [],
                        'alreadyPresent': list(existing_bank_codes),
                        'totalBanks': len(existing_accounts)
                    },
                    'message': 'All requested banks are already linked.'
                }), 200
            
            # Authenticate with Monnify
            monnify_token = call_monnify_auth()
            if not monnify_token:
                return jsonify({
                    'success': False,
                    'message': 'Failed to authenticate with payment provider'
                }), 500
            
            # CRITICAL INSIGHT: Monnify only allows ONE reserved account per customer
            # There is NO API endpoint to add banks to existing accounts
            # The only way to get all banks is to create the account with getAllAvailableBanks=true initially
            # Since Hassan already has a reserved account, we cannot create another one
            
            print(f'INFO: User {user_id} already has a reserved account: {account_reference}')
            print(f'INFO: Monnify only allows one reserved account per customer')
            print(f'INFO: Cannot add additional banks to existing accounts via API')
            
            # Check if user already has multiple bank accounts (created with getAllAvailableBanks=true)
            if len(existing_accounts) > 1:
                print(f'INFO: User already has {len(existing_accounts)} bank accounts available')
                return jsonify({
                    'success': True,
                    'data': {
                        'accounts': existing_accounts,
                        'totalBanksNow': len(existing_accounts),
                        'message': f'You already have access to {len(existing_accounts)} bank accounts from different banks.',
                        'alreadyHasMultipleBanks': True
                    },
                    'message': 'Multiple bank accounts already available'
                }), 200
            
            # For accounts with only one bank (legacy accounts), explain the limitation
            print(f'INFO: User has legacy account with only {len(existing_accounts)} bank(s)')
            
            # Return graceful response explaining the limitation
            return jsonify({
                'success': True,
                'data': {
                    'accounts': existing_accounts,
                    'totalBanksNow': len(existing_accounts),
                    'message': 'Your account was created with a single bank. Monnify only allows one reserved account per customer, so additional banks cannot be added to existing accounts.',
                    'isLegacyAccount': True,
                    'limitation': 'Cannot add banks to existing reserved accounts'
                },
                'message': 'Single bank account - additional banks not supported for existing accounts'
            }), 200
                
        except Exception as e:
            print(f'ERROR: Error adding linked accounts: {str(e)}')
            import traceback
            print(f'ERROR: Full traceback:')
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to add additional bank accounts',
                'error': str(e)
            }), 500
    @vas_wallet_bp.route('/reserved-account/transactions', methods=['GET'])
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
                txn_data['description'] = f"Wallet Funding - ₦ {txn.get('amount', 0):.2f}"
                serialized_transactions.append(txn_data)
            
            return jsonify({
                'success': True,
                'data': serialized_transactions,
                'message': 'Reserved account transactions retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting reserved account transactions: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve reserved account transactions',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_wallet_bp.route('/transactions/all', methods=['GET'])
    @token_required
    def get_all_user_transactions(current_user):
        """
        Get all user transactions (VAS + Income + Expenses) in unified chronological order
        ENHANCED: Ensures proper VAS transaction flags and comprehensive data for frontend sync
        """
        try:
            user_id = str(current_user['_id'])
            limit = int(request.args.get('limit', 50))
            skip = int(request.args.get('skip', 0))
            vas_only = request.args.get('vas_only', 'false').lower() == 'true'
            
            print(f"Loading {'VAS-only' if vas_only else 'all'} transactions for user {user_id} (limit={limit}, skip={skip})")
            
            all_transactions = []
            
            # Get VAS transactions with enhanced data
            vas_transactions = list(
                mongo.db.vas_transactions.find({'userId': ObjectId(user_id)})
                .sort('createdAt', -1)
            )
            
            for txn in vas_transactions:
                created_at = txn.get('createdAt', datetime.utcnow())
                if not isinstance(created_at, datetime):
                    created_at = datetime.utcnow()
                
                txn_type = txn.get('type', 'UNKNOWN')
                subtype = txn.get('subtype', txn_type.lower())
                description = f"{txn_type.replace('_', ' ').title()}"
                
                # Enhanced description generation
                if txn_type == 'WALLET_FUNDING':
                    description = f"Wallet Funding - ₦{txn.get('amount', 0):,.2f}"
                elif txn_type == 'AIRTIME':
                    phone = txn.get('phoneNumber', 'Unknown')
                    network = txn.get('network', '')
                    description = f"Airtime - {network} {phone} - ₦{txn.get('amount', 0):,.2f}"
                elif txn_type == 'DATA':
                    phone = txn.get('phoneNumber', 'Unknown')
                    network = txn.get('network', '')
                    plan = txn.get('dataPlanName') or txn.get('dataPlan', 'Data Plan')
                    description = f"Data - {network} {phone} - {plan}"
                elif txn_type == 'BILLS' or txn_type == 'BILL':
                    bill_provider = txn.get('billProvider', 'Bill')
                    description = f"{bill_provider} Bill Payment - ₦{txn.get('amount', 0):,.2f}"
                elif 'REFUND' in txn_type:
                    description = f"Refund - ₦{txn.get('amount', 0):,.2f}"
                
                # 🎯 CRITICAL FIX: Ensure all VAS transactions have proper flags
                enhanced_transaction = {
                    '_id': str(txn['_id']),
                    'id': str(txn['_id']),  # Alternative ID field for frontend compatibility
                    'type': 'VAS',  # Main type for unified transactions
                    'subtype': subtype,  # Specific VAS type
                    'amount': txn.get('amount', 0),
                    'amountPaid': txn.get('amountPaid', txn.get('amount', 0)),
                    'fee': txn.get('depositFee', txn.get('fee', 0)),
                    'depositFee': txn.get('depositFee', 0),
                    'serviceFee': txn.get('serviceFee', 0),
                    'totalAmount': txn.get('totalAmount', txn.get('amount', 0)),
                    'description': description,
                    'reference': txn.get('reference', txn.get('transactionReference', '')),
                    'transactionReference': txn.get('transactionReference', ''),
                    'status': txn.get('status', 'UNKNOWN'),
                    'provider': txn.get('provider', ''),
                    'createdAt': created_at.isoformat() + 'Z',
                    'completedAt': txn.get('completedAt').isoformat() + 'Z' if txn.get('completedAt') else None,
                    'date': created_at.isoformat() + 'Z',
                    'displayDate': created_at,
                    'category': 'VAS',
                    
                    # 🎯 CRITICAL: Navigation flags for proper routing
                    'isVAS': True,  # Always True for VAS transactions
                    'isIncome': txn_type == 'WALLET_FUNDING' or 'REFUND' in txn_type,  # Wallet funding and refunds are income
                    'isExpense': txn_type in ['AIRTIME', 'DATA', 'BILLS', 'BILL'],  # VAS purchases are expenses
                    'isOptimistic': False,  # Backend transactions are never optimistic
                    
                    # VAS-specific fields
                    'network': txn.get('network', ''),
                    'phoneNumber': txn.get('phoneNumber', ''),
                    'dataPlan': txn.get('dataPlan', ''),
                    'dataPlanId': txn.get('dataPlanId', ''),
                    'dataPlanName': txn.get('dataPlanName', ''),
                    
                    # Bills-specific fields
                    'billCategory': txn.get('billCategory', ''),
                    'billProvider': txn.get('billProvider', ''),
                    'accountNumber': txn.get('accountNumber', ''),
                    'customerName': txn.get('customerName', ''),
                    'packageId': txn.get('packageId', ''),
                    'packageName': txn.get('packageName', ''),
                    
                    # Enhanced metadata for frontend
                    'metadata': {
                        'originalType': txn_type,
                        'subtype': subtype,
                        'phoneNumber': txn.get('phoneNumber', ''),
                        'network': txn.get('network', ''),
                        'planName': txn.get('dataPlanName') or txn.get('dataPlan', ''),
                        'dataPlan': txn.get('dataPlan', ''),
                        'dataPlanName': txn.get('dataPlanName', ''),
                        'dataPlanId': txn.get('dataPlanId', ''),
                        'transactionReference': txn.get('transactionReference', ''),
                        'provider': txn.get('provider', ''),
                        'isVAS': True,
                        'isIncome': txn_type == 'WALLET_FUNDING' or 'REFUND' in txn_type,
                        'isExpense': txn_type in ['AIRTIME', 'DATA', 'BILLS', 'BILL'],
                        
                        # Bills-specific metadata
                        'billCategory': txn.get('billCategory', ''),
                        'billProvider': txn.get('billProvider', ''),
                        'accountNumber': txn.get('accountNumber', ''),
                        'customerName': txn.get('customerName', ''),
                        'packageId': txn.get('packageId', ''),
                        'packageName': txn.get('packageName', ''),
                    }
                }
                
                all_transactions.append(enhanced_transaction)
            
            # If VAS-only requested, skip income/expense transactions
            if not vas_only:
                # CRITICAL FIX (Feb 8, 2026): Use get_active_transactions_query for consistency
                from utils.immutable_ledger_helper import get_active_transactions_query
                
                # Get Income transactions with active filter
                income_query = get_active_transactions_query(ObjectId(user_id))
                income_transactions = list(
                    mongo.db.incomes.find(income_query)
                    .sort('dateReceived', -1)
                )
                
                for txn in income_transactions:
                    date_received = txn.get('dateReceived', datetime.utcnow())
                    if not isinstance(date_received, datetime):
                        date_received = datetime.utcnow()
                    
                    all_transactions.append({
                        '_id': str(txn['_id']),
                        'id': str(txn['_id']),
                        'type': 'INCOME',
                        'subtype': 'INCOME',
                        'amount': txn.get('amount', 0),
                        'description': txn.get('description', 'Income received'),
                        'title': txn.get('source', 'Income'),
                        'source': txn.get('source', 'Unknown'),
                        'reference': '',
                        'status': 'SUCCESS',
                        'createdAt': date_received.isoformat() + 'Z',
                        'date': date_received.isoformat() + 'Z',
                        'displayDate': date_received,
                        'category': txn.get('category', 'Income'),
                        'isVAS': False,
                        'isIncome': True,
                        'isExpense': False,
                        'isOptimistic': False,
                    })
                
                # Get Expense transactions with active filter
                expense_query = get_active_transactions_query(ObjectId(user_id))
                expense_transactions = list(
                    mongo.db.expenses.find(expense_query)
                    .sort('date', -1)
                )
                
                for txn in expense_transactions:
                    expense_date = txn.get('date', datetime.utcnow())
                    if not isinstance(expense_date, datetime):
                        expense_date = datetime.utcnow()
                    
                    all_transactions.append({
                        '_id': str(txn['_id']),
                        'id': str(txn['_id']),
                        'type': 'EXPENSE',
                        'subtype': 'EXPENSE',
                        'amount': -txn.get('amount', 0),  # Negative for expenses
                        'description': txn.get('description', 'Expense recorded'),
                        'title': txn.get('title', 'Expense'),
                        'reference': '',
                        'status': 'SUCCESS',
                        'createdAt': expense_date.isoformat() + 'Z',
                        'date': expense_date.isoformat() + 'Z',
                        'displayDate': expense_date,
                        'category': txn.get('category', 'Expense'),
                        'isVAS': False,
                        'isIncome': False,
                        'isExpense': True,
                        'isOptimistic': False,
                    })
            
            # Sort all transactions by date (newest first)
            all_transactions.sort(key=lambda x: x['createdAt'], reverse=True)
            
            # Apply pagination
            paginated_transactions = all_transactions[skip:skip + limit]
            
            print(f"✅ Loaded {len(paginated_transactions)} transactions (total: {len(all_transactions)}, VAS: {len(vas_transactions)})")
            
            return jsonify({
                'success': True,
                'data': paginated_transactions,
                'total': len(all_transactions),
                'vas_count': len(vas_transactions),
                'limit': limit,
                'skip': skip,
                'vas_only': vas_only,
                'message': f'{"VAS-only" if vas_only else "All"} transactions loaded successfully'
            }), 200
            
        except Exception as e:
            print(f"ERROR: /vas/wallet/transactions/all failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to load transactions',
                'error': str(e)
            }), 500

    @vas_wallet_bp.route('/transactions/sync', methods=['POST'])
    @token_required
    def sync_vas_transactions(current_user):
        """
        🎯 CRITICAL: VAS Transaction Sync Endpoint
        Ensures VAS transactions are properly synced between frontend and backend
        This fixes the "VAS transactions disappear after app reinstall" issue
        """
        try:
            user_id = str(current_user['_id'])
            data = request.json or {}
            
            # Get client's last sync timestamp
            last_sync = data.get('lastSync')
            client_transaction_ids = set(data.get('transactionIds', []))
            
            print(f"🔄 VAS Sync requested for user {user_id}")
            print(f"   Client last sync: {last_sync}")
            print(f"   Client has {len(client_transaction_ids)} transaction IDs")
            
            # Get all VAS transactions from backend
            query = {'userId': ObjectId(user_id)}
            if last_sync:
                try:
                    last_sync_dt = datetime.fromisoformat(last_sync.replace('Z', ''))
                    query['updatedAt'] = {'$gte': last_sync_dt}
                    print(f"   Filtering transactions updated after: {last_sync_dt}")
                except:
                    print(f"   Invalid lastSync format, fetching all transactions")
            
            backend_transactions = list(
                mongo.db.vas_transactions.find(query)
                .sort('createdAt', -1)
            )
            
            # Enhance transactions with proper flags
            enhanced_transactions = []
            backend_transaction_ids = set()
            
            for txn in backend_transactions:
                backend_transaction_ids.add(str(txn['_id']))
                
                created_at = txn.get('createdAt', datetime.utcnow())
                if not isinstance(created_at, datetime):
                    created_at = datetime.utcnow()
                
                txn_type = txn.get('type', 'UNKNOWN')
                subtype = txn.get('subtype', txn_type.lower())
                
                # 🎯 CRITICAL: Ensure all VAS transactions have proper flags
                enhanced_txn = {
                    'id': str(txn['_id']),
                    'type': txn_type,
                    'subtype': subtype,
                    'amount': txn.get('amount', 0),
                    'amountPaid': txn.get('amountPaid', txn.get('amount', 0)),
                    'fee': txn.get('depositFee', txn.get('fee', 0)),
                    'depositFee': txn.get('depositFee', 0),
                    'serviceFee': txn.get('serviceFee', 0),
                    'totalAmount': txn.get('totalAmount', txn.get('amount', 0)),
                    'status': txn.get('status', 'UNKNOWN'),
                    'provider': txn.get('provider', ''),
                    'description': txn.get('description', ''),
                    'reference': txn.get('reference', txn.get('transactionReference', '')),
                    'transactionReference': txn.get('transactionReference', ''),
                    'createdAt': created_at,
                    'completedAt': txn.get('completedAt'),
                    'expiresAt': txn.get('expiresAt'),
                    
                    # 🎯 CRITICAL: Navigation flags for proper routing
                    'isVAS': True,  # Always True for VAS transactions
                    'isIncome': txn_type == 'WALLET_FUNDING' or 'REFUND' in txn_type,
                    'isExpense': txn_type in ['AIRTIME', 'DATA', 'BILLS', 'BILL'],
                    'isOptimistic': False,  # Backend transactions are never optimistic
                    
                    # VAS-specific fields
                    'network': txn.get('network', ''),
                    'phoneNumber': txn.get('phoneNumber', ''),
                    'dataPlan': txn.get('dataPlan', ''),
                    'dataPlanId': txn.get('dataPlanId', ''),
                    'dataPlanName': txn.get('dataPlanName', ''),
                    
                    # Bills-specific fields
                    'billCategory': txn.get('billCategory', ''),
                    'billProvider': txn.get('billProvider', ''),
                    'accountNumber': txn.get('accountNumber', ''),
                    'customerName': txn.get('customerName', ''),
                    'packageId': txn.get('packageId', ''),
                    'packageName': txn.get('packageName', ''),
                }
                
                enhanced_transactions.append(enhanced_txn)
            
            # Identify missing transactions (on backend but not on client)
            missing_on_client = backend_transaction_ids - client_transaction_ids
            
            # Identify extra transactions (on client but not on backend)
            extra_on_client = client_transaction_ids - backend_transaction_ids
            
            sync_summary = {
                'backend_count': len(backend_transactions),
                'client_count': len(client_transaction_ids),
                'missing_on_client': len(missing_on_client),
                'extra_on_client': len(extra_on_client),
                'sync_timestamp': datetime.utcnow().isoformat() + 'Z'
            }
            
            print(f"✅ VAS Sync completed for user {user_id}:")
            print(f"   Backend: {sync_summary['backend_count']} transactions")
            print(f"   Client: {sync_summary['client_count']} transactions")
            print(f"   Missing on client: {sync_summary['missing_on_client']}")
            print(f"   Extra on client: {sync_summary['extra_on_client']}")
            
            return jsonify({
                'success': True,
                'data': {
                    'transactions': enhanced_transactions,
                    'summary': sync_summary,
                    'missing_transaction_ids': list(missing_on_client),
                    'extra_transaction_ids': list(extra_on_client),
                },
                'message': 'VAS transactions synced successfully'
            }), 200
            
        except Exception as e:
            print(f"ERROR: VAS sync failed for user {user_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to sync VAS transactions',
                'error': str(e)
            }), 500

    # ==================== WEBHOOK ENDPOINT ====================
    
    @vas_wallet_bp.route('/webhook', methods=['POST'])
    def monnify_webhook():
        """Handle Monnify webhook with HMAC-SHA512 signature verification"""
        
        def process_reserved_account_funding_inline(user_id, amount_paid, transaction_reference, webhook_data):
            """Process reserved account funding inline with idempotent logic"""
            try:
                # CRITICAL: Check if this transaction was already processed (idempotency)
                already_processed = mongo.db.vas_transactions.find_one({"reference": transaction_reference})
                if already_processed:
                    print(f"WARNING: Duplicate transaction ignored: {transaction_reference}")
                    return jsonify({'success': True, 'message': 'Already processed'}), 200
                
                wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
                if not wallet:
                    print(f'ERROR: Wallet not found for user: {user_id}')
                    return jsonify({'success': False, 'message': 'Wallet not found'}), 404
                
                # Check if user is premium (no deposit fee)
                user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                is_premium = False
                if user:
                    # CRITICAL FIX: Check multiple premium indicators
                    # 1. Check subscriptionStatus (standard subscription)
                    subscription_status = user.get('subscriptionStatus')
                    if subscription_status == 'active':
                        is_premium = True
                    
                    # 2. Check subscription dates (admin granted or standard)
                    elif user.get('subscriptionStartDate') and user.get('subscriptionEndDate'):
                        subscription_end = user.get('subscriptionEndDate')
                        now = datetime.utcnow()
                        if subscription_end > now:
                            is_premium = True
                            print(f'SUCCESS: User {user_id} is premium via subscription dates (ends: {subscription_end})')
                    
                    # 3. Check if user is admin
                    elif user.get('isAdmin', False):
                        is_premium = True
                        print(f'SUCCESS: User {user_id} is premium via admin status')
                
                print(f'INFO: Premium check for user {user_id}: {is_premium}')
                
                # Apply deposit fee (₦ 30 for non-premium users)
                deposit_fee = 0.0 if is_premium else VAS_TRANSACTION_FEE
                amount_to_credit = amount_paid - deposit_fee
                
                # 💰 CALCULATE GATEWAY FEE (Phase 2 - Unit Economics)
                # Monnify charges 1.6% on all deposits
                gateway_fee = amount_paid * 0.016  # 1.6%
                gateway_provider = 'monnify'
                
                # Calculate net deposit revenue (only for non-premium users)
                net_deposit_revenue = deposit_fee - gateway_fee if not is_premium else -gateway_fee
                
                # Ensure we don't credit negative amounts
                if amount_to_credit <= 0:
                    print(f'WARNING: Amount too small after fee: ₦ {amount_paid} - ₦ {deposit_fee} = ₦ {amount_to_credit}')
                    return jsonify({'success': False, 'message': 'Amount too small to process'}), 400
                
                # SAFETY FIRST: Insert transaction record BEFORE updating wallet balance
                transaction = {
                    '_id': ObjectId(),
                    'userId': ObjectId(user_id),
                    'type': 'WALLET_FUNDING',
                    'amount': amount_to_credit,
                    'amountPaid': amount_paid,
                    'depositFee': deposit_fee,
                    'reference': transaction_reference,
                    'transactionReference': transaction_reference,  # CRITICAL: Add this field for unique index
                    'status': 'SUCCESS',
                    'provider': 'monnify',
                    # 💰 UNIT ECONOMICS TRACKING (Phase 2)
                    'gatewayFee': round(gateway_fee, 2),
                    'gatewayProvider': gateway_provider,
                    'netDepositRevenue': round(net_deposit_revenue, 2),
                    'isPremiumUser': is_premium,
                    'metadata': webhook_data,
                    'createdAt': datetime.utcnow()
                }
                
                # Try to insert transaction - if duplicate key error, return success (already processed)
                try:
                    mongo.db.vas_transactions.insert_one(transaction)
                except pymongo.errors.DuplicateKeyError:
                    print(f"WARNING: Duplicate key error - transaction already exists: {transaction_reference}")
                    return jsonify({'success': True, 'message': 'Already processed'}), 200
                
                # CRITICAL FIX: Update BOTH balances using centralized utility
                new_balance = wallet.get('balance', 0.0) + amount_to_credit
                
                from utils.balance_sync import update_liquid_wallet_balance
                
                # Use centralized balance update utility
                success = update_liquid_wallet_balance(
                    mongo=mongo,
                    user_id=user_id,
                    new_balance=new_balance,
                    transaction_reference=transaction_reference,
                    transaction_type='WALLET_FUNDING',
                    push_sse_update=True,
                    sse_data={
                        'previous_balance': wallet.get('balance', 0.0),
                        'amount_credited': amount_to_credit,
                        'amount_paid': amount_paid,
                        'deposit_fee': deposit_fee,
                        'is_premium': is_premium
                    }
                )
                
                if not success:
                    print(f'WARNING: Balance update may have failed for user {user_id}')
                else:
                    print(f'SUCCESS: Updated BOTH balances using utility - New balance: ₦{new_balance:,.2f}')
                
                # ==================== REFERRAL SYSTEM: FIRST DEPOSIT BONUS (NEW - Feb 4, 2026) ====================
                # Check if this is user's first deposit and they were referred
                user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                is_first_deposit = not user.get('firstDepositCompleted', False)
                
                if is_first_deposit:
                    print(f'🎉 FIRST DEPOSIT detected for user {user_id}')
                    
                    # Update user's first deposit status
                    mongo.db.users.update_one(
                        {'_id': ObjectId(user_id)},
                        {
                            '$set': {
                                'firstDepositCompleted': True,
                                'firstDepositDate': datetime.utcnow()
                            }
                        }
                    )
                    
                    # Check if they were referred
                    referral = mongo.db.referrals.find_one({'refereeId': ObjectId(user_id)})
                    
                    if referral and not referral.get('refereeDepositBonusGranted', False):
                        print(f'🎁 REFERRAL BONUS: User {user_id} was referred by {referral["referrerId"]}')
                        
                        # BONUS 1: Waive the ₦30 deposit fee (credit it back)
                        if deposit_fee > 0:
                            from utils.balance_sync import update_liquid_wallet_balance, get_liquid_wallet_balance
                            
                            # Get current balance and add deposit fee
                            current_balance = get_liquid_wallet_balance(mongo, user_id)
                            new_balance = current_balance + deposit_fee
                            
                            # Use centralized balance update utility
                            update_liquid_wallet_balance(
                                mongo=mongo,
                                user_id=user_id,
                                new_balance=new_balance,
                                reason="Deposit fee refund (first-time funding bonus)"
                            )
                            print(f'✅ Credited back ₦{deposit_fee} deposit fee')
                        
                        # BONUS 2: Grant 5 FiCore Credits
                        current_fc_balance = user.get('ficoreCreditBalance', 0.0)
                        mongo.db.users.update_one(
                            {'_id': ObjectId(user_id)},
                            {'$inc': {'ficoreCreditBalance': 5.0}}
                        )
                        
                        # Log the bonus in credit_transactions
                        credit_transaction = {
                            '_id': ObjectId(),
                            'userId': ObjectId(user_id),
                            'type': 'credit',
                            'amount': 5.0,
                            'description': 'Referral signup bonus - Welcome to FiCore!',
                            'status': 'completed',
                            'operation': 'referral_bonus',
                            'balanceBefore': current_fc_balance,
                            'balanceAfter': current_fc_balance + 5.0,
                            'createdAt': datetime.utcnow(),
                            'metadata': {
                                'referrerId': str(referral['referrerId']),
                                'referralCode': referral.get('referralCode'),
                                'isReferralBonus': True
                            }
                        }
                        mongo.db.credit_transactions.insert_one(credit_transaction)
                        print(f'✅ Granted 5 FiCore Credits')
                        
                        # Update referral record
                        mongo.db.referrals.update_one(
                            {'_id': referral['_id']},
                            {
                                '$set': {
                                    'status': 'active',
                                    'firstDepositDate': datetime.utcnow(),
                                    'refereeDepositBonusGranted': True,
                                    'referrerVasShareActive': True,
                                    'vasShareExpiryDate': datetime.utcnow() + timedelta(days=90),
                                    'updatedAt': datetime.utcnow()
                                }
                            }
                        )
                        print(f'✅ Updated referral status to ACTIVE with 90-day VAS share')
                        
                        # Update referrer's stats
                        mongo.db.users.update_one(
                            {'_id': referral['referrerId']},
                            {'$inc': {'referralCount': 1}}
                        )
                        print(f'✅ Incremented referrer\'s referral count')
                        
                        print(f'🎉 REFERRAL BONUS COMPLETE: User {user_id} received ₦{deposit_fee} + 5 FCs')
                
                # ==================== END REFERRAL SYSTEM ====================
                
                # Record corporate revenue (₦ 30 fee) with gateway cost tracking
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
                        # 💰 UNIT ECONOMICS TRACKING (Phase 2)
                        'gatewayFee': round(gateway_fee, 2),
                        'gatewayProvider': gateway_provider,
                        'netRevenue': round(net_deposit_revenue, 2),
                        'metadata': {
                            'amountPaid': amount_paid,
                            'amountCredited': amount_to_credit,
                            'isPremium': is_premium,
                            'gatewayFeePercentage': 1.6
                        }
                    }
                    mongo.db.corporate_revenue.insert_one(corporate_revenue)
                    print(f'💰 Corporate revenue recorded: ₦{deposit_fee} deposit fee (net: ₦{net_deposit_revenue:.2f} after gateway) - User {user_id}')
                elif is_premium:
                    # Track gateway cost for premium users (no deposit fee revenue)
                    print(f'💸 Gateway cost for premium user: ₦{gateway_fee:.2f} (no deposit fee collected) - User {user_id}')
                
                # Send notification
                try:
                    notification_id = create_user_notification(
                        mongo=mongo,
                        user_id=user_id,
                        category='wallet',
                        title='💰 Wallet Funded Successfully',
                        body=f'₦ {amount_to_credit:,.2f} added to your Liquid Wallet. New balance: ₦ {new_balance:,.2f}',
                        related_id=transaction_reference,
                        metadata={
                            'transaction_type': 'WALLET_FUNDING',
                            'amount_credited': amount_to_credit,
                            'deposit_fee': deposit_fee,
                            'new_balance': new_balance,
                            'is_premium': is_premium
                        },
                        priority='normal'
                    )
                    
                    if notification_id:
                        print(f'INFO: Wallet funding notification created: {notification_id}')
                except Exception as e:
                    print(f'WARNING: Failed to create notification: {str(e)}')
                
                print(f'SUCCESS: Wallet Funding: User {user_id}, Paid: ₦ {amount_paid}, Fee: ₦ {deposit_fee}, Credited: ₦ {amount_to_credit}, New Balance: ₦ {new_balance}')
                return jsonify({'success': True, 'message': 'Wallet funded successfully'}), 200
                
            except Exception as e:
                print(f'ERROR: Error processing wallet funding: {str(e)}')
                return jsonify({'success': False, 'message': 'Processing failed'}), 500
        try:
            # Optional: IP Whitelisting (uncomment for production)
            # Monnify webhook IP: 35.242.133.146
            # client_ip = request.headers.get('X-Real-IP', request.remote_addr)
            # MONNIFY_WEBHOOK_IP = '35.242.133.146'
            # if client_ip != MONNIFY_WEBHOOK_IP:
            #     print(f'WARNING: Unauthorized webhook IP: {client_ip}')
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
                print(f'WARNING: Invalid webhook signature. Expected: {computed_signature}, Got: {signature}')
                return jsonify({'success': False, 'message': 'Invalid signature'}), 401
            
            data = request.json
            
            # Log the raw webhook data for debugging
            print(f'INFO: Raw Monnify webhook data: {json.dumps(data, indent=2)}')
            
            # Handle both old eventType format and new flat format
            event_type = data.get('eventType')
            payment_status = data.get('paymentStatus', '').upper()
            completed = data.get('completed', False)
            
            print(f'INFO: Monnify webhook - EventType: {event_type}, Status: {payment_status}, Completed: {completed}')
            
            # Handle ACCOUNT_ACTIVITY events (balance notifications)
            if event_type == 'ACCOUNT_ACTIVITY':
                activity_data = data.get('eventData', {})
                activity_type = activity_data.get('activityType', '')
                amount = activity_data.get('amount', 0)
                narration = activity_data.get('narration', '')
                
                print(f'INFO: Account activity - Type: {activity_type}, Amount: ₦{amount}, Narration: {narration}')
                
                # These are just balance notifications, not payment confirmations
                if 'COMMISSION' in narration.upper():
                    print(f'INFO: Commission notification received: ₦{amount}')
                elif 'SUCCESSFUL PAYMENT' in narration.upper() or 'PAYMENT' in narration.upper():
                    print(f'INFO: Payment notification received: ₦{amount}')
                else:
                    print(f'INFO: General account activity: {narration}')
                
                return jsonify({'success': True, 'message': 'Account activity acknowledged'}), 200
            
            # Process if it's a successful transaction (either format)
            should_process = (
                (event_type == 'SUCCESSFUL_TRANSACTION') or 
                (payment_status == 'PAID' and completed)
            )
            
            if should_process:
                # Extract transaction reference for VAS detection
                transaction_reference = ''
                if 'eventData' in data:
                    transaction_reference = data['eventData'].get('transactionReference', '')
                else:
                    transaction_reference = data.get('transactionReference', '')
                
                print(f"INFO: Checking if webhook is for VAS transaction: {transaction_reference}")
                
                # Check if this webhook is for an existing VAS transaction (airtime/data)
                existing_vas_txn = mongo.db.vas_transactions.find_one({
                    '$or': [
                        {'requestId': transaction_reference},
                        {'transactionReference': transaction_reference}
                    ],
                    'type': {'$in': ['AIRTIME', 'DATA']}
                })
                
                if existing_vas_txn:
                    # This is a VAS confirmation - update existing transaction, don't create new one
                    print(f'INFO: VAS confirmation webhook detected for: {transaction_reference}')
                    print(f'   Transaction ID: {existing_vas_txn["_id"]}')
                    print(f'   Type: {existing_vas_txn.get("type")}')
                    print(f'   Current Status: {existing_vas_txn.get("status")}')
                    
                    # Update existing transaction with webhook confirmation
                    update_data = {
                        'providerConfirmed': True,
                        'webhookReceived': datetime.utcnow(),
                        'webhookData': data,
                        'updatedAt': datetime.utcnow()
                    }
                    
                    # If transaction is still PENDING, update to SUCCESS
                    if existing_vas_txn.get('status') == 'PENDING':
                        update_data['status'] = 'SUCCESS'
                        print(f'SUCCESS: Updated PENDING VAS transaction to SUCCESS: {transaction_reference}')
                    
                    mongo.db.vas_transactions.update_one(
                        {'_id': existing_vas_txn['_id']},
                        {'$set': update_data}
                    )
                    
                    print(f'SUCCESS: VAS confirmation processed - no duplicate transaction created')
                    return jsonify({'success': True, 'message': 'VAS confirmation processed'}), 200
                
                # If we reach here, it's not a VAS confirmation - proceed with wallet funding logic
                print(f'INFO: Processing as wallet funding (not VAS confirmation)')
                
                # IMPROVED EXTRACTION - handles real Monnify reserved account format
                # Default values
                account_ref = None
                amount_paid = 0.0
                transaction_reference = ''
                payment_reference = ''
                customer_email = ''
                
                print(f"DEBUG full payload top-level keys: {list(data.keys())}")
                
                # 1. Classic Monnify format (most common for reserved accounts)
                if 'eventData' in data:
                    event_data = data['eventData']
                    print(f"DEBUG eventData keys: {list(event_data.keys())}")
                    
                    amount_paid = float(event_data.get('amountPaid', 0))
                    transaction_reference = event_data.get('transactionReference', '')
                    payment_reference = event_data.get('paymentReference', '')
                    
                    # Customer email (fallback)
                    customer = event_data.get('customer', {})
                    customer_email = customer.get('email', '')
                    
                    # Critical: account reference is usually here
                    product = event_data.get('product', {})
                    if product.get('type') == 'RESERVED_ACCOUNT':
                        account_ref = product.get('reference', '')
                        print(f"DEBUG: Found reserved account reference! eventData.product.reference = '{account_ref}'")
                
                # 2. Possible flat/newer format (less common, but we check anyway)
                if not account_ref:
                    account_ref = data.get('accountReference', '')
                    if account_ref:
                        print(f"DEBUG: Found top-level accountReference = '{account_ref}'")
                        amount_paid = float(data.get('amountPaid', amount_paid))
                        transaction_reference = data.get('transactionReference', transaction_reference)
                        payment_reference = data.get('paymentReference', payment_reference)
                        customer_email = data.get('customerEmail', customer_email) or data.get('customer', {}).get('email', '')
                
                # 3. Log what we actually got
                print(f"DEBUG extracted values:")
                print(f"  - amount_paid          : ₦ {amount_paid}")
                print(f"  - transaction_reference: {transaction_reference}")
                print(f"  - payment_reference    : {payment_reference}")
                print(f"  - account_ref          : '{account_ref}'")
                print(f"  - customer_email       : {customer_email}")
                
                if amount_paid <= 0:
                    print("WARNING: Zero or negative amount - ignoring")
                    return jsonify({'success': True, 'message': 'Zero amount ignored'}), 200
                
                # Now try to identify user and process
                user_id = None
                pending_txn = None
                
                # Priority 1: From account reference (preferred for reserved accounts)
                if account_ref:
                    cleaned = account_ref.replace(" ", "").replace("-", "").replace("_", "").upper()
                    if cleaned.startswith('FICORE'):
                        user_part = cleaned[len('FICORE'):]
                        user_id = user_part.lstrip('0123456789') if user_part.isdigit() else user_part
                        print(f"SUCCESS: Matched FICORE prefix! extracted user_id: {user_id}")
                
                # Priority 2: Fallback to email if we have it and no user yet
                if not user_id and customer_email:
                    user_doc = mongo.db.users.find_one({'email': customer_email})
                    if user_doc:
                        user_id = str(user_doc['_id'])
                        print(f"SUCCESS: Fallback: found user via email {customer_email}! {user_id}")
                
                # Priority 3: Try pending transaction matching (KYC payments only)
                if not user_id:
                    # Only check for KYC verification payments (₦ 70)
                    if amount_paid >= 70.0:
                        pending_txn = mongo.db.vas_transactions.find_one({
                            'monnifyTransactionReference': transaction_reference,
                            'status': 'PENDING_PAYMENT',
                            'type': 'KYC_VERIFICATION'
                        })
                        
                        if not pending_txn and payment_reference and payment_reference.startswith('VER_'):
                            pending_txn = mongo.db.vas_transactions.find_one({
                                'paymentReference': payment_reference,
                                'status': 'PENDING_PAYMENT',
                                'type': 'KYC_VERIFICATION'
                            })
                        
                        if not pending_txn and transaction_reference.startswith('FICORE_QP_'):
                            pending_txn = mongo.db.vas_transactions.find_one({
                                'transactionReference': transaction_reference,
                                'status': 'PENDING_PAYMENT',
                                'type': 'KYC_VERIFICATION'
                            })
                        
                        if pending_txn:
                            user_id = str(pending_txn['userId'])
                            print(f"SUCCESS: Found pending KYC verification transaction! user_id: {user_id}")
                
                # Decide how to process based on what we found
                if user_id:
                    # We have a user! treat as wallet funding (reserved account style)
                    print(f"Processing as direct reserved account funding for user {user_id}")
                    
                    # Comprehensive idempotency check - any status
                    existing = mongo.db.vas_transactions.find_one({
                        'reference': transaction_reference
                    })
                    
                    if existing:
                        if existing.get('status') == 'SUCCESS':
                            print(f"Duplicate SUCCESS webhook ignored: {transaction_reference}")
                            return jsonify({'success': True, 'message': 'Already processed'}), 200
                        else:
                            print(f"Found existing transaction with status {existing.get('status')}: {transaction_reference}")
                            print("Updating existing transaction to SUCCESS and crediting wallet...")
                            
                            # Update existing transaction to SUCCESS
                            mongo.db.vas_transactions.update_one(
                                {'_id': existing['_id']},
                                {'$set': {
                                    'status': 'SUCCESS',
                                    'amountPaid': amount_paid,
                                    'provider': 'monnify',
                                    'metadata': data,
                                    'completedAt': datetime.utcnow()
                                }}
                            )
                            
                            # Now credit the wallet (call the inline function but skip the insert part)
                            return process_reserved_account_funding_inline(user_id, amount_paid, transaction_reference, data)
                    
                    return process_reserved_account_funding_inline(user_id, amount_paid, transaction_reference, data)
                
                elif pending_txn:
                    # KYC verification transaction
                    txn_type = pending_txn.get('type')
                    print(f"Found pending transaction type: {txn_type}")
                    
                    if txn_type == 'KYC_VERIFICATION':
                        # Process KYC verification payment
                        if amount_paid < 70.0:
                            print(f'WARNING: KYC verification payment insufficient: ₦ {amount_paid} < ₦ 70')
                            return jsonify({'success': False, 'message': 'Insufficient payment amount'}), 400
                        
                        # Update transaction status
                        mongo.db.vas_transactions.update_one(
                            {'_id': pending_txn['_id']},
                            {'$set': {
                                'status': 'SUCCESS',
                                'amountPaid': amount_paid,
                                'reference': transaction_reference,
                                'provider': 'monnify',
                                'metadata': data,
                                'completedAt': datetime.utcnow()
                            }}
                        )
                        
                        # Record corporate revenue (₦ 70 KYC fee)
                        corporate_revenue = {
                            '_id': ObjectId(),
                            'type': 'SERVICE_FEE',
                            'category': 'KYC_VERIFICATION',
                            'amount': 70.0,
                            'userId': ObjectId(user_id),
                            'relatedTransaction': transaction_reference,
                            'description': f'KYC verification fee from user {user_id}',
                            'status': 'RECORDED',
                            'createdAt': datetime.utcnow(),
                            'metadata': {
                                'amountPaid': amount_paid,
                                'verificationFee': 70.0
                            }
                        }
                        mongo.db.corporate_revenue.insert_one(corporate_revenue)
                        print(f'INFO: KYC verification revenue recorded: ₦ 70 from user {user_id}')
                        
                        print(f'SUCCESS: KYC Verification Payment: User {user_id}, Paid: ₦ {amount_paid}, Fee: ₦ 70')
                        return jsonify({'success': True, 'message': 'KYC verification payment processed successfully'}), 200
                    
                    elif txn_type == 'WALLET_FUNDING':
                        return process_reserved_account_funding_inline(str(pending_txn['userId']), amount_paid, transaction_reference, data)
                    
                    else:
                        print(f"Unhandled pending txn type: {txn_type}")
                        return jsonify({'success': False, 'message': 'Unhandled transaction type'}), 400
                
                else:
                    print("Could not identify user or pending transaction")
                    # Still return 200 to Monnify - don't block their retries
                    return jsonify({'success': True, 'message': 'Acknowledged but unprocessed'}), 200
            
            # If payment status is not PAID or not completed, just acknowledge
            else:
                print(f'INFO: Webhook received but not processed - Status: {payment_status}, Completed: {completed}')
                return jsonify({'success': True, 'message': 'Webhook received'}), 200
            
        except Exception as e:
            print(f'ERROR: Error processing webhook: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Webhook processing failed',
                'errors': {'general': [str(e)]}
            }), 500
    
    # ==================== PIN MANAGEMENT ENDPOINTS ====================
    
    @vas_wallet_bp.route('/pin/setup', methods=['POST'])
    @token_required
    def setup_vas_pin(current_user):
        """Set up VAS transaction PIN - stores both locally and on server"""
        try:
            user_id = str(current_user['_id'])
            data = request.get_json()
            
            pin = data.get('pin', '').strip()
            
            # Validate PIN format
            if not pin or len(pin) != 4 or not pin.isdigit():
                return jsonify({
                    'success': False,
                    'message': 'PIN must be exactly 4 digits',
                    'errors': {'pin': ['PIN must be exactly 4 digits']}
                }), 400
            
            # Check for weak PINs
            weak_pins = ['0000', '1111', '2222', '3333', '4444', '5555', '6666', '7777', '8888', '9999', '1234', '4321', '0123', '9876']
            if pin in weak_pins:
                return jsonify({
                    'success': False,
                    'message': 'Please choose a stronger PIN',
                    'errors': {'pin': ['This PIN is too common. Please choose a different one.']}
                }), 400
            
            # Get or create wallet
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found. Please create a wallet first.'
                }), 404
            
            # Check if PIN already exists
            if wallet.get('vasPinHash'):
                return jsonify({
                    'success': False,
                    'message': 'PIN already exists. Use change PIN instead.'
                }), 400
            
            # Generate salt and hash PIN (same algorithm as frontend)
            import secrets
            import hashlib
            import base64
            
            salt = base64.b64encode(secrets.token_bytes(32)).decode('utf-8')
            pin_hash = hashlib.sha256((pin + salt).encode()).hexdigest()
            
            # Update wallet with PIN data
            mongo.db.vas_wallets.update_one(
                {'userId': ObjectId(user_id)},
                {
                    '$set': {
                        'vasPinHash': pin_hash,
                        'vasPinSalt': salt,
                        'pinSetupAt': datetime.utcnow(),
                        'pinAttempts': 0,
                        'pinLockedUntil': None,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            print(f'SUCCESS: VAS PIN setup completed for user {user_id}')
            
            return jsonify({
                'success': True,
                'message': 'PIN setup completed successfully',
                'data': {
                    'pinSetup': True,
                    'setupAt': datetime.utcnow().isoformat() + 'Z'
                }
            }), 201
            
        except Exception as e:
            print(f'ERROR: Error setting up VAS PIN: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to setup PIN',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_wallet_bp.route('/pin/validate', methods=['POST'])
    @token_required
    def validate_vas_pin(current_user):
        """Validate VAS transaction PIN"""
        try:
            user_id = str(current_user['_id'])
            data = request.get_json()
            
            pin = data.get('pin', '').strip()
            
            if not pin:
                return jsonify({
                    'success': False,
                    'message': 'PIN is required',
                    'errors': {'pin': ['PIN is required']}
                }), 400
            
            # Get wallet with PIN data
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found'
                }), 404
            
            # Check if PIN is set up
            stored_hash = wallet.get('vasPinHash')
            stored_salt = wallet.get('vasPinSalt')
            
            if not stored_hash or not stored_salt:
                return jsonify({
                    'success': False,
                    'message': 'PIN not set up. Please set up your transaction PIN first.',
                    'errors': {'pin': ['PIN not set up']}
                }), 400
            
            # Check if account is locked out
            locked_until = wallet.get('pinLockedUntil')
            if locked_until and locked_until > datetime.utcnow():
                minutes_remaining = int((locked_until - datetime.utcnow()).total_seconds() / 60) + 1
                return jsonify({
                    'success': False,
                    'message': f'Account locked. Try again in {minutes_remaining} minutes.',
                    'errors': {'pin': [f'Too many failed attempts. Try again in {minutes_remaining} minutes.']},
                    'lockoutMinutes': minutes_remaining
                }), 423  # HTTP 423 Locked
            
            # Validate PIN
            import hashlib
            input_hash = hashlib.sha256((pin + stored_salt).encode()).hexdigest()
            
            if input_hash == stored_hash:
                # PIN is correct - reset attempts and update last used
                mongo.db.vas_wallets.update_one(
                    {'userId': ObjectId(user_id)},
                    {
                        '$set': {
                            'pinAttempts': 0,
                            'pinLockedUntil': None,
                            'pinLastUsed': datetime.utcnow(),
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                
                return jsonify({
                    'success': True,
                    'message': 'PIN validated successfully',
                    'data': {
                        'valid': True,
                        'lastUsed': datetime.utcnow().isoformat() + 'Z'
                    }
                }), 200
            else:
                # PIN is incorrect - increment attempts
                attempts = wallet.get('pinAttempts', 0) + 1
                max_attempts = 3
                lockout_minutes = 15
                
                update_data = {
                    'pinAttempts': attempts,
                    'updatedAt': datetime.utcnow()
                }
                
                if attempts >= max_attempts:
                    # Lock account
                    lockout_until = datetime.utcnow() + timedelta(minutes=lockout_minutes)
                    update_data['pinLockedUntil'] = lockout_until
                    
                    mongo.db.vas_wallets.update_one(
                        {'userId': ObjectId(user_id)},
                        {'$set': update_data}
                    )
                    
                    return jsonify({
                        'success': False,
                        'message': f'Too many failed attempts. Account locked for {lockout_minutes} minutes.',
                        'errors': {'pin': [f'Account locked for {lockout_minutes} minutes due to too many failed attempts.']},
                        'lockoutMinutes': lockout_minutes
                    }), 423  # HTTP 423 Locked
                else:
                    mongo.db.vas_wallets.update_one(
                        {'userId': ObjectId(user_id)},
                        {'$set': update_data}
                    )
                    
                    attempts_left = max_attempts - attempts
                    return jsonify({
                        'success': False,
                        'message': f'Incorrect PIN. {attempts_left} attempts remaining.',
                        'errors': {'pin': [f'Incorrect PIN. {attempts_left} attempts remaining.']},
                        'attemptsRemaining': attempts_left
                    }), 400
            
        except Exception as e:
            print(f'ERROR: Error validating VAS PIN: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to validate PIN',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_wallet_bp.route('/pin/change', methods=['POST'])
    @token_required
    def change_vas_pin(current_user):
        """Change existing VAS transaction PIN"""
        try:
            user_id = str(current_user['_id'])
            data = request.get_json()
            
            old_pin = data.get('oldPin', '').strip()
            new_pin = data.get('newPin', '').strip()
            
            # Validate inputs
            if not old_pin or not new_pin:
                return jsonify({
                    'success': False,
                    'message': 'Both old and new PIN are required',
                    'errors': {'pin': ['Both old and new PIN are required']}
                }), 400
            
            if len(new_pin) != 4 or not new_pin.isdigit():
                return jsonify({
                    'success': False,
                    'message': 'New PIN must be exactly 4 digits',
                    'errors': {'newPin': ['New PIN must be exactly 4 digits']}
                }), 400
            
            if old_pin == new_pin:
                return jsonify({
                    'success': False,
                    'message': 'New PIN must be different from current PIN',
                    'errors': {'newPin': ['New PIN must be different from current PIN']}
                }), 400
            
            # Check for weak PINs
            weak_pins = ['0000', '1111', '2222', '3333', '4444', '5555', '6666', '7777', '8888', '9999', '1234', '4321', '0123', '9876']
            if new_pin in weak_pins:
                return jsonify({
                    'success': False,
                    'message': 'Please choose a stronger PIN',
                    'errors': {'newPin': ['This PIN is too common. Please choose a different one.']}
                }), 400
            
            # Get wallet
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found'
                }), 404
            
            # Validate old PIN first
            stored_hash = wallet.get('vasPinHash')
            stored_salt = wallet.get('vasPinSalt')
            
            if not stored_hash or not stored_salt:
                return jsonify({
                    'success': False,
                    'message': 'No PIN set up. Please set up your PIN first.'
                }), 400
            
            # Check lockout
            locked_until = wallet.get('pinLockedUntil')
            if locked_until and locked_until > datetime.utcnow():
                minutes_remaining = int((locked_until - datetime.utcnow()).total_seconds() / 60) + 1
                return jsonify({
                    'success': False,
                    'message': f'Account locked. Try again in {minutes_remaining} minutes.',
                    'lockoutMinutes': minutes_remaining
                }), 423
            
            # Validate old PIN
            import hashlib
            old_pin_hash = hashlib.sha256((old_pin + stored_salt).encode()).hexdigest()
            
            if old_pin_hash != stored_hash:
                return jsonify({
                    'success': False,
                    'message': 'Current PIN is incorrect',
                    'errors': {'oldPin': ['Current PIN is incorrect']}
                }), 400
            
            # Generate new salt and hash for new PIN
            import secrets
            import base64
            
            new_salt = base64.b64encode(secrets.token_bytes(32)).decode('utf-8')
            new_pin_hash = hashlib.sha256((new_pin + new_salt).encode()).hexdigest()
            
            # Update wallet with new PIN
            mongo.db.vas_wallets.update_one(
                {'userId': ObjectId(user_id)},
                {
                    '$set': {
                        'vasPinHash': new_pin_hash,
                        'vasPinSalt': new_salt,
                        'pinAttempts': 0,
                        'pinLockedUntil': None,
                        'pinLastUsed': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            print(f'SUCCESS: VAS PIN changed for user {user_id}')
            
            return jsonify({
                'success': True,
                'message': 'PIN changed successfully',
                'data': {
                    'changed': True,
                    'changedAt': datetime.utcnow().isoformat() + 'Z'
                }
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error changing VAS PIN: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to change PIN',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_wallet_bp.route('/pin/status', methods=['GET'])
    @token_required
    def get_pin_status(current_user):
        """Get PIN status for UI display"""
        try:
            user_id = str(current_user['_id'])
            
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                return jsonify({
                    'success': True,
                    'data': {
                        'isSetup': False,
                        'isLocked': False,
                        'attemptsRemaining': 3,
                        'lockoutMinutes': 0
                    },
                    'message': 'Wallet not found'
                }), 200
            
            is_setup = bool(wallet.get('vasPinHash'))
            attempts = wallet.get('pinAttempts', 0)
            max_attempts = 3
            attempts_remaining = max_attempts - attempts
            
            # Check lockout status
            locked_until = wallet.get('pinLockedUntil')
            is_locked = False
            lockout_minutes = 0
            
            if locked_until and locked_until > datetime.utcnow():
                is_locked = True
                lockout_minutes = int((locked_until - datetime.utcnow()).total_seconds() / 60) + 1
            
            return jsonify({
                'success': True,
                'data': {
                    'isSetup': is_setup,
                    'isLocked': is_locked,
                    'attemptsRemaining': max(0, attempts_remaining),
                    'lockoutMinutes': lockout_minutes,
                    'setupAt': wallet.get('pinSetupAt').isoformat() + 'Z' if wallet.get('pinSetupAt') else None,
                    'lastUsed': wallet.get('pinLastUsed').isoformat() + 'Z' if wallet.get('pinLastUsed') else None
                },
                'message': 'PIN status retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting PIN status: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to get PIN status',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_wallet_bp.route('/pin/reset', methods=['POST'])
    @token_required
    def admin_reset_pin(current_user):
        """Admin endpoint to reset user's VAS PIN - for integration with web admin panel"""
        try:
            # Check if current user is admin
            if current_user.get('role') != 'admin':
                return jsonify({
                    'success': False,
                    'message': 'Admin access required'
                }), 403
            
            data = request.get_json()
            target_user_id = data.get('userId', '').strip()
            admin_reason = data.get('reason', '').strip()
            
            if not target_user_id:
                return jsonify({
                    'success': False,
                    'message': 'User ID is required',
                    'errors': {'userId': ['User ID is required']}
                }), 400
            
            if not admin_reason:
                return jsonify({
                    'success': False,
                    'message': 'Reason is required for audit trail',
                    'errors': {'reason': ['Reason is required']}
                }), 400
            
            # Validate target user exists
            target_user = mongo.db.users.find_one({'_id': ObjectId(target_user_id)})
            if not target_user:
                return jsonify({
                    'success': False,
                    'message': 'Target user not found'
                }), 404
            
            # Get target user's wallet
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(target_user_id)})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Target user wallet not found'
                }), 404
            
            # Reset PIN data
            mongo.db.vas_wallets.update_one(
                {'userId': ObjectId(target_user_id)},
                {
                    '$unset': {
                        'vasPinHash': '',
                        'vasPinSalt': '',
                        'pinSetupAt': '',
                        'pinLastUsed': ''
                    },
                    '$set': {
                        'pinAttempts': 0,
                        'pinLockedUntil': None,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # Log admin action for audit trail
            admin_action = {
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user.get('email', ''),
                'action': 'vas_pin_reset',
                'targetUserId': ObjectId(target_user_id),
                'targetUserEmail': target_user.get('email', ''),
                'reason': admin_reason,
                'timestamp': datetime.utcnow(),
                'details': {
                    'pinWasSet': bool(wallet.get('vasPinHash')),
                    'wasLocked': bool(wallet.get('pinLockedUntil') and wallet.get('pinLockedUntil') > datetime.utcnow()),
                    'attempts': wallet.get('pinAttempts', 0)
                }
            }
            
            mongo.db.admin_actions.insert_one(admin_action)
            
            print(f'SUCCESS: Admin {current_user["email"]} reset VAS PIN for user {target_user_id} - Reason: {admin_reason}')
            
            return jsonify({
                'success': True,
                'message': 'PIN reset successfully',
                'data': {
                    'resetAt': datetime.utcnow().isoformat() + 'Z',
                    'targetUserId': target_user_id,
                    'targetUserEmail': target_user.get('email', ''),
                    'adminEmail': current_user.get('email', ''),
                    'reason': admin_reason
                }
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error resetting VAS PIN: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to reset PIN',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== ALIAS ROUTES FOR PIN ENDPOINTS (Feb 12, 2026) ====================
    # Frontend calls /vas/wallet/pin/* (missing /api prefix) due to inconsistency
    # App already submitted to Play Store, so we add backend aliases
    # These routes point to the same handlers as /api/vas/wallet/pin/*
    
    @vas_wallet_alias_bp.route('/pin/status', methods=['GET'])
    @token_required
    def get_pin_status_alias(current_user):
        """Alias for /api/vas/wallet/pin/status - called by frontend without /api prefix"""
        return get_pin_status(current_user)
    
    @vas_wallet_alias_bp.route('/pin/validate', methods=['POST'])
    @token_required
    def validate_vas_pin_alias(current_user):
        """Alias for /api/vas/wallet/pin/validate - called by frontend without /api prefix"""
        return validate_vas_pin(current_user)
    
    @vas_wallet_alias_bp.route('/pin/change', methods=['POST'])
    @token_required
    def change_vas_pin_alias(current_user):
        """Alias for /api/vas/wallet/pin/change - called by frontend without /api prefix"""
        return change_vas_pin(current_user)
    
    return vas_wallet_bp, vas_wallet_alias_bp