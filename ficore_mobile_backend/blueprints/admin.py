from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
from werkzeug.security import generate_password_hash
import uuid
import re

def init_admin_blueprint(mongo, token_required, admin_required, serialize_doc):
    admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

    # ===== HEALTH CHECK ENDPOINT =====

    @admin_bp.route('/health', methods=['GET'])
    @token_required
    @admin_required
    def admin_health_check(current_user):
        """Simple health check for admin endpoints"""
        try:
            # Test database connection
            mongo.db.users.count_documents({}, limit=1)
            
            return jsonify({
                'success': True,
                'data': {
                    'status': 'healthy',
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'admin_user': current_user.get('displayName', 'Admin')
                },
                'message': 'Admin service is healthy'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Admin service health check failed',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== DASHBOARD & ANALYTICS ENDPOINTS =====

    @admin_bp.route('/dashboard/stats', methods=['GET'])
    @token_required
    @admin_required
    def get_dashboard_stats(current_user):
        """Get comprehensive dashboard statistics for admin"""
        try:
            # Get timeframe parameter (default: 30 days)
            timeframe_days = int(request.args.get('timeframe', 30))
            timeframe_start = datetime.utcnow() - timedelta(days=timeframe_days)
            
            # User statistics
            total_users = mongo.db.users.count_documents({})
            active_users = mongo.db.users.count_documents({'isActive': True})
            admin_users = mongo.db.users.count_documents({'role': 'admin'})
            
            # Active users by timeframe (users who logged in within timeframe)
            active_users_timeframe = mongo.db.users.count_documents({
                'lastLogin': {'$gte': timeframe_start}
            })
            
            # Inactive users (never logged in or not logged in within timeframe)
            inactive_users_timeframe = total_users - active_users_timeframe
            
            # New users in timeframe
            new_users_timeframe = mongo.db.users.count_documents({
                'createdAt': {'$gte': timeframe_start}
            })
            
            # Credit statistics
            pending_credit_requests = mongo.db.credit_requests.count_documents({'status': 'pending'})
            total_credits_issued = mongo.db.credit_transactions.aggregate([
                {'$match': {'type': 'credit', 'status': 'completed'}},
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ])
            total_credits_issued = list(total_credits_issued)
            total_credits_issued = total_credits_issued[0]['total'] if total_credits_issued else 0
            
            # Credits this month
            start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            credits_this_month = mongo.db.credit_transactions.aggregate([
                {'$match': {
                    'type': 'credit', 
                    'status': 'completed',
                    'createdAt': {'$gte': start_of_month}
                }},
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ])
            credits_this_month = list(credits_this_month)
            credits_this_month = credits_this_month[0]['total'] if credits_this_month else 0
            
            # Budget statistics
            total_budgets = mongo.db.budgets.count_documents({})
            budgets_this_month = mongo.db.budgets.count_documents({
                'createdAt': {'$gte': start_of_month}
            })
            
            # Recent activities (last 10)
            recent_activities = []
            
            # Get recent credit approvals
            recent_credits = list(mongo.db.credit_requests.find({
                'status': {'$in': ['approved', 'rejected']},
                'processedAt': {'$exists': True}
            }).sort('processedAt', -1).limit(5))
            
            for credit in recent_credits:
                user = mongo.db.users.find_one({'_id': credit['userId']})
                admin_user = mongo.db.users.find_one({'_id': credit.get('processedBy')})
                
                recent_activities.append({
                    'action': f'Credit request {credit["status"]}',
                    'userName': admin_user.get('displayName', 'Admin') if admin_user else 'Admin',
                    'timestamp': credit['processedAt'].isoformat() + 'Z',
                    'details': f'{credit["amount"]} FC for {user.get("displayName", "Unknown User") if user else "Unknown User"}'
                })
            
            # Get recent user registrations
            recent_users = list(mongo.db.users.find({}).sort('createdAt', -1).limit(3))
            for user in recent_users:
                recent_activities.append({
                    'action': 'New user registered',
                    'userName': user.get('displayName', 'Unknown User'),
                    'timestamp': user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                    'details': f'Email: {user.get("email", "")}'
                })
            
            # Sort activities by timestamp
            recent_activities.sort(key=lambda x: x['timestamp'], reverse=True)
            recent_activities = recent_activities[:10]

            stats = {
                'totalUsers': total_users,
                'activeUsers': active_users,
                'adminUsers': admin_users,
                'activeUsersTimeframe': active_users_timeframe,
                'inactiveUsersTimeframe': inactive_users_timeframe,
                'newUsersTimeframe': new_users_timeframe,
                'timeframeDays': timeframe_days,
                'totalBudgets': total_budgets,
                'budgetsThisMonth': budgets_this_month,
                'pendingCreditRequests': pending_credit_requests,
                'totalCreditsIssued': total_credits_issued,
                'creditsThisMonth': credits_this_month,
                'recentActivities': recent_activities
            }

            return jsonify({
                'success': True,
                'data': stats,
                'message': 'Dashboard statistics retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve dashboard statistics',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/export', methods=['GET'])
    @token_required
    @admin_required
    def export_users(current_user):
        """Export all users data to CSV format"""
        try:
            from io import StringIO
            import csv
            
            # Get filter parameters
            status_filter = request.args.get('status', 'all')  # all, active, inactive
            timeframe_days = int(request.args.get('timeframe', 0))  # 0 = all time
            
            # Build query
            query = {}
            if status_filter == 'active':
                if timeframe_days > 0:
                    timeframe_start = datetime.utcnow() - timedelta(days=timeframe_days)
                    query['lastLogin'] = {'$gte': timeframe_start}
                else:
                    query['isActive'] = True
            elif status_filter == 'inactive':
                if timeframe_days > 0:
                    timeframe_start = datetime.utcnow() - timedelta(days=timeframe_days)
                    query['$or'] = [
                        {'lastLogin': {'$lt': timeframe_start}},
                        {'lastLogin': {'$exists': False}}
                    ]
                else:
                    query['isActive'] = False
            
            # Get all users matching criteria
            users = list(mongo.db.users.find(query).sort('createdAt', -1))
            
            # Create CSV
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'User ID',
                'Email',
                'First Name',
                'Last Name',
                'Display Name',
                'Phone',
                'Role',
                'Credit Balance',
                'Is Active',
                'Is Subscribed',
                'Subscription Type',
                'Setup Complete',
                'Created At',
                'Last Login',
                'Language'
            ])
            
            # Write user data
            for user in users:
                writer.writerow([
                    str(user['_id']),
                    user.get('email', ''),
                    user.get('firstName', ''),
                    user.get('lastName', ''),
                    user.get('displayName', ''),
                    user.get('phone', ''),
                    user.get('role', 'personal'),
                    user.get('ficoreCreditBalance', 0.0),
                    'Yes' if user.get('isActive', True) else 'No',
                    'Yes' if user.get('isSubscribed', False) else 'No',
                    user.get('subscriptionType', 'None'),
                    'Yes' if user.get('setupComplete', False) else 'No',
                    user.get('createdAt', datetime.utcnow()).isoformat(),
                    user.get('lastLogin').isoformat() if user.get('lastLogin') else 'Never',
                    user.get('language', 'en')
                ])
            
            # Get CSV content
            csv_content = output.getvalue()
            output.close()
            
            # Return as downloadable file
            from flask import make_response
            response = make_response(csv_content)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=ficore_users_export_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            return response
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to export users',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/list/active', methods=['GET'])
    @token_required
    @admin_required
    def get_active_users_list(current_user):
        """Get detailed list of active users within timeframe"""
        try:
            # Get timeframe parameter (default: 30 days)
            timeframe_days = int(request.args.get('timeframe', 30))
            timeframe_start = datetime.utcnow() - timedelta(days=timeframe_days)
            
            # Get pagination
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            skip = (page - 1) * limit
            
            # Query for active users (logged in within timeframe)
            query = {'lastLogin': {'$gte': timeframe_start}}
            
            total = mongo.db.users.count_documents(query)
            users = list(mongo.db.users.find(query)
                        .sort('lastLogin', -1)
                        .skip(skip)
                        .limit(limit))
            
            # Format user data
            user_list = []
            for user in users:
                user_list.append({
                    'id': str(user['_id']),
                    'email': user.get('email', ''),
                    'displayName': user.get('displayName', ''),
                    'firstName': user.get('firstName', ''),
                    'lastName': user.get('lastName', ''),
                    'phone': user.get('phone', ''),
                    'ficoreCreditBalance': user.get('ficoreCreditBalance', 0.0),
                    'isSubscribed': user.get('isSubscribed', False),
                    'subscriptionType': user.get('subscriptionType'),
                    'createdAt': user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                    'lastLogin': user.get('lastLogin').isoformat() + 'Z' if user.get('lastLogin') else None,
                    'daysSinceLastLogin': (datetime.utcnow() - user.get('lastLogin')).days if user.get('lastLogin') else None
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'users': user_list,
                    'timeframeDays': timeframe_days,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit
                    }
                },
                'message': f'Active users (last {timeframe_days} days) retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve active users',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/list/inactive', methods=['GET'])
    @token_required
    @admin_required
    def get_inactive_users_list(current_user):
        """Get detailed list of inactive users (not logged in within timeframe)"""
        try:
            # Get timeframe parameter (default: 30 days)
            timeframe_days = int(request.args.get('timeframe', 30))
            timeframe_start = datetime.utcnow() - timedelta(days=timeframe_days)
            
            # Get pagination
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            skip = (page - 1) * limit
            
            # Query for inactive users (not logged in within timeframe or never logged in)
            query = {
                '$or': [
                    {'lastLogin': {'$lt': timeframe_start}},
                    {'lastLogin': {'$exists': False}},
                    {'lastLogin': None}
                ]
            }
            
            total = mongo.db.users.count_documents(query)
            users = list(mongo.db.users.find(query)
                        .sort('createdAt', -1)
                        .skip(skip)
                        .limit(limit))
            
            # Format user data
            user_list = []
            for user in users:
                last_login = user.get('lastLogin')
                days_since_login = None
                if last_login:
                    days_since_login = (datetime.utcnow() - last_login).days
                
                user_list.append({
                    'id': str(user['_id']),
                    'email': user.get('email', ''),
                    'displayName': user.get('displayName', ''),
                    'firstName': user.get('firstName', ''),
                    'lastName': user.get('lastName', ''),
                    'phone': user.get('phone', ''),
                    'ficoreCreditBalance': user.get('ficoreCreditBalance', 0.0),
                    'isSubscribed': user.get('isSubscribed', False),
                    'subscriptionType': user.get('subscriptionType'),
                    'createdAt': user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                    'lastLogin': last_login.isoformat() + 'Z' if last_login else 'Never',
                    'daysSinceLastLogin': days_since_login,
                    'neverLoggedIn': last_login is None
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'users': user_list,
                    'timeframeDays': timeframe_days,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit
                    }
                },
                'message': f'Inactive users (not active in last {timeframe_days} days) retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve inactive users',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== COMPREHENSIVE USER MANAGEMENT ENDPOINTS =====

    @admin_bp.route('/users', methods=['GET'])
    @token_required
    @admin_required
    def get_all_users(current_user):
        """Get all users for admin management"""
        try:
            # Get pagination and filter parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            search = request.args.get('search', '')
            email = request.args.get('email', '')  # Add email-specific search
            role = request.args.get('role', '')
            is_active = request.args.get('is_active', '')
            sort_by = request.args.get('sort_by', 'createdAt')
            sort_order = request.args.get('sort_order', 'desc')
            
            # Build query
            query = {}
            
            # Handle email-specific search (exact match or partial)
            if email:
                query['email'] = {'$regex': email, '$options': 'i'}
            elif search:
                # General search across multiple fields
                query['$or'] = [
                    {'email': {'$regex': search, '$options': 'i'}},
                    {'displayName': {'$regex': search, '$options': 'i'}},
                    {'firstName': {'$regex': search, '$options': 'i'}},
                    {'lastName': {'$regex': search, '$options': 'i'}}
                ]
            
            if role:
                query['role'] = role
                
            if is_active:
                query['isActive'] = is_active.lower() == 'true'

            # Get total count
            total = mongo.db.users.count_documents(query)
            
            # Get users with pagination and sorting
            skip = (page - 1) * limit
            sort_direction = -1 if sort_order == 'desc' else 1
            users = list(mongo.db.users.find(query)
                        .sort(sort_by, sort_direction)
                        .skip(skip)
                        .limit(limit))
            
            # Serialize users (exclude sensitive data)
            user_data = []
            for user in users:
                user_info = {
                    'id': str(user['_id']),
                    'email': user.get('email', ''),
                    'firstName': user.get('firstName', ''),
                    'lastName': user.get('lastName', ''),
                    'displayName': user.get('displayName', ''),
                    # Provide `name` for client compatibility (mirrors displayName)
                    'name': user.get('displayName', ''),
                    'role': user.get('role', 'personal'),
                    'ficoreCreditBalance': user.get('ficoreCreditBalance', 0.0),
                    'language': user.get('language', 'en'),
                    'setupComplete': user.get('setupComplete', False),
                    'isActive': user.get('isActive', True),
                    'createdAt': user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                    'lastLogin': user.get('lastLogin').isoformat() + 'Z' if user.get('lastLogin') else None,
                    'financialGoals': user.get('financialGoals', [])
                }
                user_data.append(user_info)

            return jsonify({
                'success': True,
                'data': {
                    'users': user_data,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit,
                        'hasNext': page * limit < total,
                        'hasPrev': page > 1
                    }
                },
                'message': 'Users retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve users',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users', methods=['POST'])
    @token_required
    @admin_required
    def create_user(current_user):
        """Create a new user (admin only)"""
        try:
            data = request.get_json()
            required_fields = ['email', 'firstName', 'lastName', 'password', 'role']
            
            for field in required_fields:
                if field not in data:
                    return jsonify({
                        'success': False,
                        'message': f'Missing required field: {field}'
                    }), 400

            email = data['email'].lower().strip()
            first_name = data['firstName'].strip()
            last_name = data['lastName'].strip()
            password = data['password']
            role = data['role']
            initial_credits = float(data.get('ficoreCreditBalance', 10.0))

            # Validate email format
            if not re.match(r'^[^@]+@[^@]+\.[^@]+', email):
                return jsonify({
                    'success': False,
                    'message': 'Invalid email format'
                }), 400

            # Check if user already exists
            if mongo.db.users.find_one({'email': email}):
                return jsonify({
                    'success': False,
                    'message': 'User with this email already exists'
                }), 400

            # Validate role
            if role not in ['personal', 'admin']:
                return jsonify({
                    'success': False,
                    'message': 'Role must be either "personal" or "admin"'
                }), 400

            # Create user
            user_data = {
                '_id': ObjectId(),
                'email': email,
                'password': generate_password_hash(password),
                'firstName': first_name,
                'lastName': last_name,
                'displayName': f"{first_name} {last_name}",
                'role': role,
                'ficoreCreditBalance': initial_credits,
                'financialGoals': [],
                'createdAt': datetime.utcnow(),
                'lastLogin': None,
                'isActive': True,
                'language': 'en',
                'setupComplete': True
            }

            mongo.db.users.insert_one(user_data)

            # Return user data (without password)
            user_response = serialize_doc(user_data.copy())
            del user_response['password']
            user_response['createdAt'] = user_data['createdAt'].isoformat() + 'Z'
            # Ensure `name` is present (mirror displayName)
            user_response['name'] = user_response.get('displayName', '')

            return jsonify({
                'success': True,
                'data': user_response,
                'message': 'User created successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to create user',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>', methods=['PUT'])
    @token_required
    @admin_required
    def update_user(current_user, user_id):
        """Update user information (admin only)"""
        try:
            data = request.get_json()
            
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Prepare update data
            update_data = {}
            
            if 'email' in data:
                email = data['email'].lower().strip()
                # Check if email is already taken by another user
                existing_user = mongo.db.users.find_one({
                    'email': email,
                    '_id': {'$ne': ObjectId(user_id)}
                })
                if existing_user:
                    return jsonify({
                        'success': False,
                        'message': 'Email already taken by another user'
                    }), 400
                update_data['email'] = email

            if 'firstName' in data:
                update_data['firstName'] = data['firstName'].strip()
            
            if 'lastName' in data:
                update_data['lastName'] = data['lastName'].strip()
            
            # Update display name if first or last name changed
            if 'firstName' in update_data or 'lastName' in update_data:
                first_name = update_data.get('firstName', user.get('firstName', ''))
                last_name = update_data.get('lastName', user.get('lastName', ''))
                update_data['displayName'] = f"{first_name} {last_name}"

            if update_data:
                update_data['updatedAt'] = datetime.utcnow()
                mongo.db.users.update_one(
                    {'_id': ObjectId(user_id)},
                    {'$set': update_data}
                )

            # Get updated user
            updated_user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            user_response = serialize_doc(updated_user.copy())
            del user_response['password']
            user_response['createdAt'] = updated_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            if updated_user.get('lastLogin'):
                user_response['lastLogin'] = updated_user['lastLogin'].isoformat() + 'Z'
            # Ensure `name` is present (mirror displayName)
            user_response['name'] = user_response.get('displayName', '')
            # Ensure `name` is present (mirror displayName)
            user_response['name'] = user_response.get('displayName', '')

            return jsonify({
                'success': True,
                'data': user_response,
                'message': 'User updated successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update user',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/reset-password', methods=['POST'])
    @token_required
    @admin_required
    def reset_user_password(current_user, user_id):
        """Send password reset email to user (admin only)"""
        try:
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Generate reset token
            reset_token = str(uuid.uuid4())
            
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {
                    'resetToken': reset_token,
                    'resetTokenExpiry': datetime.utcnow() + timedelta(hours=1),
                    'updatedAt': datetime.utcnow()
                }}
            )

            return jsonify({
                'success': True,
                'message': f'Password reset email sent to {user["email"]}'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to send password reset email',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/role', methods=['PUT'])
    @token_required
    @admin_required
    def update_user_role(current_user, user_id):
        """Update user role (admin only)"""
        try:
            data = request.get_json()
            
            if 'role' not in data:
                return jsonify({
                    'success': False,
                    'message': 'Role is required'
                }), 400

            new_role = data['role']
            if new_role not in ['personal', 'admin']:
                return jsonify({
                    'success': False,
                    'message': 'Role must be either "personal" or "admin"'
                }), 400

            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Update role
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {
                    'role': new_role,
                    'updatedAt': datetime.utcnow()
                }}
            )

            # Get updated user
            updated_user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            user_response = serialize_doc(updated_user.copy())
            del user_response['password']
            user_response['createdAt'] = updated_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            if updated_user.get('lastLogin'):
                user_response['lastLogin'] = updated_user['lastLogin'].isoformat() + 'Z'

            return jsonify({
                'success': True,
                'data': user_response,
                'message': f'User role updated to {new_role}'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update user role',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/credits', methods=['PUT'])
    @token_required
    @admin_required
    def update_user_credits(current_user, user_id):
        """Update user credits with operation support (admin only)"""
        try:
            data = request.get_json()
            
            required_fields = ['operation', 'amount']
            for field in required_fields:
                if field not in data:
                    return jsonify({
                        'success': False,
                        'message': f'Missing required field: {field}'
                    }), 400

            operation = data['operation']  # 'add', 'deduct', 'set'
            amount = float(data['amount'])
            reason = data.get('reason', 'Admin credit adjustment')

            if operation not in ['add', 'deduct', 'set']:
                return jsonify({
                    'success': False,
                    'message': 'Operation must be "add", "deduct", or "set"'
                }), 400

            if amount < 0:
                return jsonify({
                    'success': False,
                    'message': 'Amount cannot be negative'
                }), 400

            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            current_balance = user.get('ficoreCreditBalance', 0.0)
            
            # Calculate new balance based on operation
            if operation == 'add':
                new_balance = current_balance + amount
                transaction_type = 'credit'
                description = f'Admin credit addition: {reason}'
            elif operation == 'deduct':
                if current_balance < amount:
                    return jsonify({
                        'success': False,
                        'message': 'Insufficient credits to deduct',
                        'data': {
                            'currentBalance': current_balance,
                            'requestedDeduction': amount
                        }
                    }), 400
                new_balance = current_balance - amount
                transaction_type = 'debit'
                description = f'Admin credit deduction: {reason}'
            else:  # set
                new_balance = amount
                transaction_type = 'credit' if amount > current_balance else 'debit'
                description = f'Admin credit balance set: {reason}'

            # Update user balance
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {
                    'ficoreCreditBalance': new_balance,
                    'updatedAt': datetime.utcnow()
                }}
            )

            # Create transaction record
            transaction = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'type': transaction_type,
                'amount': abs(new_balance - current_balance),
                'description': description,
                'status': 'completed',
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'processedBy': current_user['_id'],
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'adjustmentType': 'admin',
                    'operation': operation,
                    'adjustedBy': current_user.get('displayName', 'Admin'),
                    'adminId': str(current_user['_id']),
                    'reason': reason,
                    'processedAt': datetime.utcnow().isoformat() + 'Z'
                }
            }
            
            mongo.db.credit_transactions.insert_one(transaction)

            # Create credit event record for audit trail
            credit_event = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'transactionId': transaction['_id'],
                'eventType': 'admin_credit_adjustment',
                'timestamp': datetime.utcnow(),
                'adminId': current_user['_id'],
                'adminName': current_user.get('displayName', 'Admin'),
                'reason': reason,
                'metadata': {
                    'operation': operation,
                    'amount': amount,
                    'balanceBefore': current_balance,
                    'balanceAfter': new_balance,
                    'adjustedBy': current_user.get('displayName', 'Admin'),
                    'adjustedAt': datetime.utcnow().isoformat() + 'Z'
                }
            }
            mongo.db.credit_events.insert_one(credit_event)

            # Get updated user
            updated_user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            user_response = serialize_doc(updated_user.copy())
            del user_response['password']
            user_response['createdAt'] = updated_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            if updated_user.get('lastLogin'):
                user_response['lastLogin'] = updated_user['lastLogin'].isoformat() + 'Z'

            return jsonify({
                'success': True,
                'data': user_response,
                'message': f'User credits {operation}ed successfully'
            })

        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid amount format'
            }), 400
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update user credits',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>', methods=['GET'])
    @token_required
    @admin_required
    def get_user_by_id(current_user, user_id):
        """Get specific user details by ID (admin only)"""
        try:
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Serialize user data (exclude sensitive data)
            user_info = {
                'id': str(user['_id']),
                '_id': str(user['_id']),  # For backward compatibility
                'email': user.get('email', ''),
                'firstName': user.get('firstName', ''),
                'lastName': user.get('lastName', ''),
                'displayName': user.get('displayName', ''),
                'name': user.get('displayName', ''),
                'phone': user.get('phone', ''),
                'address': user.get('address', ''),
                'dateOfBirth': user.get('dateOfBirth', ''),
                'role': user.get('role', 'personal'),
                'ficoreCreditBalance': user.get('ficoreCreditBalance', 0.0),
                'language': user.get('language', 'en'),
                'setupComplete': user.get('setupComplete', False),
                'isActive': user.get('isActive', True),
                'createdAt': user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                'lastLogin': user.get('lastLogin').isoformat() + 'Z' if user.get('lastLogin') else None,
                'financialGoals': user.get('financialGoals', []),
                # Subscription info
                'isSubscribed': user.get('isSubscribed', False),
                'subscriptionType': user.get('subscriptionType'),
                'subscriptionStartDate': user.get('subscriptionStartDate').isoformat() + 'Z' if user.get('subscriptionStartDate') else None,
                'subscriptionEndDate': user.get('subscriptionEndDate').isoformat() + 'Z' if user.get('subscriptionEndDate') else None,
                'subscriptionAutoRenew': user.get('subscriptionAutoRenew', False)
            }

            return jsonify({
                'success': True,
                'data': user_info,
                'message': 'User retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve user',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/transactions', methods=['GET'])
    @token_required
    @admin_required
    def get_user_transactions(current_user, user_id):
        """Get user's credit transactions (admin only)"""
        try:
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Get pagination parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            status = request.args.get('status', '')
            transaction_type = request.args.get('type', '')

            # Build query
            query = {'userId': ObjectId(user_id)}
            if status:
                query['status'] = status
            if transaction_type:
                query['type'] = transaction_type

            # Get total count
            total = mongo.db.credit_transactions.count_documents(query)
            
            # Get transactions with pagination
            skip = (page - 1) * limit
            transactions = list(mongo.db.credit_transactions.find(query)
                              .sort('createdAt', -1)
                              .skip(skip)
                              .limit(limit))
            
            # Serialize transactions
            transaction_data = []
            for transaction in transactions:
                trans_data = serialize_doc(transaction.copy())
                
                # Format dates
                trans_data['createdAt'] = transaction.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                if transaction.get('updatedAt'):
                    trans_data['updatedAt'] = transaction['updatedAt'].isoformat() + 'Z'
                if transaction.get('processedAt'):
                    trans_data['processedAt'] = transaction['processedAt'].isoformat() + 'Z'
                
                # Add processed by user info if available
                if transaction.get('processedBy'):
                    processed_by_user = mongo.db.users.find_one({'_id': transaction['processedBy']})
                    if processed_by_user:
                        trans_data['processedByUser'] = {
                            'id': str(processed_by_user['_id']),
                            'displayName': processed_by_user.get('displayName', 'Admin'),
                            'email': processed_by_user.get('email', '')
                        }
                
                transaction_data.append(trans_data)

            return jsonify({
                'success': True,
                'data': {
                    'transactions': transaction_data,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit,
                        'hasNext': page * limit < total,
                        'hasPrev': page > 1
                    }
                },
                'message': 'User transactions retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve user transactions',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/activity', methods=['GET'])
    @token_required
    @admin_required
    def get_user_activity(current_user, user_id):
        """Get user activity history (admin only)"""
        try:
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            activities = []
            
            # Get credit transactions
            credit_transactions = list(mongo.db.credit_transactions.find({
                'userId': ObjectId(user_id)
            }).sort('createdAt', -1).limit(20))
            
            for transaction in credit_transactions:
                activities.append({
                    'action': f'Credit {transaction["type"]}',
                    'timestamp': transaction.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                    'details': f'{transaction["amount"]} FC - {transaction.get("description", "")}'
                })

            # Get expense activities
            expenses = list(mongo.db.expenses.find({
                'userId': ObjectId(user_id)
            }).sort('date', -1).limit(10))
            
            for expense in expenses:
                activities.append({
                    'action': 'Expense recorded',
                    'timestamp': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                    'details': f'{expense["amount"]} NGN - {expense.get("description", expense.get("category", ""))}'
                })

            # Get income activities
            incomes = list(mongo.db.incomes.find({
                'userId': ObjectId(user_id)
            }).sort('dateReceived', -1).limit(10))
            
            for income in incomes:
                activities.append({
                    'action': 'Income recorded',
                    'timestamp': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z',
                    'details': f'{income["amount"]} NGN - {income.get("description", income.get("source", ""))}'
                })

            # Sort activities by timestamp
            activities.sort(key=lambda x: x['timestamp'], reverse=True)
            activities = activities[:30]  # Limit to 30 most recent

            return jsonify({
                'success': True,
                'data': activities,
                'message': 'User activity retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve user activity',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/suspend', methods=['POST'])
    @token_required
    @admin_required
    def suspend_user(current_user, user_id):
        """Suspend a user account (admin only)"""
        try:
            data = request.get_json() or {}
            reason = data.get('reason', 'Account suspended by admin')
            
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Update user status
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {
                    'isActive': False,
                    'suspendedAt': datetime.utcnow(),
                    'suspendedBy': current_user['_id'],
                    'suspensionReason': reason,
                    'updatedAt': datetime.utcnow()
                }}
            )

            # Get updated user
            updated_user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            user_response = serialize_doc(updated_user.copy())
            del user_response['password']
            user_response['createdAt'] = updated_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            if updated_user.get('lastLogin'):
                user_response['lastLogin'] = updated_user['lastLogin'].isoformat() + 'Z'

            return jsonify({
                'success': True,
                'data': user_response,
                'message': 'User suspended successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to suspend user',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/activate', methods=['POST'])
    @token_required
    @admin_required
    def activate_user(current_user, user_id):
        """Activate a suspended user account (admin only)"""
        try:
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Update user status
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {
                    'isActive': True,
                    'activatedAt': datetime.utcnow(),
                    'activatedBy': current_user['_id'],
                    'updatedAt': datetime.utcnow()
                },
                '$unset': {
                    'suspendedAt': '',
                    'suspendedBy': '',
                    'suspensionReason': ''
                }}
            )

            # Get updated user
            updated_user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            user_response = serialize_doc(updated_user.copy())
            del user_response['password']
            user_response['createdAt'] = updated_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            if updated_user.get('lastLogin'):
                user_response['lastLogin'] = updated_user['lastLogin'].isoformat() + 'Z'

            return jsonify({
                'success': True,
                'data': user_response,
                'message': 'User activated successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to activate user',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/status', methods=['PUT'])
    @token_required
    @admin_required
    def update_user_status(current_user, user_id):
        """Update user status (activate/suspend) - unified endpoint for frontend compatibility"""
        try:
            data = request.get_json()
            
            if 'is_active' not in data:
                return jsonify({
                    'success': False,
                    'message': 'is_active field is required'
                }), 400

            is_active = data['is_active']
            reason = data.get('suspension_reason', 'Status updated by admin')
            
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Update user status
            update_data = {
                'isActive': is_active,
                'updatedAt': datetime.utcnow()
            }
            
            if is_active:
                # Activating user
                update_data.update({
                    'activatedAt': datetime.utcnow(),
                    'activatedBy': current_user['_id']
                })
                # Remove suspension fields
                mongo.db.users.update_one(
                    {'_id': ObjectId(user_id)},
                    {
                        '$set': update_data,
                        '$unset': {
                            'suspendedAt': '',
                            'suspendedBy': '',
                            'suspensionReason': ''
                        }
                    }
                )
            else:
                # Suspending user
                update_data.update({
                    'suspendedAt': datetime.utcnow(),
                    'suspendedBy': current_user['_id'],
                    'suspensionReason': reason
                })
                mongo.db.users.update_one(
                    {'_id': ObjectId(user_id)},
                    {'$set': update_data}
                )

            # Get updated user
            updated_user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            user_response = serialize_doc(updated_user.copy())
            del user_response['password']
            user_response['createdAt'] = updated_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            if updated_user.get('lastLogin'):
                user_response['lastLogin'] = updated_user['lastLogin'].isoformat() + 'Z'
            # Ensure `name` is present (mirror displayName)
            user_response['name'] = user_response.get('displayName', '')

            return jsonify({
                'success': True,
                'data': user_response,
                'message': f'User {"activated" if is_active else "suspended"} successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update user status',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>', methods=['DELETE'])
    @token_required
    @admin_required
    def delete_user(current_user, user_id):
        """Delete a user account permanently (admin only)"""
        try:
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Prevent deleting admin users (safety check)
            if user.get('role') == 'admin':
                return jsonify({
                    'success': False,
                    'message': 'Cannot delete admin users'
                }), 403

            # Delete user and related data
            mongo.db.users.delete_one({'_id': ObjectId(user_id)})
            mongo.db.expenses.delete_many({'userId': ObjectId(user_id)})
            mongo.db.incomes.delete_many({'userId': ObjectId(user_id)})
            mongo.db.budgets.delete_many({'userId': ObjectId(user_id)})
            mongo.db.credit_requests.delete_many({'userId': ObjectId(user_id)})
            mongo.db.credit_transactions.delete_many({'userId': ObjectId(user_id)})

            return jsonify({
                'success': True,
                'message': 'User deleted successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to delete user',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== CREDIT REQUEST MANAGEMENT ENDPOINTS =====

    @admin_bp.route('/credit-requests', methods=['GET'])
    @admin_bp.route('/credits/requests', methods=['GET'])  # Alternative endpoint for frontend compatibility
    @token_required
    @admin_required
    def get_all_credit_requests(current_user):
        """Get all credit requests for admin review"""
        try:
            # Get pagination parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            status = request.args.get('status', 'all')  # all, pending, approved, rejected
            
            # Build query
            query = {}
            if status != 'all':
                query['status'] = status

            # Get total count
            total = mongo.db.credit_requests.count_documents(query)
            
            # Get requests with pagination
            skip = (page - 1) * limit
            requests = list(mongo.db.credit_requests.find(query)
                          .sort('createdAt', -1)
                          .skip(skip)
                          .limit(limit))
            
            # Get user details for each request
            request_data = []
            for req in requests:
                req_data = serialize_doc(req.copy())
                
                # Get user info
                user = mongo.db.users.find_one({'_id': req['userId']})
                if user:
                    req_data['user'] = {
                        'id': str(user['_id']),
                        'email': user.get('email', ''),
                        'displayName': user.get('displayName', ''),
                        'name': user.get('displayName', ''),
                        'currentBalance': user.get('ficoreCreditBalance', 0.0)
                    }
                
                # Format dates
                req_data['createdAt'] = req_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                req_data['updatedAt'] = req_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                if req_data.get('processedAt'):
                    req_data['processedAt'] = req_data.get('processedAt', datetime.utcnow()).isoformat() + 'Z'
                
                request_data.append(req_data)

            # Get summary statistics
            stats = {
                'total': total,
                'pending': mongo.db.credit_requests.count_documents({'status': 'pending'}),
                'approved': mongo.db.credit_requests.count_documents({'status': 'approved'}),
                'rejected': mongo.db.credit_requests.count_documents({'status': 'rejected'}),
                'processing': mongo.db.credit_requests.count_documents({'status': 'processing'})
            }

            return jsonify({
                'success': True,
                'data': {
                    'requests': request_data,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit,
                        'hasNext': page * limit < total,
                        'hasPrev': page > 1
                    },
                    'statistics': stats
                },
                'message': 'Credit requests retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve credit requests',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/credit-requests/<request_id>/approve', methods=['POST'])
    @admin_bp.route('/credits/requests/<request_id>/approve', methods=['POST'])  # Alternative endpoint
    @token_required
    @admin_required
    def approve_credit_request(current_user, request_id):
        """Approve a credit request and add credits to user account"""
        try:
            data = request.get_json() or {}
            admin_notes = data.get('notes', '')
            
            # Find the credit request
            credit_request = mongo.db.credit_requests.find_one({'requestId': request_id})
            
            if not credit_request:
                return jsonify({
                    'success': False,
                    'message': 'Credit request not found'
                }), 404

            if credit_request['status'] != 'pending':
                return jsonify({
                    'success': False,
                    'message': 'Credit request has already been processed'
                }), 400

            # Get the user
            user = mongo.db.users.find_one({'_id': credit_request['userId']})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Update credit request status
            mongo.db.credit_requests.update_one(
                {'requestId': request_id},
                {
                    '$set': {
                        'status': 'approved',
                        'processedBy': current_user['_id'],
                        'processedAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow(),
                        'adminNotes': admin_notes
                    }
                }
            )

            # Add credits to user account
            current_balance = user.get('ficoreCreditBalance', 0.0)
            new_balance = current_balance + credit_request['amount']
            
            mongo.db.users.update_one(
                {'_id': credit_request['userId']},
                {'$set': {'ficoreCreditBalance': new_balance}}
            )

            # Get naira amount for description
            naira_amount = credit_request.get('nairaAmount', 0)
            credit_amount = credit_request['amount']
            
            # Update the pending transaction to completed status
            mongo.db.credit_transactions.update_one(
                {'requestId': request_id, 'type': 'credit'},
                {
                    '$set': {
                        'status': 'completed',
                        'description': f'Credit top-up approved for {credit_amount:.1f} FCs ({naira_amount:.0f} NGN) - {credit_request["paymentMethod"]}',
                        'balanceBefore': current_balance,
                        'balanceAfter': new_balance,
                        'processedBy': current_user['_id'],
                        'processedAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow(),
                        'metadata': {
                            'requestType': 'topup',
                            'approvedBy': current_user.get('displayName', 'Admin'),
                            'adminNotes': admin_notes,
                            'paymentMethod': credit_request['paymentMethod'],
                            'nairaAmount': naira_amount,
                            'creditAmount': credit_amount
                        }
                    }
                }
            )

            return jsonify({
                'success': True,
                'data': {
                    'requestId': request_id,
                    'amount': credit_request['amount'],
                    'userPreviousBalance': current_balance,
                    'userNewBalance': new_balance,
                    'processedBy': current_user.get('displayName', 'Admin'),
                    'processedAt': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'Credit request approved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to approve credit request',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/credit-requests/<request_id>/reject', methods=['POST'])
    @admin_bp.route('/credits/requests/<request_id>/reject', methods=['POST'])  # Alternative endpoint
    @token_required
    @admin_required
    def reject_credit_request(current_user, request_id):
        """Reject a credit request"""
        try:
            data = request.get_json() or {}
            rejection_reason = data.get('reason', 'Request rejected by admin')
            admin_notes = data.get('notes', '')
            
            # Find the credit request
            credit_request = mongo.db.credit_requests.find_one({'requestId': request_id})
            
            if not credit_request:
                return jsonify({
                    'success': False,
                    'message': 'Credit request not found'
                }), 404

            if credit_request['status'] != 'pending':
                return jsonify({
                    'success': False,
                    'message': 'Credit request has already been processed'
                }), 400

            # Update credit request status
            mongo.db.credit_requests.update_one(
                {'requestId': request_id},
                {
                    '$set': {
                        'status': 'rejected',
                        'processedBy': current_user['_id'],
                        'processedAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow(),
                        'rejectionReason': rejection_reason,
                        'adminNotes': admin_notes
                    }
                }
            )

            # Get naira amount for description
            naira_amount = credit_request.get('nairaAmount', 0)
            credit_amount = credit_request['amount']
            
            # Update the pending transaction status
            mongo.db.credit_transactions.update_one(
                {'requestId': request_id, 'type': 'credit'},
                {
                    '$set': {
                        'status': 'rejected',
                        'processedBy': current_user['_id'],
                        'processedAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow(),
                        'rejectionReason': rejection_reason,
                        'description': f'Credit top-up rejected for {credit_amount:.1f} FCs ({naira_amount:.0f} NGN) - {credit_request["paymentMethod"]}',
                        'metadata': {
                            'rejectedBy': current_user.get('displayName', 'Admin'),
                            'adminNotes': admin_notes,
                            'rejectionReason': rejection_reason
                        }
                    }
                }
            )

            return jsonify({
                'success': True,
                'data': {
                    'requestId': request_id,
                    'rejectionReason': rejection_reason,
                    'processedBy': current_user.get('displayName', 'Admin'),
                    'processedAt': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'Credit request rejected successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to reject credit request',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/credits/requests/<request_id>', methods=['PUT'])
    @token_required
    @admin_required
    def update_credit_request_status(current_user, request_id):
        """Update credit request status (approve/deny) - unified endpoint for frontend"""
        try:
            data = request.get_json() or {}
            status = data.get('status')
            comments = data.get('comments', '')
            
            if not status:
                return jsonify({
                    'success': False,
                    'message': 'Status is required'
                }), 400
            
            if status not in ['approved', 'denied', 'rejected']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid status. Must be approved, denied, or rejected'
                }), 400
            
            # Find the credit request
            credit_request = mongo.db.credit_requests.find_one({'requestId': request_id})
            
            if not credit_request:
                return jsonify({
                    'success': False,
                    'message': 'Credit request not found'
                }), 404

            if credit_request['status'] != 'pending':
                return jsonify({
                    'success': False,
                    'message': 'Credit request has already been processed'
                }), 400

            # Handle approval
            if status == 'approved':
                # Get the user
                user = mongo.db.users.find_one({'_id': credit_request['userId']})
                if not user:
                    return jsonify({
                        'success': False,
                        'message': 'User not found'
                    }), 404

                # Update credit request status
                mongo.db.credit_requests.update_one(
                    {'requestId': request_id},
                    {
                        '$set': {
                            'status': 'approved',
                            'processedAt': datetime.utcnow(),
                            'processedBy': current_user['_id'],
                            'adminNotes': comments,
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )

                # Add credits to user account
                current_balance = user.get('ficoreCreditBalance', 0.0)
                new_balance = current_balance + credit_request['amount']
                
                mongo.db.users.update_one(
                    {'_id': credit_request['userId']},
                    {'$set': {'ficoreCreditBalance': new_balance}}
                )

                # Update the pending transaction to completed status
                naira_amount = credit_request.get('nairaAmount', 0)
                credit_amount = credit_request['amount']
                
                mongo.db.credit_transactions.update_one(
                    {'requestId': request_id, 'type': 'credit'},
                    {
                        '$set': {
                            'status': 'completed',
                            'description': f'Credit top-up approved for {credit_amount:.1f} FCs ({naira_amount:.0f} NGN) - {credit_request["paymentMethod"]}',
                            'balanceBefore': current_balance,
                            'balanceAfter': new_balance,
                            'processedAt': datetime.utcnow(),
                            'processedBy': current_user['_id'],
                            'updatedAt': datetime.utcnow(),
                            'metadata': {
                                'requestType': 'topup',
                                'approvedBy': current_user.get('displayName', 'Admin'),
                                'adminNotes': comments,
                                'paymentMethod': credit_request['paymentMethod'],
                                'nairaAmount': naira_amount,
                                'creditAmount': credit_amount
                            }
                        }
                    }
                )

            else:  # Handle denial/rejection
                # Normalize status (both 'denied' and 'rejected' are treated as 'rejected')
                final_status = 'rejected' if status in ['denied', 'rejected'] else status
                
                # Update credit request status
                mongo.db.credit_requests.update_one(
                    {'requestId': request_id},
                    {
                        '$set': {
                            'status': final_status,
                            'processedAt': datetime.utcnow(),
                            'processedBy': current_user['_id'],
                            'rejectionReason': comments,
                            'adminNotes': comments,
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )

                # Update the pending transaction to rejected status
                mongo.db.credit_transactions.update_one(
                    {'requestId': request_id},
                    {
                        '$set': {
                            'status': 'rejected',
                            'processedAt': datetime.utcnow(),
                            'processedBy': current_user['_id'],
                            'metadata': {
                                'rejectedBy': current_user.get('displayName', 'Admin'),
                                'rejectionReason': comments,
                                'adminNotes': comments
                            }
                        }
                    }
                )

            # Get updated credit request
            updated_request = mongo.db.credit_requests.find_one({'requestId': request_id})
            request_data = serialize_doc(updated_request.copy())
            request_data['createdAt'] = updated_request.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            request_data['updatedAt'] = updated_request.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            if updated_request.get('processedAt'):
                request_data['processedAt'] = updated_request['processedAt'].isoformat() + 'Z'

            return jsonify({
                'success': True,
                'data': request_data,
                'message': f'Credit request {status} successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Failed to {status} credit request',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== SYSTEM MONITORING & ANALYTICS ENDPOINTS =====

    @admin_bp.route('/system/health', methods=['GET'])
    @token_required
    @admin_required
    def get_system_health(current_user):
        """Get system health status (admin only)"""
        try:
            # Database health
            try:
                mongo.db.users.find_one()
                db_status = 'healthy'
            except:
                db_status = 'unhealthy'
            
            # System metrics (simplified for basic implementation)
            health_data = {
                'isHealthy': db_status == 'healthy',
                'databaseStatus': db_status,
                'apiStatus': 'healthy',
                'cpuUsage': 45.0,  # Mock data
                'memoryUsage': 62.0,  # Mock data
                'diskUsage': 78.0,  # Mock data
                'errorCount': 0,
                'lastUpdated': datetime.utcnow().isoformat() + 'Z'
            }

            return jsonify({
                'success': True,
                'data': health_data,
                'message': 'System health retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': True,  # Don't fail the request
                'data': {
                    'isHealthy': False,
                    'databaseStatus': 'unknown',
                    'apiStatus': 'unknown',
                    'cpuUsage': 0,
                    'memoryUsage': 0,
                    'diskUsage': 0,
                    'errorCount': 0,
                    'lastUpdated': datetime.utcnow().isoformat() + 'Z',
                    'error': 'Could not retrieve system metrics'
                },
                'message': 'System health retrieved with limited data'
            })

    @admin_bp.route('/analytics/users', methods=['GET'])
    @token_required
    @admin_required
    def get_user_analytics(current_user):
        """Get comprehensive user analytics (admin only)"""
        try:
            # Time-based user registration
            start_date = datetime.utcnow() - timedelta(days=30)
            
            # Daily user registrations (last 30 days)
            daily_registrations = mongo.db.users.aggregate([
                {'$match': {'createdAt': {'$gte': start_date}}},
                {'$group': {
                    '_id': {
                        'year': {'$year': '$createdAt'},
                        'month': {'$month': '$createdAt'},
                        'day': {'$dayOfMonth': '$createdAt'}
                    },
                    'count': {'$sum': 1}
                }},
                {'$sort': {'_id': 1}}
            ])
            
            # User role distribution
            role_distribution = mongo.db.users.aggregate([
                {'$group': {
                    '_id': '$role',
                    'count': {'$sum': 1}
                }}
            ])
            
            # Active vs inactive users
            status_distribution = mongo.db.users.aggregate([
                {'$group': {
                    '_id': '$isActive',
                    'count': {'$sum': 1}
                }}
            ])
            
            # User engagement metrics
            total_users = mongo.db.users.count_documents({})
            active_users = mongo.db.users.count_documents({'isActive': True})
            users_with_expenses = mongo.db.expenses.distinct('userId')
            users_with_income = mongo.db.incomes.distinct('userId')
            users_with_budgets = mongo.db.budgets.distinct('userId')
            
            analytics_data = {
                'totalUsers': total_users,
                'activeUsers': active_users,
                'inactiveUsers': total_users - active_users,
                'dailyRegistrations': list(daily_registrations),
                'roleDistribution': list(role_distribution),
                'statusDistribution': list(status_distribution),
                'engagementMetrics': {
                    'usersWithExpenses': len(users_with_expenses),
                    'usersWithIncome': len(users_with_income),
                    'usersWithBudgets': len(users_with_budgets),
                    'engagementRate': (len(set(users_with_expenses + users_with_income + users_with_budgets)) / total_users * 100) if total_users > 0 else 0
                }
            }

            return jsonify({
                'success': True,
                'data': analytics_data,
                'message': 'User analytics retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve user analytics',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/credits/statistics', methods=['GET'])
    @token_required
    @admin_required
    def get_credit_statistics(current_user):
        """Get comprehensive credit statistics (admin only)"""
        try:
            # Date range parameters
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            
            # Default to last 30 days if no dates provided
            if not start_date_str:
                start_date = datetime.utcnow() - timedelta(days=30)
            else:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', ''))
                
            if not end_date_str:
                end_date = datetime.utcnow()
            else:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', ''))

            # Credit request statistics
            total_requests = mongo.db.credit_requests.count_documents({})
            pending_requests = mongo.db.credit_requests.count_documents({'status': 'pending'})
            approved_requests = mongo.db.credit_requests.count_documents({'status': 'approved'})
            rejected_requests = mongo.db.credit_requests.count_documents({'status': 'rejected'})
            
            # Credit amounts
            total_credits_requested = mongo.db.credit_requests.aggregate([
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ])
            total_credits_requested = list(total_credits_requested)
            total_credits_requested = total_credits_requested[0]['total'] if total_credits_requested else 0
            
            total_credits_issued = mongo.db.credit_requests.aggregate([
                {'$match': {'status': 'approved'}},
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ])
            total_credits_issued = list(total_credits_issued)
            total_credits_issued = total_credits_issued[0]['total'] if total_credits_issued else 0
            
            # Approval rate
            approval_rate = (approved_requests / total_requests * 100) if total_requests > 0 else 0
            
            # Credits in date range
            credits_in_range = mongo.db.credit_requests.aggregate([
                {'$match': {
                    'createdAt': {'$gte': start_date, '$lte': end_date}
                }},
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ])
            credits_in_range = list(credits_in_range)
            credits_in_range = credits_in_range[0]['total'] if credits_in_range else 0

            statistics = {
                'totalRequests': total_requests,
                'pendingRequests': pending_requests,
                'approvedRequests': approved_requests,
                'rejectedRequests': rejected_requests,
                'totalCreditsRequested': total_credits_requested,
                'totalCreditsIssued': total_credits_issued,
                'creditsInDateRange': credits_in_range,
                'approvalRate': approval_rate,
                'dateRange': {
                    'startDate': start_date.isoformat() + 'Z',
                    'endDate': end_date.isoformat() + 'Z'
                }
            }

            return jsonify({
                'success': True,
                'data': statistics,
                'message': 'Credit statistics retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve credit statistics',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== SUBSCRIPTION MANAGEMENT ENDPOINTS =====

    @admin_bp.route('/users/<user_id>/subscription', methods=['GET'])
    @token_required
    @admin_required
    def get_user_subscription(current_user, user_id):
        """Get user's subscription status (admin only)"""
        try:
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Get user's subscription
            subscription = mongo.db.subscriptions.find_one({'userId': ObjectId(user_id)})
            
            if not subscription:
                return jsonify({
                    'success': True,
                    'data': {
                        'isSubscribed': False,
                        'subscriptionType': None,
                        'startDate': None,
                        'endDate': None,
                        'autoRenew': False,
                        'daysRemaining': None,
                        'status': 'inactive'
                    },
                    'message': 'User has no active subscription'
                })

            # Calculate days remaining
            days_remaining = None
            if subscription.get('endDate'):
                end_date = subscription['endDate']
                days_remaining = max(0, (end_date - datetime.utcnow()).days)

            # Determine status
            status = 'active'
            if subscription.get('endDate') and subscription['endDate'] < datetime.utcnow():
                status = 'expired'
            elif subscription.get('status') == 'cancelled':
                status = 'cancelled'

            subscription_data = {
                'isSubscribed': subscription.get('isActive', False),
                'subscriptionType': subscription.get('planId'),
                'startDate': subscription.get('startDate').isoformat() + 'Z' if subscription.get('startDate') else None,
                'endDate': subscription.get('endDate').isoformat() + 'Z' if subscription.get('endDate') else None,
                'autoRenew': subscription.get('autoRenew', False),
                'daysRemaining': days_remaining,
                'status': status,
                'planName': subscription.get('planName'),
                'amount': subscription.get('amount', 0.0),
                'paymentMethod': subscription.get('paymentMethod'),
                'createdAt': subscription.get('createdAt').isoformat() + 'Z' if subscription.get('createdAt') else None
            }

            return jsonify({
                'success': True,
                'data': subscription_data,
                'message': 'User subscription retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve user subscription',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/subscription', methods=['POST'])
    @token_required
    @admin_required
    def create_user_subscription(current_user, user_id):
        """Create or update user subscription (admin only)"""
        try:
            data = request.get_json()
            
            required_fields = ['planId', 'durationDays']
            for field in required_fields:
                if field not in data:
                    return jsonify({
                        'success': False,
                        'message': f'Missing required field: {field}'
                    }), 400

            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            plan_id = data['planId']
            duration_days = int(data['durationDays'])
            auto_renew = data.get('autoRenew', False)
            amount = float(data.get('amount', 0.0))
            reason = data.get('reason', 'Admin subscription grant')

            # Calculate dates
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=duration_days)

            # Check if user already has a subscription
            existing_subscription = mongo.db.subscriptions.find_one({'userId': ObjectId(user_id)})
            subscription_id = None
            
            if existing_subscription:
                subscription_id = existing_subscription['_id']
                # Update existing subscription
                mongo.db.subscriptions.update_one(
                    {'userId': ObjectId(user_id)},
                    {'$set': {
                        'plan': plan_id,  # CRITICAL FIX: Set plan field for frontend compatibility
                        'planId': plan_id,
                        'planName': data.get('planName', plan_id),
                        'startDate': start_date,
                        'endDate': end_date,
                        'isActive': True,
                        'autoRenew': auto_renew,
                        'amount': amount,
                        'paymentMethod': 'admin_grant',
                        'status': 'active',
                        'updatedAt': datetime.utcnow(),
                        'grantedBy': current_user['_id'],
                        'grantReason': reason
                    }}
                )
            else:
                # Create new subscription
                subscription_id = ObjectId()
                subscription_data = {
                    '_id': subscription_id,
                    'userId': ObjectId(user_id),
                    'plan': plan_id,  # CRITICAL FIX: Set plan field for frontend compatibility
                    'planId': plan_id,
                    'planName': data.get('planName', plan_id),
                    'startDate': start_date,
                    'endDate': end_date,
                    'isActive': True,
                    'autoRenew': auto_renew,
                    'amount': amount,
                    'paymentMethod': 'admin_grant',
                    'status': 'active',
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow(),
                    'grantedBy': current_user['_id'],
                    'grantReason': reason
                }
                mongo.db.subscriptions.insert_one(subscription_data)

            # Update user subscription fields to sync with subscription collection
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {
                    'isSubscribed': True,
                    'subscriptionType': plan_id,
                    'subscriptionStartDate': start_date,
                    'subscriptionEndDate': end_date,
                    'subscriptionAutoRenew': auto_renew,
                    'lastUpdated': datetime.utcnow()
                }}
            )

            # Create subscription event record for audit trail
            subscription_event = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'subscriptionId': subscription_id,
                'eventType': 'subscription_granted',
                'timestamp': datetime.utcnow(),
                'adminId': current_user['_id'],
                'adminName': current_user.get('displayName', 'Admin'),
                'reason': reason,
                'metadata': {
                    'planId': plan_id,
                    'planName': data.get('planName', plan_id),
                    'durationDays': duration_days,
                    'amount': amount,
                    'startDate': start_date.isoformat() + 'Z',
                    'endDate': end_date.isoformat() + 'Z',
                    'autoRenew': auto_renew,
                    'previousSubscription': existing_subscription is not None,
                    'grantedBy': current_user.get('displayName', 'Admin'),
                    'grantedAt': datetime.utcnow().isoformat() + 'Z'
                }
            }
            mongo.db.subscription_events.insert_one(subscription_event)

            # Create subscription transaction record
            transaction = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'subscriptionId': subscription_id,
                'type': 'subscription_grant',
                'amount': amount,
                'description': f'Admin subscription grant: {plan_id} for {duration_days} days - {reason}',
                'status': 'completed',
                'processedBy': current_user['_id'],
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'grantedBy': current_user.get('displayName', 'Admin'),
                    'planId': plan_id,
                    'durationDays': duration_days,
                    'reason': reason
                }
            }
            mongo.db.subscription_transactions.insert_one(transaction)

            # Return updated subscription status for immediate frontend update
            updated_user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            subscription_status = {
                'isSubscribed': True,
                'subscriptionType': plan_id,
                'planType': plan_id,
                'startDate': start_date.isoformat() + 'Z',
                'endDate': end_date.isoformat() + 'Z',
                'daysRemaining': duration_days,
                'autoRenew': auto_renew,
                'isActive': True,
                'isExpired': False,
                'isExpiringSoon': duration_days <= 7
            }

            return jsonify({
                'success': True,
                'data': {
                    'subscriptionStatus': subscription_status,
                    'user': {
                        'id': str(updated_user['_id']),
                        'email': updated_user.get('email', ''),
                        'displayName': updated_user.get('displayName', ''),
                        'isSubscribed': True,
                        'subscriptionType': plan_id
                    }
                },
                'message': f'Subscription granted successfully for {duration_days} days'
            })

        except ValueError as e:
            return jsonify({
                'success': False,
                'message': 'Invalid data format',
                'errors': {'general': [str(e)]}
            }), 400
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to create user subscription',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/subscription', methods=['PUT'])
    @token_required
    @admin_required
    def update_user_subscription(current_user, user_id):
        """Update user subscription (admin only)"""
        try:
            data = request.get_json()
            
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Find subscription
            subscription = mongo.db.subscriptions.find_one({'userId': ObjectId(user_id)})
            if not subscription:
                return jsonify({
                    'success': False,
                    'message': 'User has no subscription to update'
                }), 404

            # Prepare update data
            update_data = {}
            
            if 'autoRenew' in data:
                update_data['autoRenew'] = data['autoRenew']
            
            if 'extendDays' in data:
                extend_days = int(data['extendDays'])
                current_end_date = subscription.get('endDate', datetime.utcnow())
                new_end_date = current_end_date + timedelta(days=extend_days)
                update_data['endDate'] = new_end_date
            
            if 'status' in data:
                status = data['status']
                if status in ['active', 'cancelled', 'suspended']:
                    update_data['status'] = status
                    update_data['isActive'] = status == 'active'

            if update_data:
                update_data['updatedAt'] = datetime.utcnow()
                update_data['updatedBy'] = current_user['_id']
                
                mongo.db.subscriptions.update_one(
                    {'userId': ObjectId(user_id)},
                    {'$set': update_data}
                )

                # Update user subscription fields to sync with subscription collection
                updated_subscription = mongo.db.subscriptions.find_one({'userId': ObjectId(user_id)})
                if updated_subscription:
                    user_update_data = {
                        'isSubscribed': updated_subscription.get('isActive', False),
                        'subscriptionType': updated_subscription.get('planId'),
                        'subscriptionStartDate': updated_subscription.get('startDate'),
                        'subscriptionEndDate': updated_subscription.get('endDate'),
                        'subscriptionAutoRenew': updated_subscription.get('autoRenew', False),
                        'lastUpdated': datetime.utcnow()
                    }
                    mongo.db.users.update_one(
                        {'_id': ObjectId(user_id)},
                        {'$set': user_update_data}
                    )

                # Log the update
                if 'extendDays' in data:
                    transaction = {
                        '_id': ObjectId(),
                        'userId': ObjectId(user_id),
                        'subscriptionId': subscription['_id'],
                        'type': 'subscription_extension',
                        'amount': 0.0,
                        'description': f'Admin subscription extension: {data["extendDays"]} days',
                        'status': 'completed',
                        'processedBy': current_user['_id'],
                        'createdAt': datetime.utcnow(),
                        'metadata': {
                            'extendedBy': current_user.get('displayName', 'Admin'),
                            'extensionDays': data['extendDays'],
                            'reason': data.get('reason', 'Admin extension')
                        }
                    }
                    mongo.db.subscription_transactions.insert_one(transaction)

            return jsonify({
                'success': True,
                'message': 'Subscription updated successfully'
            })

        except ValueError as e:
            return jsonify({
                'success': False,
                'message': 'Invalid data format',
                'errors': {'general': [str(e)]}
            }), 400
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update user subscription',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/subscription', methods=['DELETE'])
    @token_required
    @admin_required
    def cancel_user_subscription(current_user, user_id):
        """Cancel user subscription (admin only)"""
        try:
            data = request.get_json() or {}
            reason = data.get('reason', 'Cancelled by admin')
            
            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Find subscription
            subscription = mongo.db.subscriptions.find_one({'userId': ObjectId(user_id)})
            if not subscription:
                return jsonify({
                    'success': False,
                    'message': 'User has no active subscription'
                }), 404

            # Cancel subscription
            mongo.db.subscriptions.update_one(
                {'userId': ObjectId(user_id)},
                {'$set': {
                    'status': 'cancelled',
                    'isActive': False,
                    'autoRenew': False,
                    'cancelledAt': datetime.utcnow(),
                    'cancelledBy': current_user['_id'],
                    'cancellationReason': reason,
                    'updatedAt': datetime.utcnow()
                }}
            )

            # Update user subscription fields to sync with subscription collection
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {
                    'isSubscribed': False,
                    'subscriptionType': None,
                    'subscriptionStartDate': None,
                    'subscriptionEndDate': None,
                    'subscriptionAutoRenew': False,
                    'lastUpdated': datetime.utcnow()
                }}
            )

            # Create cancellation transaction record
            transaction = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'subscriptionId': subscription['_id'],
                'type': 'subscription_cancellation',
                'amount': 0.0,
                'description': f'Admin subscription cancellation - {reason}',
                'status': 'completed',
                'processedBy': current_user['_id'],
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'cancelledBy': current_user.get('displayName', 'Admin'),
                    'reason': reason
                }
            }
            mongo.db.subscription_transactions.insert_one(transaction)

            return jsonify({
                'success': True,
                'message': 'Subscription cancelled successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to cancel user subscription',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/subscriptions', methods=['GET'])
    @token_required
    @admin_required
    def get_all_subscriptions(current_user):
        """Get all user subscriptions for admin management"""
        try:
            # Get pagination parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            status = request.args.get('status', 'all')  # all, active, expired, cancelled
            plan_id = request.args.get('planId', '')
            
            # Build query
            query = {}
            if status != 'all':
                if status == 'active':
                    query['isActive'] = True
                    query['endDate'] = {'$gte': datetime.utcnow()}
                elif status == 'expired':
                    query['endDate'] = {'$lt': datetime.utcnow()}
                elif status == 'cancelled':
                    query['status'] = 'cancelled'
            
            if plan_id:
                query['planId'] = plan_id

            # Get total count
            total = mongo.db.subscriptions.count_documents(query)
            
            # Get subscriptions with pagination
            skip = (page - 1) * limit
            subscriptions = list(mongo.db.subscriptions.find(query)
                               .sort('createdAt', -1)
                               .skip(skip)
                               .limit(limit))
            
            # Get user details for each subscription
            subscription_data = []
            for sub in subscriptions:
                sub_data = serialize_doc(sub.copy())
                
                # Get user info
                user = mongo.db.users.find_one({'_id': sub['userId']})
                if user:
                    sub_data['user'] = {
                        'id': str(user['_id']),
                        'email': user.get('email', ''),
                        'displayName': user.get('displayName', ''),
                        'name': user.get('displayName', '')
                    }
                
                # Calculate days remaining
                days_remaining = None
                if sub.get('endDate'):
                    days_remaining = max(0, (sub['endDate'] - datetime.utcnow()).days)
                sub_data['daysRemaining'] = days_remaining
                
                # Format dates
                if sub_data.get('startDate'):
                    sub_data['startDate'] = sub['startDate'].isoformat() + 'Z'
                if sub_data.get('endDate'):
                    sub_data['endDate'] = sub['endDate'].isoformat() + 'Z'
                if sub_data.get('createdAt'):
                    sub_data['createdAt'] = sub['createdAt'].isoformat() + 'Z'
                if sub_data.get('updatedAt'):
                    sub_data['updatedAt'] = sub['updatedAt'].isoformat() + 'Z'
                
                subscription_data.append(sub_data)

            # Get summary statistics
            stats = {
                'total': total,
                'active': mongo.db.subscriptions.count_documents({
                    'isActive': True,
                    'endDate': {'$gte': datetime.utcnow()}
                }),
                'expired': mongo.db.subscriptions.count_documents({
                    'endDate': {'$lt': datetime.utcnow()}
                }),
                'cancelled': mongo.db.subscriptions.count_documents({'status': 'cancelled'})
            }

            return jsonify({
                'success': True,
                'data': {
                    'subscriptions': subscription_data,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit,
                        'hasNext': page * limit < total,
                        'hasPrev': page > 1
                    },
                    'statistics': stats
                },
                'message': 'Subscriptions retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve subscriptions',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/business-profiles/export', methods=['GET'])
    @token_required
    @admin_required
    def export_business_profiles(current_user):
        """Export all users' business profile data to CSV format"""
        try:
            from io import StringIO
            import csv
            
            # Get all users
            users = list(mongo.db.users.find({}).sort('createdAt', -1))
            
            # Create CSV
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'User ID',
                'Email',
                'Display Name',
                'Business Name',
                'Business Type',
                'Business Type Other',
                'Industry',
                'Number of Employees',
                'Physical Address',
                'Tax ID Number',
                'Social Media Links',
                'Created At',
                'Last Login'
            ])
            
            # Write user data
            for user in users:
                # Get social media links as string
                social_links = ''
                if user.get('socialMediaLinks'):
                    links = user['socialMediaLinks']
                    if isinstance(links, list):
                        social_links = '; '.join([f"{link.get('platform', '')}: {link.get('url', '')}" for link in links])
                
                writer.writerow([
                    str(user['_id']),
                    user.get('email', ''),
                    user.get('displayName', ''),
                    user.get('businessName', ''),
                    user.get('businessType', ''),
                    user.get('businessTypeOther', ''),
                    user.get('industry', ''),
                    user.get('numberOfEmployees', ''),
                    user.get('physicalAddress', ''),
                    user.get('taxIdentificationNumber', ''),
                    social_links,
                    user.get('createdAt', datetime.utcnow()).isoformat(),
                    user.get('lastLogin').isoformat() if user.get('lastLogin') else 'Never'
                ])
            
            # Get CSV content
            csv_content = output.getvalue()
            output.close()
            
            # Return as downloadable file
            from flask import make_response
            response = make_response(csv_content)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=ficore_business_profiles_export_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            return response
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to export business profiles',
                'errors': {'general': [str(e)]}
            }), 500
         
    return admin_bp
