"""
Internal KYC Management System - Zero Cost Solution
Handles KYC submissions internally without external API charges
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
            
            # RATE LIMITING: Check recent submissions (max 3 per day)
            from datetime import timedelta
            recent_submissions = mongo.db.kyc_submissions.count_documents({
                'userId': ObjectId(user_id),
                'submittedAt': {'$gte': datetime.utcnow() - timedelta(days=1)}
            })
            
            if recent_submissions >= 3:
                logger.warning(f"Rate limit exceeded for user {user_id}: {recent_submissions} submissions in 24h")
                return jsonify({
                    'success': False,
                    'message': 'Too many KYC submissions',
                    'userMessage': {
                        'title': 'Submission Limit Reached',
                        'message': 'You can only submit KYC 3 times per day. Please wait 24 hours or contact support if you need help.',
                        'type': 'warning'
                    },
                    'errors': {'rateLimit': ['Maximum 3 submissions per 24 hours']}
                }), 429  # Too Many Requests
            
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
    
    @internal_kyc_bp.route('/failed-verifications', methods=['GET'])
    @token_required
    def get_failed_verifications(current_user):
        """Get list of failed KYC verifications for admin review (admin only)"""
        try:
            # Check if user is admin
            if not current_user.get('isAdmin', False):
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized - Admin access required'
                }), 403
            
            # Get query parameters
            status = request.args.get('status', 'pending_review')
            limit = int(request.args.get('limit', 50))
            skip = int(request.args.get('skip', 0))
            
            # Build query
            query = {}
            if status != 'all':
                query['status'] = status
            
            # CRITICAL FIX: Check if collection exists first
            # Collection is created automatically when first failed verification is recorded
            # If it doesn't exist yet, return empty array instead of error
            collection_exists = 'failed_kyc_verifications' in mongo.db.list_collection_names()
            
            if not collection_exists:
                # Collection doesn't exist yet - return empty result
                logger.info("failed_kyc_verifications collection doesn't exist yet - returning empty result")
                return jsonify({
                    'success': True,
                    'data': {
                        'failedVerifications': [],
                        'totalCount': 0,
                        'limit': limit,
                        'skip': skip
                    },
                    'message': 'No failed verifications yet (collection not created)'
                }), 200
            
            # Get failed verifications
            failed_verifications = list(mongo.db.failed_kyc_verifications.find(query)
                .sort('failedAt', -1)
                .limit(limit)
                .skip(skip))
            
            # Get total count
            total_count = mongo.db.failed_kyc_verifications.count_documents(query)
            
            # Serialize
            serialized = []
            for fv in failed_verifications:
                serialized.append({
                    '_id': str(fv['_id']),
                    'userId': str(fv['userId']),
                    'userEmail': fv.get('userEmail', 'unknown'),
                    'userName': fv.get('userName', 'Unknown'),
                    'bvnMasked': fv.get('bvnMasked', 'N/A'),
                    'ninMasked': fv.get('ninMasked', 'N/A'),
                    'monnifyError': fv.get('monnifyError', 'Unknown error'),
                    'monnifyErrorCode': fv.get('monnifyErrorCode', '99'),
                    'failedAt': fv.get('failedAt').isoformat() + 'Z' if fv.get('failedAt') else None,
                    'source': fv.get('source', 'unknown'),
                    'status': fv.get('status', 'pending_review'),
                    'notified': fv.get('notified', False),
                    'notifiedAt': fv.get('notifiedAt').isoformat() + 'Z' if fv.get('notifiedAt') else None
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'failedVerifications': serialized,
                    'totalCount': total_count,
                    'limit': limit,
                    'skip': skip
                },
                'message': f'Found {len(serialized)} failed verifications'
            }), 200
            
        except Exception as e:
            logger.error(f"Error getting failed verifications: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get failed verifications',
                'errors': {'general': [str(e)]}
            }), 500
    
    @internal_kyc_bp.route('/failed-verifications/<verification_id>/notify', methods=['POST'])
    @token_required
    def notify_failed_verification(current_user, verification_id):
        """Mark failed verification as notified (admin only)"""
        try:
            # Check if user is admin
            if not current_user.get('isAdmin', False):
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized - Admin access required'
                }), 403
            
            # Update verification
            result = mongo.db.failed_kyc_verifications.update_one(
                {'_id': ObjectId(verification_id)},
                {
                    '$set': {
                        'notified': True,
                        'notifiedAt': datetime.utcnow(),
                        'notifiedBy': str(current_user['_id'])
                    }
                }
            )
            
            if result.modified_count == 0:
                return jsonify({
                    'success': False,
                    'message': 'Verification not found or already notified'
                }), 404
            
            return jsonify({
                'success': True,
                'message': 'Verification marked as notified'
            }), 200
            
        except Exception as e:
            logger.error(f"Error marking verification as notified: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to mark verification as notified',
                'errors': {'general': [str(e)]}
            }), 500
    
    @internal_kyc_bp.route('/failed-verifications/export', methods=['GET'])
    @token_required
    def export_failed_verifications(current_user):
        """Export failed verifications as CSV for bulk email (admin only)"""
        try:
            # Check if user is admin
            if not current_user.get('isAdmin', False):
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized - Admin access required'
                }), 403
            
            # Get all pending failed verifications
            failed_verifications = list(mongo.db.failed_kyc_verifications.find({
                'status': 'pending_review'
            }).sort('failedAt', -1))
            
            # Build CSV
            import io
            import csv
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['Email', 'Name', 'BVN (Masked)', 'NIN (Masked)', 'Error', 'Failed At'])
            
            # Rows
            for fv in failed_verifications:
                writer.writerow([
                    fv.get('userEmail', 'unknown'),
                    fv.get('userName', 'Unknown'),
                    fv.get('bvnMasked', 'N/A'),
                    fv.get('ninMasked', 'N/A'),
                    fv.get('monnifyError', 'Unknown error'),
                    fv.get('failedAt').strftime('%Y-%m-%d %H:%M:%S') if fv.get('failedAt') else 'N/A'
                ])
            
            # Return CSV
            from flask import Response
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=failed_kyc_verifications.csv'}
            )
            
        except Exception as e:
            logger.error(f"Error exporting failed verifications: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to export failed verifications',
                'errors': {'general': [str(e)]}
            }), 500

    return internal_kyc_bp