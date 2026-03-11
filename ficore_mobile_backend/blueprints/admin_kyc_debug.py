"""
Admin KYC Debug Blueprint

Provides endpoints for debugging KYC verification status issues.
Helps diagnose why users show "Basic KYC" instead of "Verified".
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId

def init_admin_kyc_debug_blueprint(mongo, token_required, admin_required):
    """Initialize admin KYC debug blueprint with dependencies"""
    
    admin_kyc_debug_bp = Blueprint('admin_kyc_debug', __name__)

    @admin_kyc_debug_bp.route('/debug/kyc-status/<user_identifier>', methods=['GET'])
    @token_required
    @admin_required
    def debug_user_kyc_status(current_user, user_identifier):
        """
        Debug a user's KYC status across all collections
        
        Args:
            user_identifier: Email, phone number, or user ID
        """
        try:
            # Find user by email, phone, or ID
            user_query = {}
            if '@' in user_identifier:
                user_query = {'email': user_identifier}
            elif user_identifier.isdigit() and len(user_identifier) >= 10:
                user_query = {'phoneNumber': user_identifier}
            else:
                try:
                    user_query = {'_id': ObjectId(user_identifier)}
                except:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid user identifier. Use email, phone, or ObjectId'
                    }), 400
            
            # 1. Check users collection
            user = mongo.db.users.find_one(user_query)
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            user_id = user['_id']
            
            # Extract user KYC fields
            user_data = {
                'id': str(user_id),
                'name': f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(),
                'email': user.get('email'),
                'phoneNumber': user.get('phoneNumber'),
                'bvn': user.get('bvn'),
                'nin': user.get('nin'),
                'kycStatus': user.get('kycStatus'),
                'bvnVerified': user.get('bvnVerified'),
                'ninVerified': user.get('ninVerified'),
                'verificationStatus': user.get('verificationStatus'),
                'kycVerifiedAt': user.get('kycVerifiedAt').isoformat() + 'Z' if user.get('kycVerifiedAt') else None,
                'createdAt': user.get('createdAt').isoformat() + 'Z' if user.get('createdAt') else None,
                'updatedAt': user.get('updatedAt').isoformat() + 'Z' if user.get('updatedAt') else None,
            }
            
            # 2. Check vas_wallets collection
            wallet = mongo.db.vas_wallets.find_one({'userId': user_id})
            wallet_data = None
            if wallet:
                wallet_data = {
                    'id': str(wallet['_id']),
                    'balance': wallet.get('balance', 0),
                    'kycStatus': wallet.get('kycStatus'),
                    'kycTier': wallet.get('kycTier'),
                    'tier': wallet.get('tier'),
                    'kycVerified': wallet.get('kycVerified'),
                    'bvnVerified': wallet.get('bvnVerified'),
                    'ninVerified': wallet.get('ninVerified'),
                    'verifiedName': wallet.get('verifiedName'),
                    'verificationDate': wallet.get('verificationDate').isoformat() + 'Z' if wallet.get('verificationDate') else None,
                    'isActivated': wallet.get('isActivated'),
                    'status': wallet.get('status'),
                    'createdAt': wallet.get('createdAt').isoformat() + 'Z' if wallet.get('createdAt') else None,
                    'updatedAt': wallet.get('updatedAt').isoformat() + 'Z' if wallet.get('updatedAt') else None,
                }
            
            # 3. Check kyc_verifications collection
            verifications = list(mongo.db.kyc_verifications.find({'userId': user_id}).sort('createdAt', -1))
            verification_data = []
            for verification in verifications:
                verification_data.append({
                    'id': str(verification['_id']),
                    'status': verification.get('status'),
                    'bvn': verification.get('bvn'),
                    'nin': verification.get('nin'),
                    'verifiedName': verification.get('verifiedName'),
                    'createdAt': verification.get('createdAt').isoformat() + 'Z' if verification.get('createdAt') else None,
                    'updatedAt': verification.get('updatedAt').isoformat() + 'Z' if verification.get('updatedAt') else None,
                    'expiresAt': verification.get('expiresAt').isoformat() + 'Z' if verification.get('expiresAt') else None,
                })
            
            # 4. Analysis
            has_user_bvn_nin = user_data['bvn'] and user_data['nin']
            has_wallet_verification = wallet_data and wallet_data.get('bvnVerified') and wallet_data.get('ninVerified')
            has_confirmed_verification = any(v.get('status') == 'confirmed' for v in verifications)
            
            # Determine expected tier
            if has_user_bvn_nin and has_wallet_verification:
                expected_tier = "TIER_2"
                expected_display = "Verified"
            elif wallet_data:
                expected_tier = "TIER_1"
                expected_display = "Basic"
            else:
                expected_tier = "TIER_1"  # Default is TIER_1, not TIER_0
                expected_display = "No Wallet"
            
            # Check for issues
            issues = []
            
            if has_user_bvn_nin and not has_wallet_verification:
                issues.append("User has BVN/NIN but wallet doesn't show as verified")
            
            if wallet_data and wallet_data.get('kycTier') != 2 and has_user_bvn_nin:
                issues.append(f"User has BVN/NIN but wallet kycTier is {wallet_data.get('kycTier')} instead of 2")
            
            if wallet_data and wallet_data.get('tier') != 'TIER_2' and has_user_bvn_nin:
                issues.append(f"User has BVN/NIN but wallet tier is {wallet_data.get('tier')} instead of TIER_2")
            
            if not has_confirmed_verification and has_user_bvn_nin:
                issues.append("User has BVN/NIN but no confirmed verification record")
            
            if not wallet_data and has_user_bvn_nin:
                issues.append("User has BVN/NIN but no VAS wallet")
            
            # Recommendations
            recommendations = []
            
            if has_user_bvn_nin and wallet_data:
                if wallet_data.get('kycTier') != 2:
                    recommendations.append("Update vas_wallets.kycTier to 2")
                if wallet_data.get('tier') != 'TIER_2':
                    recommendations.append("Update vas_wallets.tier to 'TIER_2'")
                if not wallet_data.get('kycVerified'):
                    recommendations.append("Update vas_wallets.kycVerified to true")
                if not wallet_data.get('bvnVerified'):
                    recommendations.append("Update vas_wallets.bvnVerified to true")
                if not wallet_data.get('ninVerified'):
                    recommendations.append("Update vas_wallets.ninVerified to true")
                if wallet_data.get('kycStatus') != 'verified':
                    recommendations.append("Update vas_wallets.kycStatus to 'verified'")
            
            return jsonify({
                'success': True,
                'data': {
                    'user': user_data,
                    'wallet': wallet_data,
                    'verifications': verification_data,
                    'analysis': {
                        'hasUserBvnNin': has_user_bvn_nin,
                        'hasWalletVerification': has_wallet_verification,
                        'hasConfirmedVerification': has_confirmed_verification,
                        'expectedTier': expected_tier,
                        'expectedDisplay': expected_display,
                        'issues': issues,
                        'recommendations': recommendations,
                        'shouldShowVerified': has_user_bvn_nin and has_wallet_verification,
                    }
                },
                'message': f'KYC status debug for {user_data["email"]}'
            })
            
        except Exception as e:
            print(f'Error debugging KYC status: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to debug KYC status',
                'error': str(e)
            }), 500

    @admin_kyc_debug_bp.route('/debug/fix-kyc-status/<user_identifier>', methods=['POST'])
    @token_required
    @admin_required
    def fix_user_kyc_status(current_user, user_identifier):
        """
        Fix a user's KYC status inconsistencies
        
        Args:
            user_identifier: Email, phone number, or user ID
        """
        try:
            # Find user
            user_query = {}
            if '@' in user_identifier:
                user_query = {'email': user_identifier}
            elif user_identifier.isdigit() and len(user_identifier) >= 10:
                user_query = {'phoneNumber': user_identifier}
            else:
                try:
                    user_query = {'_id': ObjectId(user_identifier)}
                except:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid user identifier'
                    }), 400
            
            user = mongo.db.users.find_one(user_query)
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            user_id = user['_id']
            bvn = user.get('bvn')
            nin = user.get('nin')
            
            if not (bvn and nin):
                return jsonify({
                    'success': False,
                    'message': 'User does not have both BVN and NIN. Cannot mark as verified.'
                }), 400
            
            # Check VAS wallet
            wallet = mongo.db.vas_wallets.find_one({'userId': user_id})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'No VAS wallet found. User needs to create wallet first.'
                }), 400
            
            # Prepare updates
            current_time = datetime.utcnow()
            
            # Update users collection
            users_updates = {
                'kycStatus': 'verified',
                'bvnVerified': True,
                'ninVerified': True,
                'verificationStatus': 'VERIFIED',
                'kycVerifiedAt': current_time,
                'updatedAt': current_time
            }
            
            # Update vas_wallets collection
            wallet_updates = {
                'kycStatus': 'verified',
                'kycTier': 2,
                'tier': 'TIER_2',
                'kycVerified': True,
                'bvnVerified': True,
                'ninVerified': True,
                'verificationDate': current_time,
                'updatedAt': current_time
            }
            
            # Apply updates
            users_result = mongo.db.users.update_one(
                {'_id': user_id},
                {'$set': users_updates}
            )
            
            wallet_result = mongo.db.vas_wallets.update_one(
                {'userId': user_id},
                {'$set': wallet_updates}
            )
            
            # Log admin action
            admin_action = {
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user.get('email', 'admin'),
                'action': 'fix_kyc_status',
                'targetUserId': user_id,
                'targetUserEmail': user.get('email'),
                'reason': 'Fixed KYC status inconsistency - user had BVN/NIN but showed as Basic instead of Verified',
                'timestamp': current_time,
                'details': {
                    'usersUpdated': users_result.modified_count > 0,
                    'walletUpdated': wallet_result.modified_count > 0,
                    'updatedFields': {
                        'users': list(users_updates.keys()),
                        'vas_wallets': list(wallet_updates.keys())
                    }
                }
            }
            
            mongo.db.admin_actions.insert_one(admin_action)
            
            return jsonify({
                'success': True,
                'data': {
                    'usersUpdated': users_result.modified_count > 0,
                    'walletUpdated': wallet_result.modified_count > 0,
                    'adminActionLogged': True
                },
                'message': f'KYC status fixed for {user.get("email")}. User should now show as Verified.'
            })
            
        except Exception as e:
            print(f'Error fixing KYC status: {e}')
            return jsonify({
                'success': False,
                'message': 'Failed to fix KYC status',
                'error': str(e)
            }), 500

    return admin_kyc_debug_bp