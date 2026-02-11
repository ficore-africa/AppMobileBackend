"""
Internal KYC Management System - Zero Cost Solution
Handles KYC submissions internally without external API charges
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId
import logging
from utils.kyc_encryption import encrypt_sensitive_data, decrypt_sensitive_data, mask_sensitive_data

def init_internal_kyc_blueprint(mongo, token_required, serialize_doc):
    internal_kyc_bp = Blueprint('internal_kyc', __name__, url_prefix='/api/kyc')
    logger = logging.getLogger(__name__)

    @internal_kyc_bp.route('/submit-internal', methods=['POST'])
    @token_required
    def submit_kyc_internal(current_user):
        """Submit KYC data internally - NO external API calls, NO charges"""
        try:
            user_id = str(current_user['_id'])
            
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['submissionType']
            for field in required_fields:
                if field not in data:
                    return jsonify({'success': False, 'message': f'{field} is required'}), 400
            
            submission_type = data.get('submissionType')
            
            # Check if user already has a verified submission
            existing_submission = mongo.db.kyc_submissions.find_one({'userId': ObjectId(user_id)})
            if existing_submission and existing_submission.get('status') in ['VERIFIED']:
                return jsonify({
                    'success': False,
                    'message': 'KYC already verified',
                    'status': 'ALREADY_VERIFIED'
                }), 400
            
            # Create KYC submission record with encrypted sensitive data
            submission_data = {
                'userId': ObjectId(user_id),
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
            
            # CRITICAL FIX: Update user profile with BVN/NIN for pre-population
            # This ensures the data is available for:
            # 1. Pre-population in VAS BVN verification screen
            # 2. Backend auto-retry logic when creating reserved accounts
            # 3. Unified verification status checks
            user_profile_update = {
                'kycStatus': 'SUBMITTED',
                'kycSubmittedAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            # Add BVN to user profile if provided (unencrypted for backend logic)
            if data.get('bvnNumber', '').strip():
                user_profile_update['bvn'] = data.get('bvnNumber', '').strip()
                logger.info(f"Updated user profile with BVN for user {user_id}")
            
            # Add NIN to user profile if provided (unencrypted for backend logic)
            if data.get('ninNumber', '').strip():
                user_profile_update['nin'] = data.get('ninNumber', '').strip()
                logger.info(f"Updated user profile with NIN for user {user_id}")
            
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': user_profile_update}
            )
            
            logger.info(f"KYC submitted internally for user {user_id} - NO external charges")
            
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
            
        except Exception as e:
            logger.error(f"Error submitting KYC: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to submit KYC information',
                'errors': {'general': [str(e)]}
            }), 500

    @internal_kyc_bp.route('/status', methods=['GET'])
    @token_required
    def get_kyc_status(current_user):
        """Get user's KYC submission status"""
        try:
            user_id = str(current_user['_id'])
            
            # Get KYC submission
            submission = mongo.db.kyc_submissions.find_one({'userId': ObjectId(user_id)})
            
            if not submission:
                return jsonify({
                    'success': True,
                    'data': {
                        'status': 'NOT_SUBMITTED',
                        'message': 'No KYC submission found'
                    }
                }), 200
            
            # Return status without sensitive data
            response_data = {
                'submissionId': str(submission['_id']),
                'status': submission.get('status', 'UNKNOWN'),
                'submissionType': submission.get('submissionType'),
                'submittedAt': submission.get('submittedAt').isoformat() + 'Z' if submission.get('submittedAt') else None,
                'verifiedAt': submission.get('verifiedAt').isoformat() + 'Z' if submission.get('verifiedAt') else None,
                'rejectionReason': submission.get('rejectionReason'),
                'firstName': submission.get('firstName'),
                'lastName': submission.get('lastName'),
                'phoneNumber': submission.get('phoneNumber'),
                # Mask sensitive data
                'bvnNumber': mask_sensitive_data(decrypt_sensitive_data(submission.get('bvnNumber', ''))),
                'ninNumber': mask_sensitive_data(decrypt_sensitive_data(submission.get('ninNumber', ''))),
            }
            
            return jsonify({
                'success': True,
                'data': response_data
            }), 200
            
        except Exception as e:
            logger.error(f"Error getting KYC status: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get KYC status',
                'errors': {'general': [str(e)]}
            }), 500

    return internal_kyc_bp