from flask import Blueprint, request, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from bson import ObjectId
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.pdf_generator import PDFGenerator
from utils.profile_picture_helper import generate_profile_picture_url as _generate_profile_picture_url

users_bp = Blueprint('users', __name__, url_prefix='/users')

def init_users_blueprint(mongo, token_required):
    """Initialize the users blueprint with database and auth decorator"""
    from utils.analytics_tracker import create_tracker
    users_bp.mongo = mongo
    users_bp.token_required = token_required
    users_bp.tracker = create_tracker(mongo.db)
    return users_bp

@users_bp.route('/profile', methods=['GET'])
def get_profile():
    @users_bp.token_required
    def _get_profile(current_user):
        try:
            user_data = {
                'id': str(current_user['_id']),
                'email': current_user['email'],
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'displayName': current_user.get('displayName', ''),
                # Provide `name` for client compatibility (mirrors displayName)
                'name': current_user.get('displayName', ''),
                'phone': current_user.get('phone', ''),
                'address': current_user.get('address', ''),
                'dateOfBirth': current_user.get('dateOfBirth', ''),
                'role': current_user.get('role', 'personal'),
                'ficoreCreditBalance': current_user.get('ficoreCreditBalance', 0.0),
                'setupComplete': current_user.get('setupComplete', False),
                'financialGoals': current_user.get('financialGoals', []),
                'createdAt': current_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                'lastLogin': current_user.get('lastLogin', datetime.utcnow()).isoformat() + 'Z' if current_user.get('lastLogin') else None,
                # CRITICAL FIX: Generate URL for profile picture from GCS or GridFS
                'profilePictureUrl': _generate_profile_picture_url(current_user),
                'businessName': current_user.get('businessName'),
                'businessType': current_user.get('businessType'),
                'businessTypeOther': current_user.get('businessTypeOther'),
                'industry': current_user.get('industry'),
                'numberOfEmployees': current_user.get('numberOfEmployees'),
                'physicalAddress': current_user.get('physicalAddress'),
                'taxIdentificationNumber': current_user.get('taxIdentificationNumber'),
                'socialMediaLinks': current_user.get('socialMediaLinks'),
                'profileCompletionPercentage': current_user.get('profileCompletionPercentage', 0),
                # Add subscription information to profile
                'isSubscribed': current_user.get('isSubscribed', False),
                'subscriptionType': current_user.get('subscriptionType'),
                'subscriptionStartDate': current_user.get('subscriptionStartDate').isoformat() + 'Z' if current_user.get('subscriptionStartDate') else None,
                'subscriptionEndDate': current_user.get('subscriptionEndDate').isoformat() + 'Z' if current_user.get('subscriptionEndDate') else None,
                'subscriptionAutoRenew': current_user.get('subscriptionAutoRenew', False),
                # CRITICAL FIX: Add BVN/NIN fields for verification status and pre-population
                # These are needed for:
                # 1. Pre-populating BVN/NIN verification form if user returns
                # 2. Checking verification status in frontend
                # 3. Unified verification system checks
                'bvn': current_user.get('bvn'),
                'nin': current_user.get('nin'),
                'kycStatus': current_user.get('kycStatus', 'not_submitted'),
                'bvnVerified': current_user.get('bvnVerified', False),
                'ninVerified': current_user.get('ninVerified', False),
                'kycVerified': current_user.get('kycVerified', False),
                'kycVerifiedAt': current_user.get('kycVerifiedAt').isoformat() + 'Z' if current_user.get('kycVerifiedAt') else None,
                'kycSubmittedAt': current_user.get('kycSubmittedAt').isoformat() + 'Z' if current_user.get('kycSubmittedAt') else None,
            }
            
            return jsonify({
                'success': True,
                'data': user_data,
                'message': 'Profile retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve profile',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_profile()

@users_bp.route('/profile-picture/<gridfs_id>', methods=['GET'])
def get_profile_picture(gridfs_id):
    """Serve profile picture from GridFS"""
    try:
        import gridfs
        from bson import ObjectId
        from io import BytesIO
        
        fs = gridfs.GridFS(users_bp.mongo.db)
        
        # Get file from GridFS
        try:
            file_data = fs.get(ObjectId(gridfs_id))
        except gridfs.NoFile:
            return jsonify({
                'success': False,
                'message': 'Profile picture not found'
            }), 404
        
        # Return image file
        return send_file(
            BytesIO(file_data.read()),
            mimetype=file_data.content_type or 'image/jpeg',
            as_attachment=False
        )
        
    except Exception as e:
        print(f"❌ Error serving GridFS profile picture: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve profile picture'
        }), 500

@users_bp.route('/profile', methods=['PUT'])
def update_profile():
    @users_bp.token_required
    def _update_profile(current_user):
        try:
            data = request.get_json()
            
            # Fields that can be updated
            updatable_fields = ['firstName', 'lastName', 'phone', 'address', 'dateOfBirth', 'displayName', 'bvn', 'nin']
            update_data = {}
            
            for field in updatable_fields:
                if field in data:
                    update_data[field] = data[field]
            
            # Handle financial goals update with validation
            if 'financialGoals' in data:
                financial_goals = data['financialGoals']
                # Allow expanded list of goals including business-focused keys
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
                
                if isinstance(financial_goals, list):
                    # Allow empty list (user can clear all goals)
                    if len(financial_goals) == 0:
                        update_data['financialGoals'] = financial_goals
                    else:
                        invalid_goals = [goal for goal in financial_goals if goal not in valid_goals]
                        if not invalid_goals:
                            update_data['financialGoals'] = financial_goals
                        else:
                            return jsonify({
                                'success': False,
                                'message': 'Invalid financial goals',
                                'errors': {'financialGoals': [f'Invalid goals: {", ".join(invalid_goals)}']}
                            }), 400
                else:
                    return jsonify({
                        'success': False,
                        'message': 'Financial goals must be an array',
                        'errors': {'financialGoals': ['Financial goals must be an array']}
                    }), 400
            
            # Update display name if first or last name changed
            if 'firstName' in update_data or 'lastName' in update_data:
                first_name = update_data.get('firstName', current_user.get('firstName', ''))
                last_name = update_data.get('lastName', current_user.get('lastName', ''))
                update_data['displayName'] = f"{first_name} {last_name}".strip()
            
            if update_data:
                update_data['updatedAt'] = datetime.utcnow()
                users_bp.mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': update_data}
                )
                
                # Track profile update event
                try:
                    users_bp.tracker.track_profile_updated(
                        user_id=current_user['_id'],
                        fields_updated=list(update_data.keys())
                    )
                except Exception as e:
                    print(f"Analytics tracking failed: {e}")
            
            # Get updated user
            updated_user = users_bp.mongo.db.users.find_one({'_id': current_user['_id']})
            
            user_data = {
                'id': str(updated_user['_id']),
                'email': updated_user['email'],
                'firstName': updated_user.get('firstName', ''),
                'lastName': updated_user.get('lastName', ''),
                'displayName': updated_user.get('displayName', ''),
                # Provide `name` for client compatibility (mirrors displayName)
                'name': updated_user.get('displayName', ''),
                'phone': updated_user.get('phone', ''),
                'address': updated_user.get('address', ''),
                'dateOfBirth': updated_user.get('dateOfBirth', ''),
                'role': updated_user.get('role', 'personal'),
                'ficoreCreditBalance': updated_user.get('ficoreCreditBalance', 0.0),
                'setupComplete': updated_user.get('setupComplete', False),
                'financialGoals': updated_user.get('financialGoals', []),
                'createdAt': updated_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                'lastLogin': updated_user.get('lastLogin', datetime.utcnow()).isoformat() + 'Z' if updated_user.get('lastLogin') else None,
                # CRITICAL FIX: Generate profile picture URL from GCS or GridFS
                'profilePictureUrl': _generate_profile_picture_url(updated_user),
                'businessName': updated_user.get('businessName'),
                'businessType': updated_user.get('businessType'),
                'industry': updated_user.get('industry')
            }
            
            return jsonify({
                'success': True,
                'data': user_data,
                'message': 'Profile updated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update profile',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _update_profile()

@users_bp.route('/setup', methods=['POST'])
def setup_profile():
    @users_bp.token_required
    def _setup_profile(current_user):
        try:
            data = request.get_json()
            
            setup_data = {
                'phone': data.get('phone', ''),
                'address': data.get('address', ''),
                'dateOfBirth': data.get('dateOfBirth', ''),
                'currency': data.get('currency', 'NGN'),
                'language': data.get('language', 'en'),
                'setupComplete': True,
                'setupCompletedAt': datetime.utcnow()
            }
            
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': setup_data}
            )
            
            return jsonify({
                'success': True,
                'message': 'Profile setup completed successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Profile setup failed',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _setup_profile()

@users_bp.route('/change-password', methods=['POST'])
def change_password():
    @users_bp.token_required
    def _change_password(current_user):
        try:
            data = request.get_json()
            current_password = data.get('currentPassword')
            new_password = data.get('newPassword')
            
            errors = {}
            
            if not current_password:
                errors['currentPassword'] = ['Current password is required']
            elif not check_password_hash(current_user['password'], current_password):
                errors['currentPassword'] = ['Current password is incorrect']
                
            if not new_password:
                errors['newPassword'] = ['New password is required']
            elif len(new_password) < 6:
                errors['newPassword'] = ['Password must be at least 6 characters']
            elif current_password == new_password:
                errors['newPassword'] = ['New password must be different from current password']
            
            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400
            
            # Update password and clear mustChangePassword flag
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {
                    'password': generate_password_hash(new_password),
                    'passwordChangedAt': datetime.utcnow()
                }, '$unset': {
                    'mustChangePassword': ''  # Clear the forced password change flag
                }}
            )
            
            return jsonify({
                'success': True,
                'message': 'Password changed successfully',
                'data': None
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Password change failed',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _change_password()

@users_bp.route('/delete', methods=['DELETE'])
def delete_account():
    @users_bp.token_required
    def _delete_account(current_user):
        try:
            data = request.get_json()
            password = data.get('password')
            
            if not password:
                return jsonify({
                    'success': False,
                    'message': 'Password confirmation required',
                    'errors': {'password': ['Password is required to delete account']}
                }), 400
            
            if not check_password_hash(current_user['password'], password):
                return jsonify({
                    'success': False,
                    'message': 'Invalid password',
                    'errors': {'password': ['Password is incorrect']}
                }), 400
            
            # Soft delete - mark as inactive
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {
                    'isActive': False,
                    'deletedAt': datetime.utcnow()
                }}
            )
            
            return jsonify({
                'success': True,
                'message': 'Account deleted successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Account deletion failed',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _delete_account()


# ==================== ACCOUNT DELETION REQUESTS ====================
# Added: Jan 30, 2026 - Unified deletion request system for admin review

@users_bp.route('/deletion-request', methods=['POST'])
def request_account_deletion():
    @users_bp.token_required
    def _request_deletion(current_user):
        """
        Submit account deletion request.
        Creates a pending request for admin review.
        
        Body:
            - reason: Optional[str] - User's reason for deletion
            - appVersion: Optional[str] - App version for tracking
        
        Returns:
            - 201: Request created successfully
            - 400: User already has pending request
            - 500: Server error
        """
        try:
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            # Check if user already has pending request
            existing = users_bp.mongo.db.deletion_requests.find_one({
                'userId': current_user['_id'],
                'status': 'pending'
            })
            
            if existing:
                return jsonify({
                    'success': False,
                    'message': 'You already have a pending deletion request',
                    'data': {
                        'requestId': str(existing['_id']),
                        'requestedAt': existing['requestedAt'].isoformat() + 'Z',
                        'status': 'pending'
                    }
                }), 400
            
            # Get user statistics for snapshot
            income_count = users_bp.mongo.db.incomes.count_documents({'userId': current_user['_id']})
            expense_count = users_bp.mongo.db.expenses.count_documents({'userId': current_user['_id']})
            
            # Create deletion request
            deletion_request = {
                'userId': current_user['_id'],
                'email': current_user['email'],
                'userName': current_user.get('displayName') or f"{current_user.get('firstName', '')} {current_user.get('lastName', '')}".strip() or 'Unknown User',
                'reason': reason if reason else None,
                'status': 'pending',
                'requestedAt': datetime.utcnow(),
                'processedAt': None,
                'processedBy': None,
                'processingNotes': None,
                'completedAt': None,
                'userSnapshot': {
                    'ficoreCreditBalance': current_user.get('ficoreCreditBalance', 0.0),
                    'subscriptionStatus': current_user.get('subscriptionStatus'),
                    'subscriptionPlan': current_user.get('subscriptionPlan'),
                    'createdAt': current_user.get('createdAt'),
                    'lastLogin': current_user.get('lastLogin'),
                    'totalIncomes': income_count,
                    'totalExpenses': expense_count,
                    'totalTransactions': income_count + expense_count,
                    'kycStatus': current_user.get('kycStatus'),
                },
                'ipAddress': request.remote_addr,
                'userAgent': request.headers.get('User-Agent'),
                'appVersion': data.get('appVersion'),
            }
            
            result = users_bp.mongo.db.deletion_requests.insert_one(deletion_request)
            
            print(f'✅ Deletion request created: {result.inserted_id} for user {current_user["email"]}')
            
            # TODO: Send confirmation email to user
            # email_service.send_deletion_request_confirmation(current_user['email'])
            
            return jsonify({
                'success': True,
                'message': 'Account deletion request submitted successfully',
                'data': {
                    'requestId': str(result.inserted_id),
                    'status': 'pending',
                    'requestedAt': deletion_request['requestedAt'].isoformat() + 'Z',
                    'estimatedProcessingTime': '24-48 hours',
                    'message': 'Our team will review your request and send you a confirmation email.'
                }
            }), 201
            
        except Exception as e:
            print(f'❌ Error creating deletion request: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to submit deletion request',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _request_deletion()


@users_bp.route('/deletion-request/status', methods=['GET'])
def get_deletion_request_status():
    @users_bp.token_required
    def _get_status(current_user):
        """
        Check status of user's deletion request.
        Returns most recent request if exists.
        
        Returns:
            - 200: Status retrieved (may be null if no request)
            - 500: Server error
        """
        try:
            # Get most recent deletion request
            request_doc = users_bp.mongo.db.deletion_requests.find_one(
                {'userId': current_user['_id']},
                sort=[('requestedAt', -1)]  # Get most recent
            )
            
            if not request_doc:
                return jsonify({
                    'success': True,
                    'data': {
                        'hasRequest': False,
                        'status': None
                    }
                }), 200
            
            return jsonify({
                'success': True,
                'data': {
                    'hasRequest': True,
                    'requestId': str(request_doc['_id']),
                    'status': request_doc['status'],
                    'requestedAt': request_doc['requestedAt'].isoformat() + 'Z',
                    'processedAt': request_doc['processedAt'].isoformat() + 'Z' if request_doc.get('processedAt') else None,
                    'processingNotes': request_doc.get('processingNotes'),
                    'completedAt': request_doc['completedAt'].isoformat() + 'Z' if request_doc.get('completedAt') else None,
                }
            }), 200
            
        except Exception as e:
            print(f'❌ Error checking deletion request status: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to check deletion request status',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_status()


@users_bp.route('/settings', methods=['GET'])
def get_settings():
    @users_bp.token_required
    def _get_settings(current_user):
        try:
            settings = {
                'notifications': current_user.get('settings', {}).get('notifications', {
                    'push': True,
                    'email': True,
                    'budgetAlerts': True,
                    'expenseAlerts': True
                }),
                'privacy': current_user.get('settings', {}).get('privacy', {
                    'profileVisibility': 'private',
                    'dataSharing': False
                }),
                'preferences': current_user.get('settings', {}).get('preferences', {
                    'currency': 'NGN',
                    'language': 'en',
                    'theme': 'light',
                    'dateFormat': 'DD/MM/YYYY'
                })
            }
            
            return jsonify({
                'success': True,
                'data': settings,
                'message': 'Settings retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve settings',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_settings()

@users_bp.route('/settings', methods=['PUT'])
def update_settings():
    @users_bp.token_required
    def _update_settings(current_user):
        try:
            data = request.get_json()
            
            # Get current settings or default
            current_settings = current_user.get('settings', {})
            
            # Update settings
            if 'notifications' in data:
                current_settings['notifications'] = {**current_settings.get('notifications', {}), **data['notifications']}
            if 'privacy' in data:
                current_settings['privacy'] = {**current_settings.get('privacy', {}), **data['privacy']}
            if 'preferences' in data:
                current_settings['preferences'] = {**current_settings.get('preferences', {}), **data['preferences']}
            
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {
                    'settings': current_settings,
                    'settingsUpdatedAt': datetime.utcnow()
                }}
            )
            
            return jsonify({
                'success': True,
                'data': current_settings,
                'message': 'Settings updated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update settings',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _update_settings()

@users_bp.route('/settings/notifications', methods=['GET'])
def get_notification_settings():
    @users_bp.token_required
    def _get_notification_settings(current_user):
        try:
            notifications = current_user.get('settings', {}).get('notifications', {
                'push': True,
                'email': True,
                'budgetAlerts': True,
                'expenseAlerts': True,
                'incomeAlerts': True,
                'creditAlerts': True,
                'weeklyReports': True,
                'monthlyReports': True
            })
            
            return jsonify({
                'success': True,
                'data': {
                    'notifications': notifications
                },
                'message': 'Notification settings retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve notification settings',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_notification_settings()

@users_bp.route('/settings/notifications', methods=['PUT'])
def update_notification_settings():
    @users_bp.token_required
    def _update_notification_settings(current_user):
        try:
            data = request.get_json()
            
            # Get current settings
            current_settings = current_user.get('settings', {})
            current_notifications = current_settings.get('notifications', {})
            
            # Update notification settings
            updated_notifications = {**current_notifications, **data}
            current_settings['notifications'] = updated_notifications
            
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {
                    'settings': current_settings,
                    'settingsUpdatedAt': datetime.utcnow()
                }}
            )
            
            return jsonify({
                'success': True,
                'data': {
                    'notifications': updated_notifications
                },
                'message': 'Notification settings updated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update notification settings',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _update_notification_settings()

@users_bp.route('/settings/security', methods=['GET'])
def get_security_settings():
    @users_bp.token_required
    def _get_security_settings(current_user):
        try:
            security = current_user.get('settings', {}).get('security', {
                'biometricEnabled': False,
                'twoFactorEnabled': False,
                'sessionTimeout': 30,
                'loginNotifications': True
            })
            
            return jsonify({
                'success': True,
                'data': {
                    'security': security,
                    'lastPasswordChange': current_user.get('passwordChangedAt', current_user.get('createdAt', datetime.utcnow())).isoformat() + 'Z' if current_user.get('passwordChangedAt') else None
                },
                'message': 'Security settings retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve security settings',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_security_settings()

@users_bp.route('/settings/security', methods=['PUT'])
def update_security_settings():
    @users_bp.token_required
    def _update_security_settings(current_user):
        try:
            data = request.get_json()
            
            # Get current settings
            current_settings = current_user.get('settings', {})
            current_security = current_settings.get('security', {})
            
            # Update security settings
            updated_security = {**current_security, **data}
            current_settings['security'] = updated_security
            
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {
                    'settings': current_settings,
                    'settingsUpdatedAt': datetime.utcnow()
                }}
            )
            
            return jsonify({
                'success': True,
                'data': {
                    'security': updated_security
                },
                'message': 'Security settings updated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update security settings',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _update_security_settings()

@users_bp.route('/export-data', methods=['POST'])
def export_user_data():
    @users_bp.token_required
    def _export_user_data(current_user):
        try:
            data_type = request.get_json().get('type', 'all')  # all, budgets, expenses, incomes, credits
            
            export_data = {
                'user': {
                    'id': str(current_user['_id']),
                    'email': current_user['email'],
                    'firstName': current_user.get('firstName', ''),
                    'lastName': current_user.get('lastName', ''),
                    'exportedAt': datetime.utcnow().isoformat() + 'Z'
                }
            }
            
            if data_type in ['all', 'expenses']:
                expenses = list(users_bp.mongo.db.expenses.find({'userId': current_user['_id']}))
                export_data['expenses'] = []
                for expense in expenses:
                    expense_data = {
                        'id': str(expense['_id']),
                        'title': expense.get('title', ''),
                        'amount': expense.get('amount', 0),
                        'category': expense.get('category', ''),
                        'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z'
                    }
                    export_data['expenses'].append(expense_data)
            
            if data_type in ['all', 'incomes']:
                incomes = list(users_bp.mongo.db.incomes.find({'userId': current_user['_id']}))
                export_data['incomes'] = []
                for income in incomes:
                    income_data = {
                        'id': str(income['_id']),
                        'source': income.get('source', ''),
                        'amount': income.get('amount', 0),
                        'dateReceived': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
                    }
                    export_data['incomes'].append(income_data)
            
            if data_type in ['all', 'credits']:
                credit_transactions = list(users_bp.mongo.db.credit_transactions.find({'userId': current_user['_id']}))
                export_data['creditTransactions'] = []
                for transaction in credit_transactions:
                    transaction_data = {
                        'id': str(transaction['_id']),
                        'type': transaction.get('type', ''),
                        'amount': transaction.get('amount', 0),
                        'description': transaction.get('description', ''),
                        'createdAt': transaction.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                    }
                    export_data['creditTransactions'].append(transaction_data)
            
            return jsonify({
                'success': True,
                'data': {
                    'exportData': export_data,
                    'downloadUrl': f'/users/download-export/{str(current_user["_id"])}',
                    'expiresAt': (datetime.utcnow() + timedelta(hours=24)).isoformat() + 'Z'
                },
                'message': 'Data export prepared successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to export data',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _export_user_data()

@users_bp.route('/export-pdf', methods=['POST'])
def export_pdf():
    """Export user data as PDF with credit deduction"""
    @users_bp.token_required
    def _export_pdf(current_user):
        try:
            request_data = request.get_json()
            data_type = request_data.get('type', 'all')  # all, expenses, incomes, credits
            
            # Define credit costs for different export types
            EXPORT_COSTS = {
                'expenses': 2,
                'incomes': 2,
                'credits': 2,
                'all': 2
            }
            
            credit_cost = EXPORT_COSTS.get(data_type, 2)
            current_balance = current_user.get('ficoreCreditBalance', 0.0)
            
            # Check if user has enough credits
            if current_balance < credit_cost:
                return jsonify({
                    'success': False,
                    'message': 'Insufficient credits',
                    'errors': {
                        'credits': [f'You need {credit_cost} FC to export this report. Current balance: {current_balance} FC']
                    },
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402  # Payment Required
            
            # Prepare export data
            export_data = {}
            
            if data_type in ['all', 'expenses']:
                expenses = list(users_bp.mongo.db.expenses.find({'userId': current_user['_id']}))
                export_data['expenses'] = []
                for expense in expenses:
                    expense_data = {
                        'id': str(expense['_id']),
                        'title': expense.get('title', ''),
                        'amount': expense.get('amount', 0),
                        'category': expense.get('category', ''),
                        'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z'
                    }
                    export_data['expenses'].append(expense_data)
            
            if data_type in ['all', 'incomes']:
                incomes = list(users_bp.mongo.db.incomes.find({'userId': current_user['_id']}))
                export_data['incomes'] = []
                for income in incomes:
                    income_data = {
                        'id': str(income['_id']),
                        'source': income.get('source', ''),
                        'amount': income.get('amount', 0),
                        'dateReceived': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
                    }
                    export_data['incomes'].append(income_data)
            
            if data_type in ['all', 'credits']:
                credit_transactions = list(users_bp.mongo.db.credit_transactions.find({'userId': current_user['_id']}))
                export_data['creditTransactions'] = []
                for transaction in credit_transactions:
                    transaction_data = {
                        'id': str(transaction['_id']),
                        'type': transaction.get('type', ''),
                        'amount': transaction.get('amount', 0),
                        'description': transaction.get('description', ''),
                        'createdAt': transaction.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                    }
                    export_data['creditTransactions'].append(transaction_data)
            
            # Generate PDF
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_financial_report(user_data, export_data, data_type)
            
            # Deduct credits from user balance
            new_balance = current_balance - credit_cost
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {'ficoreCreditBalance': new_balance}}
            )
            
            # Record credit transaction
            credit_transaction = {
                'userId': current_user['_id'],
                'type': 'deduction',
                'amount': -credit_cost,
                'description': f'PDF Export - {data_type.upper()}',
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'status': 'completed',
                'createdAt': datetime.utcnow()
            }
            users_bp.mongo.db.credit_transactions.insert_one(credit_transaction)
            
            # Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_report_{data_type}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to generate PDF export',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _export_pdf()

@users_bp.route('/support', methods=['GET'])
def get_support_info():
    @users_bp.token_required
    def _get_support_info(current_user):
        try:
            support_info = {
                'email': 'ficoreafrica@gmail.com',
                'subject': 'Support Request - Ficore Mobile App',
                'message': 'Need support? Reach ficoreafrica@gmail.com for inquiries',
                'faq': [
                    {
                        'question': 'How do I request FiCore Credits?',
                        'answer': 'Go to the Credits section and tap Request to submit a credit top-up request.'
                    },
                    {
                        'question': 'How do I track my expenses?',
                        'answer': 'Use the Expenses section to add and categorize your spending.'
                    },
                    {
                        'question': 'Can I export my financial data?',
                        'answer': 'Yes, go to Settings > Export Data to download your financial reports.'
                    }
                ],
                'appVersion': '1.0.0',
                'lastUpdated': datetime.utcnow().isoformat() + 'Z'
            }
            
            return jsonify({
                'success': True,
                'data': support_info,
                'message': 'Support information retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve support information',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_support_info()

# ==================== FCM TOKEN MANAGEMENT ====================
# Added: Feb 20, 2026 - FCM Production Readiness (Fix 2)

@users_bp.route('/fcm-token', methods=['POST'])
def update_fcm_token():
    """
    Update user's FCM token for push notifications
    
    Request Body:
    {
        "fcmToken": "string"
    }
    
    Returns:
        - 200: Token updated successfully
        - 400: Invalid request (missing token)
        - 500: Server error
    """
    @users_bp.token_required
    def _update_fcm_token(current_user):
        try:
            data = request.get_json()
            fcm_token = data.get('fcmToken')
            
            if not fcm_token:
                return jsonify({
                    'success': False,
                    'message': 'FCM token is required'
                }), 400
            
            # Update user's FCM token
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {
                    '$set': {
                        'fcmToken': fcm_token,
                        'fcmTokenUpdatedAt': datetime.utcnow()
                    }
                }
            )
            
            print(f"✓ FCM token updated for user {current_user['email']}: {fcm_token[:20]}...")
            
            return jsonify({
                'success': True,
                'message': 'FCM token updated successfully',
                'data': {
                    'tokenUpdatedAt': datetime.utcnow().isoformat() + 'Z'
                }
            }), 200
            
        except Exception as e:
            print(f"✗ Error updating FCM token: {e}")
            return jsonify({
                'success': False,
                'message': f'Failed to update FCM token: {str(e)}'
            }), 500
    
    return _update_fcm_token()


@users_bp.route('/fcm-token', methods=['DELETE'])
def delete_fcm_token():
    """
    Delete user's FCM token (called on logout)
    
    Returns:
        - 200: Token deleted successfully
        - 500: Server error
    """
    @users_bp.token_required
    def _delete_fcm_token(current_user):
        try:
            # Remove FCM token from user
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {
                    '$unset': {
                        'fcmToken': '',
                        'fcmTokenUpdatedAt': ''
                    }
                }
            )
            
            print(f"✓ FCM token deleted for user {current_user['email']}")
            
            return jsonify({
                'success': True,
                'message': 'FCM token deleted successfully'
            }), 200
            
        except Exception as e:
            print(f"✗ Error deleting FCM token: {e}")
            return jsonify({
                'success': False,
                'message': f'Failed to delete FCM token: {str(e)}'
            }), 500
    
    return _delete_fcm_token()

# ==================== END FCM TOKEN MANAGEMENT ====================

@users_bp.route('/financial-goals', methods=['GET'])
def get_financial_goals():
    @users_bp.token_required
    def _get_financial_goals(current_user):
        try:
            financial_goals = current_user.get('financialGoals', [])
            
            # Available goals with descriptions
            # Updated available goals to avoid investment/savings/budget wording and include business-focused goals
            available_goals = {
                'save_for_emergencies': 'Build a safety fund',
                'pay_off_debt': 'Pay off debt',
                'track_income_expenses': 'Track income & expenses',
                'plan_big_purchases': 'Plan for big purchases',
                'improve_financial_habits': 'Improve financial habits',
                'manage_business_finances': 'Manage Business Finances',
                'know_my_profit': 'Know My Profit'
            }
            
            return jsonify({
                'success': True,
                'data': {
                    'selectedGoals': financial_goals,
                    'availableGoals': available_goals
                },
                'message': 'Financial goals retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve financial goals',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_financial_goals()

@users_bp.route('/financial-goals', methods=['PUT'])
def update_financial_goals():
    @users_bp.token_required
    def _update_financial_goals(current_user):
        try:
            data = request.get_json()
            financial_goals = data.get('financialGoals', [])
            
            # Validate financial goals
            # Validation list updated to reflect frontend changes (no budget/investment wording)
            valid_goals = [
                'save_for_emergencies',
                'pay_off_debt',
                'track_income_expenses',
                'plan_big_purchases',
                'improve_financial_habits',
                'manage_business_finances',
                'know_my_profit'
            ]
            
            if not isinstance(financial_goals, list):
                return jsonify({
                    'success': False,
                    'message': 'Financial goals must be an array',
                    'errors': {'financialGoals': ['Financial goals must be an array']}
                }), 400
            
            invalid_goals = [goal for goal in financial_goals if goal not in valid_goals]
            if invalid_goals:
                return jsonify({
                    'success': False,
                    'message': 'Invalid financial goals',
                    'errors': {'financialGoals': [f'Invalid goals: {", ".join(invalid_goals)}']}
                }), 400
            
            # Update user's financial goals
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {
                    'financialGoals': financial_goals,
                    'goalsUpdatedAt': datetime.utcnow()
                }}
            )
            
            return jsonify({
                'success': True,
                'data': {
                    'financialGoals': financial_goals
                },
                'message': 'Financial goals updated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update financial goals',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _update_financial_goals()

@users_bp.route('/profile/complete', methods=['PUT'])
def complete_profile():
    @users_bp.token_required
    def _complete_profile(current_user):
        try:
            data = request.get_json()
            print(f"Profile completion request from user {current_user['email']}: {data}")
            
            # Profile completion fields
            # CRITICAL FIX: Removed 'profilePictureUrl' from profile fields
            # Profile pictures are handled separately via GCS upload endpoint
            # The upload endpoint stores gcsProfilePicturePath in user document
            # Profile retrieval generates fresh signed URLs from that path
            profile_fields = [
                'businessName', 'businessType', 'businessTypeOther', 'industry',
                'physicalAddress', 'taxIdentificationNumber',
                'socialMediaLinks', 'numberOfEmployees'
            ]
            
            update_data = {}
            
            # Validate numberOfEmployees if provided
            if 'numberOfEmployees' in data:
                num_employees = data['numberOfEmployees']
                if num_employees is not None:
                    if not isinstance(num_employees, int) or num_employees < 0:
                        return jsonify({
                            'success': False,
                            'message': 'Number of employees must be a non-negative integer (0 or greater)',
                            'errors': {'numberOfEmployees': ['Must be 0 or a positive number']}
                        }), 400
            
            # Update profile fields
            for field in profile_fields:
                if field in data:
                    update_data[field] = data[field]
            
            # CRITICAL FIX: Ignore profilePictureUrl if sent by client
            # The signed URL from upload is temporary and will expire
            # We rely on gcsProfilePicturePath which is set by upload endpoint
            if 'profilePictureUrl' in data:
                print(f"Ignoring profilePictureUrl from client (temporary signed URL)")
                print(f"Using gcsProfilePicturePath from upload endpoint instead")
            
            # Calculate completion percentage
            user = users_bp.mongo.db.users.find_one({'_id': current_user['_id']})
            total_fields = len(profile_fields)
            completed_fields = 0
            
            for field in profile_fields:
                value = data.get(field) if field in data else user.get(field)
                # Special handling for numberOfEmployees - 0 is a valid value
                if field == 'numberOfEmployees':
                    if value is not None and isinstance(value, int) and value >= 0:
                        completed_fields += 1
                elif value is not None and value != '' and value != {}:
                    completed_fields += 1
            
            completion_percentage = (completed_fields / total_fields) * 100
            update_data['profileCompletionPercentage'] = completion_percentage
            update_data['updatedAt'] = datetime.utcnow()
            
            # Update user profile
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': update_data}
            )
            
            # Check if profile is sufficiently complete (at least 5 fields)
            if completed_fields >= 5:
                # Track profile completion activity for rewards - directly in database
                try:
                    # Check if user has already earned this reward
                    existing_activity = users_bp.mongo.db.activities.find_one({
                        'userId': current_user['_id'],
                        'action': 'complete_profile',
                        'module': 'profile'
                    })
                    
                    if not existing_activity:
                        # Record the activity
                        activity_data = {
                            'userId': current_user['_id'],
                            'action': 'complete_profile',
                            'module': 'profile',
                            'timestamp': datetime.utcnow(),
                            'metadata': {
                                'completedFields': completed_fields,
                                'completionPercentage': completion_percentage
                            }
                        }
                        users_bp.mongo.db.activities.insert_one(activity_data)
                        
                        # Award credits directly (10 credits for profile completion)
                        users_bp.mongo.db.users.update_one(
                            {'_id': current_user['_id']},
                            {'$inc': {'ficoreCreditBalance': 10.0}}
                        )
                        
                        print(f"Profile completion reward granted: 10 credits to user {current_user['email']}")
                    else:
                        print(f"User {current_user['email']} has already earned profile completion reward")
                        
                except Exception as tracking_error:
                    print(f"Error tracking profile completion: {str(tracking_error)}")
                    # Don't fail the profile update if tracking fails
            
            print(f"Profile completion successful for user {current_user['email']}: {completed_fields}/{total_fields} fields")
            
            return jsonify({
                'success': True,
                'data': {
                    'profileCompletionPercentage': completion_percentage,
                    'completedFields': completed_fields,
                    'totalFields': total_fields,
                    'rewardEligible': completed_fields >= 5
                },
                'message': 'Profile updated successfully'
            })
            
        except Exception as e:
            print(f"Profile completion error for user {current_user['email']}: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to update profile',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _complete_profile()

@users_bp.route('/profile/completion-status', methods=['GET'])
def get_profile_completion_status():
    @users_bp.token_required
    def _get_profile_completion_status(current_user):
        try:
            user = users_bp.mongo.db.users.find_one({'_id': current_user['_id']})
            
            # Profile completion fields
            profile_fields = [
                'businessName', 'businessType', 'industry',
                'physicalAddress', 'taxIdentificationNumber', 'profilePictureUrl',
                'socialMediaLinks', 'numberOfEmployees'
            ]
            
            completed_fields = 0
            field_status = {}
            
            for field in profile_fields:
                value = user.get(field)
                is_completed = value is not None and value != '' and value != {}
                field_status[field] = {
                    'completed': is_completed,
                    'value': value if is_completed else None
                }
                if is_completed:
                    completed_fields += 1
            
            total_fields = len(profile_fields)
            completion_percentage = (completed_fields / total_fields) * 100
            
            return jsonify({
                'success': True,
                'data': {
                    'completionPercentage': completion_percentage,
                    'completedFields': completed_fields,
                    'totalFields': total_fields,
                    'fieldStatus': field_status,
                    'rewardEligible': completed_fields >= 5,
                    'rewardClaimed': user.get('earned_profile_complete_bonus', False)
                },
                'message': 'Profile completion status retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve profile completion status',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_profile_completion_status()


# ==================== TAX PROFILE ENDPOINTS ====================
# Added: Feb 5, 2026 - Phase 2: Tax Jurisdiction Wizard

@users_bp.route('/tax-profile', methods=['POST'])
def save_tax_profile():
    @users_bp.token_required
    def _save_tax_profile(current_user):
        """
        Save user's tax profile from Tax Jurisdiction Wizard
        
        Body:
            - businessStructure: 'business_name' | 'llc' (required)
            - annualTurnover: number (optional, for LLCs)
        
        Returns:
            - 200: Tax profile saved successfully
            - 400: Validation error
            - 500: Server error
        """
        try:
            data = request.get_json()
            
            # Validate business structure
            business_structure = data.get('businessStructure')
            if not business_structure or business_structure not in ['personal_income', 'llc', 'professional_services']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid business structure',
                    'errors': {'businessStructure': ['Must be "personal_income", "llc", or "professional_services"']}
                }), 400
            
            # Get income/turnover based on structure
            annual_income = data.get('annualIncome')
            annual_turnover = data.get('annualTurnover')
            
            # Validate inputs based on structure
            if business_structure == 'personal_income' and annual_income is None:
                return jsonify({
                    'success': False,
                    'message': 'Annual income required for personal income',
                    'errors': {'annualIncome': ['Required for personal income structure']}
                }), 400
            
            if business_structure == 'llc' and annual_turnover is None:
                return jsonify({
                    'success': False,
                    'message': 'Annual turnover required for LLCs',
                    'errors': {'annualTurnover': ['Required for LLC business structure']}
                }), 400
            
            # Compute tax profile
            tax_profile = _compute_tax_profile(business_structure, annual_turnover, annual_income)
            tax_profile['completedAt'] = datetime.utcnow()
            tax_profile['lastUpdated'] = datetime.utcnow()
            
            # Save to database
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {'taxProfile': tax_profile}}
            )
            
            print(f'✅ Tax profile saved for user {current_user["email"]}: {business_structure}')
            
            return jsonify({
                'success': True,
                'data': {
                    'taxProfile': _serialize_tax_profile(tax_profile)
                },
                'message': 'Tax profile saved successfully'
            })
            
        except Exception as e:
            print(f'❌ Error saving tax profile: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to save tax profile',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _save_tax_profile()


@users_bp.route('/tax-profile', methods=['GET'])
def get_tax_profile():
    @users_bp.token_required
    def _get_tax_profile(current_user):
        """
        Get user's tax profile
        
        Returns:
            - 200: Tax profile retrieved (may be null if not set)
            - 500: Server error
        """
        try:
            tax_profile = current_user.get('taxProfile')
            
            return jsonify({
                'success': True,
                'data': {
                    'taxProfile': _serialize_tax_profile(tax_profile) if tax_profile else None
                },
                'message': 'Tax profile retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve tax profile',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_tax_profile()


@users_bp.route('/tax-profile/year-end', methods=['PUT'])
def save_company_year_end():
    @users_bp.token_required
    def _save_company_year_end(current_user):
        """
        Save company year-end for LLC users (Sprint 12)
        
        Body:
            - companyYearEnd: ISO date string (required)
        
        Returns:
            - 200: Year-end saved successfully with calculated CIT deadline
            - 400: Validation error
            - 500: Server error
        """
        try:
            data = request.get_json()
            
            # Validate year-end date
            year_end_str = data.get('companyYearEnd')
            if not year_end_str:
                return jsonify({
                    'success': False,
                    'message': 'Company year-end required',
                    'errors': {'companyYearEnd': ['Required field']}
                }), 400
            
            # Parse date
            try:
                year_end = datetime.fromisoformat(year_end_str.replace('Z', '+00:00'))
            except ValueError:
                return jsonify({
                    'success': False,
                    'message': 'Invalid date format',
                    'errors': {'companyYearEnd': ['Must be valid ISO date string']}
                }), 400
            
            # Get user's tax profile
            tax_profile = current_user.get('taxProfile', {})
            
            # Verify user is LLC
            if tax_profile.get('businessStructure') != 'llc':
                return jsonify({
                    'success': False,
                    'message': 'Year-end only applicable for LLCs',
                    'errors': {'general': ['This feature is only for LLC business structure']}
                }), 400
            
            # Calculate CIT deadline (year-end + 6 months)
            year_end_month = year_end.month
            year_end_day = year_end.day
            year_end_year = year_end.year
            
            # Add 6 months
            cit_month = year_end_month + 6
            cit_year = year_end_year
            if cit_month > 12:
                cit_month -= 12
                cit_year += 1
            
            # Handle day overflow (e.g., Aug 31 + 6 months = Feb 28/29)
            import calendar
            max_day = calendar.monthrange(cit_year, cit_month)[1]
            cit_day = min(year_end_day, max_day)
            
            cit_deadline = datetime(cit_year, cit_month, cit_day)
            
            # Update tax profile
            tax_profile['companyYearEnd'] = year_end
            tax_profile['citDeadline'] = cit_deadline
            tax_profile['lastUpdated'] = datetime.utcnow()
            
            # Save to database
            users_bp.mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {'taxProfile': tax_profile}}
            )
            
            print(f'✅ Company year-end saved for user {current_user["email"]}: {year_end.date()} → CIT deadline: {cit_deadline.date()}')
            
            return jsonify({
                'success': True,
                'data': {
                    'companyYearEnd': year_end.isoformat() + 'Z',
                    'citDeadline': cit_deadline.isoformat() + 'Z',
                    'taxProfile': _serialize_tax_profile(tax_profile)
                },
                'message': 'Company year-end saved successfully'
            })
            
        except Exception as e:
            print(f'❌ Error saving company year-end: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to save company year-end',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _save_company_year_end()


@users_bp.route('/tax-estimate', methods=['POST'])
def calculate_tax_estimate():
    @users_bp.token_required
    def _calculate_tax_estimate(current_user):
        """
        Calculate tax estimate based on income and expenses
        
        Body:
            - totalIncome: number (required)
            - totalExpenses: number (required)
            - rentPaid: number (optional, for rent relief)
        
        Returns:
            - 200: Tax estimate calculated
            - 400: Validation error
            - 500: Server error
        """
        try:
            data = request.get_json()
            
            # Validate inputs
            total_income = data.get('totalIncome', 0)
            total_expenses = data.get('totalExpenses', 0)
            rent_paid = data.get('rentPaid', 0)
            
            if total_income < 0 or total_expenses < 0 or rent_paid < 0:
                return jsonify({
                    'success': False,
                    'message': 'Invalid amounts',
                    'errors': {'general': ['Amounts must be non-negative']}
                }), 400
            
            # Get user's tax profile
            tax_profile = current_user.get('taxProfile')
            if not tax_profile:
                return jsonify({
                    'success': False,
                    'message': 'Tax profile not set',
                    'errors': {'general': ['Please complete the Tax Jurisdiction Wizard first']}
                }), 400
            
            business_structure = tax_profile.get('businessStructure')
            
            # Calculate tax based on business structure
            if business_structure == 'personal_income':
                # Personal Income Tax (PIT) - Progressive rates
                net_income = total_income - total_expenses
                
                # Calculate rent relief (20% of rent, max ₦500,000)
                rent_relief = min(rent_paid * 0.20, 500000)
                
                # Taxable income after rent relief
                taxable_income = max(0, net_income - rent_relief)
                
                # Calculate tax using progressive bands
                estimated_tax, breakdown = _calculate_pit_tax(taxable_income)
                
                effective_rate = (estimated_tax / total_income * 100) if total_income > 0 else 0
                
                return jsonify({
                    'success': True,
                    'data': {
                        'totalIncome': total_income,
                        'totalExpenses': total_expenses,
                        'netIncome': net_income,
                        'rentRelief': rent_relief,
                        'taxableIncome': taxable_income,
                        'estimatedTax': estimated_tax,
                        'effectiveRate': round(effective_rate, 2),
                        'breakdown': breakdown,
                        'taxAuthority': 'SIRS',
                        'filingDeadline': 'March 31st'
                    },
                    'message': 'Tax estimate calculated successfully'
                })
                
            elif business_structure == 'llc':
                # Corporate Income Tax (CIT)
                net_income = total_income - total_expenses
                annual_turnover = tax_profile.get('annualTurnover', 0)
                
                # Check exemption eligibility
                exemption_eligible = annual_turnover < 100_000_000
                
                if exemption_eligible:
                    estimated_tax = 0
                    tax_rate = 0
                    note = 'Eligible for 0% CIT (Small Company Exemption) if Fixed Assets NBV < ₦250M'
                else:
                    estimated_tax = net_income * 0.30 if net_income > 0 else 0
                    tax_rate = 30
                    note = 'Standard CIT rate applies'
                
                effective_rate = (estimated_tax / total_income * 100) if total_income > 0 else 0
                
                return jsonify({
                    'success': True,
                    'data': {
                        'totalIncome': total_income,
                        'totalExpenses': total_expenses,
                        'netIncome': net_income,
                        'taxableIncome': net_income,
                        'estimatedTax': estimated_tax,
                        'taxRate': tax_rate,
                        'effectiveRate': round(effective_rate, 2),
                        'exemptionEligible': exemption_eligible,
                        'note': note,
                        'taxAuthority': 'NRS',
                        'filingDeadline': 'June 30th'
                    },
                    'message': 'Tax estimate calculated successfully'
                })
            
            else:
                return jsonify({
                    'success': False,
                    'message': 'Invalid business structure',
                    'errors': {'general': ['Unknown business structure']}
                }), 400
            
        except Exception as e:
            print(f'❌ Error calculating tax estimate: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to calculate tax estimate',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _calculate_tax_estimate()


# Helper functions

def _compute_tax_profile(business_structure, annual_turnover=None, annual_income=None):
    """Compute tax profile based on business structure and income level"""
    
    if business_structure == 'personal_income':
        # Determine income bracket for personalized guidance
        if annual_income and annual_income < 800000:
            return {
                'businessStructure': 'personal_income',
                'incomeLevel': 'below_800k',
                'annualIncome': annual_income,
                'taxAuthority': 'sirs',
                'taxRate': '0% (Tax-Free)',
                'exemptionEligible': True,
                'filingDeadline': 'March 31st',
                'description': '🎉 Great news! Your income is below ₦800,000, so you pay 0% tax. This applies to freelancers, side hustles, and small businesses. Keep records for future growth and stay compliant.'
            }
        elif annual_income and annual_income < 3000000:
            return {
                'businessStructure': 'personal_income',
                'incomeLevel': '800k_to_3m',
                'annualIncome': annual_income,
                'taxAuthority': 'sirs',
                'taxRate': '0% on first ₦800k, then 15%',
                'exemptionEligible': False,
                'filingDeadline': 'March 31st',
                'description': 'You pay 15% tax on income above ₦800,000. For employees: Your salary is taxed via PAYE by your employer. This 15% applies ONLY to your side income tracked in FiCore.'
            }
        else:
            return {
                'businessStructure': 'personal_income',
                'incomeLevel': 'above_3m',
                'annualIncome': annual_income,
                'taxAuthority': 'sirs',
                'taxRate': '15-25% (Progressive)',
                'exemptionEligible': False,
                'filingDeadline': 'March 31st',
                'description': 'You pay progressive rates (15%-25%) as your income grows. First ₦800,000 is always tax-free. This applies to all personal income including freelance work, side hustles, and business income.'
            }
    
    elif business_structure == 'llc':
        exemption_eligible = annual_turnover and annual_turnover < 100_000_000
        
        return {
            'businessStructure': 'llc',
            'annualTurnover': annual_turnover,
            'taxAuthority': 'nrs',
            'taxRate': '0% or 30%',
            'exemptionEligible': exemption_eligible,
            'filingDeadline': 'June 30th',
            'description': '0% CIT if qualified (Turnover < ₦100M AND Fixed Assets NBV < ₦250M), otherwise 30% CIT.'
        }
    
    elif business_structure == 'professional_services':
        # Professional services are EXPLICITLY EXCLUDED from small company exemption
        # Law, accounting, consulting, engineering, architecture, medical practices
        return {
            'businessStructure': 'professional_services',
            'taxAuthority': 'nrs',
            'taxRate': '30% CIT (Standard Rate)',
            'exemptionEligible': False,
            'filingDeadline': 'June 30th',
            'description': '⚠️ Professional services firms (law, accounting, consulting, engineering, architecture, medical) are EXCLUDED from the 0% CIT exemption under Nigeria Tax Act 2025. You pay the standard 30% CIT rate regardless of turnover or asset size. This applies to LLP, Ltd, BN, and Partnership structures.'
        }
    
    return None


def _serialize_tax_profile(tax_profile):
    """Serialize tax profile for JSON response"""
    if not tax_profile:
        return None
    
    return {
        'businessStructure': tax_profile.get('businessStructure'),
        'annualTurnover': tax_profile.get('annualTurnover'),
        'annualIncome': tax_profile.get('annualIncome'),
        'incomeLevel': tax_profile.get('incomeLevel'),
        'taxAuthority': tax_profile.get('taxAuthority'),
        'taxRate': tax_profile.get('taxRate'),
        'exemptionEligible': tax_profile.get('exemptionEligible', False),
        'filingDeadline': tax_profile.get('filingDeadline'),
        'description': tax_profile.get('description'),
        'companyYearEnd': tax_profile.get('companyYearEnd').isoformat() + 'Z' if tax_profile.get('companyYearEnd') else None,
        'citDeadline': tax_profile.get('citDeadline').isoformat() + 'Z' if tax_profile.get('citDeadline') else None,
        'completedAt': tax_profile.get('completedAt').isoformat() + 'Z' if tax_profile.get('completedAt') else None,
        'lastUpdated': tax_profile.get('lastUpdated').isoformat() + 'Z' if tax_profile.get('lastUpdated') else None
    }


def _calculate_pit_tax(taxable_income):
    """Calculate Personal Income Tax using progressive bands"""
    
    # Nigerian PIT bands (2026)
    tax_bands = [
        (0, 800000, 0.00),              # First ₦800,000 - Tax-free
        (800000, 3000000, 0.15),        # Next ₦2,200,000 - 15%
        (3000000, 12000000, 0.18),      # Next ₦9,000,000 - 18%
        (12000000, 25000000, 0.21),     # Next ₦13,000,000 - 21%
        (25000000, 50000000, 0.23),     # Next ₦25,000,000 - 23%
        (50000000, float('inf'), 0.25)  # Above ₦50,000,000 - 25%
    ]
    
    total_tax = 0
    breakdown = []
    
    for lower, upper, rate in tax_bands:
        if taxable_income <= lower:
            break
        
        # Calculate taxable amount in this band
        taxable_in_band = min(taxable_income, upper) - lower
        if taxable_in_band <= 0:
            continue
        
        band_tax = taxable_in_band * rate
        total_tax += band_tax
        
        upper_display = f"₦{upper:,.0f}" if upper != float('inf') else "Above"
        breakdown.append({
            'band': f"₦{lower:,.0f} - {upper_display}",
            'rate': f"{rate*100:.0f}%",
            'taxableAmount': taxable_in_band,
            'tax': band_tax
        })
    
    return total_tax, breakdown


# ============================================================================
# ENTRY TAGGING STATISTICS (Phase 3B)
# ============================================================================

@users_bp.route('/tagging-stats', methods=['GET'])
def get_tagging_statistics():
    @users_bp.token_required
    def _get_tagging_statistics(current_user):
        """Get tagging statistics for user"""
        try:
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            # Income stats
            income_query = get_active_transactions_query(current_user['_id'])
            total_income = users_bp.mongo.db.incomes.count_documents(income_query)
            
            business_income_query = income_query.copy()
            business_income_query['entryType'] = 'business'
            business_income = users_bp.mongo.db.incomes.count_documents(business_income_query)
            
            personal_income_query = income_query.copy()
            personal_income_query['entryType'] = 'personal'
            personal_income = users_bp.mongo.db.incomes.count_documents(personal_income_query)
            
            untagged_income_query = income_query.copy()
            untagged_income_query['entryType'] = None
            untagged_income = users_bp.mongo.db.incomes.count_documents(untagged_income_query)
            
            # Expense stats
            expense_query = get_active_transactions_query(current_user['_id'])
            total_expenses = users_bp.mongo.db.expenses.count_documents(expense_query)
            
            business_expenses_query = expense_query.copy()
            business_expenses_query['entryType'] = 'business'
            business_expenses = users_bp.mongo.db.expenses.count_documents(business_expenses_query)
            
            personal_expenses_query = expense_query.copy()
            personal_expenses_query['entryType'] = 'personal'
            personal_expenses = users_bp.mongo.db.expenses.count_documents(personal_expenses_query)
            
            untagged_expenses_query = expense_query.copy()
            untagged_expenses_query['entryType'] = None
            untagged_expenses = users_bp.mongo.db.expenses.count_documents(untagged_expenses_query)
            
            # Calculate totals
            total_entries = total_income + total_expenses
            tagged_entries = business_income + personal_income + business_expenses + personal_expenses
            untagged_entries = untagged_income + untagged_expenses
            
            tagging_percentage = (tagged_entries / total_entries * 100) if total_entries > 0 else 0
            
            return jsonify({
                'success': True,
                'stats': {
                    'total': total_entries,
                    'tagged': tagged_entries,
                    'untagged': untagged_entries,
                    'taggingPercentage': round(tagging_percentage, 1),
                    'income': {
                        'total': total_income,
                        'business': business_income,
                        'personal': personal_income,
                        'untagged': untagged_income
                    },
                    'expenses': {
                        'total': total_expenses,
                        'business': business_expenses,
                        'personal': personal_expenses,
                        'untagged': untagged_expenses
                    }
                }
            })
            
        except Exception as e:
            print(f"Error in get_tagging_statistics: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to get tagging statistics',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_tagging_statistics()
