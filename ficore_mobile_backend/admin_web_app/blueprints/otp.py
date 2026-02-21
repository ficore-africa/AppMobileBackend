"""
OTP Blueprint for ₦0 Communication Strategy
Handles OTP generation and delivery via Email + Firebase Push
"""
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
import random
import string
from bson import ObjectId
from utils.email_service import get_email_service

otp_bp = Blueprint('otp', __name__, url_prefix='/otp')

def init_otp_blueprint(mongo, app_config):
    """Initialize the OTP blueprint with database and config"""
    otp_bp.mongo = mongo
    otp_bp.config = app_config
    return otp_bp

def generate_otp_code():
    """Generate a 6-digit OTP code"""
    return ''.join(random.choices(string.digits, k=6))

@otp_bp.route('/send', methods=['POST'])
def send_otp():
    """
    Send OTP via Email + Firebase Push (₦0 Communication Strategy)
    
    Request body:
    {
        "email": "user@example.com",
        "purpose": "password_reset|login_verification|transaction_confirmation",
        "user_id": "optional_user_id_for_push"
    }
    """
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        purpose = data.get('purpose', 'verification')
        user_id = data.get('user_id')
        
        if not email:
            return jsonify({
                'success': False,
                'message': 'Email is required',
                'errors': {'email': ['Email is required']}
            }), 400
        
        # Generate OTP code
        otp_code = generate_otp_code()
        
        # Store OTP in database with expiration
        otp_record = {
            '_id': ObjectId(),
            'email': email,
            'otpCode': otp_code,
            'purpose': purpose,
            'userId': ObjectId(user_id) if user_id else None,
            'createdAt': datetime.utcnow(),
            'expiresAt': datetime.utcnow() + timedelta(minutes=10),
            'isUsed': False,
            'attempts': 0,
            'maxAttempts': 3
        }
        
        otp_bp.mongo.db.otp_codes.insert_one(otp_record)
        
        # Send OTP via Email (Primary Channel)
        email_service = get_email_service()
        
        # Get user name for personalization
        user_name = None
        if user_id:
            user = otp_bp.mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if user:
                user_name = user.get('displayName') or f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
        
        email_result = email_service.send_otp(
            to_email=email,
            otp_code=otp_code,
            user_name=user_name
        )
        
        # TODO: Send OTP via Firebase Push (Secondary Channel)
        # This would be implemented when Firebase Admin SDK is set up on backend
        push_result = {
            'success': False,
            'method': 'not_implemented',
            'message': 'Firebase push not yet implemented on backend'
        }
        
        # Update OTP record with delivery status
        otp_bp.mongo.db.otp_codes.update_one(
            {'_id': otp_record['_id']},
            {'$set': {
                'emailSent': email_result.get('success', False),
                'emailMethod': email_result.get('method', 'failed'),
                'pushSent': push_result.get('success', False),
                'pushMethod': push_result.get('method', 'not_implemented'),
                'deliveryStatus': 'email_sent' if email_result.get('success') else 'failed'
            }}
        )
        
        return jsonify({
            'success': True,
            'message': 'OTP sent successfully',
            'data': {
                'otp_id': str(otp_record['_id']),
                'expires_at': otp_record['expiresAt'].isoformat() + 'Z',
                'delivery': {
                    'email': email_result,
                    'push': push_result
                }
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to send OTP',
            'errors': {'general': [str(e)]}
        }), 500

@otp_bp.route('/verify', methods=['POST'])
def verify_otp():
    """
    Verify OTP code
    
    Request body:
    {
        "email": "user@example.com",
        "otp_code": "123456",
        "purpose": "password_reset|login_verification|transaction_confirmation"
    }
    """
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        otp_code = data.get('otp_code', '').strip()
        purpose = data.get('purpose', 'verification')
        
        if not email or not otp_code:
            return jsonify({
                'success': False,
                'message': 'Email and OTP code are required',
                'errors': {
                    'email': ['Email is required'] if not email else [],
                    'otp_code': ['OTP code is required'] if not otp_code else []
                }
            }), 400
        
        # Find valid OTP record
        otp_record = otp_bp.mongo.db.otp_codes.find_one({
            'email': email,
            'purpose': purpose,
            'isUsed': False,
            'expiresAt': {'$gt': datetime.utcnow()},
            'attempts': {'$lt': 3}  # Max 3 attempts
        })
        
        if not otp_record:
            return jsonify({
                'success': False,
                'message': 'Invalid or expired OTP',
                'errors': {'otp_code': ['Invalid or expired OTP code']}
            }), 400
        
        # Increment attempt counter
        otp_bp.mongo.db.otp_codes.update_one(
            {'_id': otp_record['_id']},
            {'$inc': {'attempts': 1}}
        )
        
        # Verify OTP code
        if otp_record['otpCode'] != otp_code:
            # Check if max attempts reached
            if otp_record['attempts'] + 1 >= 3:
                otp_bp.mongo.db.otp_codes.update_one(
                    {'_id': otp_record['_id']},
                    {'$set': {'isUsed': True, 'failedAt': datetime.utcnow()}}
                )
                return jsonify({
                    'success': False,
                    'message': 'Maximum attempts exceeded. Please request a new OTP.',
                    'errors': {'otp_code': ['Maximum attempts exceeded']}
                }), 400
            
            return jsonify({
                'success': False,
                'message': 'Invalid OTP code',
                'errors': {'otp_code': ['Invalid OTP code']},
                'attempts_remaining': 3 - (otp_record['attempts'] + 1)
            }), 400
        
        # Mark OTP as used
        otp_bp.mongo.db.otp_codes.update_one(
            {'_id': otp_record['_id']},
            {'$set': {
                'isUsed': True,
                'verifiedAt': datetime.utcnow()
            }}
        )
        
        return jsonify({
            'success': True,
            'message': 'OTP verified successfully',
            'data': {
                'otp_id': str(otp_record['_id']),
                'purpose': purpose,
                'verified_at': datetime.utcnow().isoformat() + 'Z'
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'OTP verification failed',
            'errors': {'general': [str(e)]}
        }), 500

@otp_bp.route('/resend', methods=['POST'])
def resend_otp():
    """
    Resend OTP (rate limited to prevent abuse)
    
    Request body:
    {
        "email": "user@example.com",
        "purpose": "password_reset|login_verification|transaction_confirmation"
    }
    """
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        purpose = data.get('purpose', 'verification')
        
        if not email:
            return jsonify({
                'success': False,
                'message': 'Email is required',
                'errors': {'email': ['Email is required']}
            }), 400
        
        # Check rate limiting (max 1 OTP per minute)
        recent_otp = otp_bp.mongo.db.otp_codes.find_one({
            'email': email,
            'purpose': purpose,
            'createdAt': {'$gt': datetime.utcnow() - timedelta(minutes=1)}
        })
        
        if recent_otp:
            return jsonify({
                'success': False,
                'message': 'Please wait before requesting another OTP',
                'errors': {'general': ['Rate limit exceeded. Please wait 1 minute.']}
            }), 429
        
        # Mark previous OTPs as expired
        otp_bp.mongo.db.otp_codes.update_many(
            {
                'email': email,
                'purpose': purpose,
                'isUsed': False
            },
            {'$set': {'isUsed': True, 'expiredAt': datetime.utcnow()}}
        )
        
        # Generate new OTP
        return send_otp()
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to resend OTP',
            'errors': {'general': [str(e)]}
        }), 500