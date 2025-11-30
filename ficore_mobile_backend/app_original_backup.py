from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import jwt
import os
from bson import ObjectId
import uuid
from functools import wraps
import re

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ficore-mobile-secret-key-2024')
app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
app.config['JWT_EXPIRATION_DELTA'] = timedelta(hours=24)

# Initialize extensions
CORS(app, origins=['*'])
mongo = PyMongo(app)

# Helper function to convert ObjectId to string
def serialize_doc(doc):
    if doc and '_id' in doc:
        doc['id'] = str(doc['_id'])
        del doc['_id']
    return doc

# JWT token decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token is missing'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = mongo.db.users.find_one({'_id': ObjectId(data['user_id'])})
            if not current_user:
                return jsonify({'success': False, 'message': 'Invalid token'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        return f(current_user, *args, **kwargs)
    return decorated

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated(current_user, *args, **kwargs):
        if current_user.get('role') != 'admin':
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        return f(current_user, *args, **kwargs)
    return decorated

# Validation helpers
def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    return len(password) >= 6

# AUTHENTICATION ENDPOINTS #

@app.route('/auth/login', methods=['POST'])
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
        user = mongo.db.users.find_one({'email': email})
        if not user or not check_password_hash(user['password'], password):
            return jsonify({
                'success': False,
                'message': 'Invalid credentials',
                'errors': {'email': ['Invalid email or password']}
            }), 401
        
        # Generate tokens
        access_token = jwt.encode({
            'user_id': str(user['_id']),
            'exp': datetime.utcnow() + app.config['JWT_EXPIRATION_DELTA']
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        refresh_token = jwt.encode({
            'user_id': str(user['_id']),
            'type': 'refresh',
            'exp': datetime.utcnow() + timedelta(days=30)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        # Update last login
        mongo.db.users.update_one(
            {'_id': user['_id']},
            {'$set': {'lastLogin': datetime.utcnow()}}
        )
        
        return jsonify({
            'success': True,
            'data': {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'expires_at': (datetime.utcnow() + app.config['JWT_EXPIRATION_DELTA']).isoformat() + 'Z',
                'user': {
                    'id': str(user['_id']),
                    'email': user['email'],
                    'displayName': user.get('displayName', user.get('firstName', '') + ' ' + user.get('lastName', '')),
                    'role': user.get('role', 'personal'),
                    'ficoreCreditBalance': user.get('ficoreCreditBalance', 1000.0),
                    'setupComplete': user.get('setupComplete', True),
                    'createdAt': user.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
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

@app.route('/auth/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')
        first_name = data.get('firstName', '').strip()
        last_name = data.get('lastName', '').strip()
        
        errors = {}
        
        # Validation
        if not email:
            errors['email'] = ['Email is required']
        elif not validate_email(email):
            errors['email'] = ['Invalid email format']
        elif mongo.db.users.find_one({'email': email}):
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
        
        # Create user
        user_data = {
            'email': email,
            'password': generate_password_hash(password),
            'firstName': first_name,
            'lastName': last_name,
            'displayName': f"{first_name} {last_name}",
            'role': 'personal',
            'ficoreCreditBalance': 1000.0,
            'setupComplete': False,
            'createdAt': datetime.utcnow(),
            'lastLogin': None,
            'isActive': True
        }
        
        result = mongo.db.users.insert_one(user_data)
        user_id = str(result.inserted_id)
        
        # Generate tokens
        access_token = jwt.encode({
            'user_id': user_id,
            'exp': datetime.utcnow() + app.config['JWT_EXPIRATION_DELTA']
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        refresh_token = jwt.encode({
            'user_id': user_id,
            'type': 'refresh',
            'exp': datetime.utcnow() + timedelta(days=30)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'success': True,
            'data': {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'expires_at': (datetime.utcnow() + app.config['JWT_EXPIRATION_DELTA']).isoformat() + 'Z',
                'user': {
                    'id': user_id,
                    'email': email,
                    'displayName': f"{first_name} {last_name}",
                    'role': 'personal',
                    'ficoreCreditBalance': 1000.0,
                    'setupComplete': False,
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

@app.route('/auth/logout', methods=['POST'])
@token_required
def logout(current_user):
    return jsonify({
        'success': True,
        'message': 'Logged out successfully'
    })

@app.route('/auth/refresh', methods=['POST'])
def refresh_token():
    try:
        data = request.get_json()
        refresh_token = data.get('refresh_token')
        
        if not refresh_token:
            return jsonify({'success': False, 'message': 'Refresh token required'}), 400
        
        try:
            data = jwt.decode(refresh_token, app.config['SECRET_KEY'], algorithms=['HS256'])
            if data.get('type') != 'refresh':
                return jsonify({'success': False, 'message': 'Invalid refresh token'}), 401
                
            user = mongo.db.users.find_one({'_id': ObjectId(data['user_id'])})
            if not user:
                return jsonify({'success': False, 'message': 'User not found'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Refresh token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'Invalid refresh token'}), 401
        
        # Generate new access token
        access_token = jwt.encode({
            'user_id': str(user['_id']),
            'exp': datetime.utcnow() + app.config['JWT_EXPIRATION_DELTA']
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'success': True,
            'data': {
                'access_token': access_token,
                'expires_at': (datetime.utcnow() + app.config['JWT_EXPIRATION_DELTA']).isoformat() + 'Z'
            },
            'message': 'Token refreshed successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Token refresh failed',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/auth/forgot-password', methods=['POST'])
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
        
        user = mongo.db.users.find_one({'email': email})
        if not user:
            # Don't reveal if email exists or not
            return jsonify({
                'success': True,
                'message': 'If the email exists, a reset link has been sent'
            })
        
        # Generate reset token
        reset_token = str(uuid.uuid4())
        mongo.db.users.update_one(
            {'_id': user['_id']},
            {'$set': {
                'resetToken': reset_token,
                'resetTokenExpiry': datetime.utcnow() + timedelta(hours=1)
            }}
        )
        
        # In production, send email here
        # For now, just return success
        return jsonify({
            'success': True,
            'message': 'Password reset instructions sent to your email'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Password reset failed',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/auth/reset-password', methods=['POST'])
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
        
        user = mongo.db.users.find_one({
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
        mongo.db.users.update_one(
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
    
# USER MANAGEMENT ENDPOINTS#

@app.route('/users/profile', methods=['GET'])
@token_required
def get_profile(current_user):
    try:
        user_data = {
            'id': str(current_user['_id']),
            'email': current_user['email'],
            'firstName': current_user.get('firstName', ''),
            'lastName': current_user.get('lastName', ''),
            'displayName': current_user.get('displayName', ''),
            'phone': current_user.get('phone', ''),
            'address': current_user.get('address', ''),
            'dateOfBirth': current_user.get('dateOfBirth', ''),
            'role': current_user.get('role', 'personal'),
            'ficoreCreditBalance': current_user.get('ficoreCreditBalance', 0.0),
            'setupComplete': current_user.get('setupComplete', False),
            'createdAt': current_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
            'lastLogin': current_user.get('lastLogin', datetime.utcnow()).isoformat() + 'Z' if current_user.get('lastLogin') else None
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

@app.route('/users/profile', methods=['PUT'])
@token_required
def update_profile(current_user):
    try:
        data = request.get_json()
        
        # Fields that can be updated
        updatable_fields = ['firstName', 'lastName', 'phone', 'address', 'dateOfBirth']
        update_data = {}
        
        for field in updatable_fields:
            if field in data:
                update_data[field] = data[field]
        
        # Update display name if first or last name changed
        if 'firstName' in update_data or 'lastName' in update_data:
            first_name = update_data.get('firstName', current_user.get('firstName', ''))
            last_name = update_data.get('lastName', current_user.get('lastName', ''))
            update_data['displayName'] = f"{first_name} {last_name}".strip()
        
        if update_data:
            update_data['updatedAt'] = datetime.utcnow()
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': update_data}
            )
        
        # Get updated user
        updated_user = mongo.db.users.find_one({'_id': current_user['_id']})
        
        user_data = {
            'id': str(updated_user['_id']),
            'email': updated_user['email'],
            'firstName': updated_user.get('firstName', ''),
            'lastName': updated_user.get('lastName', ''),
            'displayName': updated_user.get('displayName', ''),
            'phone': updated_user.get('phone', ''),
            'address': updated_user.get('address', ''),
            'dateOfBirth': updated_user.get('dateOfBirth', ''),
            'role': updated_user.get('role', 'personal'),
            'ficoreCreditBalance': updated_user.get('ficoreCreditBalance', 0.0),
            'setupComplete': updated_user.get('setupComplete', False),
            'createdAt': updated_user.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
            'lastLogin': updated_user.get('lastLogin', datetime.utcnow()).isoformat() + 'Z' if updated_user.get('lastLogin') else None
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

@app.route('/users/setup', methods=['POST'])
@token_required
def setup_profile(current_user):
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
        
        mongo.db.users.update_one(
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

@app.route('/users/change-password', methods=['POST'])
@token_required
def change_password(current_user):
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
        elif not validate_password(new_password):
            errors['newPassword'] = ['Password must be at least 6 characters']
        elif current_password == new_password:
            errors['newPassword'] = ['New password must be different from current password']
        
        if errors:
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': errors
            }), 400
        
        # Update password
        mongo.db.users.update_one(
            {'_id': current_user['_id']},
            {'$set': {
                'password': generate_password_hash(new_password),
                'passwordChangedAt': datetime.utcnow()
            }}
        )
        
        return jsonify({
            'success': True,
            'message': 'Password changed successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Password change failed',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/users/delete', methods=['DELETE'])
@token_required
def delete_account(current_user):
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
        mongo.db.users.update_one(
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

@app.route('/users/settings', methods=['GET'])
@token_required
def get_settings(current_user):
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

@app.route('/users/settings', methods=['PUT'])
@token_required
def update_settings(current_user):
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
        
        mongo.db.users.update_one(
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
        
# BUDGET MANAGEMENT ENDPOINTS#

@app.route('/budget/budgets', methods=['GET'])
@token_required
def get_budgets(current_user):
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        status = request.args.get('status')
        
        # Build query
        query = {'userId': current_user['_id']}
        if status:
            query['status'] = status
        
        # Get budgets with pagination
        skip = (page - 1) * limit
        budgets = list(mongo.db.budgets.find(query).sort('createdAt', -1).skip(skip).limit(limit))
        total = mongo.db.budgets.count_documents(query)
        
        # Serialize budgets
        budget_list = []
        for budget in budgets:
            budget_data = serialize_doc(budget)
            budget_data['createdAt'] = budget_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            budget_data['updatedAt'] = budget_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            budget_list.append(budget_data)
        
        return jsonify({
            'success': True,
            'data': {
                'budgets': budget_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                }
            },
            'message': 'Budgets retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve budgets',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/budget/budgets/<budget_id>', methods=['GET'])
@token_required
def get_budget(current_user, budget_id):
    try:
        budget = mongo.db.budgets.find_one({
            '_id': ObjectId(budget_id),
            'userId': current_user['_id']
        })
        
        if not budget:
            return jsonify({
                'success': False,
                'message': 'Budget not found'
            }), 404
        
        budget_data = serialize_doc(budget)
        budget_data['createdAt'] = budget_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
        budget_data['updatedAt'] = budget_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
        
        return jsonify({
            'success': True,
            'data': budget_data,
            'message': 'Budget retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve budget',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/budget/new', methods=['POST'])
@token_required
def create_budget(current_user):
    try:
        data = request.get_json()
        
        # Validation
        errors = {}
        if not data.get('name'):
            errors['name'] = ['Budget name is required']
        if not data.get('income') or data.get('income', 0) <= 0:
            errors['income'] = ['Valid income amount is required']
        if not data.get('categories') or not isinstance(data.get('categories'), list):
            errors['categories'] = ['Budget categories are required']
        
        if errors:
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': errors
            }), 400
        
        # Calculate totals
        total_allocated = sum(cat.get('allocated', 0) for cat in data.get('categories', []))
        surplus_deficit = data.get('income', 0) - total_allocated
        
        budget_data = {
            'userId': current_user['_id'],
            'name': data['name'],
            'description': data.get('description', ''),
            'income': float(data['income']),
            'categories': data['categories'],
            'totalAllocated': total_allocated,
            'totalSpent': 0.0,
            'surplusDeficit': surplus_deficit,
            'period': data.get('period', 'monthly'),
            'startDate': datetime.fromisoformat(data.get('startDate', datetime.utcnow().isoformat())),
            'endDate': datetime.fromisoformat(data.get('endDate', (datetime.utcnow() + timedelta(days=30)).isoformat())),
            'status': 'active',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        result = mongo.db.budgets.insert_one(budget_data)
        budget_id = str(result.inserted_id)
        
        return jsonify({
            'success': True,
            'data': {
                'id': budget_id,
                'name': budget_data['name'],
                'income': budget_data['income'],
                'totalAllocated': budget_data['totalAllocated'],
                'surplusDeficit': budget_data['surplusDeficit']
            },
            'message': 'Budget created successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to create budget',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/budget/budgets/<budget_id>', methods=['PUT'])
@token_required
def update_budget(current_user, budget_id):
    try:
        data = request.get_json()
        
        # Check if budget exists and belongs to user
        budget = mongo.db.budgets.find_one({
            '_id': ObjectId(budget_id),
            'userId': current_user['_id']
        })
        
        if not budget:
            return jsonify({
                'success': False,
                'message': 'Budget not found'
            }), 404
        
        # Update fields
        update_data = {}
        if 'name' in data:
            update_data['name'] = data['name']
        if 'description' in data:
            update_data['description'] = data['description']
        if 'income' in data:
            update_data['income'] = float(data['income'])
        if 'categories' in data:
            update_data['categories'] = data['categories']
            update_data['totalAllocated'] = sum(cat.get('allocated', 0) for cat in data['categories'])
        
        # Recalculate surplus/deficit if income or categories changed
        if 'income' in update_data or 'categories' in update_data:
            income = update_data.get('income', budget['income'])
            total_allocated = update_data.get('totalAllocated', budget['totalAllocated'])
            update_data['surplusDeficit'] = income - total_allocated
        
        update_data['updatedAt'] = datetime.utcnow()
        
        mongo.db.budgets.update_one(
            {'_id': ObjectId(budget_id)},
            {'$set': update_data}
        )
        
        return jsonify({
            'success': True,
            'message': 'Budget updated successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to update budget',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/budget/budgets/<budget_id>', methods=['DELETE'])
@token_required
def delete_budget(current_user, budget_id):
    try:
        # Check if budget exists and belongs to user
        budget = mongo.db.budgets.find_one({
            '_id': ObjectId(budget_id),
            'userId': current_user['_id']
        })
        
        if not budget:
            return jsonify({
                'success': False,
                'message': 'Budget not found'
            }), 404
        
        # Soft delete
        mongo.db.budgets.update_one(
            {'_id': ObjectId(budget_id)},
            {'$set': {
                'status': 'deleted',
                'deletedAt': datetime.utcnow()
            }}
        )
        
        return jsonify({
            'success': True,
            'message': 'Budget deleted successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to delete budget',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/budget/dashboard', methods=['GET'])
@token_required
def get_budget_dashboard(current_user):
    try:
        # Get current month's active budgets
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month_end = (current_month_start + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        
        # Simplified query to avoid potential date issues
        budgets = list(mongo.db.budgets.find({
            'userId': current_user['_id'],
            'status': 'active'
        }))
        
        # Calculate dashboard metrics
        total_income = sum(float(b.get('income', 0)) for b in budgets)
        total_allocated = sum(float(b.get('totalAllocated', 0)) for b in budgets)
        total_spent = sum(float(b.get('totalSpent', 0)) for b in budgets)
        total_remaining = total_allocated - total_spent
        
        # Get recent budgets (simplified query to avoid date issues)
        recent_budgets = list(mongo.db.budgets.find({
            'userId': current_user['_id']
        }).sort('createdAt', -1).limit(5))
        
        recent_budget_list = []
        for budget in recent_budgets:
            budget_data = serialize_doc(budget.copy())  # Make a copy to avoid modifying original
            # Handle createdAt safely
            created_at = budget_data.get('createdAt')
            if created_at:
                if isinstance(created_at, datetime):
                    budget_data['createdAt'] = created_at.isoformat() + 'Z'
                else:
                    budget_data['createdAt'] = str(created_at)
            else:
                budget_data['createdAt'] = datetime.utcnow().isoformat() + 'Z'
            recent_budget_list.append(budget_data)
        
        dashboard_data = {
            'summary': {
                'totalIncome': float(total_income),
                'totalAllocated': float(total_allocated),
                'totalSpent': float(total_spent),
                'totalRemaining': float(total_remaining),
                'budgetCount': len(budgets)
            },
            'recentBudgets': recent_budget_list,
            'currentMonth': {
                'year': current_month_start.year,
                'month': current_month_start.month,
                'monthName': current_month_start.strftime('%B')
            }
        }
        
        return jsonify({
            'success': True,
            'data': dashboard_data,
            'message': 'Budget dashboard retrieved successfully'
        })
        
    except Exception as e:
        print(f"Dashboard error: {str(e)}")  # Add logging
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve budget dashboard',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/budget/statistics', methods=['GET'])
@token_required
def get_budget_statistics(current_user):
    try:
        # Get date range from query params
        months = int(request.args.get('months', 6))
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=months * 30)
        
        # Get budgets in date range
        budgets = list(mongo.db.budgets.find({
            'userId': current_user['_id'],
            'createdAt': {'$gte': start_date, '$lte': end_date}
        }).sort('createdAt', 1))
        
        # Calculate monthly statistics
        monthly_stats = {}
        for budget in budgets:
            month_key = budget['createdAt'].strftime('%Y-%m')
            if month_key not in monthly_stats:
                monthly_stats[month_key] = {
                    'month': budget['createdAt'].strftime('%B %Y'),
                    'totalIncome': 0,
                    'totalAllocated': 0,
                    'totalSpent': 0,
                    'budgetCount': 0
                }
            
            monthly_stats[month_key]['totalIncome'] += budget.get('income', 0)
            monthly_stats[month_key]['totalAllocated'] += budget.get('totalAllocated', 0)
            monthly_stats[month_key]['totalSpent'] += budget.get('totalSpent', 0)
            monthly_stats[month_key]['budgetCount'] += 1
        
        # Category analysis
        category_stats = {}
        for budget in budgets:
            for category in budget.get('categories', []):
                cat_name = category.get('name', 'Unknown')
                if cat_name not in category_stats:
                    category_stats[cat_name] = {
                        'name': cat_name,
                        'totalAllocated': 0,
                        'totalSpent': 0,
                        'count': 0
                    }
                
                category_stats[cat_name]['totalAllocated'] += category.get('allocated', 0)
                category_stats[cat_name]['totalSpent'] += category.get('spent', 0)
                category_stats[cat_name]['count'] += 1
        
        statistics_data = {
            'monthlyTrends': list(monthly_stats.values()),
            'categoryBreakdown': list(category_stats.values()),
            'summary': {
                'totalBudgets': len(budgets),
                'averageIncome': sum(b.get('income', 0) for b in budgets) / len(budgets) if budgets else 0,
                'averageSpending': sum(b.get('totalSpent', 0) for b in budgets) / len(budgets) if budgets else 0,
                'savingsRate': 0  # Calculate based on income vs spending
            }
        }
        
        return jsonify({
            'success': True,
            'data': statistics_data,
            'message': 'Budget statistics retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve budget statistics',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/budget/recent', methods=['GET'])
@token_required
def get_recent_budgets(current_user):
    try:
        limit = int(request.args.get('limit', 5))
        
        budgets = list(mongo.db.budgets.find({
            'userId': current_user['_id'],
            'status': 'active'
        }).sort('createdAt', -1).limit(limit))
        
        budget_list = []
        for budget in budgets:
            budget_data = serialize_doc(budget)
            budget_data['createdAt'] = budget_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            budget_data['updatedAt'] = budget_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            budget_list.append(budget_data)
        
        return jsonify({
            'success': True,
            'data': budget_list,
            'message': 'Recent budgets retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve recent budgets',
            'errors': {'general': [str(e)]}
        }), 500
        
# INCOME MANAGEMENT ENDPOINTS #

@app.route('/income', methods=['GET'])
@token_required
def get_incomes(current_user):
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        category = request.args.get('category')
        frequency = request.args.get('frequency')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Build query
        query = {'userId': current_user['_id']}
        if category:
            query['category'] = category
        if frequency:
            query['frequency'] = frequency
        if start_date and end_date:
            query['dateReceived'] = {
                '$gte': datetime.fromisoformat(start_date),
                '$lte': datetime.fromisoformat(end_date)
            }
        
        # Get incomes with pagination
        skip = (page - 1) * limit
        incomes = list(mongo.db.incomes.find(query).sort('dateReceived', -1).skip(skip).limit(limit))
        total = mongo.db.incomes.count_documents(query)
        
        # Serialize incomes
        income_list = []
        for income in incomes:
            income_data = serialize_doc(income)
            income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
            income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            income_data['updatedAt'] = income_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if income_data.get('updatedAt') else None
            income_list.append(income_data)
        
        return jsonify({
            'success': True,
            'data': {
                'incomes': income_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                }
            },
            'message': 'Income records retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve income records',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/income/<income_id>', methods=['GET'])
@token_required
def get_income(current_user, income_id):
    try:
        income = mongo.db.incomes.find_one({
            '_id': ObjectId(income_id),
            'userId': current_user['_id']
        })
        
        if not income:
            return jsonify({
                'success': False,
                'message': 'Income record not found'
            }), 404
        
        income_data = serialize_doc(income)
        income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
        income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
        income_data['updatedAt'] = income_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if income_data.get('updatedAt') else None
        
        return jsonify({
            'success': True,
            'data': income_data,
            'message': 'Income record retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve income record',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/income', methods=['POST'])
@token_required
def create_income(current_user):
    try:
        data = request.get_json()
        
        # Validation
        errors = {}
        if not data.get('amount') or data.get('amount', 0) <= 0:
            errors['amount'] = ['Valid amount is required']
        if not data.get('source'):
            errors['source'] = ['Income source is required']
        if not data.get('category'):
            errors['category'] = ['Income category is required']
        if not data.get('frequency'):
            errors['frequency'] = ['Income frequency is required']
        
        if errors:
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': errors
            }), 400
        
        # Calculate next recurring date if applicable
        next_recurring_date = None
        is_recurring = data.get('frequency', 'one_time') != 'one_time'
        
        if is_recurring:
            date_received = datetime.fromisoformat(data.get('dateReceived', datetime.utcnow().isoformat()))
            frequency = data.get('frequency')
            
            if frequency == 'daily':
                next_recurring_date = date_received + timedelta(days=1)
            elif frequency == 'weekly':
                next_recurring_date = date_received + timedelta(weeks=1)
            elif frequency == 'biweekly':
                next_recurring_date = date_received + timedelta(weeks=2)
            elif frequency == 'monthly':
                next_recurring_date = date_received + timedelta(days=30)
            elif frequency == 'quarterly':
                next_recurring_date = date_received + timedelta(days=90)
            elif frequency == 'yearly':
                next_recurring_date = date_received + timedelta(days=365)
        
        income_data = {
            'userId': current_user['_id'],
            'amount': float(data['amount']),
            'source': data['source'],
            'description': data.get('description', ''),
            'category': data['category'],
            'frequency': data['frequency'],
            'dateReceived': datetime.fromisoformat(data.get('dateReceived', datetime.utcnow().isoformat())),
            'isRecurring': is_recurring,
            'nextRecurringDate': next_recurring_date,
            'metadata': data.get('metadata', {}),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        result = mongo.db.incomes.insert_one(income_data)
        income_id = str(result.inserted_id)
        
        return jsonify({
            'success': True,
            'data': {
                'id': income_id,
                'amount': income_data['amount'],
                'source': income_data['source'],
                'category': income_data['category'],
                'frequency': income_data['frequency']
            },
            'message': 'Income record created successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to create income record',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/income/<income_id>', methods=['PUT'])
@token_required
def update_income(current_user, income_id):
    try:
        data = request.get_json()
        
        # Check if income exists
        income = mongo.db.incomes.find_one({
            '_id': ObjectId(income_id),
            'userId': current_user['_id']
        })
        
        if not income:
            return jsonify({
                'success': False,
                'message': 'Income record not found'
            }), 404
        
        # Build update data
        update_data = {}
        updatable_fields = ['amount', 'source', 'description', 'category', 'frequency', 'dateReceived', 'metadata']
        
        for field in updatable_fields:
            if field in data:
                if field == 'amount':
                    update_data[field] = float(data[field])
                elif field == 'dateReceived':
                    update_data[field] = datetime.fromisoformat(data[field])
                else:
                    update_data[field] = data[field]
        
        # Update recurring settings if frequency changed
        if 'frequency' in update_data:
            is_recurring = update_data['frequency'] != 'one_time'
            update_data['isRecurring'] = is_recurring
            
            if is_recurring and 'dateReceived' in update_data:
                frequency = update_data['frequency']
                date_received = update_data['dateReceived']
                
                if frequency == 'daily':
                    update_data['nextRecurringDate'] = date_received + timedelta(days=1)
                elif frequency == 'weekly':
                    update_data['nextRecurringDate'] = date_received + timedelta(weeks=1)
                elif frequency == 'biweekly':
                    update_data['nextRecurringDate'] = date_received + timedelta(weeks=2)
                elif frequency == 'monthly':
                    update_data['nextRecurringDate'] = date_received + timedelta(days=30)
                elif frequency == 'quarterly':
                    update_data['nextRecurringDate'] = date_received + timedelta(days=90)
                elif frequency == 'yearly':
                    update_data['nextRecurringDate'] = date_received + timedelta(days=365)
            else:
                update_data['nextRecurringDate'] = None
        
        if update_data:
            update_data['updatedAt'] = datetime.utcnow()
            mongo.db.incomes.update_one(
                {'_id': ObjectId(income_id)},
                {'$set': update_data}
            )
        
        # Get updated income
        updated_income = mongo.db.incomes.find_one({'_id': ObjectId(income_id)})
        income_data = serialize_doc(updated_income)
        income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
        income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
        income_data['updatedAt'] = income_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
        
        return jsonify({
            'success': True,
            'data': income_data,
            'message': 'Income record updated successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to update income record',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/income/<income_id>', methods=['DELETE'])
@token_required
def delete_income(current_user, income_id):
    try:
        # Check if income exists
        income = mongo.db.incomes.find_one({
            '_id': ObjectId(income_id),
            'userId': current_user['_id']
        })
        
        if not income:
            return jsonify({
                'success': False,
                'message': 'Income record not found'
            }), 404
        
        # Delete income
        mongo.db.incomes.delete_one({'_id': ObjectId(income_id)})
        
        return jsonify({
            'success': True,
            'message': 'Income record deleted successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to delete income record',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/income/summary', methods=['GET'])
@token_required
def get_income_summary(current_user):
    try:
        # Get current month dates
        now = datetime.utcnow()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month_end = (current_month_start + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        
        # Get last month dates
        last_month_end = current_month_start - timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Get year start
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate totals
        total_this_month = list(mongo.db.incomes.aggregate([
            {'$match': {
                'userId': current_user['_id'],
                'dateReceived': {'$gte': current_month_start, '$lte': current_month_end}
            }},
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
        ]))
        total_this_month = total_this_month[0]['total'] if total_this_month else 0.0
        
        total_last_month = list(mongo.db.incomes.aggregate([
            {'$match': {
                'userId': current_user['_id'],
                'dateReceived': {'$gte': last_month_start, '$lte': last_month_end}
            }},
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
        ]))
        total_last_month = total_last_month[0]['total'] if total_last_month else 0.0
        
        year_to_date = list(mongo.db.incomes.aggregate([
            {'$match': {
                'userId': current_user['_id'],
                'dateReceived': {'$gte': year_start}
            }},
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
        ]))
        year_to_date = year_to_date[0]['total'] if year_to_date else 0.0
        
        # Calculate growth percentage
        growth_percentage = 0.0
        if total_last_month > 0:
            growth_percentage = ((total_this_month - total_last_month) / total_last_month) * 100
        
        # Get total records count
        total_records = mongo.db.incomes.count_documents({'userId': current_user['_id']})
        
        # Get recent incomes
        recent_incomes = list(mongo.db.incomes.find({
            'userId': current_user['_id']
        }).sort('dateReceived', -1).limit(5))
        
        recent_income_list = []
        for income in recent_incomes:
            income_data = serialize_doc(income)
            income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
            income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            recent_income_list.append(income_data)
        
        # Get top sources
        top_sources_data = list(mongo.db.incomes.aggregate([
            {'$match': {'userId': current_user['_id']}},
            {'$group': {'_id': '$source', 'total': {'$sum': '$amount'}}},
            {'$sort': {'total': -1}},
            {'$limit': 5}
        ]))
        top_sources = {item['_id']: item['total'] for item in top_sources_data}
        
        # Calculate average monthly (last 12 months)
        twelve_months_ago = now - timedelta(days=365)
        monthly_totals = list(mongo.db.incomes.aggregate([
            {'$match': {
                'userId': current_user['_id'],
                'dateReceived': {'$gte': twelve_months_ago}
            }},
            {'$group': {
                '_id': {'year': {'$year': '$dateReceived'}, 'month': {'$month': '$dateReceived'}},
                'total': {'$sum': '$amount'}
            }}
        ]))
        average_monthly = sum(item['total'] for item in monthly_totals) / max(len(monthly_totals), 1)
        
        summary_data = {
            'total_this_month': float(total_this_month),
            'total_last_month': float(total_last_month),
            'average_monthly': float(average_monthly),
            'year_to_date': float(year_to_date),
            'total_records': total_records,
            'recent_incomes': recent_income_list,
            'top_sources': top_sources,
            'growth_percentage': float(growth_percentage)
        }
        
        return jsonify({
            'success': True,
            'data': summary_data,
            'message': 'Income summary retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve income summary',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/income/statistics', methods=['GET'])
@token_required
def get_income_statistics(current_user):
    try:
        period = request.args.get('period', 'year')  # month, quarter, year
        
        # Calculate date range based on period
        now = datetime.utcnow()
        if period == 'month':
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == 'quarter':
            quarter_start_month = ((now.month - 1) // 3) * 3 + 1
            start_date = now.replace(month=quarter_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # year
            start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Get all incomes in period
        incomes = list(mongo.db.incomes.find({
            'userId': current_user['_id'],
            'dateReceived': {'$gte': start_date}
        }))
        
        if not incomes:
            return jsonify({
                'success': True,
                'data': {
                    'total_income': 0.0,
                    'monthly_average': 0.0,
                    'yearly_projection': 0.0,
                    'category_breakdown': {},
                    'source_breakdown': {},
                    'frequency_breakdown': {},
                    'trends': [],
                    'growth_rate': 0.0,
                    'top_category': 'other',
                    'top_source': ''
                },
                'message': 'Income statistics retrieved successfully'
            })
        
        # Calculate totals
        total_income = sum(income['amount'] for income in incomes)
        
        # Category breakdown
        category_breakdown = {}
        for income in incomes:
            category = income.get('category', 'other')
            category_breakdown[category] = category_breakdown.get(category, 0) + income['amount']
        
        # Source breakdown
        source_breakdown = {}
        for income in incomes:
            source = income.get('source', 'Unknown')
            source_breakdown[source] = source_breakdown.get(source, 0) + income['amount']
        
        # Frequency breakdown
        frequency_breakdown = {}
        for income in incomes:
            frequency = income.get('frequency', 'one_time')
            frequency_breakdown[frequency] = frequency_breakdown.get(frequency, 0) + income['amount']
        
        # Calculate projections
        months_in_period = (now - start_date).days / 30.44
        monthly_average = total_income / max(months_in_period, 1)
        yearly_projection = monthly_average * 12
        
        # Get top category and source
        top_category = max(category_breakdown.items(), key=lambda x: x[1])[0] if category_breakdown else 'other'
        top_source = max(source_breakdown.items(), key=lambda x: x[1])[0] if source_breakdown else ''
        
        # Calculate growth rate (compare with previous period)
        prev_start = start_date - (now - start_date)
        prev_incomes = list(mongo.db.incomes.find({
            'userId': current_user['_id'],
            'dateReceived': {'$gte': prev_start, '$lt': start_date}
        }))
        prev_total = sum(income['amount'] for income in prev_incomes)
        growth_rate = ((total_income - prev_total) / max(prev_total, 1)) * 100 if prev_total > 0 else 0.0
        
        # Generate trends (monthly breakdown)
        trends = []
        current_date = start_date
        while current_date < now:
            next_month = (current_date + timedelta(days=32)).replace(day=1)
            month_incomes = [i for i in incomes if current_date <= i['dateReceived'] < next_month]
            month_total = sum(i['amount'] for i in month_incomes)
            
            # Category amounts for this month
            month_categories = {}
            for income in month_incomes:
                category = income.get('category', 'other')
                month_categories[category] = month_categories.get(category, 0) + income['amount']
            
            trends.append({
                'date': current_date.isoformat() + 'Z',
                'amount': month_total,
                'count': len(month_incomes),
                'category_amounts': month_categories
            })
            
            current_date = next_month
        
        statistics_data = {
            'total_income': float(total_income),
            'monthly_average': float(monthly_average),
            'yearly_projection': float(yearly_projection),
            'category_breakdown': {k: float(v) for k, v in category_breakdown.items()},
            'source_breakdown': {k: float(v) for k, v in source_breakdown.items()},
            'frequency_breakdown': {k: float(v) for k, v in frequency_breakdown.items()},
            'trends': trends,
            'growth_rate': float(growth_rate),
            'top_category': top_category,
            'top_source': top_source
        }
        
        return jsonify({
            'success': True,
            'data': statistics_data,
            'message': 'Income statistics retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve income statistics',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/income/recent', methods=['GET'])
@token_required
def get_recent_incomes(current_user):
    try:
        limit = int(request.args.get('limit', 10))
        
        incomes = list(mongo.db.incomes.find({
            'userId': current_user['_id']
        }).sort('dateReceived', -1).limit(limit))
        
        income_list = []
        for income in incomes:
            income_data = serialize_doc(income)
            income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
            income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            income_list.append(income_data)
        
        return jsonify({
            'success': True,
            'data': {'incomes': income_list},
            'message': 'Recent income records retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve recent income records',
            'errors': {'general': [str(e)]}
        }), 500

# EXPENSE TRACKING ENDPOINTS #

@app.route('/tracking', methods=['GET'])
@token_required
def get_expenses(current_user):
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        category = request.args.get('category')
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        
        # Build query
        query = {'userId': current_user['_id']}
        
        if category:
            query['category'] = category
        
        if start_date and end_date:
            query['date'] = {
                '$gte': datetime.fromisoformat(start_date),
                '$lte': datetime.fromisoformat(end_date)
            }
        
        # Get expenses with pagination
        skip = (page - 1) * limit
        expenses = list(mongo.db.expenses.find(query).sort('date', -1).skip(skip).limit(limit))
        total = mongo.db.expenses.count_documents(query)
        
        # Serialize expenses
        expense_list = []
        for expense in expenses:
            expense_data = serialize_doc(expense)
            expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            expense_list.append(expense_data)
        
        return jsonify({
            'success': True,
            'data': {
                'expenses': expense_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                }
            },
            'message': 'Expenses retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve expenses',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/tracking', methods=['POST'])
@token_required
def create_expense(current_user):
    try:
        data = request.get_json()
        
        # Validation
        errors = {}
        if not data.get('title'):
            errors['title'] = ['Expense title is required']
        if not data.get('amount') or data.get('amount', 0) <= 0:
            errors['amount'] = ['Valid amount is required']
        if not data.get('category'):
            errors['category'] = ['Category is required']
        
        if errors:
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': errors
            }), 400
        
        expense_data = {
            'userId': current_user['_id'],
            'title': data['title'],
            'amount': float(data['amount']),
            'category': data['category'],
            'description': data.get('description', ''),
            'date': datetime.fromisoformat(data.get('date', datetime.utcnow().isoformat())),
            'paymentMethod': data.get('paymentMethod', 'cash'),
            'tags': data.get('tags', []),
            'receiptUrl': data.get('receiptUrl', ''),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        result = mongo.db.expenses.insert_one(expense_data)
        expense_id = str(result.inserted_id)
        
        # Update budget spending if applicable
        if data.get('budgetId'):
            mongo.db.budgets.update_one(
                {'_id': ObjectId(data['budgetId']), 'userId': current_user['_id']},
                {'$inc': {'totalSpent': expense_data['amount']}}
            )
        
        return jsonify({
            'success': True,
            'data': {
                'id': expense_id,
                'title': expense_data['title'],
                'amount': expense_data['amount'],
                'category': expense_data['category'],
                'date': expense_data['date'].isoformat() + 'Z'
            },
            'message': 'Expense created successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to create expense',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/tracking/expense/<expense_id>', methods=['PUT'])
@token_required
def update_expense(current_user, expense_id):
    try:
        data = request.get_json()
        
        # Check if expense exists and belongs to user
        expense = mongo.db.expenses.find_one({
            '_id': ObjectId(expense_id),
            'userId': current_user['_id']
        })
        
        if not expense:
            return jsonify({
                'success': False,
                'message': 'Expense not found'
            }), 404
        
        # Update fields
        update_data = {}
        if 'title' in data:
            update_data['title'] = data['title']
        if 'amount' in data:
            update_data['amount'] = float(data['amount'])
        if 'category' in data:
            update_data['category'] = data['category']
        if 'description' in data:
            update_data['description'] = data['description']
        if 'date' in data:
            update_data['date'] = datetime.fromisoformat(data['date'])
        if 'paymentMethod' in data:
            update_data['paymentMethod'] = data['paymentMethod']
        if 'tags' in data:
            update_data['tags'] = data['tags']
        
        update_data['updatedAt'] = datetime.utcnow()
        
        mongo.db.expenses.update_one(
            {'_id': ObjectId(expense_id)},
            {'$set': update_data}
        )
        
        return jsonify({
            'success': True,
            'message': 'Expense updated successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to update expense',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/tracking/expense/<expense_id>', methods=['DELETE'])
@token_required
def delete_expense(current_user, expense_id):
    try:
        # Check if expense exists and belongs to user
        expense = mongo.db.expenses.find_one({
            '_id': ObjectId(expense_id),
            'userId': current_user['_id']
        })
        
        if not expense:
            return jsonify({
                'success': False,
                'message': 'Expense not found'
            }), 404
        
        # Delete expense
        mongo.db.expenses.delete_one({'_id': ObjectId(expense_id)})
        
        return jsonify({
            'success': True,
            'message': 'Expense deleted successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to delete expense',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/tracking/statistics', methods=['GET'])
@token_required
def get_expense_statistics(current_user):
    try:
        # Get date range from query params
        months = int(request.args.get('months', 6))
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=months * 30)
        
        # Get expenses in date range
        expenses = list(mongo.db.expenses.find({
            'userId': current_user['_id'],
            'date': {'$gte': start_date, '$lte': end_date}
        }))
        
        # Calculate monthly statistics
        monthly_stats = {}
        for expense in expenses:
            month_key = expense['date'].strftime('%Y-%m')
            if month_key not in monthly_stats:
                monthly_stats[month_key] = {
                    'month': expense['date'].strftime('%B %Y'),
                    'totalAmount': 0,
                    'expenseCount': 0,
                    'averageAmount': 0
                }
            
            monthly_stats[month_key]['totalAmount'] += expense.get('amount', 0)
            monthly_stats[month_key]['expenseCount'] += 1
        
        # Calculate averages
        for stats in monthly_stats.values():
            if stats['expenseCount'] > 0:
                stats['averageAmount'] = stats['totalAmount'] / stats['expenseCount']
        
        # Category analysis
        category_stats = {}
        for expense in expenses:
            category = expense.get('category', 'Unknown')
            if category not in category_stats:
                category_stats[category] = {
                    'category': category,
                    'totalAmount': 0,
                    'expenseCount': 0,
                    'percentage': 0
                }
            
            category_stats[category]['totalAmount'] += expense.get('amount', 0)
            category_stats[category]['expenseCount'] += 1
        
        # Calculate percentages
        total_amount = sum(stats['totalAmount'] for stats in category_stats.values())
        for stats in category_stats.values():
            if total_amount > 0:
                stats['percentage'] = (stats['totalAmount'] / total_amount) * 100
        
        statistics_data = {
            'monthlyTrends': list(monthly_stats.values()),
            'categoryBreakdown': list(category_stats.values()),
            'summary': {
                'totalExpenses': len(expenses),
                'totalAmount': sum(e.get('amount', 0) for e in expenses),
                'averageExpense': sum(e.get('amount', 0) for e in expenses) / len(expenses) if expenses else 0,
                'topCategory': max(category_stats.values(), key=lambda x: x['totalAmount'])['category'] if category_stats else None
            }
        }
        
        return jsonify({
            'success': True,
            'data': statistics_data,
            'message': 'Expense statistics retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve expense statistics',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/tracking/summary', methods=['GET'])
@token_required
def get_expense_summary(current_user):
    try:
        # Get current month expenses
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month_end = (current_month_start + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        
        expenses = list(mongo.db.expenses.find({
            'userId': current_user['_id'],
            'date': {'$gte': current_month_start, '$lte': current_month_end}
        }))
        
        # Calculate summary
        total_amount = sum(e.get('amount', 0) for e in expenses)
        expense_count = len(expenses)
        
        # Category breakdown
        categories = {}
        for expense in expenses:
            category = expense.get('category', 'Unknown')
            if category not in categories:
                categories[category] = {'amount': 0, 'count': 0}
            categories[category]['amount'] += expense.get('amount', 0)
            categories[category]['count'] += 1
        
        # Recent expenses
        recent_expenses = list(mongo.db.expenses.find({
            'userId': current_user['_id']
        }).sort('date', -1).limit(10))
        
        recent_expense_list = []
        for expense in recent_expenses:
            expense_data = serialize_doc(expense)
            expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            recent_expense_list.append(expense_data)
        
        summary_data = {
            'currentMonth': {
                'totalAmount': total_amount,
                'expenseCount': expense_count,
                'averageAmount': total_amount / expense_count if expense_count > 0 else 0,
                'dailyAverage': total_amount / datetime.utcnow().day if datetime.utcnow().day > 0 else 0
            },
            'categoryBreakdown': [
                {
                    'category': cat,
                    'amount': data['amount'],
                    'count': data['count'],
                    'percentage': (data['amount'] / total_amount * 100) if total_amount > 0 else 0
                }
                for cat, data in categories.items()
            ],
            'recentExpenses': recent_expense_list
        }
        
        return jsonify({
            'success': True,
            'data': summary_data,
            'message': 'Expense summary retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve expense summary',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/tracking/history/<expense_type>', methods=['GET'])
@token_required
def get_expense_history(current_user, expense_type):
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        
        # Build query based on type
        query = {'userId': current_user['_id']}
        
        if expense_type == 'recent':
            # Get recent expenses (last 30 days)
            query['date'] = {'$gte': datetime.utcnow() - timedelta(days=30)}
        elif expense_type == 'monthly':
            # Get current month expenses
            current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            query['date'] = {'$gte': current_month_start}
        elif expense_type == 'category':
            category = request.args.get('category')
            if category:
                query['category'] = category
        
        # Get expenses with pagination
        skip = (page - 1) * limit
        expenses = list(mongo.db.expenses.find(query).sort('date', -1).skip(skip).limit(limit))
        total = mongo.db.expenses.count_documents(query)
        
        # Serialize expenses
        expense_list = []
        for expense in expenses:
            expense_data = serialize_doc(expense)
            expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            expense_list.append(expense_data)
        
        return jsonify({
            'success': True,
            'data': {
                'expenses': expense_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                },
                'type': expense_type
            },
            'message': f'{expense_type.title()} expense history retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve expense history',
            'errors': {'general': [str(e)]}
        }), 500 
        
# CREDITS MANAGEMENT ENDPOINTS #

@app.route('/credits/balance', methods=['GET'])
@token_required
def get_credit_balance(current_user):
    try:
        balance = current_user.get('ficoreCreditBalance', 0.0)
        
        # Get recent transactions
        recent_transactions = list(mongo.db.credit_transactions.find({
            'userId': current_user['_id']
        }).sort('createdAt', -1).limit(5))
        
        transaction_list = []
        for transaction in recent_transactions:
            transaction_data = serialize_doc(transaction)
            transaction_data['createdAt'] = transaction_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            transaction_list.append(transaction_data)
        
        return jsonify({
            'success': True,
            'data': {
                'balance': balance,
                'currency': 'NGN',
                'recentTransactions': transaction_list,
                'lastUpdated': datetime.utcnow().isoformat() + 'Z'
            },
            'message': 'Credit balance retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve credit balance',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/credits/history', methods=['GET'])
@token_required
def get_credit_history(current_user):
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        transaction_type = request.args.get('type')  # 'credit', 'debit', 'all'
        
        # Build query
        query = {'userId': current_user['_id']}
        if transaction_type and transaction_type != 'all':
            query['type'] = transaction_type
        
        # Get transactions with pagination
        skip = (page - 1) * limit
        transactions = list(mongo.db.credit_transactions.find(query).sort('createdAt', -1).skip(skip).limit(limit))
        total = mongo.db.credit_transactions.count_documents(query)
        
        # Serialize transactions
        transaction_list = []
        for transaction in transactions:
            transaction_data = serialize_doc(transaction)
            transaction_data['createdAt'] = transaction_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            transaction_list.append(transaction_data)
        
        return jsonify({
            'success': True,
            'data': {
                'transactions': transaction_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                }
            },
            'message': 'Credit history retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve credit history',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/credits/request', methods=['POST'])
@token_required
def create_credit_request(current_user):
    try:
        data = request.get_json()
        
        # Validation
        errors = {}
        if not data.get('amount') or data.get('amount', 0) <= 0:
            errors['amount'] = ['Valid amount is required']
        if not data.get('paymentMethod'):
            errors['paymentMethod'] = ['Payment method is required']
        if not data.get('paymentReference'):
            errors['paymentReference'] = ['Payment reference is required']
        
        if errors:
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': errors
            }), 400
        
        request_data = {
            'userId': current_user['_id'],
            'amount': float(data['amount']),
            'paymentMethod': data['paymentMethod'],
            'paymentReference': data['paymentReference'],
            'receiptUrl': data.get('receiptUrl', ''),
            'notes': data.get('notes', ''),
            'status': 'pending',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        result = mongo.db.credit_requests.insert_one(request_data)
        request_id = str(result.inserted_id)
        
        return jsonify({
            'success': True,
            'data': {
                'id': request_id,
                'amount': request_data['amount'],
                'paymentMethod': request_data['paymentMethod'],
                'status': request_data['status'],
                'createdAt': request_data['createdAt'].isoformat() + 'Z'
            },
            'message': 'Credit request submitted successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to create credit request',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/credits/request/<request_id>', methods=['PUT'])
@token_required
def update_credit_request(current_user, request_id):
    try:
        data = request.get_json()
        
        # Check if request exists and belongs to user
        credit_request = mongo.db.credit_requests.find_one({
            '_id': ObjectId(request_id),
            'userId': current_user['_id']
        })
        
        if not credit_request:
            return jsonify({
                'success': False,
                'message': 'Credit request not found'
            }), 404
        
        # Only allow updates if status is pending
        if credit_request.get('status') != 'pending':
            return jsonify({
                'success': False,
                'message': 'Cannot update processed credit request'
            }), 400
        
        # Update fields
        update_data = {}
        if 'amount' in data:
            update_data['amount'] = float(data['amount'])
        if 'paymentMethod' in data:
            update_data['paymentMethod'] = data['paymentMethod']
        if 'paymentReference' in data:
            update_data['paymentReference'] = data['paymentReference']
        if 'receiptUrl' in data:
            update_data['receiptUrl'] = data['receiptUrl']
        if 'notes' in data:
            update_data['notes'] = data['notes']
        
        update_data['updatedAt'] = datetime.utcnow()
        
        mongo.db.credit_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': update_data}
        )
        
        return jsonify({
            'success': True,
            'message': 'Credit request updated successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to update credit request',
            'errors': {'general': [str(e)]}
        }), 500

# FILE UPLOAD ENDPOINTS #

@app.route('/upload/profile-picture', methods=['POST'])
@token_required
def upload_profile_picture(current_user):
    try:
        # In a real implementation, you would handle file upload here
        # For now, we'll just return a mock response
        
        return jsonify({
            'success': True,
            'data': {
                'url': 'https://example.com/profile-pictures/user-' + str(current_user['_id']) + '.jpg',
                'filename': 'profile-picture.jpg'
            },
            'message': 'Profile picture uploaded successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to upload profile picture',
            'errors': {'general': [str(e)]}
        }), 500

# ADMIN ENDPOINTS (for admin users only) #

@app.route('/admin/users', methods=['GET'])
@token_required
@admin_required
def get_all_users(current_user):
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        
        skip = (page - 1) * limit
        users = list(mongo.db.users.find({
            'isActive': True
        }).skip(skip).limit(limit))
        total = mongo.db.users.count_documents({'isActive': True})
        
        user_list = []
        for user in users:
            user_data = serialize_doc(user)
            # Remove sensitive data
            user_data.pop('password', None)
            user_data['createdAt'] = user_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            user_list.append(user_data)
        
        return jsonify({
            'success': True,
            'data': {
                'users': user_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
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

@app.route('/admin/credit-requests', methods=['GET'])
@token_required
@admin_required
def get_credit_requests(current_user):
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        status = request.args.get('status', 'pending')
        
        query = {}
        if status != 'all':
            query['status'] = status
        
        skip = (page - 1) * limit
        requests = list(mongo.db.credit_requests.find(query).sort('createdAt', -1).skip(skip).limit(limit))
        total = mongo.db.credit_requests.count_documents(query)
        
        request_list = []
        for req in requests:
            request_data = serialize_doc(req)
            request_data['createdAt'] = request_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            request_data['updatedAt'] = request_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            
            # Get user info
            user = mongo.db.users.find_one({'_id': req['userId']})
            if user:
                request_data['user'] = {
                    'id': str(user['_id']),
                    'email': user['email'],
                    'displayName': user.get('displayName', '')
                }
            
            request_list.append(request_data)
        
        return jsonify({
            'success': True,
            'data': {
                'requests': request_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                }
            },
            'message': 'Credit requests retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve credit requests',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/admin/credit-requests/<request_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_credit_request(current_user, request_id):
    try:
        data = request.get_json()
        
        # Get the credit request
        credit_request = mongo.db.credit_requests.find_one({'_id': ObjectId(request_id)})
        if not credit_request:
            return jsonify({
                'success': False,
                'message': 'Credit request not found'
            }), 404
        
        if credit_request.get('status') != 'pending':
            return jsonify({
                'success': False,
                'message': 'Credit request already processed'
            }), 400
        
        # Update request status
        mongo.db.credit_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'approved',
                'approvedBy': current_user['_id'],
                'approvedAt': datetime.utcnow(),
                'adminNotes': data.get('notes', ''),
                'updatedAt': datetime.utcnow()
            }}
        )
        
        # Add credits to user account
        mongo.db.users.update_one(
            {'_id': credit_request['userId']},
            {'$inc': {'ficoreCreditBalance': credit_request['amount']}}
        )
        
        # Create credit transaction record
        transaction_data = {
            'userId': credit_request['userId'],
            'type': 'credit',
            'amount': credit_request['amount'],
            'description': f"Credit top-up approved - {credit_request['paymentMethod']}",
            'reference': credit_request['paymentReference'],
            'requestId': ObjectId(request_id),
            'approvedBy': current_user['_id'],
            'createdAt': datetime.utcnow()
        }
        mongo.db.credit_transactions.insert_one(transaction_data)
        
        return jsonify({
            'success': True,
            'message': 'Credit request approved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to approve credit request',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/admin/credit-requests/<request_id>/deny', methods=['POST'])
@token_required
@admin_required
def deny_credit_request(current_user, request_id):
    try:
        data = request.get_json()
        
        # Get the credit request
        credit_request = mongo.db.credit_requests.find_one({'_id': ObjectId(request_id)})
        if not credit_request:
            return jsonify({
                'success': False,
                'message': 'Credit request not found'
            }), 404
        
        if credit_request.get('status') != 'pending':
            return jsonify({
                'success': False,
                'message': 'Credit request already processed'
            }), 400
        
        # Update request status
        mongo.db.credit_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'denied',
                'deniedBy': current_user['_id'],
                'deniedAt': datetime.utcnow(),
                'adminNotes': data.get('notes', ''),
                'updatedAt': datetime.utcnow()
            }}
        )
        
        return jsonify({
            'success': True,
            'message': 'Credit request denied successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to deny credit request',
            'errors': {'general': [str(e)]}
        }), 500


# HEALTH CHECK AND ROOT ENDPOINTS# 

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        'success': True,
        'message': 'Ficore Budget Mobile API is running',
        'version': '1.0.0',
        'endpoints': {
            'authentication': '/auth/*',
            'users': '/users/*',
            'budgets': '/budget/*',
            'expenses': '/tracking/*',
            'credits': '/credits/*',
            'uploads': '/upload/*',
            'admin': '/admin/*'
        }
    })

@app.route('/health', methods=['GET'])
def health_check():
    try:
        # Test database connection
        mongo.db.users.find_one()
        
        return jsonify({
            'success': True,
            'message': 'API is healthy',
            'database': 'connected',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'API health check failed',
            'database': 'disconnected',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'message': 'Endpoint not found',
        'errors': {'general': ['The requested endpoint does not exist']}
    }), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        'success': False,
        'message': 'Method not allowed',
        'errors': {'general': ['The HTTP method is not allowed for this endpoint']}
    }), 405

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'message': 'Internal server error',
        'errors': {'general': ['An unexpected error occurred']}

    }), 500
