"""
VAS (Value Added Services) Blueprint - Production Grade
Handles wallet management and utility purchases (Airtime, Data, etc.)

Security: API keys in environment variables, idempotency protection, webhook verification
Providers: Monnify (wallet), Peyflex (primary VAS), VTpass (backup)
Pricing: Dynamic pricing engine with subscription tiers and psychological pricing
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
import os
import requests
import hmac
import hashlib
import uuid
from utils.email_service import get_email_service
from utils.dynamic_pricing_engine import get_pricing_engine, calculate_vas_price
from utils.emergency_pricing_recovery import tag_emergency_transaction
from blueprints.notifications import create_user_notification

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
    
    # ==================== PRICING ENDPOINTS ====================
    
    @vas_bp.route('/pricing/calculate', methods=['POST'])
    @token_required
    def calculate_pricing(current_user):
        """
        Calculate dynamic pricing for VAS services
        Supports both airtime and data with subscription-based discounts
        """
        try:
            data = request.json
            service_type = data.get('type', '').lower()  # 'airtime' or 'data'
            network = data.get('network', '').upper()
            amount = float(data.get('amount', 0))
            plan_id = data.get('planId')  # Required for data
            
            if service_type not in ['airtime', 'data']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid service type. Must be airtime or data.'
                }), 400
            
            if not network or amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Network and amount are required.'
                }), 400
            
            if service_type == 'data' and not plan_id:
                return jsonify({
                    'success': False,
                    'message': 'Plan ID is required for data pricing.'
                }), 400
            
            # Determine user tier
            user_tier = 'basic'
            if current_user.get('subscriptionStatus') == 'active':
                subscription_plan = current_user.get('subscriptionPlan', 'premium')
                user_tier = subscription_plan.lower()
            
            # Calculate pricing using dynamic engine
            pricing_engine = get_pricing_engine(mongo.db)
            pricing_result = pricing_engine.calculate_selling_price(
                service_type=service_type,
                network=network,
                base_amount=amount,
                user_tier=user_tier,
                plan_id=plan_id
            )
            
            # Get competitive analysis
            competitive_analysis = pricing_engine.get_competitive_analysis(
                service_type, network, amount
            )
            
            return jsonify({
                'success': True,
                'data': {
                    'pricing': pricing_result,
                    'competitive': competitive_analysis,
                    'userTier': user_tier,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'Pricing calculated successfully'
            }), 200
            
        except Exception as e:
            print(f'❌ Error calculating pricing: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to calculate pricing',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/pricing/plans/<network>', methods=['GET'])
    @token_required
    def get_data_plans_with_pricing(current_user, network):
        """
        Get data plans with dynamic pricing for a specific network
        """
        try:
            # Determine user tier
            user_tier = 'basic'
            if current_user.get('subscriptionStatus') == 'active':
                subscription_plan = current_user.get('subscriptionPlan', 'premium')
                user_tier = subscription_plan.lower()
            
            # Get pricing engine
            pricing_engine = get_pricing_engine(mongo.db)
            
            # Get data plans from Peyflex
            data_plans = pricing_engine.get_peyflex_rates('data', network)
            
            # Add dynamic pricing to each plan
            enhanced_plans = []
            for plan_id, plan_data in data_plans.items():
                base_price = plan_data.get('price', 0)
                
                # Calculate pricing for this plan
                pricing_result = pricing_engine.calculate_selling_price(
                    service_type='data',
                    network=network,
                    base_amount=base_price,
                    user_tier=user_tier,
                    plan_id=plan_id
                )
                
                enhanced_plan = {
                    'id': plan_id,
                    'name': plan_data.get('name', ''),
                    'validity': plan_data.get('validity', 30),
                    'originalPrice': base_price,
                    'sellingPrice': pricing_result['selling_price'],
                    'savings': pricing_result['discount_applied'],
                    'savingsMessage': pricing_result['savings_message'],
                    'margin': pricing_result['margin'],
                    'strategy': pricing_result['strategy_used']
                }
                
                enhanced_plans.append(enhanced_plan)
            
            # Sort by price (cheapest first)
            enhanced_plans.sort(key=lambda x: x['sellingPrice'])
            
            return jsonify({
                'success': True,
                'data': {
                    'network': network.upper(),
                    'plans': enhanced_plans,
                    'userTier': user_tier,
                    'totalPlans': len(enhanced_plans)
                },
                'message': 'Data plans with pricing retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'❌ Error getting data plans with pricing: {str(e)}')
            
            # Fallback to original endpoint
            return get_data_plans(network)

    # ==================== EMERGENCY RECOVERY ENDPOINTS ====================
    
    @vas_bp.route('/emergency-recovery/process', methods=['POST'])
    @token_required
    def process_emergency_recovery(current_user):
        """
        Process emergency pricing recovery (Admin only)
        Run this periodically to compensate users who paid emergency rates
        """
        try:
            # Check if user is admin
            if not current_user.get('isAdmin', False):
                return jsonify({
                    'success': False,
                    'message': 'Admin access required'
                }), 403
            
            data = request.json
            limit = int(data.get('limit', 50))
            
            from utils.emergency_pricing_recovery import process_emergency_recoveries
            
            recovery_results = process_emergency_recoveries(mongo.db, limit)
            
            # Summary statistics
            total_processed = len(recovery_results)
            completed_recoveries = [r for r in recovery_results if r['status'] == 'completed']
            total_compensated = sum(r.get('overage', 0) for r in completed_recoveries)
            
            return jsonify({
                'success': True,
                'data': {
                    'total_processed': total_processed,
                    'completed_recoveries': len(completed_recoveries),
                    'total_compensated': total_compensated,
                    'results': recovery_results
                },
                'message': f'Processed {total_processed} emergency recoveries, compensated ₦{total_compensated:.2f}'
            }), 200
            
        except Exception as e:
            print(f'❌ Error processing emergency recovery: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to process emergency recovery',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/emergency-recovery/stats', methods=['GET'])
    @token_required
    def get_emergency_recovery_stats(current_user):
        """
        Get emergency recovery statistics (Admin only)
        """
        try:
            # Check if user is admin
            if not current_user.get('isAdmin', False):
                return jsonify({
                    'success': False,
                    'message': 'Admin access required'
                }), 403
            
            days = int(request.args.get('days', 30))
            
            from utils.emergency_pricing_recovery import EmergencyPricingRecovery
            recovery_system = EmergencyPricingRecovery(mongo.db)
            
            stats = recovery_system.get_recovery_stats(days)
            
            return jsonify({
                'success': True,
                'data': stats,
                'message': f'Emergency recovery stats for last {days} days'
            }), 200
            
        except Exception as e:
            print(f'❌ Error getting recovery stats: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to get recovery stats',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/emergency-recovery/trigger', methods=['POST'])
    @token_required
    def trigger_emergency_recovery_job(current_user):
        """
        Manually trigger emergency recovery job (Admin only)
        This is the integration point for the automated recovery script
        """
        try:
            # Check if user is admin
            if not current_user.get('isAdmin', False):
                return jsonify({
                    'success': False,
                    'message': 'Admin access required'
                }), 403
            
            data = request.json or {}
            limit = int(data.get('limit', 50))
            dry_run = data.get('dryRun', False)
            
            print(f'🚨 Manual emergency recovery triggered by admin {current_user.get("email", "unknown")}')
            
            if dry_run:
                # Count pending recoveries for dry run
                pending_count = mongo.db.emergency_pricing_tags.count_documents({
                    'status': 'PENDING_RECOVERY',
                    'recoveryDeadline': {'$gt': datetime.utcnow()}
                })
                
                return jsonify({
                    'success': True,
                    'data': {
                        'dry_run': True,
                        'pending_recoveries': pending_count,
                        'would_process': min(pending_count, limit)
                    },
                    'message': f'Dry run: {pending_count} pending recoveries found'
                }), 200
            
            # Execute actual recovery processing
            from utils.emergency_pricing_recovery import process_emergency_recoveries
            
            recovery_results = process_emergency_recoveries(mongo.db, limit)
            
            # Enhanced response with detailed results
            if recovery_results.get('status') == 'completed':
                results = recovery_results.get('results', [])
                completed_recoveries = [r for r in results if r.get('status') == 'completed']
                total_compensated = sum(r.get('overage', 0) for r in completed_recoveries)
                
                return jsonify({
                    'success': True,
                    'data': {
                        'total_processed': len(results),
                        'completed_recoveries': len(completed_recoveries),
                        'total_compensated': total_compensated,
                        'results': results,
                        'triggered_by': current_user.get('email', 'unknown'),
                        'triggered_at': datetime.utcnow().isoformat() + 'Z'
                    },
                    'message': f'Recovery job completed: {len(completed_recoveries)} recoveries processed, ₦{total_compensated:.2f} compensated'
                }), 200
            
            elif recovery_results.get('status') == 'skipped':
                return jsonify({
                    'success': True,
                    'data': {
                        'skipped': True,
                        'reason': recovery_results.get('reason', 'unknown'),
                        'message': recovery_results.get('message', '')
                    },
                    'message': f'Recovery job skipped: {recovery_results.get("reason", "unknown")}'
                }), 200
            
            else:
                return jsonify({
                    'success': False,
                    'message': f'Recovery job failed: {recovery_results.get("error", "unknown")}',
                    'errors': {'general': [recovery_results.get('error', 'unknown')]}
                }), 500
            
        except Exception as e:
            print(f'❌ Error triggering recovery job: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to trigger recovery job',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bp.route('/emergency-recovery/schedule', methods=['POST'])
    @token_required
    def schedule_emergency_recovery(current_user):
        """
        Schedule automated emergency recovery job (Admin only)
        This endpoint can be called by external schedulers (cron, etc.)
        """
        try:
            # Check if user is admin or if this is a system call
            api_key = request.headers.get('X-API-Key')
            system_api_key = os.environ.get('SYSTEM_API_KEY', '')
            
            is_admin = current_user.get('isAdmin', False) if current_user else False
            is_system_call = api_key and api_key == system_api_key and system_api_key
            
            if not (is_admin or is_system_call):
                return jsonify({
                    'success': False,
                    'message': 'Admin access or valid API key required'
                }), 403
            
            # Process recoveries automatically
            from utils.emergency_pricing_recovery import process_emergency_recoveries
            
            recovery_results = process_emergency_recoveries(mongo.db, limit=100)
            
            # Log the scheduled job execution
            caller = current_user.get('email', 'unknown') if current_user else 'system_scheduler'
            print(f'🕐 Scheduled emergency recovery executed by: {caller}')
            
            if recovery_results.get('status') == 'completed':
                results = recovery_results.get('results', [])
                completed_recoveries = [r for r in results if r.get('status') == 'completed']
                total_compensated = sum(r.get('overage', 0) for r in completed_recoveries)
                
                # Create admin notification for significant recoveries
                if len(completed_recoveries) > 10 or total_compensated > 5000:
                    create_user_notification(
                        mongo=mongo.db,
                        user_id='admin',  # Special admin notification
                        category='system',
                        title='🚨 Large Emergency Recovery Batch',
                        body=f'Processed {len(completed_recoveries)} recoveries totaling ₦{total_compensated:.2f}',
                        metadata={
                            'recovery_count': len(completed_recoveries),
                            'total_compensated': total_compensated,
                            'triggered_by': caller
                        },
                        priority='high'
                    )
                
                return jsonify({
                    'success': True,
                    'data': {
                        'scheduled_execution': True,
                        'total_processed': len(results),
                        'completed_recoveries': len(completed_recoveries),
                        'total_compensated': total_compensated,
                        'executed_by': caller,
                        'executed_at': datetime.utcnow().isoformat() + 'Z'
                    },
                    'message': f'Scheduled recovery completed: {len(completed_recoveries)} recoveries, ₦{total_compensated:.2f} compensated'
                }), 200
            
            elif recovery_results.get('status') == 'skipped':
                return jsonify({
                    'success': True,
                    'data': {
                        'scheduled_execution': True,
                        'skipped': True,
                        'reason': recovery_results.get('reason', 'unknown')
                    },
                    'message': f'Scheduled recovery skipped: {recovery_results.get("reason", "unknown")}'
                }), 200
            
            else:
                return jsonify({
                    'success': False,
                    'message': f'Scheduled recovery failed: {recovery_results.get("error", "unknown")}',
                    'errors': {'general': [recovery_results.get('error', 'unknown')]}
                }), 500
            
        except Exception as e:
            print(f'❌ Error in scheduled recovery: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to execute scheduled recovery',
                'errors': {'general': [str(e)]}
            }), 500

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
        
        # Use rewards.streak as authoritative source for login streak
        rewards_record = mongo.db.rewards.find_one({'user_id': ObjectId(user_id)})
        login_streak = rewards_record.get('streak', 0) if rewards_record else 0
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
        
        Step 1: Initialize transaction to get Monnify transaction reference
        Step 2: Use that reference to generate dynamic account number
        """
        try:
            access_token = call_monnify_auth()
            
            # Step 1: Initialize transaction with Monnify
            init_payload = {
                'amount': amount,
                'customerName': customer_name,
                'customerEmail': customer_email,
                'paymentReference': transaction_reference,  # Our unique reference
                'paymentDescription': payment_description,
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'paymentMethods': ['ACCOUNT_TRANSFER']
            }
            
            print(f'🔄 Step 1: Initializing Monnify transaction with payload: {init_payload}')
            
            init_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/merchant/transactions/init-transaction',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json=init_payload,
                timeout=30
            )
            
            print(f'📥 Monnify init response status: {init_response.status_code}')
            print(f'📥 Monnify init response body: {init_response.text}')
            
            if init_response.status_code != 200:
                error_msg = f'Monnify transaction initialization failed with status {init_response.status_code}: {init_response.text}'
                print(f'❌ {error_msg}')
                raise Exception(error_msg)
            
            init_json = init_response.json()
            
            if not init_json.get('requestSuccessful', False):
                error_msg = f"Monnify init failed: {init_json.get('responseMessage', 'Unknown error')}"
                print(f'❌ {error_msg}')
                raise Exception(error_msg)
            
            # Get the Monnify transaction reference
            monnify_transaction_ref = init_json['responseBody']['transactionReference']
            print(f'✅ Step 1 complete. Monnify transaction reference: {monnify_transaction_ref}')
            
            # Step 2: Generate dynamic account using Monnify transaction reference
            account_payload = {
                'transactionReference': monnify_transaction_ref,
                'bankCode': '058'  # GTBank for USSD generation (optional)
            }
            
            print(f'🔄 Step 2: Generating dynamic account with payload: {account_payload}')
            
            payment_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/merchant/bank-transfer/init-payment',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json=account_payload,
                timeout=30
            )
            
            print(f'📥 Monnify account response status: {payment_response.status_code}')
            print(f'📥 Monnify account response body: {payment_response.text}')
            
            if payment_response.status_code != 200:
                error_msg = f'Monnify dynamic account generation failed with status {payment_response.status_code}: {payment_response.text}'
                print(f'❌ {error_msg}')
                raise Exception(error_msg)
            
            payment_json = payment_response.json()
            
            if not payment_json.get('requestSuccessful', False):
                error_msg = f"Monnify account generation failed: {payment_json.get('responseMessage', 'Unknown error')}"
                print(f'❌ {error_msg}')
                raise Exception(error_msg)
            
            response_data = payment_json['responseBody']
            
            result = {
                'accountNumber': response_data['accountNumber'],
                'accountName': response_data['accountName'],
                'bankName': response_data['bankName'],
                'bankCode': response_data['bankCode'],
                'ussdCode': response_data.get('ussdCode', ''),
                'monnifyTransactionReference': monnify_transaction_ref  # Store for webhook matching
            }
            
            print(f'✅ Step 2 complete. Dynamic account generated: {result["accountNumber"]}')
            return result
            
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
    
    def generate_retention_description(base_description, savings_message, user_tier, discount_applied):
        """
        Generate retention-focused expense description that reinforces subscription value
        🎯 PASSIVE RETENTION ENGINE: Every expense entry becomes a subscription value reminder
        """
        if not savings_message or discount_applied <= 0:
            return base_description
        
        # Tier-specific retention messaging
        if user_tier == 'gold':
            if discount_applied >= 50:
                retention_suffix = f" • 💎 Gold Tier saved you ₦{discount_applied:.0f}! Your ₦25k/year subscription pays for itself."
            else:
                retention_suffix = f" • 💎 Gold Tier benefit: ₦{discount_applied:.0f} saved"
        elif user_tier == 'premium':
            if discount_applied >= 30:
                retention_suffix = f" • ✨ Premium saved you ₦{discount_applied:.0f}! Your ₦10k/year subscription is working."
            else:
                retention_suffix = f" • ✨ Premium benefit: ₦{discount_applied:.0f} saved"
        else:
            # Basic users see what they're missing
            return base_description
        
        return base_description + retention_suffix
    
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
    
    @vas_bp.route('/verification/validate-details', methods=['POST'])
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
                    'warning': 'Double-check your details to avoid losing the ₦70 non-refundable government verification fee'
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
                    'warning': 'IMPORTANT: The ₦70 verification fee is a government charge and is NON-REFUNDABLE. If your BVN/NIN details are incorrect, you will need to pay again.',
                    'advice': 'Please triple-check your BVN and NIN numbers before proceeding to payment.'
                }
            }), 200
            
        except Exception as e:
            print(f'❌ Error validating KYC details: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': {'general': [str(e)]}
            }), 500

    @vas_bp.route('/verification/generate-payment', methods=['POST'])
    @token_required
    def generate_verification_payment(current_user):
        """Generate Quick Pay payment for KYC verification fee (₦70)"""
        try:
            user_id = str(current_user['_id'])
            data = request.get_json()
            
            bvn = data.get('bvn', '').strip()
            nin = data.get('nin', '').strip()
            
            if not bvn or not nin:
                return jsonify({
                    'success': False,
                    'message': 'BVN and NIN are required'
                }), 400
            
            # Store BVN/NIN temporarily for account creation after payment
            mongo.db.kyc_verifications.delete_many({
                'userId': ObjectId(user_id),
                'status': 'pending_payment'
            })
            
            mongo.db.kyc_verifications.insert_one({
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'bvn': bvn,
                'nin': nin,
                'status': 'pending_payment',
                'createdAt': datetime.utcnow(),
                'expiresAt': datetime.utcnow() + timedelta(minutes=30)
            })
            
            # Generate Quick Pay payment for ₦70 verification fee
            # Initialize transaction with Monnify first
            access_token = call_monnify_auth()
            
            transaction_reference = f'VER_{user_id}_{int(datetime.utcnow().timestamp())}'
            
            # Initialize transaction
            init_data = {
                'amount': 70.00,
                'customerName': current_user.get('fullName', f'FiCore User {user_id[:8]}'),
                'customerEmail': current_user.get('email', ''),
                'paymentReference': transaction_reference,
                'paymentDescription': 'KYC Verification Fee',
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'redirectUrl': 'https://ficore.africa/payment-success',
                'paymentMethods': ['ACCOUNT_TRANSFER']
            }
            
            init_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/merchant/transactions/init-transaction',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json=init_data,
                timeout=30
            )
            
            if init_response.status_code != 200:
                raise Exception(f'Transaction initialization failed: {init_response.text}')
            
            init_result = init_response.json()['responseBody']
            monnify_transaction_reference = init_result['transactionReference']
            
            # Generate dynamic account for payment
            payment_data = {
                'transactionReference': monnify_transaction_reference,
                'amount': 70.00,
                'customerName': current_user.get('fullName', f'FiCore User {user_id[:8]}'),
                'customerEmail': current_user.get('email', ''),
                'bankCode': '035',  # Wema Bank
                'accountDurationInMinutes': 30
            }
            
            payment_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/merchant/bank-transfer/init-payment',
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json=payment_data,
                timeout=30
            )
            
            if payment_response.status_code != 200:
                raise Exception(f'Payment initialization failed: {payment_response.text}')
            
            payment_result = payment_response.json()['responseBody']
            
            # Store payment details for webhook matching
            mongo.db.vas_transactions.insert_one({
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'type': 'KYC_VERIFICATION',
                'amount': 70.00,
                'status': 'PENDING',
                'paymentReference': transaction_reference,
                'monnifyTransactionReference': monnify_transaction_reference,
                'accountNumber': payment_result['accountNumber'],
                'accountName': payment_result['accountName'],
                'bankName': payment_result['bankName'],
                'bankCode': payment_result['bankCode'],
                'expiresAt': datetime.utcnow() + timedelta(minutes=30),
                'createdAt': datetime.utcnow()
            })
            
            print(f'✅ KYC verification payment generated for user {user_id}: {payment_result["accountNumber"]}')
            
            return jsonify({
                'success': True,
                'data': {
                    'accountNumber': payment_result['accountNumber'],
                    'accountName': payment_result['accountName'],
                    'bankName': payment_result['bankName'],
                    'bankCode': payment_result['bankCode'],
                    'amount': 70.00,
                    'reference': transaction_reference,
                    'expiresAt': (datetime.utcnow() + timedelta(minutes=30)).isoformat() + 'Z'
                },
                'message': 'Verification payment account generated',
                'disclaimer': {
                    'nonRefundable': True,
                    'governmentFee': True,
                    'warning': 'NON-REFUNDABLE: The ₦70 verification fee is a government charge for BVN/NIN validation, not a FiCore fee. If verification fails due to incorrect details, you must pay again with correct information.',
                    'notice': 'This is a government regulatory fee, not a FiCore charge'
                }
            }), 200
            
        except Exception as e:
            print(f'❌ Error generating verification payment: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to generate payment account',
                'errors': {'general': [str(e)]},
                'reminder': 'Remember: Verification fees are non-refundable government charges. Please ensure your BVN and NIN are correct before proceeding.'
            }), 500

    @vas_bp.route('/verification/verify-and-create', methods=['POST'])
    @token_required
    def verify_payment_and_create_account(current_user):
        """Verify KYC payment was received and create dedicated account"""
        try:
            user_id = str(current_user['_id'])
            
            # Check for successful KYC verification payment
            successful_payment = mongo.db.vas_transactions.find_one({
                'userId': ObjectId(user_id),
                'type': 'KYC_VERIFICATION',
                'status': 'SUCCESS'
            })
            
            if not successful_payment:
                return jsonify({
                    'success': False,
                    'message': 'Payment not found yet. Please wait a moment and try again.',
                    'reminder': 'If your BVN/NIN details were incorrect, the ₦70 government verification fee is non-refundable. You will need to pay again with correct details.'
                }), 400
            
            # Get stored KYC data
            kyc_data = mongo.db.kyc_verifications.find_one({
                'userId': ObjectId(user_id),
                'status': 'pending_payment'
            })
            
            if not kyc_data:
                return jsonify({
                    'success': False,
                    'message': 'KYC data not found. Please restart the verification process.',
                    'note': 'Previous verification fees are non-refundable as they are government charges for BVN/NIN validation.'
                }), 400
            
            # Check if wallet already exists
            existing_wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if existing_wallet:
                return jsonify({
                    'success': False,
                    'message': 'Dedicated account already exists.'
                }), 400
            
            # Create dedicated account with KYC data
            access_token = call_monnify_auth()
            
            account_data = {
                'accountReference': f'FICORE_{user_id}',
                'accountName': current_user.get('fullName', f"FiCore User {user_id[:8]}"),
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'customerEmail': current_user.get('email', ''),
                'customerName': current_user.get('fullName', f"FiCore User {user_id[:8]}"),
                'bvn': kyc_data['bvn'],
                'nin': kyc_data['nin'],
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
                'kycVerified': True,
                'bvn': kyc_data['bvn'],
                'nin': kyc_data['nin'],
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.vas_wallets.insert_one(wallet_data)
            
            # Update KYC verification status
            mongo.db.kyc_verifications.update_one(
                {'_id': kyc_data['_id']},
                {'$set': {'status': 'completed', 'completedAt': datetime.utcnow()}}
            )
            
            print(f'✅ KYC verified dedicated account created for user {user_id}')
            
            # Return the first account details
            first_account = van_data['accounts'][0] if van_data['accounts'] else {}
            
            return jsonify({
                'success': True,
                'data': {
                    'accountNumber': first_account.get('accountNumber', ''),
                    'accountName': first_account.get('accountName', ''),
                    'bankName': first_account.get('bankName', 'Wema Bank'),
                    'bankCode': first_account.get('bankCode', '035'),
                    'tier': 'TIER_2',
                    'kycVerified': True,
                    'createdAt': wallet_data['createdAt'].isoformat() + 'Z'
                },
                'message': 'Payment verified and dedicated account created successfully'
            }), 201
            
        except Exception as e:
            print(f'❌ Error verifying payment and creating account: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to verify payment and create account',
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
            
            # Update transaction with Monnify reference for webhook matching
            mongo.db.vas_transactions.update_one(
                {'_id': pending_txn['_id']},
                {'$set': {'monnifyTransactionReference': monnify_response['monnifyTransactionReference']}}
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
                
                # Handle Quick Pay transactions
                # First try to find by Monnify transaction reference (new method)
                pending_txn = mongo.db.vas_transactions.find_one({
                    'monnifyTransactionReference': transaction_reference,
                    'status': 'PENDING_PAYMENT'
                })
                
                # Fallback: try to find by our transaction reference (old method)
                if not pending_txn and transaction_reference.startswith('FICORE_QP_'):
                    pending_txn = mongo.db.vas_transactions.find_one({
                        'transactionReference': transaction_reference,
                        'status': 'PENDING_PAYMENT'
                    })
                
                if not pending_txn:
                    print(f'⚠️ No pending transaction found for Monnify ref: {transaction_reference}')
                    return jsonify({'success': False, 'message': 'Transaction not found'}), 404
                
                user_id = str(pending_txn['userId'])
                txn_type = pending_txn.get('type')
                
                print(f'✅ Found pending transaction: {pending_txn["transactionReference"]} (Type: {txn_type})')
                
                # Handle KYC_VERIFICATION payments
                if txn_type == 'KYC_VERIFICATION':
                    # Verify the payment amount is correct (₦70)
                    if amount_paid < 70.0:
                        print(f'⚠️ KYC verification payment insufficient: ₦{amount_paid} < ₦70')
                        return jsonify({'success': False, 'message': 'Insufficient payment amount'}), 400
                    
                    # Update transaction status
                    mongo.db.vas_transactions.update_one(
                        {'_id': pending_txn['_id']},
                        {'$set': {
                            'status': 'SUCCESS',
                            'amountPaid': amount_paid,
                            'reference': transaction_reference,
                            'provider': 'monnify',
                            'metadata': transaction_data,
                            'completedAt': datetime.utcnow()
                        }}
                    )
                    
                    # Record corporate revenue (₦70 KYC fee)
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
                    print(f'💰 KYC verification revenue recorded: ₦70 from user {user_id}')
                    
                    # Send confirmation email
                    try:
                        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                        if user and user.get('email'):
                            email_service = get_email_service()
                            user_name = user.get('displayName') or f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
                            
                            transaction_data_email = {
                                'type': 'KYC Verification Payment',
                                'amount': '70.00',
                                'fee': '0.00',
                                'total_paid': f"{amount_paid:,.2f}",
                                'date': datetime.utcnow().strftime('%B %d, %Y at %I:%M %p'),
                                'reference': transaction_reference,
                                'new_balance': 'N/A',
                                'is_premium': False
                            }
                            
                            email_result = email_service.send_transaction_receipt(
                                to_email=user['email'],
                                transaction_data=transaction_data_email
                            )
                            
                            print(f'📧 KYC verification receipt email: {email_result.get("success", False)} to {user["email"]}')
                            
                            # Create notification
                            notification_id = create_user_notification(
                                mongo=mongo,
                                user_id=user_id,
                                category='account',
                                title='✅ KYC Verification Payment Received',
                                body='Your ₦70 verification payment has been confirmed. You can now create your dedicated account.',
                                related_id=transaction_reference,
                                metadata={
                                    'transaction_type': 'KYC_VERIFICATION',
                                    'amount_paid': amount_paid,
                                    'verification_fee': 70.0
                                },
                                priority='high'
                            )
                            
                            if notification_id:
                                print(f'🔔 KYC verification notification created: {notification_id}')
                    except Exception as email_error:
                        print(f'⚠️ KYC verification email failed: {email_error}')
                        # Don't fail the transaction if email fails
                    
                    print(f'✅ KYC Verification Payment: User {user_id}, Paid: ₦{amount_paid}, Fee: ₦70')
                    return jsonify({'success': True, 'message': 'KYC verification payment processed successfully'}), 200
                    
                    # Handle WALLET_FUNDING
                    elif txn_type == 'WALLET_FUNDING':
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
                        
                        # ₦0 COMMUNICATION STRATEGY: Send transaction receipt via email
                        try:
                            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                            if user and user.get('email'):
                                email_service = get_email_service()
                                user_name = user.get('displayName') or f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
                                
                                transaction_data = {
                                    'type': 'Liquid Wallet Funding',
                                    'amount': f"{amount_to_credit:,.2f}",
                                    'fee': f"{deposit_fee:,.2f}" if deposit_fee > 0 else "₦0 (Premium)",
                                    'total_paid': f"{amount_paid:,.2f}",
                                    'date': datetime.utcnow().strftime('%B %d, %Y at %I:%M %p'),
                                    'reference': transaction_reference,
                                    'new_balance': f"{new_balance:,.2f}",
                                    'is_premium': is_premium
                                }
                                
                                email_result = email_service.send_transaction_receipt(
                                    to_email=user['email'],
                                    transaction_data=transaction_data
                                )
                                
                                print(f'📧 Transaction receipt email: {email_result.get("success", False)} to {user["email"]}')
                                
                                # PERSISTENT NOTIFICATIONS: Create server notification
                                notification_id = create_user_notification(
                                    mongo=mongo,
                                    user_id=user_id,
                                    category='wallet',
                                    title='💰 Wallet Funded Successfully',
                                    body=f'₦{amount_to_credit:,.2f} added to your Liquid Wallet. New balance: ₦{new_balance:,.2f}',
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
                                    print(f'🔔 Persistent notification created: {notification_id}')
                                
                        except Exception as e:
                            print(f'📧 Failed to send transaction receipt email: {str(e)}')
                            # Don't fail the transaction if email fails
                        
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
                    
                    # ₦0 COMMUNICATION STRATEGY: Send transaction receipt via email
                    try:
                        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                        if user and user.get('email'):
                            email_service = get_email_service()
                            user_name = user.get('displayName') or f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
                            
                            transaction_data = {
                                'type': 'Liquid Wallet Funding',
                                'amount': f"{amount_to_credit:,.2f}",
                                'fee': f"{deposit_fee:,.2f}" if deposit_fee > 0 else "₦0 (Premium)",
                                'total_paid': f"{amount_paid:,.2f}",
                                'date': datetime.utcnow().strftime('%B %d, %Y at %I:%M %p'),
                                'reference': transaction_reference,
                                'new_balance': f"{new_balance:,.2f}",
                                'is_premium': is_premium
                            }
                            
                            email_result = email_service.send_transaction_receipt(
                                to_email=user['email'],
                                transaction_data=transaction_data
                            )
                            
                            print(f'📧 Transaction receipt email: {email_result.get("success", False)} to {user["email"]}')
                    except Exception as e:
                        print(f'📧 Failed to send transaction receipt email: {str(e)}')
                        # Don't fail the transaction if email fails
                    
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
        """Purchase airtime with dynamic pricing and idempotency protection"""
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
            
            # Determine user tier for pricing
            user_tier = 'basic'
            if current_user.get('subscriptionStatus') == 'active':
                subscription_plan = current_user.get('subscriptionPlan', 'premium')
                user_tier = subscription_plan.lower()
            
            # Calculate dynamic pricing
            pricing_result = calculate_vas_price(
                mongo.db, 'airtime', network, amount, user_tier, None, user_id
            )
            
            selling_price = pricing_result['selling_price']
            cost_price = pricing_result['cost_price']
            margin = pricing_result['margin']
            savings_message = pricing_result['savings_message']
            
            # 🚨 EMERGENCY PRICING DETECTION
            emergency_multiplier = 2.0
            normal_expected_cost = amount * 0.99  # Expected normal cost for airtime
            is_emergency_pricing = cost_price >= (normal_expected_cost * emergency_multiplier * 0.8)  # 80% threshold
            
            if is_emergency_pricing:
                print(f"🚨 EMERGENCY PRICING DETECTED: Cost ₦{cost_price} vs Expected ₦{normal_expected_cost}")
                # Will tag after successful transaction
            
            # CRITICAL: Check for pending duplicate transaction (idempotency)
            pending_txn = check_pending_transaction(user_id, 'AIRTIME', selling_price, phone_number)
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
            
            # Use selling price as total amount (no additional fees)
            total_amount = selling_price
            
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
                'amount': amount,  # Face value amount
                'sellingPrice': selling_price,
                'costPrice': cost_price,
                'margin': margin,
                'userTier': user_tier,
                'pricingStrategy': pricing_result['strategy_used'],
                'savingsMessage': savings_message,
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
                # Use face value amount for API call (not selling price)
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
            
            # Deduct selling price from wallet (not face value)
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
            
            # Record corporate revenue (margin earned)
            if margin > 0:
                corporate_revenue = {
                    '_id': ObjectId(),
                    'type': 'VAS_MARGIN',
                    'category': 'AIRTIME_MARGIN',
                    'amount': margin,
                    'userId': ObjectId(user_id),
                    'relatedTransaction': str(transaction_id),
                    'description': f'Airtime margin from user {user_id} - {network}',
                    'status': 'RECORDED',
                    'createdAt': datetime.utcnow(),
                    'metadata': {
                        'network': network,
                        'faceValue': amount,
                        'sellingPrice': selling_price,
                        'costPrice': cost_price,
                        'userTier': user_tier,
                        'strategy': pricing_result['strategy_used'],
                        'emergencyPricing': is_emergency_pricing
                    }
                }
                mongo.db.corporate_revenue.insert_one(corporate_revenue)
                print(f'💰 Corporate revenue recorded: ₦{margin} from airtime sale to user {user_id}')
            
            # 🚨 TAG EMERGENCY TRANSACTIONS FOR RECOVERY
            if is_emergency_pricing:
                try:
                    emergency_tag_id = tag_emergency_transaction(
                        mongo.db, str(transaction_id), cost_price, 'airtime', network
                    )
                    print(f'🏥 Emergency transaction tagged for recovery: {emergency_tag_id}')
                    
                    # Create immediate notification about emergency pricing
                    create_user_notification(
                        mongo=mongo.db,
                        user_id=user_id,
                        category='system',
                        title='⚡ Emergency Pricing Used',
                        body=f'Your {network} airtime purchase used emergency pricing during system maintenance. We\'ll automatically adjust any overcharges within 24 hours.',
                        related_id=str(transaction_id),
                        metadata={
                            'emergency_cost': cost_price,
                            'transaction_id': str(transaction_id),
                            'recovery_expected': True
                        },
                        priority='high'
                    )
                    
                except Exception as e:
                    print(f'⚠️ Failed to tag emergency transaction: {str(e)}')
                    # Don't fail the transaction if tagging fails
            
            # Auto-create expense entry (auto-bookkeeping)
            base_description = f'Airtime - {network} ₦{amount} for {phone_number[-4:]}****'
            
            # 🎯 PASSIVE RETENTION ENGINE: Generate retention-focused description
            retention_description = generate_retention_description(
                base_description,
                savings_message,
                user_tier,
                pricing_result.get('discount_applied', 0)
            )
            
            expense_entry = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'amount': selling_price,  # Record selling price as expense
                'category': 'Utilities',
                'description': retention_description,  # Use retention-enhanced description
                'date': datetime.utcnow(),
                'tags': ['VAS', 'Airtime', network],
                'vasTransactionId': transaction_id,
                'metadata': {
                    'faceValue': amount,
                    'actualCost': selling_price,
                    'userTier': user_tier,
                    'savingsMessage': savings_message,
                    'originalPrice': pricing_result.get('cost_price', 0) + pricing_result.get('margin', 0),
                    'discountApplied': pricing_result.get('discount_applied', 0),
                    'pricingStrategy': pricing_result.get('strategy_used', 'standard'),
                    'freeFeesApplied': pricing_result.get('free_fee_applied', False),
                    'baseDescription': base_description,  # Store original for reference
                    'retentionEnhanced': True  # Flag to indicate retention messaging applied
                },
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.expenses.insert_one(expense_entry)
            
            print(f'✅ Airtime purchase complete: User {user_id}, Face Value: ₦{amount}, Charged: ₦{selling_price}, Margin: ₦{margin}, Provider: {provider}')
            
            # 🎯 RETENTION DATA for Frontend Trust Building
            retention_data = {
                'userTier': user_tier,
                'originalPrice': amount,
                'finalPrice': selling_price,
                'totalSaved': amount - selling_price,
                'savingsMessage': savings_message,
                'subscriptionROI': {
                    'tierName': user_tier.title() if user_tier != 'basic' else 'Basic',
                    'annualCost': 25000 if user_tier == 'gold' else (10000 if user_tier == 'premium' else 0),
                    'monthlyProgress': f"You've saved ₦{amount - selling_price:.0f} this transaction",
                    'loyaltyNudge': f"Your {user_tier.title()} subscription is working!" if user_tier != 'basic' else "Upgrade to Premium to start saving on every purchase!"
                },
                'retentionDescription': retention_description,
                'emergencyPricing': is_emergency_pricing,
                'priceProtectionActive': is_emergency_pricing
            }

            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(transaction_id),
                    'requestId': request_id,
                    'faceValue': amount,
                    'amountCharged': selling_price,
                    'margin': margin,
                    'newBalance': new_balance,
                    'provider': provider,
                    'userTier': user_tier,
                    'savingsMessage': savings_message,
                    'pricingStrategy': pricing_result['strategy_used'],
                    'expenseRecorded': True,
                    'retentionData': retention_data  # 🎯 NEW: Frontend trust data
                },
                'message': f'Airtime purchased successfully! {savings_message}' if savings_message else 'Airtime purchased successfully!'
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
        """Purchase data with dynamic pricing and idempotency protection"""
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
            
            # Determine user tier for pricing
            user_tier = 'basic'
            if current_user.get('subscriptionStatus') == 'active':
                subscription_plan = current_user.get('subscriptionPlan', 'premium')
                user_tier = subscription_plan.lower()
            
            # Calculate dynamic pricing
            pricing_result = calculate_vas_price(
                mongo.db, 'data', network, amount, user_tier, data_plan_id, user_id
            )
            
            selling_price = pricing_result['selling_price']
            cost_price = pricing_result['cost_price']
            margin = pricing_result['margin']
            savings_message = pricing_result['savings_message']
            
            # 🚨 EMERGENCY PRICING DETECTION
            emergency_multiplier = 2.0
            normal_expected_cost = amount  # For data, amount is usually the expected cost
            is_emergency_pricing = cost_price >= (normal_expected_cost * emergency_multiplier * 0.8)  # 80% threshold
            
            if is_emergency_pricing:
                print(f"🚨 EMERGENCY PRICING DETECTED: Cost ₦{cost_price} vs Expected ₦{normal_expected_cost}")
                # Will tag after successful transaction
            
            # CRITICAL: Check for pending duplicate transaction (idempotency)
            pending_txn = check_pending_transaction(user_id, 'DATA', selling_price, phone_number)
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
            
            # Use selling price as total amount
            total_amount = selling_price
            
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
                'amount': amount,  # Original plan amount
                'sellingPrice': selling_price,
                'costPrice': cost_price,
                'margin': margin,
                'userTier': user_tier,
                'pricingStrategy': pricing_result['strategy_used'],
                'savingsMessage': savings_message,
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
            
            # Deduct selling price from wallet
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
            
            # Record corporate revenue (margin earned)
            if margin > 0:
                corporate_revenue = {
                    '_id': ObjectId(),
                    'type': 'VAS_MARGIN',
                    'category': 'DATA_MARGIN',
                    'amount': margin,
                    'userId': ObjectId(user_id),
                    'relatedTransaction': str(transaction_id),
                    'description': f'Data margin from user {user_id} - {network} {data_plan_name}',
                    'status': 'RECORDED',
                    'createdAt': datetime.utcnow(),
                    'metadata': {
                        'network': network,
                        'planName': data_plan_name,
                        'planId': data_plan_id,
                        'originalAmount': amount,
                        'sellingPrice': selling_price,
                        'costPrice': cost_price,
                        'userTier': user_tier,
                        'strategy': pricing_result['strategy_used'],
                        'emergencyPricing': is_emergency_pricing
                    }
                }
                mongo.db.corporate_revenue.insert_one(corporate_revenue)
                print(f'💰 Corporate revenue recorded: ₦{margin} from data sale to user {user_id}')
            
            # 🚨 TAG EMERGENCY TRANSACTIONS FOR RECOVERY
            if is_emergency_pricing:
                try:
                    emergency_tag_id = tag_emergency_transaction(
                        mongo.db, str(transaction_id), cost_price, 'data', network
                    )
                    print(f'🏥 Emergency transaction tagged for recovery: {emergency_tag_id}')
                    
                    # Create immediate notification about emergency pricing
                    create_user_notification(
                        mongo=mongo.db,
                        user_id=user_id,
                        category='system',
                        title='⚡ Emergency Pricing Used',
                        body=f'Your {network} {data_plan_name} purchase used emergency pricing during system maintenance. We\'ll automatically adjust any overcharges within 24 hours.',
                        related_id=str(transaction_id),
                        metadata={
                            'emergency_cost': cost_price,
                            'transaction_id': str(transaction_id),
                            'recovery_expected': True,
                            'plan_name': data_plan_name
                        },
                        priority='high'
                    )
                    
                except Exception as e:
                    print(f'⚠️ Failed to tag emergency transaction: {str(e)}')
                    # Don't fail the transaction if tagging fails
            
            # 🎯 PASSIVE RETENTION ENGINE: Generate retention-focused description
            base_description = f'Data - {network} {data_plan_name} for {phone_number[-4:]}****'
            discount_applied = amount - selling_price  # Calculate actual discount
            retention_description = generate_retention_description(
                base_description,
                savings_message,
                user_tier,
                discount_applied
            )
            
            # Auto-create expense entry (auto-bookkeeping)
            expense_entry = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'amount': selling_price,  # Record selling price as expense
                'category': 'Utilities',
                'description': retention_description,  # 🎯 Use retention-focused description
                'date': datetime.utcnow(),
                'tags': ['VAS', 'Data', network],
                'vasTransactionId': transaction_id,
                'metadata': {
                    'planName': data_plan_name,
                    'originalAmount': amount,
                    'actualCost': selling_price,
                    'userTier': user_tier,
                    'savingsMessage': savings_message,
                    'discountApplied': discount_applied,  # Track discount for analytics
                    'retentionMessaging': True  # Flag for retention analytics
                },
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.expenses.insert_one(expense_entry)
            
            # 🎯 RETENTION DATA for Frontend Trust Building
            retention_data = {
                'userTier': user_tier,
                'originalPrice': amount,
                'finalPrice': selling_price,
                'totalSaved': discount_applied,
                'savingsMessage': savings_message,
                'subscriptionROI': {
                    'tierName': user_tier.title() if user_tier != 'basic' else 'Basic',
                    'annualCost': 25000 if user_tier == 'gold' else (10000 if user_tier == 'premium' else 0),
                    'monthlyProgress': f"You've saved ₦{discount_applied:.0f} this transaction",
                    'loyaltyNudge': f"Your {user_tier.title()} subscription is working!" if user_tier != 'basic' else "Upgrade to Premium to start saving on every purchase!"
                },
                'retentionDescription': retention_description,
                'emergencyPricing': is_emergency_pricing,
                'priceProtectionActive': is_emergency_pricing,
                'planDetails': {
                    'network': network,
                    'planName': data_plan_name,
                    'validity': '30 days'  # Could be dynamic based on plan
                }
            }

            print(f'✅ Data purchase complete: User {user_id}, Plan: {data_plan_name}, Original: ₦{amount}, Charged: ₦{selling_price}, Margin: ₦{margin}, Provider: {provider}')
            
            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(transaction_id),
                    'requestId': request_id,
                    'planName': data_plan_name,
                    'originalAmount': amount,
                    'amountCharged': selling_price,
                    'margin': margin,
                    'newBalance': new_balance,
                    'provider': provider,
                    'userTier': user_tier,
                    'savingsMessage': savings_message,
                    'pricingStrategy': pricing_result['strategy_used'],
                    'expenseRecorded': True,
                    'retentionData': retention_data  # 🎯 NEW: Frontend trust data
                },
                'message': f'Data purchased successfully! {savings_message}' if savings_message else 'Data purchased successfully!'
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
    
    @vas_bp.route('/reserved-account/create', methods=['POST'])
    @token_required
    def create_reserved_account(current_user):
        """Create a basic reserved account for the user (without KYC)"""
        try:
            user_id = str(current_user['_id'])
            
            # Check if wallet already exists
            existing_wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if existing_wallet:
                return jsonify({
                    'success': True,
                    'data': {
                        'accountNumber': existing_wallet.get('accounts', [{}])[0].get('accountNumber', ''),
                        'accountName': existing_wallet.get('accounts', [{}])[0].get('accountName', ''),
                        'bankName': existing_wallet.get('accounts', [{}])[0].get('bankName', 'Wema Bank'),
                        'bankCode': existing_wallet.get('accounts', [{}])[0].get('bankCode', '035'),
                        'createdAt': existing_wallet.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                    },
                    'message': 'Reserved account already exists'
                }), 200
            
            # Get Monnify access token
            access_token = call_monnify_auth()
            
            # Create basic reserved account (Tier 1 - no BVN/NIN required)
            account_data = {
                'accountReference': f'FICORE_{user_id}',
                'accountName': current_user.get('fullName', f"FiCore User {user_id[:8]}"),
                'currencyCode': 'NGN',
                'contractCode': MONNIFY_CONTRACT_CODE,
                'customerEmail': current_user.get('email', ''),
                'customerName': current_user.get('fullName', f"FiCore User {user_id[:8]}"),
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
            
            # Create wallet record
            wallet_data = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'balance': 0.0,
                'accountReference': van_data['accountReference'],
                'contractCode': van_data['contractCode'],
                'accounts': van_data['accounts'],
                'status': 'ACTIVE',
                'tier': 'TIER_1',  # Basic account without KYC
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.vas_wallets.insert_one(wallet_data)
            
            print(f'✅ Basic reserved account created for user {user_id}')
            
            # Return the first account details
            first_account = van_data['accounts'][0] if van_data['accounts'] else {}
            
            return jsonify({
                'success': True,
                'data': {
                    'accountNumber': first_account.get('accountNumber', ''),
                    'accountName': first_account.get('accountName', ''),
                    'bankName': first_account.get('bankName', 'Wema Bank'),
                    'bankCode': first_account.get('bankCode', '035'),
                    'createdAt': wallet_data['createdAt'].isoformat() + 'Z'
                },
                'message': 'Reserved account created successfully'
            }), 201
            
        except Exception as e:
            print(f'❌ Error creating reserved account: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to create reserved account',
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
            
            # Get the first account details (most wallets have one account)
            accounts = wallet.get('accounts', [])
            first_account = accounts[0] if accounts else {}
            
            return jsonify({
                'success': True,
                'data': {
                    'accountNumber': first_account.get('accountNumber', ''),
                    'accountName': first_account.get('accountName', ''),
                    'bankName': first_account.get('bankName', 'Wema Bank'),
                    'bankCode': first_account.get('bankCode', '035'),
                    'accountReference': wallet.get('accountReference', ''),
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
