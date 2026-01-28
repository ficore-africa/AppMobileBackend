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
from blueprints.otp import init_otp_blueprint  # ₦0 Communication Strategy
from blueprints.engagement import init_engagement_blueprint  # Weekly engagement reminders
from blueprints.notifications import init_notifications_blueprint  # Persistent notifications

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
# VAS modules - broken down from monolithic blueprint
from blueprints.vas_wallet import init_vas_wallet_blueprint
from blueprints.vas_purchase import init_vas_purchase_blueprint
from blueprints.vas_bills import init_vas_bills_blueprint

# Import database models
from models import DatabaseInitializer

# Import rate limit tracking utilities
from utils.rate_limit_tracker import RateLimitTracker
from utils.api_logging_middleware import setup_api_logging

# Import credential manager
from config.credentials import credential_manager

app = Flask(__name__)

# Enhanced logging configuration
import logging
from logging.handlers import RotatingFileHandler

# Configure logging
if not app.debug:
    # Create logs directory if it doesn't exist
    import os
    if not os.path.exists('logs'):
        os.mkdir('logs')
    
    # Set up file handler with rotation
    file_handler = RotatingFileHandler('logs/ficore_backend.log', maxBytes=10240000, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    
    # Set up console handler for immediate feedback
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s'
    ))
    console_handler.setLevel(logging.INFO)
    app.logger.addHandler(console_handler)
    
    app.logger.setLevel(logging.INFO)
    app.logger.info('FiCore Backend startup')

# Add request logging middleware - DISABLED FOR LIQUID WALLET FOCUS
@app.before_request
def log_request_info():
    # DISABLED FOR LIQUID WALLET FOCUS - Uncomment to re-enable request logging
    pass
    # try:
    #     # Only log request body for non-file uploads to avoid logging large files
    #     body_preview = ""
    #     if request.content_type and 'multipart/form-data' not in request.content_type:
    #         body_data = request.get_data(as_text=True)
    #         body_preview = body_data[:500] if body_data else ""
    #     
    #     app.logger.info(f'Request: {request.method} {request.url} - Headers: {dict(request.headers)} - Body: {body_preview}')
    # except Exception as e:
    #     app.logger.info(f'Request: {request.method} {request.url} - (Error reading request: {str(e)})')

@app.after_request
def log_response_info(response):
    # DISABLED FOR LIQUID WALLET FOCUS - Uncomment to re-enable response logging
    # try:
    #     # Only try to read response data for JSON responses, not file downloads
    #     if response.content_type and 'application/json' in response.content_type:
    #         app.logger.info(f'Response: {response.status_code} - {response.get_data(as_text=True)[:500]}')
    #     else:
    #         # For file responses, just log the status and content type
    #         app.logger.info(f'Response: {response.status_code} - Content-Type: {response.content_type}')
    # except Exception as e:
    #     # Fallback logging if response data can't be read
    #     app.logger.info(f'Response: {response.status_code} - (Content not readable: {str(e)})')
    return response

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
    
    # Run immutability migration (idempotent - safe to run multiple times)
    from utils.immutability_migrator import run_immutability_migration
    migration_result = run_immutability_migration(mongo.db)
    
    if migration_result['success'] and not migration_result['already_run']:
        print("✅ Immutability migration completed successfully")
    elif migration_result['already_run']:
        print("✅ Immutability migration already completed (skipped)")
    else:
        print(f"⚠️  Immutability migration failed: {migration_result.get('error', 'Unknown error')}")
    
    # CRITICAL FIX: Run dashboard performance indexes migration
    from migrations.add_dashboard_performance_indexes import run_dashboard_performance_migration
    dashboard_migration_result = run_dashboard_performance_migration(mongo.db)
    
    if dashboard_migration_result['success'] and not dashboard_migration_result['already_run']:
        print("✅ Dashboard performance migration completed successfully")
    elif dashboard_migration_result['already_run']:
        print("✅ Dashboard performance migration already completed (skipped)")
    else:
        print(f"⚠️  Dashboard performance migration failed: {dashboard_migration_result.get('error', 'Unknown error')}")

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

# ₦0 Communication Strategy - OTP Management
otp_blueprint = init_otp_blueprint(mongo, app.config)

# ₦0 Communication Strategy - Weekly Engagement Reminders
engagement_blueprint = init_engagement_blueprint(mongo, app.config)

# Persistent Notifications System
notifications_blueprint = init_notifications_blueprint(mongo, token_required, serialize_doc)

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

# Initialize VAS modules - broken down from monolithic blueprint
vas_wallet_blueprint = init_vas_wallet_blueprint(mongo, token_required, serialize_doc)
vas_purchase_blueprint = init_vas_purchase_blueprint(mongo, token_required, serialize_doc)
vas_bills_blueprint = init_vas_bills_blueprint(mongo, token_required, serialize_doc)

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

# ₦0 Communication Strategy
app.register_blueprint(otp_blueprint)
print("✓ OTP blueprint registered at /otp")

app.register_blueprint(engagement_blueprint)
print("✓ Engagement blueprint registered at /engagement")

app.register_blueprint(notifications_blueprint)
print("✓ Notifications blueprint registered at /api/notifications")

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

# Register VAS modules - broken down from monolithic blueprint
app.register_blueprint(vas_wallet_blueprint)
print("✓ VAS Wallet blueprint registered at /api/vas/wallet")
app.register_blueprint(vas_purchase_blueprint)
print("✓ VAS Purchase blueprint registered at /api/vas/purchase")
app.register_blueprint(vas_bills_blueprint)
print("✓ VAS Bills blueprint registered at /api/vas/bills")

# Register VAS reconciliation blueprint for admin transaction management
from blueprints.vas_reconciliation import init_vas_reconciliation_blueprint
vas_reconciliation_blueprint = init_vas_reconciliation_blueprint(mongo, token_required, admin_required)
app.register_blueprint(vas_reconciliation_blueprint, url_prefix='/admin')
print("✓ VAS Reconciliation blueprint registered at /admin")

# Register admin user transactions blueprint
from blueprints.admin_user_transactions import init_admin_user_transactions_blueprint
admin_user_transactions_blueprint = init_admin_user_transactions_blueprint(mongo, token_required, admin_required)
app.register_blueprint(admin_user_transactions_blueprint, url_prefix='/api/admin')
print("✓ Admin User Transactions blueprint registered at /api/admin")

# Root redirect to admin login
@app.route('/', methods=['GET', 'HEAD'])
def index():
    """Redirect root URL to admin login page, but return 200 for health checks"""
    # Check if this is a health check request (HEAD request or specific user agent)
    if request.method == 'HEAD' or 'Go-http-client' in request.headers.get('User-Agent', ''):
        return jsonify({
            'status': 'healthy',
            'service': 'FiCore Backend',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    
    # Regular browser requests get redirected to admin
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
        # Use credential manager instead of direct import
        if not credential_manager.is_gcs_available():
            return jsonify({
                'success': False,
                'message': 'GCS client not initialized',
                'bucket': None,
                'status': 'unavailable'
            }), 503
        
        storage_client = credential_manager.get_gcs_client()
        bucket_name = os.environ.get('GCS_BUCKET_NAME', 'ficore-attachments')
        bucket = storage_client.bucket(bucket_name)
        
        # Test if bucket exists and is accessible
        exists = bucket.exists()
        
        if exists:
            return jsonify({
                'success': True,
                'message': 'GCS is accessible',
                'bucket': bucket_name,
                'status': 'available'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'GCS bucket not found or not accessible',
                'bucket': bucket_name,
                'status': 'unavailable'
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'GCS health check failed: {str(e)}',
            'bucket': bucket_name,
            'status': 'error'
        }), 500

# Firebase health check endpoint
@app.route('/health/firebase', methods=['GET'])
def firebase_health_check():
    """Check if Firebase is properly initialized"""
    try:
        if credential_manager.is_firebase_available():
            return jsonify({
                'success': True,
                'message': 'Firebase is available',
                'status': 'initialized'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Firebase is not initialized',
                'status': 'unavailable'
            }), 503
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Firebase health check failed: {str(e)}',
            'status': 'error'
        }), 500

# Email service health check endpoint
@app.route('/health/email', methods=['GET'])
def email_health_check():
    """Check if Email service is properly configured"""
    try:
        from utils.email_service import get_email_service
        
        email_service = get_email_service()
        status = email_service.get_service_status()
        
        if status['enabled']:
            return jsonify({
                'success': True,
                'message': 'Email service is available',
                'status': 'enabled',
                'sender_email': status['sender_email'],
                'mode': status['mode']
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Email service is not configured',
                'status': 'disabled',
                'mode': status['mode']
            }), 503
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Email health check failed: {str(e)}',
            'status': 'error'
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
    # Run database migrations after initialization
    try:
        print("🔄 Running database migrations...")
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
    
    # Only run Flask development server if not running under Gunicorn
    # Check if we're running under Gunicorn by looking for gunicorn in the process
    import sys
    if 'gunicorn' not in sys.modules and 'gunicorn' not in ' '.join(sys.argv):
        print("🔧 Running Flask development server...")
        app.run(debug=True, host='0.0.0.0', port=5000)
    else:
        print("🚀 Running under Gunicorn - Flask development server disabled")

# Ensure app is available at module level for Gunicorn
# This is critical for Gunicorn to find the app object
if __name__ != '__main__':
    print(f"🔍 Module imported by Gunicorn - app object available at: {__name__}.app")
    
    # Production deployment - no additional initialization needed
    print("🚀 Production deployment ready")





