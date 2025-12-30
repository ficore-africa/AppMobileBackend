from flask import Flask, request, jsonify, Response, redirect, url_for, send_from_directory, g
from flask_cors import CORS
from flask_pymongo import PyMongo
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime, timedelta
import jwt
import os
from bson import ObjectId
from functools import wraps
from werkzeug.security import generate_password_hash

# Import blueprints
from blueprints.auth import auth_bp, init_auth_blueprint
from blueprints.users import users_bp, init_users_blueprint
from blueprints.income import init_income_blueprint
from blueprints.expenses import expenses_bp, init_expenses_blueprint
from blueprints.financial_aggregation import init_financial_aggregation_blueprint
from blueprints.attachments import init_attachments_blueprint

from blueprints.credits import init_credits_blueprint
from blueprints.summaries import init_summaries_blueprint
from blueprints.admin import init_admin_blueprint
from blueprints.tax import init_tax_blueprint
from blueprints.debtors import init_debtors_blueprint
from blueprints.creditors import init_creditors_blueprint
from blueprints.inventory import init_inventory_blueprint
from blueprints.assets import init_assets_blueprint
from blueprints.dashboard import init_dashboard_blueprint
from blueprints.rewards import init_rewards_blueprint
from blueprints.subscription import init_subscription_blueprint
from blueprints.subscription_discounts import init_subscription_discounts_blueprint
from blueprints.reminders import init_reminders_blueprint
from blueprints.analytics import init_analytics_blueprint
from blueprints.rate_limit_monitoring import init_rate_limit_monitoring_blueprint
from blueprints.admin_subscription_management import init_admin_subscription_management_blueprint
from blueprints.atomic_entries import init_atomic_entries_blueprint
from blueprints.reports import init_reports_blueprint
from blueprints.voice_reporting import init_voice_reporting_blueprint

# Import database models
from models import DatabaseInitializer

# Import rate limit tracking utilities
from utils.rate_limit_tracker import RateLimitTracker
from utils.api_logging_middleware import setup_api_logging

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ficore-mobile-secret-key-2025')
app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
app.config['JWT_EXPIRATION_DELTA'] = timedelta(hours=24)

# Initialize extensions
CORS(app, origins=['*'])
mongo = PyMongo(app)

# Initialize rate limiter with more reasonable limits
# CRITICAL FIX: Increased limits to prevent legitimate usage from being blocked
# Mobile apps make frequent API calls, especially for status checks
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["50000 per day", "5000 per hour"],  # Increased from 1000/200
    storage_uri="memory://",
)

# Initialize admin user on startup
def initialize_admin_user():
    """Create admin user if it doesn't exist - safe for deployment"""
    try:
        admin_email = "admin@ficore.com"
        
        # Check if admin already exists
        existing_admin = mongo.db.users.find_one({"email": admin_email})
        if existing_admin:
            # Ensure existing user has admin role
            if existing_admin.get('role') != 'admin':
                mongo.db.users.update_one(
                    {"_id": existing_admin['_id']},
                    {"$set": {"role": "admin", "updatedAt": datetime.utcnow()}}
                )
                print(f"✅ Updated existing user {admin_email} to admin role")
            else:
                print(f"✅ Admin user {admin_email} already exists")
            return existing_admin['_id']
        
        # Create new admin user
        admin_user = {
            "_id": ObjectId(),
            "email": admin_email,
            "password": generate_password_hash("admin123"),
            "firstName": "System",
            "lastName": "Administrator",
            "displayName": "System Administrator",
            "role": "admin",
            "ficoreCreditBalance": 0.0,
            "setupComplete": True,
            "isActive": True,
            "language": "en",
            "currency": "NGN",
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
            "settings": {
                "notifications": {
                    "push": True,
                    "email": True,
                    "expenseAlerts": True
                },
                "privacy": {
                    "profileVisibility": "private",
                    "dataSharing": False
                },
                "preferences": {
                    "currency": "NGN",
                    "language": "en",
                    "theme": "light",
                    "dateFormat": "DD/MM/YYYY"
                }
            }
        }
        
        result = mongo.db.users.insert_one(admin_user)
        print(f"✅ Created admin user: {admin_email} (ID: {result.inserted_id})")
        return result.inserted_id
        
    except Exception as e:
        print(f"⚠️  Admin initialization error: {str(e)}")
        return None

# Initialize database and admin on app startup
with app.app_context():
    # Initialize database collections and indexes
    print("\n" + "="*60)
    print("Initializing FiCore Mobile Database...")
    print("="*60)
    db_initializer = DatabaseInitializer(mongo.db)
    db_results = db_initializer.initialize_collections()
    
    if db_results['created']:
        print(f"✅ Created {len(db_results['created'])} new collections")
    if db_results['existing']:
        print(f"✅ Verified {len(db_results['existing'])} existing collections")
    if db_results['errors']:
        print(f"⚠️  {len(db_results['errors'])} errors during initialization")
    print("="*60 + "\n")
    
    # Initialize admin user
    initialize_admin_user()

# Helper function to convert ObjectId to string
def serialize_doc(doc):
    if not doc:
        return doc
    
    # Make a copy to avoid modifying the original
    if isinstance(doc, dict):
        doc = doc.copy()
    
    # Handle _id field
    if '_id' in doc:
        doc['id'] = str(doc['_id'])
        del doc['_id']
    
    # Handle other ObjectId fields recursively
    for key, value in list(doc.items()):  # Use list() to avoid dict changed size during iteration
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        elif isinstance(value, list):
            # Handle lists that might contain ObjectIds or nested documents
            new_list = []
            for item in value:
                if isinstance(item, ObjectId):
                    new_list.append(str(item))
                elif isinstance(item, dict):
                    new_list.append(serialize_doc(item))
                else:
                    new_list.append(item)
            doc[key] = new_list
        elif isinstance(value, dict):
            # Recursively handle nested documents
            doc[key] = serialize_doc(value)
    
    # Final check for any remaining ObjectIds (debugging)
    def check_for_objectids(obj, path=""):
        if isinstance(obj, ObjectId):
            print(f"WARNING: ObjectId found at path '{path}': {obj}")
            return str(obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = check_for_objectids(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                obj[i] = check_for_objectids(item, f"{path}[{i}]")
        return obj
    
    doc = check_for_objectids(doc)
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
            
            # Validate user_id exists in token
            if 'user_id' not in data:
                return jsonify({'success': False, 'message': 'Invalid token format'}), 401
            
            # Find user with error handling
            try:
                current_user = mongo.db.users.find_one({'_id': ObjectId(data['user_id'])})
                if not current_user:
                    return jsonify({'success': False, 'message': 'User not found'}), 401
            except Exception as db_error:
                print(f"Database error in token validation: {str(db_error)}")
                return jsonify({'success': False, 'message': 'Database connection error'}), 500
            
            # Store user ID in g for API logging middleware
            g.current_user_id = current_user['_id']
                
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        except Exception as e:
            print(f"Unexpected error in token validation: {str(e)}")
            return jsonify({'success': False, 'message': 'Authentication error'}), 500
        
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

# Make limiter available to the app
app.limiter = limiter

# Initialize and register blueprints
auth_blueprint = init_auth_blueprint(mongo, app.config)
users_blueprint = init_users_blueprint(mongo, token_required)
income_blueprint = init_income_blueprint(mongo, token_required, serialize_doc)
expenses_blueprint = init_expenses_blueprint(mongo, token_required, serialize_doc)
financial_aggregation_blueprint = init_financial_aggregation_blueprint(mongo, token_required, serialize_doc)
attachments_blueprint = init_attachments_blueprint(mongo, token_required, serialize_doc)

credits_blueprint = init_credits_blueprint(mongo, token_required, serialize_doc)
summaries_blueprint = init_summaries_blueprint(mongo, token_required, serialize_doc)
admin_blueprint = init_admin_blueprint(mongo, token_required, admin_required, serialize_doc)
tax_blueprint = init_tax_blueprint(mongo, token_required, serialize_doc)
debtors_blueprint = init_debtors_blueprint(mongo, token_required, serialize_doc)
creditors_blueprint = init_creditors_blueprint(mongo, token_required, serialize_doc)
inventory_blueprint = init_inventory_blueprint(mongo, token_required, serialize_doc)
assets_blueprint = init_assets_blueprint(mongo, token_required, serialize_doc)
dashboard_blueprint = init_dashboard_blueprint(mongo, token_required, serialize_doc)
rewards_blueprint = init_rewards_blueprint(mongo, token_required, serialize_doc)
subscription_blueprint = init_subscription_blueprint(mongo, token_required, serialize_doc)
subscription_discounts_blueprint = init_subscription_discounts_blueprint(mongo, token_required, serialize_doc)
reminders_blueprint = init_reminders_blueprint(mongo, token_required, serialize_doc)
analytics_blueprint = init_analytics_blueprint(mongo, token_required, admin_required, serialize_doc)
admin_subscription_management_blueprint = init_admin_subscription_management_blueprint(mongo, token_required, admin_required, serialize_doc)

# CRITICAL: Initialize atomic entries blueprint for FC charging fix
atomic_entries_blueprint = init_atomic_entries_blueprint(mongo, token_required, serialize_doc)

# Initialize reports blueprint for centralized export functionality
reports_blueprint = init_reports_blueprint(mongo, token_required)
voice_reporting_blueprint = init_voice_reporting_blueprint(mongo, token_required, serialize_doc)

# Initialize rate limit tracker
rate_limit_tracker = RateLimitTracker(mongo)
rate_limit_monitoring_blueprint = init_rate_limit_monitoring_blueprint(mongo, token_required, admin_required, rate_limit_tracker)

# Setup API logging middleware
setup_api_logging(app, rate_limit_tracker)

app.register_blueprint(auth_blueprint)
app.register_blueprint(users_blueprint)
app.register_blueprint(income_blueprint)
app.register_blueprint(expenses_blueprint)
app.register_blueprint(financial_aggregation_blueprint)
app.register_blueprint(attachments_blueprint)

app.register_blueprint(credits_blueprint)
app.register_blueprint(summaries_blueprint)
app.register_blueprint(admin_blueprint)
app.register_blueprint(tax_blueprint)
app.register_blueprint(debtors_blueprint)
app.register_blueprint(creditors_blueprint)
app.register_blueprint(inventory_blueprint)
app.register_blueprint(assets_blueprint)
app.register_blueprint(dashboard_blueprint)
app.register_blueprint(rewards_blueprint)
app.register_blueprint(subscription_blueprint)
app.register_blueprint(subscription_discounts_blueprint)
app.register_blueprint(reminders_blueprint)
app.register_blueprint(analytics_blueprint)
app.register_blueprint(admin_subscription_management_blueprint)
app.register_blueprint(rate_limit_monitoring_blueprint)

# CRITICAL: Register atomic entries blueprint for FC charging fix
app.register_blueprint(atomic_entries_blueprint)
print("✓ Atomic entries blueprint registered at /atomic")

# Register reports blueprint for centralized export functionality
app.register_blueprint(reports_blueprint)
print("✓ Reports blueprint registered at /api/reports")
app.register_blueprint(voice_reporting_blueprint)
print("✓ Voice reporting blueprint registered at /api/voice")

# Root redirect to admin login
@app.route('/')
def index():
    """Redirect root URL to admin login page"""
    return redirect('/admin/admin_login.html')

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'success': True,
        'message': 'FiCore Mobile Backend is running',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'version': '1.0.0'
    })

# GCS health check endpoint
@app.route('/health/gcs', methods=['GET'])
def gcs_health_check():
    """Check if Google Cloud Storage is accessible"""
    try:
        from google.cloud import storage
        
        storage_client = storage.Client()
        bucket_name = os.environ.get('GCS_BUCKET_NAME', 'ficore-attachments')
        bucket = storage_client.bucket(bucket_name)
        
        # Test if bucket exists and is accessible
        exists = bucket.exists()
        
        if exists:
            return jsonify({
                'success': True,
                'message': 'GCS is accessible',
                'bucket': bucket_name,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'GCS bucket not found',
                'bucket': bucket_name,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'GCS error: {str(e)}',
            'bucket': os.environ.get('GCS_BUCKET_NAME', 'ficore-attachments'),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

# Profile picture upload endpoint
@app.route('/upload/profile-picture', methods=['POST'])
@token_required
def upload_profile_picture(current_user):
    """Upload profile picture with GCS primary and GridFS fallback"""
    try:
        from werkzeug.utils import secure_filename
        import uuid
        import base64
        
        # Check if file is in request
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'No file provided'
            }), 400
        
        file = request.files['file']
        
        # Check if file has a filename
        if file.filename == '':
            return jsonify({
                'success': False,
                'message': 'No file selected'
            }), 400
        
        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        if file_ext not in allowed_extensions:
            return jsonify({
                'success': False,
                'message': f'Invalid file type. Allowed types: {", ".join(allowed_extensions)}'
            }), 400
        
        # Read file data once
        file.seek(0)
        file_data = file.read()
        content_type = file.content_type or f'image/{file_ext}'
        
        user_id = str(current_user['_id'])
        unique_id = str(uuid.uuid4())
        
        # Try GCS first
        gcs_success = False
        signed_url = None
        gcs_filename = None
        
        try:
            from google.cloud import storage
            from datetime import timedelta
            from io import BytesIO
            
            storage_client = storage.Client()
            bucket_name = os.environ.get('GCS_BUCKET_NAME', 'ficore-attachments')
            bucket = storage_client.bucket(bucket_name)
            
            if bucket.exists():
                gcs_filename = f"profile_pictures/{user_id}/{unique_id}.{file_ext}"
                blob = bucket.blob(gcs_filename)
                blob.upload_from_file(BytesIO(file_data), content_type=content_type)
                
                # Generate signed URL
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(days=7),
                    method="GET"
                )
                
                gcs_success = True
                print(f"✅ Profile picture uploaded to GCS: {gcs_filename}")
            else:
                print(f"⚠️ GCS bucket does not exist: {bucket_name}, falling back to GridFS")
        except Exception as e:
            print(f"⚠️ GCS upload failed: {e}, falling back to GridFS")
        
        # Fallback to GridFS if GCS failed
        if not gcs_success:
            try:
                import gridfs
                fs = gridfs.GridFS(mongo.db)
                
                # Store in GridFS
                gridfs_id = fs.put(
                    file_data,
                    filename=f"profile_{user_id}_{unique_id}.{file_ext}",
                    content_type=content_type,
                    user_id=user_id
                )
                
                # Create data URL for immediate display (fallback)
                base64_data = base64.b64encode(file_data).decode('utf-8')
                data_url = f"data:{content_type};base64,{base64_data}"
                
                # CRITICAL FIX: Generate absolute GridFS URL for persistent access
                base_url = os.environ.get('API_BASE_URL', 'https://mobilebackend.ficoreafrica.com')
                gridfs_url = f"{base_url}/api/users/profile-picture/{str(gridfs_id)}"
                
                # Update user with GridFS reference
                mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {
                        '$set': {
                            'gridfsProfilePictureId': str(gridfs_id),
                            'gcsProfilePicturePath': None,
                            'profilePictureUrl': None,
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                
                print(f"✅ Profile picture stored in GridFS: {gridfs_id}")
                print(f"✅ GridFS URL: {gridfs_url}")
                
                return jsonify({
                    'success': True,
                    'data': {
                        'image_url': gridfs_url,  # Use persistent GridFS URL
                        'url': gridfs_url,
                        'data_url': data_url,  # Include data URL as fallback
                        'storage': 'gridfs',
                        'gridfs_id': str(gridfs_id)
                    },
                    'message': 'Profile picture uploaded successfully'
                }), 200
                
            except Exception as gridfs_error:
                print(f"❌ GridFS fallback failed: {gridfs_error}")
                import traceback
                traceback.print_exc()
                return jsonify({
                    'success': False,
                    'message': 'Failed to upload image',
                    'errors': {'general': [str(gridfs_error)]}
                }), 500
        
        # GCS succeeded - update user document
        try:
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {
                    '$set': {
                        'gcsProfilePicturePath': gcs_filename,
                        'gridfsProfilePictureId': None,
                        'profilePictureUrl': None,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            print(f"✅ Saved GCS path to user document: {gcs_filename}")
        except Exception as e:
            print(f"⚠️ Error updating user document: {e}")
        
        return jsonify({
            'success': True,
            'data': {
                'image_url': signed_url,
                'url': signed_url,
                'storage': 'gcs',
                'gcs_path': gcs_filename
            },
            'message': 'Profile picture uploaded successfully'
        }), 200
        
    except Exception as e:
        print(f"❌ Error uploading profile picture: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Failed to upload profile picture',
            'errors': {'general': [str(e)]}
        }), 500

@app.route('/admin')
def admin_redirect():
    """Redirect /admin to admin login page"""
    return redirect('/admin/admin_login.html')

@app.route('/admin/<path:filename>')
def serve_admin_static(filename):
    """Serve static files for the admin interface"""
    try:
        admin_static_path = os.path.join(os.path.dirname(__file__), 'admin_web_app')
        return send_from_directory(admin_static_path, filename)
    except FileNotFoundError:
        return jsonify({
            'success': False,
            'message': f'Static file {filename} not found'
        }), 404

@app.route('/uploads/<path:filename>')
def serve_uploaded_file(filename):
    """Serve uploaded files (receipts, documents, profile pictures, etc.)"""
    try:
        uploads_path = os.path.join(os.path.dirname(__file__), 'uploads')
        
        # Handle subdirectories (e.g., profile_pictures/image.jpg)
        if '/' in filename:
            # Split into directory and filename
            parts = filename.split('/')
            subdir = parts[0]
            file_name = '/'.join(parts[1:])
            full_path = os.path.join(uploads_path, subdir)
            
            # Check if file exists
            file_path = os.path.join(full_path, file_name)
            if not os.path.exists(file_path):
                print(f"Error serving file {filename}: 404 Not Found: File does not exist at {file_path}")
                return jsonify({
                    'success': False,
                    'message': f'File not found'
                }), 404
                
            return send_from_directory(full_path, file_name)
        else:
            file_path = os.path.join(uploads_path, filename)
            if not os.path.exists(file_path):
                print(f"Error serving file {filename}: 404 Not Found: File does not exist at {file_path}")
                return jsonify({
                    'success': False,
                    'message': f'File not found'
                }), 404
            return send_from_directory(uploads_path, filename)
            
    except FileNotFoundError as e:
        print(f"Error serving file {filename}: 404 Not Found: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'File not found'
        }), 404
    except Exception as e:
        print(f"Error serving file {filename}: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Failed to serve file',
            'error': str(e)
        }), 500

@app.route('/favicon.ico')
def favicon():
    """Serve favicon"""
    try:
        return send_from_directory(os.path.join(os.path.dirname(__file__), 'admin_web_app'), 'favicon.png')
    except FileNotFoundError:
        return jsonify({
            'success': False,
            'message': 'Favicon not found'
        }), 404

# Dashboard endpoint that combines data from all modules
@app.route('/dashboard', methods=['GET'])
@token_required
def get_dashboard(current_user):
    try:
        # Get current month data
        now = datetime.utcnow()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Get income data
        incomes = list(mongo.db.incomes.find({'userId': current_user['_id']}))
        total_income_this_month = sum(inc['amount'] for inc in incomes if inc['dateReceived'] >= start_of_month)
        
        # Get expense data
        expenses = list(mongo.db.expenses.find({'userId': current_user['_id']}))
        total_expenses_this_month = sum(exp['amount'] for exp in expenses if exp['date'] >= start_of_month)
        
        # Calculate financial health metrics
        net_income = total_income_this_month - total_expenses_this_month
        savings_rate = (net_income / total_income_this_month * 100) if total_income_this_month > 0 else 0
        
        # Recent transactions (combined income and expenses)
        recent_incomes = sorted(incomes, key=lambda x: x['dateReceived'], reverse=True)[:3]
        recent_expenses = sorted(expenses, key=lambda x: x['date'], reverse=True)[:3]
        
        # Serialize recent transactions
        recent_income_data = []
        for income in recent_incomes:
            income_data = serialize_doc(income.copy())
            income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
            income_data['type'] = 'income'
            recent_income_data.append(income_data)
        
        recent_expense_data = []
        for expense in recent_expenses:
            expense_data = serialize_doc(expense.copy())
            expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            expense_data['type'] = 'expense'
            recent_expense_data.append(expense_data)
        
        # Category breakdown for expenses
        expense_categories = {}
        for expense in expenses:
            if expense['date'] >= start_of_month:
                category = expense['category']
                expense_categories[category] = expense_categories.get(category, 0) + expense['amount']
        
        # Income sources breakdown
        income_sources = {}
        for income in incomes:
            if income['dateReceived'] >= start_of_month:
                source = income['source']
                income_sources[source] = income_sources.get(source, 0) + income['amount']
        
        dashboard_data = {
            'financialSummary': {
                'totalIncome': total_income_this_month,
                'totalExpenses': total_expenses_this_month,
                'netIncome': net_income,
                'savingsRate': savings_rate
            },
            'recentTransactions': {
                'incomes': recent_income_data,
                'expenses': recent_expense_data
            },
            'categoryBreakdown': {
                'expenses': expense_categories,
                'incomeSources': income_sources
            },
            'insights': {
                'topExpenseCategory': max(expense_categories.items(), key=lambda x: x[1])[0] if expense_categories else 'None',
                'topIncomeSource': max(income_sources.items(), key=lambda x: x[1])[0] if income_sources else 'None',
                'monthlyGrowth': 0  # Placeholder for month-over-month growth
            }
        }
        
        return jsonify({
            'success': True,
            'data': dashboard_data,
            'message': 'Dashboard data retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve dashboard data',
            'errors': {'general': [str(e)]}
        }), 500

# Analytics endpoint
@app.route('/analytics', methods=['GET'])
@token_required
def get_analytics(current_user):
    try:
        period = request.args.get('period', 'monthly')  # monthly, yearly
        
        # Get all user data
        incomes = list(mongo.db.incomes.find({'userId': current_user['_id']}))
        expenses = list(mongo.db.expenses.find({'userId': current_user['_id']}))
        
        # Calculate trends over time
        now = datetime.utcnow()
        trends = []
        
        for i in range(12):  # Last 12 months
            month_start = (now - timedelta(days=30*i)).replace(day=1)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            
            month_incomes = [inc for inc in incomes if month_start <= inc['dateReceived'] <= month_end]
            month_expenses = [exp for exp in expenses if month_start <= exp['date'] <= month_end]
            
            trends.append({
                'month': month_start.strftime('%Y-%m'),
                'income': sum(inc['amount'] for inc in month_incomes),
                'expenses': sum(exp['amount'] for exp in month_expenses),
                'net': sum(inc['amount'] for inc in month_incomes) - sum(exp['amount'] for exp in month_expenses)
            })
        
        # Financial ratios and metrics
        total_income = sum(inc['amount'] for inc in incomes)
        total_expenses = sum(exp['amount'] for exp in expenses)
        
        analytics_data = {
            'trends': trends,
            'totals': {
                'income': total_income,
                'expenses': total_expenses,
                'net': total_income - total_expenses
            },
            'ratios': {
                'savingsRate': ((total_income - total_expenses) / total_income * 100) if total_income > 0 else 0,
                'expenseRatio': (total_expenses / total_income * 100) if total_income > 0 else 0
            },
            'counts': {
                'incomes': len(incomes),
                'expenses': len(expenses)
            }
        }
        
        return jsonify({
            'success': True,
            'data': analytics_data,
            'message': 'Analytics data retrieved successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve analytics data',
            'errors': {'general': [str(e)]}
        }), 500

# Analytics overview endpoint
@app.route('/analytics/overview', methods=['GET'])
@token_required
def get_analytics_overview(current_user):
    """Get analytics overview - summary of key business metrics"""
    try:
        user_id = current_user['_id']
        
        # Get current month data
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Get financial data
        incomes = list(mongo.db.incomes.find({'userId': user_id}))
        expenses = list(mongo.db.expenses.find({'userId': user_id}))
        
        # Current month data
        current_month_incomes = [inc for inc in incomes if inc['dateReceived'] >= month_start]
        current_month_expenses = [exp for exp in expenses if exp['date'] >= month_start]
        
        current_month_income_total = sum(inc['amount'] for inc in current_month_incomes)
        current_month_expense_total = sum(exp['amount'] for exp in current_month_expenses)
        
        # All time data
        total_income = sum(inc['amount'] for inc in incomes)
        total_expenses = sum(exp['amount'] for exp in expenses)
        
        # Business suite data (if available)
        debtors_count = mongo.db.debtors.count_documents({'userId': user_id})
        creditors_count = mongo.db.creditors.count_documents({'userId': user_id})
        inventory_count = mongo.db.inventory_items.count_documents({'userId': user_id})
        
        # Calculate key metrics
        net_income = total_income - total_expenses
        monthly_net = current_month_income_total - current_month_expense_total
        savings_rate = (net_income / total_income * 100) if total_income > 0 else 0
        
        overview_data = {
            'currentMonth': {
                'income': current_month_income_total,
                'expenses': current_month_expense_total,
                'net': monthly_net,
                'transactionCount': len(current_month_incomes) + len(current_month_expenses)
            },
            'allTime': {
                'income': total_income,
                'expenses': total_expenses,
                'net': net_income,
                'transactionCount': len(incomes) + len(expenses)
            },
            'businessSuite': {
                'debtorsCount': debtors_count,
                'creditorsCount': creditors_count,
                'inventoryCount': inventory_count
            },
            'keyMetrics': {
                'savingsRate': round(savings_rate, 2),
                'expenseRatio': round((total_expenses / total_income * 100), 2) if total_income > 0 else 0,
                'averageMonthlyIncome': round(total_income / 12, 2) if total_income > 0 else 0,
                'averageMonthlyExpense': round(total_expenses / 12, 2) if total_expenses > 0 else 0
            }
        }
        
        return jsonify({
            'success': True,
            'data': overview_data,
            'message': 'Analytics overview retrieved successfully'
        }), 200
        
    except Exception as e:
        print(f"Error getting analytics overview: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve analytics overview',
            'error': str(e)
        }), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'message': 'Endpoint not found',
        'error': 'The requested resource was not found on this server.'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'message': 'Internal server error',
        'error': 'An unexpected error occurred. Please try again later.'
    }), 500

@app.errorhandler(400)
def bad_request(error):
    return jsonify({
        'success': False,
        'message': 'Bad request',
        'error': 'The request could not be understood by the server.'
    }), 400

if __name__ == '__main__':
    # Run database migrations before starting the app
    try:
        print("\n🔄 Running database migrations...")
        from run_migrations import run_all_migrations
        mongo_uri = app.config.get('MONGO_URI')
        run_all_migrations(mongo_uri)
        print("✅ Migrations completed\n")
    except Exception as e:
        print(f"⚠️  Migration error (non-fatal): {str(e)}\n")
        # Don't fail app startup if migrations fail
    
    # Initialize subscription scheduler
    try:
        print("🕐 Initializing subscription scheduler...")
        from utils.subscription_scheduler import SubscriptionScheduler
        subscription_scheduler = SubscriptionScheduler(mongo.db)
        subscription_scheduler.start()
        print("✅ Subscription scheduler started\n")
        print("   - Daily expiration processing at 2:00 AM UTC")
        print("   - Daily expiry warnings at 10:00 AM UTC")
        print("   - Daily renewal reminders at 9:00 AM UTC")
        print("   - Daily re-engagement messages at 11:00 AM UTC")
        print("   - Daily auto-renewal processing at 1:00 AM UTC\n")
    except Exception as e:
        print(f"⚠️  Scheduler initialization error (non-fatal): {str(e)}\n")
        # Don't fail app startup if scheduler fails
    
    app.run(debug=True, host='0.0.0.0', port=5000)





