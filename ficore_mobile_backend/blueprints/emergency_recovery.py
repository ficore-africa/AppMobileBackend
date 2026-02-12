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
    
    @recovery_bp.route('/restore-specific-wallets', methods=['POST'])
    @token_required
    @admin_required
    def restore_specific_wallets(current_user):
        """
        Restore wallets for specific users who had Monnify accounts created before the bug
        Admin access required
        """
        try:
            print(f"\n{'='*80}")
            print(f"RESTORING SPECIFIC WALLETS WITH EXISTING MONNIFY ACCOUNTS")
            print(f"Initiated by: {current_user.get('email')}")
            print(f"{'='*80}")
            
            # Get Monnify auth token
            print("\n🔐 Authenticating with Monnify...")
            auth_response = requests.post(
                f'{MONNIFY_BASE_URL}/api/v1/auth/login',
                auth=(MONNIFY_API_KEY, MONNIFY_SECRET_KEY),
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if auth_response.status_code != 200:
                return jsonify({
                    'success': False,
                    'message': f'Monnify authentication failed: {auth_response.text}'
                }), 500
            
            access_token = auth_response.json()['responseBody']['accessToken']
            print("✅ Authenticated with Monnify")
            
            # The 3 users to restore
            users_to_restore = [
                {
                    'email': 'adamumuhammad952@gmail.com',
                    'user_id': ObjectId('697908f9fbf1be25a9bcfd16'),
                    'account_reference': '697908f9fbf1be25a9bcfd16'
                },
                {
                    'email': 'khadijahibrahimgmb@gmail.com',
                    'user_id': ObjectId('6977c7ef467f4945c8ab426d'),
                    'account_reference': 'FICORE_6977c7ef467f4945c8ab426d'
                },
                {
                    'email': '0kalshingi@gmail.com',
                    'user_id': ObjectId('690e6b3436344ee7516e32e2'),
                    'account_reference': '690e6b3436344ee7516e32e2'
                }
            ]
            
            restored_count = 0
            failed_count = 0
            results = []
            
            for user_info in users_to_restore:
                print(f"\n{'='*80}")
                print(f"Restoring: {user_info['email']}")
                print('='*80)
                
                try:
                    # Check if wallet already exists
                    existing_wallet = mongo.db.vas_wallets.find_one({'userId': user_info['user_id']})
                    if existing_wallet:
                        print(f"⚠️  Wallet already exists, skipping...")
                        results.append({
                            'email': user_info['email'],
                            'status': 'skipped',
                            'reason': 'Wallet already exists'
                        })
                        continue
                    
                    # Fetch account from Monnify
                    print(f"📡 Fetching account from Monnify (reference: {user_info['account_reference']})...")
                    fetch_response = requests.get(
                        f"{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts/{user_info['account_reference']}",
                        headers={'Authorization': f'Bearer {access_token}'},
                        timeout=30
                    )
                    
                    if fetch_response.status_code != 200:
                        print(f"❌ Failed to fetch account: {fetch_response.text}")
                        failed_count += 1
                        results.append({
                            'email': user_info['email'],
                            'status': 'failed',
                            'error': f'Failed to fetch from Monnify: {fetch_response.text}'
                        })
                        continue
                    
                    fetch_data = fetch_response.json()
                    if not fetch_data.get('requestSuccessful'):
                        print(f"❌ Monnify error: {fetch_data.get('responseMessage')}")
                        failed_count += 1
                        results.append({
                            'email': user_info['email'],
                            'status': 'failed',
                            'error': fetch_data.get('responseMessage')
                        })
                        continue
                    
                    monnify_data = fetch_data['responseBody']
                    accounts = monnify_data.get('accounts', [])
                    print(f"✅ Fetched {len(accounts)} account(s) from Monnify")
                    for acc in accounts:
                        print(f"   - {acc.get('bankName')} | {acc.get('accountNumber')}")
                    
                    # Get user details
                    user = mongo.db.users.find_one({'_id': user_info['user_id']})
                    if not user:
                        print(f"❌ User not found in database")
                        failed_count += 1
                        results.append({
                            'email': user_info['email'],
                            'status': 'failed',
                            'error': 'User not found in database'
                        })
                        continue
                    
                    # Create wallet record
                    wallet = {
                        '_id': ObjectId(),
                        'userId': user_info['user_id'],
                        'balance': 0.0,  # Start with 0 balance (no transactions yet)
                        'accountReference': monnify_data.get('accountReference'),
                        'accountName': monnify_data.get('accountName'),
                        'accounts': accounts,
                        'status': 'active',
                        'tier': 'TIER_1',
                        'kycTier': 1,
                        'kycVerified': False,
                        'kycStatus': 'pending',
                        'createdAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow(),
                        'restoredFromMonnify': True,  # Flag to indicate this was restored
                        'restoredAt': datetime.utcnow()
                    }
                    
                    # Insert wallet
                    mongo.db.vas_wallets.insert_one(wallet)
                    print(f"✅ Wallet created successfully")
                    print(f"   Balance: ₦{wallet['balance']:,.2f}")
                    print(f"   Accounts: {len(accounts)}")
                    print(f"   Status: {wallet['status']}")
                    
                    restored_count += 1
                    results.append({
                        'email': user_info['email'],
                        'status': 'restored',
                        'balance': wallet['balance'],
                        'accounts': len(accounts),
                        'accountReference': wallet['accountReference']
                    })
                    
                except Exception as e:
                    print(f"❌ Error restoring {user_info['email']}: {str(e)}")
                    failed_count += 1
                    results.append({
                        'email': user_info['email'],
                        'status': 'failed',
                        'error': str(e)
                    })
            
            # Log recovery action
            mongo.db.admin_actions.insert_one({
                'adminId': current_user['_id'],
                'adminEmail': current_user['email'],
                'action': 'RESTORE_SPECIFIC_WALLETS',
                'timestamp': datetime.utcnow(),
                'details': {
                    'restored': restored_count,
                    'failed': failed_count,
                    'total': len(users_to_restore)
                },
                'reason': 'Restore 3 wallets with existing Monnify accounts'
            })
            
            print(f"\n{'='*80}")
            print(f"RESTORATION COMPLETE")
            print(f"{'='*80}")
            print(f"✅ Restored: {restored_count} wallets")
            print(f"❌ Failed: {failed_count} wallets")
            
            return jsonify({
                'success': True,
                'message': f'Restoration complete: {restored_count} wallets restored, {failed_count} failed',
                'data': {
                    'restored': restored_count,
                    'failed': failed_count,
                    'total': len(users_to_restore),
                    'results': results
                }
            }), 200
            
        except Exception as e:
            print(f"ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                'success': False,
                'message': f'Restoration failed: {str(e)}'
            }), 500
    
    return recovery_bp
