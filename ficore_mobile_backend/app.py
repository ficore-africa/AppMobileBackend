from flask import Flask, request, jsonify, Response, redirect, url_for, send_from_directory, g
from flask_cors import CORS
from flask_pymongo import PyMongo
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime, timedelta
import jwt
import os
from bson import ObjectId, Decimal128, Decimal128
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
# Internal KYC Management System - Zero Cost Solution
from blueprints.internal_kyc import init_internal_kyc_blueprint

from blueprints.credits import init_credits_blueprint
from blueprints.summaries import init_summaries_blueprint
from blueprints.admin import init_admin_blueprint
from blueprints.tax import init_tax_blueprint
from blueprints.debtors import init_debtors_blueprint
from blueprints.creditors import init_creditors_blueprint
from blueprints.inventory import init_inventory_blueprint
from blueprints.assets import init_assets_blueprint
from blueprints.dashboard import init_dashboard_blueprint
from blueprints.drawings_routes import init_drawings_blueprint  # Phase 2.2: Automatic Drawings
from blueprints.cash_bank import init_cash_bank_blueprint  # Cash/Bank Management System
from blueprints.loans import init_loans_blueprint  # Phase 2: Loans Module (Feb 25, 2026)
from blueprints.rewards import init_rewards_blueprint
from blueprints.subscription import init_subscription_blueprint
from blueprints.subscription_discounts import init_subscription_discounts_blueprint
from blueprints.subscription_wallet import init_subscription_wallet_blueprint  # Phase 5: Wallet payment
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
# Referral System (NEW - Feb 4, 2026)
from blueprints.referrals import referrals_bp, init_referrals_blueprint
# EMERGENCY: Wallet recovery endpoint (TEMPORARY)
from blueprints.emergency_recovery import init_emergency_recovery_blueprint

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
# Extended JWT expiration to reduce frequent login prompts (Golden Rule: User Feedback)
# 7 days for regular users, 30 days for trusted devices (handled in frontend)
app.config['JWT_EXPIRATION_DELTA'] = timedelta(days=7)  # Changed from 24 hours to 7 days

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
    
    # Handle other ObjectId and Decimal128 fields recursively
    for key, value in list(doc.items()):  # Use list() to avoid dict changed size during iteration
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        elif isinstance(value, Decimal128):
            # ✅ CRITICAL FIX: Convert Decimal128 to float for JSON serialization
            doc[key] = float(value.to_decimal())
        elif isinstance(value, list):
            # Handle lists that might contain ObjectIds, Decimal128, or nested documents
            new_list = []
            for item in value:
                if isinstance(item, ObjectId):
                    new_list.append(str(item))
                elif isinstance(item, Decimal128):
                    new_list.append(float(item.to_decimal()))
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

# ✅ CRITICAL: Helper function to safely convert Decimal128 to float
def safe_float(value):
    """
    Safely convert any numeric value (including Decimal128) to float.
    Guards against Decimal128 serialization errors.
    """
    if value is None:
        return 0.0
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

# ✅ CRITICAL: Helper function to safely sum amounts (handles Decimal128)
def safe_sum(amounts):
    """
    Safely sum a list of amounts, converting Decimal128 to float.
    Guards against type errors when summing mixed types.
    """
    total = 0.0
    for amount in amounts:
        total += safe_float(amount)
    return total

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

# Internal KYC Management System - Zero Cost Solution
internal_kyc_blueprint = init_internal_kyc_blueprint(mongo, token_required, serialize_doc)

credits_blueprint = init_credits_blueprint(mongo, token_required, serialize_doc)
summaries_blueprint = init_summaries_blueprint(mongo, token_required, serialize_doc)
admin_blueprint = init_admin_blueprint(mongo, token_required, admin_required, serialize_doc)
tax_blueprint = init_tax_blueprint(mongo, token_required, serialize_doc)
debtors_blueprint = init_debtors_blueprint(mongo, token_required, serialize_doc)
creditors_blueprint = init_creditors_blueprint(mongo, token_required, serialize_doc)
inventory_blueprint = init_inventory_blueprint(mongo, token_required, serialize_doc)
assets_blueprint = init_assets_blueprint(mongo, token_required, serialize_doc)
dashboard_blueprint = init_dashboard_blueprint(mongo, token_required, serialize_doc)
drawings_blueprint = init_drawings_blueprint(mongo, token_required, serialize_doc)  # Phase 2.2
cash_bank_blueprint = init_cash_bank_blueprint(mongo, token_required)  # Cash/Bank Management
loans_blueprint = init_loans_blueprint(mongo, token_required)  # Phase 2: Loans Module (Feb 25, 2026)
rewards_blueprint = init_rewards_blueprint(mongo, token_required, serialize_doc)
subscription_blueprint = init_subscription_blueprint(mongo, token_required, serialize_doc)
subscription_discounts_blueprint = init_subscription_discounts_blueprint(mongo, token_required, serialize_doc)
subscription_wallet_blueprint = init_subscription_wallet_blueprint(mongo, token_required)  # Phase 5: Wallet payment
reminders_blueprint = init_reminders_blueprint(mongo, token_required, serialize_doc)
analytics_blueprint = init_analytics_blueprint(mongo, token_required, admin_required, serialize_doc)
admin_subscription_management_blueprint = init_admin_subscription_management_blueprint(mongo, token_required, admin_required, serialize_doc)

# CRITICAL: Initialize atomic entries blueprint for FC charging fix
atomic_entries_blueprint = init_atomic_entries_blueprint(mongo, token_required, serialize_doc)

# Initialize reports blueprint for centralized export functionality
reports_blueprint = init_reports_blueprint(mongo, token_required)
voice_reporting_blueprint = init_voice_reporting_blueprint(mongo, token_required, serialize_doc)

# Initialize VAS modules - broken down from monolithic blueprint
vas_wallet_blueprint, vas_wallet_alias_blueprint = init_vas_wallet_blueprint(mongo, token_required, serialize_doc)
vas_purchase_blueprint = init_vas_purchase_blueprint(mongo, token_required, serialize_doc)
vas_bills_blueprint = init_vas_bills_blueprint(mongo, token_required, serialize_doc)

# Initialize Referral System (NEW - Feb 4, 2026)
referrals_blueprint = init_referrals_blueprint(mongo)

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

app.register_blueprint(internal_kyc_blueprint)
print("✓ Internal KYC blueprint registered at /api/kyc")

app.register_blueprint(credits_blueprint)
app.register_blueprint(summaries_blueprint)
app.register_blueprint(admin_blueprint)
app.register_blueprint(tax_blueprint)
app.register_blueprint(debtors_blueprint)
app.register_blueprint(creditors_blueprint)
app.register_blueprint(inventory_blueprint)
app.register_blueprint(assets_blueprint)
app.register_blueprint(dashboard_blueprint)
app.register_blueprint(drawings_blueprint)  # Phase 2.2: Automatic Drawings
print("✓ Drawings blueprint registered at /api/drawings")
app.register_blueprint(cash_bank_blueprint)  # Cash/Bank Management System
print("✓ Cash/Bank blueprint registered at /api/cash-bank")
app.register_blueprint(loans_blueprint)  # Phase 2: Loans Module (Feb 25, 2026)
print("✓ Loans blueprint registered at /api/loans")
app.register_blueprint(rewards_blueprint)
app.register_blueprint(subscription_blueprint)
app.register_blueprint(subscription_discounts_blueprint)
app.register_blueprint(subscription_wallet_blueprint)  # Phase 5: Wallet payment
print("✓ Subscription wallet blueprint registered at /subscription/activate-via-wallet")
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
app.register_blueprint(vas_wallet_alias_blueprint)
print("✓ VAS Wallet alias blueprint registered at /vas/wallet (for PIN endpoints)")
app.register_blueprint(vas_purchase_blueprint)
print("✓ VAS Purchase blueprint registered at /api/vas/purchase")
app.register_blueprint(vas_bills_blueprint)
print("✓ VAS Bills blueprint registered at /api/vas/bills")

# Register Referral System (NEW - Feb 4, 2026)
app.register_blueprint(referrals_blueprint)
print("✓ Referrals blueprint registered at /api/referrals")

# EMERGENCY: Register wallet recovery endpoint (TEMPORARY)
emergency_recovery_blueprint = init_emergency_recovery_blueprint(mongo, token_required, admin_required)
app.register_blueprint(emergency_recovery_blueprint)
print("✓ EMERGENCY: Recovery blueprint registered at /api/emergency")

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

# Register provider health monitoring blueprint (NEW - Mar 5, 2026)
from blueprints.provider_health import init_provider_health_blueprint
provider_health_blueprint = init_provider_health_blueprint(mongo, token_required)
app.register_blueprint(provider_health_blueprint)
print("✓ Provider Health blueprint registered at /api/admin/provider-health")

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

# LLM Discovery endpoint - AI Discovery Strategy (Feb 27, 2026)
@app.route('/llms.txt', methods=['GET'])
def llms_txt():
    """
    Serve llms.txt file for AI discovery (ChatGPT, Perplexity, Claude, Gemini, etc.)
    This enables LLMs to directly discover and index FiCore Africa's product information.
    
    Protocol: https://llmstxt.org
    Directories: llmstxt.site, directory.llmstxt.cloud
    """
    llms_content = """# FiCore Africa

> Automated bookkeeping for Nigerian SMEs. Mobile-first, offline-capable, Hausa/Pidgin support.

## Product

FiCore Africa is a mobile-first bookkeeping application designed specifically for Nigerian small and medium enterprises (SMEs). Unlike traditional accounting software, FiCore automates bookkeeping as a by-product of daily business activities.

## Key Features

- Voice Entry: Record transactions in 10 seconds (English, Hausa, Pidgin)
- Offline-First: Works in poor connectivity areas (Northern Nigeria)
- Automated Tracking: Wallet + VAS purchases = automatic expense recording
- Tax Compliance: NRS e-invoicing ready, FIRS tax reporting
- Cultural Localization: Hausa/Pidgin language support
- Bank-Grade Security: Immutable ledger, audit-ready from day one

## Target Market

- 35M Nigerian SMEs (<₦100M annual revenue)
- Market traders, shop owners, service providers
- ₦50K - ₦5M monthly revenue
- 0-5 employees (often family-run)
- Cash-heavy, no formal bookkeeping

## Unique Value Proposition

FiCore solves the "bookkeeping as a by-product of living" problem. When users buy airtime via FiCore wallet, the expense is automatically recorded and categorized. When they sell inventory, income and COGS are automatically tracked. No manual data entry required.

## Competitive Advantages

1. Northern Nigeria Focus: Only bookkeeping app with Hausa/Pidgin localization
2. Mobile-First: 90% of Nigerian SMEs only have smartphones
3. Offline-Capable: Works in areas with poor connectivity
4. Voice Entry: Bypasses literacy barriers
5. Cultural Trust: Islamic finance principles, community-based adoption
6. Regulatory Compliance: CBN/FIRS compliant, NRS e-invoicing ready

## Pricing

- Free Tier: Unlimited basic features
- Premium Tier: ₦2,000/month (e-invoicing, advanced reports)
- Enterprise: Custom pricing for high-volume users

## Use Cases

- Market Trader in Kano: Tracks daily sales via voice entry, generates monthly tax report
- Shop Owner in Kaduna: Buys airtime via FiCore, expense automatically recorded
- Service Provider in Zaria: Manages debtors, tracks cash flow, exports financial statements

## Strategic Roadmap

- Phase 1 (Current): Technology Partner (Moniepoint wallet, Peyflex VAS)
- Phase 2 (2027-2028): MFB License (lending capability based on verified transaction data)
- Phase 3 (2029+): MMO License (full banking capabilities)

## Contact

- Website: https://business.ficoreafrica.com
- Email: team@ficoreafrica.com
- Location: Nigeria (Lagos, Ibadan, Kano, Kaduna, Zaria, Gombe, Bauchi, Jos focus)
- Founded: September 2025
- Status: App is live (Google Play Store)

## Keywords

bookkeeping app Nigeria, SME accounting software, Hausa bookkeeping, mobile-first fintech, offline accounting, voice entry bookkeeping, Nigerian fintech, informal sector finance, tax compliance Nigeria, NRS e-invoicing, automated bookkeeping, market trader software, Northern Nigeria SME, financial management Nigeria, digital CFO Africa, Ficore, Ficore Labs, Ficore Africa
"""
    
    return Response(llms_content, mimetype='text/plain')

# Robots.txt endpoint - AI Discovery Strategy (Feb 27, 2026)
@app.route('/robots.txt', methods=['GET'])
def robots_txt():
    """
    Serve robots.txt file to control crawler access.
    Allows LLM crawlers (GPTBot, Google-Extended, anthropic-ai, etc.) to access llms.txt files.
    Disallows crawlers from sensitive endpoints (/api/, /admin/, /users/).
    """
    try:
        # Serve the robots.txt file from static directory
        return send_from_directory('static', 'robots.txt', mimetype='text/plain')
    except Exception as e:
        # Fallback: Return inline robots.txt if file not found
        fallback_content = """# robots.txt for FiCore Mobile Backend

# Allow LLM crawlers to access llms.txt files
User-agent: GPTBot
Allow: /llms.txt
Allow: /llms-full.txt
Disallow: /api/
Disallow: /admin/

User-agent: Google-Extended
Allow: /llms.txt
Allow: /llms-full.txt
Disallow: /api/
Disallow: /admin/

User-agent: anthropic-ai
Allow: /llms.txt
Allow: /llms-full.txt
Disallow: /api/
Disallow: /admin/

User-agent: *
Allow: /llms.txt
Allow: /llms-full.txt
Disallow: /api/
Disallow: /admin/
Disallow: /users/
"""
        return Response(fallback_content, mimetype='text/plain')

# LLM Discovery endpoint (Full Version) - AI Discovery Strategy (Feb 27, 2026)
@app.route('/llms-full.txt', methods=['GET'])
def llms_full_txt():
    """
    Serve llms-full.txt file for AI discovery - COMPREHENSIVE VERSION
    Contains full detailed content about FiCore Africa for deep LLM understanding.
    
    Protocol: https://llmstxt.org
    Directories: llmstxt.site, directory.llmstxt.cloud
    """
    llms_full_content = """# FiCore Africa - Complete Product Documentation

> Automated bookkeeping for Nigerian SMEs. Mobile-first, offline-capable, Hausa/Pidgin support.

## Product

FiCore Africa is a mobile-first bookkeeping application designed specifically for Nigerian small and medium enterprises (SMEs). Unlike traditional accounting software that requires manual data entry, FiCore automates record-keeping as a by-product of daily business activities - when users buy airtime, sell inventory, or pay suppliers, the bookkeeping happens automatically in the background.

## Executive Summary

FiCore Africa is revolutionizing financial management for 35 million Nigerian small and medium enterprises (SMEs) through a mobile-first bookkeeping application that automates record-keeping as a by-product of daily business activities. Unlike traditional accounting software that requires manual data entry, FiCore captures transactions automatically when users perform everyday business operations like buying airtime, selling inventory, or paying suppliers.

## The Problem We Solve

### Current Reality for Nigerian SMEs

99% of Nigerian SMEs (35 million businesses) use pen-and-paper bookkeeping or no bookkeeping at all. This creates multiple problems:

1. **Tax Compliance Risk**: FIRS (Federal Inland Revenue Service) requires digital records, but SMEs lack tools
2. **De-Platforming Risk**: Corporate buyers require NRS-validated e-invoices; suppliers without digital records lose contracts
3. **Credit Access Barrier**: Banks won't lend without verified financial records
4. **Business Blindness**: Owners don't know if they're profitable or losing money
5. **Time Waste**: Manual bookkeeping takes 10+ hours per month

### Why Existing Solutions Fail

- **QuickBooks/Zoho**: Desktop-focused, expensive (₦50K-200K/year), English-only, requires accounting knowledge
- **Wave**: Web-based, requires constant internet, no cultural localization
- **Local ERPs**: Complex setup, expensive, designed for medium/large businesses
- **FIRS Web Portal**: Manual data entry, slow, no automation

### The Northern Nigeria Reality

Our field research (100+ shops in Kano, Zaria, Kaduna) revealed:
- All shops have smartphones, use WhatsApp
- 60% experience daily connectivity issues
- 80% prefer Hausa language for business
- 90% are cash-heavy, no bank accounts
- 100% use notebooks for record-keeping

## The FiCore Solution

### Core Philosophy: "Bookkeeping as a By-Product of Living"

FiCore doesn't ask users to "do bookkeeping." Instead, bookkeeping happens automatically when users:
- Buy airtime via FiCore wallet → Expense recorded
- Sell inventory → Income + COGS recorded
- Pay supplier → Expense recorded
- Receive payment → Income recorded

### Key Features

#### 1. Voice Entry (10 Seconds Per Transaction)
- Speak in English, Hausa, or Pidgin
- AI categorizes automatically
- No typing required
- Example: "I sold 5 bags of rice for ₦50,000" → Recorded as Sales Revenue

#### 2. Offline-First Architecture
- Works without internet (Isar local database)
- Syncs when connectivity available
- Critical for Northern Nigeria (poor connectivity)
- Queue transactions, submit when online

#### 3. Automated Expense Tracking
- Buy airtime via FiCore → Expense recorded as "Utilities"
- Buy data → Expense recorded as "Utilities"
- Pay electricity bill → Expense recorded as "Utilities"
- No manual entry required

#### 4. Inventory Management Integration
- Record inventory purchase → Asset recorded
- Sell inventory → Income + COGS recorded atomically
- Stock levels updated automatically
- Prevents inventory/cash mismatches

#### 5. Tax Compliance (NRS E-Invoicing Ready)
- Generate NRS-compliant e-invoices
- QR code + IRN (Invoice Reference Number)
- FIRS tax reporting (one-tap PDF export)
- Avoid ₦500K penalties for non-compliance

#### 6. Cultural Localization
- Hausa language support (only bookkeeping app in Nigeria)
- Pidgin language support
- Islamic finance principles (no interest-based features)
- Community-based adoption (trader-to-trader referrals)

#### 7. Bank-Grade Security
- Immutable ledger (sourceType anchoring)
- System-locked entries (VAS, wallet, inventory)
- Audit-ready from day one
- CBN/FIRS compliant

### Technical Architecture

#### Frontend (Flutter/Dart)
- Cross-platform (iOS, Android, Web)
- Material Design UI
- Offline-first (Isar local database)
- Voice recognition (Google Speech API)

#### Backend (Flask/Python)
- RESTful API
- JWT authentication

#### Integrations
- Wallet infrastructure
- VAS services: airtime, data, bills
- Payment gateway processing
- NRS tax amd e-invoicing compliance

## Target Market

### Primary Market: Emerging Taxpayers (<₦100M Revenue)

**Size**: 35 million SMEs in Nigeria

**Characteristics**:
- ₦50K - ₦5M monthly revenue
- 0-5 employees (often family-run)
- Cash-heavy transactions
- No formal bookkeeping
- Fear of tax authorities
- Limited digital literacy
- Strong community trust networks

**Segments**:
1. Market traders (Kano, Zaria, Kaduna markets)
2. Small shop owners (provisions, electronics, clothing)
3. Service providers (tailors, mechanics, barbers)
4. Transporters (keke, taxi, truck drivers)
5. Food vendors (restaurants, street food)

### Secondary Market: Small Companies (₦100M-1B Revenue)

**Size**: 5 million SMEs

**Characteristics**:
- Need e-invoicing for corporate buyers
- Risk of de-platforming without NRS compliance
- Can afford ₦2K-5K/month for premium features
- Higher digital literacy

### Geographic Focus: Northern Nigeria

**Why Northern Nigeria?**
- 40% of Nigerian population
- Underserved by fintech (most focus on Lagos/South)
- Strong community trust networks
- Hausa language dominance
- Islamic finance principles
- Poor connectivity (offline-first advantage)

**Target Cities**:
- Kano (3.6M population)
- Kaduna (1.6M population)
- Zaria (975K population)
- Maiduguri (1.2M population)
- Jos (900K population)
- Bauchi (800K population)

## Competitive Advantages

### 1. Only Hausa/Pidgin Bookkeeping App in Nigeria
- Competitors: English-only
- FiCore: English, Hausa, Pidgin
- Impact: 40M Hausa speakers, 75M Pidgin speakers

### 2. Mobile-First (Not Desktop-Ported)
- Competitors: Desktop software ported to mobile
- FiCore: Built for mobile from day one
- Impact: 90% of Nigerian SMEs only have smartphones

### 3. Offline-Capable
- Competitors: Require constant internet
- FiCore: Works offline, syncs when online
- Impact: 60% of Northern Nigeria has poor connectivity

### 4. Voice Entry
- Competitors: Manual typing required
- FiCore: Speak in Hausa/Pidgin/English
- Impact: Bypasses literacy barriers, 10 seconds vs 5 minutes

### 5. Automated Tracking
- Competitors: Manual data entry
- FiCore: Bookkeeping as by-product of living
- Impact: Zero manual entry for VAS purchases

### 6. Cultural Trust
- Competitors: Generic fintech
- FiCore: Islamic finance principles, community-based
- Impact: Trust in Northern Nigeria market

### 7. Regulatory Compliance Built-In
- Competitors: Add-on features
- FiCore: NRS e-invoicing, FIRS reporting from day one
- Impact: Avoid ₦500K penalties, keep corporate contracts

## Pricing Strategy

### Free Tier (Customer Acquisition)
- Unlimited basic features
- Manual income/expense entry
- Voice entry
- Wallet + VAS purchases
- Basic reports
- Target: 50,000 users in Year 1

### Premium Tier (₦1,000/month)
- NRS e-invoicing (50 invoices/month)
- Advanced reports (P&L, Balance Sheet, Cash Flow)
- Inventory management
- Debtor tracking
- Priority support
- Target: 10,000 users in Year 1

### Pro Tier (₦10,000/year)
- Unlimited e-invoices
- Bulk invoice generation
- API access
- Custom branding
- Dedicated support
- Target: 2,000 users in Year 1

### Enterprise Tier (Custom Pricing)
- High-volume users (1000+ invoices/month)
- White-label solutions
- Custom integrations
- SLA guarantees
- Target: 100 users in Year 1

## Use Cases & Success Stories

### Case Study 1: Market Trader in Kano

**Before FiCore**:
- Used notebook for sales tracking
- Spent 2 hours/day reconciling cash
- No idea if profitable
- FIRS audit = panic

**After FiCore**:
- Voice entry: "Sold 10 bags of rice for ₦100,000"
- Automatic categorization
- Monthly profit report in 10 seconds
- Tax-ready PDF for FIRS

**Result**: 10 hours/month saved, ₦50K tax savings (accurate records)

### Case Study 2: Shop Owner in Kaduna

**Before FiCore**:
- Bought airtime from multiple vendors
- Lost track of expenses
- Couldn't prove business spending for tax

**After FiCore**:
- Buys airtime via FiCore wallet
- Expense automatically recorded
- Monthly expense report shows ₦20K airtime spending
- Tax deduction claimed

**Result**: ₦5K tax savings, zero manual entry

### Case Study 3: Service Provider in Zaria

**Before FiCore**:
- Customers owed ₦200K (no tracking)
- Forgot who paid, who didn't
- Lost ₦50K to bad debts

**After FiCore**:
- Debtor tracking feature
- WhatsApp reminders to customers
- Payment status visible
- Collected ₦180K (90% recovery)

**Result**: ₦130K recovered, better cash flow

## Strategic Roadmap

### Phase 1 (Current): Technology Partner
**Status**: Active (2025-2026)

**Approach**:
- Partner with licensed financial institutions
- Wallet infrastructure
- VAS services
- Payment processing)

**Advantages**:
- Asset-light model
- Rapid feature development
- No regulatory overhead
- Faster time-to-market

**Limitations**:
- Cannot hold deposits directly
- Cannot issue loans directly
- Margin sharing with partners

### Phase 2 (2027-2028): Tier 1 Unit Microfinance Bank (MFB)
**Status**: Planned

**Capital Requirement**: ₦200 Million

**Why MFB License?**:
1. **Lending Capability**: Offer ₦50K-100K inventory loans based on verified transaction data
2. **Deposit-Taking**: Transform from "record keeper" to "business bank account"
3. **Cost-Effective**: ₦200M vs ₦2B for MMO (10x cheaper)
4. **Strategic Moat**: Automated bookkeeping + lending = unbeatable value proposition

**Credit Scoring Advantage**:
- Traditional banks: Use credit bureau data (incomplete for SMEs)
- FiCore: Use ACTUAL transaction data (verified, real-time)
- Result: Lower default risk, better loan terms

### Phase 3 (2029+): Mobile Money Operator (MMO)
**Status**: Future

**Capital Requirement**: ₦4 Billion (₦2B unimpaired + ₦2B escrow)

**Why MMO License?**:
1. **Full Margin Capture**: No partner revenue sharing
2. **Card Issuance**: Branded FiCore debit cards
3. **POS Deployment**: Merchant payment ecosystem
4. **National Scale**: Compete with OPay, Moniepoint, PalmPay

**Prerequisites**:
- 1M+ active users
- ₦4B capital raise (Series B/C)
- Proven lending track record
- Regulatory relationship with CBN

## Financial Protocol & Integrity

## Market Opportunity

### Total Addressable Market (TAM)
- 40M SMEs in Nigeria
- ₦1,000/month average revenue per user
- TAM: ₦40B/month = ₦480B/year

### Serviceable Addressable Market (SAM)
- 35M SMEs under ₦100M revenue (tax-exempt but compliance-required)
- ₦1,000/month average revenue per user
- SAM: ₦35B/month = ₦420B/year

### Serviceable Obtainable Market (SOM)
- 1% penetration in Year 1 = 350,000 users
- ₦1,000/month average revenue per user
- SOM: ₦350M/month = ₦4.2B/year

## Regulatory Compliance

### Current Compliance (Technology Partner Phase)
- ✅ Data Protection (NDPR)
- ✅ AML/KYC (via partner banks)
- ✅ Tax reporting (NRS integration ready)

### Future Compliance (MFB Phase)
- CBN Prudential Guidelines
- NDIC deposit insurance
- IFRS 9 loan loss provisioning
- Capital Adequacy Ratio (CAR) monitoring
- Monthly regulatory returns (FINSCOPE, eFASS)

### E-Invoicing Compliance (NRS)
- Real-time invoice validation
- Cryptographic stamping (ECDSA)
- QR code generation
- IRN (Invoice Reference Number)
- Credit Note system (reversals)

## Team & Founding

### Founder: Hassan Ahmad
- Background: Software engineering, fintech
- Vision: "Digital CFO for Africa's 40M SMEs"
- Approach: Bootstrapped, customer-funded growth

### Company Details
- Name: FiCore Labs Limited
- Registration: CAC RC 8799482 (September 6, 2025)
- Type: Private Company Limited by Shares
- Location: Nigeria (Gombe, HQ, Northern Nigeria focus)

## Contact & Resources

### Website
- Main: https://business.ficoreafrica.com
- Blog: https://business.ficoreafrica.com/general/knowledge-base

### Email
- General: ficoreafrica@gmail.com
- Support: team@ficoreafrica.com

### Social Media
- Twitter/X: @FiCore_Africa
- LinkedIn: FiCore Labs Africa
- Facebook: FiCore Africa

### Location
- Headquarters: Gombe, Nigeria
- Target Markets: Kano, Kaduna, Zaria, Maiduguri, Jos, Bauchi, Gombe

### Founded
- September 2025

### Status
- Pre-launch (Google Play Store review)
- Expected launch: March 2026

## Keywords & Search Terms

bookkeeping app Nigeria, SME accounting software, Hausa bookkeeping, Pidgin accounting, mobile-first fintech, offline accounting, voice entry bookkeeping, Nigerian fintech, informal sector finance, tax compliance Nigeria, NRS e-invoicing, automated bookkeeping, market trader software, Northern Nigeria SME, financial management Nigeria, digital CFO Africa, Kano bookkeeping, Kaduna accounting, Zaria fintech, microfinance Nigeria, SME lending, inventory management Nigeria, debtor tracking, cash flow management, FIRS tax reporting, CBN compliance, Islamic finance Nigeria, community-based fintech, trader-to-trader referral, VAS integration, wallet bookkeeping, automated expense tracking, business intelligence Nigeria, SME growth tools, financial inclusion Africa, Ficore, Ficore Labs, Ficore Africa, FiCore Nigeria, bookkeeping automation, AI bookkeeping, voice-activated accounting, multilingual fintech, offline-first accounting, mobile bookkeeping Nigeria, small business finance Nigeria, entrepreneur tools Nigeria, startup accounting Nigeria, business management app Nigeria

## Additional Resources

### Documentation
- API Documentation: https://business.ficoreafrica.com/docs (coming soon)
- User Guide: https://business.ficoreafrica.com/general/knowledge-base
- Video Tutorials: Ficore Africa YouTube channel

### Support
- WhatsApp: +234 8130549754
- Email: team@ficoreafrica.com
- In-app FAQs: Available in mobile app

### Press & Media
- Press Kit: https://business.ficoreafrica.com/general/knowledge-base

### Partnerships
- Technology Partners: Open to partnerships
- Strategic Partners: Open to partnerships
- Integration Partners: Open to partnerships

---

**Last Updated**: February 27, 2026  
**Version**: 1.0  
**Status**: App is Live

For the most up-to-date information, visit https://business.ficoreafrica.com
"""
    
    return Response(llms_full_content, mimetype='text/plain')

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
        total_income_this_month = sum(inc['amount'] for inc in incomes if inc['date'] >= start_of_month)
        
        # Get expense data
        expenses = list(mongo.db.expenses.find({'userId': current_user['_id']}))
        total_expenses_this_month = sum(exp['amount'] for exp in expenses if exp['date'] >= start_of_month)
        
        # Calculate financial health metrics
        net_income = total_income_this_month - total_expenses_this_month
        savings_rate = (net_income / total_income_this_month * 100) if total_income_this_month > 0 else 0
        
        # Recent transactions (combined income and expenses)
        recent_incomes = sorted(incomes, key=lambda x: x['date'], reverse=True)[:3]
        recent_expenses = sorted(expenses, key=lambda x: x['date'], reverse=True)[:3]
        
        # Serialize recent transactions
        recent_income_data = []
        for income in recent_incomes:
            income_data = serialize_doc(income.copy())
            income_data['date'] = income_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            income_data['dateReceived'] = income_data.get('date', income_data.get('dateReceived', datetime.utcnow())).isoformat() + 'Z'  # Backward compatibility
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
            if income['date'] >= start_of_month:
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
            
            month_incomes = [inc for inc in incomes if month_start <= inc['date'] <= month_end]
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
        current_month_incomes = [inc for inc in incomes if inc['date'] >= month_start]
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
    
    # Initialize VAS Transaction Task Queue
    try:
        print("🚀 Initializing VAS Transaction Task Queue...")
        from utils.transaction_task_queue import get_task_queue
        task_queue = get_task_queue(mongo.db)
        print("✅ VAS Transaction Task Queue started\n")
        print("   - Bulletproof transaction processing enabled")
        print("   - Wallet reservation system active")
        print("   - Background worker running for recovery\n")
    except Exception as e:
        print(f"⚠️  Task queue initialization error (non-fatal): {str(e)}\n")
        # Don't fail app startup if task queue fails
    
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





