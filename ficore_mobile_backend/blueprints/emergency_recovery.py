"""
Emergency Recovery Endpoint - Restore deleted wallets
TEMPORARY: Remove this file after recovery is complete
"""
from flask import Blueprint, jsonify, request
from bson import ObjectId
from datetime import datetime
import requests
import os

def init_emergency_recovery_blueprint(mongo, token_required, admin_required):
    recovery_bp = Blueprint('emergency_recovery', __name__, url_prefix='/api/emergency')
    
    MONNIFY_API_KEY = os.environ.get('MONNIFY_API_KEY', '')
    MONNIFY_SECRET_KEY = os.environ.get('MONNIFY_SECRET_KEY', '')
    MONNIFY_BASE_URL = os.environ.get('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')
    
    @recovery_bp.route('/recover-all-wallets', methods=['POST'])
    @token_required
    @admin_required
    def recover_all_wallets(current_user):
        """
        Emergency endpoint to recover all deleted wallets
        Admin access required (checks current_user['role'] == 'admin')
        """
        try:
            print(f"\n{'='*80}")
            print(f"EMERGENCY WALLET RECOVERY STARTED")
            print(f"Initiated by: {current_user.get('email')}")
            print(f"{'='*80}")
            
            # Get Monnify auth token
            monnify_token = None
            try:
                auth_response = requests.post(
                    f'{MONNIFY_BASE_URL}/api/v1/auth/login',
                    auth=(MONNIFY_API_KEY, MONNIFY_SECRET_KEY),
                    headers={'Content-Type': 'application/json'},
                    timeout=30
                )
                if auth_response.status_code == 200:
                    monnify_token = auth_response.json()['responseBody']['accessToken']
                    print(f"✅ Monnify authenticated")
            except Exception as e:
                print(f"⚠️ Monnify auth failed: {e}")
            
            # Find all users with VAS transactions
            user_ids_with_txns = mongo.db.vas_transactions.distinct('userId')
            print(f"Found {len(user_ids_with_txns)} users with VAS transactions")
            
            # Check which ones don't have wallets or have empty accounts
            users_needing_recovery = []
            for user_id in user_ids_with_txns:
                wallet = mongo.db.vas_wallets.find_one({'userId': user_id})
                if not wallet:
                    users_needing_recovery.append({'user_id': user_id, 'issue': 'missing_wallet'})
                elif not wallet.get('accounts') or len(wallet.get('accounts', [])) == 0:
                    users_needing_recovery.append({'user_id': user_id, 'issue': 'missing_accounts', 'wallet_id': wallet['_id']})
            
            print(f"Users needing recovery: {len(users_needing_recovery)}")
            
            recovered = 0
            failed = 0
            results = []
            
            for item in users_needing_recovery:
                try:
                    user_id = item['user_id']
                    user_id_str = str(user_id)
                    issue = item['issue']
                    
                    # Get user info
                    user = mongo.db.users.find_one({'_id': user_id})
                    if not user:
                        failed += 1
                        continue
                    
                    email = user.get('email', 'unknown')
                    print(f"\nRecovering: {email} ({issue})")
                    
                    # Calculate balance from transactions
                    txns = list(mongo.db.vas_transactions.find({'userId': user_id}))
                    balance = 0.0
                    
                    for t in txns:
                        status = t.get('status', '').upper()
                        if status in ['COMPLETED', 'SUCCESS', 'SUCCESSFUL']:
                            if t.get('type') == 'WALLET_FUNDING':
                                balance += t.get('amount', 0)
                            elif t.get('type') in ['AIRTIME', 'DATA', 'BILLS']:
                                balance -= t.get('amount', 0)
                    
                    # Try to fetch accounts from Monnify
                    accounts = []
                    if monnify_token:
                        try:
                            fetch_response = requests.get(
                                f'{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts/{user_id_str}',
                                headers={'Authorization': f'Bearer {monnify_token}'},
                                timeout=30
                            )
                            
                            if fetch_response.status_code == 200:
                                fetch_data = fetch_response.json()
                                if fetch_data.get('requestSuccessful'):
                                    accounts = fetch_data['responseBody'].get('accounts', [])
                                    print(f"  ✅ Fetched {len(accounts)} accounts")
                        except Exception as e:
                            print(f"  ⚠️ Monnify fetch failed: {e}")
                    
                    if issue == 'missing_wallet':
                        # Create new wallet
                        new_wallet = {
                            '_id': ObjectId(),
                            'userId': user_id,
                            'balance': balance,
                            'reservedAmount': 0.0,
                            'accountReference': user_id_str,
                            'accountName': f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(),
                            'accounts': accounts,
                            'status': 'active',
                            'tier': 'TIER_1',
                            'kycTier': 1,
                            'kycVerified': False,
                            'kycStatus': 'pending',
                            'createdAt': datetime.utcnow(),
                            'updatedAt': datetime.utcnow(),
                            'recoveredAt': datetime.utcnow()
                        }
                        
                        mongo.db.vas_wallets.insert_one(new_wallet)
                        
                        # Update transactions
                        mongo.db.vas_transactions.update_many(
                            {'userId': user_id},
                            {'$set': {'walletId': new_wallet['_id']}}
                        )
                        
                        print(f"  ✅ Wallet created")
                    else:
                        # Update existing wallet with accounts and balance
                        mongo.db.vas_wallets.update_one(
                            {'_id': item['wallet_id']},
                            {'$set': {
                                'accounts': accounts,
                                'balance': balance,
                                'updatedAt': datetime.utcnow(),
                                'recoveredAt': datetime.utcnow()
                            }}
                        )
                        print(f"  ✅ Wallet updated")
                    
                    recovered += 1
                    results.append({
                        'email': email,
                        'issue': issue,
                        'balance': balance,
                        'accounts': len(accounts),
                        'status': 'recovered'
                    })
                    
                except Exception as e:
                    print(f"  ❌ Failed: {e}")
                    failed += 1
                    results.append({
                        'email': email if 'email' in locals() else 'unknown',
                        'status': 'failed',
                        'error': str(e)
                    })
            
            # Log recovery action
            mongo.db.admin_actions.insert_one({
                'adminId': current_user['_id'],
                'adminEmail': current_user['email'],
                'action': 'EMERGENCY_WALLET_RECOVERY',
                'timestamp': datetime.utcnow(),
                'details': {
                    'recovered': recovered,
                    'failed': failed,
                    'total_affected': len(users_needing_recovery)
                },
                'reason': 'Emergency recovery after wallet deletion bug'
            })
            
            print(f"\n{'='*80}")
            print(f"RECOVERY COMPLETE: {recovered} recovered, {failed} failed")
            print(f"{'='*80}")
            
            return jsonify({
                'success': True,
                'message': f'Recovery complete: {recovered} wallets recovered, {failed} failed',
                'data': {
                    'recovered': recovered,
                    'failed': failed,
                    'total': len(users_needing_recovery),
                    'results': results
                }
            }), 200
            
        except Exception as e:
            print(f"ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                'success': False,
                'message': f'Recovery failed: {str(e)}'
            }), 500
    
    return recovery_bp
