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
            
            # Transaction statistics (income + expenses + VAS)
            total_income_transactions = mongo.db.income.count_documents({})
            total_expense_transactions = mongo.db.expenses.count_documents({})
            total_vas_transactions = mongo.db.vas_transactions.count_documents({})
            total_transactions = total_income_transactions + total_expense_transactions + total_vas_transactions

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
                'totalTransactions': total_transactions,
                'totalIncomeTransactions': total_income_transactions,
                'totalExpenseTransactions': total_expense_transactions,
                'totalVASTransactions': total_vas_transactions,
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

    # ==================== REFERRAL SYSTEM: MANUAL CODE ASSIGNMENT (NEW - Feb 4, 2026) ====================
    
    @admin_bp.route('/users/<user_id>/referral-code', methods=['PUT'])
    @token_required
    @admin_required
    def update_referral_code(current_user, user_id):
        """
        Manually assign a custom referral code to a user.
        For key partners like Auwal (AUWAL2026).
        """
        try:
            data = request.get_json()
            new_code = data.get('referralCode', '').strip().upper()
            
            if not new_code:
                return jsonify({
                    'success': False,
                    'message': 'Referral code is required',
                    'errors': {'referralCode': ['Referral code is required']}
                }), 400
            
            # Validate format (alphanumeric, 3-20 chars)
            if not new_code.isalnum():
                return jsonify({
                    'success': False,
                    'message': 'Code must contain only letters and numbers',
                    'errors': {'referralCode': ['Code must contain only letters and numbers']}
                }), 400
            
            if len(new_code) < 3 or len(new_code) > 20:
                return jsonify({
                    'success': False,
                    'message': 'Code must be 3-20 characters',
                    'errors': {'referralCode': ['Code must be 3-20 characters']}
                }), 400
            
            # Check if user exists
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Check uniqueness (excluding current user)
            existing = mongo.db.users.find_one({
                'referralCode': new_code,
                '_id': {'$ne': ObjectId(user_id)}
            })
            
            if existing:
                return jsonify({
                    'success': False,
                    'message': f'Code "{new_code}" is already taken by another user',
                    'errors': {'referralCode': [f'Code "{new_code}" is already taken']}
                }), 400
            
            # Get old code for logging
            old_code = user.get('referralCode', 'None')
            
            # Update user
            result = mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {
                    '$set': {
                        'referralCode': new_code,
                        'referralCodeGeneratedAt': user.get('referralCodeGeneratedAt', datetime.utcnow()),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count == 0 and user.get('referralCode') != new_code:
                return jsonify({
                    'success': False,
                    'message': 'Failed to update referral code'
                }), 500
            
            # Log admin action
            admin_action = {
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user.get('email'),
                'action': 'UPDATE_REFERRAL_CODE',
                'targetUserId': ObjectId(user_id),
                'targetUserEmail': user.get('email'),
                'details': {
                    'oldCode': old_code,
                    'newCode': new_code,
                    'userName': user.get('displayName')
                },
                'timestamp': datetime.utcnow()
            }
            mongo.db.admin_actions.insert_one(admin_action)
            
            print(f'✅ ADMIN: Referral code updated for user {user_id} ({user.get("email")}): {old_code} → {new_code}')
            
            return jsonify({
                'success': True,
                'data': {
                    'userId': user_id,
                    'referralCode': new_code,
                    'oldCode': old_code,
                    'userName': user.get('displayName'),
                    'userEmail': user.get('email')
                },
                'message': f'Referral code updated to "{new_code}" successfully'
            }), 200
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update referral code',
                'errors': {'general': [str(e)]}
            }), 500
    
    # ==================== END REFERRAL SYSTEM ====================

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

    @admin_bp.route('/users/<user_id>/reset-password-direct', methods=['POST'])
    @token_required
    @admin_required
    def reset_user_password_direct(current_user, user_id):
        """Directly reset user password to a temporary password (admin only)"""
        try:
            data = request.get_json()
            reason = data.get('reason', '').strip()
            
            # Validate reason
            if not reason or len(reason) < 10:
                return jsonify({
                    'success': False,
                    'message': 'Reason is required and must be at least 10 characters'
                }), 400

            # Find user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Generate temporary password (8 characters: letters + numbers)
            import random
            import string
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            
            # Update user password and set flag for forced password change
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {
                    'password': generate_password_hash(temp_password),
                    'passwordChangedAt': datetime.utcnow(),
                    'mustChangePassword': True,  # Force password change on next login
                    'updatedAt': datetime.utcnow()
                }, '$unset': {
                    'resetToken': '',
                    'resetTokenExpiry': ''
                }}
            )

            # Log the admin action
            mongo.db.admin_actions.insert_one({
                'adminId': current_user['_id'],
                'adminEmail': current_user['email'],
                'action': 'password_reset_direct',
                'targetUserId': ObjectId(user_id),
                'targetUserEmail': user['email'],
                'reason': reason,
                'timestamp': datetime.utcnow(),
                'details': {
                    'temporary_password_generated': True,
                    'force_password_change': True
                }
            })

            return jsonify({
                'success': True,
                'message': 'Password reset successfully',
                'data': {
                    'temporaryPassword': temp_password,
                    'userEmail': user['email'],
                    'mustChangePassword': True,
                    'note': 'User must change this password on next login'
                }
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to reset password',
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
                # Business Profile Fields
                'businessName': user.get('businessName'),
                'businessType': user.get('businessType'),
                'businessTypeOther': user.get('businessTypeOther'),
                'industry': user.get('industry'),
                'numberOfEmployees': user.get('numberOfEmployees'),
                'physicalAddress': user.get('physicalAddress'),
                'taxIdentificationNumber': user.get('taxIdentificationNumber'),
                'socialMediaLinks': user.get('socialMediaLinks'),
                'profileCompletionPercentage': user.get('profileCompletionPercentage', 0),
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
            }).sort('createdAt', -1).limit(10))  # FIXED: Sort by createdAt instead of date
            
            for expense in expenses:
                activities.append({
                    'action': 'Expense recorded',
                    'timestamp': expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z',  # FIXED: Use createdAt for activity timestamp
                    'transactionDate': expense.get('date', datetime.utcnow()).isoformat() + 'Z',  # ADDED: Keep user-selected date for reference
                    'details': f'{expense["amount"]} NGN - {expense.get("description", expense.get("category", ""))}'
                })

            # Get income activities
            incomes = list(mongo.db.incomes.find({
                'userId': ObjectId(user_id)
            }).sort('createdAt', -1).limit(10))  # FIXED: Sort by createdAt instead of dateReceived
            
            for income in incomes:
                activities.append({
                    'action': 'Income recorded',
                    'timestamp': income.get('createdAt', datetime.utcnow()).isoformat() + 'Z',  # FIXED: Use createdAt for activity timestamp
                    'transactionDate': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z',  # ADDED: Keep user-selected date for reference
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

    # ===== ACCOUNT DELETION REQUEST MANAGEMENT ENDPOINTS =====
    # Added: Jan 30, 2026 - Unified deletion request system

    @admin_bp.route('/deletion-requests', methods=['GET'])
    @token_required
    @admin_required
    def get_deletion_requests(current_user):
        """
        Get all account deletion requests (admin only).
        Supports filtering by status and pagination.
        
        Query Parameters:
            - status: 'pending', 'approved', 'rejected', 'completed', 'all' (default: 'pending')
            - page: Page number (default: 1)
            - limit: Items per page (default: 20)
            - search: Search by email or name
        
        Returns:
            - 200: List of deletion requests
            - 500: Server error
        """
        try:
            # Get query parameters
            status = request.args.get('status', 'pending')
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            search = request.args.get('search', '').strip()
            
            # Build query
            query = {}
            if status != 'all':
                query['status'] = status
            
            if search:
                query['$or'] = [
                    {'email': {'$regex': search, '$options': 'i'}},
                    {'userName': {'$regex': search, '$options': 'i'}}
                ]
            
            # Get total count
            total = mongo.db.deletion_requests.count_documents(query)
            
            # Get requests with pagination
            skip = (page - 1) * limit
            requests = list(mongo.db.deletion_requests.find(query)
                          .sort('requestedAt', -1)
                          .skip(skip)
                          .limit(limit))
            
            # Serialize
            for req in requests:
                req['_id'] = str(req['_id'])
                req['userId'] = str(req['userId'])
                if req.get('processedBy'):
                    req['processedBy'] = str(req['processedBy'])
                    # Get admin name
                    admin = mongo.db.users.find_one({'_id': ObjectId(req['processedBy'])})
                    req['processedByName'] = admin.get('displayName') if admin else 'Unknown Admin'
                req['requestedAt'] = req['requestedAt'].isoformat() + 'Z'
                if req.get('processedAt'):
                    req['processedAt'] = req['processedAt'].isoformat() + 'Z'
                if req.get('completedAt'):
                    req['completedAt'] = req['completedAt'].isoformat() + 'Z'
                # Serialize userSnapshot dates
                if req.get('userSnapshot'):
                    if req['userSnapshot'].get('createdAt'):
                        req['userSnapshot']['createdAt'] = req['userSnapshot']['createdAt'].isoformat() + 'Z'
                    if req['userSnapshot'].get('lastLogin'):
                        req['userSnapshot']['lastLogin'] = req['userSnapshot']['lastLogin'].isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': requests,
                'pagination': {
                    'total': total,
                    'page': page,
                    'limit': limit,
                    'pages': (total + limit - 1) // limit
                }
            }), 200
            
        except Exception as e:
            print(f'❌ Error fetching deletion requests: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to fetch deletion requests',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/deletion-requests/<request_id>', methods=['GET'])
    @token_required
    @admin_required
    def get_deletion_request_detail(current_user, request_id):
        """
        Get detailed information about a specific deletion request.
        
        Returns:
            - 200: Deletion request details
            - 404: Request not found
            - 500: Server error
        """
        try:
            if not ObjectId.is_valid(request_id):
                return jsonify({'success': False, 'message': 'Invalid request ID'}), 400
            
            deletion_req = mongo.db.deletion_requests.find_one({'_id': ObjectId(request_id)})
            
            if not deletion_req:
                return jsonify({'success': False, 'message': 'Deletion request not found'}), 404
            
            # Get user details
            user = mongo.db.users.find_one({'_id': deletion_req['userId']})
            
            # Serialize
            deletion_req['_id'] = str(deletion_req['_id'])
            deletion_req['userId'] = str(deletion_req['userId'])
            if deletion_req.get('processedBy'):
                deletion_req['processedBy'] = str(deletion_req['processedBy'])
                admin = mongo.db.users.find_one({'_id': ObjectId(deletion_req['processedBy'])})
                deletion_req['processedByName'] = admin.get('displayName') if admin else 'Unknown Admin'
            deletion_req['requestedAt'] = deletion_req['requestedAt'].isoformat() + 'Z'
            if deletion_req.get('processedAt'):
                deletion_req['processedAt'] = deletion_req['processedAt'].isoformat() + 'Z'
            if deletion_req.get('completedAt'):
                deletion_req['completedAt'] = deletion_req['completedAt'].isoformat() + 'Z'
            
            # Add current user status
            deletion_req['userCurrentStatus'] = {
                'exists': user is not None,
                'isActive': user.get('isActive') if user else False,
                'deletedAt': user.get('deletedAt').isoformat() + 'Z' if user and user.get('deletedAt') else None
            }
            
            return jsonify({
                'success': True,
                'data': deletion_req
            }), 200
            
        except Exception as e:
            print(f'❌ Error fetching deletion request detail: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to fetch deletion request',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/deletion-requests/<request_id>/approve', methods=['POST'])
    @token_required
    @admin_required
    def approve_deletion_request(current_user, request_id):
        """
        Approve deletion request and soft delete user account.
        
        Body:
            - notes: Optional[str] - Admin notes
        
        Returns:
            - 200: Request approved and account deleted
            - 400: Invalid request or already processed
            - 404: Request not found
            - 500: Server error
        """
        try:
            if not ObjectId.is_valid(request_id):
                return jsonify({'success': False, 'message': 'Invalid request ID'}), 400
            
            data = request.get_json() or {}
            notes = data.get('notes', '').strip()
            
            # Get deletion request
            deletion_req = mongo.db.deletion_requests.find_one({'_id': ObjectId(request_id)})
            
            if not deletion_req:
                return jsonify({'success': False, 'message': 'Deletion request not found'}), 404
            
            if deletion_req['status'] != 'pending':
                return jsonify({
                    'success': False,
                    'message': f'Request already {deletion_req["status"]}'
                }), 400
            
            # Soft delete user account
            mongo.db.users.update_one(
                {'_id': deletion_req['userId']},
                {
                    '$set': {
                        'isActive': False,
                        'deletedAt': datetime.utcnow(),
                        'deletionReason': 'user_requested',
                        'deletedBy': current_user['_id']
                    }
                }
            )
            
            # Update deletion request
            mongo.db.deletion_requests.update_one(
                {'_id': ObjectId(request_id)},
                {
                    '$set': {
                        'status': 'approved',
                        'processedAt': datetime.utcnow(),
                        'processedBy': current_user['_id'],
                        'processingNotes': notes if notes else 'Approved by admin',
                        'completedAt': datetime.utcnow()
                    }
                }
            )
            
            print(f'✅ Deletion request approved: {request_id} by admin {current_user["email"]}')
            
            # TODO: Send confirmation email to user
            # email_service.send_deletion_completed(deletion_req['email'])
            
            return jsonify({
                'success': True,
                'message': 'Account deletion approved and completed',
                'data': {
                    'requestId': request_id,
                    'status': 'approved',
                    'completedAt': datetime.utcnow().isoformat() + 'Z'
                }
            }), 200
            
        except Exception as e:
            print(f'❌ Error approving deletion request: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to approve deletion request',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/deletion-requests/<request_id>/reject', methods=['POST'])
    @token_required
    @admin_required
    def reject_deletion_request(current_user, request_id):
        """
        Reject deletion request with reason.
        
        Body:
            - notes: Required[str] - Reason for rejection
        
        Returns:
            - 200: Request rejected
            - 400: Invalid request or missing notes
            - 404: Request not found
            - 500: Server error
        """
        try:
            if not ObjectId.is_valid(request_id):
                return jsonify({'success': False, 'message': 'Invalid request ID'}), 400
            
            data = request.get_json() or {}
            notes = data.get('notes', '').strip()
            
            if not notes:
                return jsonify({
                    'success': False,
                    'message': 'Rejection reason is required',
                    'errors': {'notes': ['Please provide a reason for rejection']}
                }), 400
            
            # Update deletion request
            result = mongo.db.deletion_requests.update_one(
                {'_id': ObjectId(request_id), 'status': 'pending'},
                {
                    '$set': {
                        'status': 'rejected',
                        'processedAt': datetime.utcnow(),
                        'processedBy': current_user['_id'],
                        'processingNotes': notes
                    }
                }
            )
            
            if result.modified_count == 0:
                return jsonify({
                    'success': False,
                    'message': 'Request not found or already processed'
                }), 404
            
            print(f'✅ Deletion request rejected: {request_id} by admin {current_user["email"]}')
            
            # TODO: Send rejection email to user
            # email_service.send_deletion_rejected(deletion_req['email'], notes)
            
            return jsonify({
                'success': True,
                'message': 'Deletion request rejected',
                'data': {
                    'requestId': request_id,
                    'status': 'rejected'
                }
            }), 200
            
        except Exception as e:
            print(f'❌ Error rejecting deletion request: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to reject deletion request',
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
                    'subscriptionStatus': 'active',  # CRITICAL FIX: Add this field for VAS webhook compatibility
                    'subscriptionPlan': plan_id,  # CRITICAL FIX: Add this field for consistency
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
                        'subscriptionStatus': 'active' if updated_subscription.get('isActive', False) else 'inactive',  # CRITICAL FIX: Add this field
                        'subscriptionPlan': updated_subscription.get('planId'),  # CRITICAL FIX: Add this field
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
                    'subscriptionStatus': 'cancelled',  # CRITICAL FIX: Add this field
                    'subscriptionPlan': None,  # CRITICAL FIX: Clear this field
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

    # ===== SUBSCRIPTION PLANS ENDPOINT =====

    @admin_bp.route('/subscription-plans', methods=['GET'])
    @token_required
    @admin_required
    def get_subscription_plans(current_user):
        """Get available subscription plans with pricing (admin only)"""
        try:
            plans = [
                {
                    'id': 'MONTHLY',
                    'name': 'Monthly Premium',
                    'duration': 30,
                    'durationUnit': 'days',
                    'amount': 1000.0,
                    'currency': 'NGN',
                    'features': [
                        'Unlimited transactions',
                        'Advanced analytics',
                        'Priority support',
                        'Export to Excel/PDF',
                        'Multi-currency support'
                    ]
                },
                {
                    'id': 'ANNUAL',
                    'name': 'Annual Premium',
                    'duration': 365,
                    'durationUnit': 'days',
                    'amount': 10000.0,
                    'currency': 'NGN',
                    'features': [
                        'Unlimited transactions',
                        'Advanced analytics',
                        'Priority support',
                        'Export to Excel/PDF',
                        'Multi-currency support',
                        '2 months free (vs monthly)'
                    ],
                    'savings': '17% savings vs monthly'
                },
                {
                    'id': 'CUSTOM',
                    'name': 'Custom Duration',
                    'duration': null,
                    'durationUnit': 'days',
                    'amount': null,
                    'currency': 'NGN',
                    'description': 'Specify custom duration and amount'
                }
            ]

            return jsonify({
                'success': True,
                'data': {
                    'plans': plans
                },
                'message': 'Subscription plans retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve subscription plans',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== AUDIT LOGS ENDPOINT =====

    @admin_bp.route('/audit-logs', methods=['GET'])
    @token_required
    @admin_required
    def get_audit_logs(current_user):
        """Get audit logs with filtering capabilities (admin only)"""
        try:
            # Get filter parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            event_type = request.args.get('eventType', '')  # admin_credit_adjustment, subscription_granted, etc.
            admin_id = request.args.get('adminId', '')
            user_id = request.args.get('userId', '')
            start_date = request.args.get('startDate', '')
            end_date = request.args.get('endDate', '')

            # Collect audit logs from multiple collections
            all_logs = []

            # Build query for credit events
            credit_query = {}
            if event_type and event_type.startswith('credit'):
                credit_query['eventType'] = event_type
            if admin_id:
                credit_query['adminId'] = ObjectId(admin_id)
            if user_id:
                credit_query['userId'] = ObjectId(user_id)
            if start_date or end_date:
                credit_query['timestamp'] = {}
                if start_date:
                    credit_query['timestamp']['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    credit_query['timestamp']['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))

            # Get credit events
            if not event_type or 'credit' in event_type:
                credit_events = list(mongo.db.credit_events.find(credit_query).sort('timestamp', -1))
                for event in credit_events:
                    # Get user info
                    user = mongo.db.users.find_one({'_id': event['userId']})
                    all_logs.append({
                        'id': str(event['_id']),
                        'eventType': event['eventType'],
                        'timestamp': event['timestamp'].isoformat() + 'Z',
                        'adminId': str(event['adminId']),
                        'adminName': event.get('adminName', 'Admin'),
                        'userId': str(event['userId']),
                        'userEmail': user.get('email', '') if user else '',
                        'userName': user.get('displayName', '') if user else '',
                        'reason': event.get('reason', ''),
                        'metadata': event.get('metadata', {}),
                        'category': 'credit'
                    })

            # Build query for subscription events
            subscription_query = {}
            if event_type and event_type.startswith('subscription'):
                subscription_query['eventType'] = event_type
            if admin_id:
                subscription_query['adminId'] = ObjectId(admin_id)
            if user_id:
                subscription_query['userId'] = ObjectId(user_id)
            if start_date or end_date:
                subscription_query['timestamp'] = {}
                if start_date:
                    subscription_query['timestamp']['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    subscription_query['timestamp']['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))

            # Get subscription events
            if not event_type or 'subscription' in event_type:
                subscription_events = list(mongo.db.subscription_events.find(subscription_query).sort('timestamp', -1))
                for event in subscription_events:
                    # Get user info
                    user = mongo.db.users.find_one({'_id': event['userId']})
                    all_logs.append({
                        'id': str(event['_id']),
                        'eventType': event['eventType'],
                        'timestamp': event['timestamp'].isoformat() + 'Z',
                        'adminId': str(event['adminId']),
                        'adminName': event.get('adminName', 'Admin'),
                        'userId': str(event['userId']),
                        'userEmail': user.get('email', '') if user else '',
                        'userName': user.get('displayName', '') if user else '',
                        'reason': event.get('reason', ''),
                        'metadata': event.get('metadata', {}),
                        'category': 'subscription'
                    })

            # Sort all logs by timestamp (most recent first)
            all_logs.sort(key=lambda x: x['timestamp'], reverse=True)

            # Apply pagination
            total = len(all_logs)
            skip = (page - 1) * limit
            paginated_logs = all_logs[skip:skip + limit]

            return jsonify({
                'success': True,
                'data': {
                    'logs': paginated_logs,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit if total > 0 else 0,
                        'hasNext': page * limit < total,
                        'hasPrev': page > 1
                    }
                },
                'message': 'Audit logs retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve audit logs',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== CANCELLATION REQUESTS MANAGEMENT ENDPOINTS =====

    @admin_bp.route('/cancellation-requests', methods=['GET'])
    @token_required
    @admin_required
    def get_cancellation_requests(current_user):
        """Get all subscription cancellation requests"""
        try:
            # Get filter parameters
            status = request.args.get('status', 'all')  # all, pending, approved, rejected, completed
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 100))
            
            # Build query
            query = {}
            if status != 'all':
                query['status'] = status
            
            # Get total count
            total = mongo.db.cancellation_requests.count_documents(query)
            
            # Get requests with pagination
            skip = (page - 1) * limit
            requests = list(mongo.db.cancellation_requests.find(query)
                          .sort('requestedAt', -1)
                          .skip(skip)
                          .limit(limit))
            
            # Serialize requests
            request_data = []
            for req in requests:
                req_info = {
                    'id': str(req['_id']),
                    'userId': str(req['userId']),
                    'userEmail': req.get('userEmail', ''),
                    'userName': req.get('userName', 'Unknown User'),
                    'subscriptionType': req.get('subscriptionType', 'Premium'),
                    'subscriptionStartDate': req.get('subscriptionStartDate').isoformat() + 'Z' if req.get('subscriptionStartDate') else None,
                    'subscriptionEndDate': req.get('subscriptionEndDate').isoformat() + 'Z' if req.get('subscriptionEndDate') else None,
                    'reason': req.get('reason'),
                    'status': req.get('status', 'pending'),
                    'requestedAt': req.get('requestedAt', datetime.utcnow()).isoformat() + 'Z',
                    'processedAt': req.get('processedAt').isoformat() + 'Z' if req.get('processedAt') else None,
                    'processedBy': str(req['processedBy']) if req.get('processedBy') else None,
                    'processedByName': req.get('processedByName'),
                    'adminNotes': req.get('adminNotes'),
                    'autoRenewDisabled': req.get('autoRenewDisabled', False)
                }
                request_data.append(req_info)
            
            return jsonify({
                'success': True,
                'data': {
                    'requests': request_data,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit if total > 0 else 0
                    }
                },
                'message': 'Cancellation requests retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting cancellation requests: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve cancellation requests',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/cancellation-requests/<request_id>/approve', methods=['POST'])
    @token_required
    @admin_required
    def approve_cancellation_request(current_user, request_id):
        """Approve a cancellation request"""
        try:
            data = request.get_json() or {}
            admin_notes = data.get('adminNotes', '').strip()
            
            # Find the cancellation request
            cancellation_req = mongo.db.cancellation_requests.find_one({'_id': ObjectId(request_id)})
            if not cancellation_req:
                return jsonify({
                    'success': False,
                    'message': 'Cancellation request not found'
                }), 404
            
            if cancellation_req['status'] != 'pending':
                return jsonify({
                    'success': False,
                    'message': f'Request already {cancellation_req["status"]}'
                }), 400
            
            # Update cancellation request status
            mongo.db.cancellation_requests.update_one(
                {'_id': ObjectId(request_id)},
                {'$set': {
                    'status': 'approved',
                    'processedAt': datetime.utcnow(),
                    'processedBy': current_user['_id'],
                    'processedByName': current_user.get('displayName', 'Admin'),
                    'adminNotes': admin_notes if admin_notes else None
                }}
            )
            
            # Ensure auto-renew is disabled for the user
            mongo.db.users.update_one(
                {'_id': cancellation_req['userId']},
                {'$set': {'subscriptionAutoRenew': False}}
            )
            
            # Log the approval in audit logs
            audit_log = {
                '_id': ObjectId(),
                'eventType': 'subscription_cancellation_approved',
                'timestamp': datetime.utcnow(),
                'adminId': current_user['_id'],
                'adminName': current_user.get('displayName', 'Admin'),
                'userId': cancellation_req['userId'],
                'reason': admin_notes if admin_notes else 'Cancellation request approved',
                'metadata': {
                    'requestId': str(request_id),
                    'subscriptionType': cancellation_req.get('subscriptionType', 'Premium'),
                    'userEmail': cancellation_req.get('userEmail', ''),
                    'userName': cancellation_req.get('userName', '')
                }
            }
            mongo.db.subscription_events.insert_one(audit_log)
            
            return jsonify({
                'success': True,
                'message': 'Cancellation request approved successfully'
            })
            
        except Exception as e:
            print(f"Error approving cancellation request: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to approve cancellation request',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/cancellation-requests/<request_id>/reject', methods=['POST'])
    @token_required
    @admin_required
    def reject_cancellation_request(current_user, request_id):
        """Reject a cancellation request"""
        try:
            data = request.get_json() or {}
            admin_notes = data.get('adminNotes', '').strip()
            
            if not admin_notes:
                return jsonify({
                    'success': False,
                    'message': 'Admin notes are required when rejecting a request'
                }), 400
            
            # Find the cancellation request
            cancellation_req = mongo.db.cancellation_requests.find_one({'_id': ObjectId(request_id)})
            if not cancellation_req:
                return jsonify({
                    'success': False,
                    'message': 'Cancellation request not found'
                }), 404
            
            if cancellation_req['status'] != 'pending':
                return jsonify({
                    'success': False,
                    'message': f'Request already {cancellation_req["status"]}'
                }), 400
            
            # Update cancellation request status
            mongo.db.cancellation_requests.update_one(
                {'_id': ObjectId(request_id)},
                {'$set': {
                    'status': 'rejected',
                    'processedAt': datetime.utcnow(),
                    'processedBy': current_user['_id'],
                    'processedByName': current_user.get('displayName', 'Admin'),
                    'adminNotes': admin_notes
                }}
            )
            
            # Re-enable auto-renew for the user (since request was rejected)
            mongo.db.users.update_one(
                {'_id': cancellation_req['userId']},
                {'$set': {'subscriptionAutoRenew': True}}
            )
            
            # Log the rejection in audit logs
            audit_log = {
                '_id': ObjectId(),
                'eventType': 'subscription_cancellation_rejected',
                'timestamp': datetime.utcnow(),
                'adminId': current_user['_id'],
                'adminName': current_user.get('displayName', 'Admin'),
                'userId': cancellation_req['userId'],
                'reason': admin_notes,
                'metadata': {
                    'requestId': str(request_id),
                    'subscriptionType': cancellation_req.get('subscriptionType', 'Premium'),
                    'userEmail': cancellation_req.get('userEmail', ''),
                    'userName': cancellation_req.get('userName', '')
                }
            }
            mongo.db.subscription_events.insert_one(audit_log)
            
            return jsonify({
                'success': True,
                'message': 'Cancellation request rejected successfully'
            })
            
        except Exception as e:
            print(f"Error rejecting cancellation request: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to reject cancellation request',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/cancellation-requests/stats', methods=['GET'])
    @token_required
    @admin_required
    def get_cancellation_stats(current_user):
        """Get statistics about cancellation requests"""
        try:
            total = mongo.db.cancellation_requests.count_documents({})
            pending = mongo.db.cancellation_requests.count_documents({'status': 'pending'})
            approved = mongo.db.cancellation_requests.count_documents({'status': 'approved'})
            rejected = mongo.db.cancellation_requests.count_documents({'status': 'rejected'})
            
            # Get today's stats
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            approved_today = mongo.db.cancellation_requests.count_documents({
                'status': 'approved',
                'processedAt': {'$gte': today_start}
            })
            rejected_today = mongo.db.cancellation_requests.count_documents({
                'status': 'rejected',
                'processedAt': {'$gte': today_start}
            })
            
            return jsonify({
                'success': True,
                'data': {
                    'total': total,
                    'pending': pending,
                    'approved': approved,
                    'rejected': rejected,
                    'approvedToday': approved_today,
                    'rejectedToday': rejected_today
                },
                'message': 'Cancellation statistics retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting cancellation stats: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve cancellation statistics',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== PASSWORD RESET REQUESTS MANAGEMENT ENDPOINTS =====

    @admin_bp.route('/password-reset-requests', methods=['GET'])
    @token_required
    @admin_required
    def get_password_reset_requests(current_user):
        """Get all password reset requests"""
        try:
            # Get filter parameters
            status = request.args.get('status', 'all')
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            
            # Build query
            query = {}
            if status != 'all':
                query['status'] = status
            
            # Get total count
            total = mongo.db.password_reset_requests.count_documents(query)
            
            # Get requests with pagination
            skip = (page - 1) * limit
            requests = list(mongo.db.password_reset_requests.find(query)
                          .sort('requestedAt', -1)
                          .skip(skip)
                          .limit(limit))
            
            # Format requests
            formatted_requests = []
            for req in requests:
                formatted_req = {
                    'id': str(req['_id']),
                    'userId': str(req['userId']),
                    'userEmail': req.get('userEmail', ''),
                    'userName': req.get('userName', 'Unknown User'),
                    'status': req.get('status', 'pending'),
                    'requestedAt': req.get('requestedAt').isoformat() + 'Z' if req.get('requestedAt') else None,
                    'processedAt': req.get('processedAt').isoformat() + 'Z' if req.get('processedAt') else None,
                    'processedBy': str(req['processedBy']) if req.get('processedBy') else None,
                    'processedByName': req.get('processedByName'),
                    'expiresAt': req.get('expiresAt').isoformat() + 'Z' if req.get('expiresAt') else None,
                    'isExpired': req.get('expiresAt') < datetime.utcnow() if req.get('expiresAt') else False
                }
                formatted_requests.append(formatted_req)
            
            return jsonify({
                'success': True,
                'data': {
                    'requests': formatted_requests,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit
                    }
                },
                'message': 'Password reset requests retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting password reset requests: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve password reset requests',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/password-reset-requests/<request_id>/process', methods=['POST'])
    @token_required
    @admin_required
    def process_password_reset_request(current_user, request_id):
        """Process a password reset request by generating temporary password"""
        try:
            data = request.get_json() or {}
            admin_notes = data.get('adminNotes', '').strip()
            
            # Find the password reset request
            reset_req = mongo.db.password_reset_requests.find_one({'_id': ObjectId(request_id)})
            
            if not reset_req:
                return jsonify({
                    'success': False,
                    'message': 'Password reset request not found'
                }), 404
            
            if reset_req.get('status') != 'pending':
                return jsonify({
                    'success': False,
                    'message': 'Request has already been processed'
                }), 400
            
            # Check if request has expired
            if reset_req.get('expiresAt') and reset_req['expiresAt'] < datetime.utcnow():
                # Mark as expired
                mongo.db.password_reset_requests.update_one(
                    {'_id': ObjectId(request_id)},
                    {'$set': {'status': 'expired'}}
                )
                return jsonify({
                    'success': False,
                    'message': 'Request has expired'
                }), 400
            
            # Generate temporary password (8 characters: letters + numbers)
            import random
            import string
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            
            # Update user password and set flag for forced password change
            mongo.db.users.update_one(
                {'_id': reset_req['userId']},
                {'$set': {
                    'password': generate_password_hash(temp_password),
                    'passwordChangedAt': datetime.utcnow(),
                    'mustChangePassword': True,  # Force password change on next login
                    'updatedAt': datetime.utcnow()
                }, '$unset': {
                    'resetToken': '',
                    'resetTokenExpiry': ''
                }}
            )
            
            # Update password reset request status
            mongo.db.password_reset_requests.update_one(
                {'_id': ObjectId(request_id)},
                {'$set': {
                    'status': 'completed',
                    'processedAt': datetime.utcnow(),
                    'processedBy': current_user['_id'],
                    'processedByName': current_user.get('displayName', 'Admin'),
                    'temporaryPassword': temp_password,  # Store for admin reference
                    'adminNotes': admin_notes if admin_notes else None
                }}
            )
            
            # Log the admin action
            mongo.db.admin_actions.insert_one({
                'adminId': current_user['_id'],
                'adminEmail': current_user['email'],
                'adminName': current_user.get('displayName', 'Admin'),
                'action': 'password_reset_request_processed',
                'targetUserId': reset_req['userId'],
                'targetUserEmail': reset_req['userEmail'],
                'reason': admin_notes if admin_notes else 'Password reset request from user',
                'timestamp': datetime.utcnow(),
                'metadata': {
                    'requestId': str(request_id),
                    'temporary_password_generated': True,
                    'force_password_change': True
                }
            })
            
            return jsonify({
                'success': True,
                'data': {
                    'temporaryPassword': temp_password,
                    'userEmail': reset_req['userEmail'],
                    'userName': reset_req['userName']
                },
                'message': 'Password reset request processed successfully'
            })
            
        except Exception as e:
            print(f"Error processing password reset request: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to process password reset request',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/password-reset-requests/stats', methods=['GET'])
    @token_required
    @admin_required
    def get_password_reset_stats(current_user):
        """Get statistics about password reset requests"""
        try:
            total = mongo.db.password_reset_requests.count_documents({})
            pending = mongo.db.password_reset_requests.count_documents({'status': 'pending'})
            completed = mongo.db.password_reset_requests.count_documents({'status': 'completed'})
            expired = mongo.db.password_reset_requests.count_documents({'status': 'expired'})
            
            # Get today's stats
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            completed_today = mongo.db.password_reset_requests.count_documents({
                'status': 'completed',
                'processedAt': {'$gte': today_start}
            })
            
            # Get pending requests that are about to expire (less than 2 hours left)
            urgent_cutoff = datetime.utcnow() + timedelta(hours=2)
            urgent_pending = mongo.db.password_reset_requests.count_documents({
                'status': 'pending',
                'expiresAt': {'$lte': urgent_cutoff, '$gte': datetime.utcnow()}
            })
            
            return jsonify({
                'success': True,
                'data': {
                    'total': total,
                    'pending': pending,
                    'completed': completed,
                    'expired': expired,
                    'completedToday': completed_today,
                    'urgentPending': urgent_pending
                },
                'message': 'Password reset statistics retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting password reset stats: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve password reset statistics',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== USER ACTIVATION METRICS ENDPOINT =====

    @admin_bp.route('/activation/stats', methods=['GET'])
    @token_required
    @admin_required
    def get_activation_stats(current_user):
        """Get user activation metrics (Phase 2 & 3 analytics)"""
        try:
            # Get timeframe parameter (default: 30 days)
            timeframe_param = request.args.get('timeframe', '30')
            
            if timeframe_param == 'all':
                timeframe_start = datetime(2020, 1, 1)  # Beginning of time
                timeframe_days = None
            else:
                timeframe_days = int(timeframe_param)
                timeframe_start = datetime.utcnow() - timedelta(days=timeframe_days)
            
            timeframe_end = datetime.utcnow()
            
            # 1. SIGNUPS
            total_signups = mongo.db.users.count_documents({
                'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
            })
            
            # Daily signups for trend
            daily_signups = []
            if timeframe_days and timeframe_days <= 90:
                for i in range(timeframe_days):
                    day_start = timeframe_start + timedelta(days=i)
                    day_end = day_start + timedelta(days=1)
                    count = mongo.db.users.count_documents({
                        'createdAt': {'$gte': day_start, '$lt': day_end}
                    })
                    daily_signups.append(count)
            
            # 2. FIRST ENTRIES (Derived from income + expenses)
            # Get unique users who created at least one entry
            income_users = mongo.db.income.distinct('userId', {
                'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
            })
            expense_users = mongo.db.expenses.distinct('userId', {
                'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
            })
            
            # Combine and deduplicate
            users_with_entries = set(income_users + expense_users)
            first_entries_count = len(users_with_entries)
            
            # Daily first entries for trend
            daily_first_entries = []
            if timeframe_days and timeframe_days <= 90:
                for i in range(timeframe_days):
                    day_start = timeframe_start + timedelta(days=i)
                    day_end = day_start + timedelta(days=1)
                    
                    income_day = mongo.db.income.distinct('userId', {
                        'createdAt': {'$gte': day_start, '$lt': day_end}
                    })
                    expense_day = mongo.db.expenses.distinct('userId', {
                        'createdAt': {'$gte': day_start, '$lt': day_end}
                    })
                    
                    count = len(set(income_day + expense_day))
                    daily_first_entries.append(count)
            
            # 3. ACTIVATION RATE
            activation_rate = (first_entries_count / total_signups * 100) if total_signups > 0 else 0
            target_rate = 90.0
            status = 'on_target' if activation_rate >= target_rate else 'below_target'
            
            # 4. AVERAGE TIME TO FIRST ENTRY
            time_to_first_entries = []
            distribution = {'0-5min': 0, '5-15min': 0, '15-60min': 0, '60min+': 0}
            
            # Sample users from timeframe (limit to 1000 for performance)
            users_in_timeframe = list(mongo.db.users.find({
                'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
            }).limit(1000))
            
            for user in users_in_timeframe:
                user_id = user['_id']
                signup_date = user.get('createdAt')
                
                if not signup_date:
                    continue
                
                # Find first income entry
                first_income = mongo.db.income.find_one(
                    {'userId': user_id},
                    sort=[('createdAt', 1)]
                )
                
                # Find first expense entry
                first_expense = mongo.db.expenses.find_one(
                    {'userId': user_id},
                    sort=[('createdAt', 1)]
                )
                
                # Determine actual first entry
                first_entry_date = None
                if first_income and first_expense:
                    first_entry_date = min(
                        first_income['createdAt'],
                        first_expense['createdAt']
                    )
                elif first_income:
                    first_entry_date = first_income['createdAt']
                elif first_expense:
                    first_entry_date = first_expense['createdAt']
                
                if first_entry_date:
                    time_diff = (first_entry_date - signup_date).total_seconds() / 60  # minutes
                    time_to_first_entries.append(time_diff)
                    
                    # Categorize
                    if time_diff <= 5:
                        distribution['0-5min'] += 1
                    elif time_diff <= 15:
                        distribution['5-15min'] += 1
                    elif time_diff <= 60:
                        distribution['15-60min'] += 1
                    else:
                        distribution['60min+'] += 1
            
            avg_time = sum(time_to_first_entries) / len(time_to_first_entries) if time_to_first_entries else 0
            median_time = sorted(time_to_first_entries)[len(time_to_first_entries) // 2] if time_to_first_entries else 0
            
            # 5. ENTRY TYPE SPLIT
            income_first_count = 0
            expense_first_count = 0
            
            for user in users_in_timeframe:
                user_id = user['_id']
                
                first_income = mongo.db.income.find_one(
                    {'userId': user_id},
                    sort=[('createdAt', 1)]
                )
                first_expense = mongo.db.expenses.find_one(
                    {'userId': user_id},
                    sort=[('createdAt', 1)]
                )
                
                if first_income and first_expense:
                    if first_income['createdAt'] < first_expense['createdAt']:
                        income_first_count += 1
                    else:
                        expense_first_count += 1
                elif first_income:
                    income_first_count += 1
                elif first_expense:
                    expense_first_count += 1
            
            total_first_entries = income_first_count + expense_first_count
            income_percentage = (income_first_count / total_first_entries * 100) if total_first_entries > 0 else 0
            expense_percentage = (expense_first_count / total_first_entries * 100) if total_first_entries > 0 else 0
            
            # 6. SECOND ENTRY RATE
            users_with_second_entry = 0
            users_with_second_entry_24h = 0
            
            for user_id in users_with_entries:
                # Count total entries for this user
                income_count = mongo.db.income.count_documents({'userId': user_id})
                expense_count = mongo.db.expenses.count_documents({'userId': user_id})
                total_entries = income_count + expense_count
                
                if total_entries >= 2:
                    users_with_second_entry += 1
                    
                    # Check if second entry was within 24h of first
                    all_entries = []
                    
                    incomes = list(mongo.db.income.find(
                        {'userId': user_id},
                        {'createdAt': 1}
                    ).sort('createdAt', 1).limit(2))
                    
                    expenses = list(mongo.db.expenses.find(
                        {'userId': user_id},
                        {'createdAt': 1}
                    ).sort('createdAt', 1).limit(2))
                    
                    all_entries = sorted(
                        incomes + expenses,
                        key=lambda x: x['createdAt']
                    )
                    
                    if len(all_entries) >= 2:
                        time_diff = (all_entries[1]['createdAt'] - all_entries[0]['createdAt']).total_seconds() / 3600  # hours
                        if time_diff <= 24:
                            users_with_second_entry_24h += 1
            
            second_entry_rate = (users_with_second_entry / first_entries_count * 100) if first_entries_count > 0 else 0
            
            # Build response
            response_data = {
                'timeframe': f'{timeframe_days}d' if timeframe_days else 'all',
                'dateRange': {
                    'start': timeframe_start.isoformat() + 'Z',
                    'end': timeframe_end.isoformat() + 'Z'
                },
                'signups': {
                    'total': total_signups,
                    'daily': daily_signups if daily_signups else None
                },
                'firstEntries': {
                    'total': first_entries_count,
                    'daily': daily_first_entries if daily_first_entries else None
                },
                'activationRate': {
                    'percentage': round(activation_rate, 1),
                    'target': target_rate,
                    'status': status
                },
                'avgTimeToFirstEntry': {
                    'minutes': round(avg_time, 1),
                    'median': round(median_time, 1),
                    'distribution': distribution
                },
                'entryTypeSplit': {
                    'income': income_first_count,
                    'expense': expense_first_count,
                    'incomePercentage': round(income_percentage, 1),
                    'expensePercentage': round(expense_percentage, 1)
                },
                'secondEntryRate': {
                    'total': users_with_second_entry,
                    'percentage': round(second_entry_rate, 1),
                    'within24h': users_with_second_entry_24h
                }
            }
            
            return jsonify({
                'success': True,
                'data': response_data,
                'message': 'Activation statistics retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting activation stats: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve activation statistics',
                'errors': {'general': [str(e)]}
            }), 500
    
    # ===== PHASE 4B: ACTIVATION ANALYTICS AGGREGATION =====
    
    @admin_bp.route('/activation/nudge-performance', methods=['GET'])
    @token_required
    @admin_required
    def get_nudge_performance(current_user):
        """
        Get nudge effectiveness metrics (Phase 4B.1).
        
        Query params:
        - timeframe: '7' | '30' | '90' | 'all' (default: '30')
        
        Returns nudge performance data:
        - shown count
        - dismissed count
        - converted count (next state_transition after shown)
        - conversion rate
        - avg time to conversion
        """
        try:
            # Get timeframe parameter
            timeframe_param = request.args.get('timeframe', '30')
            
            if timeframe_param == 'all':
                timeframe_start = datetime(2020, 1, 1)
            else:
                timeframe_days = int(timeframe_param)
                timeframe_start = datetime.utcnow() - timedelta(days=timeframe_days)
            
            timeframe_end = datetime.utcnow()
            
            # Get all nudge types
            nudge_types = ['noEntryYet', 'firstEntryDone', 'earlyStreak', 'sevenDayStreak']
            
            nudge_performance = []
            
            for nudge_type in nudge_types:
                # Count "shown" events
                shown_count = mongo.db.activation_events.count_documents({
                    'eventType': 'shown',
                    'nudgeType': nudge_type,
                    'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
                })
                
                # Count "dismissed" events
                dismissed_count = mongo.db.activation_events.count_documents({
                    'eventType': 'dismissed',
                    'nudgeType': nudge_type,
                    'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
                })
                
                # Calculate conversions: users who had state_transition after shown
                # CONVERSION ATTRIBUTION RULE (LOCKED):
                # - First "shown" event before a state_transition gets credit
                # - One conversion max per shown event
                # - Unlimited time window (observational)
                # - If multiple nudges shown before conversion, earliest gets credit
                
                # Get all shown events for this nudge
                shown_events = list(mongo.db.activation_events.find({
                    'eventType': 'shown',
                    'nudgeType': nudge_type,
                    'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
                }).sort('createdAt', 1))
                
                converted_count = 0
                conversion_times = []
                
                for shown_event in shown_events:
                    user_id = shown_event['userId']
                    shown_time = shown_event['createdAt']
                    
                    # Find next state_transition for this user after shown
                    next_transition = mongo.db.activation_events.find_one({
                        'userId': user_id,
                        'eventType': 'state_transition',
                        'createdAt': {'$gt': shown_time}
                    }, sort=[('createdAt', 1)])
                    
                    if next_transition:
                        converted_count += 1
                        # Calculate time to conversion in minutes
                        time_diff = (next_transition['createdAt'] - shown_time).total_seconds() / 60
                        conversion_times.append(time_diff)
                
                # Calculate conversion rate
                conversion_rate = (converted_count / shown_count * 100) if shown_count > 0 else 0
                
                # Calculate avg time to conversion
                avg_time_to_conversion = sum(conversion_times) / len(conversion_times) if conversion_times else 0
                
                nudge_performance.append({
                    'type': nudge_type,
                    'shown': shown_count,
                    'dismissed': dismissed_count,
                    'converted': converted_count,
                    'conversionRate': round(conversion_rate, 1),
                    'avgTimeToConversion': round(avg_time_to_conversion, 1)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'timeframe': f'{timeframe_param}d' if timeframe_param != 'all' else 'all',
                    'dateRange': {
                        'start': timeframe_start.isoformat() + 'Z',
                        'end': timeframe_end.isoformat() + 'Z'
                    },
                    'nudges': nudge_performance
                },
                'message': 'Nudge performance retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting nudge performance: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve nudge performance',
                'errors': {'general': [str(e)]}
            }), 500
    
    @admin_bp.route('/activation/funnel', methods=['GET'])
    @token_required
    @admin_required
    def get_activation_funnel(current_user):
        """
        Get S0→S1→S2→S3 funnel metrics (Phase 4B.2).
        
        Query params:
        - timeframe: '7' | '30' | '90' | 'all' (default: '30')
        
        Returns funnel data based on state_transition events only.
        """
        try:
            # Get timeframe parameter
            timeframe_param = request.args.get('timeframe', '30')
            
            if timeframe_param == 'all':
                timeframe_start = datetime(2020, 1, 1)
            else:
                timeframe_days = int(timeframe_param)
                timeframe_start = datetime.utcnow() - timedelta(days=timeframe_days)
            
            timeframe_end = datetime.utcnow()
            
            # Count unique users who reached each state (from state_transition events ONLY)
            # PHASE 4 FIX: S0 must also come from activation_events for consistency
            states = ['S0', 'S1', 'S2', 'S3']
            funnel_data = []
            
            # Get baseline from S0 state_transition events (not users table)
            s0_users = mongo.db.activation_events.distinct('userId', {
                'eventType': 'state_transition',
                'activationState': 'S0',
                'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
            })
            s0_count = len(s0_users)
            
            # If no S0 events yet, fall back to user signups (temporary during migration)
            if s0_count == 0:
                s0_count = mongo.db.users.count_documents({
                    'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
                })
            
            funnel_data.append({
                'state': 'S0',
                'count': s0_count,
                'percentage': 100.0
            })
            
            # S1, S2, S3 = unique users who reached these states
            for state in ['S1', 'S2', 'S3']:
                # Get unique users who transitioned to this state
                users_in_state = mongo.db.activation_events.distinct('userId', {
                    'eventType': 'state_transition',
                    'activationState': state,
                    'createdAt': {'$gte': timeframe_start, '$lte': timeframe_end}
                })
                
                count = len(users_in_state)
                percentage = (count / s0_count * 100) if s0_count > 0 else 0
                
                funnel_data.append({
                    'state': state,
                    'count': count,
                    'percentage': round(percentage, 1)
                })
            
            # Calculate drop-off rates
            drop_off = {}
            for i in range(len(funnel_data) - 1):
                current_state = funnel_data[i]['state']
                next_state = funnel_data[i + 1]['state']
                current_count = funnel_data[i]['count']
                next_count = funnel_data[i + 1]['count']
                
                drop_off_rate = ((current_count - next_count) / current_count * 100) if current_count > 0 else 0
                drop_off[f'{current_state}_to_{next_state}'] = round(drop_off_rate, 1)
            
            return jsonify({
                'success': True,
                'data': {
                    'timeframe': f'{timeframe_param}d' if timeframe_param != 'all' else 'all',
                    'dateRange': {
                        'start': timeframe_start.isoformat() + 'Z',
                        'end': timeframe_end.isoformat() + 'Z'
                    },
                    'funnel': funnel_data,
                    'dropOff': drop_off
                },
                'message': 'Activation funnel retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting activation funnel: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve activation funnel',
                'errors': {'general': [str(e)]}
            }), 500

    # ===== CERTIFIED LEDGER EXPORT ENDPOINT =====

    @admin_bp.route('/ledger/certified/<user_id>', methods=['GET'])
    @token_required
    @admin_required
    def generate_certified_ledger(current_user, user_id):
        """
        Generate Certified Ledger PDF for a specific user
        
        This is the "M-Pesa Standard" - a tamper-evident financial ledger that shows:
        - Complete transaction lifecycle (original → superseded → voided)
        - Reversal entries for deleted transactions
        - Version history for edited transactions
        - Verification QR code for authenticity
        
        Query Parameters:
        - start_date: Start date (YYYY-MM-DD) - optional
        - end_date: End date (YYYY-MM-DD) - optional
        - include_all_statuses: Include voided/superseded transactions (default: true)
        """
        try:
            from utils.pdf_generator import PDFGenerator
            from flask import make_response
            
            # Get user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get date range parameters
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            include_all_statuses = request.args.get('include_all_statuses', 'true').lower() == 'true'
            
            start_date = None
            end_date = None
            
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            
            # Build query for transactions
            query = {'userId': ObjectId(user_id)}
            
            if start_date or end_date:
                date_filter = {}
                if start_date:
                    date_filter['$gte'] = start_date
                if end_date:
                    date_filter['$lte'] = end_date
                # Note: We'll filter by date in the query
            
            # For certified ledger, we want ALL transactions (including voided/superseded)
            # to show the complete audit trail
            if not include_all_statuses:
                # Only active transactions
                query['status'] = 'active'
                query['isDeleted'] = False
            
            # Get all incomes
            income_query = query.copy()
            if start_date or end_date:
                date_filter = {}
                if start_date:
                    date_filter['$gte'] = start_date
                if end_date:
                    date_filter['$lte'] = end_date
                income_query['dateReceived'] = date_filter
            
            incomes = list(mongo.db.incomes.find(income_query).sort('dateReceived', 1))
            
            # Get all expenses
            expense_query = query.copy()
            if start_date or end_date:
                date_filter = {}
                if start_date:
                    date_filter['$gte'] = start_date
                if end_date:
                    date_filter['$lte'] = end_date
                expense_query['date'] = date_filter
            
            expenses = list(mongo.db.expenses.find(expense_query).sort('date', 1))
            
            # Serialize transactions
            transactions = {
                'incomes': [serialize_doc(income) for income in incomes],
                'expenses': [serialize_doc(expense) for expense in expenses]
            }
            
            # Generate unique audit ID
            audit_id = f"FCL-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{user_id[:8]}"
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            user_data = serialize_doc(user)
            pdf_buffer = pdf_generator.generate_certified_ledger(
                user_data=user_data,
                transactions=transactions,
                start_date=start_date,
                end_date=end_date,
                audit_id=audit_id
            )
            
            # Create response
            response = make_response(pdf_buffer.read())
            response.headers['Content-Type'] = 'application/pdf'
            
            # Generate filename
            user_name = user.get('displayName', 'User').replace(' ', '_')
            date_suffix = ''
            if start_date and end_date:
                date_suffix = f"_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}"
            elif start_date:
                date_suffix = f"_from_{start_date.strftime('%Y%m%d')}"
            elif end_date:
                date_suffix = f"_until_{end_date.strftime('%Y%m%d')}"
            
            filename = f"FiCore_Certified_Ledger_{user_name}{date_suffix}_{audit_id}.pdf"
            response.headers['Content-Disposition'] = f'attachment; filename={filename}'
            
            # Log the export for audit trail
            mongo.db.admin_audit_logs.insert_one({
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user.get('email'),
                'action': 'certified_ledger_export',
                'targetUserId': ObjectId(user_id),
                'targetUserEmail': user.get('email'),
                'auditId': audit_id,
                'dateRange': {
                    'start': start_date.isoformat() if start_date else None,
                    'end': end_date.isoformat() if end_date else None
                },
                'includeAllStatuses': include_all_statuses,
                'transactionCount': len(incomes) + len(expenses),
                'timestamp': datetime.utcnow()
            })
            
            return response
            
        except Exception as e:
            print(f"Error generating certified ledger: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to generate certified ledger',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/ledger/search-users', methods=['GET'])
    @token_required
    @admin_required
    def search_users_for_ledger(current_user):
        """
        Search users for certified ledger export
        
        Query Parameters:
        - q: Search query (email, name, phone)
        - limit: Number of results (default: 20, max: 100)
        """
        try:
            search_query = request.args.get('q', '').strip()
            limit = min(int(request.args.get('limit', 20)), 100)
            
            if not search_query:
                return jsonify({
                    'success': False,
                    'message': 'Search query is required'
                }), 400
            
            # Build search query
            query = {
                '$or': [
                    {'email': {'$regex': search_query, '$options': 'i'}},
                    {'displayName': {'$regex': search_query, '$options': 'i'}},
                    {'firstName': {'$regex': search_query, '$options': 'i'}},
                    {'lastName': {'$regex': search_query, '$options': 'i'}},
                    {'phone': {'$regex': search_query, '$options': 'i'}}
                ]
            }
            
            # Get users
            users = list(mongo.db.users.find(query).limit(limit))
            
            # Format results
            results = []
            for user in users:
                # Get transaction counts
                income_count = mongo.db.incomes.count_documents({'userId': user['_id']})
                expense_count = mongo.db.expenses.count_documents({'userId': user['_id']})
                
                results.append({
                    'id': str(user['_id']),
                    'email': user.get('email', ''),
                    'displayName': user.get('displayName', ''),
                    'phone': user.get('phone', ''),
                    'businessName': user.get('businessName', ''),
                    'transactionCount': income_count + expense_count,
                    'incomeCount': income_count,
                    'expenseCount': expense_count,
                    'createdAt': user.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'users': results,
                    'count': len(results),
                    'query': search_query
                },
                'message': 'Users found successfully'
            })
            
        except Exception as e:
            print(f"Error searching users: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to search users',
                'errors': {'general': [str(e)]}
            }), 500
    
    # ===== TREASURY COMMAND CENTER ENDPOINT =====
    
    @admin_bp.route('/treasury/analytics', methods=['GET'])
    @token_required
    @admin_required
    def get_treasury_analytics(current_user):
        """
        💰 PHASE 3: Enhanced Treasury Analytics with Actual Commission Data
        Real-time unit economics tracking with accurate costs and revenues
        """
        try:
            from datetime import datetime, timedelta
            
            # Get time period filter
            period = request.args.get('period', 'all')
            
            # Calculate date filter
            date_filter = {}
            start_date = None
            if period != 'all':
                days = int(period)
                start_date = datetime.utcnow() - timedelta(days=days)
                date_filter = {'createdAt': {'$gte': start_date}}
            
            # ===== 1. VAS COMMISSIONS (from corporate_revenue) =====
            commission_query = {'type': 'VAS_COMMISSION'}
            commission_query.update(date_filter)
            
            commissions = list(mongo.db.corporate_revenue.find(commission_query))
            
            # Calculate by provider
            monnify_commission = sum(c['amount'] for c in commissions if 'MONNIFY' in c.get('category', ''))
            peyflex_commission = sum(c['amount'] for c in commissions if 'PEYFLEX' in c.get('category', ''))
            total_vas_commissions = monnify_commission + peyflex_commission
            
            # Calculate by transaction type
            airtime_commission = sum(c['amount'] for c in commissions if 'AIRTIME' in c.get('category', ''))
            data_commission = sum(c['amount'] for c in commissions if 'DATA' in c.get('category', ''))
            
            # ===== 2. GATEWAY FEES (from vas_transactions and corporate_revenue) =====
            # Get deposit gateway fees
            deposit_query = {'type': 'WALLET_FUNDING', 'status': 'SUCCESS', 'gatewayFee': {'$exists': True}}
            deposit_query.update(date_filter)
            deposits = list(mongo.db.vas_transactions.find(deposit_query))
            total_deposit_gateway_fees = sum(d.get('gatewayFee', 0) for d in deposits)
            
            # Get subscription/credits gateway fees from corporate_revenue
            revenue_query = {'gatewayFee': {'$exists': True}}
            revenue_query.update(date_filter)
            revenue_with_fees = list(mongo.db.corporate_revenue.find(revenue_query))
            total_revenue_gateway_fees = sum(r.get('gatewayFee', 0) for r in revenue_with_fees)
            
            total_gateway_fees = total_deposit_gateway_fees + total_revenue_gateway_fees
            
            # ===== 3. SUBSCRIPTION REVENUE =====
            subscription_query = {'type': 'SUBSCRIPTION'}
            subscription_query.update(date_filter)
            subscriptions = list(mongo.db.corporate_revenue.find(subscription_query))
            
            total_subscription_revenue = sum(s['amount'] for s in subscriptions)
            subscription_gateway_fees = sum(s.get('gatewayFee', 0) for s in subscriptions)
            net_subscription_revenue = sum(s.get('netRevenue', s['amount']) for s in subscriptions)
            
            # ===== 4. FC CREDITS REVENUE =====
            credits_query = {'type': 'CREDITS_PURCHASE'}
            credits_query.update(date_filter)
            credits = list(mongo.db.corporate_revenue.find(credits_query))
            
            total_credits_revenue = sum(c['amount'] for c in credits)
            credits_gateway_fees = sum(c.get('gatewayFee', 0) for c in credits)
            net_credits_revenue = sum(c.get('netRevenue', c['amount']) for c in credits)
            
            # ===== 5. DEPOSIT FEES =====
            deposit_fee_query = {'type': 'SERVICE_FEE', 'category': 'DEPOSIT_FEE'}
            deposit_fee_query.update(date_filter)
            deposit_fees = list(mongo.db.corporate_revenue.find(deposit_fee_query))
            
            total_deposit_fees = sum(d['amount'] for d in deposit_fees)
            deposit_fee_gateway_costs = sum(d.get('gatewayFee', 0) for d in deposit_fees)
            net_deposit_fees = sum(d.get('netRevenue', d['amount']) for d in deposit_fees)
            
            # ===== 6. CALCULATE TOTALS =====
            total_revenue = (
                total_vas_commissions +
                total_subscription_revenue +
                total_credits_revenue +
                total_deposit_fees
            )
            
            total_costs = total_gateway_fees
            
            net_profit = total_revenue - total_costs
            profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
            
            # ===== 7. VAS TRANSACTION BREAKDOWN =====
            vas_query = {'status': 'SUCCESS', 'type': {'$in': ['AIRTIME', 'DATA']}}
            vas_query.update(date_filter)
            vas_transactions = list(mongo.db.vas_transactions.find(vas_query))
            
            # Provider breakdown with commissions
            provider_stats = {}
            for txn in vas_transactions:
                provider = txn.get('provider', 'unknown')
                if provider not in provider_stats:
                    provider_stats[provider] = {
                        'count': 0,
                        'volume': 0,
                        'commission': 0,
                        'commissionRate': '3%' if provider == 'monnify' else '1-5%'
                    }
                
                provider_stats[provider]['count'] += 1
                provider_stats[provider]['volume'] += txn.get('amount', 0)
                provider_stats[provider]['commission'] += txn.get('providerCommission', 0)
            
            # Transaction type breakdown
            type_stats = {}
            for txn in vas_transactions:
                txn_type = txn.get('type', 'UNKNOWN')
                if txn_type not in type_stats:
                    type_stats[txn_type] = {
                        'count': 0,
                        'volume': 0,
                        'commission': 0
                    }
                
                type_stats[txn_type]['count'] += 1
                type_stats[txn_type]['volume'] += txn.get('amount', 0)
                type_stats[txn_type]['commission'] += txn.get('providerCommission', 0)
            
            # ===== 8. RECENT HIGH-VALUE TRANSACTIONS =====
            recent_transactions = []
            for txn in vas_transactions[:50]:  # Last 50 transactions
                serialized_txn = serialize_doc(txn)
                
                # Add user email
                user_id = txn.get('userId')
                if user_id:
                    user = mongo.db.users.find_one({'_id': user_id}, {'email': 1})
                    serialized_txn['userEmail'] = user.get('email') if user else 'N/A'
                else:
                    serialized_txn['userEmail'] = 'N/A'
                
                recent_transactions.append(serialized_txn)
            
            # ===== 9. FORMAT RESPONSE =====
            return jsonify({
                'success': True,
                'data': {
                    'overview': {
                        'totalRevenue': round(total_revenue, 2),
                        'totalCosts': round(total_costs, 2),
                        'netProfit': round(net_profit, 2),
                        'profitMargin': round(profit_margin, 2),
                        'totalTransactions': len(vas_transactions)
                    },
                    'revenueBreakdown': {
                        'vasCommissions': {
                            'total': round(total_vas_commissions, 2),
                            'monnify': round(monnify_commission, 2),
                            'peyflex': round(peyflex_commission, 2),
                            'airtime': round(airtime_commission, 2),
                            'data': round(data_commission, 2)
                        },
                        'subscriptions': {
                            'gross': round(total_subscription_revenue, 2),
                            'gatewayFees': round(subscription_gateway_fees, 2),
                            'net': round(net_subscription_revenue, 2)
                        },
                        'credits': {
                            'gross': round(total_credits_revenue, 2),
                            'gatewayFees': round(credits_gateway_fees, 2),
                            'net': round(net_credits_revenue, 2)
                        },
                        'depositFees': {
                            'gross': round(total_deposit_fees, 2),
                            'gatewayFees': round(deposit_fee_gateway_costs, 2),
                            'net': round(net_deposit_fees, 2)
                        }
                    },
                    'costBreakdown': {
                        'gatewayFees': {
                            'total': round(total_gateway_fees, 2),
                            'deposits': round(total_deposit_gateway_fees, 2),
                            'subscriptions': round(subscription_gateway_fees, 2),
                            'credits': round(credits_gateway_fees, 2)
                        }
                    },
                    'providerStats': [
                        {
                            'name': provider,
                            'count': stats['count'],
                            'volume': round(stats['volume'], 2),
                            'commission': round(stats['commission'], 2),
                            'commissionRate': stats['commissionRate']
                        }
                        for provider, stats in sorted(provider_stats.items(), key=lambda x: x[1]['commission'], reverse=True)
                    ],
                    'transactionTypeStats': [
                        {
                            'type': txn_type,
                            'count': stats['count'],
                            'volume': round(stats['volume'], 2),
                            'commission': round(stats['commission'], 2)
                        }
                        for txn_type, stats in sorted(type_stats.items(), key=lambda x: x[1]['commission'], reverse=True)
                    ],
                    'recentTransactions': recent_transactions,
                    'period': period,
                    'dateRange': {
                        'start': start_date.isoformat() if start_date else None,
                        'end': datetime.utcnow().isoformat()
                    }
                },
                'message': f'Treasury analytics retrieved successfully ({period} period)'
            })
            
        except Exception as e:
            print(f"Error getting treasury analytics: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to get treasury analytics',
                'error': str(e)
            }), 500

    @admin_bp.route('/treasury/user-profitability/<user_id>', methods=['GET'])
    @token_required
    @admin_required
    def get_user_profitability(current_user, user_id):
        """
        💰 PHASE 3: Per-User Profitability Analysis
        Track if individual users (especially premium) are profitable
        """
        try:
            from datetime import datetime, timedelta
            
            # Validate user exists
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get time period filter (optional)
            period = request.args.get('period', 'all')
            date_filter = {}
            start_date = None
            if period != 'all':
                days = int(period)
                start_date = datetime.utcnow() - timedelta(days=days)
                date_filter = {'createdAt': {'$gte': start_date}}
            
            # ===== 1. SUBSCRIPTION REVENUE =====
            subscription_query = {
                'userId': ObjectId(user_id),
                'type': 'SUBSCRIPTION'
            }
            subscription_query.update(date_filter)
            subscriptions = list(mongo.db.corporate_revenue.find(subscription_query))
            
            total_subscription_revenue = sum(s['amount'] for s in subscriptions)
            subscription_gateway_fees = sum(s.get('gatewayFee', 0) for s in subscriptions)
            net_subscription_revenue = total_subscription_revenue - subscription_gateway_fees
            
            # ===== 2. FC CREDITS REVENUE =====
            credits_query = {
                'userId': ObjectId(user_id),
                'type': 'CREDITS_PURCHASE'
            }
            credits_query.update(date_filter)
            credits = list(mongo.db.corporate_revenue.find(credits_query))
            
            total_credits_revenue = sum(c['amount'] for c in credits)
            credits_gateway_fees = sum(c.get('gatewayFee', 0) for c in credits)
            net_credits_revenue = total_credits_revenue - credits_gateway_fees
            
            # ===== 3. DEPOSIT FEES REVENUE =====
            deposit_fee_query = {
                'userId': ObjectId(user_id),
                'type': 'SERVICE_FEE',
                'category': 'DEPOSIT_FEE'
            }
            deposit_fee_query.update(date_filter)
            deposit_fees = list(mongo.db.corporate_revenue.find(deposit_fee_query))
            
            total_deposit_fees = sum(d['amount'] for d in deposit_fees)
            deposit_fee_gateway_costs = sum(d.get('gatewayFee', 0) for d in deposit_fees)
            net_deposit_fees = total_deposit_fees - deposit_fee_gateway_costs
            
            # ===== 4. VAS COMMISSIONS =====
            vas_commission_query = {
                'userId': ObjectId(user_id),
                'type': 'VAS_COMMISSION'
            }
            vas_commission_query.update(date_filter)
            vas_commissions = list(mongo.db.corporate_revenue.find(vas_commission_query))
            
            total_vas_commissions = sum(c['amount'] for c in vas_commissions)
            
            # ===== 5. GATEWAY COSTS (Deposits) =====
            deposit_query = {
                'userId': ObjectId(user_id),
                'type': 'WALLET_FUNDING',
                'status': 'SUCCESS',
                'gatewayFee': {'$exists': True}
            }
            deposit_query.update(date_filter)
            deposits = list(mongo.db.vas_transactions.find(deposit_query))
            
            total_deposits = len(deposits)
            total_deposit_gateway_fees = sum(d.get('gatewayFee', 0) for d in deposits)
            total_deposited = sum(d.get('amountPaid', 0) for d in deposits)
            
            # ===== 6. VAS USAGE =====
            vas_query = {
                'userId': ObjectId(user_id),
                'status': 'SUCCESS',
                'type': {'$in': ['AIRTIME', 'DATA']}
            }
            vas_query.update(date_filter)
            vas_transactions = list(mongo.db.vas_transactions.find(vas_query))
            
            total_vas_transactions = len(vas_transactions)
            total_vas_volume = sum(t.get('amount', 0) for t in vas_transactions)
            
            # ===== 7. CALCULATE TOTALS =====
            total_revenue = (
                net_subscription_revenue +
                net_credits_revenue +
                net_deposit_fees +
                total_vas_commissions
            )
            
            total_costs = (
                subscription_gateway_fees +
                credits_gateway_fees +
                deposit_fee_gateway_costs +
                total_deposit_gateway_fees
            )
            
            net_profit = total_revenue - total_costs
            is_profitable = net_profit > 0
            
            # Calculate profit margin
            profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
            
            # ===== 8. USER STATUS =====
            is_premium = user.get('isSubscribed', False)
            subscription_type = user.get('subscriptionType')
            subscription_end = user.get('subscriptionEndDate')
            
            # ===== 9. PROFITABILITY ASSESSMENT =====
            # For premium users, check if they're within safe deposit limits
            assessment = 'profitable'
            warning = None
            
            if is_premium:
                # Monthly subscription: Safe up to 60 deposits/month
                # Annual subscription: Safe up to 600 deposits/year
                if subscription_type == 'monthly':
                    safe_deposit_limit = 60
                    if period == '30':
                        if total_deposits > safe_deposit_limit:
                            assessment = 'at_risk'
                            warning = f'User exceeds safe deposit limit ({total_deposits} > {safe_deposit_limit}/month)'
                elif subscription_type == 'annually':
                    safe_deposit_limit = 600
                    if period == '365':
                        if total_deposits > safe_deposit_limit:
                            assessment = 'at_risk'
                            warning = f'User exceeds safe deposit limit ({total_deposits} > {safe_deposit_limit}/year)'
                
                # Check if VAS commissions offset deposit costs
                if total_vas_commissions < total_deposit_gateway_fees:
                    if assessment != 'at_risk':
                        assessment = 'low_vas_usage'
                        warning = 'VAS commissions not offsetting deposit costs'
            
            if not is_profitable:
                assessment = 'unprofitable'
                warning = f'User is generating net loss of ₦{abs(net_profit):.2f}'
            
            # ===== 10. FORMAT RESPONSE =====
            return jsonify({
                'success': True,
                'data': {
                    'userId': user_id,
                    'userEmail': user.get('email'),
                    'userName': user.get('displayName', user.get('firstName', 'Unknown')),
                    'isPremium': is_premium,
                    'subscriptionType': subscription_type,
                    'subscriptionEnd': subscription_end.isoformat() if subscription_end else None,
                    'revenue': {
                        'subscription': {
                            'gross': round(total_subscription_revenue, 2),
                            'gatewayFees': round(subscription_gateway_fees, 2),
                            'net': round(net_subscription_revenue, 2)
                        },
                        'credits': {
                            'gross': round(total_credits_revenue, 2),
                            'gatewayFees': round(credits_gateway_fees, 2),
                            'net': round(net_credits_revenue, 2)
                        },
                        'depositFees': {
                            'gross': round(total_deposit_fees, 2),
                            'gatewayFees': round(deposit_fee_gateway_costs, 2),
                            'net': round(net_deposit_fees, 2)
                        },
                        'vasCommissions': round(total_vas_commissions, 2),
                        'total': round(total_revenue, 2)
                    },
                    'costs': {
                        'depositGatewayFees': round(total_deposit_gateway_fees, 2),
                        'subscriptionGatewayFees': round(subscription_gateway_fees, 2),
                        'creditsGatewayFees': round(credits_gateway_fees, 2),
                        'depositFeeGatewayCosts': round(deposit_fee_gateway_costs, 2),
                        'total': round(total_costs, 2)
                    },
                    'usage': {
                        'totalDeposits': total_deposits,
                        'totalDeposited': round(total_deposited, 2),
                        'totalVasTransactions': total_vas_transactions,
                        'totalVasVolume': round(total_vas_volume, 2)
                    },
                    'profitability': {
                        'netProfit': round(net_profit, 2),
                        'isProfitable': is_profitable,
                        'profitMargin': round(profit_margin, 2),
                        'assessment': assessment,
                        'warning': warning
                    },
                    'period': period,
                    'dateRange': {
                        'start': start_date.isoformat() if start_date else None,
                        'end': datetime.utcnow().isoformat()
                    }
                },
                'message': 'User profitability analysis retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting user profitability: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to get user profitability',
                'error': str(e)
            }), 500

    @admin_bp.route('/treasury/corporate-revenue/export', methods=['GET'])
    @token_required
    @admin_required
    def export_corporate_revenue(current_user):
        """Export corporate revenue to CSV"""
        try:
            from flask import make_response
            import csv
            import io
            
            # Get corporate revenue records
            corporate_revenue = list(mongo.db.corporate_revenue.find({}).sort('createdAt', -1))
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write headers
            writer.writerow([
                'Date', 'Type', 'Category', 'Amount', 'Description', 
                'User ID', 'Related Transaction', 'Created At'
            ])
            
            # Write data
            for rev in corporate_revenue:
                writer.writerow([
                    rev.get('createdAt', '').strftime('%Y-%m-%d') if rev.get('createdAt') else '',
                    rev.get('type', ''),
                    rev.get('category', ''),
                    rev.get('amount', 0),
                    rev.get('description', ''),
                    str(rev.get('userId', '')),
                    str(rev.get('relatedTransaction', '')),
                    rev.get('createdAt', '').isoformat() if rev.get('createdAt') else ''
                ])
            
            # Create response
            csv_content = output.getvalue()
            output.close()
            
            response = make_response(csv_content)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=corporate_revenue_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            
            return response
            
        except Exception as e:
            print(f"Error exporting corporate revenue: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to export corporate revenue',
                'error': str(e)
            }), 500
    
    # ===== REFERRAL SYSTEM METRICS ENDPOINT =====
    
    @admin_bp.route('/treasury/referral-metrics', methods=['GET'])
    @token_required
    @admin_required
    def get_referral_metrics(current_user):
        """
        📊 Referral System Metrics for Treasury Dashboard
        Track referral program performance and payouts
        """
        try:
            from datetime import datetime, timedelta
            
            # Get time period filter
            period = request.args.get('period', 'all')
            
            # Calculate date filter
            date_filter = {}
            start_date = None
            if period != 'all':
                days = int(period)
                start_date = datetime.utcnow() - timedelta(days=days)
                date_filter = {'createdAt': {'$gte': start_date}}
            
            # ===== 1. REFERRAL COUNTS =====
            # Total referrals (all-time or filtered)
            referral_query = {}
            referral_query.update(date_filter)
            total_referrals = mongo.db.referrals.count_documents(referral_query)
            
            # Active referrals (made first deposit)
            active_referrals = mongo.db.referrals.count_documents({
                **referral_query,
                'status': {'$in': ['active', 'qualified']}
            })
            
            # Pending referrals (not yet deposited)
            pending_referrals = mongo.db.referrals.count_documents({
                **referral_query,
                'status': 'pending_deposit'
            })
            
            # ===== 2. PAYOUT STATISTICS =====
            payout_query = {}
            payout_query.update(date_filter)
            
            # Total payouts (all statuses)
            all_payouts = list(mongo.db.referral_payouts.find(payout_query))
            total_payouts_amount = sum(p['amount'] for p in all_payouts)
            
            # Withdrawable payouts
            withdrawable_payouts = [p for p in all_payouts if p['status'] == 'WITHDRAWABLE']
            withdrawable_amount = sum(p['amount'] for p in withdrawable_payouts)
            
            # Pending payouts (in vesting)
            pending_payouts = [p for p in all_payouts if p['status'] == 'PENDING']
            pending_amount = sum(p['amount'] for p in pending_payouts)
            
            # Withdrawn payouts
            withdrawn_payouts = [p for p in all_payouts if p['status'] == 'WITHDRAWN']
            withdrawn_amount = sum(p['amount'] for p in withdrawn_payouts)
            
            # ===== 3. PAYOUT BREAKDOWN BY TYPE =====
            subscription_payouts = [p for p in all_payouts if p['type'] == 'SUBSCRIPTION_COMMISSION']
            subscription_payout_amount = sum(p['amount'] for p in subscription_payouts)
            
            vas_payouts = [p for p in all_payouts if p['type'] == 'VAS_SHARE']
            vas_payout_amount = sum(p['amount'] for p in vas_payouts)
            
            # ===== 4. TOP REFERRERS =====
            # Aggregate top referrers by total earnings
            top_referrers_pipeline = [
                {'$match': payout_query},
                {'$group': {
                    '_id': '$referrerId',
                    'totalEarnings': {'$sum': '$amount'},
                    'payoutCount': {'$sum': 1}
                }},
                {'$sort': {'totalEarnings': -1}},
                {'$limit': 10}
            ]
            
            top_referrers_data = list(mongo.db.referral_payouts.aggregate(top_referrers_pipeline))
            
            # Enrich with user details
            top_referrers = []
            for referrer in top_referrers_data:
                user = mongo.db.users.find_one({'_id': referrer['_id']}, {'displayName': 1, 'email': 1, 'referralCode': 1})
                if user:
                    top_referrers.append({
                        'userId': str(referrer['_id']),
                        'name': user.get('displayName', 'Unknown'),
                        'email': user.get('email', 'N/A'),
                        'referralCode': user.get('referralCode', 'N/A'),
                        'totalEarnings': round(referrer['totalEarnings'], 2),
                        'payoutCount': referrer['payoutCount']
                    })
            
            # ===== 5. RECENT PAYOUTS =====
            recent_payouts = list(mongo.db.referral_payouts.find(payout_query).sort('createdAt', -1).limit(20))
            
            # Enrich with user details
            recent_payouts_formatted = []
            for payout in recent_payouts:
                referrer = mongo.db.users.find_one({'_id': payout['referrerId']}, {'displayName': 1, 'email': 1})
                referee = mongo.db.users.find_one({'_id': payout['refereeId']}, {'displayName': 1, 'email': 1})
                
                recent_payouts_formatted.append({
                    'id': str(payout['_id']),
                    'referrerName': referrer.get('displayName', 'Unknown') if referrer else 'Unknown',
                    'referrerEmail': referrer.get('email', 'N/A') if referrer else 'N/A',
                    'refereeName': referee.get('displayName', 'Unknown') if referee else 'Unknown',
                    'refereeEmail': referee.get('email', 'N/A') if referee else 'N/A',
                    'type': payout['type'],
                    'amount': round(payout['amount'], 2),
                    'status': payout['status'],
                    'createdAt': payout['createdAt'].isoformat() if payout.get('createdAt') else None,
                    'vestingEndDate': payout['vestingEndDate'].isoformat() if payout.get('vestingEndDate') else None
                })
            
            # ===== 6. FORMAT RESPONSE =====
            return jsonify({
                'success': True,
                'data': {
                    'overview': {
                        'totalReferrals': total_referrals,
                        'activeReferrals': active_referrals,
                        'pendingReferrals': pending_referrals,
                        'totalPayouts': round(total_payouts_amount, 2),
                        'withdrawablePayouts': round(withdrawable_amount, 2),
                        'pendingPayouts': round(pending_amount, 2),
                        'withdrawnPayouts': round(withdrawn_amount, 2)
                    },
                    'payoutBreakdown': {
                        'subscriptionCommissions': {
                            'amount': round(subscription_payout_amount, 2),
                            'count': len(subscription_payouts)
                        },
                        'vasShares': {
                            'amount': round(vas_payout_amount, 2),
                            'count': len(vas_payouts)
                        }
                    },
                    'topReferrers': top_referrers,
                    'recentPayouts': recent_payouts_formatted,
                    'period': period,
                    'dateRange': {
                        'start': start_date.isoformat() if start_date else None,
                        'end': datetime.utcnow().isoformat()
                    }
                },
                'message': f'Referral metrics retrieved successfully ({period} period)'
            })
            
        except Exception as e:
            print(f"Error getting referral metrics: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to get referral metrics',
                'error': str(e)
            }), 500
    
    # ===== WITHDRAWAL MANAGEMENT ENDPOINTS =====
    
    @admin_bp.route('/withdrawals/pending', methods=['GET'])
    @token_required
    @admin_required
    def get_pending_withdrawals(current_user):
        """
        Get all pending withdrawal requests for admin review.
        """
        try:
            # Get all pending withdrawals
            withdrawals = list(mongo.db.withdrawal_requests.find({
                'status': 'PENDING'
            }).sort('requestedAt', 1))  # FIFO - oldest first
            
            # Enrich with user details and referral stats
            formatted = []
            for w in withdrawals:
                user = mongo.db.users.find_one({'_id': w['userId']})
                if not user:
                    continue
                
                # Get referral stats
                total_referrals = mongo.db.referrals.count_documents({'referrerId': w['userId']})
                active_referrals = mongo.db.referrals.count_documents({
                    'referrerId': w['userId'],
                    'status': {'$in': ['active', 'qualified']}
                })
                total_earnings = user.get('referralEarnings', 0.0)
                
                formatted.append({
                    'id': str(w['_id']),
                    'user': {
                        'id': str(user['_id']),
                        'name': user.get('displayName', 'Unknown'),
                        'email': user.get('email', 'N/A'),
                        'referralCode': user.get('referralCode', 'N/A')
                    },
                    'amount': w['amount'],
                    'withdrawableBalance': w.get('withdrawableBalanceAtRequest', 0.0),
                    'pendingBalance': w.get('pendingBalanceAtRequest', 0.0),
                    'walletBalance': w.get('walletBalanceAtRequest', 0.0),
                    'requestedAt': w['requestedAt'].isoformat(),
                    'referralStats': {
                        'totalReferrals': total_referrals,
                        'activeReferrals': active_referrals,
                        'totalEarnings': round(total_earnings, 2)
                    }
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'pendingWithdrawals': formatted,
                    'count': len(formatted)
                },
                'message': f'{len(formatted)} pending withdrawal(s) found'
            }), 200
            
        except Exception as e:
            print(f"Error getting pending withdrawals: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to get pending withdrawals',
                'error': str(e)
            }), 500
    
    @admin_bp.route('/withdrawals/<withdrawal_id>/approve', methods=['POST'])
    @token_required
    @admin_required
    def approve_withdrawal(current_user, withdrawal_id):
        """
        Approve withdrawal and transfer to wallet balance.
        ATOMIC TRANSACTION with rollback on error.
        """
        try:
            data = request.get_json() or {}
            notes = data.get('notes', '')
            
            # 1. Get withdrawal request
            withdrawal = mongo.db.withdrawal_requests.find_one({'_id': ObjectId(withdrawal_id)})
            if not withdrawal:
                return jsonify({
                    'success': False,
                    'message': 'Withdrawal request not found'
                }), 404
            
            if withdrawal['status'] != 'PENDING':
                return jsonify({
                    'success': False,
                    'message': f'Withdrawal already processed (status: {withdrawal["status"]})'
                }), 400
            
            # 2. Get user
            user = mongo.db.users.find_one({'_id': withdrawal['userId']})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # 3. Verify balance still available
            current_withdrawable = user.get('withdrawableCommissionBalance', 0.0)
            if current_withdrawable < withdrawal['amount']:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient balance. Current: ₦{current_withdrawable:,.2f}, Requested: ₦{withdrawal["amount"]:,.2f}'
                }), 400
            
            # 4. Start atomic transaction
            try:
                # 4a. Update user balances
                # CRITICAL: Update ALL THREE wallet balance fields (Golden Rule 38)
                mongo.db.users.update_one(
                    {'_id': user['_id']},
                    {
                        '$inc': {
                            'withdrawableCommissionBalance': -withdrawal['amount'],
                            'walletBalance': withdrawal['amount'],
                            'liquidWalletBalance': withdrawal['amount'],
                            'vasWalletBalance': withdrawal['amount']
                        },
                        '$set': {
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                
                # 4b. Create VAS transaction for wallet funding
                vas_txn = {
                    'userId': user['_id'],
                    'type': 'WALLET_FUNDING',
                    'subType': 'REFERRAL_WITHDRAWAL',
                    'amount': withdrawal['amount'],
                    'status': 'SUCCESS',
                    'description': f"Referral earnings withdrawal (₦{withdrawal['amount']:,.2f})",
                    'relatedWithdrawal': withdrawal['_id'],
                    'provider': 'internal',
                    'createdAt': datetime.utcnow()
                }
                vas_result = mongo.db.vas_transactions.insert_one(vas_txn)
                
                # 4c. Create corporate revenue entry (expense)
                revenue_entry = {
                    'type': 'REFERRAL_WITHDRAWAL',
                    'category': 'REFERRAL_PAYOUT',
                    'amount': -withdrawal['amount'],  # Negative (expense)
                    'description': f"Referral withdrawal to wallet - {user.get('displayName', 'User')}",
                    'userId': user['_id'],
                    'relatedWithdrawal': withdrawal['_id'],
                    'createdAt': datetime.utcnow()
                }
                revenue_result = mongo.db.corporate_revenue.insert_one(revenue_entry)
                
                # 4d. Update withdrawal request
                mongo.db.withdrawal_requests.update_one(
                    {'_id': withdrawal['_id']},
                    {'$set': {
                        'status': 'COMPLETED',
                        'processedAt': datetime.utcnow(),
                        'completedAt': datetime.utcnow(),
                        'processedBy': current_user['_id'],
                        'notes': notes,
                        'relatedVasTransaction': vas_result.inserted_id,
                        'relatedRevenueEntry': revenue_result.inserted_id,
                        'updatedAt': datetime.utcnow()
                    }}
                )
                
                # 5. Log admin action
                mongo.db.admin_actions.insert_one({
                    'adminId': current_user['_id'],
                    'action': 'WITHDRAWAL_APPROVED',
                    'details': f"User: {user.get('displayName')}, Amount: ₦{withdrawal['amount']:,.2f}",
                    'timestamp': datetime.utcnow()
                })
                
                print(f"✅ Withdrawal approved: {user.get('displayName')} - ₦{withdrawal['amount']:,.2f}")
                
                # 6. Get new wallet balance
                updated_user = mongo.db.users.find_one({'_id': user['_id']})
                new_wallet_balance = updated_user.get('walletBalance', 0.0)
                
                return jsonify({
                    'success': True,
                    'data': {
                        'newWalletBalance': round(new_wallet_balance, 2),
                        'withdrawalId': str(withdrawal['_id'])
                    },
                    'message': 'Withdrawal approved and processed successfully'
                }), 200
                
            except Exception as txn_error:
                # Rollback: Mark withdrawal as FAILED
                mongo.db.withdrawal_requests.update_one(
                    {'_id': withdrawal['_id']},
                    {'$set': {
                        'status': 'FAILED',
                        'notes': f'Processing error: {str(txn_error)}',
                        'updatedAt': datetime.utcnow()
                    }}
                )
                raise txn_error
            
        except Exception as e:
            print(f"Error approving withdrawal: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to approve withdrawal',
                'error': str(e)
            }), 500
    
    @admin_bp.route('/withdrawals/<withdrawal_id>/reject', methods=['POST'])
    @token_required
    @admin_required
    def reject_withdrawal(current_user, withdrawal_id):
        """
        Reject withdrawal request with reason.
        """
        try:
            data = request.get_json() or {}
            reason = data.get('reason', '').strip()
            
            if not reason:
                return jsonify({
                    'success': False,
                    'message': 'Rejection reason is required'
                }), 400
            
            # 1. Get withdrawal request
            withdrawal = mongo.db.withdrawal_requests.find_one({'_id': ObjectId(withdrawal_id)})
            if not withdrawal:
                return jsonify({
                    'success': False,
                    'message': 'Withdrawal request not found'
                }), 404
            
            if withdrawal['status'] != 'PENDING':
                return jsonify({
                    'success': False,
                    'message': f'Withdrawal already processed (status: {withdrawal["status"]})'
                }), 400
            
            # 2. Get user
            user = mongo.db.users.find_one({'_id': withdrawal['userId']})
            
            # 3. Update withdrawal request
            mongo.db.withdrawal_requests.update_one(
                {'_id': withdrawal['_id']},
                {'$set': {
                    'status': 'REJECTED',
                    'processedAt': datetime.utcnow(),
                    'processedBy': current_user['_id'],
                    'rejectionReason': reason,
                    'updatedAt': datetime.utcnow()
                }}
            )
            
            # 4. Log admin action
            mongo.db.admin_actions.insert_one({
                'adminId': current_user['_id'],
                'action': 'WITHDRAWAL_REJECTED',
                'details': f"User: {user.get('displayName') if user else 'Unknown'}, Reason: {reason}",
                'timestamp': datetime.utcnow()
            })
            
            print(f"❌ Withdrawal rejected: {user.get('displayName') if user else 'Unknown'} - Reason: {reason}")
            
            return jsonify({
                'success': True,
                'message': 'Withdrawal rejected successfully'
            }), 200
            
        except Exception as e:
            print(f"Error rejecting withdrawal: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to reject withdrawal',
                'error': str(e)
            }), 500
    
    @admin_bp.route('/withdrawals/history', methods=['GET'])
    @token_required
    @admin_required
    def get_withdrawal_history(current_user):
        """
        Get all withdrawal requests (all statuses) for admin.
        """
        try:
            status_filter = request.args.get('status')  # Optional filter
            limit = int(request.args.get('limit', 50))
            
            # Build query
            query = {}
            if status_filter:
                query['status'] = status_filter.upper()
            
            # Get withdrawals
            withdrawals = list(mongo.db.withdrawal_requests.find(query).sort('requestedAt', -1).limit(limit))
            
            # Format for response
            formatted = []
            for w in withdrawals:
                user = mongo.db.users.find_one({'_id': w['userId']})
                formatted.append({
                    'id': str(w['_id']),
                    'userName': user.get('displayName', 'Unknown') if user else 'Unknown',
                    'userEmail': user.get('email', 'N/A') if user else 'N/A',
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
                    'count': len(formatted)
                },
                'message': f'{len(formatted)} withdrawal(s) found'
            }), 200
            
        except Exception as e:
            print(f"Error getting withdrawal history: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get withdrawal history',
                'error': str(e)
            }), 500
    
    # ===== RATE LIMIT MONITORING ENDPOINTS =====
    
    @admin_bp.route('/rate-limits/overview', methods=['GET'])
    @token_required
    @admin_required
    def get_rate_limits_overview(current_user):
        """Get rate limit overview statistics"""
        try:
            hours = int(request.args.get('hours', 24))
            time_start = datetime.utcnow() - timedelta(hours=hours)
            
            # Mock data for now - replace with actual rate limit collection when implemented
            overview = {
                'totalCalls': 0,
                'callsPerMinute': 0,
                'rateLimitHits': 0,
                'rateLimitRate': 0,
                'errorRate': 0,
                'errorCalls': 0,
                'avgResponseTime': 0
            }
            
            return jsonify({
                'success': True,
                'data': {
                    'overview': overview
                }
            })
            
        except Exception as e:
            print(f"Error getting rate limits overview: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get rate limits overview',
                'error': str(e)
            }), 500
    
    @admin_bp.route('/rate-limits/heavy-users', methods=['GET'])
    @token_required
    @admin_required
    def get_heavy_users(current_user):
        """Get users with high API usage"""
        try:
            hours = int(request.args.get('hours', 24))
            min_calls = int(request.args.get('min_calls', 100))
            
            # Mock data for now - replace with actual rate limit collection when implemented
            heavy_users = []
            
            return jsonify({
                'success': True,
                'data': {
                    'heavyUsers': heavy_users
                }
            })
            
        except Exception as e:
            print(f"Error getting heavy users: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get heavy users',
                'error': str(e)
            }), 500
    
    @admin_bp.route('/rate-limits/endpoint-stats', methods=['GET'])
    @token_required
    @admin_required
    def get_endpoint_stats(current_user):
        """Get endpoint usage statistics"""
        try:
            hours = int(request.args.get('hours', 24))
            
            # Mock data for now - replace with actual rate limit collection when implemented
            endpoints = []
            
            return jsonify({
                'success': True,
                'data': {
                    'endpoints': endpoints
                }
            })
            
        except Exception as e:
            print(f"Error getting endpoint stats: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get endpoint stats',
                'error': str(e)
            }), 500
    
    @admin_bp.route('/rate-limits/violations', methods=['GET'])
    @token_required
    @admin_required
    def get_rate_limit_violations(current_user):
        """Get rate limit violations"""
        try:
            hours = int(request.args.get('hours', 24))
            
            # Mock data for now - replace with actual rate limit collection when implemented
            violations = []
            
            return jsonify({
                'success': True,
                'data': {
                    'violations': violations
                }
            })
            
        except Exception as e:
            print(f"Error getting rate limit violations: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get rate limit violations',
                'error': str(e)
            }), 500
    
    @admin_bp.route('/rate-limits/user/<user_id>', methods=['GET'])
    @token_required
    @admin_required
    def get_user_rate_limit_details(current_user, user_id):
        """Get detailed rate limit information for a specific user"""
        try:
            hours = int(request.args.get('hours', 24))
            
            # Get user info
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Mock data for now - replace with actual rate limit collection when implemented
            user_data = {
                'user': {
                    'displayName': user.get('displayName', 'Unknown'),
                    'email': user.get('email', 'Unknown'),
                    'isSubscribed': user.get('isSubscribed', False)
                },
                'totalCalls': 0,
                'callsPerMinute': 0,
                'timeframe': f'Last {hours} hours',
                'endpoints': []
            }
            
            return jsonify({
                'success': True,
                'data': user_data
            })
            
        except Exception as e:
            print(f"Error getting user rate limit details: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get user rate limit details',
                'error': str(e)
            }), 500
    
    # ===== LIQUID WALLET MANAGEMENT ENDPOINTS =====
    
    @admin_bp.route('/users/<user_id>/wallet', methods=['GET'])
    @token_required
    @admin_required
    def get_user_wallet(current_user, user_id):
        """Get user's liquid wallet information"""
        try:
            # Validate user exists
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get wallet data
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found for this user'
                }), 404
            
            # Serialize wallet data
            wallet_data = serialize_doc(wallet)
            
            return jsonify({
                'success': True,
                'data': wallet_data,
                'message': 'Wallet information retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting user wallet: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get wallet information',
                'errors': {'general': [str(e)]}
            }), 500
    
    @admin_bp.route('/users/<user_id>/wallet/transactions', methods=['GET'])
    @token_required
    @admin_required
    def get_user_wallet_transactions(current_user, user_id):
        """Get user's wallet transaction history"""
        try:
            # Validate user exists
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get transaction history from VAS transactions
            limit = int(request.args.get('limit', 50))
            
            transactions = list(mongo.db.vas_transactions.find({
                'userId': ObjectId(user_id)
            }).sort('createdAt', -1).limit(limit))
            
            # Serialize transactions
            transaction_data = []
            for tx in transactions:
                tx_data = serialize_doc(tx)
                transaction_data.append(tx_data)
            
            return jsonify({
                'success': True,
                'data': {
                    'transactions': transaction_data,
                    'count': len(transaction_data)
                },
                'message': 'Wallet transactions retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error getting wallet transactions: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get wallet transactions',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/wallet/transactions/export', methods=['GET'])
    @token_required
    @admin_required
    def export_user_wallet_transactions(current_user, user_id):
        """Export user's complete wallet transaction history as CSV"""
        try:
            from flask import make_response
            import csv
            from io import StringIO
            
            # Validate user exists
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get ALL wallet transactions (no limit for export)
            transactions = list(mongo.db.vas_transactions.find({
                'userId': ObjectId(user_id)
            }).sort('createdAt', -1))
            
            # Get wallet transaction history from vas_wallets collection
            vas_wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            wallet_history = vas_wallet.get('transactionHistory', []) if vas_wallet else []
            
            # Create CSV
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Date',
                'Transaction ID',
                'Type',
                'Category',
                'Amount (₦)',
                'Balance Before (₦)',
                'Balance After (₦)',
                'Status',
                'Description',
                'Phone Number',
                'Provider',
                'Reference',
                'Admin Notes'
            ])
            
            # Write transaction data
            for tx in transactions:
                writer.writerow([
                    tx.get('createdAt', '').isoformat() if isinstance(tx.get('createdAt'), datetime) else str(tx.get('createdAt', '')),
                    str(tx.get('_id', '')),
                    tx.get('type', ''),
                    tx.get('category', ''),
                    tx.get('amount', 0),
                    tx.get('balanceBefore', ''),
                    tx.get('balanceAfter', ''),
                    tx.get('status', ''),
                    tx.get('description', ''),
                    tx.get('phoneNumber', ''),
                    tx.get('provider', ''),
                    tx.get('referenceTransactionId', ''),
                    tx.get('adminNotes', '')
                ])
            
            # Write wallet history entries (if any)
            for hist in wallet_history:
                writer.writerow([
                    hist.get('timestamp', '').isoformat() if isinstance(hist.get('timestamp'), datetime) else str(hist.get('timestamp', '')),
                    hist.get('transactionId', ''),
                    hist.get('type', ''),
                    'WALLET_HISTORY',
                    hist.get('amount', 0),
                    hist.get('balanceBefore', ''),
                    hist.get('balanceAfter', ''),
                    'SUCCESS',
                    hist.get('description', ''),
                    '',
                    '',
                    '',
                    hist.get('adminEmail', '')
                ])
            
            # Create response
            output.seek(0)
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=liquid_wallet_transactions_{user.get("email", user_id)}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            
            # Log export action
            mongo.db.admin_audit_logs.insert_one({
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user['email'],
                'action': 'export_wallet_transactions',
                'targetUserId': ObjectId(user_id),
                'targetUserEmail': user['email'],
                'timestamp': datetime.utcnow(),
                'details': {
                    'transaction_count': len(transactions) + len(wallet_history)
                }
            })
            
            return response
            
        except Exception as e:
            print(f"Error exporting wallet transactions: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to export wallet transactions',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/credits/transactions/export', methods=['GET'])
    @token_required
    @admin_required
    def export_user_credits_transactions(current_user, user_id):
        """Export user's complete FiCore Credits transaction history as CSV"""
        try:
            from flask import make_response
            import csv
            from io import StringIO
            
            # Validate user exists
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get ALL credits transactions (no limit for export)
            credits_transactions = list(mongo.db.credits.find({
                'userId': ObjectId(user_id)
            }).sort('createdAt', -1))
            
            # Create CSV
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Date',
                'Transaction ID',
                'Type',
                'Amount (FC)',
                'Balance Before (FC)',
                'Balance After (FC)',
                'Status',
                'Description',
                'Source',
                'Reference',
                'Metadata'
            ])
            
            # Write transaction data
            for tx in credits_transactions:
                metadata = tx.get('metadata', {})
                writer.writerow([
                    tx.get('createdAt', '').isoformat() if isinstance(tx.get('createdAt'), datetime) else str(tx.get('createdAt', '')),
                    str(tx.get('_id', '')),
                    tx.get('type', ''),
                    tx.get('amount', 0),
                    tx.get('balanceBefore', ''),
                    tx.get('balanceAfter', ''),
                    tx.get('status', 'SUCCESS'),
                    tx.get('description', ''),
                    tx.get('source', ''),
                    tx.get('referenceId', ''),
                    str(metadata) if metadata else ''
                ])
            
            # Create response
            output.seek(0)
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=ficore_credits_transactions_{user.get("email", user_id)}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            
            # Log export action
            mongo.db.admin_audit_logs.insert_one({
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user['email'],
                'action': 'export_credits_transactions',
                'targetUserId': ObjectId(user_id),
                'targetUserEmail': user['email'],
                'timestamp': datetime.utcnow(),
                'details': {
                    'transaction_count': len(credits_transactions)
                }
            })
            
            return response
            
        except Exception as e:
            print(f"Error exporting credits transactions: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to export credits transactions',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/wallet/refund', methods=['POST'])
    @token_required
    @admin_required
    def process_admin_refund(current_user, user_id):
        """Process admin refund for VAS transaction issues"""
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['amount', 'reason']
            for field in required_fields:
                if field not in data:
                    return jsonify({
                        'success': False,
                        'message': f'Missing required field: {field}'
                    }), 400

            amount = float(data['amount'])
            reason = data['reason'].strip()
            reference_transaction_id = data.get('referenceTransactionId', '')
            
            # Validate inputs
            if amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Refund amount must be greater than 0'
                }), 400
                
            if len(reason) < 10:
                return jsonify({
                    'success': False,
                    'message': 'Reason must be at least 10 characters'
                }), 400

            # Validate user exists
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            # Get or create user's wallet
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                # Create wallet if it doesn't exist
                wallet_data = {
                    '_id': ObjectId(),
                    'userId': ObjectId(user_id),
                    'balance': 0.0,
                    'accountName': user.get('displayName', f"{user.get('firstName', '')} {user.get('lastName', '')}").strip(),
                    'status': 'ACTIVE',
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                }
                mongo.db.vas_wallets.insert_one(wallet_data)
                wallet = wallet_data

            # Calculate new balance
            current_balance = wallet.get('balance', 0.0)
            new_balance = current_balance + amount

            # CRITICAL FIX: Update BOTH balances simultaneously for instant sync
            # Update VAS wallet balance
            mongo.db.vas_wallets.update_one(
                {'userId': ObjectId(user_id)},
                {
                    '$set': {
                        'balance': new_balance,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # 🚀 STREAM FIX: Update ALL THREE wallet balance fields for instant frontend updates
            # CRITICAL: walletBalance, liquidWalletBalance, and vasWalletBalance MUST always be the same
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {
                    '$set': {
                        'walletBalance': new_balance,
                        'liquidWalletBalance': new_balance,
                        'vasWalletBalance': new_balance,
                        'liquidWalletLastUpdated': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            print(f'SUCCESS: Updated BOTH balances after admin refund - VAS wallet: ₦{new_balance:,.2f}, Liquid wallet: ₦{new_balance:,.2f}')
            
            # REMOVED: SSE instant balance update - replaced with polling
            # Clients will detect balance change within 3 seconds via polling
            print(f'INFO: Balance updated for user {user_id}: ₦{new_balance:,.2f} - clients will detect via polling')

            # Create refund transaction record
            refund_transaction = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'type': 'ADMIN_REFUND',
                'category': 'REFUND_CORRECTION',
                'amount': amount,
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'status': 'SUCCESS',
                'description': f'Admin refund: {reason}',
                'referenceTransactionId': reference_transaction_id,
                'processedBy': current_user['_id'],
                'processedByName': current_user.get('displayName', 'Admin'),
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'refundType': 'admin_manual',
                    'adminId': str(current_user['_id']),
                    'adminName': current_user.get('displayName', 'Admin'),
                    'adminEmail': current_user.get('email', ''),
                    'reason': reason,
                    'referenceTransactionId': reference_transaction_id,
                    'processedAt': datetime.utcnow().isoformat() + 'Z'
                }
            }
            
            mongo.db.vas_transactions.insert_one(refund_transaction)

            # Create audit log entry
            audit_entry = {
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user['email'],
                'action': 'wallet_refund',
                'targetUserId': ObjectId(user_id),
                'targetUserEmail': user['email'],
                'amount': amount,
                'reason': reason,
                'referenceTransactionId': reference_transaction_id,
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'timestamp': datetime.utcnow(),
                'details': {
                    'refund_amount': amount,
                    'wallet_balance_before': current_balance,
                    'wallet_balance_after': new_balance,
                    'transaction_id': str(refund_transaction['_id']),
                    'reference_transaction': reference_transaction_id
                }
            }
            
            mongo.db.admin_actions.insert_one(audit_entry)

            # Record corporate expense (refunds are expenses for the company)
            corporate_expense = {
                '_id': ObjectId(),
                'type': 'CUSTOMER_REFUND',
                'category': 'VAS_REFUND',
                'amount': amount,
                'userId': ObjectId(user_id),
                'relatedTransaction': str(refund_transaction['_id']),
                'description': f'Customer refund - {reason}',
                'status': 'RECORDED',
                'processedBy': current_user['_id'],
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'refundAmount': amount,
                    'adminId': str(current_user['_id']),
                    'adminName': current_user.get('displayName', 'Admin'),
                    'reason': reason,
                    'referenceTransactionId': reference_transaction_id
                }
            }
            mongo.db.corporate_expenses.insert_one(corporate_expense)
            print(f'💸 Corporate expense recorded: ₦{amount} refund to user {user_id} - Reason: {reason}')

            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(refund_transaction['_id']),
                    'amount': amount,
                    'previousBalance': current_balance,
                    'newBalance': new_balance,
                    'reason': reason,
                    'referenceTransactionId': reference_transaction_id,
                    'processedBy': current_user.get('displayName', 'Admin'),
                    'processedAt': datetime.utcnow().isoformat() + 'Z'
                },
                'message': f'Refund of ₦{amount:,.2f} processed successfully'
            })

        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid amount format'
            }), 400
        except Exception as e:
            print(f"Error processing admin refund: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to process refund',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/wallet/deduct', methods=['POST'])
    @token_required
    @admin_required
    def process_admin_deduction(current_user, user_id):
        """Process admin deduction for dispute resolution or excess balance correction"""
        try:
            data = request.get_json()
            amount = data.get('amount')
            reason = data.get('reason', '').strip()
            reference_transaction_id = data.get('referenceTransactionId', '').strip()
            
            # Validate inputs
            if not amount or not isinstance(amount, (int, float)):
                return jsonify({
                    'success': False,
                    'message': 'Valid deduction amount is required'
                }), 400
            
            if amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Deduction amount must be greater than 0'
                }), 400
                
            if not reason:
                return jsonify({
                    'success': False,
                    'message': 'Deduction reason is required'
                }), 400
            
            # Get user
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # 🚀 CRITICAL FIX: Get FRESH balance from VAS wallet (source of truth)
            # This prevents race conditions from stale user document balance
            vas_wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if vas_wallet:
                current_balance = vas_wallet.get('balance', 0)
                print(f'INFO: Using VAS wallet balance (source of truth): ₦{current_balance:,.2f}')
            else:
                # Fallback to user document if VAS wallet doesn't exist
                current_balance = user.get('liquidWalletBalance', 0)
                print(f'WARNING: VAS wallet not found, using user document balance: ₦{current_balance:,.2f}')
            
            # Check if user has sufficient balance
            if current_balance < amount:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient balance. User has ₦{current_balance:,.2f}, cannot deduct ₦{amount:,.2f}'
                }), 400
            
            # Calculate new balance
            new_balance = current_balance - amount
            
            # 🚀 CRITICAL FIX: Use atomic update with current balance check to prevent race conditions
            # Update VAS wallet balance (primary source used by backend) with atomic operation
            vas_wallet_result = mongo.db.vas_wallets.update_one(
                {
                    'userId': ObjectId(user_id),
                    'balance': current_balance  # Only update if balance hasn't changed
                },
                {
                    '$set': {
                        'balance': new_balance,
                        'updatedAt': datetime.utcnow()
                    },
                    '$push': {
                        'transactionHistory': {
                            'transactionId': str(ObjectId()),
                            'type': 'ADMIN_DEDUCTION',
                            'amount': amount,
                            'balanceBefore': current_balance,
                            'balanceAfter': new_balance,
                            'description': f'Admin deduction: {reason}',
                            'timestamp': datetime.utcnow(),
                            'adminId': str(current_user['_id']),
                            'adminEmail': current_user['email']
                        }
                    }
                }
            )
            
            # Check if update was successful (balance hasn't changed since we read it)
            if vas_wallet_result.modified_count == 0:
                return jsonify({
                    'success': False,
                    'message': 'Balance changed during operation. Please refresh and try again.',
                    'error': 'RACE_CONDITION_DETECTED'
                }), 409  # Conflict
            
            # Update user's liquid wallet balance (for backward compatibility)
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {
                    '$set': {
                        'liquidWalletBalance': new_balance,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            print(f'SUCCESS: Updated balance after admin deduction - Liquid wallet: ₦{current_balance:,.2f} → ₦{new_balance:,.2f}')
            
            # REMOVED: SSE instant balance update - replaced with polling
            # Clients will detect balance change within 3 seconds via polling
            print(f'INFO: Balance updated for user {user_id}: ₦{new_balance:,.2f} - clients will detect via polling')

            # Create deduction transaction record
            deduction_transaction = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'type': 'ADMIN_DEDUCTION',
                'category': 'BALANCE_CORRECTION',
                'amount': amount,
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'status': 'SUCCESS',
                'description': f'Admin deduction: {reason}',
                'referenceTransactionId': reference_transaction_id,
                'processedBy': current_user['_id'],
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'deductionType': 'admin_manual',
                    'adminId': str(current_user['_id']),
                    'adminName': current_user.get('displayName', 'Admin'),
                    'reason': reason,
                    'referenceTransaction': reference_transaction_id
                }
            }
            
            mongo.db.vas_transactions.insert_one(deduction_transaction)

            # Create audit log entry
            audit_entry = {
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user['email'],
                'action': 'wallet_deduction',
                'targetUserId': ObjectId(user_id),
                'targetUserEmail': user['email'],
                'timestamp': datetime.utcnow(),
                'details': {
                    'deduction_amount': amount,
                    'wallet_balance_before': current_balance,
                    'wallet_balance_after': new_balance,
                    'transaction_id': str(deduction_transaction['_id']),
                    'reason': reason,
                    'reference_transaction': reference_transaction_id
                }
            }
            
            mongo.db.admin_actions.insert_one(audit_entry)

            # Record corporate income (deductions are income for the company)
            corporate_income = {
                '_id': ObjectId(),
                'type': 'CUSTOMER_DEDUCTION',
                'category': 'BALANCE_CORRECTION',
                'amount': amount,
                'userId': ObjectId(user_id),
                'relatedTransaction': str(deduction_transaction['_id']),
                'description': f'Customer balance deduction - {reason}',
                'status': 'RECORDED',
                'processedBy': current_user['_id'],
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'deductionAmount': amount,
                    'adminId': str(current_user['_id']),
                    'adminName': current_user.get('displayName', 'Admin'),
                    'reason': reason
                }
            }
            mongo.db.corporate_income.insert_one(corporate_income)
            print(f'💰 Corporate income recorded: ₦{amount} deduction from user {user_id} - Reason: {reason}')

            # Create expense entry for user's records (deduction appears as expense)
            expense_entry = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'title': f'Admin Deduction - {reason}',
                'description': f'Balance correction by admin: {reason}',
                'amount': amount,
                'category': 'Administrative',
                'subcategory': 'Balance Correction',
                'date': datetime.utcnow(),  # CRITICAL: Must have date field for expense summary
                'transactionType': 'ADMIN_DEDUCTION',
                'adminTransactionId': str(deduction_transaction['_id']),
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
                'status': 'active',
                'isDeleted': False,
                'source': 'admin_deduction'
            }
            
            mongo.db.expenses.insert_one(expense_entry)
            print(f'📝 Expense entry created for user records: ₦{amount} deduction')

            return jsonify({
                'success': True,
                'data': {
                    'transactionId': str(deduction_transaction['_id']),
                    'amount': amount,
                    'previousBalance': current_balance,
                    'newBalance': new_balance,
                    'reason': reason,
                    'processedAt': datetime.utcnow().isoformat() + 'Z'
                },
                'message': f'Deduction of ₦{amount:,.2f} processed successfully'
            })

        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid amount format'
            }), 400
        except Exception as e:
            print(f"Error processing admin deduction: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to process deduction',
                'errors': {'general': [str(e)]}
            }), 500

    @admin_bp.route('/users/<user_id>/wallet/pin-reset', methods=['POST'])
    @token_required
    @admin_required
    def reset_user_vas_pin(current_user, user_id):
        """Reset user's VAS transaction PIN - for admin panel integration"""
        try:
            data = request.get_json()
            reason = data.get('reason', '').strip()
            
            # Validate reason is provided
            if not reason:
                return jsonify({
                    'success': False,
                    'message': 'Reason is required for audit trail',
                    'errors': {'reason': ['Reason is required']}
                }), 400
            
            if len(reason) < 10:
                return jsonify({
                    'success': False,
                    'message': 'Reason must be at least 10 characters',
                    'errors': {'reason': ['Reason must be at least 10 characters']}
                }), 400
            
            # Validate user exists
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get user's wallet
            wallet = mongo.db.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'User wallet not found'
                }), 404
            
            # Check if PIN was actually set
            pin_was_set = bool(wallet.get('vasPinHash'))
            was_locked = bool(wallet.get('pinLockedUntil') and wallet.get('pinLockedUntil') > datetime.utcnow())
            attempts = wallet.get('pinAttempts', 0)
            
            # Reset PIN data
            mongo.db.vas_wallets.update_one(
                {'userId': ObjectId(user_id)},
                {
                    '$unset': {
                        'vasPinHash': '',
                        'vasPinSalt': '',
                        'pinSetupAt': '',
                        'pinLastUsed': ''
                    },
                    '$set': {
                        'pinAttempts': 0,
                        'pinLockedUntil': None,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # Create audit log entry
            audit_entry = {
                '_id': ObjectId(),
                'adminId': current_user['_id'],
                'adminEmail': current_user.get('email', ''),
                'action': 'vas_pin_reset',
                'targetUserId': ObjectId(user_id),
                'targetUserEmail': user.get('email', ''),
                'reason': reason,
                'timestamp': datetime.utcnow(),
                'details': {
                    'pinWasSet': pin_was_set,
                    'wasLocked': was_locked,
                    'failedAttempts': attempts,
                    'resetBy': current_user.get('displayName', 'Admin'),
                    'resetAt': datetime.utcnow().isoformat() + 'Z'
                }
            }
            
            mongo.db.admin_actions.insert_one(audit_entry)
            
            print(f'SUCCESS: Admin {current_user.get("email")} reset VAS PIN for user {user_id} ({user.get("email")}) - Reason: {reason}')
            
            return jsonify({
                'success': True,
                'data': {
                    'resetAt': datetime.utcnow().isoformat() + 'Z',
                    'targetUserId': user_id,
                    'targetUserEmail': user.get('email', ''),
                    'targetUserName': user.get('displayName', ''),
                    'adminEmail': current_user.get('email', ''),
                    'adminName': current_user.get('displayName', 'Admin'),
                    'reason': reason,
                    'previousState': {
                        'pinWasSet': pin_was_set,
                        'wasLocked': was_locked,
                        'failedAttempts': attempts
                    }
                },
                'message': f'VAS PIN reset successfully for {user.get("displayName", "user")}'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Admin PIN reset failed: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'PIN reset failed',
                'error': str(e)
            }), 500
    

    return admin_bp
