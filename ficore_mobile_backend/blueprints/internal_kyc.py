from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId
import logging
import hashlib
import os
from cryptography.fernet import Fernet
from ..utils.auth import get_current_user_id, is_admin_user
from ..database import db

internal_kyc_bp = Blueprint('internal_kyc', __name__)
logger = logging.getLogger(__name__)

# Security utilities for BVN/NIN encryption
def get_encryption_key():
    """Get or create encryption key for sensitive data"""
    key = os.environ.get('KYC_ENCRYPTION_KEY')
    if not key:
        # Generate a key if not provided (store this securely in production)
        key = Fernet.generate_key().decode()
        logger.warning("Using generated encryption key - set KYC_ENCRYPTION_KEY in production")
    return key.encode() if isinstance(key, str) else key

def encrypt_sensitive_data(data):
    """Encrypt sensitive data like BVN/NIN"""
    if not data or not data.strip():
        return ""
    
    try:
        fernet = Fernet(get_encryption_key())
        return fernet.encrypt(data.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption error: {str(e)}")
        # Fallback to hashing if encryption fails
        return hashlib.sha256(data.encode()).hexdigest()

def decrypt_sensitive_data(encrypted_data):
    """Decrypt sensitive data for admin viewing"""
    if not encrypted_data:
        return ""
    
    try:
        fernet = Fernet(get_encryption_key())
        return fernet.decrypt(encrypted_data.encode()).decode()
    except Exception as e:
        logger.error(f"Decryption error: {str(e)}")
        # Return masked version if decryption fails
        return f"***{encrypted_data[-4:]}" if len(encrypted_data) > 4 else "***"

def mask_sensitive_data(data):
    """Mask sensitive data for display (show only last 4 digits)"""
    if not data or len(data) < 4:
        return "***"
    return f"***{data[-4:]}"

@internal_kyc_bp.route('/api/kyc/submit-internal', methods=['POST'])
def submit_kyc_internal():
    """Submit KYC data internally - NO external API calls, NO charges"""
    try:
        user_id = get_current_user_id()
        user = db.users.find_one({'_id': user_id})
        
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['submissionType']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'message': f'{field} is required'}), 400
        
        submission_type = data.get('submissionType')
        
        # Check if user already has a verified submission
        existing_submission = db.kyc_submissions.find_one({'userId': user_id})
        if existing_submission and existing_submission.get('status') in ['VERIFIED']:
            return jsonify({
                'success': False,
                'message': 'KYC already verified',
                'status': 'ALREADY_VERIFIED'
            }), 400
        
        # Create KYC submission record with encrypted sensitive data
        submission_data = {
            'userId': user_id,
            'submissionType': submission_type,
            'bvnNumber': encrypt_sensitive_data(data.get('bvnNumber', '').strip()),
            'ninNumber': encrypt_sensitive_data(data.get('ninNumber', '').strip()),
            'firstName': data.get('firstName', '').strip(),
            'lastName': data.get('lastName', '').strip(),
            'dateOfBirth': data.get('dateOfBirth'),
            'phoneNumber': data.get('phoneNumber', '').strip(),
            'submittedAt': datetime.utcnow(),
            'status': 'SUBMITTED',
            'metadata': {
                'ipAddress': request.remote_addr,
                'userAgent': request.headers.get('User-Agent', ''),
                'submissionSource': 'mobile_app',
                'encryptionUsed': True  # Flag to indicate data is encrypted
            }
        }
        
        # Insert or update submission
        if existing_submission:
            # Update existing submission
            db.kyc_submissions.update_one(
                {'userId': user_id},
                {
                    '$set': submission_data,
                    '$unset': {'verifiedAt': '', 'verifiedBy': '', 'rejectionReason': ''}
                }
            )
            submission_id = existing_submission['_id']
        else:
            # Create new submission
            result = db.kyc_submissions.insert_one(submission_data)
            submission_id = result.inserted_id
        
        # Update user status to show KYC submitted
        db.users.update_one(
            {'_id': user_id},
            {
                '$set': {
                    'kycStatus': 'SUBMITTED',
                    'kycSubmittedAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                }
            }
        )
        
        logger.info(f"KYC submitted internally for user {user_id}: {submission_type}")
        
        return jsonify({
            'success': True,
            'message': 'KYC information submitted successfully',
            'data': {
                'submissionId': str(submission_id),
                'status': 'SUBMITTED',
                'submittedAt': submission_data['submittedAt'].isoformat(),
                'message': 'Your KYC information is under review. You will be notified once verified.'
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Internal KYC submission error: {str(e)}")
        return jsonify({'success': False, 'message': 'Submission failed'}), 500

@internal_kyc_bp.route('/api/kyc/status', methods=['GET'])
def get_kyc_status():
    """Get user's KYC submission status"""
    try:
        user_id = get_current_user_id()
        
        # Get user's KYC submission
        submission = db.kyc_submissions.find_one({'userId': user_id})
        user = db.users.find_one({'_id': user_id})
        
        if not submission:
            return jsonify({
                'success': True,
                'data': {
                    'status': 'NOT_SUBMITTED',
                    'message': 'No KYC submission found'
                }
            }), 200
        
        status_messages = {
            'SUBMITTED': 'KYC information submitted and under review',
            'UNDER_REVIEW': 'KYC information is being reviewed by our team',
            'VERIFIED': 'KYC verified successfully',
            'REJECTED': f"KYC rejected: {submission.get('rejectionReason', 'Please resubmit')}"
        }
        
        return jsonify({
            'success': True,
            'data': {
                'submissionId': str(submission['_id']),
                'status': submission['status'],
                'submissionType': submission['submissionType'],
                'submittedAt': submission['submittedAt'].isoformat(),
                'verifiedAt': submission.get('verifiedAt').isoformat() if submission.get('verifiedAt') else None,
                'message': status_messages.get(submission['status'], 'Unknown status'),
                'canResubmit': submission['status'] in ['REJECTED']
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get KYC status error: {str(e)}")
        return jsonify({'success': False, 'message': 'Failed to get status'}), 500

# Admin endpoints for KYC management
@internal_kyc_bp.route('/api/admin/kyc/pending', methods=['GET'])
def get_pending_kyc_submissions():
    """Get all pending KYC submissions for admin review"""
    try:
        # Check admin permissions
        if not is_admin_user():
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        
        submissions = list(db.kyc_submissions.find({
            'status': {'$in': ['SUBMITTED', 'UNDER_REVIEW']}
        }).sort('submittedAt', 1))
        
        # Enrich with user data and mask sensitive information
        for submission in submissions:
            user = db.users.find_one({'_id': submission['userId']})
            if user:
                submission['userEmail'] = user.get('email')
                submission['userPhone'] = user.get('phone')
                
            # Mask sensitive data for admin display
            if submission.get('bvnNumber'):
                submission['bvnNumberMasked'] = mask_sensitive_data(
                    decrypt_sensitive_data(submission['bvnNumber'])
                )
            if submission.get('ninNumber'):
                submission['ninNumberMasked'] = mask_sensitive_data(
                    decrypt_sensitive_data(submission['ninNumber'])
                )
                
            # Convert ObjectIds to strings
            submission['_id'] = str(submission['_id'])
            submission['userId'] = str(submission['userId'])
        
        return jsonify({
            'success': True,
            'data': {
                'submissions': submissions,
                'count': len(submissions)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get pending KYC error: {str(e)}")
        return jsonify({'success': False, 'message': 'Failed to get submissions'}), 500

@internal_kyc_bp.route('/api/admin/kyc/verify/<submission_id>', methods=['POST'])
def verify_kyc_submission(submission_id):
    """Admin endpoint to verify KYC submission"""
    try:
        if not is_admin_user():
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        
        admin_id = get_current_user_id()
        data = request.get_json()
        action = data.get('action')  # 'VERIFY' or 'REJECT'
        reason = data.get('reason', '')
        
        submission = db.kyc_submissions.find_one({'_id': ObjectId(submission_id)})
        if not submission:
            return jsonify({'success': False, 'message': 'Submission not found'}), 404
        
        if action == 'VERIFY':
            # Verify the submission
            db.kyc_submissions.update_one(
                {'_id': ObjectId(submission_id)},
                {
                    '$set': {
                        'status': 'VERIFIED',
                        'verifiedAt': datetime.utcnow(),
                        'verifiedBy': admin_id
                    }
                }
            )
            
            # Update user status
            db.users.update_one(
                {'_id': submission['userId']},
                {
                    '$set': {
                        'kycStatus': 'VERIFIED',
                        'bvnVerified': 'BVN' in submission.get('submissionType', ''),
                        'ninVerified': 'NIN' in submission.get('submissionType', ''),
                        'verifiedAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            message = 'KYC verified successfully'
            
        elif action == 'REJECT':
            # Reject the submission
            db.kyc_submissions.update_one(
                {'_id': ObjectId(submission_id)},
                {
                    '$set': {
                        'status': 'REJECTED',
                        'rejectionReason': reason,
                        'verifiedAt': datetime.utcnow(),
                        'verifiedBy': admin_id
                    }
                }
            )
            
            # Update user status
            db.users.update_one(
                {'_id': submission['userId']},
                {
                    '$set': {
                        'kycStatus': 'REJECTED',
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            message = 'KYC rejected'
            
        else:
            return jsonify({'success': False, 'message': 'Invalid action'}), 400
        
        return jsonify({
            'success': True,
            'message': message,
            'data': {'status': action.lower()}
        }), 200
        
    except Exception as e:
        logger.error(f"Verify KYC error: {str(e)}")
        return jsonify({'success': False, 'message': 'Verification failed'}), 500