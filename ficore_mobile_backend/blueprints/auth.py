from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import jwt
import uuid
from bson import ObjectId
from functools import wraps
from utils.analytics_tracker import create_tracker
from utils.profile_picture_helper import generate_profile_picture_url
from utils.email_service import get_email_service

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def init_auth_blueprint(mongo, app_config):
    """Initialize the auth blueprint with database and config"""
    auth_bp.mongo = mongo
    auth_bp.config = app_config
    auth_bp.tracker = create_tracker(mongo.db)
    return auth_bp

# ==================== REFERRAL SYSTEM HELPERS (NEW - Feb 4, 2026) ====================

def generate_referral_code(first_name, phone_suffix, db):
    """
    Generate a unique, user-friendly referral code.
    Format: {FIRST_NAME_3_CHARS}{PHONE_LAST_3_DIGITS}
    Falls back to random if collision occurs.
    
    Args:
        first_name: User's first name
        phone_suffix: Last 3 digits of phone number
        db: MongoDB database instance
    
    Returns:
        str: Unique referral code (e.g., 'AUW123')
    """
    import random
    import string
    
    # Clean the name (e.g., 'Auwal' -> 'AUW')
    prefix = (first_name[:3]).upper() if first_name else "FIC"
    
    # Add phone suffix or random digits
    suffix = phone_suffix[-3:] if phone_suffix and len(phone_suffix) >= 3 else ''.join(random.choices(string.digits, k=3))
    
    code = f"{prefix}{suffix}"
    
    # Check for collision in DB
    max_attempts = 10
    attempts = 0
    while db.users.find_one({"referralCode": code}) and attempts < max_attempts:
        code = f"{prefix}{''.join(random.choices(string.digits, k=3))}"
        attempts += 1
    
    if attempts >= max_attempts:
        # Fallback to UUID-based code
        code = f"FIC{str(uuid.uuid4())[:6].upper()}"
    
    return code

# ==================== END REFERRAL HELPERS ====================

# Validation helpers
def validate_email(email):
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    return len(password) >= 6

@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({
                'success': False,
                'message': 'Email and password are required',
                'errors': {
                    'email': ['Email is required'] if not email else [],
                    'password': ['Password is required'] if not password else []
                }
            }), 400
        
        # Find user
        user = auth_bp.mongo.db.users.find_one({'email': email})
        if not user or not check_password_hash(user['password'], password):
            return jsonify({
                'success': False,
                'message': 'Invalid credentials',
                'errors': {'email': ['Invalid email or password']}
            }), 401
        
        # Check if user must change password (admin reset)
        must_change_password = user.get('mustChangePassword', False)
        
        # Generate tokens
        access_token = jwt.encode({
            'user_id': str(user['_id']),
            'exp': datetime.utcnow() + auth_bp.config['JWT_EXPIRATION_DELTA']
        }, auth_bp.config['SECRET_KEY'], algorithm='HS256')
        
        refresh_token = jwt.encode({
            'user_id': str(user['_id']),
            'type': 'refresh',
            'exp': datetime.utcnow() + timedelta(days=30)
        }, auth_bp.config['SECRET_KEY'], algorithm='HS256')
        
        # Update last login
        auth_bp.mongo.db.users.update_one(
            {'_id': user['_id']},
            {'$set': {'lastLogin': datetime.utcnow()}}
        )
        
        # Track login event
        try:
            device_info = {
                'user_agent': request.headers.get('User-Agent', 'Unknown'),
                'ip_address': request.remote_addr
            }
            auth_bp.tracker.track_login(user['_id'], device_info=device_info)
        except Exception as e:
            print(f"Analytics tracking failed: {e}")
        
        # Determine admin permissions based on role
        permissions = []
        if user.get('role') == 'admin':
            # Grant all admin permissions
            permissions = [
                'admin:*',  # Super admin - all permissions
                'admin:credits:grant',
                'admin:credits:deduct',
                'admin:subscription:grant',
                'admin:subscription:cancel',
                'admin:subscription:extend',
                'admin:password:reset',
                'admin:view:audit',
                'admin:users:manage'
            ]
        
        return jsonify({
            'success': True,
            'data': {
                'token': access_token,  # Keep for frontend compatibility
                'access_token': access_token,  # Keep for backward compatibility
                'refresh_token': refresh_token,
                'expires_at': (datetime.utcnow() + auth_bp.config['JWT_EXPIRATION_DELTA']).isoformat() + 'Z',
                'permissions': permissions,  # RBAC permissions for frontend
                'mustChangePassword': must_change_password,  # Flag for forced password change
                'user': {
                    'id': str(user['_id']),
                    'email': user['email'],
                    'displayName': user.get('displayName', user.get('firstName', '') + ' ' + user.get('lastName', '')),
                    # Backwards/forwards compatibility: include `name` keyed value as well
                    'name': user.get('displayName', user.get('firstName', '') + ' ' + user.get('lastName', '')),
                    'role': user.get('role', 'personal'),
                    'ficoreCreditBalance': user.get('ficoreCreditBalance', 10.0),
                    'financialGoals': user.get('financialGoals', []),
                    'createdAt': user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                    # CRITICAL FIX: Generate profile picture URL from GCS or GridFS
                    'profilePictureUrl': generate_profile_picture_url(user),
                    'businessName': user.get('businessName'),
                    'mustChangePassword': must_change_password  # Also include in user object for convenience
                }
            },
            'message': 'Login successful'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Login failed',
            'errors': {'general': [str(e)]}
        }), 500

@auth_bp.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')
        first_name = data.get('firstName', '').strip()
        last_name = data.get('lastName', '').strip()
        
        errors = {}
        
        # Validation (unchanged)
        if not email:
            errors['email'] = ['Email is required']
        elif not validate_email(email):
            errors['email'] = ['Invalid email format']
        elif auth_bp.mongo.db.users.find_one({'email': email}):
            errors['email'] = ['Email already exists']
            
        if not password:
            errors['password'] = ['Password is required']
        elif not validate_password(password):
            errors['password'] = ['Password must be at least 6 characters']
            
        if not first_name:
            errors['firstName'] = ['First name is required']
            
        if not last_name:
            errors['lastName'] = ['Last name is required']
        
        if errors:
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': errors
            }), 400
        # Get financial goals from request (optional)
        financial_goals = data.get('financialGoals', [])
        # Optional displayName or businessName from frontend
        display_name = data.get('displayName')
        # Optional referral code (NEW - Feb 4, 2026)
        referred_by_code = data.get('referralCode', '').strip().upper() if data.get('referralCode') else None
        phone = data.get('phone', '').strip()  # Get phone for code generation

        # Validate financial goals if provided
        valid_goals = [
            'save_for_emergencies',
            'pay_off_debt', 
            'budget_better',
            'track_income_expenses',
            'grow_savings_investments',
            'plan_big_purchases',
            'improve_financial_habits',
            'financial_education',
            'manage_business_finances',
            'know_my_profit'
        ]

        if financial_goals:
            invalid_goals = [goal for goal in financial_goals if goal not in valid_goals]
            if invalid_goals:
                errors['financialGoals'] = [f'Invalid goals: {", ".join(invalid_goals)}']

        # Validate referral code if provided (NEW - Feb 4, 2026)
        referrer = None
        if referred_by_code:
            referrer = auth_bp.mongo.db.users.find_one({"referralCode": referred_by_code})
            if not referrer:
                errors['referralCode'] = ['Invalid referral code']

        if errors:
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': errors
            }), 400

        # Generate unique referral code for new user (NEW - Feb 4, 2026)
        new_user_referral_code = generate_referral_code(
            first_name=first_name,
            phone_suffix=phone[-3:] if phone and len(phone) >= 3 else '',
            db=auth_bp.mongo.db
        )

        # Create user with clean account (no demo data, removed setupComplete)
        user_data = {
            'email': email,
            'password': generate_password_hash(password),
            'firstName': first_name,
            'lastName': last_name,
            # Prefer explicit displayName if provided by client (business name), else generate from names
            'displayName': display_name.strip() if display_name and isinstance(display_name, str) and display_name.strip() else f"{first_name} {last_name}",
            'role': 'personal',
            'ficoreCreditBalance': 10.0,  # Starting balance: 10 FC (Welcome bonus)
            'financialGoals': financial_goals,
            'createdAt': datetime.utcnow(),
            'lastLogin': None,
            'isActive': True,
            # Referral System Fields (NEW - Feb 4, 2026)
            'referralCode': new_user_referral_code,
            'referredBy': referrer['_id'] if referrer else None,
            'referralCount': 0,
            'referralEarnings': 0.0,
            'pendingCommissionBalance': 0.0,
            'withdrawableCommissionBalance': 0.0,
            'firstDepositCompleted': False,
            'firstDepositDate': None,
            'referralBonusReceived': False,
            'referralCodeGeneratedAt': datetime.utcnow(),
            'referredAt': datetime.utcnow() if referrer else None,
        }
        
        result = auth_bp.mongo.db.users.insert_one(user_data)
        user_id = str(result.inserted_id)
        
        # If referred, create referral tracking entry (NEW - Feb 4, 2026)
        if referrer:
            referral_doc = {
                'referrerId': referrer['_id'],
                'refereeId': result.inserted_id,
                'referralCode': referred_by_code,
                'status': 'pending_deposit',
                'signupDate': datetime.utcnow(),
                'firstDepositDate': None,
                'firstSubscriptionDate': None,
                'qualifiedDate': None,
                'refereeDepositBonusGranted': False,
                'referrerSubCommissionGranted': False,
                'referrerVasShareActive': False,
                'vasShareExpiryDate': None,
                'ipAddress': request.remote_addr,
                'deviceId': request.headers.get('X-Device-ID'),
                'isSelfReferral': False,
                'fraudReason': None,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            auth_bp.mongo.db.referrals.insert_one(referral_doc)
        
        # Create signup bonus transaction record for transparency
        signup_transaction = {
            '_id': ObjectId(),
            'userId': result.inserted_id,
            'type': 'credit',
            'amount': 10.0,
            'description': 'Welcome bonus - Thank you for joining Ficore!',
            'operation': 'signup_bonus',
            'balanceBefore': 0.0,
            'balanceAfter': 10.0,
            'status': 'completed',
            'createdAt': datetime.utcnow(),
            'metadata': {
                'isWelcomeBonus': True,
                'isEarned': False,  # This is a gift, not earned
                'source': 'registration'
            }
        }
        auth_bp.mongo.db.credit_transactions.insert_one(signup_transaction)
        
        # Track registration event
        try:
            device_info = {
                'user_agent': request.headers.get('User-Agent', 'Unknown'),
                'ip_address': request.remote_addr
            }
            auth_bp.tracker.track_registration(result.inserted_id, device_info=device_info)
        except Exception as e:
            print(f"Analytics tracking failed: {e}")
        
        # Generate tokens (unchanged)
        access_token = jwt.encode({
            'user_id': user_id,
            'exp': datetime.utcnow() + auth_bp.config['JWT_EXPIRATION_DELTA']
        }, auth_bp.config['SECRET_KEY'], algorithm='HS256')
        
        refresh_token = jwt.encode({
            'user_id': user_id,
            'type': 'refresh',
            'exp': datetime.utcnow() + timedelta(days=30)
        }, auth_bp.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'success': True,
            'data': {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'expires_at': (datetime.utcnow() + auth_bp.config['JWT_EXPIRATION_DELTA']).isoformat() + 'Z',
                'user': {
                    'id': user_id,
                    'email': email,
                    'displayName': user_data.get('displayName'),
                    # Also include `name` for client compatibility (mirrors displayName)
                    'name': user_data.get('displayName'),
                    'role': 'personal',
                    'ficoreCreditBalance': 10.0,  # Starting balance: 10 FC
                    'financialGoals': financial_goals,
                    'createdAt': datetime.utcnow().isoformat() + 'Z'
                }
            },
            'message': 'Account created successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Registration failed',
            'errors': {'general': [str(e)]}
        }), 500

@auth_bp.route('/logout', methods=['POST'])
def logout():
    return jsonify({
        'success': True,
        'message': 'Logged out successfully'
    })

@auth_bp.route('/refresh', methods=['POST'])
def refresh_token():
    try:
        data = request.get_json()
        refresh_token = data.get('refresh_token')
        
        if not refresh_token:
            return jsonify({'success': False, 'message': 'Refresh token required'}), 400
        
        try:
            data = jwt.decode(refresh_token, auth_bp.config['SECRET_KEY'], algorithms=['HS256'])
            if data.get('type') != 'refresh':
                return jsonify({'success': False, 'message': 'Invalid refresh token'}), 401
                
            user = auth_bp.mongo.db.users.find_one({'_id': ObjectId(data['user_id'])})
            if not user:
                return jsonify({'success': False, 'message': 'User not found'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Refresh token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'Invalid refresh token'}), 401
        
        # Generate new access token
        access_token = jwt.encode({
            'user_id': str(user['_id']),
            'exp': datetime.utcnow() + auth_bp.config['JWT_EXPIRATION_DELTA']
        }, auth_bp.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'success': True,
            'data': {
                'access_token': access_token,
                'expires_at': (datetime.utcnow() + auth_bp.config['JWT_EXPIRATION_DELTA']).isoformat() + 'Z'
            },
            'message': 'Token refreshed successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Token refresh failed',
            'errors': {'general': [str(e)]}
        }), 500

@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        
        if not email:
            return jsonify({
                'success': False,
                'message': 'Email is required',
                'errors': {'email': ['Email is required']}
            }), 400
        
        user = auth_bp.mongo.db.users.find_one({'email': email})
        if not user:
            # Don't reveal if email exists or not - but still return success
            return jsonify({
                'success': True,
                'message': 'If the email exists, a reset link has been sent',
                'data': None
            })
        
        # Generate reset token
        reset_token = str(uuid.uuid4())
        auth_bp.mongo.db.users.update_one(
            {'_id': user['_id']},
            {'$set': {
                'resetToken': reset_token,
                'resetTokenExpiry': datetime.utcnow() + timedelta(hours=1)
            }}
        )
        
        # ₦0 COMMUNICATION STRATEGY: Send email with reset link
        email_service = get_email_service()
        user_name = user.get('displayName') or f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
        
        email_result = email_service.send_password_reset(
            to_email=user['email'],
            reset_token=reset_token,
            user_name=user_name if user_name else None
        )
        
        # DUAL-TRACK APPROACH: Also create admin request for password reset
        # This allows admins to help users while email service is not ready
        password_reset_request = {
            '_id': ObjectId(),
            'userId': user['_id'],
            'userEmail': user.get('email', ''),
            'userName': user_name or 'Unknown User',
            'status': 'pending',  # pending, completed, expired
            'requestedAt': datetime.utcnow(),
            'processedAt': None,
            'processedBy': None,
            'processedByName': None,
            'temporaryPassword': None,
            'resetToken': reset_token,  # Keep for future email service
            'expiresAt': datetime.utcnow() + timedelta(hours=24),  # Admin has 24 hours to process
            'emailSent': email_result.get('success', False),
            'emailMethod': email_result.get('method', 'disabled')
        }
        
        auth_bp.mongo.db.password_reset_requests.insert_one(password_reset_request)
        
        # Track analytics event
        try:
            auth_bp.tracker.track_event(
                user_id=user['_id'],
                event_type='password_reset_requested',
                event_details={
                    'request_source': 'mobile_app',
                    'email_sent': email_result.get('success', False),
                    'email_method': email_result.get('method', 'disabled'),
                    'has_admin_fallback': True
                }
            )
        except Exception as e:
            print(f"Analytics tracking failed: {e}")
        
        # Always return success to user (don't reveal if email exists)
        return jsonify({
            'success': True,
            'message': 'Password reset instructions sent to your email',
            'data': None
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Password reset failed',
            'errors': {'general': [str(e)]}
        }), 500

@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    try:
        data = request.get_json()
        token = data.get('token')
        new_password = data.get('password')
        
        if not token or not new_password:
            return jsonify({
                'success': False,
                'message': 'Token and new password are required',
                'errors': {
                    'token': ['Reset token is required'] if not token else [],
                    'password': ['New password is required'] if not new_password else []
                }
            }), 400
        
        if not validate_password(new_password):
            return jsonify({
                'success': False,
                'message': 'Invalid password',
                'errors': {'password': ['Password must be at least 6 characters']}
            }), 400
        
        user = auth_bp.mongo.db.users.find_one({
            'resetToken': token,
            'resetTokenExpiry': {'$gt': datetime.utcnow()}
        })
        
        if not user:
            return jsonify({
                'success': False,
                'message': 'Invalid or expired reset token',
                'errors': {'token': ['Invalid or expired reset token']}
            }), 400
        
        # Update password and clear reset token
        auth_bp.mongo.db.users.update_one(
            {'_id': user['_id']},
            {'$set': {
                'password': generate_password_hash(new_password)
            }, '$unset': {
                'resetToken': '',
                'resetTokenExpiry': ''
            }}
        )
        
        return jsonify({
            'success': True,
            'message': 'Password reset successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Password reset failed',
            'errors': {'general': [str(e)]}

        }), 500


# ==================== ONBOARDING STATE ENDPOINTS ====================
# Added: Jan 30, 2026 - For Google Play review two-account strategy

@auth_bp.route('/onboarding-status', methods=['GET'])
def get_onboarding_status():
    """
    Check if user has completed onboarding.
    Used by frontend to decide whether to show wizard.
    
    Returns:
        - hasCompletedOnboarding: bool
        - onboardingCompletedAt: datetime or null
        - onboardingSkipped: bool
        - entryCount: int (only if onboarding not completed)
    """
    try:
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'message': 'Authorization token required',
                'errors': {'auth': ['Missing or invalid authorization header']}
            }), 401
        
        token = auth_header.split(' ')[1]
        
        # Decode JWT token
        try:
            payload = jwt.decode(token, auth_bp.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = payload.get('user_id')
        except jwt.ExpiredSignatureError:
            return jsonify({
                'success': False,
                'message': 'Token expired',
                'errors': {'auth': ['Token has expired']}
            }), 401
        except jwt.InvalidTokenError:
            return jsonify({
                'success': False,
                'message': 'Invalid token',
                'errors': {'auth': ['Invalid token']}
            }), 401
        
        # Find user
        user = auth_bp.mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        if not user:
            return jsonify({
                'success': False,
                'message': 'User not found',
                'errors': {'user': ['User not found']}
            }), 404
        
        # Check backend onboarding state
        has_completed = user.get('hasCompletedOnboarding', False)
        
        # Fallback: Check if user has any entries (backward compatibility)
        # This ensures existing users who completed onboarding before this feature
        # don't get stuck in the wizard
        if not has_completed:
            income_count = auth_bp.mongo.db.incomes.count_documents({'userId': ObjectId(user_id)})
            expense_count = auth_bp.mongo.db.expenses.count_documents({'userId': ObjectId(user_id)})
            total_entries = income_count + expense_count
            
            # If user has entries, mark onboarding as complete automatically
            if total_entries > 0:
                has_completed = True
                # Update backend state for future checks
                auth_bp.mongo.db.users.update_one(
                    {'_id': ObjectId(user_id)},
                    {
                        '$set': {
                            'hasCompletedOnboarding': True,
                            'onboardingCompletedAt': datetime.utcnow()
                        }
                    }
                )
        else:
            total_entries = None  # Don't count if already completed
        
        return jsonify({
            'success': True,
            'hasCompletedOnboarding': has_completed,
            'onboardingCompletedAt': user.get('onboardingCompletedAt').isoformat() if user.get('onboardingCompletedAt') else None,
            'onboardingSkipped': user.get('onboardingSkipped', False),
            'onboardingSkippedAt': user.get('onboardingSkippedAt').isoformat() if user.get('onboardingSkippedAt') else None,
            'entryCount': total_entries  # Only returned if onboarding not completed
        }), 200
        
    except Exception as e:
        print(f'❌ Error checking onboarding status: {str(e)}')
        return jsonify({
            'success': False,
            'message': 'Failed to check onboarding status',
            'errors': {'general': [str(e)]}
        }), 500


@auth_bp.route('/onboarding-complete', methods=['POST'])
def mark_onboarding_complete():
    """
    Mark onboarding as complete.
    Called by frontend when user creates first entry or completes wizard.
    
    Body:
        - skipped: bool (optional) - true if user chose "Explore First"
    """
    try:
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'message': 'Authorization token required',
                'errors': {'auth': ['Missing or invalid authorization header']}
            }), 401
        
        token = auth_header.split(' ')[1]
        
        # Decode JWT token
        try:
            payload = jwt.decode(token, auth_bp.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = payload.get('user_id')
        except jwt.ExpiredSignatureError:
            return jsonify({
                'success': False,
                'message': 'Token expired',
                'errors': {'auth': ['Token has expired']}
            }), 401
        except jwt.InvalidTokenError:
            return jsonify({
                'success': False,
                'message': 'Invalid token',
                'errors': {'auth': ['Invalid token']}
            }), 401
        
        data = request.get_json() or {}
        skipped = data.get('skipped', False)
        
        # Update user onboarding state
        update_data = {
            'hasCompletedOnboarding': True,
            'onboardingCompletedAt': datetime.utcnow()
        }
        
        if skipped:
            update_data['onboardingSkipped'] = True
            update_data['onboardingSkippedAt'] = datetime.utcnow()
        
        result = auth_bp.mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': update_data}
        )
        
        if result.modified_count == 0:
            # User might already have onboarding marked complete
            user = auth_bp.mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found',
                    'errors': {'user': ['User not found']}
                }), 404
        
        action = 'skipped' if skipped else 'completed'
        print(f'✅ Onboarding {action} for user {user_id}')
        
        return jsonify({
            'success': True,
            'message': f'Onboarding {action} successfully',
            'hasCompletedOnboarding': True,
            'onboardingSkipped': skipped
        }), 200
        
    except Exception as e:
        print(f'❌ Error marking onboarding complete: {str(e)}')
        return jsonify({
            'success': False,
            'message': 'Failed to mark onboarding complete',
            'errors': {'general': [str(e)]}
        }), 500


# Added: Jan 30, 2026 - Redo Setup Wizard feature for Google Play
@auth_bp.route('/reset-onboarding', methods=['POST'])
def reset_onboarding():
    """
    Reset onboarding state to allow user to redo wizard.
    Useful for users who skipped wizard and want to try again.
    
    This endpoint:
    - Sets hasCompletedOnboarding = False
    - Clears onboardingSkipped flag
    - Clears onboarding timestamps
    - User will see wizard on next app restart or manual navigation
    """
    try:
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'message': 'Authorization token required',
                'errors': {'auth': ['Missing or invalid authorization header']}
            }), 401
        
        token = auth_header.split(' ')[1]
        
        # Decode JWT token
        try:
            payload = jwt.decode(token, auth_bp.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = payload.get('user_id')
        except jwt.ExpiredSignatureError:
            return jsonify({
                'success': False,
                'message': 'Token expired',
                'errors': {'auth': ['Token has expired']}
            }), 401
        except jwt.InvalidTokenError:
            return jsonify({
                'success': False,
                'message': 'Invalid token',
                'errors': {'auth': ['Invalid token']}
            }), 401
        
        # Reset onboarding state
        result = auth_bp.mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {
                '$set': {
                    'hasCompletedOnboarding': False,
                    'onboardingSkipped': False
                },
                '$unset': {
                    'onboardingCompletedAt': '',
                    'onboardingSkippedAt': ''
                }
            }
        )
        
        if result.matched_count == 0:
            return jsonify({
                'success': False,
                'message': 'User not found',
                'errors': {'user': ['User not found']}
            }), 404
        
        print(f'✅ Onboarding reset for user {user_id}')
        
        return jsonify({
            'success': True,
            'message': 'Onboarding reset successfully. You can now redo the setup wizard.',
            'data': {
                'hasCompletedOnboarding': False,
                'onboardingSkipped': False
            }
        }), 200
        
    except Exception as e:
        print(f'❌ Error resetting onboarding: {str(e)}')
        return jsonify({
            'success': False,
            'message': 'Failed to reset onboarding',
            'errors': {'general': [str(e)]}
        }), 500
