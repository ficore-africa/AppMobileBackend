"""
Referral System API Endpoints
Created: February 4, 2026
Purpose: Handle referral stats, validation, and partner management
"""
from flask import Blueprint, jsonify, request
from bson import ObjectId
from datetime import datetime, timedelta
from functools import wraps

referrals_bp = Blueprint('referrals', __name__, url_prefix='/api/referrals')

def init_referrals_blueprint(mongo):
    """Initialize the referrals blueprint with database"""
    referrals_bp.mongo = mongo
    return referrals_bp

# Token authentication decorator (imported from utils)
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(' ')[1] if ' ' in request.headers['Authorization'] else request.headers['Authorization']
        
        if not token:
            return jsonify({'success': False, 'message': 'Token is missing'}), 401
        
        try:
            import jwt
            from flask import current_app
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = referrals_bp.mongo.db.users.find_one({'_id': ObjectId(data['user_id'])})
            if not current_user:
                return jsonify({'success': False, 'message': 'User not found'}), 401
        except Exception as e:
            return jsonify({'success': False, 'message': 'Token is invalid'}), 401
        
        return f(current_user, *args, **kwargs)
    
    return decorated

@referrals_bp.route('/stats', methods=['GET'])
@token_required
def get_referral_stats(current_user):
    """
    Get referral statistics for current user.
    Returns: referral code, count, earnings, pending payouts, etc.
    """
    try:
        user_id = current_user['_id']
        
        # Get user's referral info
        user = referrals_bp.mongo.db.users.find_one({"_id": user_id})
        
        # Get all referrals made by this user
        referrals = list(referrals_bp.mongo.db.referrals.find({"referrerId": user_id}))
        
        # Count by status
        pending_count = len([r for r in referrals if r['status'] == 'pending_deposit'])
        active_count = len([r for r in referrals if r['status'] == 'active'])
        qualified_count = len([r for r in referrals if r['status'] == 'qualified'])
        
        # Get payout summary
        total_earned = user.get('referralEarnings', 0.0)
        pending_balance = user.get('pendingCommissionBalance', 0.0)
        withdrawable_balance = user.get('withdrawableCommissionBalance', 0.0)
        
        # Get recent payouts
        recent_payouts = list(referrals_bp.mongo.db.referral_payouts.find(
            {"referrerId": user_id}
        ).sort("createdAt", -1).limit(10))
        
        # Format payouts for response
        formatted_payouts = []
        for payout in recent_payouts:
            referee = referrals_bp.mongo.db.users.find_one({"_id": payout['refereeId']})
            formatted_payouts.append({
                "id": str(payout['_id']),
                "type": payout['type'],
                "amount": payout['amount'],
                "status": payout['status'],
                "refereeName": referee.get('displayName', 'Unknown') if referee else 'Unknown',
                "createdAt": payout['createdAt'].isoformat(),
                "vestingEndDate": payout['vestingEndDate'].isoformat() if payout.get('vestingEndDate') else None
            })
        
        return jsonify({
            "success": True,
            "data": {
                "referralCode": user.get('referralCode'),
                "totalReferrals": len(referrals),
                "pendingReferrals": pending_count,
                "activeReferrals": active_count,
                "qualifiedReferrals": qualified_count,
                "totalEarned": total_earned,
                "pendingBalance": pending_balance,
                "withdrawableBalance": withdrawable_balance,
                "recentPayouts": formatted_payouts,
                "shareMessage": generate_share_message(user.get('referralCode'), user.get('displayName'))
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Get referral stats error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@referrals_bp.route('/my-stats', methods=['GET'])
@token_required
def get_my_referral_stats(current_user):
    """
    Get current user's referral stats for Partner Hub screen.
    Returns: earnings, balances, referral counts, and recent activity.
    
    This endpoint is optimized for the mobile app Partner Hub display.
    """
    try:
        user_id = current_user['_id']
        
        # Get user's referral info
        user = referrals_bp.mongo.db.users.find_one({"_id": user_id})
        
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404
        
        # Get referral code (or generate if missing)
        referral_code = user.get('referralCode')
        if not referral_code:
            # Generate code if user doesn't have one yet
            from .auth import generate_referral_code
            referral_code = generate_referral_code(user.get('firstName', 'USER'), user.get('phone', '0000000000'))
            referrals_bp.mongo.db.users.update_one(
                {"_id": user_id},
                {"$set": {"referralCode": referral_code}}
            )
        
        # Get all referrals made by this user
        referrals = list(referrals_bp.mongo.db.referrals.find({"referrerId": user_id}))
        
        # Count active referrals (users who made first deposit)
        active_referrals = len([r for r in referrals if r['status'] in ['active', 'qualified']])
        
        # Get earnings from user document
        total_earnings = user.get('referralEarnings', 0.0)
        pending_balance = user.get('pendingCommissionBalance', 0.0)
        withdrawable_balance = user.get('withdrawableCommissionBalance', 0.0)
        
        # Get recent payouts for activity list
        recent_payouts = list(referrals_bp.mongo.db.referral_payouts.find(
            {"referrerId": user_id}
        ).sort("createdAt", -1).limit(5))
        
        # Format recent earnings for display
        recent_earnings = []
        for payout in recent_payouts:
            # Get referee info
            referee = referrals_bp.mongo.db.users.find_one({"_id": payout['refereeId']})
            referee_name = referee.get('displayName', 'User') if referee else 'User'
            
            # Calculate time ago
            time_ago = calculate_time_ago(payout['createdAt'])
            
            # Determine type and description
            payout_type = payout.get('type', 'UNKNOWN')
            if payout_type == 'SUBSCRIPTION_COMMISSION':
                type_key = 'subscription'
                description = f"{referee_name} subscribed"
            elif payout_type == 'VAS_SHARE':
                type_key = 'vas'
                description = f"{referee_name} bought airtime/data"
            else:
                type_key = 'other'
                description = f"{referee_name}"
            
            recent_earnings.append({
                "amount": payout['amount'],
                "type": type_key,
                "userName": referee_name,
                "timeAgo": time_ago,
                "description": description
            })
        
        return jsonify({
            "success": True,
            "data": {
                "referralCode": referral_code,
                "totalEarnings": total_earnings,
                "pendingBalance": pending_balance,
                "withdrawableBalance": withdrawable_balance,
                "totalReferrals": len(referrals),
                "activeReferrals": active_referrals,
                "recentEarnings": recent_earnings
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Get my stats error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": "Failed to load referral stats"}), 500

def calculate_time_ago(timestamp):
    """Calculate human-readable time ago string."""
    try:
        now = datetime.utcnow()
        diff = now - timestamp
        
        seconds = diff.total_seconds()
        
        if seconds < 60:
            return "Just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}m" if minutes > 1 else "1m"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h" if hours > 1 else "1h"
        elif seconds < 604800:
            days = int(seconds / 86400)
            return f"{days}d" if days > 1 else "1d"
        elif seconds < 2592000:
            weeks = int(seconds / 604800)
            return f"{weeks}w" if weeks > 1 else "1w"
        else:
            months = int(seconds / 2592000)
            return f"{months}mo" if months > 1 else "1mo"
    except:
        return "Recently"

def generate_share_message(referral_code, user_name):
    """Generate WhatsApp share message."""
    return f"""🎉 Join me on FiCore Africa!

I'm using FiCore to manage my business finances, track expenses, and buy airtime/data at great prices.

Use my referral code: *{referral_code}*

You'll get:
✅ ₦30 deposit fee waived
✅ 5 Free FiCore Credits
✅ Professional financial tools

Download: https://play.google.com/store/apps/details?id=com.ficoreafrica.app

- {user_name}"""

@referrals_bp.route('/validate-code', methods=['GET', 'POST'])
def validate_referral_code():
    """
    Validate a referral code (public endpoint for registration screen).
    Supports both GET (with query param) and POST (with JSON body).
    """
    try:
        # Support both GET and POST
        if request.method == 'GET':
            code = request.args.get('code', '').strip().upper()
        else:
            data = request.get_json()
            code = data.get('referralCode', '').strip().upper()
        
        if not code:
            return jsonify({"success": False, "message": "Referral code is required"}), 400
        
        # Check if code exists
        referrer = referrals_bp.mongo.db.users.find_one({"referralCode": code})
        
        if not referrer:
            return jsonify({
                "success": False,
                "data": None,
                "message": "Invalid referral code"
            }), 404
        
        return jsonify({
            "success": True,
            "data": {
                "referrerName": referrer.get('displayName', 'A FiCore user'),
                "referrerId": str(referrer['_id'])
            },
            "message": f"Valid code - Referred by {referrer.get('displayName', 'a FiCore user')}"
        }), 200
        
    except Exception as e:
        print(f"❌ Validate code error: {e}")
        return jsonify({"success": False, "message": "Unable to validate code"}), 500


# ===== WITHDRAWAL SYSTEM ENDPOINTS (Phase 4A) =====

@referrals_bp.route('/request-withdrawal', methods=['POST'])
@token_required
def request_withdrawal(current_user):
    """
    Request withdrawal of referral earnings to FiCore Credits.
    Phase 4A: Manual admin approval required.
    """
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        user_id = current_user['_id']
        
        # 1. Validate amount
        if amount < 1000:
            return jsonify({
                'success': False,
                'message': 'Minimum withdrawal amount is ₦1,000'
            }), 400
        
        # 2. Check available balance
        withdrawable_balance = current_user.get('withdrawableCommissionBalance', 0.0)
        if withdrawable_balance < amount:
            return jsonify({
                'success': False,
                'message': f'Insufficient balance. Available: ₦{withdrawable_balance:,.2f}'
            }), 400
        
        # 3. Check for pending requests
        pending_request = referrals_bp.mongo.db.withdrawal_requests.find_one({
            'userId': user_id,
            'status': 'PENDING'
        })
        
        if pending_request:
            return jsonify({
                'success': False,
                'message': 'You already have a pending withdrawal request'
            }), 400
        
        # 4. Create withdrawal request
        withdrawal = {
            'userId': user_id,
            'amount': amount,
            'status': 'PENDING',
            'requestedAt': datetime.utcnow(),
            'withdrawableBalanceAtRequest': withdrawable_balance,
            'pendingBalanceAtRequest': current_user.get('pendingCommissionBalance', 0.0),
            'creditBalanceAtRequest': current_user.get('ficoreCreditBalance', 0),
            'ipAddress': request.remote_addr,
            'deviceInfo': request.headers.get('User-Agent', 'Unknown'),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        result = referrals_bp.mongo.db.withdrawal_requests.insert_one(withdrawal)
        
        # 5. Log action
        print(f"✅ Withdrawal request created: User {current_user.get('displayName')} - ₦{amount}")
        
        return jsonify({
            'success': True,
            'data': {
                'withdrawalId': str(result.inserted_id),
                'status': 'PENDING',
                'amount': amount,
                'estimatedProcessingTime': '24 hours'
            },
            'message': 'Withdrawal request submitted successfully. Admin will review within 24 hours.'
        }), 200
        
    except Exception as e:
        print(f"❌ Request withdrawal error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Failed to submit withdrawal request'
        }), 500

@referrals_bp.route('/withdrawal-status', methods=['GET'])
@token_required
def get_withdrawal_status(current_user):
    """
    Get current withdrawal request status for user.
    """
    try:
        user_id = current_user['_id']
        
        # Get pending request
        pending_request = referrals_bp.mongo.db.withdrawal_requests.find_one({
            'userId': user_id,
            'status': 'PENDING'
        })
        
        if pending_request:
            return jsonify({
                'success': True,
                'data': {
                    'hasPendingRequest': True,
                    'withdrawalId': str(pending_request['_id']),
                    'amount': pending_request['amount'],
                    'requestedAt': pending_request['requestedAt'].isoformat(),
                    'status': 'PENDING'
                }
            }), 200
        
        return jsonify({
            'success': True,
            'data': {
                'hasPendingRequest': False
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Get withdrawal status error: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to get withdrawal status'
        }), 500

@referrals_bp.route('/withdrawal-history', methods=['GET'])
@token_required
def get_withdrawal_history(current_user):
    """
    Get withdrawal history for current user.
    """
    try:
        user_id = current_user['_id']
        
        # Get all withdrawal requests for user
        withdrawals = list(referrals_bp.mongo.db.withdrawal_requests.find({
            'userId': user_id
        }).sort('requestedAt', -1).limit(20))
        
        # Format for response
        formatted_withdrawals = []
        for w in withdrawals:
            formatted_withdrawals.append({
                'id': str(w['_id']),
                'amount': w['amount'],
                'status': w['status'],
                'requestedAt': w['requestedAt'].isoformat(),
                'processedAt': w['processedAt'].isoformat() if w.get('processedAt') else None,
                'completedAt': w['completedAt'].isoformat() if w.get('completedAt') else None,
                'rejectionReason': w.get('rejectionReason')
            })
        
        return jsonify({
            'success': True,
            'data': {
                'withdrawals': formatted_withdrawals
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Get withdrawal history error: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to get withdrawal history'
        }), 500


# ===== WITHDRAWAL ENDPOINTS =====

@referrals_bp.route('/request-withdrawal', methods=['POST'])
@token_required
def request_withdrawal(current_user):
    """
    Request withdrawal of referral earnings to wallet balance.
    Minimum: ₦1,000
    """
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        
        user_id = current_user['_id']
        
        # 1. Validate minimum amount
        if amount < 1000:
            return jsonify({
                'success': False,
                'message': 'Minimum withdrawal amount is ₦1,000'
            }), 400
        
        # 2. Check available balance
        withdrawable_balance = current_user.get('withdrawableCommissionBalance', 0.0)
        if amount > withdrawable_balance:
            return jsonify({
                'success': False,
                'message': f'Insufficient balance. Available: ₦{withdrawable_balance:,.2f}'
            }), 400
        
        # 3. Check for pending requests
        pending = referrals_bp.mongo.db.withdrawal_requests.find_one({
            'userId': user_id,
            'status': 'PENDING'
        })
        if pending:
            return jsonify({
                'success': False,
                'message': 'You already have a pending withdrawal request'
            }), 400
        
        # 4. Create withdrawal request
        withdrawal = {
            'userId': user_id,
            'amount': amount,
            'status': 'PENDING',
            'requestedAt': datetime.utcnow(),
            'withdrawableBalanceAtRequest': withdrawable_balance,
            'pendingBalanceAtRequest': current_user.get('pendingCommissionBalance', 0.0),
            'walletBalanceAtRequest': current_user.get('walletBalance', 0.0),
            'ipAddress': request.remote_addr,
            'deviceInfo': request.headers.get('User-Agent', 'Unknown'),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        result = referrals_bp.mongo.db.withdrawal_requests.insert_one(withdrawal)
        
        print(f"✅ Withdrawal request created: User {current_user.get('displayName')}, Amount: ₦{amount:,.2f}")
        
        return jsonify({
            'success': True,
            'data': {
                'withdrawalId': str(result.inserted_id),
                'status': 'PENDING',
                'amount': amount,
                'estimatedProcessingTime': '24 hours'
            },
            'message': 'Withdrawal request submitted successfully'
        }), 200
        
    except Exception as e:
        print(f"❌ Request withdrawal error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Failed to submit withdrawal request'
        }), 500

@referrals_bp.route('/withdrawal-status', methods=['GET'])
@token_required
def get_withdrawal_status(current_user):
    """
    Get current pending withdrawal request for user.
    """
    try:
        user_id = current_user['_id']
        
        # Find pending withdrawal
        withdrawal = referrals_bp.mongo.db.withdrawal_requests.find_one({
            'userId': user_id,
            'status': 'PENDING'
        })
        
        if not withdrawal:
            return jsonify({
                'success': True,
                'data': None,
                'message': 'No pending withdrawal'
            }), 200
        
        return jsonify({
            'success': True,
            'data': {
                'id': str(withdrawal['_id']),
                'amount': withdrawal['amount'],
                'status': withdrawal['status'],
                'requestedAt': withdrawal['requestedAt'].isoformat(),
                'estimatedCompletionTime': (withdrawal['requestedAt'] + timedelta(hours=24)).isoformat()
            },
            'message': 'Pending withdrawal found'
        }), 200
        
    except Exception as e:
        print(f"❌ Get withdrawal status error: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to get withdrawal status'
        }), 500

@referrals_bp.route('/withdrawal-history', methods=['GET'])
@token_required
def get_withdrawal_history(current_user):
    """
    Get user's withdrawal history (last 20).
    """
    try:
        user_id = current_user['_id']
        
        # Get all withdrawals for user
        withdrawals = list(referrals_bp.mongo.db.withdrawal_requests.find({
            'userId': user_id
        }).sort('requestedAt', -1).limit(20))
        
        # Format for response
        formatted = []
        for w in withdrawals:
            formatted.append({
                'id': str(w['_id']),
                'amount': w['amount'],
                'status': w['status'],
                'requestedAt': w['requestedAt'].isoformat(),
                'processedAt': w.get('processedAt').isoformat() if w.get('processedAt') else None,
                'rejectionReason': w.get('rejectionReason')
            })
        
        return jsonify({
            'success': True,
            'data': {
                'withdrawals': formatted,
                'total': len(formatted)
            },
            'message': 'Withdrawal history retrieved'
        }), 200
        
    except Exception as e:
        print(f"❌ Get withdrawal history error: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to get withdrawal history'
        }), 500
