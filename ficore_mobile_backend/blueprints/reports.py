"""
Reports Blueprint - Centralized Export Endpoints
Handles all report generation and export functionality for FiCore Mobile
"""
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import sys
import os
import io
import csv

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.business_bookkeeping import *
from utils.decimal_helpers import *
from utils.pdf_generator import PDFGenerator
from utils.parallel_query_helper import fetch_collections_parallel
from utils.pdf_cache_helper import get_pdf_cache
from utils.background_report_generator import get_background_generator, ReportJobStatus

# CRITICAL SECURITY FIX: Business User ID to exclude from user reports
# This prevents regular users from seeing FiCore's internal business data
BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')

def create_user_query(user_id, additional_filters=None):
    """
    SECURITY FIX: Create a secure query that excludes business data
    
    This function ensures that regular users NEVER see FiCore's internal
    business transactions (FC liabilities, marketing expenses, etc.)
    
    Args:
        user_id: The current user's ID
        additional_filters: Additional query filters to apply
    
    Returns:
        dict: MongoDB query that excludes business data
    """
    # Base query: user's data only, exclude business account
    query = {
        'userId': user_id,
        'status': 'active',
        'isDeleted': False
    }
    
    # CRITICAL: Ensure we never include business account data
    # Even if somehow user_id equals BUSINESS_USER_ID, this prevents it
    if user_id == BUSINESS_USER_ID:
        # If someone tries to query business data directly, return empty results
        query['_id'] = ObjectId('000000000000000000000000')  # Non-existent ID
    
    # Apply additional filters if provided
    if additional_filters:
        query.update(additional_filters)
    
    return query

# ============================================================================
# QUERY PROJECTIONS FOR PDF EXPORT OPTIMIZATION
# ============================================================================
# These projections fetch only the fields needed for PDF generation,
# reducing data transfer from MongoDB by 40-60% and improving query speed by 2-3x

PDF_PROJECTIONS = {
    'incomes': {
        'source': 1,
        'amount': 1,
        'date': 1,
        'description': 1,
        'category': 1,
        'tags': 1,
        'status': 1,
        '_id': 1  # Keep _id for tracking
    },
    'expenses': {
        'title': 1,
        'description': 1,
        'notes': 1,
        'amount': 1,
        'date': 1,
        'category': 1,
        'tags': 1,
        'status': 1,
        '_id': 1
    },
    'assets': {
        'name': 1,
        'assetName': 1,
        'category': 1,
        'purchaseDate': 1,
        'purchasePrice': 1,
        'purchaseCost': 1,
        'currentValue': 1,
        'usefulLifeYears': 1,
        'manualValueAdjustment': 1,
        'status': 1,
        '_id': 1
    },
    'debtors': {
        'name': 1,
        'customerName': 1,
        'amount': 1,
        'invoiceDate': 1,
        'dueDate': 1,
        'status': 1,
        '_id': 1
    },
    'creditors': {
        'name': 1,
        'vendorName': 1,
        'amount': 1,
        'invoiceDate': 1,
        'dueDate': 1,
        'status': 1,
        '_id': 1
    },
    'inventory': {
        'name': 1,
        'sku': 1,
        'quantity': 1,
        'unitCost': 1,
        'minStockLevel': 1,
        '_id': 1
    },
    'credit_transactions': {
        'type': 1,
        'amount': 1,
        'description': 1,
        'createdAt': 1,
        'balanceAfter': 1,
        '_id': 1
    }
}

# ============================================================================
# VAS COMMISSION HELPER FUNCTION
# ============================================================================

def get_vas_commissions_from_transactions(mongo, user_id, start_date=None, end_date=None):
    """
    Fetch VAS commissions from vas_transactions.providerCommission field
    This matches the treasury dashboard pattern and is the authoritative source
    """
    try:
        # Build query for VAS transactions with commissions
        query = {
            'userId': ObjectId(user_id),
            'status': 'SUCCESS',
            'providerCommission': {'$gt': 0}  # Only transactions with actual commissions
        }
        
        # Add date filtering if provided
        if start_date or end_date:
            date_filter = {}
            if start_date:
                date_filter['$gte'] = start_date
            if end_date:
                date_filter['$lte'] = end_date
            query['createdAt'] = date_filter
        
        # Fetch VAS transactions with commissions
        vas_transactions = list(mongo.db.vas_transactions.find(query, {
            'providerCommission': 1,
            'provider': 1,
            'type': 1,
            'createdAt': 1,
            'amount': 1,
            '_id': 1
        }))
        
        # Calculate total VAS commission revenue
        total_vas_commission = sum(t.get('providerCommission', 0) for t in vas_transactions)
        
        return {
            'total_commission': total_vas_commission,
            'transactions': vas_transactions,
            'count': len(vas_transactions)
        }
        
    except Exception as e:
        print(f"Error fetching VAS commissions: {str(e)}")
        return {
            'total_commission': 0,
            'transactions': [],
            'count': 0
        }

# ============================================================================

def init_reports_blueprint(mongo, token_required):
    print("DEBUG: init_reports_blueprint called")
    """Initialize the reports blueprint with database and auth decorator"""
    reports_bp = Blueprint('reports', __name__, url_prefix='/api/reports')
    print("DEBUG: Blueprint object created successfully")
    print("DEBUG: Blueprint created successfully")
    
    # Credit costs for different report types
    print("DEBUG: About to define REPORT_CREDIT_COSTS")
    REPORT_CREDIT_COSTS = {
        # Basic Reports (2 FC each)
        'income_csv': 2,
        'income_pdf': 2,
        'expense_csv': 2,
        'expense_pdf': 2,
        'credits_pdf': 2,
        'credits_csv': 2,
        
        # Business Reports (3 FC each)
        'profit_loss_pdf': 3,
        'profit_loss_csv': 3,
        'cash_flow_pdf': 3,
        'cash_flow_csv': 3,
        'tax_summary_pdf': 3,
        'tax_summary_csv': 3,
        
        # Advanced Reports (5 FC each)
        'debtors_pdf': 5,
        'debtors_csv': 5,
        'creditors_pdf': 5,
        'creditors_csv': 5,
        'assets_pdf': 5,
        'assets_csv': 5,
        'asset_depreciation_pdf': 5,
        'asset_depreciation_csv': 5,
        'inventory_pdf': 5,
        'inventory_csv': 5,
        
        # Wallet Reports (2-4 FC each)
        'wallet_funding_csv': 2,
        'wallet_funding_pdf': 3,
        'wallet_vas_csv': 2,
        'wallet_vas_pdf': 3,
        'wallet_bills_csv': 2,
        'wallet_bills_pdf': 3,
        'wallet_full_csv': 3,
        'wallet_full_pdf': 4,
        
        # Premium Comprehensive Reports (8 FC)
        'statement_of_affairs_pdf': 8,
        'statement_of_affairs_csv': 5,
    }    
    # Initialize PDF cache (singleton)
    print("DEBUG: About to initialize PDF cache")
    pdf_cache = get_pdf_cache()
    print("DEBUG: PDF cache initialized successfully")
    
    
    print("DEBUG: About to define check_user_access function")
    def check_user_access(current_user, report_type):
        """
        Check if user has access to generate report (Premium or sufficient credits)
        Returns: (has_access: bool, is_premium: bool, current_balance: float, credit_cost: int)
        """
        user = mongo.db.users.find_one({'_id': current_user['_id']})
        is_admin = user.get('role') == 'admin'
        
        # [OK] CRITICAL FIX: Validate subscription end date, not just flag
        is_subscribed = user.get('isSubscribed', False)
        subscription_end = user.get('subscriptionEndDate')
        is_premium = is_admin or (is_subscribed and subscription_end and subscription_end > datetime.utcnow())
        
        current_balance = user.get('ficoreCreditBalance', 0.0)
        credit_cost = REPORT_CREDIT_COSTS.get(report_type, 2)
        
        # Premium users and admins have unlimited access
        if is_premium:
            return True, True, current_balance, 0
        
        # Free users need sufficient credits
        has_access = current_balance >= credit_cost
        return has_access, False, current_balance, credit_cost

    def _validate_pdf_integrity(pdf_buffer):
        """
        Validate that the generated PDF is not corrupted and can be opened.
        
        Args:
            pdf_buffer: BytesIO buffer containing PDF data
            
        Returns:
            bool: True if PDF is valid, False if corrupted
        """
        try:
            # Reset buffer position
            pdf_buffer.seek(0)
            pdf_data = pdf_buffer.read()
            
            # Check minimum size (empty or tiny PDFs are likely corrupted)
            if len(pdf_data) < 1000:  # PDFs should be at least 1KB
                print(f"[ERROR] PDF Validation: File too small ({len(pdf_data)} bytes)")
                return False
            
            # Check PDF header
            if not pdf_data.startswith(b'%PDF-'):
                print(f"[ERROR] PDF Validation: Invalid PDF header")
                return False
            
            # Check PDF footer (should end with %%EOF)
            if not pdf_data.rstrip().endswith(b'%%EOF'):
                print(f"[ERROR] PDF Validation: Invalid PDF footer")
                return False
            
            # Try to parse with PyPDF2 (if available)
            try:
                import PyPDF2
                pdf_buffer.seek(0)
                reader = PyPDF2.PdfReader(pdf_buffer)
                
                # Check if we can read at least one page
                if len(reader.pages) == 0:
                    print(f"[ERROR] PDF Validation: No pages found")
                    return False
                    
                # Try to read first page content
                first_page = reader.pages[0]
                text = first_page.extract_text()
                
                print(f"[OK] PDF Validation: Valid PDF with {len(reader.pages)} pages")
                return True
                
            except ImportError:
                # PyPDF2 not available, use basic validation
                print(f"[WARNING] PDF Validation: PyPDF2 not available, using basic validation")
                
            # Reset buffer position for further use
            pdf_buffer.seek(0)
            
            print(f"[OK] PDF Validation: Basic validation passed ({len(pdf_data)} bytes)")
            return True
            
        except Exception as e:
            print(f"[ERROR] PDF Validation: Exception during validation - {str(e)}")
            return False


    def _generate_pl_with_validation(pdf_generator, user_data, export_data, data_type, tag_filter):
        """
        Generate P&L PDF with integrity validation to prevent FC deduction for corrupted PDFs.
        
        Args:
            pdf_generator: PDFGenerator instance
            user_data: User information dict
            export_data: Report data dict
            data_type: Report data type ('all' for P&L)
            tag_filter: Tag filter for report
            
        Returns:
            tuple: (pdf_buffer, is_valid)
        """
        try:
            # Generate PDF
            pdf_buffer = pdf_generator.generate_financial_report(user_data, export_data, data_type, tag_filter)
            
            # Validate PDF integrity
            is_valid = _validate_pdf_integrity(pdf_buffer)
            
            if not is_valid:
                print(f"[ERROR] P&L PDF Generation: Generated PDF failed validation")
                return pdf_buffer, False
                
            print(f"[OK] P&L PDF Generation: PDF generated and validated successfully")
            return pdf_buffer, True
            
        except Exception as e:
            print(f"[ERROR] P&L PDF Generation: Exception during generation - {str(e)}")
            return None, False


    print("DEBUG: About to define deduct_credits function")
    def deduct_credits(current_user, credit_cost, report_type, job_id=None):
        """
        Deduct credits from user account and log transaction
        CRITICAL: Also records FC consumption in business books (liability consumption)
        """
        user = mongo.db.users.find_one({'_id': current_user['_id']})
        current_balance = user.get('ficoreCreditBalance', 0.0)
        new_balance = current_balance - credit_cost
        
        # Update user balance
        mongo.db.users.update_one(
            {'_id': current_user['_id']},
            {'$set': {'ficoreCreditBalance': new_balance}}
        )
        
        # Log credit transaction
        credit_transaction = {
            'userId': current_user['_id'],
            'type': 'deduction',
            'amount': -credit_cost,
            'description': f'Report Export - {report_type.upper()}',
            'balanceBefore': current_balance,
            'balanceAfter': new_balance,
            'status': 'completed',
            'metadata': {
                'reportType': report_type,
                'reportJobId': job_id,  # Track job ID for refund purposes
                'exportFormat': 'pdf'
            },
            'createdAt': datetime.utcnow()
        }
        mongo.db.credit_transactions.insert_one(credit_transaction)
        
        # CRITICAL: Record FC consumption in business books (liability consumption)
        # EXCLUDE test accounts (including business account) from consuming services
        from utils.test_account_filter import is_test_account
        
        user_email = current_user.get('email', '')
        if not is_test_account(user_email):
            try:
                consumption_result = record_fc_consumption_revenue(
                    mongo=mongo,
                    user_id=current_user['_id'],
                    fc_amount=credit_cost,
                    description=f'Report Export - {report_type.upper()}',
                    service='report_export'
                )
                
                print(f'[OK] FC Consumption recorded: {credit_cost} FCs for {report_type} by {user_email}')
                
            except Exception as e:
                # Don't fail the deduction if consumption recording fails
                print(f'[WARNING] FC consumption recording failed (non-critical): {str(e)}')
        else:
            print(f'[INFO] Skipped FC consumption for test/business account: {user_email}')
        
        
        # CRITICAL: Record subscription consumption in business books (liability consumption)
        # This works alongside FC consumption for users with admin-granted subscriptions
        if not is_test_account(user_email):
            try:
                # Calculate subscription consumption based on credit cost
                # Convert FC credits to Naira: credit_cost FCs x N30/FC = Naira amount
                subscription_consumption_amount = credit_cost * 30.0  # FC to Naira conversion
                
                subscription_result = record_subscription_consumption_revenue(
                    mongo=mongo,
                    user_id=current_user['_id'],
                    consumption_amount=subscription_consumption_amount,
                    description=f'Report Export - {report_type.upper()}',
                    service='report_export'
                )
                
                if subscription_result and subscription_result.get('consumed_amount', 0) > 0:
                    print(f'[OK] Subscription consumption recorded: N{subscription_result["consumed_amount"]:,.2f} for {report_type} by {user_email}')
                else:
                    print(f'[INFO] No subscription liability to consume for {report_type} by {user_email}')
                
            except Exception as e:
                # Don't fail the deduction if consumption recording fails
                print(f'[WARNING] Subscription consumption recording failed (non-critical): {str(e)}')
        else:
            print(f'[INFO] Skipped subscription consumption for test/business account: {user_email}')
        
        return new_balance

    def log_export_event(current_user, report_type, export_format, success=True, error=None):
        """
        Log export event for analytics and auditing
        """
        try:
            export_log = {
                'userId': current_user['_id'],
                'userEmail': current_user.get('email'),
                'reportType': report_type,
                'exportFormat': export_format,
                'success': success,
                'error': error,
                'timestamp': datetime.utcnow(),
                'ipAddress': request.remote_addr,
                'userAgent': request.headers.get('User-Agent')
            }
            mongo.db.export_logs.insert_one(export_log)
        except Exception as e:
            # DISABLED FOR LIQUID WALLET FOCUS
            # print(f"Error logging export event: {str(e)}")
            pass


    def parse_date_range(request_data):
        """
        Parse start and end dates from request data
        Returns: (start_date, end_date)
        """
        start_date = None
        end_date = None
        
        if request_data.get('startDate'):
            try:
                start_date = datetime.fromisoformat(request_data['startDate'].replace('Z', ''))
            except:
                pass
        
        if request_data.get('endDate'):
            try:
                end_date = datetime.fromisoformat(request_data['endDate'].replace('Z', ''))
            except:
                pass
        
        return start_date, end_date


    def calculate_cash_bank_balance(user_id, end_date=None):
        """
        Calculate cash/bank balance as of a specific date
        NEW FORMULA (Mar 13, 2026): Opening Balance + Cash Adjustments ONLY
        
        CRITICAL CHANGE: Net income NO LONGER affects cash balance automatically.
        Cash only moves when real money comes in/out via manual adjustments.
        
        This prevents phantom cash from appearing in reports and maintains
        proper separation between profit (equity) and cash flow.
        
        Args:
            user_id: User ID
            end_date: Calculate balance as of this date (None = current/all time)
        
        Returns: float - Cash/bank balance
        """
        try:
            # Get user's opening balance
            user = mongo.db.users.find_one({'_id': user_id})
            opening_balance = user.get('openingCashBalance', 0.0) if user else 0.0
            
            # Build query for cash adjustments only
            adjustment_query = {
                'userId': user_id,
                'status': 'active',
                'isDeleted': False
            }
            
            # Apply date filter if provided
            if end_date:
                adjustment_query['date'] = {'$lte': end_date}
            
            # Get only cash-affecting adjustments (drawings, capital, asset purchases)
            drawing_amounts = []
            capital_amounts = []
            asset_amounts = []
            adjustment_cursor = mongo.db.cash_adjustments.find(adjustment_query)
            for adjustment in adjustment_cursor:
                adj_type = adjustment.get('type')
                amount = adjustment.get('amount', 0.0)
                
                if adj_type == 'drawing':
                    drawing_amounts.append(amount)
                elif adj_type == 'capital':
                    capital_amounts.append(amount)
                elif adj_type == 'asset_purchase':
                    asset_amounts.append(amount)
            
            total_drawings = safe_sum(drawing_amounts)
            total_capital = safe_sum(capital_amounts)
            total_asset_purchases = safe_sum(asset_amounts)
            
            # NEW FORMULA: Only cash movements affect cash balance
            # Net income affects equity, not cash
            current_balance = round(
                opening_balance 
                - total_drawings 
                + total_capital
                - total_asset_purchases,
                2
            )
            
            return current_balance
        except Exception as e:
            print(f'Error calculating cash/bank balance: {str(e)}')
            return 0.0

    def get_last_transaction_timestamp(user_id):
        """
        Get the most recent transaction timestamp for cache invalidation.
        
        CACHE INVALIDATION: When a user adds/edits any transaction, this timestamp
        changes, which invalidates all cached PDFs automatically.
        
        Returns: ISO timestamp string of most recent transaction, or None
        """
        try:
            # Check all transaction collections for most recent updatedAt
            collections_and_fields = [
                ('incomes', 'updatedAt'),
                ('expenses', 'updatedAt'),
                ('assets', 'updatedAt'),
                ('debtors', 'updatedAt'),
                ('creditors', 'updatedAt'),
            ]
            
            latest_timestamp = None
            
            for collection_name, field_name in collections_and_fields:
                # Get most recent document from this collection
                result = mongo.db[collection_name].find_one(
                    {'userId': user_id},
                    {field_name: 1},
                    sort=[(field_name, -1)]
                )
                
                if result and result.get(field_name):
                    timestamp = result[field_name]
                    if latest_timestamp is None or timestamp > latest_timestamp:
                        latest_timestamp = timestamp
            
            # Return as ISO string for cache key
            return latest_timestamp.isoformat() if latest_timestamp else None
            
        except Exception as e:
            # If we can't get timestamp, return current time to be safe (no caching)
            print(f"[WARNING] Error getting last transaction timestamp: {e}")
            return datetime.utcnow().isoformat()


    def filter_by_date_range(items, date_field, start_date, end_date):
        """
        Filter items by date range
        """
        if not start_date and not end_date:
            return items
        
        filtered = []
        for item in items:
            item_date = item.get(date_field)
            if not item_date:
                continue
            
            if isinstance(item_date, str):
                try:
                    item_date = datetime.fromisoformat(item_date.replace('Z', ''))
                except:
                    continue
            
            if start_date and item_date < start_date:
                continue
            if end_date and item_date > end_date:
                continue
            
            filtered.append(item)
        
        return filtered
    
    # ============================================================================
    # PDF INTEGRITY & REFUND ENDPOINTS
    # ============================================================================
    
    @reports_bp.route('/validate-pdf/<job_id>', methods=['GET'])
    @token_required
    def validate_pdf_integrity(current_user, job_id):
        """Validate PDF integrity for a specific job"""
        try:
            bg_generator = get_background_generator(mongo.db)
            
            # Get job details
            job = bg_generator.get_job(job_id)
            if not job or job.get('user_id') != current_user['_id']:
                return jsonify({
                    'success': False,
                    'message': 'Job not found or access denied'
                }), 404
            
            # Check if file exists
            if job.get('status') != 'completed' or not job.get('file_id'):
                return jsonify({
                    'success': False,
                    'message': 'PDF not ready or job not completed'
                }), 400
            
            # Get file from GridFS
            file_buffer = bg_generator.get_file(job['file_id'])
            if not file_buffer:
                return jsonify({
                    'success': False,
                    'message': 'PDF file not found',
                    'is_corrupted': True
                }), 404
            
            # Validate PDF
            is_valid = _validate_pdf_integrity(file_buffer)
            
            return jsonify({
                'success': True,
                'is_valid': is_valid,
                'is_corrupted': not is_valid,
                'job_id': job_id,
                'file_size': len(file_buffer.getvalue()) if file_buffer else 0
            })
            
        except Exception as e:
            print(f"[ERROR] PDF Validation Error: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Error validating PDF',
                'is_corrupted': True
            }), 500
    
    # ============================================================================
    # INCOME REPORTS
    # ============================================================================
    
    print("DEBUG: About to define first route")
    @reports_bp.route('/income-pdf', methods=['POST'])
    @token_required
    def export_income_pdf(current_user):
        """Export income records as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'income_pdf'
            
            # CRITICAL: Get tag filter from request
            tag_filter = request_data.get('tagFilter', 'all').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            
            # OPTIMIZATION: Check PDF cache first (instant delivery for duplicate requests)
            # CACHE INVALIDATION: Include last_updated to auto-invalidate when user adds/edits transactions
            last_updated = get_last_transaction_timestamp(current_user['_id'])
            
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'tag_filter': tag_filter if 'tag_filter' in locals() else 'all',
            'last_updated': last_updated  # Auto-invalidates cache when data changes
            }
            
            cached_pdf = pdf_cache.get(current_user['_id'], report_type, cache_params)
            if cached_pdf:
                # Deduct credits even for cached PDFs (user still gets the report)
                if not is_premium and credit_cost > 0:
                    deduct_credits(current_user, credit_cost, report_type)
                
                log_export_event(current_user, report_type, 'pdf', success=True)
                
                return send_file(
                    cached_pdf,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=f'ficore_{report_type}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
                )
            
# SECURITY FIX: Use secure query that excludes business data
            additional_filters = {}
            
            # Apply tag filtering
            if tag_filter == 'business':
                additional_filters['tags'] = 'Business'
            elif tag_filter == 'personal':
                additional_filters['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                additional_filters['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
            
            # Apply date filtering
            if start_date or end_date:
                additional_filters['date'] = {}
                if start_date:
                    additional_filters['date']['$gte'] = start_date
                if end_date:
                    additional_filters['date']['$lte'] = end_date
            
            # Create secure query that excludes business data
            query = create_user_query(current_user['_id'], additional_filters)
            
            incomes = list(mongo.db.incomes.find(query, PDF_PROJECTIONS['incomes']).sort('date', -1))
            
            # Check data size - recommend background generation for large reports
            if len(incomes) > 100:
                return jsonify({
                    'success': False,
                    'message': 'This report is too large to generate instantly. Please use the background generation option.',
                    'recommendation': 'Use background generation for better performance with large reports',
                    'recordCount': len(incomes),
                    'backgroundEndpoint': '/api/reports/income-pdf-async'
                }), 413  # Payload Too Large
            
            if not incomes:
                return jsonify({
                    'success': False,
                    'message': 'No income records found for the selected period'
                }), 404
            
            # Prepare user data with business name
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', ''),
                'businessName': user.get('businessName', '') if user else '',
            'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
            }
            
            # Prepare export data
            export_data = {
                'incomes': []
            }
            
            for income in incomes:
                export_data['incomes'].append({
                    'source': income.get('source', ''),
                    'amount': income.get('amount', 0),
                    'date': income.get('date', datetime.utcnow()).isoformat() + 'Z'
                })
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_financial_report(user_data, export_data, 'incomes', tag_filter)
            
            # AUDIT SHIELD: Track export for version history (Feb 7, 2026)
            # This enables "Report Discrepancy" warnings when entries are edited after export
            try:
                from utils.immutable_ledger_helper import track_export
                
                entry_ids = [str(income['_id']) for income in incomes]
                report_id = f"income_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                report_name = f"Income Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
                
                track_export(
                    db=mongo.db,
                    collection_name='incomes',
                    entry_ids=entry_ids,
                    report_id=report_id,
                    report_name=report_name,
                    export_type='income_report'
                )
            except Exception as e:
                # Don't fail export if tracking fails
                print(f"[WARNING] Export tracking failed (non-critical): {e}")
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            
            # Cache the generated PDF for future requests
            pdf_cache.set(current_user['_id'], report_type, cache_params, pdf_buffer)
            
# Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_income_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'income_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate income PDF: {str(e)}'
            }), 500
    
    @reports_bp.route('/income-pdf-async', methods=['POST'])
    @token_required
    def export_income_pdf_async(current_user):
        """
        Generate PDF report in the background.
        Returns immediately with a job ID that can be used to check progress.
        """
        try:
            request_data = request.get_json() or {}
            report_type = 'income_pdf'
            
            # CRITICAL: Get tag filter from request
            tag_filter = request_data.get('tagFilter', 'all').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check user access (fast)
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse parameters
            start_date, end_date = parse_date_range(request_data)
            
            # Create background job (fast - just inserts to MongoDB)
            bg_generator = get_background_generator(mongo.db)
            job_id = bg_generator.create_job(
                user_id=current_user['_id'],
                report_type=report_type,
                report_format='pdf',
                params={
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None,
                    'tag_filter': tag_filter
                }
            )
            
            # Define the generation function (this will run in background)
            def generate_income_pdf():
                # SECURITY FIX: Use secure query that excludes business data
                additional_filters = {}
                
                # Apply tag filtering
                if tag_filter == 'business':
                    additional_filters['tags'] = 'Business'
                elif tag_filter == 'personal':
                    additional_filters['tags'] = 'Personal'
                elif tag_filter == 'untagged':
                    additional_filters['$or'] = [
                        {'entryType': {'$exists': False}},
                        {'entryType': {'$size': 0}},
                        {'entryType': None}
                    ]
                
                # Apply date filtering
                if start_date or end_date:
                    additional_filters['date'] = {}
                    if start_date:
                        additional_filters['date']['$gte'] = start_date
                    if end_date:
                        additional_filters['date']['$lte'] = end_date
                
                # Create secure query that excludes business data
                query = create_user_query(current_user['_id'], additional_filters)
                
                # Fetch data
                incomes = list(mongo.db.incomes.find(query, PDF_PROJECTIONS['incomes']).sort('date', -1))
                
                # Prepare user data
                user = mongo.db.users.find_one({'_id': current_user['_id']})
                user_data = {
                    'firstName': current_user.get('firstName', ''),
                    'lastName': current_user.get('lastName', ''),
                    'email': current_user.get('email', ''),
                    'businessName': user.get('businessName', '') if user else '',
                    'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
                }
                
                # Prepare export data
                export_data = {'incomes': []}
                for income in incomes:
                    export_data['incomes'].append({
                        'source': income.get('source', ''),
                        'amount': income.get('amount', 0),
                        'date': income.get('date', datetime.utcnow()).isoformat() + 'Z'
                    })
                
                # Generate PDF
                pdf_generator = PDFGenerator()
                pdf_buffer = pdf_generator.generate_financial_report(user_data, export_data, 'incomes', tag_filter)
                
                # Track export for audit
                try:
                    from utils.immutable_ledger_helper import track_export
                    entry_ids = [str(income['_id']) for income in incomes]
                    report_id = f"income_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                    report_name = f"Income Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
                    track_export(
                        db=mongo.db,
                        collection_name='incomes',
                        entry_ids=entry_ids,
                        report_id=report_id,
                        report_name=report_name,
                        export_type='income_report'
                    )
                except Exception as e:
                    print(f"[WARNING] Export tracking failed (non-critical): {e}")
                
                return pdf_buffer
            
            # Define wrapper function that deducts credits ONLY on success
            def generate_and_deduct_on_success():
                try:
                    # Generate PDF
                    pdf_buffer = generate_income_pdf()
                    
                    # ONLY deduct credits if generation succeeded
                    if not is_premium and credit_cost > 0:
                        print(f"[INFO] INCOME PDF: Generated successfully, deducting {credit_cost} credits...")
                        deduct_credits(current_user, credit_cost, report_type)
                        print(f"[OK] INCOME PDF: Credits deducted after successful generation")
                    
                    # Log export event
                    log_export_event(current_user, report_type, 'pdf', success=True)
                    
                    return pdf_buffer
                except Exception as e:
                    # DO NOT deduct credits on failure
                    print(f"[ERROR] INCOME PDF: Generation failed, credits NOT deducted")
                    log_export_event(current_user, report_type, 'pdf', success=False)
                    raise
            
            # Start background generation with wrapper (non-blocking)
            bg_generator.start_generation(job_id, generate_and_deduct_on_success)
            
            # Return job_id immediately (user doesn't wait!)
            return jsonify({
                'success': True,
                'message': 'Your report is being prepared. We\'ll have it ready in a few minutes.',
                'jobId': job_id,
                'statusUrl': f'/api/reports/job-status/{job_id}',
                'estimatedTime': '2-5 minutes'
            }), 202  # 202 Accepted
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Unable to start preparing your report: {str(e)}'
            }), 500
    
    @reports_bp.route('/income-csv', methods=['POST'])
    @token_required
    def export_income_csv(current_user):
        """Export income records as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'income_csv'
            
            # CRITICAL: Get tag filter from request
            tag_filter = request_data.get('tagFilter', 'all').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # SECURITY FIX: Use secure query that excludes business data
            additional_filters = {}
            
            # Apply tag filtering
            if tag_filter == 'business':
                additional_filters['tags'] = 'Business'
            elif tag_filter == 'personal':
                additional_filters['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                additional_filters['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
            
            # Apply date filtering
            if start_date or end_date:
                additional_filters['date'] = {}
                if start_date:
                    additional_filters['date']['$gte'] = start_date
                if end_date:
                    additional_filters['date']['$lte'] = end_date
            
            # Create secure query that excludes business data
            query = create_user_query(current_user['_id'], additional_filters)
            
            incomes = list(mongo.db.incomes.find(query, PDF_PROJECTIONS['incomes']).sort('date', -1))
            
            if not incomes:
                return jsonify({
                    'success': False,
                    'message': 'No income records found for the selected period'
                }), 404
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Date', 'Source', 'Category', 'Amount (N)', 'Description', 'Source Type', 'Entry Type', 'Verified'])
            
            # Write data
            total_amount = 0
            for income in incomes:
                date_str = income.get('date', datetime.utcnow()).strftime('%Y-%m-%d')
                source = income.get('source', '')
                category = income.get('category', {}).get('name', 'Other')
                amount = income.get('amount', 0)
                description = income.get('description', '')
                source_type = income.get('sourceType', 'manual')
                entry_type = income.get('entryType', 'untagged')
                verified = 'Yes' if source_type != 'manual' else 'No'
                
                writer.writerow([date_str, source, category, f'{amount:,.2f}', description, source_type, entry_type, verified])
                total_amount += safe_float(amount)
            
            # Write total
            total_amount = round(total_amount, 2)
            writer.writerow(['', '', 'TOTAL', f'{total_amount:,.2f}', ''])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_income_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'income_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate income CSV: {str(e)}'
            }), 500
    
    # ============================================================================
    # EXPENSE REPORTS
    # ============================================================================
    
    @reports_bp.route('/expense-pdf', methods=['POST'])
    @token_required
    def export_expense_pdf(current_user):
        """Export expense records as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'expense_pdf'
            
            # CRITICAL: Get tag filter from request
            tag_filter = request_data.get('tagFilter', 'all').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            
            # OPTIMIZATION: Check PDF cache first (instant delivery for duplicate requests)
            # CACHE INVALIDATION: Include last_updated to auto-invalidate when user adds/edits transactions
            last_updated = get_last_transaction_timestamp(current_user['_id'])
            
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'tag_filter': tag_filter if 'tag_filter' in locals() else 'all',
            'last_updated': last_updated  # Auto-invalidates cache when data changes
            }
            
            cached_pdf = pdf_cache.get(current_user['_id'], report_type, cache_params)
            if cached_pdf:
                # Deduct credits even for cached PDFs (user still gets the report)
                if not is_premium and credit_cost > 0:
                    deduct_credits(current_user, credit_cost, report_type)
                
                log_export_event(current_user, report_type, 'pdf', success=True)
                
                return send_file(
                    cached_pdf,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=f'ficore_{report_type}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
                )
            
# SECURITY FIX: Use secure query that excludes business data
            additional_filters = {}
            
            # Apply tag filtering
            if tag_filter == 'business':
                additional_filters['tags'] = 'Business'
            elif tag_filter == 'personal':
                additional_filters['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                additional_filters['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
            
            # Apply date filtering
            if start_date or end_date:
                additional_filters['date'] = {}
                if start_date:
                    additional_filters['date']['$gte'] = start_date
                if end_date:
                    additional_filters['date']['$lte'] = end_date
            
            # Create secure query that excludes business data
            query = create_user_query(current_user['_id'], additional_filters)
            
            expenses = list(mongo.db.expenses.find(query, PDF_PROJECTIONS['expenses']).sort('date', -1))
            
            if not expenses:
                return jsonify({
                    'success': False,
                    'message': 'No expense records found for the selected period'
                }), 404
            
            # Prepare user data with business name
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', ''),
                'businessName': user.get('businessName', '') if user else '',
            'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
            }
            
            # Prepare export data
            export_data = {
                'expenses': []
            }
            
            for expense in expenses:
                export_data['expenses'].append({
                    'id': str(expense['_id']),
                    'title': expense.get('title', ''),
                    'amount': expense.get('amount', 0),
                    'category': expense.get('category', 'Other'),
                    'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                    'description': expense.get('description', '')
                })
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_financial_report(user_data, export_data, 'expenses', tag_filter)
            
            # AUDIT SHIELD: Track export for version history (Feb 7, 2026)
            # This enables "Report Discrepancy" warnings when entries are edited after export
            try:
                from utils.immutable_ledger_helper import track_export
                
                entry_ids = [str(expense['_id']) for expense in expenses]
                report_id = f"expense_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                report_name = f"Expense Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
                
                track_export(
                    db=mongo.db,
                    collection_name='expenses',
                    entry_ids=entry_ids,
                    report_id=report_id,
                    report_name=report_name,
                    export_type='expense_report'
                )
            except Exception as e:
                # Don't fail export if tracking fails
                print(f"[WARNING] Export tracking failed (non-critical): {e}")
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            
            # Cache the generated PDF for future requests
            pdf_cache.set(current_user['_id'], report_type, cache_params, pdf_buffer)
            
# Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_expense_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'expense_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate expense PDF: {str(e)}'
            }), 500
    
    @reports_bp.route('/expense-pdf-async', methods=['POST'])
    @token_required
    def export_expense_pdf_async(current_user):
        """Generate Expense PDF in background"""
        try:
            request_data = request.get_json() or {}
            report_type = 'expense_pdf'
            
            # Get tag filter
            tag_filter = request_data.get('tagFilter', 'all').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check credits (fast)
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse parameters
            start_date, end_date = parse_date_range(request_data)
            
            # Create background job
            bg_generator = get_background_generator(mongo.db)
            job_id = bg_generator.create_job(
                user_id=current_user['_id'],
                report_type=report_type,
                report_format='pdf',
                params={
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None,
                    'tag_filter': tag_filter
                }
            )
            
            # Define generation function
            def generate_expense_pdf():
                # SECURITY FIX: Use secure query that excludes business data
                additional_filters = {}
                
                # Apply tag filtering
                if tag_filter == 'business':
                    additional_filters['tags'] = 'Business'
                elif tag_filter == 'personal':
                    additional_filters['tags'] = 'Personal'
                elif tag_filter == 'untagged':
                    additional_filters['$or'] = [
                        {'entryType': {'$exists': False}},
                        {'entryType': {'$size': 0}},
                        {'entryType': None}
                    ]
                
                # Apply date filtering
                if start_date or end_date:
                    additional_filters['date'] = {}
                    if start_date:
                        additional_filters['date']['$gte'] = start_date
                    if end_date:
                        additional_filters['date']['$lte'] = end_date
                
                # Create secure query that excludes business data
                query = create_user_query(current_user['_id'], additional_filters)
                
                # Fetch data
                expenses = list(mongo.db.expenses.find(query, PDF_PROJECTIONS['expenses']).sort('date', -1))
                
                # Prepare user data
                user = mongo.db.users.find_one({'_id': current_user['_id']})
                user_data = {
                    'firstName': current_user.get('firstName', ''),
                    'lastName': current_user.get('lastName', ''),
                    'email': current_user.get('email', ''),
                    'businessName': user.get('businessName', '') if user else '',
                    'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
                }
                
                # Prepare export data
                export_data = {'expenses': []}
                for expense in expenses:
                    export_data['expenses'].append({
                        'id': str(expense['_id']),
                        'title': expense.get('title', ''),
                        'amount': expense.get('amount', 0),
                        'category': expense.get('category', 'Other'),
                        'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                        'description': expense.get('description', '')
                    })
                
                # Generate PDF
                pdf_generator = PDFGenerator()
                pdf_buffer = pdf_generator.generate_financial_report(user_data, export_data, 'expenses', tag_filter)
                
                # Track export
                try:
                    from utils.immutable_ledger_helper import track_export
                    entry_ids = [str(expense['_id']) for expense in expenses]
                    report_id = f"expense_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                    report_name = f"Expense Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
                    track_export(
                        db=mongo.db,
                        collection_name='expenses',
                        entry_ids=entry_ids,
                        report_id=report_id,
                        report_name=report_name,
                        export_type='expense_report'
                    )
                except Exception as e:
                    print(f"[WARNING] Export tracking failed (non-critical): {e}")
                
                return pdf_buffer
            
            # Define wrapper function that deducts credits ONLY on success
            def generate_and_deduct_on_success():
                try:
                    # Generate PDF
                    pdf_buffer = generate_expense_pdf()
                    
                    # ONLY deduct credits if generation succeeded
                    if not is_premium and credit_cost > 0:
                        print(f"[INFO] EXPENSE PDF: Generated successfully, deducting {credit_cost} credits...")
                        deduct_credits(current_user, credit_cost, report_type)
                        print(f"[OK] EXPENSE PDF: Credits deducted after successful generation")
                    
                    # Log export event
                    log_export_event(current_user, report_type, 'pdf', success=True)
                    
                    return pdf_buffer
                except Exception as e:
                    # DO NOT deduct credits on failure
                    print(f"[ERROR] EXPENSE PDF: Generation failed, credits NOT deducted")
                    log_export_event(current_user, report_type, 'pdf', success=False)
                    raise
            
            # Start background generation with wrapper
            bg_generator.start_generation(job_id, generate_and_deduct_on_success)
            
            # Return job_id immediately
            return jsonify({
                'success': True,
                'message': 'Your report is being prepared. We\'ll have it ready in a few minutes.',
                'jobId': job_id,
                'statusUrl': f'/api/reports/job-status/{job_id}',
                'estimatedTime': '2-5 minutes'
            }), 202
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Unable to start preparing your report: {str(e)}'
            }), 500
    
    @reports_bp.route('/expense-csv', methods=['POST'])
    @token_required
    def export_expense_csv(current_user):
        """Export expense records as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'expense_csv'
            
            # CRITICAL: Get tag filter from request
            tag_filter = request_data.get('tagFilter', 'all').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # SECURITY FIX: Use secure query that excludes business data
            additional_filters = {}
            
            # Apply tag filtering
            if tag_filter == 'business':
                additional_filters['tags'] = 'Business'
            elif tag_filter == 'personal':
                additional_filters['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                additional_filters['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
            
            # Apply date filtering
            if start_date or end_date:
                additional_filters['date'] = {}
                if start_date:
                    additional_filters['date']['$gte'] = start_date
                if end_date:
                    additional_filters['date']['$lte'] = end_date
            
            # Create secure query that excludes business data
            query = create_user_query(current_user['_id'], additional_filters)
            
            expenses = list(mongo.db.expenses.find(query, PDF_PROJECTIONS['expenses']).sort('date', -1))
            
            if not expenses:
                return jsonify({
                    'success': False,
                    'message': 'No expense records found for the selected period'
                }), 404
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Date', 'Title', 'Category', 'Amount (N)', 'Description', 'Source Type', 'Entry Type', 'Verified'])
            
            # Write data
            total_amount = 0
            for expense in expenses:
                date_str = expense.get('date', datetime.utcnow()).strftime('%Y-%m-%d')
                title = expense.get('title', '')
                category = expense.get('category', 'Other')
                amount = expense.get('amount', 0)
                description = expense.get('description', '')
                source_type = expense.get('sourceType', 'manual')
                entry_type = expense.get('entryType', 'untagged')
                verified = 'Yes' if source_type != 'manual' else 'No'
                
                writer.writerow([date_str, title, category, f'{amount:,.2f}', description, source_type, entry_type, verified])
                total_amount += safe_float(amount)
            
            # Write total
            total_amount = round(total_amount, 2)
            writer.writerow(['', '', 'TOTAL', f'{total_amount:,.2f}', ''])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_expense_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'expense_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate expense CSV: {str(e)}'
            }), 500
    
    # ============================================================================
    # BUSINESS REPORTS
    # ============================================================================
    
    @reports_bp.route('/profit-loss-pdf', methods=['POST'])
    @token_required
    def export_profit_loss_pdf(current_user):
        """Export Profit & Loss statement as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'profit_loss_pdf'
            
            # CRITICAL: Get tag filter from request (default to 'all' for general P&L)
            # For tax-specific P&L, frontend should pass 'business'
            tag_filter = request_data.get('tagFilter', 'all').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'tag_filter': tag_filter
            }
            
            # Fetch income and expense data with tag filtering
            # MODERNIZATION (Feb 18, 2026): Exclude personal expenses
            # [OK] CRITICAL FIX (Mar 9, 2026): Exclude Capital Contributions and Capital Expenditures from P&L
            # SECURITY FIX: Use secure query that excludes business data
            income_additional_filters = {
                'excludeFromProfitLoss': {'$ne': True},  # [OK] Exclude capital contributions
                '$or': [
                    {'entryType': {'$ne': 'personal'}},  # Exclude personal
                    {'entryType': {'$exists': False}},   # Include untagged (legacy)
                    {'entryType': None}                   # Include null
                ]
            }
            expense_additional_filters = {
                'excludeFromProfitLoss': {'$ne': True},  # [OK] Exclude capital expenditures
                '$or': [
                    {'entryType': {'$ne': 'personal'}},  # Exclude personal
                    {'entryType': {'$exists': False}},   # Include untagged (legacy)
                    {'entryType': None}                   # Include null
                ]
            }
            
            # Apply legacy tag filtering (for backward compatibility)
            if tag_filter == 'business':
                income_additional_filters['entryType'] = 'business'
                expense_additional_filters['entryType'] = 'business'
            elif tag_filter == 'personal':
                # Override: If user explicitly requests personal, show personal
                income_additional_filters = {
                    'entryType': 'personal'
                }
                expense_additional_filters = {
                    'entryType': 'personal'
                }
            elif tag_filter == 'untagged':
                income_additional_filters['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
                expense_query['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
            
            if start_date or end_date:
                if start_date:
                    income_query['date'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('date', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            # OPTIMIZATION: Fetch incomes and expenses in parallel (2-3x faster)

            
            results = fetch_collections_parallel({

            
                'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),

            
                'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))

            
            }, max_workers=2)

            
            incomes = results['incomes']

            
            expenses = results['expenses']
            
            # Prepare user data with business name
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', ''),
                'businessName': user.get('businessName', '') if user else '',
                'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
            }
            
            # Prepare export data
            export_data = {
                'incomes': [],
                'expenses': []
            }
            
            for income in incomes:
                export_data['incomes'].append({
                    'source': income.get('source', ''),
                    'amount': income.get('amount', 0),
                    'date': income.get('date', datetime.utcnow()).isoformat() + 'Z'
                })
            
            for expense in expenses:
                export_data['expenses'].append({
                    'title': expense.get('title', ''),
                    'amount': expense.get('amount', 0),
                    'category': expense.get('category', 'Other'),
                    'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z'
                })
            
            # Generate PDF with validation
            pdf_generator = PDFGenerator()
            pdf_buffer, is_valid = _generate_pl_with_validation(pdf_generator, user_data, export_data, 'all', tag_filter)
            
            # Check if PDF is valid before deducting credits
            if not is_valid:
                return jsonify({
                    'success': False,
                    'message': 'Report generation failed - PDF corrupted. Please try again.',
                    'error_code': 'PDF_CORRUPTED'
                }), 500
            
            # AUDIT SHIELD: Track export for version history (Feb 7, 2026)
            # Track both incomes and expenses for P&L report
            try:
                from utils.immutable_ledger_helper import track_export
                
                report_id = f"profit_loss_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                report_name = f"Profit & Loss Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
                
                # Track incomes
                income_ids = [str(income['_id']) for income in incomes]
                if income_ids:
                    track_export(
                        db=mongo.db,
                        collection_name='incomes',
                        entry_ids=income_ids,
                        report_id=report_id,
                        report_name=report_name,
                        export_type='profit_loss_report'
                    )
                
                # Track expenses
                expense_ids = [str(expense['_id']) for expense in expenses]
                if expense_ids:
                    track_export(
                        db=mongo.db,
                        collection_name='expenses',
                        entry_ids=expense_ids,
                        report_id=report_id,
                        report_name=report_name,
                        export_type='profit_loss_report'
                    )
            except Exception as e:
                # Don't fail export if tracking fails
                print(f"[WARNING] Export tracking failed (non-critical): {e}")
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            
            # Cache the generated PDF for future requests
            pdf_cache.set(current_user['_id'], report_type, cache_params, pdf_buffer)
            
# Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_profit_loss_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'profit_loss_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Profit & Loss PDF: {str(e)}'
            }), 500
    
    @reports_bp.route('/profit-loss-pdf-async', methods=['POST'])
    @token_required
    def export_profit_loss_pdf_async(current_user):
        """Generate Profit & Loss PDF in background"""
        try:
            request_data = request.get_json() or {}
            report_type = 'profit_loss_pdf'
            
            # Get tag filter
            tag_filter = request_data.get('tagFilter', 'all').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check credits (fast)
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse parameters
            start_date, end_date = parse_date_range(request_data)
            
            # Create background job
            bg_generator = get_background_generator(mongo.db)
            job_id = bg_generator.create_job(
                user_id=current_user['_id'],
                report_type=report_type,
                report_format='pdf',
                params={
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None,
                    'tag_filter': tag_filter
                }
            )
            
            # Define generation function
            def generate_profit_loss_pdf():
                # Build queries
                # [OK] CRITICAL FIX (Mar 9, 2026): Exclude Capital Contributions and Capital Expenditures from P&L
                income_query = {
                    'userId': current_user['_id'],
                    'status': 'active',
                    'isDeleted': False,
                    'excludeFromProfitLoss': {'$ne': True},  # [OK] Exclude capital contributions
                    '$or': [
                        {'entryType': {'$ne': 'personal'}},
                        {'entryType': {'$exists': False}},
                        {'entryType': None}
                    ]
                }
                expense_query = {
                    'userId': current_user['_id'],
                    'status': 'active',
                    'isDeleted': False,
                    'excludeFromProfitLoss': {'$ne': True},  # [OK] Exclude capital expenditures
                    '$or': [
                        {'entryType': {'$ne': 'personal'}},
                        {'entryType': {'$exists': False}},
                        {'entryType': None}
                    ]
                }
                
                # Apply tag filtering
                if tag_filter == 'business':
                    income_query['entryType'] = 'business'
                    expense_query['entryType'] = 'business'
                elif tag_filter == 'personal':
                    income_query = {
                        'userId': current_user['_id'],
                        'status': 'active',
                        'isDeleted': False,
                        'entryType': 'personal'
                    }
                    expense_query = {
                        'userId': current_user['_id'],
                        'status': 'active',
                        'isDeleted': False,
                        'entryType': 'personal'
                    }
                elif tag_filter == 'untagged':
                    income_query['$or'] = [
                        {'entryType': {'$exists': False}},
                        {'entryType': {'$size': 0}},
                        {'entryType': None}
                    ]
                    expense_query['$or'] = [
                        {'entryType': {'$exists': False}},
                        {'entryType': {'$size': 0}},
                        {'entryType': None}
                    ]
                
                if start_date or end_date:
                    if start_date:
                        income_query['date'] = {'$gte': start_date}
                        expense_query['date'] = {'$gte': start_date}
                    if end_date:
                        income_query.setdefault('date', {})['$lte'] = end_date
                        expense_query.setdefault('date', {})['$lte'] = end_date
                
                # Fetch data in parallel (USER DATA ONLY - NO BUSINESS DATA)
                results = fetch_collections_parallel({
                    'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),
                    'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))
                }, max_workers=2)
                
                # Use only user transactions (NO business data mixing)
                incomes = results['incomes']
                expenses = results['expenses']
                
                # Prepare user data
                user = mongo.db.users.find_one({'_id': current_user['_id']})
                user_data = {
                    'firstName': current_user.get('firstName', ''),
                    'lastName': current_user.get('lastName', ''),
                    'email': current_user.get('email', ''),
                    'businessName': user.get('businessName', '') if user else '',
                    'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
                }
                
                # Prepare export data
                export_data = {'incomes': [], 'expenses': []}
                
                for income in incomes:
                    export_data['incomes'].append({
                        'source': income.get('source', ''),
                        'amount': income.get('amount', 0),
                        'date': income.get('date', datetime.utcnow()).isoformat() + 'Z'
                    })
                
                for expense in expenses:
                    export_data['expenses'].append({
                        'title': expense.get('title', ''),
                        'amount': expense.get('amount', 0),
                        'category': expense.get('category', 'Other'),
                        'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z'
                    })
                
                # Generate PDF with validation
                pdf_generator = PDFGenerator()
                pdf_buffer, is_valid = _generate_pl_with_validation(pdf_generator, user_data, export_data, 'all', tag_filter)
                
                # If PDF is corrupted, mark job as failed
                if not is_valid:
                    bg_generator._update_job(job_id, {
                        'status': ReportJobStatus.FAILED,
                        'error': 'PDF generation failed - corrupted output',
                        'progress': 0
                    })
                    return
                
                # Track export
                try:
                    from utils.immutable_ledger_helper import track_export
                    report_id = f"profit_loss_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                    report_name = f"Profit & Loss Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
                    
                    income_ids = [str(income['_id']) for income in incomes]
                    if income_ids:
                        track_export(mongo.db, 'incomes', income_ids, report_id, report_name, 'profit_loss_report')
                    
                    expense_ids = [str(expense['_id']) for expense in expenses]
                    if expense_ids:
                        track_export(mongo.db, 'expenses', expense_ids, report_id, report_name, 'profit_loss_report')
                except Exception as e:
                    print(f"[WARNING] Export tracking failed (non-critical): {e}")
                
                return pdf_buffer
            
            # Define wrapper function that deducts credits ONLY on success AND validation
            def generate_and_deduct_on_success():
                try:
                    # Generate PDF
                    pdf_buffer = generate_profit_loss_pdf()
                    
                    # CRITICAL: Validate PDF before deducting credits (double-check)
                    if not _validate_pdf_integrity(pdf_buffer):
                        raise Exception("Generated PDF is corrupted or invalid")
                    
                    # ONLY deduct credits if generation succeeded AND PDF is valid
                    if not is_premium and credit_cost > 0:
                        print(f"[INFO] P&L PDF: Generated and validated successfully, deducting {credit_cost} credits...")
                        deduct_credits(current_user, credit_cost, report_type, job_id)
                        print(f"[OK] P&L PDF: Credits deducted after successful generation and validation")
                    
                    # Log export event
                    log_export_event(current_user, report_type, 'pdf', success=True)
                    
                    return pdf_buffer
                except Exception as e:
                    # DO NOT deduct credits on failure OR invalid PDF
                    print(f"[ERROR] P&L PDF: Generation failed or PDF invalid, credits NOT deducted - Error: {str(e)}")
                    log_export_event(current_user, report_type, 'pdf', success=False)
                    raise
            
            # Start background generation with wrapper
            bg_generator.start_generation(job_id, generate_and_deduct_on_success)
            
            # Return job_id immediately
            return jsonify({
                'success': True,
                'message': 'Your report is being prepared. We\'ll have it ready in a few minutes.',
                'jobId': job_id,
                'statusUrl': f'/api/reports/job-status/{job_id}',
                'estimatedTime': '2-5 minutes'
            }), 202
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Unable to start preparing your report: {str(e)}'
            }), 500
    
    # ============================================================================
    # CASH FLOW REPORT
    # ============================================================================
    
    @reports_bp.route('/cash-flow-pdf', methods=['POST'])
    @token_required
    def export_cash_flow_pdf(current_user):
        """Export Cash Flow statement as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'cash_flow_pdf'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)

            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
            
            # Fetch income and expense data
            income_query = {'userId': current_user['_id']}
            expense_query = {'userId': current_user['_id']}
            
            if start_date or end_date:
                if start_date:
                    income_query['date'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('date', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            # OPTIMIZATION: Fetch incomes and expenses in parallel (2-3x faster)

            
            results = fetch_collections_parallel({

            
                'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),

            
                'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))

            
            }, max_workers=2)

            
            incomes = results['incomes']

            
            expenses = results['expenses']
            
            if not incomes and not expenses:
                return jsonify({
                    'success': False,
                    'message': 'No transactions found for the selected period'
                }), 404
            
            # Prepare user data with business name
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', ''),
                'businessName': user.get('businessName', '') if user else '',
            'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
            }
            
            # Prepare transaction data
            transactions = {
                'incomes': [],
                'expenses': []
            }
            
            for income in incomes:
                transactions['incomes'].append({
                    'amount': income.get('amount', 0),
                    'date': income.get('date', datetime.utcnow())
                })
            
            for expense in expenses:
                transactions['expenses'].append({
                    'amount': expense.get('amount', 0),
                    'date': expense.get('date', datetime.utcnow())
                })
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_cash_flow_report(user_data, transactions, start_date, end_date, tag_filter)
            
            # AUDIT SHIELD: Track export for version history (Feb 7, 2026)
            # Track both incomes and expenses for cash flow report
            try:
                from utils.immutable_ledger_helper import track_export
                
                report_id = f"cash_flow_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                report_name = f"Cash Flow Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
                
                # Track incomes
                income_ids = [str(income['_id']) for income in incomes]
                if income_ids:
                    track_export(
                        db=mongo.db,
                        collection_name='incomes',
                        entry_ids=income_ids,
                        report_id=report_id,
                        report_name=report_name,
                        export_type='cash_flow_report'
                    )
                
                # Track expenses
                expense_ids = [str(expense['_id']) for expense in expenses]
                if expense_ids:
                    track_export(
                        db=mongo.db,
                        collection_name='expenses',
                        entry_ids=expense_ids,
                        report_id=report_id,
                        report_name=report_name,
                        export_type='cash_flow_report'
                    )
            except Exception as e:
                # Don't fail export if tracking fails
                print(f"[WARNING] Export tracking failed (non-critical): {e}")
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            # Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_cash_flow_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'cash_flow_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Cash Flow PDF: {str(e)}'
            }), 500
    
    @reports_bp.route('/cash-flow-pdf-async', methods=['POST'])
    @token_required
    def export_cash_flow_pdf_async(current_user):
        """Generate Cash Flow PDF in background"""
        try:
            request_data = request.get_json() or {}
            report_type = 'cash_flow_pdf'
            
            # Check credits (fast)
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse parameters
            start_date, end_date = parse_date_range(request_data)
            
            # CRITICAL: Get tag filter from request
            tag_filter = request_data.get('tagFilter', 'all').lower()
            
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Create background job
            bg_generator = get_background_generator(mongo.db)
            job_id = bg_generator.create_job(
                user_id=current_user['_id'],
                report_type=report_type,
                report_format='pdf',
                params={
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None,
                    'tag_filter': tag_filter
                }
            )
            
            # Define generation function
            def generate_cash_flow_pdf():
                # Fetch income and expense data
                income_query = {'userId': current_user['_id']}
                expense_query = {'userId': current_user['_id']}
                
                if start_date or end_date:
                    if start_date:
                        income_query['date'] = {'$gte': start_date}
                        expense_query['date'] = {'$gte': start_date}
                    if end_date:
                        income_query.setdefault('date', {})['$lte'] = end_date
                        expense_query.setdefault('date', {})['$lte'] = end_date
                
                # Apply tag filtering
                if tag_filter == 'business':
                    income_query['entryType'] = 'business'
                    expense_query['entryType'] = 'business'
                elif tag_filter == 'personal':
                    income_query['entryType'] = 'personal'
                    expense_query['entryType'] = 'personal'
                elif tag_filter == 'untagged':
                    income_query['$or'] = [
                        {'entryType': {'$exists': False}},
                        {'entryType': None},
                        {'entryType': ''}
                    ]
                    expense_query['$or'] = [
                        {'entryType': {'$exists': False}},
                        {'entryType': None},
                        {'entryType': ''}
                    ]
                # 'all' requires no additional filtering
                
                # Fetch data in parallel
                results = fetch_collections_parallel({
                    'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),
                    'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))
                }, max_workers=2)
                
                incomes = results['incomes']
                expenses = results['expenses']
                
                # Prepare user data
                user = mongo.db.users.find_one({'_id': current_user['_id']})
                user_data = {
                    'firstName': current_user.get('firstName', ''),
                    'lastName': current_user.get('lastName', ''),
                    'email': current_user.get('email', ''),
                    'businessName': user.get('businessName', '') if user else '',
                    'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
                }
                
                # Prepare transaction data
                transactions = {
                    'incomes': [],
                    'expenses': []
                }
                
                for income in incomes:
                    transactions['incomes'].append({
                        'amount': income.get('amount', 0),
                        'date': income.get('date', datetime.utcnow())
                    })
                
                for expense in expenses:
                    transactions['expenses'].append({
                        'amount': expense.get('amount', 0),
                        'date': expense.get('date', datetime.utcnow())
                    })
                
                # Generate PDF
                pdf_generator = PDFGenerator()
                pdf_buffer = pdf_generator.generate_cash_flow_report(user_data, transactions, start_date, end_date, tag_filter)
                
                # Track export
                try:
                    from utils.immutable_ledger_helper import track_export
                    report_id = f"cash_flow_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                    report_name = f"Cash Flow Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
                    
                    income_ids = [str(income['_id']) for income in incomes]
                    if income_ids:
                        track_export(mongo.db, 'incomes', income_ids, report_id, report_name, 'cash_flow_report')
                    
                    expense_ids = [str(expense['_id']) for expense in expenses]
                    if expense_ids:
                        track_export(mongo.db, 'expenses', expense_ids, report_id, report_name, 'cash_flow_report')
                except Exception as e:
                    print(f"[WARNING] Export tracking failed (non-critical): {e}")
                
                return pdf_buffer
            
            # Define wrapper function that deducts credits ONLY on success
            def generate_and_deduct_on_success():
                try:
                    # Generate PDF
                    pdf_buffer = generate_cash_flow_pdf()
                    
                    # ONLY deduct credits if generation succeeded
                    if not is_premium and credit_cost > 0:
                        print(f"[INFO] CASH FLOW PDF: Generated successfully, deducting {credit_cost} credits...")
                        deduct_credits(current_user, credit_cost, report_type)
                        print(f"[OK] CASH FLOW PDF: Credits deducted after successful generation")
                    
                    # Log export event
                    log_export_event(current_user, report_type, 'pdf', success=True)
                    
                    return pdf_buffer
                except Exception as e:
                    # DO NOT deduct credits on failure
                    print(f"[ERROR] CASH FLOW PDF: Generation failed, credits NOT deducted")
                    log_export_event(current_user, report_type, 'pdf', success=False)
                    raise
            
            # Start background generation with wrapper
            bg_generator.start_generation(job_id, generate_and_deduct_on_success)
            
            # Return job_id immediately
            return jsonify({
                'success': True,
                'message': 'Your report is being prepared. We\'ll have it ready in a few minutes.',
                'jobId': job_id,
                'statusUrl': f'/api/reports/job-status/{job_id}',
                'estimatedTime': '2-5 minutes'
            }), 202
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Unable to start preparing your report: {str(e)}'
            }), 500
    
    # ============================================================================
    # TAX SUMMARY REPORT
    # ============================================================================
    
    @reports_bp.route('/tax-summary-pdf', methods=['POST'])
    @token_required
    def export_tax_summary_pdf(current_user):
        """Export Tax Summary as PDF (supports both PIT and CIT)"""
        try:
            request_data = request.get_json() or {}
            report_type = 'tax_summary_pdf'
            
            # Get tax type from request (default to PIT for individuals)
            tax_type = request_data.get('taxType', 'PIT').upper()
            if tax_type not in ['PIT', 'CIT']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tax type. Must be either PIT (Personal Income Tax) or CIT (Corporate Income Tax)'
                }), 400
            
            # CRITICAL: Get tag filter from request (default to 'business' for tax reports)
            # Options: 'business', 'personal', 'all', 'untagged'
            tag_filter = request_data.get('tagFilter', 'business').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # OPTIMIZATION: Define cache parameters for PDF caching
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'tag_filter': tag_filter,
                'tax_type': tax_type
            }
            
            # Fetch income and expense data for tax calculation
            # CRITICAL: Apply tag filtering for tax compliance
            # CRITICAL FIX (Mar 9, 2026): Exclude capital contributions/expenditures from P&L
            income_query = {
                'userId': current_user['_id'],
                'status': 'active',  # Only active entries
                'isDeleted': False,   # Exclude soft-deleted entries
                'excludeFromProfitLoss': {'$ne': True}  # Exclude capital contributions
            }
            expense_query = {
                'userId': current_user['_id'],
                'status': 'active',  # Only active entries
                'isDeleted': False,   # Exclude soft-deleted entries
                'excludeFromProfitLoss': {'$ne': True}  # Exclude capital expenditures
            }
            
            # Apply tag filtering based on user selection
            if tag_filter == 'business':
                # Only entries tagged as "Business"
                income_query['entryType'] = 'business'
                expense_query['entryType'] = 'business'
            elif tag_filter == 'personal':
                # Only entries tagged as "Personal"
                income_query['entryType'] = 'personal'
                expense_query['entryType'] = 'personal'
            elif tag_filter == 'untagged':
                # Only entries without any tags
                income_query['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
                expense_query['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
            # If 'all', no tag filtering applied
            
            if start_date or end_date:
                if start_date:
                    income_query['date'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('date', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            # OPTIMIZATION: Fetch incomes and expenses in parallel (2-3x faster)

            
            results = fetch_collections_parallel({

            
                'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),

            
                'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))

            
            }, max_workers=2)

            
            incomes = results['incomes']

            
            expenses = results['expenses']
            
            # Calculate totals
            total_income = sum(income.get('amount', 0) for income in incomes)
            total_expenses = sum(expense.get('amount', 0) for expense in expenses)
            
            # MODERNIZATION (Feb 25, 2026): Calculate 3-Step P&L (align with SOA)
            # CORRECTED REVENUE CLASSIFICATION (Mar 12, 2026):
            # Sales Revenue = What we actually sell/earn (VAS Commissions + Inventory Sales + Subscriptions + FC Purchases)
            # Other Income = Internal accounting (consumed promotional spends, grants, interest)
            
            # CRITICAL FIX (Mar 14, 2026): VAS commissions are in business books, not VAS transactions
            # Business reports should read VAS commissions from incomes.vas_commission entries
            # Treasury dashboard reads from vas_transactions, but business reports read from business books
            
            # Define what constitutes "Sales Revenue" (actual business revenue)
            # CORRECTED (Mar 14, 2026): Only include REAL revenue sources
            sales_revenue_sources = [
                'vas_commission',                    # VAS commission income (REAL revenue) ✅
                'deposit_fee',                       # Deposit fees (single source of truth) ✅
                'inventory_sale',                    # Inventory sales (when we have them) ✅
                # REMOVED: fc_purchase_revenue_recognition (fake test revenue)
                # REMOVED: subscription_purchase_revenue_recognition (fake test revenue)
            ]
            
            # Define what constitutes "Other Income" (internal accounting, not real external revenue)
            other_income_sources = [
                'fc_consumption',                    # Consumed promotional FC spends (internal) ✅
                'fee_waiver_consumption',           # Consumed promotional fee waivers (internal) ✅
                'subscription_consumption',         # Consumed promotional subscriptions (internal) ✅
                'manual',                          # Manual entries (could be grants, interest, etc.) ✅
                'voice',                           # Voice entries (could be grants, interest, etc.) ✅
            ]
            
            # Calculate Sales Revenue from incomes collection (including VAS commissions)
            sales_revenue = sum(
                inc.get('amount', 0) for inc in incomes 
                if inc.get('sourceType') in sales_revenue_sources
            )
            
            # Calculate Other Income (internal accounting, not real external revenue)
            other_income = sum(
                inc.get('amount', 0) for inc in incomes 
                if inc.get('sourceType') in other_income_sources
            )
            
            # Separate COGS from Operating Expenses
            # CORRECTED COGS CLASSIFICATION (Mar 12, 2026):
            # COGS = Direct costs of providing services (inventory COGS + gateway fees for VAS services)
            cogs_categories = ['Cost of Goods Sold', 'Payment Processing Fees']
            cogs_expenses = [exp for exp in expenses if exp.get('category') in cogs_categories]
            operating_expenses = [exp for exp in expenses if exp.get('category') not in cogs_categories]
            
            total_cogs = sum(exp.get('amount', 0) for exp in cogs_expenses)
            total_operating = sum(exp.get('amount', 0) for exp in operating_expenses)
            
            # Calculate 3-Step P&L
            gross_profit = (sales_revenue + other_income) - total_cogs
            gross_margin_pct = (gross_profit / (sales_revenue + other_income) * 100) if (sales_revenue + other_income) > 0 else 0
            operating_profit = gross_profit - total_operating
            net_income = operating_profit
            
            # Prepare user data
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', ''),
                'businessName': user.get('businessName', '') if user else '',
            'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
            }
            
            # Prepare comprehensive tax data
            tax_data = {
                # Revenue Breakdown (NEW - Feb 25, 2026)
                'sales_revenue': sales_revenue,
                'other_income': other_income,
                'total_income': total_income,
                
                # COGS (NEW - Feb 25, 2026)
                'cost_of_goods_sold': total_cogs,
                
                # Gross Profit (NEW - Feb 25, 2026)
                'gross_profit': gross_profit,
                'gross_margin_percentage': gross_margin_pct,
                
                # Operating Expenses (NEW - Feb 25, 2026)
                'operating_expenses': total_operating,
                
                # Operating Profit (NEW - Feb 25, 2026)
                'operating_profit': operating_profit,
                
                # Legacy fields (for backward compatibility)
                'deductible_expenses': total_expenses,
                
                'tag_filter': tag_filter,  # Include filter info in report
                'tag_filter_label': {
                    'business': 'Business Only',
                    'personal': 'Personal Only',
                    'all': 'All Entries',
                    'untagged': 'Untagged Only'
                }.get(tag_filter, 'All Entries')
            }
            
            # For CIT, add comprehensive business data for exemption check
            if tax_type == 'CIT':
                # Calculate annual turnover from incomes
                tax_data['annual_turnover'] = total_income
                
                # CRITICAL: Get FIXED ASSETS NET BOOK VALUE for CIT exemption check
                # CIT Exemption Criteria: Turnover < N100M AND Fixed Assets NBV < N250M
                # Fixed Assets NBV = Original Cost - Accumulated Depreciation
                
                assets_query = {'userId': current_user['_id']}
                # Note: For CIT exemption, we consider ALL fixed assets owned, not just those purchased in period
                # Remove date filtering for exemption calculation
                
                assets = list(mongo.db.assets.find(assets_query, PDF_PROJECTIONS['assets']))
                
                # Calculate Net Book Value for each asset
                # Use datetime from module-level import (line 6)
                nigerian_time = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=1)))
                
                fixed_assets_nbv = 0  # Net Book Value for exemption check
                fixed_assets_original_cost = 0  # Original cost for display
                
                for asset in assets:
                    original_cost = asset.get('purchaseCost', 0)
                    fixed_assets_original_cost += original_cost
                    
                    # Calculate depreciation using straight-line method
                    useful_life = asset.get('usefulLife', 5)  # Default 5 years
                    purchase_date_raw = asset.get('purchaseDate')
                    
                    # Safe date parsing
                    if isinstance(purchase_date_raw, datetime):
                        purchase_date = purchase_date_raw
                    elif isinstance(purchase_date_raw, str):
                        try:
                            purchase_date = datetime.fromisoformat(purchase_date_raw.replace('Z', ''))
                        except:
                            purchase_date = nigerian_time
                    else:
                        purchase_date = nigerian_time
                    
                    # Calculate years owned
                    years_owned = (nigerian_time.replace(tzinfo=None) - purchase_date.replace(tzinfo=None)).days / 365.25
                    
                    # Calculate accumulated depreciation
                    annual_depreciation = original_cost / useful_life if useful_life > 0 else 0
                    accumulated_depreciation = min(annual_depreciation * years_owned, original_cost)
                    
                    # Net Book Value = Original Cost - Accumulated Depreciation
                    net_book_value = original_cost - accumulated_depreciation
                    fixed_assets_nbv += net_book_value
                
                # Store BOTH values: NBV for exemption, original cost for display
                tax_data['fixed_assets_nbv'] = fixed_assets_nbv  # For exemption check (< N250M)
                tax_data['fixed_assets_original_cost'] = fixed_assets_original_cost  # For display
                tax_data['assets_count'] = len(assets)
                
                # Add inventory value (for balance sheet display, NOT for exemption)
                inventory = list(mongo.db.inventory.find({'userId': current_user['_id']}))
                inventory_value = sum(item.get('quantity', 0) * item.get('unitCost', 0) for item in inventory)
                tax_data['inventory_value'] = inventory_value
                
                # Add debtors (accounts receivable - for balance sheet display, NOT for exemption)
                debtors = list(mongo.db.debtors.find({'userId': current_user['_id'], 'status': {'$ne': 'paid'}}))
                debtors_value = sum(debtor.get('amount', 0) for debtor in debtors)
                tax_data['debtors_value'] = debtors_value
                
                # Add creditors (accounts payable - for balance sheet display, NOT for exemption)
                creditors = list(mongo.db.creditors.find({'userId': current_user['_id'], 'status': {'$ne': 'paid'}}))
                creditors_value = sum(creditor.get('amount', 0) for creditor in creditors)
                tax_data['creditors_value'] = creditors_value
                
            else:
                # For PIT, add statutory deductions and reliefs
                # These reduce taxable income
                
                # IMPORTANT: PIT Deduction Category Dependencies
                # The following deductions rely on specific expense categories being used by users.
                # The UI/Frontend team MUST ensure these categories are available and clearly 
                # presented in the expense tracking interface for these deductions to work.
                #
                # Required Categories:
                # - Rent: "rent", "housing", "accommodation"
                # - Pension: "pension", "retirement"
                # - Life Insurance: "insurance", "life insurance"
                # - NHIS: "nhis", "health insurance"
                # - HMO: "hmo", "health maintenance"
                
                # ASSUMPTION: The following deductions are currently treated as "fully deductible"
                # based on current Nigerian tax law (as of 2025). However, tax laws can change
                # or have nuanced conditions. This implementation should be reviewed and updated
                # if future tax law changes introduce caps or specific conditions for these deductions.
                
                # 1. Rent Relief (20% of annual rent, capped at N500,000)
                # Category dependency: "rent", "housing", "accommodation"
                # PHASE 5: Flexible keyword matching for frontend category compatibility
                rent_keywords = ['rent', 'housing', 'accommodation']
                rent_expenses = [exp for exp in expenses 
                                if any(keyword in exp.get('category', '').lower() 
                                       for keyword in rent_keywords)]
                annual_rent = sum(exp.get('amount', 0) for exp in rent_expenses)
                rent_relief = min(annual_rent * 0.20, 500000)  # 20% capped at N500k
                
                # 2. Pension Contributions (currently fully deductible)
                # Category dependency: "pension", "retirement"
                # PHASE 5: Flexible keyword matching for frontend category compatibility
                pension_keywords = ['pension', 'retirement']
                pension_expenses = [exp for exp in expenses 
                                   if any(keyword in exp.get('category', '').lower() 
                                          for keyword in pension_keywords)]
                pension_contributions = sum(exp.get('amount', 0) for exp in pension_expenses)
                
                # 3. Life Insurance Premiums (currently fully deductible)
                # Category dependency: "insurance", "life insurance"
                # PHASE 5: Flexible keyword matching for frontend category compatibility
                insurance_keywords = ['insurance', 'life insurance']
                insurance_expenses = [exp for exp in expenses 
                                     if any(keyword in exp.get('category', '').lower() 
                                            for keyword in insurance_keywords)]
                life_insurance = sum(exp.get('amount', 0) for exp in insurance_expenses)
                
                # 4. NHIS (National Health Insurance Scheme) contributions (currently fully deductible)
                # Category dependency: "nhis", "health insurance"
                # PHASE 5: Flexible keyword matching for frontend category compatibility
                nhis_keywords = ['nhis', 'health insurance']
                nhis_expenses = [exp for exp in expenses 
                                if any(keyword in exp.get('category', '').lower() 
                                       for keyword in nhis_keywords)]
                nhis_contributions = sum(exp.get('amount', 0) for exp in nhis_expenses)
                
                # 5. HMO (Health Maintenance Organization) premiums (currently fully deductible)
                # Category dependency: "hmo", "health maintenance"
                # PHASE 5: Flexible keyword matching for frontend category compatibility
                hmo_keywords = ['hmo', 'health maintenance']
                hmo_expenses = [exp for exp in expenses 
                               if any(keyword in exp.get('category', '').lower() 
                                      for keyword in hmo_keywords)]
                hmo_premiums = sum(exp.get('amount', 0) for exp in hmo_expenses)
                
                # Aggregate all statutory deductions
                total_statutory_deductions = (
                    rent_relief + 
                    pension_contributions + 
                    life_insurance + 
                    nhis_contributions + 
                    hmo_premiums
                )
                
                # Store detailed breakdown
                tax_data['statutory_deductions'] = {
                    'rent_relief': {
                        'annual_rent': annual_rent,
                        'relief_amount': rent_relief,
                        'calculation': f"20% of N{annual_rent:,.2f}, capped at N500,000"
                    },
                    'pension_contributions': pension_contributions,
                    'life_insurance': life_insurance,
                    'nhis_contributions': nhis_contributions,
                    'hmo_premiums': hmo_premiums,
                    'total': total_statutory_deductions
                }
                
                # Adjust deductible expenses to include statutory deductions
                tax_data['deductible_expenses'] = total_expenses + total_statutory_deductions
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_tax_summary_report(user_data, tax_data, start_date, end_date, tax_type, tag_filter)
            
            # AUDIT SHIELD: Track export for version history (Feb 7, 2026)
            # CRITICAL: Tax reports are the most important for audit trail
            # Track both incomes and expenses with tax_report type
            try:
                from utils.immutable_ledger_helper import track_export
                
                report_id = f"tax_summary_{tax_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                report_name = f"Tax Summary Report ({tax_type}) - {datetime.utcnow().strftime('%Y-%m-%d')}"
                
                # Track incomes
                income_ids = [str(income['_id']) for income in incomes]
                if income_ids:
                    track_export(
                        db=mongo.db,
                        collection_name='incomes',
                        entry_ids=income_ids,
                        report_id=report_id,
                        report_name=report_name,
                        export_type='tax_report'  # CRITICAL: tax_report type for highest priority
                    )
                
                # Track expenses
                expense_ids = [str(expense['_id']) for expense in expenses]
                if expense_ids:
                    track_export(
                        db=mongo.db,
                        collection_name='expenses',
                        entry_ids=expense_ids,
                        report_id=report_id,
                        report_name=report_name,
                        export_type='tax_report'  # CRITICAL: tax_report type for highest priority
                    )
            except Exception as e:
                # Don't fail export if tracking fails
                print(f"[WARNING] Export tracking failed (non-critical): {e}")
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            
            # Cache the generated PDF for future requests
            pdf_cache.set(current_user['_id'], report_type, cache_params, pdf_buffer)
            
# Return PDF file
            tax_type_label = 'PIT' if tax_type == 'PIT' else 'CIT'
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_tax_summary_{tax_type_label}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'tax_summary_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Tax Summary PDF: {str(e)}'
            }), 500
    
    @reports_bp.route('/tax-summary-pdf-async', methods=['POST'])
    @token_required
    def export_tax_summary_pdf_async(current_user):
        """Generate Tax Summary PDF in background"""
        try:
            request_data = request.get_json() or {}
            report_type = 'tax_summary_pdf'
            
            # Get tax type and tag filter
            tax_type = request_data.get('taxType', 'PIT').upper()
            if tax_type not in ['PIT', 'CIT']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tax type. Must be either PIT or CIT'
                }), 400
            
            tag_filter = request_data.get('tagFilter', 'business').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter'
                }), 400
            
            # Check credits (fast)
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse parameters
            start_date, end_date = parse_date_range(request_data)
            
            # Create background job
            bg_generator = get_background_generator(mongo.db)
            job_id = bg_generator.create_job(
                user_id=current_user['_id'],
                report_type=report_type,
                report_format='pdf',
                params={
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None,
                    'tag_filter': tag_filter,
                    'tax_type': tax_type
                }
            )
            
            # Define generation function
            def generate_tax_summary_pdf():
                # Build queries with tag filtering
                # CRITICAL FIX (Feb 26, 2026): Use 'entryType' not 'tags'
                # CRITICAL FIX (Mar 9, 2026): Exclude capital contributions/expenditures from P&L
                income_query = {
                    'userId': current_user['_id'],
                    'status': 'active',
                    'isDeleted': False,
                    'excludeFromProfitLoss': {'$ne': True}
                }
                expense_query = {
                    'userId': current_user['_id'],
                    'status': 'active',
                    'isDeleted': False,
                    'excludeFromProfitLoss': {'$ne': True}
                }
                
                # Apply tag filtering - FIXED to use entryType field
                if tag_filter == 'business':
                    income_query['entryType'] = 'business'
                    expense_query['entryType'] = 'business'
                elif tag_filter == 'personal':
                    income_query['entryType'] = 'personal'
                    expense_query['entryType'] = 'personal'
                elif tag_filter == 'untagged':
                    income_query['$or'] = [
                        {'entryType': {'$exists': False}},
                        {'entryType': {'$size': 0}},
                        {'entryType': None}
                    ]
                    expense_query['$or'] = [
                        {'entryType': {'$exists': False}},
                        {'entryType': {'$size': 0}},
                        {'entryType': None}
                    ]
                # For 'all' filter, no additional filtering needed
                
                if start_date or end_date:
                    if start_date:
                        income_query['date'] = {'$gte': start_date}
                        expense_query['date'] = {'$gte': start_date}
                    if end_date:
                        income_query.setdefault('date', {})['$lte'] = end_date
                        expense_query.setdefault('date', {})['$lte'] = end_date
                
                # Fetch data in parallel
                results = fetch_collections_parallel({
                    'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),
                    'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))
                }, max_workers=2)
                
                incomes = results['incomes']
                expenses = results['expenses']
                
                # Calculate totals
                total_income = sum(income.get('amount', 0) for income in incomes)
                total_expenses = sum(expense.get('amount', 0) for expense in expenses)
                
                # MODERNIZATION (Feb 25, 2026): Calculate 3-Step P&L (align with SOA)
                # CORRECTED REVENUE CLASSIFICATION (Mar 12, 2026):
                # Sales Revenue = What we actually sell/earn (VAS Commissions + Inventory Sales + Subscriptions + FC Purchases)
                # Other Income = Internal accounting (consumed promotional spends, grants, interest)
                
                # CRITICAL FIX (Mar 13, 2026): Get VAS commissions from vas_transactions.providerCommission
                # This matches the treasury dashboard pattern and is the authoritative source
                vas_commission_data = get_vas_commissions_from_transactions(
                    mongo, user_id, start_date, end_date
                )
                vas_commission_revenue = vas_commission_data['total_commission']
                
                # Define what constitutes "Sales Revenue" (actual business revenue)
                # UPDATED: Remove 'vas_commission' from incomes query since we get it from vas_transactions
                sales_revenue_sources = [
                    'deposit_fee',                       # Deposit fees (single source of truth) ✅
                    'inventory_sale',                    # Inventory sales ✅
                    'subscription_purchase_payment_received',  # Subscription payments ✅
                    'subscription_purchase_revenue_recognition',  # Subscription revenue ✅
                    'fc_purchase_payment_received',      # FC purchase payments ✅
                    'fc_purchase_revenue_recognition',   # FC purchase revenue ✅
                ]
                
                # Define what constitutes "Other Income" (internal accounting, not real external revenue)
                other_income_sources = [
                    'fc_consumption',                    # Consumed promotional FC spends (internal) ✅
                    'fee_waiver_consumption',           # Consumed promotional fee waivers (internal) ✅
                    'subscription_consumption',         # Consumed promotional subscriptions (internal) ✅
                    'manual',                          # Manual entries (could be grants, interest, etc.) ✅
                    'voice',                           # Voice entries (could be grants, interest, etc.) ✅
                ]
                
                # Calculate Sales Revenue from incomes collection (excluding VAS commissions)
                sales_revenue_from_incomes = sum(
                    inc.get('amount', 0) for inc in incomes 
                    if inc.get('sourceType') in sales_revenue_sources
                )
                
                # Total Sales Revenue = VAS Commissions + Other Sales Revenue
                sales_revenue = vas_commission_revenue + sales_revenue_from_incomes
                
                # Calculate Other Income (internal accounting, not real external revenue)
                other_income = sum(
                    inc.get('amount', 0) for inc in incomes 
                    if inc.get('sourceType') in other_income_sources
                )
                
                # Separate COGS from Operating Expenses
                # CORRECTED COGS CLASSIFICATION (Mar 12, 2026):
                # COGS = Direct costs of providing services (inventory COGS + gateway fees for VAS services)
                cogs_categories = ['Cost of Goods Sold', 'Payment Processing Fees']
                cogs_expenses = [exp for exp in expenses if exp.get('category') in cogs_categories]
                operating_expenses = [exp for exp in expenses if exp.get('category') not in cogs_categories]
                
                total_cogs = sum(exp.get('amount', 0) for exp in cogs_expenses)
                total_operating = sum(exp.get('amount', 0) for exp in operating_expenses)
                
                # Calculate 3-Step P&L
                gross_profit = (sales_revenue + other_income) - total_cogs
                gross_margin_pct = (gross_profit / (sales_revenue + other_income) * 100) if (sales_revenue + other_income) > 0 else 0
                operating_profit = gross_profit - total_operating
                net_income = operating_profit
                
                # Prepare user data
                user = mongo.db.users.find_one({'_id': current_user['_id']})
                user_data = {
                    'firstName': current_user.get('firstName', ''),
                    'lastName': current_user.get('lastName', ''),
                    'email': current_user.get('email', ''),
                    'businessName': user.get('businessName', '') if user else '',
                    'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
                }
                
                # Prepare tax data
                tax_data = {
                    # Revenue Breakdown (NEW - Feb 25, 2026)
                    'sales_revenue': sales_revenue,
                    'other_income': other_income,
                    'total_income': total_income,
                    
                    # COGS (NEW - Feb 25, 2026)
                    'cost_of_goods_sold': total_cogs,
                    
                    # Gross Profit (NEW - Feb 25, 2026)
                    'gross_profit': gross_profit,
                    'gross_margin_percentage': gross_margin_pct,
                    
                    # Operating Expenses (NEW - Feb 25, 2026)
                    'operating_expenses': total_operating,
                    
                    # Operating Profit (NEW - Feb 25, 2026)
                    'operating_profit': operating_profit,
                    
                    # Legacy fields (for backward compatibility)
                    'deductible_expenses': total_expenses,
                    
                    'tag_filter': tag_filter,
                    'tag_filter_label': {
                        'business': 'Business Only',
                        'personal': 'Personal Only',
                        'all': 'All Entries',
                        'untagged': 'Untagged Only'
                    }.get(tag_filter, 'All Entries')
                }
                
                # For CIT, add business data
                if tax_type == 'CIT':
                    tax_data['annual_turnover'] = total_income
                    
                    # Get assets for NBV calculation
                    assets_query = {'userId': current_user['_id']}
                    assets = list(mongo.db.assets.find(assets_query, PDF_PROJECTIONS['assets']))
                    
                    nigerian_time = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=1)))
                    fixed_assets_nbv = 0
                    fixed_assets_original_cost = 0
                    
                    for asset in assets:
                        original_cost = asset.get('purchaseCost', 0)
                        fixed_assets_original_cost += original_cost
                        
                        useful_life = asset.get('usefulLife', 5)
                        purchase_date_raw = asset.get('purchaseDate')
                        
                        if isinstance(purchase_date_raw, datetime):
                            purchase_date = purchase_date_raw
                        elif isinstance(purchase_date_raw, str):
                            try:
                                purchase_date = datetime.fromisoformat(purchase_date_raw.replace('Z', ''))
                            except:
                                purchase_date = nigerian_time
                        else:
                            purchase_date = nigerian_time
                        
                        years_owned = (nigerian_time.replace(tzinfo=None) - purchase_date.replace(tzinfo=None)).days / 365.25
                        annual_depreciation = original_cost / useful_life if useful_life > 0 else 0
                        accumulated_depreciation = min(annual_depreciation * years_owned, original_cost)
                        net_book_value = original_cost - accumulated_depreciation
                        fixed_assets_nbv += net_book_value
                    
                    tax_data['fixed_assets_nbv'] = fixed_assets_nbv
                    tax_data['fixed_assets_original_cost'] = fixed_assets_original_cost
                    tax_data['assets_count'] = len(assets)
                    
                    # Add inventory, debtors, creditors
                    inventory = list(mongo.db.inventory.find({'userId': current_user['_id']}))
                    tax_data['inventory_value'] = sum(item.get('quantity', 0) * item.get('unitCost', 0) for item in inventory)
                    
                    debtors = list(mongo.db.debtors.find({'userId': current_user['_id'], 'status': {'$ne': 'paid'}}))
                    tax_data['debtors_value'] = sum(debtor.get('amount', 0) for debtor in debtors)
                    
                    creditors = list(mongo.db.creditors.find({'userId': current_user['_id'], 'status': {'$ne': 'paid'}}))
                    tax_data['creditors_value'] = sum(creditor.get('amount', 0) for creditor in creditors)
                else:
                    # For PIT, calculate statutory deductions
                    rent_keywords = ['rent', 'housing', 'accommodation']
                    rent_expenses = [exp for exp in expenses if any(keyword in exp.get('category', '').lower() for keyword in rent_keywords)]
                    annual_rent = sum(exp.get('amount', 0) for exp in rent_expenses)
                    rent_relief = min(annual_rent * 0.20, 500000)
                    
                    pension_keywords = ['pension', 'retirement']
                    pension_expenses = [exp for exp in expenses if any(keyword in exp.get('category', '').lower() for keyword in pension_keywords)]
                    pension_contributions = sum(exp.get('amount', 0) for exp in pension_expenses)
                    
                    insurance_keywords = ['insurance', 'life insurance']
                    insurance_expenses = [exp for exp in expenses if any(keyword in exp.get('category', '').lower() for keyword in insurance_keywords)]
                    life_insurance = sum(exp.get('amount', 0) for exp in insurance_expenses)
                    
                    nhis_keywords = ['nhis', 'health insurance']
                    nhis_expenses = [exp for exp in expenses if any(keyword in exp.get('category', '').lower() for keyword in nhis_keywords)]
                    nhis_contributions = sum(exp.get('amount', 0) for exp in nhis_expenses)
                    
                    hmo_keywords = ['hmo', 'health maintenance']
                    hmo_expenses = [exp for exp in expenses if any(keyword in exp.get('category', '').lower() for keyword in hmo_keywords)]
                    hmo_premiums = sum(exp.get('amount', 0) for exp in hmo_expenses)
                    
                    total_statutory_deductions = rent_relief + pension_contributions + life_insurance + nhis_contributions + hmo_premiums
                    
                    tax_data['statutory_deductions'] = {
                        'rent_relief': {
                            'annual_rent': annual_rent,
                            'relief_amount': rent_relief,
                            'calculation': f"20% of N{annual_rent:,.2f}, capped at N500,000"
                        },
                        'pension_contributions': pension_contributions,
                        'life_insurance': life_insurance,
                        'nhis_contributions': nhis_contributions,
                        'hmo_premiums': hmo_premiums,
                        'total': total_statutory_deductions
                    }
                    
                    tax_data['deductible_expenses'] = total_expenses + total_statutory_deductions
                
                # Generate PDF
                pdf_generator = PDFGenerator()
                pdf_buffer = pdf_generator.generate_tax_summary_report(user_data, tax_data, start_date, end_date, tax_type, tag_filter)
                
                # Track export
                try:
                    from utils.immutable_ledger_helper import track_export
                    report_id = f"tax_summary_{tax_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{current_user['_id']}"
                    report_name = f"Tax Summary Report ({tax_type}) - {datetime.utcnow().strftime('%Y-%m-%d')}"
                    
                    income_ids = [str(income['_id']) for income in incomes]
                    if income_ids:
                        track_export(mongo.db, 'incomes', income_ids, report_id, report_name, 'tax_report')
                    
                    expense_ids = [str(expense['_id']) for expense in expenses]
                    if expense_ids:
                        track_export(mongo.db, 'expenses', expense_ids, report_id, report_name, 'tax_report')
                except Exception as e:
                    print(f"[WARNING] Export tracking failed (non-critical): {e}")
                
                return pdf_buffer
            
            # Define wrapper function that deducts credits ONLY on success
            def generate_and_deduct_on_success():
                try:
                    # Generate PDF
                    pdf_buffer = generate_tax_summary_pdf()
                    
                    # ONLY deduct credits if generation succeeded
                    if not is_premium and credit_cost > 0:
                        print(f"[INFO] TAX SUMMARY PDF: Generated successfully, deducting {credit_cost} credits...")
                        deduct_credits(current_user, credit_cost, report_type)
                        print(f"[OK] TAX SUMMARY PDF: Credits deducted after successful generation")
                    
                    # Log export event
                    log_export_event(current_user, report_type, 'pdf', success=True)
                    
                    return pdf_buffer
                except Exception as e:
                    # DO NOT deduct credits on failure
                    print(f"[ERROR] TAX SUMMARY PDF: Generation failed, credits NOT deducted")
                    log_export_event(current_user, report_type, 'pdf', success=False)
                    raise
            
            # Start background generation with wrapper
            bg_generator.start_generation(job_id, generate_and_deduct_on_success)
            
            # Log export event (removed - now in wrapper)
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            # Return job_id immediately
            return jsonify({
                'success': True,
                'message': 'Your report is being prepared. We\'ll have it ready in a few minutes.',
                'jobId': job_id,
                'statusUrl': f'/api/reports/job-status/{job_id}',
                'estimatedTime': '2-5 minutes'
            }), 202
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Unable to start preparing your report: {str(e)}'
            }), 500
    
    # ============================================================================
    # DEBTORS REPORT
    # ============================================================================
    
    @reports_bp.route('/debtors-pdf', methods=['POST'])
    @token_required
    def export_debtors_pdf(current_user):
        """Export Debtors/Accounts Receivable as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'debtors_pdf'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)

            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
            
            # Fetch debtors data
            query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            if start_date or end_date:
                query['invoiceDate'] = {}
                if start_date:
                    query['invoiceDate']['$gte'] = start_date
                if end_date:
                    query['invoiceDate']['$lte'] = end_date
            
            debtors = list(mongo.db.debtors.find(query, PDF_PROJECTIONS['debtors']).sort('dueDate', 1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_debtors_report(user_data, debtors, start_date, end_date, tag_filter)
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            # Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_debtors_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'debtors_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Debtors PDF: {str(e)}'
            }), 500
    
    # ============================================================================
    # CREDITORS REPORT
    # ============================================================================
    
    @reports_bp.route('/creditors-pdf', methods=['POST'])
    @token_required
    def export_creditors_pdf(current_user):
        """Export Creditors/Accounts Payable as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'creditors_pdf'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)

            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
            
            # Fetch creditors data
            query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            if start_date or end_date:
                query['invoiceDate'] = {}
                if start_date:
                    query['invoiceDate']['$gte'] = start_date
                if end_date:
                    query['invoiceDate']['$lte'] = end_date
            
            creditors = list(mongo.db.creditors.find(query, PDF_PROJECTIONS['creditors']).sort('dueDate', 1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_creditors_report(user_data, creditors, start_date, end_date, tag_filter)
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            # Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_creditors_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'creditors_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Creditors PDF: {str(e)}'
            }), 500
    
    # ============================================================================
    # ASSETS REPORT
    # ============================================================================
    
    @reports_bp.route('/assets-pdf', methods=['POST'])
    @token_required
    def export_assets_pdf(current_user):
        """Export Assets Register as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'assets_pdf'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            
            # OPTIMIZATION: Check PDF cache first (instant delivery for duplicate requests)
            # CACHE INVALIDATION: Include last_updated to auto-invalidate when user adds/edits transactions
            last_updated = get_last_transaction_timestamp(current_user['_id'])
            
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'tag_filter': tag_filter if 'tag_filter' in locals() else 'all',
                'tax_type': tax_type if 'tax_type' in locals() else None,
            'last_updated': last_updated  # Auto-invalidates cache when data changes
            }
            
            cached_pdf = pdf_cache.get(current_user['_id'], report_type, cache_params)
            if cached_pdf:
                # Deduct credits even for cached PDFs (user still gets the report)
                if not is_premium and credit_cost > 0:
                    deduct_credits(current_user, credit_cost, report_type)
                
                log_export_event(current_user, report_type, 'pdf', success=True)
                
                return send_file(
                    cached_pdf,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=f'ficore_{report_type}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
                )
            
            # Fetch assets data
            # CRITICAL: Assets are Balance Sheet items (cumulative), NOT filtered by date
            # Balance Sheet = point-in-time snapshot of ALL assets owned, regardless of purchase date
            # Only Income Statement items (income/expenses) should be date-filtered
            query = {'userId': current_user['_id'], 'status': 'active'}
            
            assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']).sort('purchaseDate', -1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_assets_report(user_data, assets, start_date, end_date, tag_filter)
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            
            # Cache the generated PDF for future requests
            pdf_cache.set(current_user['_id'], report_type, cache_params, pdf_buffer)
            
# Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_assets_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'assets_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Assets PDF: {str(e)}'
            }), 500
    
    @reports_bp.route('/assets-pdf-async', methods=['POST'])
    @token_required
    def export_assets_pdf_async(current_user):
        """Generate Assets PDF in background"""
        try:
            request_data = request.get_json() or {}
            report_type = 'assets_pdf'
            
            # Check credits (fast)
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse parameters
            start_date, end_date = parse_date_range(request_data)
            
            # Create background job
            bg_generator = get_background_generator(mongo.db)
            job_id = bg_generator.create_job(
                user_id=current_user['_id'],
                report_type=report_type,
                report_format='pdf',
                params={
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None
                }
            )
            
            # Define generation function
            def generate_assets_pdf():
                # Fetch assets data (Balance Sheet items - NOT date filtered)
                query = {'userId': current_user['_id'], 'status': 'active'}
                assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']).sort('purchaseDate', -1))
                
                # Prepare user data
                user_data = {
                    'firstName': current_user.get('firstName', ''),
                    'lastName': current_user.get('lastName', ''),
                    'email': current_user.get('email', '')
                }
                
                # Generate PDF
                pdf_generator = PDFGenerator()
                pdf_buffer = pdf_generator.generate_assets_report(user_data, assets, start_date, end_date, tag_filter)
                
                return pdf_buffer
            
            # Define wrapper function that deducts credits ONLY on success
            def generate_and_deduct_on_success():
                try:
                    # Generate PDF
                    pdf_buffer = generate_assets_pdf()
                    
                    # ONLY deduct credits if generation succeeded
                    if not is_premium and credit_cost > 0:
                        print(f"[INFO] ASSETS PDF: Generated successfully, deducting {credit_cost} credits...")
                        deduct_credits(current_user, credit_cost, report_type)
                        print(f"[OK] ASSETS PDF: Credits deducted after successful generation")
                    
                    # Log export event
                    log_export_event(current_user, report_type, 'pdf', success=True)
                    
                    return pdf_buffer
                except Exception as e:
                    # DO NOT deduct credits on failure
                    print(f"[ERROR] ASSETS PDF: Generation failed, credits NOT deducted")
                    log_export_event(current_user, report_type, 'pdf', success=False)
                    raise
            
            # Start background generation with wrapper
            bg_generator.start_generation(job_id, generate_and_deduct_on_success)
            
            # Return job_id immediately
            return jsonify({
                'success': True,
                'message': 'Your report is being prepared. We\'ll have it ready in a few minutes.',
                'jobId': job_id,
                'statusUrl': f'/api/reports/job-status/{job_id}',
                'estimatedTime': '2-5 minutes'
            }), 202
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Unable to start preparing your report: {str(e)}'
            }), 500
    
    # ============================================================================
    # ASSET DEPRECIATION REPORT
    # ============================================================================
    
    @reports_bp.route('/asset-depreciation-pdf', methods=['POST'])
    @token_required
    def export_asset_depreciation_pdf(current_user):
        """Export Asset Depreciation Schedule as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'asset_depreciation_pdf'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            
            # OPTIMIZATION: Check PDF cache first (instant delivery for duplicate requests)
            # CACHE INVALIDATION: Include last_updated to auto-invalidate when user adds/edits transactions
            last_updated = get_last_transaction_timestamp(current_user['_id'])
            
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'tag_filter': tag_filter if 'tag_filter' in locals() else 'all',
                'tax_type': tax_type if 'tax_type' in locals() else None,
            'last_updated': last_updated  # Auto-invalidates cache when data changes
            }
            
            cached_pdf = pdf_cache.get(current_user['_id'], report_type, cache_params)
            if cached_pdf:
                # Deduct credits even for cached PDFs (user still gets the report)
                if not is_premium and credit_cost > 0:
                    deduct_credits(current_user, credit_cost, report_type)
                
                log_export_event(current_user, report_type, 'pdf', success=True)
                
                return send_file(
                    cached_pdf,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=f'ficore_{report_type}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
                )
            
            # Fetch assets data
            # CRITICAL: Assets are Balance Sheet items (cumulative), NOT filtered by date
            # Balance Sheet = point-in-time snapshot of ALL assets owned, regardless of purchase date
            # Only Income Statement items (income/expenses) should be date-filtered
            query = {'userId': current_user['_id'], 'status': 'active'}
            
            assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']).sort('purchaseDate', -1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_asset_depreciation_report(user_data, assets, start_date, end_date, tag_filter)
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            
            # Cache the generated PDF for future requests
            pdf_cache.set(current_user['_id'], report_type, cache_params, pdf_buffer)
            
# Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_asset_depreciation_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'asset_depreciation_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Asset Depreciation PDF: {str(e)}'
            }), 500
    
    @reports_bp.route('/asset-depreciation-pdf-async', methods=['POST'])
    @token_required
    def export_asset_depreciation_pdf_async(current_user):
        """Generate Asset Depreciation PDF in background"""
        try:
            request_data = request.get_json() or {}
            report_type = 'asset_depreciation_pdf'
            
            # Check credits (fast)
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse parameters
            start_date, end_date = parse_date_range(request_data)
            
            # Create background job
            bg_generator = get_background_generator(mongo.db)
            job_id = bg_generator.create_job(
                user_id=current_user['_id'],
                report_type=report_type,
                report_format='pdf',
                params={
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None
                }
            )
            
            # Define generation function
            def generate_asset_depreciation_pdf():
                # Fetch assets data (Balance Sheet items - NOT date filtered)
                query = {'userId': current_user['_id'], 'status': 'active'}
                assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']).sort('purchaseDate', -1))
                
                # Prepare user data
                user_data = {
                    'firstName': current_user.get('firstName', ''),
                    'lastName': current_user.get('lastName', ''),
                    'email': current_user.get('email', '')
                }
                
                # Generate PDF
                pdf_generator = PDFGenerator()
                pdf_buffer = pdf_generator.generate_asset_depreciation_report(user_data, assets, start_date, end_date, tag_filter)
                
                return pdf_buffer
            
            # Define wrapper function that deducts credits ONLY on success
            def generate_and_deduct_on_success():
                try:
                    # Generate PDF
                    pdf_buffer = generate_asset_depreciation_pdf()
                    
                    # ONLY deduct credits if generation succeeded
                    if not is_premium and credit_cost > 0:
                        print(f"[INFO] ASSET DEPRECIATION PDF: Generated successfully, deducting {credit_cost} credits...")
                        deduct_credits(current_user, credit_cost, report_type)
                        print(f"[OK] ASSET DEPRECIATION PDF: Credits deducted after successful generation")
                    
                    # Log export event
                    log_export_event(current_user, report_type, 'pdf', success=True)
                    
                    return pdf_buffer
                except Exception as e:
                    # DO NOT deduct credits on failure
                    print(f"[ERROR] ASSET DEPRECIATION PDF: Generation failed, credits NOT deducted")
                    log_export_event(current_user, report_type, 'pdf', success=False)
                    raise
            
            # Start background generation with wrapper
            bg_generator.start_generation(job_id, generate_and_deduct_on_success)
            
            # Return job_id immediately
            return jsonify({
                'success': True,
                'message': 'Your report is being prepared. We\'ll have it ready in a few minutes.',
                'jobId': job_id,
                'statusUrl': f'/api/reports/job-status/{job_id}',
                'estimatedTime': '2-5 minutes'
            }), 202
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Unable to start preparing your report: {str(e)}'
            }), 500
    
    # ============================================================================
    # INVENTORY REPORTS
    # ============================================================================
    
    @reports_bp.route('/inventory-pdf', methods=['POST'])
    @token_required
    def export_inventory_pdf(current_user):
        """Export Inventory as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'inventory_pdf'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            # Inventory doesn't use date filtering, so cache is simpler
            cache_params = {
                'report_type': 'inventory'
            }
            
            # Fetch inventory data
            query = {'userId': current_user['_id']}
            inventory_items = list(mongo.db.inventory.find(query, PDF_PROJECTIONS['inventory']).sort('name', 1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_inventory_report(user_data, inventory_items, None, None, tag_filter)
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            # Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_inventory_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'inventory_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Inventory PDF: {str(e)}'
            }), 500
    
    @reports_bp.route('/inventory-csv', methods=['POST'])
    @token_required
    def export_inventory_csv(current_user):
        """Export Inventory as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'inventory_csv'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Fetch inventory data
            query = {'userId': current_user['_id']}
            inventory_items = list(mongo.db.inventory.find(query, PDF_PROJECTIONS['inventory']).sort('name', 1))
            
            if not inventory_items:
                return jsonify({
                    'success': False,
                    'message': 'No inventory items found'
                }), 404
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Item Name', 'SKU', 'Category', 'Quantity', 'Unit Cost (N)', 'Total Value (N)', 'Min Stock Level', 'Status'])
            
            # Write data
            total_quantity = 0
            total_value = 0
            
            for item in inventory_items:
                quantity = item.get('quantity', 0)
                unit_cost = item.get('unitCost', 0)
                total_item_value = quantity * unit_cost
                min_stock = item.get('minStockLevel', 10)
                
                # Determine status
                if quantity == 0:
                    status = 'OUT OF STOCK'
                elif quantity <= min_stock:
                    status = 'LOW STOCK'
                else:
                    status = 'In Stock'
                
                writer.writerow([
                    item.get('name', 'N/A'),
                    item.get('sku', 'N/A'),
                    item.get('category', 'N/A'),
                    quantity,
                    f'{unit_cost:,.2f}',
                    f'{total_item_value:,.2f}',
                    min_stock,
                    status
                ])
                
                total_quantity += quantity
                total_value += total_item_value
            
            # Write totals
            writer.writerow(['', '', 'TOTALS', total_quantity, '', f'{total_value:,.2f}', '', ''])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_inventory_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'inventory_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Inventory CSV: {str(e)}'
            }), 500
    
    # ============================================================================
    # PHASE 4: ADDITIONAL CSV EXPORTS
    # ============================================================================
    
    # Profit & Loss CSV
    @reports_bp.route('/profit-loss-csv', methods=['POST'])
    @token_required
    def export_profit_loss_csv(current_user):
        """Export Profit & Loss statement as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'profit_loss_csv'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # MODERNIZATION (Feb 18, 2026): Exclude personal expenses (Default Business Assumption)
            # CRITICAL FIX (Mar 9, 2026): Exclude capital contributions/expenditures from P&L
            income_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False,
                'excludeFromProfitLoss': {'$ne': True},
                '$or': [
                    {'entryType': {'$ne': 'personal'}},
                    {'entryType': {'$exists': False}},
                    {'entryType': None}
                ]
            }
            expense_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False,
                'excludeFromProfitLoss': {'$ne': True},
                '$or': [
                    {'entryType': {'$ne': 'personal'}},
                    {'entryType': {'$exists': False}},
                    {'entryType': None}
                ]
            }
            
            if start_date or end_date:
                if start_date:
                    income_query['date'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('date', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            # OPTIMIZATION: Fetch incomes and expenses in parallel (2-3x faster)
            results = fetch_collections_parallel({
                'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),
                'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))
            }, max_workers=2)
            incomes = results['incomes']
            expenses = results['expenses']
            
            # CORRECTED REVENUE CLASSIFICATION (Mar 12, 2026):
            # Sales Revenue = What we actually sell/earn (VAS Commissions + Inventory Sales + Subscriptions + FC Purchases)
            # Other Income = Internal accounting (consumed promotional spends, grants, interest)
            
            # CRITICAL FIX (Mar 13, 2026): Get VAS commissions from vas_transactions.providerCommission
            # This matches the treasury dashboard pattern and is the authoritative source
            vas_commission_data = get_vas_commissions_from_transactions(
                mongo, current_user['_id'], start_date, end_date
            )
            vas_commission_revenue = vas_commission_data['total_commission']
            
            # Define what constitutes "Sales Revenue" (actual business revenue)
            # UPDATED: Remove 'vas_commission' from incomes query since we get it from vas_transactions
            sales_revenue_sources = [
                'vas_commission',                    # VAS commission income (REAL revenue) ✅
                'deposit_fee',               # Deposit fees (MOST RELIABLE revenue) ✅
                'inventory_sale',                    # Inventory sales (when we have them) ✅
                # REMOVED: fc_purchase_revenue_recognition (fake test revenue)
                # REMOVED: subscription_purchase_revenue_recognition (fake test revenue)
            ]
            
            # Define what constitutes "Other Income" (internal accounting, not real external revenue)
            other_income_sources = [
                'fc_consumption',                    # Consumed promotional FC spends (internal) ✅
                'fee_waiver_consumption',           # Consumed promotional fee waivers (internal) ✅
                'subscription_consumption',         # Consumed promotional subscriptions (internal) ✅
                'manual',                          # Manual entries (could be grants, interest, etc.) ✅
                'voice',                           # Voice entries (could be grants, interest, etc.) ✅
            ]
            
            # Calculate Sales Revenue from incomes collection (including VAS commissions)
            sales_revenue = sum(
                inc.get('amount', 0) for inc in incomes 
                if inc.get('sourceType') in sales_revenue_sources
            )
            
            # Calculate Other Income (internal accounting, not real external revenue)
            other_income = sum(
                inc.get('amount', 0) for inc in incomes 
                if inc.get('sourceType') in other_income_sources
            )
            total_revenue = sales_revenue + other_income
            
            # Separate COGS from Operating Expenses
            # CORRECTED COGS CLASSIFICATION (Mar 12, 2026):
            # COGS = Direct costs of providing services (inventory COGS + gateway fees for VAS services)
            cogs_categories = ['Cost of Goods Sold', 'Payment Processing Fees']
            cogs_items = [exp for exp in expenses if exp.get('category') in cogs_categories]
            operating_items = [exp for exp in expenses if exp.get('category') not in cogs_categories]
            
            total_cogs = sum(exp.get('amount', 0) for exp in cogs_items)
            total_operating = sum(exp.get('amount', 0) for exp in operating_items)
            
            # Calculate 3-Step P&L
            gross_profit = sales_revenue - total_cogs
            gross_margin_pct = (gross_profit / sales_revenue * 100) if sales_revenue > 0 else 0
            operating_profit = gross_profit - total_operating
            net_profit = operating_profit
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Profit & Loss Statement (3-Step Professional)'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            if start_date and end_date:
                writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
            writer.writerow(['Note:', 'Personal expenses excluded from business P&L'])
            writer.writerow([])
            
            # REVENUE SECTION
            writer.writerow(['REVENUE'])
            writer.writerow(['Date', 'Source', 'Category', 'Amount (N)', 'Source Type'])
            
            # Sales Revenue
            if sales_revenue_items:
                writer.writerow(['--- Sales Revenue ---'])
                for income in sales_revenue_items:
                    date_str = income.get('date', datetime.utcnow()).strftime('%Y-%m-%d')
                    writer.writerow([
                        date_str,
                        income.get('source', 'N/A'),
                        'Sales Revenue',
                        f'{income.get("amount", 0):,.2f}',
                        income.get('sourceType', 'manual')
                    ])
                writer.writerow(['', '', 'Sales Revenue Total:', f'{sales_revenue:,.2f}', ''])
                writer.writerow([])
            
            # Other Income
            if other_income_items:
                writer.writerow(['--- Other Income ---'])
                for income in other_income_items:
                    date_str = income.get('date', datetime.utcnow()).strftime('%Y-%m-%d')
                    writer.writerow([
                        date_str,
                        income.get('source', 'N/A'),
                        income.get('category', 'Other'),
                        f'{income.get("amount", 0):,.2f}',
                        income.get('sourceType', 'manual')
                    ])
                writer.writerow(['', '', 'Other Income Total:', f'{other_income:,.2f}', ''])
                writer.writerow([])
            
            writer.writerow(['', '', 'TOTAL REVENUE:', f'{total_revenue:,.2f}', ''])
            writer.writerow([])
            
            # COGS SECTION
            if cogs_items:
                writer.writerow(['COST OF GOODS SOLD (COGS)'])
                writer.writerow(['Date', 'Title', 'Category', 'Amount (N)', 'Source Type'])
                for expense in cogs_items:
                    date_str = expense.get('date', datetime.utcnow()).strftime('%Y-%m-%d')
                    writer.writerow([
                        date_str,
                        expense.get('title', 'N/A'),
                        expense.get('category', 'COGS'),
                        f'{expense.get("amount", 0):,.2f}',
                        expense.get('sourceType', 'manual')
                    ])
                writer.writerow(['', '', 'Total COGS:', f'{total_cogs:,.2f}', ''])
                writer.writerow([])
            
            # GROSS PROFIT
            writer.writerow(['GROSS PROFIT'])
            writer.writerow(['Sales Revenue', f'{sales_revenue:,.2f}'])
            writer.writerow(['Less: COGS', f'{total_cogs:,.2f}'])
            writer.writerow(['Gross Profit', f'{gross_profit:,.2f}'])
            writer.writerow(['Gross Margin %', f'{gross_margin_pct:.2f}%'])
            writer.writerow([])
            
            # OPERATING EXPENSES SECTION
            if operating_items:
                writer.writerow(['OPERATING EXPENSES'])
                writer.writerow(['Date', 'Title', 'Category', 'Amount (N)', 'Source Type'])
                for expense in operating_items:
                    date_str = expense.get('date', datetime.utcnow()).strftime('%Y-%m-%d')
                    writer.writerow([
                        date_str,
                        expense.get('title', 'N/A'),
                        expense.get('category', 'Other'),
                        f'{expense.get("amount", 0):,.2f}',
                        expense.get('sourceType', 'manual')
                    ])
                writer.writerow(['', '', 'Total Operating Expenses:', f'{total_operating:,.2f}', ''])
                writer.writerow([])
            
            # FINAL SUMMARY
            writer.writerow(['PROFIT & LOSS SUMMARY'])
            writer.writerow(['Total Revenue', f'{total_revenue:,.2f}'])
            writer.writerow(['Less: COGS', f'{total_cogs:,.2f}'])
            writer.writerow(['Gross Profit', f'{gross_profit:,.2f}'])
            writer.writerow(['Gross Margin %', f'{gross_margin_pct:.2f}%'])
            writer.writerow(['Less: Operating Expenses', f'{total_operating:,.2f}'])
            writer.writerow(['Operating Profit', f'{operating_profit:,.2f}'])
            writer.writerow(['NET PROFIT/LOSS', f'{net_profit:,.2f}'])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_profit_loss_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'profit_loss_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Profit & Loss CSV: {str(e)}'
            }), 500
    
    # Cash Flow CSV
    @reports_bp.route('/cash-flow-csv', methods=['POST'])
    @token_required
    def export_cash_flow_csv(current_user):
        """Export Cash Flow statement as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'cash_flow_csv'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Fetch income and expense data
            income_query = {'userId': current_user['_id']}
            expense_query = {'userId': current_user['_id']}
            
            if start_date or end_date:
                if start_date:
                    income_query['date'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('date', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            # OPTIMIZATION: Fetch incomes and expenses in parallel (2-3x faster)

            
            results = fetch_collections_parallel({

            
                'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),

            
                'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))

            
            }, max_workers=2)

            
            incomes = results['incomes']

            
            expenses = results['expenses']
            
            # Calculate totals
            total_inflows = sum(income.get('amount', 0) for income in incomes)
            total_outflows = sum(expense.get('amount', 0) for expense in expenses)
            net_cash_flow = total_inflows - total_outflows
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Cash Flow Statement'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            if start_date and end_date:
                writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
            writer.writerow([])
            
            # Cash Flow from Operating Activities
            writer.writerow(['CASH FLOW FROM OPERATING ACTIVITIES'])
            writer.writerow(['Description', 'Amount (N)'])
            writer.writerow(['Cash Inflows (Income)', f'{total_inflows:,.2f}'])
            writer.writerow(['Cash Outflows (Expenses)', f'{-total_outflows:,.2f}'])
            writer.writerow(['Net Cash from Operations', f'{net_cash_flow:,.2f}'])
            writer.writerow([])
            
            # Summary
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Cash Inflows', f'{total_inflows:,.2f}'])
            writer.writerow(['Total Cash Outflows', f'{total_outflows:,.2f}'])
            writer.writerow(['Net Cash Flow', f'{net_cash_flow:,.2f}'])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_cash_flow_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'cash_flow_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Cash Flow CSV: {str(e)}'
            }), 500
    
    # Tax Summary CSV
    @reports_bp.route('/tax-summary-csv', methods=['POST'])
    @token_required
    def export_tax_summary_csv(current_user):
        """Export Tax Summary as CSV (supports both PIT and CIT)"""
        try:
            request_data = request.get_json() or {}
            report_type = 'tax_summary_csv'
            
            # Get tax type from request (default to PIT for individuals)
            tax_type = request_data.get('taxType', 'PIT').upper()
            if tax_type not in ['PIT', 'CIT']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tax type. Must be either PIT (Personal Income Tax) or CIT (Corporate Income Tax)'
                }), 400
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Fetch income and expense data
            # CRITICAL FIX (Mar 9, 2026): Exclude capital contributions/expenditures from P&L
            income_query = {'userId': current_user['_id'], 'excludeFromProfitLoss': {'$ne': True}}
            expense_query = {'userId': current_user['_id'], 'excludeFromProfitLoss': {'$ne': True}}
            
            if start_date or end_date:
                if start_date:
                    income_query['date'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('date', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            # OPTIMIZATION: Fetch incomes and expenses in parallel (2-3x faster)

            
            results = fetch_collections_parallel({

            
                'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),

            
                'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))

            
            }, max_workers=2)

            
            incomes = results['incomes']

            
            expenses = results['expenses']
            
            # Calculate totals
            total_income = sum(income.get('amount', 0) for income in incomes)
            total_expenses = sum(expense.get('amount', 0) for expense in expenses)
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            tax_type_name = "Personal Income Tax (PIT)" if tax_type == 'PIT' else "Corporate Income Tax (CIT)"
            writer.writerow([f'FiCore Africa - Tax Summary Report - {tax_type_name}'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            if start_date and end_date:
                writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
            writer.writerow([])
            
            # Income Summary
            writer.writerow(['INCOME SUMMARY'])
            writer.writerow(['Description', 'Amount (N)'])
            writer.writerow(['Gross Income', f'{total_income:,.2f}'])
            writer.writerow(['Less: Deductible Expenses', f'{total_expenses:,.2f}'])
            
            net_income = total_income - total_expenses
            writer.writerow(['Taxable Income', f'{net_income:,.2f}'])
            writer.writerow([])
            
            # Tax Calculation
            if tax_type == 'CIT':
                writer.writerow(['CORPORATE INCOME TAX CALCULATION'])
                writer.writerow(['Description', 'Amount (N)'])
                cit_rate = 0.25
                total_tax = net_income * cit_rate if net_income > 0 else 0
                writer.writerow(['Taxable Profit', f'{net_income:,.2f}'])
                writer.writerow(['CIT Rate', '25%'])
                writer.writerow(['Calculated Tax', f'{total_tax:,.2f}'])
            else:
                writer.writerow(['PERSONAL INCOME TAX CALCULATION'])
                writer.writerow(['Income Band', 'Rate', 'Taxable Amount (N)', 'Tax (N)'])
                
                # Nigerian PIT bands
                tax_bands = [
                    (0, 800000, 0.00),
                    (800000, 3000000, 0.15),
                    (3000000, 12000000, 0.18),
                    (12000000, 25000000, 0.21),
                    (25000000, 50000000, 0.23),
                    (50000000, float('inf'), 0.25)
                ]
                
                total_tax = 0
                for lower, upper, rate in tax_bands:
                    if net_income <= lower:
                        break
                    
                    taxable_in_band = min(net_income, upper) - lower
                    if taxable_in_band <= 0:
                        continue
                    
                    band_tax = taxable_in_band * rate
                    total_tax += band_tax
                    
                    upper_display = f"N{upper:,.0f}" if upper != float('inf') else "Above"
                    writer.writerow([
                        f"N{lower:,.0f} - {upper_display}",
                        f"{rate*100:.1f}%",
                        f'{taxable_in_band:,.2f}',
                        f'{band_tax:,.2f}'
                    ])
                
                writer.writerow(['', 'Total Tax:', '', f'{total_tax:,.2f}'])
            
            writer.writerow([])
            
            # Summary
            effective_rate = (total_tax / net_income * 100) if net_income > 0 else 0
            net_after_tax = net_income - total_tax
            
            writer.writerow(['TAX SUMMARY'])
            writer.writerow(['Total Tax Liability', f'{total_tax:,.2f}'])
            writer.writerow(['Effective Tax Rate', f'{effective_rate:.2f}%'])
            writer.writerow(['Net Income After Tax', f'{net_after_tax:,.2f}'])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            tax_type_label = 'PIT' if tax_type == 'PIT' else 'CIT'
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_tax_summary_{tax_type_label}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'tax_summary_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Tax Summary CSV: {str(e)}'
            }), 500
    
    # Debtors CSV
    @reports_bp.route('/debtors-csv', methods=['POST'])
    @token_required
    def export_debtors_csv(current_user):
        """Export Debtors/Accounts Receivable as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'debtors_csv'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Fetch debtors data
            query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            if start_date or end_date:
                query['invoiceDate'] = {}
                if start_date:
                    query['invoiceDate']['$gte'] = start_date
                if end_date:
                    query['invoiceDate']['$lte'] = end_date
            
            debtors = list(mongo.db.debtors.find(query, PDF_PROJECTIONS['debtors']).sort('dueDate', 1))
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Debtors Report (Accounts Receivable)'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            writer.writerow([])
            
            # Data
            writer.writerow(['Debtor Name', 'Invoice Date', 'Due Date', 'Amount (N)', 'Status'])
            total_outstanding = 0
            overdue_amount = 0
            
            for debtor in debtors:
                invoice_date = debtor.get('invoiceDate', datetime.utcnow())
                due_date = debtor.get('dueDate', datetime.utcnow())
                amount = debtor.get('amount', 0)
                
                # Determine status
                if datetime.utcnow() > due_date:
                    status = 'OVERDUE'
                    overdue_amount += amount
                else:
                    status = 'Current'
                
                writer.writerow([
                    debtor.get('name', 'N/A'),
                    invoice_date.strftime('%Y-%m-%d'),
                    due_date.strftime('%Y-%m-%d'),
                    f'{amount:,.2f}',
                    status
                ])
                total_outstanding += amount
            
            writer.writerow(['', '', 'Total Outstanding:', f'{total_outstanding:,.2f}', ''])
            writer.writerow([])
            
            # Summary
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Outstanding', f'{total_outstanding:,.2f}'])
            writer.writerow(['Overdue Amount', f'{overdue_amount:,.2f}'])
            writer.writerow(['Number of Debtors', len(debtors)])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_debtors_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'debtors_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Debtors CSV: {str(e)}'
            }), 500
    
    # Creditors CSV
    @reports_bp.route('/creditors-csv', methods=['POST'])
    @token_required
    def export_creditors_csv(current_user):
        """Export Creditors/Accounts Payable as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'creditors_csv'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Fetch creditors data
            query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            if start_date or end_date:
                query['invoiceDate'] = {}
                if start_date:
                    query['invoiceDate']['$gte'] = start_date
                if end_date:
                    query['invoiceDate']['$lte'] = end_date
            
            creditors = list(mongo.db.creditors.find(query, PDF_PROJECTIONS['creditors']).sort('dueDate', 1))
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Creditors Report (Accounts Payable)'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            writer.writerow([])
            
            # Data
            writer.writerow(['Creditor Name', 'Invoice Date', 'Due Date', 'Amount (N)', 'Status'])
            total_outstanding = 0
            overdue_amount = 0
            
            for creditor in creditors:
                invoice_date = creditor.get('invoiceDate', datetime.utcnow())
                due_date = creditor.get('dueDate', datetime.utcnow())
                amount = creditor.get('amount', 0)
                
                # Determine status
                if datetime.utcnow() > due_date:
                    status = 'OVERDUE'
                    overdue_amount += amount
                else:
                    status = 'Current'
                
                writer.writerow([
                    creditor.get('name', 'N/A'),
                    invoice_date.strftime('%Y-%m-%d'),
                    due_date.strftime('%Y-%m-%d'),
                    f'{amount:,.2f}',
                    status
                ])
                total_outstanding += amount
            
            writer.writerow(['', '', 'Total Outstanding:', f'{total_outstanding:,.2f}', ''])
            writer.writerow([])
            
            # Summary
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Outstanding', f'{total_outstanding:,.2f}'])
            writer.writerow(['Overdue Amount', f'{overdue_amount:,.2f}'])
            writer.writerow(['Number of Creditors', len(creditors)])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_creditors_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'creditors_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Creditors CSV: {str(e)}'
            }), 500
    
    # Assets CSV
    @reports_bp.route('/assets-csv', methods=['POST'])
    @token_required
    def export_assets_csv(current_user):
        """Export Assets Register as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'assets_csv'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Fetch assets data
            # CRITICAL: Assets are Balance Sheet items (cumulative), NOT filtered by date
            # Balance Sheet = point-in-time snapshot of ALL assets owned, regardless of purchase date
            # Only Income Statement items (income/expenses) should be date-filtered
            query = {'userId': current_user['_id'], 'status': 'active'}
            
            assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']).sort('purchaseDate', -1))
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Assets Register'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            writer.writerow([])
            
            # Data
            writer.writerow(['Asset Name', 'Category', 'Purchase Date', 'Cost (N)', 'Current Value (N)'])
            total_cost = 0
            total_value = 0
            
            for asset in assets:
                purchase_date = asset.get('purchaseDate', datetime.utcnow())
                cost = asset.get('purchaseCost', 0)
                current_value = asset.get('currentValue', cost)
                
                writer.writerow([
                    asset.get('name', 'N/A'),
                    asset.get('category', 'N/A'),
                    purchase_date.strftime('%Y-%m-%d'),
                    f'{cost:,.2f}',
                    f'{current_value:,.2f}'
                ])
                total_cost += cost
                total_value += current_value
            
            writer.writerow(['', '', 'Totals:', f'{total_cost:,.2f}', f'{total_value:,.2f}'])
            writer.writerow([])
            
            # Summary
            total_depreciation = total_cost - total_value
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Asset Cost', f'{total_cost:,.2f}'])
            writer.writerow(['Total Current Value', f'{total_value:,.2f}'])
            writer.writerow(['Total Depreciation', f'{total_depreciation:,.2f}'])
            writer.writerow(['Number of Assets', len(assets)])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_assets_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'assets_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Assets CSV: {str(e)}'
            }), 500
    
    # Asset Depreciation CSV
    @reports_bp.route('/asset-depreciation-csv', methods=['POST'])
    @token_required
    def export_asset_depreciation_csv(current_user):
        """Export Asset Depreciation Schedule as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'asset_depreciation_csv'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Fetch assets data
            # CRITICAL: Assets are Balance Sheet items (cumulative), NOT filtered by date
            # Balance Sheet = point-in-time snapshot of ALL assets owned, regardless of purchase date
            # Only Income Statement items (income/expenses) should be date-filtered
            query = {'userId': current_user['_id'], 'status': 'active'}
            
            assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']).sort('purchaseDate', -1))
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Asset Depreciation Schedule'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            writer.writerow(['Depreciation Method: Straight-Line'])
            writer.writerow([])
            
            # Data
            writer.writerow(['Asset', 'Cost (N)', 'Useful Life', 'Annual Dep. (N)', 'Accumulated (N)', 'Book Value (N)'])
            total_cost = 0
            total_annual_dep = 0
            total_accumulated = 0
            total_book_value = 0
            
            for asset in assets:
                cost = asset.get('purchaseCost', 0)
                useful_life = asset.get('usefulLife', 5)
                purchase_date = asset.get('purchaseDate', datetime.utcnow())
                
                # Calculate depreciation
                annual_depreciation = cost / useful_life if useful_life > 0 else 0
                years_owned = (datetime.utcnow() - purchase_date).days / 365.25
                accumulated_depreciation = min(annual_depreciation * years_owned, cost)
                book_value = cost - accumulated_depreciation
                
                writer.writerow([
                    asset.get('name', 'N/A'),
                    f'{cost:,.2f}',
                    f'{useful_life} years',
                    f'{annual_depreciation:,.2f}',
                    f'{accumulated_depreciation:,.2f}',
                    f'{book_value:,.2f}'
                ])
                
                total_cost += cost
                total_annual_dep += annual_depreciation
                total_accumulated += accumulated_depreciation
                total_book_value += book_value
            
            writer.writerow([
                'Totals:',
                f'{total_cost:,.2f}',
                '',
                f'{total_annual_dep:,.2f}',
                f'{total_accumulated:,.2f}',
                f'{total_book_value:,.2f}'
            ])
            writer.writerow([])
            
            # Summary
            writer.writerow(['DEPRECIATION SUMMARY'])
            writer.writerow(['Total Asset Cost', f'{total_cost:,.2f}'])
            writer.writerow(['Total Annual Depreciation', f'{total_annual_dep:,.2f}'])
            writer.writerow(['Total Accumulated Depreciation', f'{total_accumulated:,.2f}'])
            writer.writerow(['Total Book Value', f'{total_book_value:,.2f}'])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_asset_depreciation_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'asset_depreciation_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Asset Depreciation CSV: {str(e)}'
            }), 500
    
    # ============================================================================
    # CREDIT TRANSACTION REPORTS
    # ============================================================================
    
    @reports_bp.route('/credits-pdf', methods=['POST'])
    @token_required
    def export_credits_pdf(current_user):
        """Export Credit Transactions as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'credits_pdf'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to generate this report. Current balance: {current_balance} FC',
                    'required_credits': credit_cost,
                    'current_balance': current_balance
                }), 402  # Payment Required
            
            # Get date range from request
            start_date = request_data.get('startDate')
            end_date = request_data.get('endDate')
            
            # Parse dates
            if start_date:
                start_date = datetime.fromisoformat(start_date.replace('Z', ''))
            if end_date:
                end_date = datetime.fromisoformat(end_date.replace('Z', ''))
            
            # Cache parameters for this report
            cache_params = {
                'report_type': 'credits',
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
            
            # Build query
            query = {'userId': current_user['_id']}
            if start_date or end_date:
                query['createdAt'] = {}
                if start_date:
                    query['createdAt']['$gte'] = start_date
                if end_date:
                    query['createdAt']['$lte'] = end_date
            
            # Fetch credit transactions
            transactions = list(mongo.db.credit_transactions.find(query).sort('createdAt', -1))
            
            # Calculate totals
            total_earned = sum(t.get('amount', 0) for t in transactions if t.get('amount', 0) > 0)
            total_spent = abs(sum(t.get('amount', 0) for t in transactions if t.get('amount', 0) < 0))
            net_change = total_earned - total_spent
            
            # Calculate breakdown by source (Feb 9, 2026)
            purchased = sum(
                t.get('amount', 0) for t in transactions 
                if t.get('amount', 0) > 0 and (
                    t.get('metadata', {}).get('purchaseType') or 
                    t.get('paymentMethod') == 'paystack' or
                    'purchase' in t.get('description', '').lower()
                )
            )
            
            signup_bonus = sum(
                t.get('amount', 0) for t in transactions 
                if t.get('amount', 0) > 0 and t.get('operation') == 'signup_bonus'
            )
            
            rewards = sum(
                t.get('amount', 0) for t in transactions 
                if t.get('amount', 0) > 0 and (
                    t.get('operation') in ['engagement_reward', 'streak_milestone', 'exploration_bonus', 'profile_completion'] or
                    any(keyword in t.get('description', '').lower() for keyword in ['reward', 'streak', 'exploration', 'milestone'])
                )
            )
            
            tax_education = sum(
                t.get('amount', 0) for t in transactions 
                if t.get('amount', 0) > 0 and (
                    t.get('operation') == 'tax_education_progress' or
                    any(keyword in t.get('description', '').lower() for keyword in ['tax education', 'tax module'])
                )
            )
            
            other = total_earned - (purchased + signup_bonus + rewards + tax_education)
            if other < 0:
                other = 0.0
            
            # Get current balance
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            current_fc_balance = user.get('ficoreCreditBalance', 0.0)
            
            # Prepare data for PDF
            credit_data = {
                'transactions': transactions,
                'total_earned': total_earned,
                'total_spent': total_spent,
                'net_change': net_change,
                'current_balance': current_fc_balance,
                'transaction_count': len(transactions),
                # NEW: Credits breakdown by source (Feb 9, 2026)
                'earned_breakdown': {
                    'purchased': purchased,
                    'signup_bonus': signup_bonus,
                    'rewards': rewards,
                    'tax_education': tax_education,
                    'other': other
                }
            }
            
            # User data
            user_data = {
                'name': user.get('name', 'N/A'),
                'email': user.get('email', 'N/A'),
                'phone': user.get('phone', 'N/A'),
                'isSubscribed': user.get('isSubscribed', False)
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_credit_transactions_report(user_data, credit_data, start_date, end_date, tag_filter)
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            # Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_credit_transactions_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'credits_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Credit Transactions PDF: {str(e)}'
            }), 500
    
    # Credit Transactions CSV
    @reports_bp.route('/credits-csv', methods=['POST'])
    @token_required
    def export_credits_csv(current_user):
        """Export Credit Transactions as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'credits_csv'
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to generate this report. Current balance: {current_balance} FC',
                    'required_credits': credit_cost,
                    'current_balance': current_balance
                }), 402  # Payment Required
            
            # Get date range from request
            start_date = request_data.get('startDate')
            end_date = request_data.get('endDate')
            
            # Parse dates
            if start_date:
                start_date = datetime.fromisoformat(start_date.replace('Z', ''))
            if end_date:
                end_date = datetime.fromisoformat(end_date.replace('Z', ''))
            
            # Cache parameters for this report
            cache_params = {
                'report_type': 'credits',
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
            
            # Build query
            query = {'userId': current_user['_id']}
            if start_date or end_date:
                query['createdAt'] = {}
                if start_date:
                    query['createdAt']['$gte'] = start_date
                if end_date:
                    query['createdAt']['$lte'] = end_date
            
            # Fetch credit transactions
            transactions = list(mongo.db.credit_transactions.find(query).sort('createdAt', -1))
            
            # Calculate totals
            total_earned = sum(t.get('amount', 0) for t in transactions if t.get('amount', 0) > 0)
            total_spent = abs(sum(t.get('amount', 0) for t in transactions if t.get('amount', 0) < 0))
            net_change = total_earned - total_spent
            
            # Calculate breakdown by source (Feb 9, 2026)
            purchased = sum(
                t.get('amount', 0) for t in transactions 
                if t.get('amount', 0) > 0 and (
                    t.get('metadata', {}).get('purchaseType') or 
                    t.get('paymentMethod') == 'paystack' or
                    'purchase' in t.get('description', '').lower()
                )
            )
            
            signup_bonus = sum(
                t.get('amount', 0) for t in transactions 
                if t.get('amount', 0) > 0 and t.get('operation') == 'signup_bonus'
            )
            
            rewards = sum(
                t.get('amount', 0) for t in transactions 
                if t.get('amount', 0) > 0 and (
                    t.get('operation') in ['engagement_reward', 'streak_milestone', 'exploration_bonus', 'profile_completion'] or
                    any(keyword in t.get('description', '').lower() for keyword in ['reward', 'streak', 'exploration', 'milestone'])
                )
            )
            
            tax_education = sum(
                t.get('amount', 0) for t in transactions 
                if t.get('amount', 0) > 0 and (
                    t.get('operation') == 'tax_education_progress' or
                    any(keyword in t.get('description', '').lower() for keyword in ['tax education', 'tax module'])
                )
            )
            
            other = total_earned - (purchased + signup_bonus + rewards + tax_education)
            if other < 0:
                other = 0.0
            
            # Get current balance
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            current_fc_balance = user.get('ficoreCreditBalance', 0.0)
            
            # Create CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Credit Transactions Report'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            if start_date and end_date:
                writer.writerow(['Period:', f"{start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}"])
            elif start_date:
                writer.writerow(['Period:', f"From {start_date.strftime('%B %d, %Y')}"])
            elif end_date:
                writer.writerow(['Period:', f"Until {end_date.strftime('%B %d, %Y')}"])
            writer.writerow(['User:', user.get('name', 'N/A')])
            writer.writerow([])
            
            # Summary
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Earned (FC)', f'{total_earned:,.2f}'])
            writer.writerow(['Total Spent (FC)', f'{total_spent:,.2f}'])
            writer.writerow(['Net Change (FC)', f'{net_change:,.2f}'])
            writer.writerow(['Current Balance (FC)', f'{current_fc_balance:,.2f}'])
            writer.writerow(['Total Transactions', len(transactions)])
            writer.writerow([])
            
            # Credits Earned Breakdown (Feb 9, 2026)
            writer.writerow(['CREDITS EARNED BY SOURCE'])
            if purchased > 0:
                writer.writerow(['Purchased', f'{purchased:,.2f}'])
            if signup_bonus > 0:
                writer.writerow(['Signup Bonus', f'{signup_bonus:,.2f}'])
            if rewards > 0:
                writer.writerow(['Rewards Screen', f'{rewards:,.2f}'])
            if tax_education > 0:
                writer.writerow(['Tax Education', f'{tax_education:,.2f}'])
            if other > 0:
                writer.writerow(['Other', f'{other:,.2f}'])
            writer.writerow([])
            
            # Transactions table
            writer.writerow(['TRANSACTIONS'])
            writer.writerow(['Date', 'Type', 'Description', 'Amount (FC)', 'Balance Before', 'Balance After', 'Status'])
            
            for transaction in transactions:
                date_obj = transaction.get('createdAt', datetime.utcnow())
                date_str = date_obj.strftime('%b %d, %Y')
                
                trans_type = transaction.get('type', 'N/A')
                description = transaction.get('description', 'N/A')
                amount = transaction.get('amount', 0)
                balance_before = transaction.get('balanceBefore', 0)
                balance_after = transaction.get('balanceAfter', 0)
                status = transaction.get('status', 'N/A')
                
                writer.writerow([
                    date_str,
                    trans_type,
                    description,
                    f'{amount:,.2f}',
                    f'{balance_before:,.2f}',
                    f'{balance_after:,.2f}',
                    status
                ])
            
            writer.writerow([])
            writer.writerow(['Totals:'])
            writer.writerow(['Total Earned', f'{total_earned:,.2f}'])
            writer.writerow(['Total Spent', f'{total_spent:,.2f}'])
            writer.writerow(['Net Change', f'{net_change:,.2f}'])
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV file
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_credit_transactions_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'credits_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Credit Transactions CSV: {str(e)}'
            }), 500
    
    # ============================================================================
    # PREVIEW ENDPOINT - Unified preview for all report types
    # ============================================================================
    
    @reports_bp.route('/preview', methods=['POST'])
    @token_required
    def preview_report(current_user):
        """
        Preview report data before exporting
        Returns first 50 entries + summary statistics
        
        Request body:
        {
            "reportType": "income|expenses|profit_loss|cash_flow|tax_summary|debtors|creditors|assets|asset_depreciation|inventory|credits",
            "startDate": "2024-01-01T00:00:00Z" (optional),
            "endDate": "2024-01-31T23:59:59Z" (optional)
        }
        
        Response:
        {
            "success": true,
            "preview": true,
            "total_count": 250,
            "showing_count": 50,
            "data": [...],
            "summary": {...}
        }
        """
        try:
            request_data = request.get_json() or {}
            report_type = request_data.get('reportType')
            
            if not report_type:
                return jsonify({
                    'success': False,
                    'message': 'Report type is required'
                }), 400
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Preview limit (50 entries as per founder's specification)
            PREVIEW_LIMIT = 50
            
            # Route to appropriate preview handler
            if report_type == 'income':
                return _preview_income(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'expenses':
                return _preview_expenses(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'profit_loss':
                return _preview_profit_loss(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'cash_flow':
                return _preview_cash_flow(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'tax_summary':
                return _preview_tax_summary(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'debtors':
                return _preview_debtors(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'creditors':
                return _preview_creditors(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'assets':
                return _preview_assets(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'asset_depreciation':
                return _preview_asset_depreciation(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'inventory':
                return _preview_inventory(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'credits':
                return _preview_credits(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'statement_of_affairs':
                # Statement of Affairs is a comprehensive report combining multiple sections
                # For preview, show summary of each section
                return _preview_statement_of_affairs(current_user, start_date, end_date, PREVIEW_LIMIT)
            # Wallet reports (Feb 19, 2026)
            elif report_type == 'wallet_funding':
                return _preview_wallet_funding(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'bill_payments':
                return _preview_bill_payments(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'airtime_purchases':
                return _preview_airtime_purchases(current_user, start_date, end_date, PREVIEW_LIMIT)
            elif report_type == 'full_wallet':
                return _preview_full_wallet(current_user, start_date, end_date, PREVIEW_LIMIT)
            else:
                return jsonify({
                    'success': False,
                    'message': f'Unknown report type: {report_type}'
                }), 400
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Failed to generate preview: {str(e)}'
            }), 500
    
    # Preview helper functions
    
    def _preview_income(current_user, start_date, end_date, limit):
        """Preview income records"""
        query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False}
        if start_date or end_date:
            query['date'] = {}
            if start_date:
                query['date']['$gte'] = start_date
            if end_date:
                query['date']['$lte'] = end_date
        
        total_count = mongo.db.incomes.count_documents(query)
        incomes = list(mongo.db.incomes.find(query, PDF_PROJECTIONS['incomes']).sort('date', -1).limit(limit))
        
        # Calculate summary
        all_incomes = list(mongo.db.incomes.find(query, PDF_PROJECTIONS['incomes']))
        total_amount = sum(inc.get('amount', 0) for inc in all_incomes)
        
        # Format data
        data = []
        for income in incomes:
            data.append({
                'id': str(income['_id']),
                'date': income.get('date', datetime.utcnow()).isoformat() + 'Z',
                'source': income.get('source', ''),
                'category': income.get('category', {}).get('name', 'Other') if isinstance(income.get('category'), dict) else income.get('category', 'Other'),
                'amount': income.get('amount', 0),
                'description': income.get('description', '')
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_income': total_amount,
                'average_income': total_amount / total_count if total_count > 0 else 0,
                'count': total_count
            }
        })
    
    def _preview_expenses(current_user, start_date, end_date, limit):
        """
        Preview expense records
        
        CRITICAL FIX (Feb 19, 2026):
        - Normalize category format (handle dict vs string)
        """
        
        def normalize_category(category):
            """Normalize category to string (handle dict format)"""
            if isinstance(category, dict):
                return category.get('name', 'Other')
            return category or 'Other'
        
        query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False}
        if start_date or end_date:
            query['date'] = {}
            if start_date:
                query['date']['$gte'] = start_date
            if end_date:
                query['date']['$lte'] = end_date
        
        total_count = mongo.db.expenses.count_documents(query)
        expenses = list(mongo.db.expenses.find(query, PDF_PROJECTIONS['expenses']).sort('date', -1).limit(limit))
        
        # Calculate summary
        all_expenses = list(mongo.db.expenses.find(query, PDF_PROJECTIONS['expenses']))
        total_amount = sum(exp.get('amount', 0) for exp in all_expenses)
        
        # Format data
        data = []
        for expense in expenses:
            category_raw = expense.get('category', 'Other')
            category = normalize_category(category_raw)  # [OK] Normalize here
            data.append({
                'id': str(expense['_id']),
                'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                'title': expense.get('title', ''),
                'category': category,  # [OK] Always string now
                'amount': expense.get('amount', 0),
                'description': expense.get('description', '')
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_expenses': total_amount,
                'average_expense': total_amount / total_count if total_count > 0 else 0,
                'count': total_count
            }
        })
    
    def _preview_profit_loss(current_user, start_date, end_date, limit):
        """
        Preview profit & loss data with 3-Step Professional P&L Calculation
        
        MODERNIZATION (Feb 18, 2026):
        - Excludes personal expenses (entryType: 'personal')
        - Separates COGS from Operating Expenses
        - Calculates Gross Profit, Operating Profit, Net Profit
        - Calculates Gross Margin % (the "CFO in your pocket" metric)
        
        CRITICAL FIX (Feb 19, 2026):
        - Normalize category format (handle dict vs string)
        - Prevents category comparison failures that break calculations
        """
        
        def normalize_category(category):
            """Normalize category to string (handle dict format)"""
            if isinstance(category, dict):
                return category.get('name', 'Other')
            return category or 'Other'
        
        # BASE QUERIES: Exclude personal expenses (Default Business Assumption)
        # Rationale: In a business wallet, assume transactions are business unless explicitly personal
        income_query = {
            'userId': current_user['_id'],
            'status': 'active',
            'isDeleted': False,
            '$or': [
                {'entryType': {'$ne': 'personal'}},  # Exclude personal
                {'entryType': {'$exists': False}},   # Include untagged (legacy data)
                {'entryType': None}                   # Include null
            ]
        }
        
        expense_query = {
            'userId': current_user['_id'],
            'status': 'active',
            'isDeleted': False,
            '$or': [
                {'entryType': {'$ne': 'personal'}},  # Exclude personal
                {'entryType': {'$exists': False}},   # Include untagged (legacy data)
                {'entryType': None}                   # Include null
            ]
        }
        
        # Apply date filters
        if start_date or end_date:
            if start_date:
                income_query['date'] = {'$gte': start_date}
                expense_query['date'] = {'$gte': start_date}
            if end_date:
                income_query.setdefault('date', {})['$lte'] = end_date
                expense_query.setdefault('date', {})['$lte'] = end_date
        
        # STEP 1: Get all business incomes
        all_incomes = list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes']))
        
        # CORRECTED REVENUE CLASSIFICATION (Mar 12, 2026):
        # Sales Revenue = What we actually sell/earn (VAS Commissions + Inventory Sales + Subscriptions + FC Purchases)
        # Other Income = Internal accounting (consumed promotional spends, grants, interest)
        
        # CRITICAL FIX (Mar 13, 2026): Get VAS commissions from vas_transactions.providerCommission
        # This matches the treasury dashboard pattern and is the authoritative source
        vas_commission_data = get_vas_commissions_from_transactions(
            mongo, user_id, start_date, end_date
        )
        vas_commission_revenue = vas_commission_data['total_commission']
        
        # Define what constitutes "Sales Revenue" (actual business revenue)
        # UPDATED: Remove 'vas_commission' from incomes query since we get it from vas_transactions
        sales_revenue_sources = [
            'inventory_sale',                    # Inventory sales ✅
            'deposit_fee',                       # Deposit fees (single source of truth) ✅
            'subscription_purchase_payment_received',  # Subscription payments ✅
            'subscription_purchase_revenue_recognition',  # Subscription revenue ✅
            'fc_purchase_payment_received',      # FC purchase payments ✅
            'fc_purchase_revenue_recognition',   # FC purchase revenue ✅
            ]
        
        # Define what constitutes "Other Income" (internal accounting, not real external revenue)
        other_income_sources = [
            'fc_consumption',                    # Consumed promotional FC spends (internal) ✅
            'fee_waiver_consumption',           # Consumed promotional fee waivers (internal) ✅
            'subscription_consumption',         # Consumed promotional subscriptions (internal) ✅
            'manual',                          # Manual entries (could be grants, interest, etc.) ✅
            'voice',                           # Voice entries (could be grants, interest, etc.) ✅
        ]
        
        # Calculate Sales Revenue from incomes collection (excluding VAS commissions)
        sales_revenue_from_incomes = 0
        other_income = 0
        for inc in all_incomes:
            amount = inc.get('amount', 0)
            source_type = inc.get('sourceType', '')
            if source_type in sales_revenue_sources:
                sales_revenue_from_incomes += amount
            elif source_type in other_income_sources:
                other_income += amount
            else:
                # Default to other income for unclassified entries
                other_income += amount
        
        # Total Sales Revenue = VAS Commissions + Other Sales Revenue
        sales_revenue = vas_commission_revenue + sales_revenue_from_incomes
        total_revenue = sales_revenue + other_income
        
        # STEP 2: Get COGS (Cost of Goods Sold)
        # Note: MongoDB query still uses raw format, normalization happens in Python
        all_expenses = list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))
        
        # [OK] CRITICAL FIX: Normalize category before filtering
        # CORRECTED COGS CLASSIFICATION (Mar 12, 2026):
        # COGS = Direct costs of providing services (inventory COGS + gateway fees for VAS services)
        cogs_expenses = []
        operating_expenses = []
        for exp in all_expenses:
            category_raw = exp.get('category', '')
            category = normalize_category(category_raw)  # [OK] Normalize here
            if category in ['Cost of Goods Sold', 'Payment Processing Fees']:
                cogs_expenses.append(exp)
            else:
                operating_expenses.append(exp)
        
        total_cogs = sum(exp.get('amount', 0) for exp in cogs_expenses)
        
        # STEP 3: Calculate Operating Expenses total
        total_operating = sum(exp.get('amount', 0) for exp in operating_expenses)
        
        # CALCULATE 3-STEP P&L
        # Step 1: Gross Profit = (Sales Revenue + Other Operating Income) - COGS
        # CRITICAL FIX (Feb 19, 2026): Include Other Income in Gross Profit calculation
        gross_profit = (sales_revenue + other_income) - total_cogs
        gross_margin_pct = (gross_profit / (sales_revenue + other_income) * 100) if (sales_revenue + other_income) > 0 else 0
        
        # Step 2: Operating Profit = Gross Profit - Operating Expenses
        operating_profit = gross_profit - total_operating
        
        # Step 3: Net Profit = Operating Profit (taxes/fees already in operating expenses)
        net_profit = operating_profit
        
        # Get limited data for preview
        incomes = list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes']).sort('date', -1).limit(limit // 2))
        expenses_preview = (cogs_expenses + operating_expenses)[:limit // 2]
        
        # Format data
        data = {
            'incomes': [],
            'expenses': []
        }
        
        for income in incomes:
            category_raw = income.get('category', '')
            category = normalize_category(category_raw)  # [OK] Normalize for display
            data['incomes'].append({
                'date': income.get('date', datetime.utcnow()).isoformat() + 'Z',
                'source': income.get('source', ''),
                'category': category,  # [OK] Always string now
                'amount': income.get('amount', 0),
                'sourceType': income.get('sourceType', 'manual'),  # NEW: Show origin
                'entryType': income.get('entryType')  # NEW: Show classification
            })
        
        for expense in expenses_preview:
            category_raw = expense.get('category', '')
            category = normalize_category(category_raw)  # [OK] Normalize for display
            data['expenses'].append({
                'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                'title': expense.get('title', ''),
                'category': category,  # [OK] Always string now
                'amount': expense.get('amount', 0),
                'sourceType': expense.get('sourceType', 'manual'),  # NEW: Show origin
                'entryType': expense.get('entryType')  # NEW: Show classification
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': len(all_incomes) + len(cogs_expenses) + len(operating_expenses),
            'showing_count': len(incomes) + len(expenses_preview),
            'data': data,
            'summary': {
                # Revenue Breakdown
                'sales_revenue': sales_revenue,
                'other_income': other_income,
                'total_revenue': total_revenue,
                
                # COGS
                'cost_of_goods_sold': total_cogs,
                
                # Gross Profit (The "Aha!" Moment)
                'gross_profit': gross_profit,
                'gross_margin_percentage': round(gross_margin_pct, 2),
                
                # Operating Expenses
                'operating_expenses': total_operating,
                
                # Operating Profit
                'operating_profit': operating_profit,
                
                # Net Profit
                'net_profit': net_profit,
                
                # Legacy fields (for backward compatibility)
                'total_income': total_revenue,
                'total_expenses': total_cogs + total_operating
            },
            'metadata': {
                'calculation_method': '3_step_professional_pl',
                'excludes_personal_expenses': True,
                'gross_margin_note': 'Gross Margin % = (Gross Profit / Sales Revenue) x 100',
                'category_normalization': 'Applied (Feb 19, 2026)'  # [OK] Track fix
            }
        })

    
    def _preview_cash_flow(current_user, start_date, end_date, limit):
        """
        Preview cash flow data with Operating, Investing, and Financing Activities
        
        MODERNIZATION (Feb 18, 2026):
        - Excludes personal expenses (entryType: 'personal')
        - Categorizes cash flows into Operating, Investing, and Financing
        - Shows net cash flow from each activity
        """
        # BASE QUERIES: Exclude personal expenses (Default Business Assumption)
        income_query = {
            'userId': current_user['_id'],
            'status': 'active',
            'isDeleted': False,
            '$or': [
                {'entryType': {'$ne': 'personal'}},
                {'entryType': {'$exists': False}},
                {'entryType': None}
            ]
        }
        
        expense_query = {
            'userId': current_user['_id'],
            'status': 'active',
            'isDeleted': False,
            '$or': [
                {'entryType': {'$ne': 'personal'}},
                {'entryType': {'$exists': False}},
                {'entryType': None}
            ]
        }
        
        # Apply date filters
        if start_date or end_date:
            if start_date:
                income_query['date'] = {'$gte': start_date}
                expense_query['date'] = {'$gte': start_date}
            if end_date:
                income_query.setdefault('date', {})['$lte'] = end_date
                expense_query.setdefault('date', {})['$lte'] = end_date
        
        # Get all business incomes and expenses
        all_incomes = list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes']))
        all_expenses = list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))
        
        # OPERATING ACTIVITIES
        # Cash from sales (all income)
        cash_from_sales = sum(inc.get('amount', 0) for inc in all_incomes)
        
        # Cash paid for COGS
        # CORRECTED COGS CLASSIFICATION (Mar 12, 2026):
        # COGS = Direct costs of providing services (inventory COGS + gateway fees for VAS services)
        cogs_categories = ['Cost of Goods Sold', 'Payment Processing Fees']
        cogs_expenses = [exp for exp in all_expenses if exp.get('category') in cogs_categories]
        cash_paid_cogs = sum(exp.get('amount', 0) for exp in cogs_expenses)
        
        # Cash paid for operating expenses (exclude COGS and asset purchases)
        operating_expenses = [exp for exp in all_expenses 
                            if exp.get('category') not in cogs_categories + ['Asset Purchase']]
        cash_paid_operating = sum(exp.get('amount', 0) for exp in operating_expenses)
        
        net_cash_operating = cash_from_sales - cash_paid_cogs - cash_paid_operating
        
        # INVESTING ACTIVITIES
        # Asset purchases (negative cash flow)
        asset_purchases = [exp for exp in all_expenses if exp.get('category') == 'Asset Purchase']
        cash_paid_assets = sum(exp.get('amount', 0) for exp in asset_purchases)
        
        # Asset sales (positive cash flow) - from income with category 'assetSale'
        asset_sales = [inc for inc in all_incomes if inc.get('category') == 'assetSale']
        cash_from_asset_sales = sum(inc.get('amount', 0) for inc in asset_sales)
        
        net_cash_investing = cash_from_asset_sales - cash_paid_assets
        
        # FINANCING ACTIVITIES
        # Get user data for drawings and contributions
        user = mongo.db.users.find_one({'_id': current_user['_id']})
        drawings = user.get('drawings', 0) if user else 0
        owner_contributions = user.get('ownerContributions', 0) if user else 0
        
        net_cash_financing = owner_contributions - drawings
        
        # TOTAL NET CASH FLOW
        net_cash_flow = net_cash_operating + net_cash_investing + net_cash_financing
        
        # Get limited transactions for preview
        incomes = list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes']).sort('date', -1).limit(limit // 2))
        expenses = list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']).sort('date', -1).limit(limit // 2))
        
        # Format data
        data = {
            'incomes': [],
            'expenses': []
        }
        
        for income in incomes:
            data['incomes'].append({
                'date': income.get('date', datetime.utcnow()).isoformat() + 'Z',
                'source': income.get('source', ''),
                'category': income.get('category', 'other'),
                'amount': income.get('amount', 0),
                'sourceType': income.get('sourceType', 'manual'),
                'entryType': income.get('entryType')
            })
        
        for expense in expenses:
            data['expenses'].append({
                'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                'title': expense.get('title', ''),
                'category': expense.get('category', 'Other'),
                'amount': expense.get('amount', 0),
                'sourceType': expense.get('sourceType', 'manual'),
                'entryType': expense.get('entryType')
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': len(all_incomes) + len(all_expenses),
            'showing_count': len(incomes) + len(expenses),
            'data': data,
            'summary': {
                # Operating Activities
                'operating_activities': {
                    'cash_from_sales': cash_from_sales,
                    'cash_paid_for_cogs': -cash_paid_cogs,
                    'cash_paid_for_operating': -cash_paid_operating,
                    'net_cash_from_operations': net_cash_operating
                },
                # Investing Activities
                'investing_activities': {
                    'cash_from_asset_sales': cash_from_asset_sales,
                    'cash_paid_for_assets': -cash_paid_assets,
                    'net_cash_from_investing': net_cash_investing
                },
                # Financing Activities
                'financing_activities': {
                    'owner_contributions': owner_contributions,
                    'owner_drawings': -drawings,
                    'net_cash_from_financing': net_cash_financing
                },
                # Total
                'net_cash_flow': net_cash_flow,
                
                # Legacy fields (for backward compatibility)
                'total_income': cash_from_sales,
                'total_expenses': cash_paid_cogs + cash_paid_operating + cash_paid_assets
            },
            'metadata': {
                'calculation_method': 'cash_flow_statement',
                'excludes_personal_expenses': True,
                'categories': ['Operating', 'Investing', 'Financing']
            }
        })
    
    def _preview_tax_summary(current_user, start_date, end_date, limit):
        """
        Preview tax summary data with business-only filtering
        
        MODERNIZATION (Feb 18, 2026):
        - Only includes business income (taxable)
        - Only includes business expenses (tax-deductible)
        - Excludes personal transactions from tax calculations
        
        ENHANCEMENT (Feb 28, 2026):
        - Includes PIT statutory deductions (rent, pension, insurance, NHIS, HMO)
        - Shows tax savings from deductions
        - Matches full PDF report calculations
        """
        # BUSINESS-ONLY QUERIES: Only business transactions are taxable/deductible
        income_query = {
            'userId': current_user['_id'],
            'status': 'active',
            'isDeleted': False,
            '$or': [
                {'entryType': {'$ne': 'personal'}},
                {'entryType': {'$exists': False}},
                {'entryType': None}
            ]
        }
        
        expense_query = {
            'userId': current_user['_id'],
            'status': 'active',
            'isDeleted': False,
            '$or': [
                {'entryType': {'$ne': 'personal'}},
                {'entryType': {'$exists': False}},
                {'entryType': None}
            ]
        }
        
        # Apply date filters
        if start_date or end_date:
            if start_date:
                income_query['date'] = {'$gte': start_date}
                expense_query['date'] = {'$gte': start_date}
            if end_date:
                income_query.setdefault('date', {})['$lte'] = end_date
                expense_query.setdefault('date', {})['$lte'] = end_date
        
        # Get all business incomes and expenses
        all_incomes = list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes']))
        all_expenses = list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))
        
        # Calculate totals
        total_income = sum(inc.get('amount', 0) for inc in all_incomes)
        total_expenses = sum(exp.get('amount', 0) for exp in all_expenses)
        gross_taxable_income = total_income - total_expenses
        
        # Get user's tax profile
        user = mongo.db.users.find_one({'_id': current_user['_id']})
        tax_profile = user.get('taxProfile', {})
        tax_type = tax_profile.get('taxType', 'PIT')  # PIT or CIT
        
        # Calculate PIT statutory deductions (only for PIT users)
        statutory_deductions = {
            'rent_relief': 0,
            'pension_contributions': 0,
            'life_insurance': 0,
            'nhis_contributions': 0,
            'hmo_premiums': 0,
            'total': 0
        }
        
        if tax_type == 'PIT':
            # 1. Rent Relief (20% of annual rent, capped at N500,000)
            rent_keywords = ['rent', 'housing', 'accommodation']
            rent_expenses = [exp for exp in all_expenses 
                            if any(keyword in exp.get('category', '').lower() 
                                   for keyword in rent_keywords)]
            annual_rent = sum(exp.get('amount', 0) for exp in rent_expenses)
            rent_relief = min(annual_rent * 0.20, 500000)  # 20% capped at N500k
            statutory_deductions['rent_relief'] = rent_relief
            
            # 2. Pension Contributions (fully deductible)
            pension_keywords = ['pension', 'retirement']
            pension_expenses = [exp for exp in all_expenses 
                               if any(keyword in exp.get('category', '').lower() 
                                      for keyword in pension_keywords)]
            pension_contributions = sum(exp.get('amount', 0) for exp in pension_expenses)
            statutory_deductions['pension_contributions'] = pension_contributions
            
            # 3. Life Insurance Premiums (fully deductible)
            insurance_keywords = ['insurance', 'life insurance']
            insurance_expenses = [exp for exp in all_expenses 
                                 if any(keyword in exp.get('category', '').lower() 
                                        for keyword in insurance_keywords)]
            life_insurance = sum(exp.get('amount', 0) for exp in insurance_expenses)
            statutory_deductions['life_insurance'] = life_insurance
            
            # 4. NHIS contributions (fully deductible)
            nhis_keywords = ['nhis', 'health insurance']
            nhis_expenses = [exp for exp in all_expenses 
                            if any(keyword in exp.get('category', '').lower() 
                                   for keyword in nhis_keywords)]
            nhis_contributions = sum(exp.get('amount', 0) for exp in nhis_expenses)
            statutory_deductions['nhis_contributions'] = nhis_contributions
            
            # 5. HMO premiums (fully deductible)
            hmo_keywords = ['hmo', 'health maintenance']
            hmo_expenses = [exp for exp in all_expenses 
                           if any(keyword in exp.get('category', '').lower() 
                                  for keyword in hmo_keywords)]
            hmo_premiums = sum(exp.get('amount', 0) for exp in hmo_expenses)
            statutory_deductions['hmo_premiums'] = hmo_premiums
            
            # Total statutory deductions
            statutory_deductions['total'] = (
                rent_relief + 
                pension_contributions + 
                life_insurance + 
                nhis_contributions + 
                hmo_premiums
            )
        
        # Adjust taxable income for PIT deductions
        taxable_income = gross_taxable_income - statutory_deductions['total']
        
        # Calculate estimated tax based on tax type
        estimated_tax = 0
        tax_without_deductions = 0
        tax_rate_display = ''
        
        if gross_taxable_income > 0:
            if tax_type == 'CIT':
                # Corporate Income Tax: 30% flat rate
                # Small company exemption: Revenue <=N100M AND Assets <=N250M
                estimated_tax = taxable_income * 0.30
                tax_without_deductions = estimated_tax  # CIT has no statutory deductions
                tax_rate_display = '30% (CIT)'
            else:
                # Personal Income Tax: Progressive rates
                # Calculate tax WITHOUT deductions (for comparison)
                if gross_taxable_income <= 800000:
                    tax_without_deductions = 0
                else:
                    taxable_without = gross_taxable_income - 800000
                    tax_without_deductions = taxable_without * 0.15  # Simplified rate
                
                # Calculate tax WITH deductions (actual tax)
                if taxable_income <= 800000:
                    estimated_tax = 0
                    tax_rate_display = '0% (Below threshold)'
                else:
                    # Simplified progressive calculation
                    taxable = taxable_income - 800000
                    estimated_tax = taxable * 0.15  # Simplified rate
                    tax_rate_display = 'Progressive (PIT)'
        
        effective_rate = (estimated_tax / taxable_income * 100) if taxable_income > 0 else 0
        tax_savings = tax_without_deductions - estimated_tax
        
        # Get limited transactions for preview
        incomes = list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes']).sort('date', -1).limit(limit // 2))
        expenses = list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']).sort('date', -1).limit(limit // 2))
        
        # Format data
        data = {
            'incomes': [],
            'expenses': []
        }
        
        for income in incomes:
            data['incomes'].append({
                'date': income.get('date', datetime.utcnow()).isoformat() + 'Z',
                'source': income.get('source', ''),
                'category': income.get('category', 'other'),
                'amount': income.get('amount', 0),
                'sourceType': income.get('sourceType', 'manual'),
                'entryType': income.get('entryType')
            })
        
        for expense in expenses:
            data['expenses'].append({
                'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                'title': expense.get('title', ''),
                'category': expense.get('category', 'Other'),
                'amount': expense.get('amount', 0),
                'sourceType': expense.get('sourceType', 'manual'),
                'entryType': expense.get('entryType')
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': len(all_incomes) + len(all_expenses),
            'showing_count': len(incomes) + len(expenses),
            'data': data,
            'summary': {
                'total_income': total_income,
                'total_expenses': total_expenses,
                'gross_taxable_income': gross_taxable_income,  # Before deductions
                'statutory_deductions': statutory_deductions,  # NEW: Deduction breakdown
                'taxable_income': taxable_income,  # After deductions
                'estimated_tax': estimated_tax,
                'tax_without_deductions': tax_without_deductions,  # NEW: For comparison
                'tax_savings': tax_savings,  # NEW: Savings from deductions
                'effective_rate': round(effective_rate, 2),
                'tax_type': tax_type,
                'tax_rate_display': tax_rate_display
            },
            'metadata': {
                'calculation_method': 'business_only_tax_with_deductions',
                'excludes_personal_transactions': True,
                'includes_statutory_deductions': tax_type == 'PIT',  # NEW
                'note': 'Only business income is taxable and only business expenses are deductible. PIT users benefit from statutory deductions (rent, pension, insurance, NHIS, HMO).'
            }
        })
    
    def _preview_debtors(current_user, start_date, end_date, limit):
        """Preview debtors data"""
        query = {'userId': current_user['_id']}
        
        total_count = mongo.db.debtors.count_documents(query)
        debtors = list(mongo.db.debtors.find(query, PDF_PROJECTIONS['debtors']).sort('createdAt', -1).limit(limit))
        
        # Calculate summary
        all_debtors = list(mongo.db.debtors.find(query, PDF_PROJECTIONS['debtors']))
        total_owed = sum(d.get('totalOwed', 0) for d in all_debtors)
        total_paid = sum(d.get('totalPaid', 0) for d in all_debtors)
        
        data = []
        for debtor in debtors:
            data.append({
                'id': str(debtor['_id']),
                'name': debtor.get('name', ''),
                'phone': debtor.get('phone', ''),
                'totalOwed': debtor.get('totalOwed', 0),
                'totalPaid': debtor.get('totalPaid', 0),
                'balance': debtor.get('totalOwed', 0) - debtor.get('totalPaid', 0),
                'createdAt': debtor.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_owed': total_owed,
                'total_paid': total_paid,
                'outstanding_balance': total_owed - total_paid,
                'count': total_count
            }
        })
    
    def _preview_creditors(current_user, start_date, end_date, limit):
        """Preview creditors data"""
        query = {'userId': current_user['_id']}
        
        total_count = mongo.db.creditors.count_documents(query)
        creditors = list(mongo.db.creditors.find(query, PDF_PROJECTIONS['creditors']).sort('createdAt', -1).limit(limit))
        
        # Calculate summary
        all_creditors = list(mongo.db.creditors.find(query, PDF_PROJECTIONS['creditors']))
        total_owed = sum(c.get('totalOwed', 0) for c in all_creditors)
        total_paid = sum(c.get('totalPaid', 0) for c in all_creditors)
        
        data = []
        for creditor in creditors:
            data.append({
                'id': str(creditor['_id']),
                'name': creditor.get('name', ''),
                'phone': creditor.get('phone', ''),
                'totalOwed': creditor.get('totalOwed', 0),
                'totalPaid': creditor.get('totalPaid', 0),
                'balance': creditor.get('totalOwed', 0) - creditor.get('totalPaid', 0),
                'createdAt': creditor.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_owed': total_owed,
                'total_paid': total_paid,
                'outstanding_balance': total_owed - total_paid,
                'count': total_count
            }
        })
    
    def _preview_assets(current_user, start_date, end_date, limit):
        """Preview assets data"""
        query = {'userId': current_user['_id']}
        
        total_count = mongo.db.assets.count_documents(query)
        assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']).sort('purchaseDate', -1).limit(limit))
        
        # Calculate summary - check both purchasePrice and purchaseCost for compatibility
        all_assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']))
        total_value = 0
        total_current_value = 0
        
        for a in all_assets:
            # Check both purchasePrice and purchaseCost (backend compatibility)
            cost = a.get('purchasePrice', a.get('purchaseCost', 0))
            # If cost is 0 but currentValue exists, use currentValue (legacy data fix)
            if cost == 0:
                cost = a.get('currentValue', 0)
            
            current_val = a.get('currentValue', cost)
            total_value += cost
            total_current_value += current_val
        
        total_depreciation = total_value - total_current_value
        
        data = []
        for asset in assets:
            # Check both purchasePrice and purchaseCost for backend compatibility
            cost = asset.get('purchasePrice', asset.get('purchaseCost', 0))
            # If cost is 0 but currentValue exists, use currentValue (legacy data fix)
            if cost == 0:
                cost = asset.get('currentValue', 0)
            
            current_val = asset.get('currentValue', cost)
            
            # Get asset name - check both 'assetName' and 'name' fields
            asset_name = asset.get('assetName', asset.get('name', 'Unknown Asset'))
            
            data.append({
                'id': str(asset['_id']),
                'name': asset_name,  # Use the resolved name
                'category': asset.get('category', ''),
                'purchasePrice': cost,  # Use calculated cost, not raw field
                'currentValue': current_val,
                'purchaseDate': asset.get('purchaseDate', datetime.utcnow()).isoformat() + 'Z',
                'depreciationMethod': asset.get('depreciationMethod', 'None')
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_purchase_value': total_value,
                'total_depreciation': total_depreciation,
                'net_book_value': total_current_value,
                'asset_count': total_count  # Use 'asset_count' instead of 'count' to avoid frontend currency formatting
            }
        })
    
    def _preview_asset_depreciation(current_user, start_date, end_date, limit):
        """Preview asset depreciation schedule"""
        query = {'userId': current_user['_id'], 'depreciationMethod': {'$ne': 'None'}}
        
        total_count = mongo.db.assets.count_documents(query)
        assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']).sort('purchaseDate', -1).limit(limit))
        
        # Calculate summary
        all_assets = list(mongo.db.assets.find(query, PDF_PROJECTIONS['assets']))
        total_depreciation = sum(a.get('accumulatedDepreciation', 0) for a in all_assets)
        
        data = []
        for asset in assets:
            data.append({
                'id': str(asset['_id']),
                'name': asset.get('name', ''),
                'purchasePrice': asset.get('purchasePrice', 0),
                'accumulatedDepreciation': asset.get('accumulatedDepreciation', 0),
                'currentValue': asset.get('currentValue', 0),
                'depreciationMethod': asset.get('depreciationMethod', ''),
                'usefulLife': asset.get('usefulLife', 0)
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_depreciation': total_depreciation,
                'count': total_count
            }
        })
    
    def _preview_inventory(current_user, start_date, end_date, limit):
        """Preview inventory data"""
        query = {'userId': current_user['_id']}
        
        total_count = mongo.db.inventory_items.count_documents(query)
        items = list(mongo.db.inventory_items.find(query).sort('createdAt', -1).limit(limit))
        
        # Calculate summary
        all_items = list(mongo.db.inventory_items.find(query))
        total_value = sum(i.get('quantity', 0) * i.get('unitCost', 0) for i in all_items)
        total_quantity = sum(i.get('quantity', 0) for i in all_items)
        
        data = []
        for item in items:
            data.append({
                'id': str(item['_id']),
                'name': item.get('name', ''),
                'sku': item.get('sku', ''),
                'quantity': item.get('quantity', 0),
                'unitCost': item.get('unitCost', 0),
                'sellingPrice': item.get('sellingPrice', 0),
                'totalValue': item.get('quantity', 0) * item.get('unitCost', 0)
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_inventory_value': total_value,
                'total_items': total_quantity,
                'count': total_count
            }
        })
    
    def _preview_credits(current_user, start_date, end_date, limit):
        """Preview FiCore Credits transactions"""
        query = {'userId': current_user['_id']}
        if start_date or end_date:
            query['createdAt'] = {}
            if start_date:
                query['createdAt']['$gte'] = start_date
            if end_date:
                query['createdAt']['$lte'] = end_date
        
        total_count = mongo.db.credit_transactions.count_documents(query)
        transactions = list(mongo.db.credit_transactions.find(query).sort('createdAt', -1).limit(limit))
        
        # Calculate summary with breakdown by source (Feb 9, 2026)
        all_transactions = list(mongo.db.credit_transactions.find(query))
        total_earned = sum(t.get('amount', 0) for t in all_transactions if t.get('amount', 0) > 0)
        total_spent = sum(abs(t.get('amount', 0)) for t in all_transactions if t.get('amount', 0) < 0)
        
        # Credits breakdown by source
        purchased = sum(
            t.get('amount', 0) for t in all_transactions 
            if t.get('amount', 0) > 0 and (
                t.get('metadata', {}).get('purchaseType') or 
                t.get('paymentMethod') == 'paystack' or
                'purchase' in t.get('description', '').lower()
            )
        )
        
        signup_bonus = sum(
            t.get('amount', 0) for t in all_transactions 
            if t.get('amount', 0) > 0 and t.get('operation') == 'signup_bonus'
        )
        
        rewards = sum(
            t.get('amount', 0) for t in all_transactions 
            if t.get('amount', 0) > 0 and (
                t.get('operation') in ['engagement_reward', 'streak_milestone', 'exploration_bonus', 'profile_completion'] or
                any(keyword in t.get('description', '').lower() for keyword in ['reward', 'streak', 'exploration', 'milestone'])
            )
        )
        
        tax_education = sum(
            t.get('amount', 0) for t in all_transactions 
            if t.get('amount', 0) > 0 and (
                t.get('operation') == 'tax_education_progress' or
                any(keyword in t.get('description', '').lower() for keyword in ['tax education', 'tax module'])
            )
        )
        
        other = total_earned - (purchased + signup_bonus + rewards + tax_education)
        if other < 0:
            other = 0.0
        
        data = []
        for txn in transactions:
            data.append({
                'id': str(txn['_id']),
                'type': txn.get('type', ''),
                'amount': txn.get('amount', 0),
                'description': txn.get('description', ''),
                'operation': txn.get('operation', ''),
                'balanceBefore': txn.get('balanceBefore', 0),
                'balanceAfter': txn.get('balanceAfter', 0),
                'createdAt': txn.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_earned': total_earned,
                'total_spent': total_spent,
                'net_change': total_earned - total_spent,
                'count': total_count,
                # NEW: Credits breakdown by source (Feb 9, 2026)
                'earned_breakdown': {
                    'purchased': purchased,
                    'signup_bonus': signup_bonus,
                    'rewards': rewards,
                    'tax_education': tax_education,
                    'other': other
                }
            }
        })
    
    def _preview_statement_of_affairs(current_user, start_date, end_date, limit):
        """
        Preview Statement of Affairs - Comprehensive financial overview
        Combines Balance Sheet, P&L, Tax Summary, and Assets
        
        CRITICAL FIX (Feb 19, 2026):
        - Normalize category format (handle dict vs string)
        - Prevents "'str' object has no attribute 'get'" crash
        """
        try:
            def normalize_category(category):
                """Normalize category to string (handle dict format)"""
                if isinstance(category, dict):
                    return category.get('name', 'Other')
                return category or 'Other'
            
            # Get tax type from request (default to PIT)
            request_data = request.get_json() or {}
            tax_type = request_data.get('taxType', 'PIT').upper()
            
            # 1. Balance Sheet Summary
            # Assets
            assets_query = {'userId': current_user['_id']}
            assets = list(mongo.db.assets.find(assets_query, PDF_PROJECTIONS['assets']))
            total_assets = sum(
                asset.get('currentValue', 0) or asset.get('purchasePrice', 0) or asset.get('purchaseCost', 0)
                for asset in assets
            )
            
            # Inventory
            inventory_query = {'userId': current_user['_id']}
            inventory = list(mongo.db.inventory.find(inventory_query, PDF_PROJECTIONS['inventory']))
            total_inventory = sum(
                item.get('quantity', 0) * item.get('unitCost', 0)
                for item in inventory
            )
            
            # Debtors (Accounts Receivable)
            debtors_query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            debtors = list(mongo.db.debtors.find(debtors_query, PDF_PROJECTIONS['debtors']))
            total_debtors = sum(debtor.get('amount', 0) for debtor in debtors)
            
            # Creditors (Accounts Payable)
            creditors_query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            creditors = list(mongo.db.creditors.find(creditors_query, PDF_PROJECTIONS['creditors']))
            total_creditors = sum(creditor.get('amount', 0) for creditor in creditors)
            
            # 2. P&L Summary
            # CRITICAL FIX (Mar 12, 2026): Exclude liability adjustments from income calculation
            income_query = {
                'userId': current_user['_id'], 
                'status': 'active', 
                'isDeleted': False,
                'sourceType': {'$not': {'$regex': '^liability_adjustment_'}}  # [NEW] Exclude liability adjustments
            }
            expense_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False}
            
            if start_date or end_date:
                income_query['date'] = {}
                expense_query['date'] = {}
                if start_date:
                    income_query['date']['$gte'] = start_date
                    expense_query['date']['$gte'] = start_date
                if end_date:
                    income_query['date']['$lte'] = end_date
                    expense_query['date']['$lte'] = end_date
            
            incomes = list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes']))
            expenses = list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']))
            
            total_income = sum(inc.get('amount', 0) for inc in incomes)
            total_expenses = sum(exp.get('amount', 0) for exp in expenses)
            net_profit = total_income - total_expenses
            
            # 3. Tax Summary
            # Business-only filtering for tax compliance
            business_incomes = [inc for inc in incomes if 'Business' in inc.get('tags', [])]
            business_expenses = [exp for exp in expenses if 'Business' in exp.get('tags', [])]
            
            taxable_income = sum(inc.get('amount', 0) for inc in business_incomes)
            deductible_expenses = sum(exp.get('amount', 0) for exp in business_expenses)
            taxable_profit = taxable_income - deductible_expenses
            
            # Calculate tax based on type
            if tax_type == 'PIT':
                # Personal Income Tax (Progressive bands)
                if taxable_profit <= 300000:
                    tax_due = taxable_profit * 0.07
                elif taxable_profit <= 600000:
                    tax_due = 21000 + (taxable_profit - 300000) * 0.11
                elif taxable_profit <= 1100000:
                    tax_due = 54000 + (taxable_profit - 600000) * 0.15
                elif taxable_profit <= 1600000:
                    tax_due = 129000 + (taxable_profit - 1100000) * 0.19
                elif taxable_profit <= 3200000:
                    tax_due = 224000 + (taxable_profit - 1600000) * 0.21
                else:
                    tax_due = 560000 + (taxable_profit - 3200000) * 0.24
            else:
                # Corporate Income Tax (CIT)
                # Check if exempt (Revenue < N100M AND Assets < N250M)
                is_exempt = taxable_income < 100000000 and total_assets < 250000000
                tax_due = 0 if is_exempt else taxable_profit * 0.30
            
            # 4. Format preview data (first 10 entries from each section)
            preview_incomes = incomes[:10]
            preview_expenses = expenses[:10]
            preview_assets = assets[:10]
            preview_debtors = debtors[:10]
            preview_creditors = creditors[:10]
            
            return jsonify({
                'success': True,
                'preview': True,
                'total_count': len(incomes) + len(expenses) + len(assets) + len(debtors) + len(creditors),
                'showing_count': len(preview_incomes) + len(preview_expenses) + len(preview_assets) + len(preview_debtors) + len(preview_creditors),
                'data': {
                    'incomes': [
                        {
                            'id': str(inc['_id']),
                            'source': inc.get('source', ''),
                            'amount': inc.get('amount', 0),
                            'date': inc.get('date', datetime.utcnow()).isoformat() + 'Z',
                            'category': normalize_category(inc.get('category', 'Other'))  # [OK] Normalize here
                        }
                        for inc in preview_incomes
                    ],
                    'expenses': [
                        {
                            'id': str(exp['_id']),
                            'title': exp.get('title', ''),
                            'amount': exp.get('amount', 0),
                            'date': exp.get('date', datetime.utcnow()).isoformat() + 'Z',
                            'category': normalize_category(exp.get('category', 'Other'))  # [OK] Normalize here
                        }
                        for exp in preview_expenses
                    ],
                    'assets': [
                        {
                            'id': str(asset['_id']),
                            'name': asset.get('name', '') or asset.get('assetName', ''),
                            'category': normalize_category(asset.get('category', '')),  # [OK] Normalize here
                            'currentValue': asset.get('currentValue', 0) or asset.get('purchasePrice', 0) or asset.get('purchaseCost', 0)
                        }
                        for asset in preview_assets
                    ],
                    'debtors': [
                        {
                            'id': str(debtor['_id']),
                            'name': debtor.get('name', '') or debtor.get('customerName', ''),
                            'amount': debtor.get('amount', 0),
                            'dueDate': debtor.get('dueDate', datetime.utcnow()).isoformat() + 'Z'
                        }
                        for debtor in preview_debtors
                    ],
                    'creditors': [
                        {
                            'id': str(creditor['_id']),
                            'name': creditor.get('name', '') or creditor.get('vendorName', ''),
                            'amount': creditor.get('amount', 0),
                            'dueDate': creditor.get('dueDate', datetime.utcnow()).isoformat() + 'Z'
                        }
                        for creditor in preview_creditors
                    ]
                },
                'summary': {
                    'balance_sheet': {
                        'total_assets': total_assets,
                        'total_inventory': total_inventory,
                        'total_debtors': total_debtors,
                        'total_creditors': total_creditors,
                        'net_assets': total_assets + total_inventory + total_debtors - total_creditors
                    },
                    'profit_loss': {
                        'total_income': total_income,
                        'total_expenses': total_expenses,
                        'net_profit': net_profit,
                        'income_count': len(incomes),
                        'expense_count': len(expenses)
                    },
                    'tax_summary': {
                        'tax_type': tax_type,
                        'taxable_income': taxable_income,
                        'deductible_expenses': deductible_expenses,
                        'taxable_profit': taxable_profit,
                        'tax_due': tax_due,
                        'is_exempt': tax_type == 'CIT' and taxable_income < 100000000 and total_assets < 250000000
                    },
                    'assets_summary': {
                        'total_assets': total_assets,
                        'total_inventory': total_inventory,
                        'asset_count': len(assets),
                        'inventory_count': len(inventory)
                    }
                }
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Failed to generate Statement of Affairs preview: {str(e)}'
            }), 500
    
    def _preview_wallet_funding(current_user, start_date, end_date, limit):
        """Preview Wallet Funding transactions"""
        query = {
            'userId': ObjectId(str(current_user['_id'])),
            'type': 'WALLET_FUNDING'
        }
        if start_date or end_date:
            query['createdAt'] = {}
            if start_date:
                query['createdAt']['$gte'] = start_date
            if end_date:
                query['createdAt']['$lte'] = end_date
        
        total_count = mongo.db.vas_transactions.count_documents(query)
        transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1).limit(limit))
        
        # Calculate summary
        all_transactions = list(mongo.db.vas_transactions.find(query))
        total_amount = sum(txn.get('amount', 0) for txn in all_transactions)
        
        data = []
        for txn in transactions:
            data.append({
                'id': str(txn['_id']),
                'amount': txn.get('amount', 0),
                'description': txn.get('description', 'Wallet Funding'),
                'createdAt': txn.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                'status': txn.get('status', 'PENDING')
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_amount': total_amount,
                'count': total_count
            }
        })
    
    def _preview_bill_payments(current_user, start_date, end_date, limit):
        """Preview Bill Payments transactions with VAS breakdown"""
        query = {
            'userId': current_user['_id'],
            'status': 'active',
            'isDeleted': False,
            'sourceType': {'$in': ['vas_electricity', 'vas_cable_tv', 'vas_internet', 'vas_water', 'vas_transportation']}
        }
        if start_date or end_date:
            query['date'] = {}
            if start_date:
                query['date']['$gte'] = start_date
            if end_date:
                query['date']['$lte'] = end_date
        
        total_count = mongo.db.expenses.count_documents(query)
        expenses = list(mongo.db.expenses.find(query, PDF_PROJECTIONS['expenses']).sort('date', -1).limit(limit))
        
        # Calculate summary with VAS breakdown
        all_expenses = list(mongo.db.expenses.find(query, PDF_PROJECTIONS['expenses']))
        bill_payments = {
            'electricity': [],
            'cable_tv': [],
            'internet': [],
            'water': [],
            'transportation': [],
            'other': []
        }
        
        for exp in all_expenses:
            source_type = exp.get('sourceType', '')
            if source_type.startswith('vas_'):
                bill_type = source_type.replace('vas_', '')
                if bill_type in bill_payments:
                    bill_payments[bill_type].append(exp)
                else:
                    bill_payments['other'].append(exp)
        
        summary = {
            'electricity': sum(e.get('amount', 0) for e in bill_payments['electricity']),
            'cable_tv': sum(e.get('amount', 0) for e in bill_payments['cable_tv']),
            'internet': sum(e.get('amount', 0) for e in bill_payments['internet']),
            'water': sum(e.get('amount', 0) for e in bill_payments['water']),
            'transportation': sum(e.get('amount', 0) for e in bill_payments['transportation']),
            'other': sum(e.get('amount', 0) for e in bill_payments['other']),
            'total': sum(e.get('amount', 0) for e in all_expenses),
            'count': total_count
        }
        
        data = []
        for exp in expenses:
            data.append({
                'id': str(exp['_id']),
                'title': exp.get('title', ''),
                'amount': exp.get('amount', 0),
                'date': exp.get('date', datetime.utcnow()).isoformat() + 'Z',
                'sourceType': exp.get('sourceType', ''),
                'category': exp.get('category', {}).get('name', 'Bills')
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': summary
        })
    
    def _preview_airtime_purchases(current_user, start_date, end_date, limit):
        """Preview Airtime Purchases transactions with network grouping"""
        query = {
            'userId': current_user['_id'],
            'status': 'active',
            'isDeleted': False,
            'sourceType': 'vas_airtime'
        }
        if start_date or end_date:
            query['date'] = {}
            if start_date:
                query['date']['$gte'] = start_date
            if end_date:
                query['date']['$lte'] = end_date
        
        total_count = mongo.db.expenses.count_documents(query)
        expenses = list(mongo.db.expenses.find(query, PDF_PROJECTIONS['expenses']).sort('date', -1).limit(limit))
        
        # Calculate summary with network grouping
        all_expenses = list(mongo.db.expenses.find(query, PDF_PROJECTIONS['expenses']))
        networks = {'MTN': [], 'Airtel': [], 'Glo': [], '9mobile': [], 'Other': []}
        
        for exp in all_expenses:
            description = exp.get('description', '').upper()
            if 'MTN' in description:
                networks['MTN'].append(exp)
            elif 'AIRTEL' in description:
                networks['Airtel'].append(exp)
            elif 'GLO' in description:
                networks['Glo'].append(exp)
            elif '9MOBILE' in description or 'ETISALAT' in description:
                networks['9mobile'].append(exp)
            else:
                networks['Other'].append(exp)
        
        summary = {
            'mtn': sum(e.get('amount', 0) for e in networks['MTN']),
            'airtel': sum(e.get('amount', 0) for e in networks['Airtel']),
            'glo': sum(e.get('amount', 0) for e in networks['Glo']),
            '9mobile': sum(e.get('amount', 0) for e in networks['9mobile']),
            'other': sum(e.get('amount', 0) for e in networks['Other']),
            'total': sum(e.get('amount', 0) for e in all_expenses),
            'count': total_count
        }
        
        data = []
        for exp in expenses:
            data.append({
                'id': str(exp['_id']),
                'title': exp.get('title', ''),
                'amount': exp.get('amount', 0),
                'date': exp.get('date', datetime.utcnow()).isoformat() + 'Z',
                'description': exp.get('description', ''),
                'category': exp.get('category', {}).get('name', 'Airtime')
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': summary
        })
    
    def _preview_full_wallet(current_user, start_date, end_date, limit):
        """Preview Full Wallet transactions (all types)"""
        query = {'userId': ObjectId(str(current_user['_id']))}
        if start_date or end_date:
            query['createdAt'] = {}
            if start_date:
                query['createdAt']['$gte'] = start_date
            if end_date:
                query['createdAt']['$lte'] = end_date
        
        total_count = mongo.db.vas_transactions.count_documents(query)
        transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1).limit(limit))
        
        # Calculate summary with type breakdown
        all_transactions = list(mongo.db.vas_transactions.find(query))
        type_breakdown = {}
        for txn in all_transactions:
            txn_type = txn.get('type', 'OTHER')
            if txn_type not in type_breakdown:
                type_breakdown[txn_type] = {'count': 0, 'amount': 0}
            type_breakdown[txn_type]['count'] += 1
            type_breakdown[txn_type]['amount'] += txn.get('amount', 0)
        
        total_amount = sum(txn.get('amount', 0) for txn in all_transactions)
        
        data = []
        for txn in transactions:
            txn_type = txn.get('type', 'OTHER')
            description = txn.get('description', '')
            
            if not description:
                if txn_type == 'WALLET_FUNDING':
                    description = f"Wallet Funding - N{txn.get('amount', 0):,.2f}"
                elif txn_type == 'BILL_PAYMENT':
                    description = f"Bill Payment - N{txn.get('amount', 0):,.2f}"
                else:
                    description = f"{txn_type} - N{txn.get('amount', 0):,.2f}"
            
            data.append({
                'id': str(txn['_id']),
                'type': txn_type,
                'amount': txn.get('amount', 0),
                'description': description,
                'createdAt': txn.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                'status': txn.get('status', 'PENDING')
            })
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': total_count,
            'showing_count': len(data),
            'data': data,
            'summary': {
                'total_amount': total_amount,
                'count': total_count,
                'type_breakdown': type_breakdown
            }
        })
    
    # ============================================================================
    # WALLET REPORTS ENDPOINTS
    # ============================================================================
    
    # Wallet Funding Report - PDF
    @reports_bp.route('/wallet-funding-pdf', methods=['POST'])
    @token_required
    def export_wallet_funding_pdf(current_user):
        """Export Wallet Funding transactions as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'wallet_funding_pdf'
            
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            start_date, end_date = parse_date_range(request_data)

            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
            
            query = {
                'userId': ObjectId(str(current_user['_id'])),
                'type': 'WALLET_FUNDING'
            }
            
            if start_date or end_date:
                query['createdAt'] = {}
                if start_date:
                    query['createdAt']['$gte'] = start_date
                if end_date:
                    query['createdAt']['$lte'] = end_date
            
            transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
            
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': user.get('firstName', ''),
                'lastName': user.get('lastName', ''),
                'email': user.get('email', ''),
                'businessName': user.get('businessName', '')
            }
            
            export_data = {'transactions': []}
            
            for txn in transactions:
                export_data['transactions'].append({
                    'date': txn.get('createdAt', datetime.utcnow()),
                    'reference': txn.get('reference', txn.get('transactionReference', 'N/A')),
                    'amount': txn.get('amount', 0),
                    'fee': txn.get('depositFee', 0),
                    'status': txn.get('status', 'UNKNOWN'),
                    'description': f"Wallet Funding - N{txn.get('amount', 0):,.2f}"
                })
            
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_wallet_funding_report(user_data, export_data, start_date, end_date)
            
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            pdf_buffer.seek(0)
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_wallet_funding_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'wallet_funding_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Wallet Funding PDF: {str(e)}'
            }), 500
    
    # Wallet Funding Report - CSV
    @reports_bp.route('/wallet-funding-csv', methods=['POST'])
    @token_required
    def export_wallet_funding_csv(current_user):
        """Export Wallet Funding transactions as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'wallet_funding_csv'
            
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            start_date, end_date = parse_date_range(request_data)
            
            query = {
                'userId': ObjectId(str(current_user['_id'])),
                'type': 'WALLET_FUNDING'
            }
            
            if start_date or end_date:
                query['createdAt'] = {}
                if start_date:
                    query['createdAt']['$gte'] = start_date
                if end_date:
                    query['createdAt']['$lte'] = end_date
            
            transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            writer.writerow(['FiCore Africa - Wallet Funding Report'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            if start_date and end_date:
                writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
            writer.writerow([])
            
            writer.writerow(['Date', 'Reference', 'Amount (N)', 'Fee (N)', 'Status'])
            total_amount = 0
            total_fees = 0
            
            for txn in transactions:
                date_obj = txn.get('createdAt', datetime.utcnow())
                date_str = date_obj.strftime('%Y-%m-%d %H:%M')
                amount = txn.get('amount', 0)
                fee = txn.get('depositFee', 0)
                
                writer.writerow([
                    date_str,
                    txn.get('reference', txn.get('transactionReference', 'N/A')),
                    f'{amount:,.2f}',
                    f'{fee:,.2f}',
                    txn.get('status', 'UNKNOWN')
                ])
                total_amount += amount
                total_fees += fee
            
            writer.writerow(['', 'Totals:', f'{total_amount:,.2f}', f'{total_fees:,.2f}', ''])
            writer.writerow([])
            
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Funded', f'{total_amount:,.2f}'])
            writer.writerow(['Total Fees', f'{total_fees:,.2f}'])
            writer.writerow(['Number of Transactions', len(transactions)])
            
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            log_export_event(current_user, report_type, 'csv', success=True)
            
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_wallet_funding_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'wallet_funding_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Wallet Funding CSV: {str(e)}'
            }), 500
    
    # Bill Payments Report - PDF
    @reports_bp.route('/bill-payments-pdf', methods=['POST'])
    @token_required
    def export_bill_payments_pdf(current_user):
        """
        Export Bill Payments transactions as PDF with granular VAS breakdown
        
        MODERNIZATION (Feb 18, 2026):
        - Groups bills by VAS type (electricity, cable_tv, internet, water, transportation)
        - Shows granular breakdown instead of generic "Bill Payment"
        - Uses sourceType from expenses for accurate categorization
        """
        try:
            request_data = request.get_json() or {}
            report_type = 'bill_payments_pdf'
            
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            start_date, end_date = parse_date_range(request_data)

            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
            
            # MODERNIZATION: Query expenses with VAS sourceType for granular breakdown
            expense_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False,
                'sourceType': {'$regex': '^vas_(?!airtime|data)'}  # VAS bills (exclude airtime/data)
            }
            
            if start_date or end_date:
                if start_date:
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            # Get all VAS bill expenses
            expenses = list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']).sort('date', -1))
            
            # Group by VAS type
            bill_payments = {
                'electricity': [],
                'cable_tv': [],
                'internet': [],
                'water': [],
                'transportation': [],
                'other': []
            }
            
            for exp in expenses:
                source_type = exp.get('sourceType', '')
                if source_type.startswith('vas_'):
                    bill_type = source_type.replace('vas_', '')
                    if bill_type in bill_payments:
                        bill_payments[bill_type].append(exp)
                    else:
                        bill_payments['other'].append(exp)
            
            # Calculate totals
            summary = {
                'electricity': sum(e.get('amount', 0) for e in bill_payments['electricity']),
                'cable_tv': sum(e.get('amount', 0) for e in bill_payments['cable_tv']),
                'internet': sum(e.get('amount', 0) for e in bill_payments['internet']),
                'water': sum(e.get('amount', 0) for e in bill_payments['water']),
                'transportation': sum(e.get('amount', 0) for e in bill_payments['transportation']),
                'other': sum(e.get('amount', 0) for e in bill_payments['other']),
                'total': sum(e.get('amount', 0) for e in expenses),
                'count': len(expenses)
            }
            
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': user.get('firstName', ''),
                'lastName': user.get('lastName', ''),
                'email': user.get('email', ''),
                'businessName': user.get('businessName', '')
            }
            
            export_data = {
                'transactions': [],
                'bill_payments': bill_payments,
                'summary': summary
            }
            
            # Format all transactions for PDF
            for exp in expenses:
                source_type = exp.get('sourceType', 'vas_other')
                bill_type = source_type.replace('vas_', '').replace('_', ' ').title()
                
                export_data['transactions'].append({
                    'date': exp.get('date', datetime.utcnow()),
                    'reference': exp.get('referenceTransactionId', 'N/A'),
                    'amount': exp.get('amount', 0),
                    'fee': 0,  # Fees are included in amount for VAS
                    'status': 'COMPLETED',
                    'category': bill_type,
                    'description': exp.get('title', f"{bill_type} Payment"),
                    'sourceType': source_type
                })
            
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_bill_payments_report(user_data, export_data, start_date, end_date)
            
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            pdf_buffer.seek(0)
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_bill_payments_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'bill_payments_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Bill Payments PDF: {str(e)}'
            }), 500
    # Bill Payments Report - CSV
    @reports_bp.route('/bill-payments-csv', methods=['POST'])
    @token_required
    def export_bill_payments_csv(current_user):
        """Export Bill Payments transactions as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'bill_payments_csv'
            
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            start_date, end_date = parse_date_range(request_data)
            
            query = {
                'userId': ObjectId(str(current_user['_id'])),
                'type': 'BILL_PAYMENT'
            }
            
            if start_date or end_date:
                query['createdAt'] = {}
                if start_date:
                    query['createdAt']['$gte'] = start_date
                if end_date:
                    query['createdAt']['$lte'] = end_date
            
            transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            writer.writerow(['FiCore Africa - Bill Payments Report'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            if start_date and end_date:
                writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
            writer.writerow([])
            
            writer.writerow(['Date', 'Reference', 'Category', 'Amount (N)', 'Fee (N)', 'Status'])
            total_amount = 0
            total_fees = 0
            
            for txn in transactions:
                date_obj = txn.get('createdAt', datetime.utcnow())
                date_str = date_obj.strftime('%Y-%m-%d %H:%M')
                amount = txn.get('amount', 0)
                fee = txn.get('fee', 0)
                
                writer.writerow([
                    date_str,
                    txn.get('reference', txn.get('transactionReference', 'N/A')),
                    txn.get('category', 'N/A'),
                    f'{amount:,.2f}',
                    f'{fee:,.2f}',
                    txn.get('status', 'UNKNOWN')
                ])
                total_amount += amount
                total_fees += fee
            
            writer.writerow(['', 'Totals:', '', f'{total_amount:,.2f}', f'{total_fees:,.2f}', ''])
            writer.writerow([])
            
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Spent', f'{total_amount:,.2f}'])
            writer.writerow(['Total Fees', f'{total_fees:,.2f}'])
            writer.writerow(['Number of Transactions', len(transactions)])
            
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            log_export_event(current_user, report_type, 'csv', success=True)
            
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_bill_payments_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'bill_payments_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Bill Payments CSV: {str(e)}'
            }), 500
    
    # Airtime Purchases Report - PDF
    @reports_bp.route('/airtime-purchases-pdf', methods=['POST'])
    @token_required
    def export_airtime_purchases_pdf(current_user):
        """
        Export Airtime Purchases transactions as PDF with network grouping
        
        MODERNIZATION (Feb 18, 2026):
        - Groups airtime by network (MTN, Airtel, Glo, 9mobile)
        - Uses sourceType 'vas_airtime' for accurate filtering
        - Shows network-specific breakdown
        """
        try:
            request_data = request.get_json() or {}
            report_type = 'airtime_purchases_pdf'
            
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            start_date, end_date = parse_date_range(request_data)

            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
            
            # MODERNIZATION: Query expenses with sourceType 'vas_airtime'
            expense_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False,
                'sourceType': 'vas_airtime'
            }
            
            if start_date or end_date:
                if start_date:
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            # Get all airtime expenses
            expenses = list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses']).sort('date', -1))
            
            # Group by network (from metadata)
            by_network = {}
            for exp in expenses:
                metadata = exp.get('metadata', {})
                network = metadata.get('network', 'Unknown')
                if network not in by_network:
                    by_network[network] = []
                by_network[network].append(exp)
            
            # Calculate totals by network
            network_summary = {}
            for network, txns in by_network.items():
                network_summary[network] = {
                    'count': len(txns),
                    'total': sum(e.get('amount', 0) for e in txns)
                }
            
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': user.get('firstName', ''),
                'lastName': user.get('lastName', ''),
                'email': user.get('email', ''),
                'businessName': user.get('businessName', '')
            }
            
            export_data = {
                'transactions': [],
                'by_network': by_network,
                'network_summary': network_summary
            }
            
            # Format all transactions for PDF
            for exp in expenses:
                metadata = exp.get('metadata', {})
                network = metadata.get('network', 'Unknown')
                phone = metadata.get('phoneNumber', 'N/A')
                
                export_data['transactions'].append({
                    'date': exp.get('date', datetime.utcnow()),
                    'reference': exp.get('referenceTransactionId', 'N/A'),
                    'amount': exp.get('amount', 0),
                    'fee': 0,  # Fees included in amount
                    'status': 'COMPLETED',
                    'phone': phone,
                    'network': network,
                    'description': f"Airtime - {network} - {phone}",
                    'sourceType': 'vas_airtime'
                })
            
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_airtime_purchases_report(user_data, export_data, start_date, end_date)
            
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            pdf_buffer.seek(0)
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_airtime_purchases_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'airtime_purchases_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Airtime Purchases PDF: {str(e)}'
            }), 500
    
    # Airtime Purchases Report - CSV
    @reports_bp.route('/airtime-purchases-csv', methods=['POST'])
    @token_required
    def export_airtime_purchases_csv(current_user):
        """Export Airtime Purchases transactions as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'airtime_purchases_csv'
            
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            start_date, end_date = parse_date_range(request_data)
            
            query = {
                'userId': ObjectId(str(current_user['_id'])),
                'type': 'AIRTIME_PURCHASE'
            }
            
            if start_date or end_date:
                query['createdAt'] = {}
                if start_date:
                    query['createdAt']['$gte'] = start_date
                if end_date:
                    query['createdAt']['$lte'] = end_date
            
            transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            writer.writerow(['FiCore Africa - Airtime Purchases Report'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            if start_date and end_date:
                writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
            writer.writerow([])
            
            writer.writerow(['Date', 'Reference', 'Phone Number', 'Amount (N)', 'Fee (N)', 'Status'])
            total_amount = 0
            total_fees = 0
            
            for txn in transactions:
                date_obj = txn.get('createdAt', datetime.utcnow())
                date_str = date_obj.strftime('%Y-%m-%d %H:%M')
                amount = txn.get('amount', 0)
                fee = txn.get('fee', 0)
                
                writer.writerow([
                    date_str,
                    txn.get('reference', txn.get('transactionReference', 'N/A')),
                    txn.get('phoneNumber', 'N/A'),
                    f'{amount:,.2f}',
                    f'{fee:,.2f}',
                    txn.get('status', 'UNKNOWN')
                ])
                total_amount += amount
                total_fees += fee
            
            writer.writerow(['', 'Totals:', '', f'{total_amount:,.2f}', f'{total_fees:,.2f}', ''])
            writer.writerow([])
            
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Spent', f'{total_amount:,.2f}'])
            writer.writerow(['Total Fees', f'{total_fees:,.2f}'])
            writer.writerow(['Number of Transactions', len(transactions)])
            
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            log_export_event(current_user, report_type, 'csv', success=True)
            
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_airtime_purchases_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'airtime_purchases_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Airtime Purchases CSV: {str(e)}'
            }), 500
    
    # Full Wallet Report - PDF
    @reports_bp.route('/full-wallet-pdf', methods=['POST'])
    @token_required
    def export_full_wallet_pdf(current_user):
        """Export Full Wallet transactions (all types) as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'full_wallet_pdf'
            
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            start_date, end_date = parse_date_range(request_data)

            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
            
            query = {
                'userId': ObjectId(str(current_user['_id']))
            }
            
            if start_date or end_date:
                query['createdAt'] = {}
                if start_date:
                    query['createdAt']['$gte'] = start_date
                if end_date:
                    query['createdAt']['$lte'] = end_date
            
            transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
            
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': user.get('firstName', ''),
                'lastName': user.get('lastName', ''),
                'email': user.get('email', ''),
                'businessName': user.get('businessName', '')
            }
            
            export_data = {'transactions': []}
            
            for txn in transactions:
                txn_type = txn.get('type', 'UNKNOWN')
                description = txn.get('description', '')
                
                if not description:
                    if txn_type == 'WALLET_FUNDING':
                        description = f"Wallet Funding - N{txn.get('amount', 0):,.2f}"
                    elif txn_type == 'BILL_PAYMENT':
                        description = f"Bill Payment - {txn.get('category', 'N/A')}"
                    elif txn_type == 'AIRTIME_PURCHASE':
                        description = f"Airtime - {txn.get('phoneNumber', 'N/A')}"
                    else:
                        description = txn_type
                
                export_data['transactions'].append({
                    'date': txn.get('createdAt', datetime.utcnow()),
                    'reference': txn.get('reference', txn.get('transactionReference', 'N/A')),
                    'type': txn_type,
                    'amount': txn.get('amount', 0),
                    'fee': txn.get('fee', txn.get('depositFee', 0)),
                    'status': txn.get('status', 'UNKNOWN'),
                    'description': description
                })
            
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_full_wallet_report(user_data, export_data, start_date, end_date)
            
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            pdf_buffer.seek(0)
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_full_wallet_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'full_wallet_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Full Wallet PDF: {str(e)}'
            }), 500
    
    # Full Wallet Report - CSV
    @reports_bp.route('/full-wallet-csv', methods=['POST'])
    @token_required
    def export_full_wallet_csv(current_user):
        """Export Full Wallet transactions (all types) as CSV"""
        try:
            request_data = request.get_json() or {}
            report_type = 'full_wallet_csv'
            
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            start_date, end_date = parse_date_range(request_data)
            
            query = {
                'userId': ObjectId(str(current_user['_id']))
            }
            
            if start_date or end_date:
                query['createdAt'] = {}
                if start_date:
                    query['createdAt']['$gte'] = start_date
                if end_date:
                    query['createdAt']['$lte'] = end_date
            
            transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            writer.writerow(['FiCore Africa - Full Wallet Report'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            if start_date and end_date:
                writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
            writer.writerow([])
            
            writer.writerow(['Date', 'Reference', 'Type', 'Description', 'Amount (N)', 'Fee (N)', 'Status'])
            total_amount = 0
            total_fees = 0
            
            for txn in transactions:
                date_obj = txn.get('createdAt', datetime.utcnow())
                date_str = date_obj.strftime('%Y-%m-%d %H:%M')
                amount = txn.get('amount', 0)
                fee = txn.get('fee', txn.get('depositFee', 0))
                txn_type = txn.get('type', 'UNKNOWN')
                description = txn.get('description', '')
                
                if not description:
                    if txn_type == 'WALLET_FUNDING':
                        description = f"Wallet Funding - N{amount:,.2f}"
                    elif txn_type == 'BILL_PAYMENT':
                        description = f"Bill Payment - {txn.get('category', 'N/A')}"
                    elif txn_type == 'AIRTIME_PURCHASE':
                        description = f"Airtime - {txn.get('phoneNumber', 'N/A')}"
                    else:
                        description = txn_type
                
                writer.writerow([
                    date_str,
                    txn.get('reference', txn.get('transactionReference', 'N/A')),
                    txn_type,
                    description,
                    f'{amount:,.2f}',
                    f'{fee:,.2f}',
                    txn.get('status', 'UNKNOWN')
                ])
                total_amount += amount
                total_fees += fee
            
            writer.writerow(['', 'Totals:', '', '', f'{total_amount:,.2f}', f'{total_fees:,.2f}', ''])
            writer.writerow([])
            
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Amount', f'{total_amount:,.2f}'])
            writer.writerow(['Total Fees', f'{total_fees:,.2f}'])
            writer.writerow(['Number of Transactions', len(transactions)])
            
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            log_export_event(current_user, report_type, 'csv', success=True)
            
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_full_wallet_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'full_wallet_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Full Wallet CSV: {str(e)}'
            }), 500
    
    # ============================================================================
    # BACKGROUND REPORT GENERATION ENDPOINTS (Feb 2026)
    # ============================================================================
    
    @reports_bp.route('/job-status/<job_id>', methods=['GET'])
    @token_required
    def get_report_job_status(current_user, job_id):
        """
        Get status of a background report generation job.
        
        Returns:
        {
            "found": true,
            "jobId": "...",
            "status": "pending|processing|completed|failed",
            "progress": 0-100,
            "message": "...",
            "downloadUrl": "/api/reports/download/{job_id}" (if completed)
        }
        """
        try:
            bg_generator = get_background_generator(mongo.db)
            status = bg_generator.get_job_status(job_id)
            
            if not status['found']:
                return jsonify({
                    'success': False,
                    'message': 'Job not found'
                }), 404
            
            # Verify job belongs to current user
            job = mongo.db.report_jobs.find_one({'jobId': job_id})
            if job and str(job['userId']) != str(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized access to job'
                }), 403
            
            return jsonify({
                'success': True,
                'job': status
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Failed to get job status: {str(e)}'
            }), 500
    
    @reports_bp.route('/download/<job_id>', methods=['GET'])
    @token_required
    def download_report(current_user, job_id):
        """
        Download a completed report file.
        
        This endpoint is called when the job status is 'completed'.
        """
        try:
            # Verify job belongs to current user
            job = mongo.db.report_jobs.find_one({'jobId': job_id})
            
            if not job:
                return jsonify({
                    'success': False,
                    'message': 'Job not found'
                }), 404
            
            if str(job['userId']) != str(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized access to job'
                }), 403
            
            if job['status'] != ReportJobStatus.COMPLETED:
                return jsonify({
                    'success': False,
                    'message': f'Report is not ready yet. Status: {job["status"]}'
                }), 400
            
            # Get file from GridFS
            bg_generator = get_background_generator(mongo.db)
            file_buffer, filename, mimetype = bg_generator.get_file(job_id)
            
            if file_buffer is None:
                return jsonify({
                    'success': False,
                    'message': 'Report file not found'
                }), 404
            
            return send_file(
                file_buffer,
                mimetype=mimetype,
                as_attachment=True,
                download_name=filename
            )
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Failed to download report: {str(e)}'
            }), 500
    
    @reports_bp.route('/my-jobs', methods=['GET'])
    @token_required
    def get_my_report_jobs(current_user):
        """
        Get list of recent report jobs for current user.
        
        Query params:
        - limit: Number of jobs to return (default: 10, max: 50)
        """
        try:
            limit = min(int(request.args.get('limit', 10)), 50)
            
            bg_generator = get_background_generator(mongo.db)
            jobs = bg_generator.get_user_jobs(current_user['_id'], limit=limit)
            
            return jsonify({
                'success': True,
                'jobs': jobs,
                'count': len(jobs)
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Failed to get jobs: {str(e)}'
            }), 500
    

    # ============================================================================
    # STATEMENT OF AFFAIRS REPORT - COMPREHENSIVE BUSINESS REPORT
    # ============================================================================
    
    @reports_bp.route('/statement-of-affairs-pdf', methods=['POST'])
    @token_required
    def export_statement_of_affairs_pdf(current_user):
        """Export comprehensive Statement of Affairs as PDF"""
        try:
            request_data = request.get_json() or {}
            report_type = 'statement_of_affairs_pdf'
            
            # Get tax type from request (default to PIT)
            tax_type = request_data.get('taxType', 'PIT').upper()
            if tax_type not in ['PIT', 'CIT']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tax type. Must be either PIT or CIT'
                }), 400
            
            # Get tag filter (default to 'business' for compliance reports)
            tag_filter = request_data.get('tagFilter', 'business').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter. Must be one of: business, personal, all, untagged'
                }), 400
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # OPTIMIZATION: Define cache parameters for PDF caching (Feb 25, 2026)
            cache_params = {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'tag_filter': tag_filter,
                'tax_type': tax_type
            }
            
            # Build queries with tag filtering
            # MODERNIZATION (Feb 18, 2026): Exclude personal expenses (Default Business Assumption)
            # [OK] CRITICAL FIX (Mar 9, 2026): Exclude Capital Contributions and Capital Expenditures from P&L
            # CRITICAL FIX (Mar 12, 2026): Exclude liability adjustments from income calculation
            income_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False,
                'excludeFromProfitLoss': {'$ne': True},  # [OK] Exclude capital contributions
                'sourceType': {'$not': {'$regex': '^liability_adjustment_'}},  # [NEW] Exclude liability adjustments
                '$or': [
                    {'entryType': {'$ne': 'personal'}},
                    {'entryType': {'$exists': False}},
                    {'entryType': None}
                ]
            }
            expense_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False,
                'excludeFromProfitLoss': {'$ne': True},  # [OK] Exclude capital expenditures
                '$or': [
                    {'entryType': {'$ne': 'personal'}},
                    {'entryType': {'$exists': False}},
                    {'entryType': None}
                ]
            }
            asset_query = {
                'userId': current_user['_id'],
                'status': 'active'
            }
            debtors_query = {
                'userId': current_user['_id'],
                'status': {'$ne': 'paid'}
            }
            creditors_query = {
                'userId': current_user['_id'],
                'status': {'$ne': 'paid'}
            }
            inventory_query = {
                'userId': current_user['_id']
            }
            
            # Apply legacy tag filtering (for backward compatibility)
            if tag_filter == 'business':
                income_query['entryType'] = 'business'
                expense_query['entryType'] = 'business'
            elif tag_filter == 'personal':
                # Override: If user explicitly requests personal, show personal
                income_query = {
                    'userId': current_user['_id'],
                    'status': 'active',
                    'isDeleted': False,
                    'entryType': 'personal'
                }
                expense_query = {
                    'userId': current_user['_id'],
                    'status': 'active',
                    'isDeleted': False,
                    'entryType': 'personal'
                }
            elif tag_filter == 'untagged':
                income_query['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
                expense_query['$or'] = [
                    {'entryType': {'$exists': False}},
                    {'entryType': {'$size': 0}},
                    {'entryType': None}
                ]
            
            # Apply date filtering
            # CRITICAL FIX (Feb 22, 2026): Balance Sheet items (assets, debtors, creditors, inventory)
            # are CUMULATIVE and should NOT be filtered by date range.
            # Only P&L items (income, expenses) should be filtered by date range.
            # 
            # Accounting Principle: Balance Sheet = Point-in-time snapshot (cumulative from beginning)
            #                       Income Statement = Period summary (start_date to end_date)
            if start_date or end_date:
                if start_date:
                    income_query['date'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                    # [ERROR] REMOVED: asset_query['purchaseDate'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('date', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
                    # [ERROR] REMOVED: asset_query.setdefault('purchaseDate', {})['$lte'] = end_date
            
            # NOTE: Assets, Debtors, Creditors, Inventory are NOT date-filtered
            # They are cumulative (all entries from beginning of time)
            # NBV calculation will use end_date as "as of" date for depreciation
            
            # Fetch all data in parallel (6 collections)
            results = fetch_collections_parallel({
                'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),
                'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses'])),
                'assets': lambda: list(mongo.db.assets.find(asset_query, PDF_PROJECTIONS['assets'])),
                'debtors': lambda: list(mongo.db.debtors.find(debtors_query, PDF_PROJECTIONS['debtors'])),
                'creditors': lambda: list(mongo.db.creditors.find(creditors_query, PDF_PROJECTIONS['creditors'])),
                'inventory': lambda: list(mongo.db.inventory.find(inventory_query, PDF_PROJECTIONS['inventory']))
            }, max_workers=6)
            
            incomes = results['incomes']
            expenses = results['expenses']
            assets = results['assets']
            debtors = results['debtors']
            creditors = results['creditors']
            inventory = results['inventory']
            
            # Prepare user data
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', ''),
                'businessName': user.get('businessName', '') if user else '',
                'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
            }
            
            # Get user's registered tax profile (for watermark comparison)
            user_tax_profile = user.get('taxProfile', {}) if user else {}
            profile_tax_type = user_tax_profile.get('type', 'PIT').upper() if user_tax_profile else 'PIT'
            
            # Prepare financial data
            financial_data = {
                'incomes': incomes,
                'expenses': expenses
            }
            
            # MODERNIZATION (Feb 18, 2026): Calculate 3-Step P&L
            # CORRECTED REVENUE CLASSIFICATION (Mar 12, 2026):
            # Sales Revenue = What we actually sell/earn (VAS Commissions + Inventory Sales + Subscriptions + FC Purchases)
            # Other Income = Internal accounting (consumed promotional spends, grants, interest)
            
            # CRITICAL FIX (Mar 13, 2026): Get VAS commissions from vas_transactions.providerCommission
            # This matches the treasury dashboard pattern and is the authoritative source
            vas_commission_data = get_vas_commissions_from_transactions(
                mongo, current_user['_id'], start_date, end_date
            )
            vas_commission_revenue = vas_commission_data['total_commission']
            
            # Define what constitutes "Sales Revenue" (actual business revenue)
            # UPDATED: Remove 'vas_commission' from incomes query since we get it from vas_transactions
            sales_revenue_sources = [
                'vas_commission',                    # VAS commission income (REAL revenue) ✅
                'deposit_fee',               # Deposit fees (MOST RELIABLE revenue) ✅
                'inventory_sale',                    # Inventory sales (when we have them) ✅
                # REMOVED: fc_purchase_revenue_recognition (fake test revenue)
                # REMOVED: subscription_purchase_revenue_recognition (fake test revenue)
            ]
            
            # Define what constitutes "Other Income" (internal accounting, not real external revenue)
            other_income_sources = [
                'fc_consumption',                    # Consumed promotional FC spends (internal) ✅
                'fee_waiver_consumption',           # Consumed promotional fee waivers (internal) ✅
                'subscription_consumption',         # Consumed promotional subscriptions (internal) ✅
                'manual',                          # Manual entries (could be grants, interest, etc.) ✅
                'voice',                           # Voice entries (could be grants, interest, etc.) ✅
            ]
            
            # Calculate Sales Revenue from incomes collection (including VAS commissions)
            sales_revenue = sum(
                inc.get('amount', 0) for inc in incomes 
                if inc.get('sourceType') in sales_revenue_sources
            )
            
            # Calculate Other Income (internal accounting, not real external revenue)
            other_income = sum(
                inc.get('amount', 0) for inc in incomes 
                if inc.get('sourceType') in other_income_sources
            )
            total_income = sales_revenue + other_income
            
            # Separate COGS from Operating Expenses
            # CORRECTED COGS CLASSIFICATION (Mar 12, 2026):
            # COGS = Direct costs of providing services (inventory COGS + gateway fees for VAS services)
            cogs_categories = ['Cost of Goods Sold', 'Payment Processing Fees']
            cogs_expenses = [exp for exp in expenses if exp.get('category') in cogs_categories]
            operating_expenses = [exp for exp in expenses if exp.get('category') not in cogs_categories]
            
            total_cogs = sum(exp.get('amount', 0) for exp in cogs_expenses)
            total_operating = sum(exp.get('amount', 0) for exp in operating_expenses)
            total_expenses = total_cogs + total_operating
            
            # Calculate 3-Step P&L
            # CRITICAL FIX (Feb 19, 2026): Include Other Income in Gross Profit calculation
            gross_profit = (sales_revenue + other_income) - total_cogs
            gross_margin_pct = (gross_profit / (sales_revenue + other_income) * 100) if (sales_revenue + other_income) > 0 else 0
            operating_profit = gross_profit - total_operating
            net_income = operating_profit  # Net Profit
            
            # Group VAS expenses by type for granular breakdown
            vas_expenses = {
                'airtime': [],
                'data': [],
                'electricity': [],
                'cable_tv': [],
                'internet': [],
                'water': [],
                'transportation': [],
                'other': []
            }
            
            for exp in expenses:
                source_type = exp.get('sourceType', '')
                if source_type.startswith('vas_'):
                    vas_type = source_type.replace('vas_', '')
                    if vas_type in vas_expenses:
                        vas_expenses[vas_type].append(exp)
                    else:
                        vas_expenses['other'].append(exp)
            
            # Calculate VAS totals
            vas_totals = {
                'airtime': sum(e.get('amount', 0) for e in vas_expenses['airtime']),
                'data': sum(e.get('amount', 0) for e in vas_expenses['data']),
                'electricity': sum(e.get('amount', 0) for e in vas_expenses['electricity']),
                'cable_tv': sum(e.get('amount', 0) for e in vas_expenses['cable_tv']),
                'internet': sum(e.get('amount', 0) for e in vas_expenses['internet']),
                'water': sum(e.get('amount', 0) for e in vas_expenses['water']),
                'transportation': sum(e.get('amount', 0) for e in vas_expenses['transportation']),
                'other': sum(e.get('amount', 0) for e in vas_expenses['other']),
                'total': sum(sum(e.get('amount', 0) for e in vas_expenses[k]) for k in vas_expenses)
            }
            
            # Calculate current assets and liabilities
            debtors_value = sum(d.get('amount', 0) for d in debtors)
            creditors_value = sum(c.get('amount', 0) for c in creditors)
            inventory_value = sum(i.get('quantity', 0) * i.get('unitCost', 0) for i in inventory)
            
            # CRITICAL FIX (Feb 19, 2026): Use calculated Cash/Bank balance from Cash/Bank Management System
            # This replaces the old ficoreWalletBalance which was just the VAS wallet
            # New system uses: Opening Balance + Income - Expenses - Drawings + Capital
            # CRITICAL FIX (Feb 27, 2026): Use OPENING cash balance for Balance Sheet
            # The Balance Sheet shows position at a point in time (opening balances)
            # Net profit is added to equity separately, so we don't double-count
            # Formula: Assets (opening cash + fixed assets) = Liabilities + Equity (opening + net profit)
            opening_cash_balance = user.get('openingCashBalance', 0.0) if user else 0.0
            
            # Get opening equity and drawings (if tracked)
            # CRITICAL FIX (Feb 28, 2026): Always use stored opening equity if set
            # Only calculate from assets if opening equity is NOT set
            opening_equity_stored = user.get('openingEquity', 0) if user else 0
            
            if opening_equity_stored > 0:
                # User has explicitly set opening equity - use it
                opening_equity = opening_equity_stored
            elif len(assets) > 0:
                # Opening equity not set but assets exist
                # Calculate opening equity from fixed assets (capital injected to buy assets)
                total_assets_original_cost = sum(
                    asset.get('purchasePrice', 0) or asset.get('purchaseCost', 0) 
                    for asset in assets
                )
                # Opening Equity = Assets - Liabilities (at start of period)
                # Assuming no opening liabilities for simplicity
                opening_equity = total_assets_original_cost
            else:
                # No opening equity set and no assets
                opening_equity = 0
            
            drawings = user.get('drawings', 0) if user else 0
            
            # CRITICAL FIX (Feb 27, 2026): Get capital contributions from user field (synced automatically)
            capital = user.get('capital', 0) if user else 0
            
            # CRITICAL FIX (Feb 27, 2026): Get total outstanding loans
            loans_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            loans = list(mongo.db.loans.find(loans_query))
            
            # Calculate outstanding balance for each loan
            total_loans_outstanding = 0.0
            for loan in loans:
                loan_id = loan['_id']
                
                # Get total principal repaid
                repayments_query = {
                    'userId': current_user['_id'],
                    'loanId': loan_id,
                    'status': 'completed',
                    'isDeleted': False
                }
                repayments = list(mongo.db.loan_payments.find(repayments_query))
                total_principal_repaid = sum([r.get('principalAmount', 0.0) for r in repayments])
                
                # Calculate outstanding
                outstanding = loan.get('loanAmount', 0.0) - total_principal_repaid
                total_loans_outstanding += outstanding
            
            # Get tax paid (if tracked)
            tax_paid = user.get('taxPaid', 0) if user else 0
            
            # CRITICAL FIX (Mar 12, 2026): Calculate FC Credit, Subscription, and Fee Waiver liabilities
            # Import the liability calculation function
            from utils.liability_calculator import calculate_total_liabilities
            
            # PRIVACY FIX: Pass current user ID to filter liabilities to this user only
            liability_result = calculate_total_liabilities(mongo, current_user['_id'])
            fc_credit_liabilities = 0
            subscription_liabilities = 0
            fee_waiver_liabilities = 0
            
            if liability_result['success']:
                fc_credit_liabilities = liability_result.get('fc_credit_liabilities', {}).get('total', 0)
                subscription_liabilities = liability_result.get('subscription_liabilities', {}).get('total', 0)
                fee_waiver_liabilities = liability_result.get('fee_waiver_liabilities', {}).get('total', 0)
            
            # Prepare tax data with current assets/liabilities and 3-Step P&L
            tax_data = {
                # Revenue Breakdown
                'sales_revenue': sales_revenue,
                'other_income': other_income,
                'total_income': total_income,
                
                # COGS
                'cost_of_goods_sold': total_cogs,
                
                # Gross Profit
                'gross_profit': gross_profit,
                'gross_margin_percentage': gross_margin_pct,
                
                # Operating Expenses
                'operating_expenses': total_operating,
                
                # Operating Profit
                'operating_profit': operating_profit,
                
                # Net Income (for equity calculation)
                'net_income': net_income,
                
                # Legacy fields (for backward compatibility)
                'deductible_expenses': total_expenses,
                
                # Tax info
                'tax_type': tax_type,
                'tax_paid': tax_paid,
                
                # Current Assets
                'inventory_value': inventory_value,
                'debtors_value': debtors_value,
                'cash_balance': opening_cash_balance,  # CRITICAL: Opening balance, not current
                
                # Current Liabilities
                'creditors_value': creditors_value,
                
                # Counts
                'inventory_count': len(inventory),
                'debtors_count': len(debtors),
                'creditors_count': len(creditors),
                
                # Equity Components
                'opening_equity': opening_equity,
                'drawings': drawings,
                'capital': capital,  # NEW (Feb 27, 2026): Capital contributions
                
                # Liabilities Components
                'loans_outstanding': total_loans_outstanding,  # NEW (Feb 27, 2026): Outstanding loans
                
                # CRITICAL FIX (Mar 12, 2026): Include FC Credit, Subscription, and Fee Waiver liabilities
                'fc_credit_liabilities': fc_credit_liabilities,
                'subscription_liabilities': subscription_liabilities,
                'fee_waiver_liabilities': fee_waiver_liabilities,
                
                # VAS Breakdown (Granular Utility Reporting)
                'vas_breakdown': vas_totals,
                'vas_expenses': vas_expenses  # Detailed items for each category
            }
            
            # CRITICAL: Calculate asset NBV as of endDate (not current date)
            # This ensures historical accuracy for mid-period reports
            from datetime import datetime, timezone, timedelta
            
            # Determine the "as of" date for depreciation calculation
            calculation_date = end_date if end_date else datetime.now(timezone.utc)
            
            # Recalculate NBV for each asset as of the calculation_date
            assets_data = []
            for asset in assets:
                # Get original values
                original_cost = asset.get('purchasePrice', 0) or asset.get('purchaseCost', 0)
                purchase_date_raw = asset.get('purchaseDate')
                useful_life_years = asset.get('usefulLifeYears', 5)
                
                # Parse purchase date
                if isinstance(purchase_date_raw, str):
                    try:
                        purchase_date = datetime.fromisoformat(purchase_date_raw.replace('Z', ''))
                    except:
                        purchase_date = datetime.now(timezone.utc)
                elif isinstance(purchase_date_raw, datetime):
                    purchase_date = purchase_date_raw
                else:
                    purchase_date = datetime.now(timezone.utc)
                
                # Calculate years elapsed as of calculation_date
                years_elapsed = (calculation_date - purchase_date).days / 365.25
                
                # Calculate depreciation (straight-line method)
                annual_depreciation = original_cost / useful_life_years if useful_life_years > 0 else 0
                accumulated_depreciation = min(annual_depreciation * years_elapsed, original_cost)
                
                # Calculate NBV as of calculation_date
                nbv_as_of_date = max(original_cost - accumulated_depreciation, 1.0 if asset.get('status') == 'active' else 0)
                
                # Create asset dict with recalculated NBV
                asset_data = dict(asset)
                asset_data['currentValue'] = nbv_as_of_date
                asset_data['accumulatedDepreciation'] = accumulated_depreciation
                assets_data.append(asset_data)
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_statement_of_affairs(
                user_data=user_data,
                financial_data=financial_data,
                tax_data=tax_data,
                assets_data=assets_data,
                start_date=start_date,
                end_date=end_date,
                tax_type=tax_type,
                profile_tax_type=profile_tax_type,  # NEW: Pass user's registered tax type for watermark
                tag_filter=tag_filter
            )
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
            # Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_statement_of_affairs_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'statement_of_affairs_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Statement of Affairs PDF: {str(e)}'
            }), 500
    
    @reports_bp.route('/statement-of-affairs-pdf-async', methods=['POST'])
    @token_required
    def export_statement_of_affairs_pdf_async(current_user):
        """Generate Statement of Affairs PDF in background (PRIORITY ENDPOINT)"""
        try:
            print(f"[INFO] SOA ASYNC: Starting for user {current_user['_id']}")
            request_data = request.get_json() or {}
            report_type = 'statement_of_affairs_pdf'
            
            # Get tax type and tag filter
            tax_type = request_data.get('taxType', 'PIT').upper()
            print(f"[INFO] SOA ASYNC: Tax type = {tax_type}")
            if tax_type not in ['PIT', 'CIT']:
                print(f"[ERROR] SOA ASYNC: Invalid tax type {tax_type}")
                return jsonify({
                    'success': False,
                    'message': 'Invalid tax type. Must be either PIT or CIT'
                }), 400
            
            tag_filter = request_data.get('tagFilter', 'business').lower()
            print(f"[INFO] SOA ASYNC: Tag filter = {tag_filter}")
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                print(f"[ERROR] SOA ASYNC: Invalid tag filter {tag_filter}")
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter'
                }), 400
            
            # Check credits (fast)
            print(f"[INFO] SOA ASYNC: Checking credits...")
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            print(f"[INFO] SOA ASYNC: Credits check - has_access={has_access}, is_premium={is_premium}, balance={current_balance}, cost={credit_cost}")
            
            if not has_access:
                print(f"[ERROR] SOA ASYNC: Insufficient credits")
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse parameters
            print(f"[INFO] SOA ASYNC: Parsing date range...")
            start_date, end_date = parse_date_range(request_data)
            print(f"[INFO] SOA ASYNC: Date range = {start_date} to {end_date}")
            
            # Create background job
            print(f"[INFO] SOA ASYNC: Creating background job...")
            bg_generator = get_background_generator(mongo.db)
            job_id = bg_generator.create_job(
                user_id=current_user['_id'],
                report_type=report_type,
                report_format='pdf',
                params={
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None,
                    'tag_filter': tag_filter,
                    'tax_type': tax_type
                }
            )
            print(f"[OK] SOA ASYNC: Job created with ID = {job_id}")
            
            # Define generation function
            def generate_statement_of_affairs_pdf():
                try:
                    print(f"[SUCCESS] SOA GENERATION: Starting for job {job_id}")
                    
                    # Build queries (USER DATA ONLY - NO BUSINESS DATA)
                    print(f"[SUCCESS] SOA GENERATION: Building queries...")
                    # CRITICAL FIX (Mar 9, 2026): Exclude capital contributions/expenditures from P&L
                    income_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False, 'excludeFromProfitLoss': {'$ne': True}}
                    expense_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False, 'excludeFromProfitLoss': {'$ne': True}}
                    asset_query = {'userId': current_user['_id'], 'status': 'active'}
                    debtors_query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
                    creditors_query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
                    inventory_query = {'userId': current_user['_id']}
                    
                    # Apply tag filtering
                    print(f"[SUCCESS] SOA GENERATION: Applying tag filter = {tag_filter}")
                    if tag_filter == 'business':
                        income_query['entryType'] = 'business'
                        expense_query['entryType'] = 'business'
                    elif tag_filter == 'personal':
                        income_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False, 'entryType': 'personal', 'excludeFromProfitLoss': {'$ne': True}}
                        expense_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False, 'entryType': 'personal', 'excludeFromProfitLoss': {'$ne': True}}
                    
                    # Apply date filtering (only for P&L items)
                    if start_date or end_date:
                        print(f"[SUCCESS] SOA GENERATION: Applying date filter...")
                        if start_date:
                            income_query['date'] = {'$gte': start_date}
                            expense_query['date'] = {'$gte': start_date}
                        if end_date:
                            income_query.setdefault('date', {})['$lte'] = end_date
                            expense_query.setdefault('date', {})['$lte'] = end_date
                    
                    # Fetch all data in parallel (USER DATA ONLY - NO BUSINESS DATA)
                    print(f"[SUCCESS] SOA GENERATION: Fetching data from 6 collections...")
                    results = fetch_collections_parallel({
                        'incomes': lambda: list(mongo.db.incomes.find(income_query, PDF_PROJECTIONS['incomes'])),
                        'expenses': lambda: list(mongo.db.expenses.find(expense_query, PDF_PROJECTIONS['expenses'])),
                        'assets': lambda: list(mongo.db.assets.find(asset_query, PDF_PROJECTIONS['assets'])),
                        'debtors': lambda: list(mongo.db.debtors.find(debtors_query, PDF_PROJECTIONS['debtors'])),
                        'creditors': lambda: list(mongo.db.creditors.find(creditors_query, PDF_PROJECTIONS['creditors'])),
                        'inventory': lambda: list(mongo.db.inventory.find(inventory_query, PDF_PROJECTIONS['inventory']))
                    }, max_workers=6)
                    
                    # Use only user transactions (NO business data mixing)
                    incomes = results['incomes']
                    expenses = results['expenses']
                    assets = results['assets']
                    debtors = results['debtors']
                    creditors = results['creditors']
                    inventory = results['inventory']
                    
                    print(f"[OK] SOA GENERATION: Data fetched - {len(incomes)} incomes, {len(expenses)} expenses, {len(assets)} assets, {len(debtors)} debtors, {len(creditors)} creditors, {len(inventory)} inventory (USER DATA ONLY)")
                    
                    # Prepare user data
                    print(f"[SUCCESS] SOA GENERATION: Preparing user data...")
                    user = mongo.db.users.find_one({'_id': current_user['_id']})
                    user_data = {
                        'firstName': current_user.get('firstName', ''),
                        'lastName': current_user.get('lastName', ''),
                        'email': current_user.get('email', ''),
                        'businessName': user.get('businessName', '') if user else '',
                        'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
                    }
                    print(f"[OK] SOA GENERATION: User data prepared for {user_data.get('firstName')} {user_data.get('lastName')}")
                    
                    # Calculate financial metrics
                    print(f"[SUCCESS] SOA GENERATION: Calculating financial metrics...")
                    total_income = sum(inc.get('amount', 0) for inc in incomes)
                    total_expenses = sum(exp.get('amount', 0) for exp in expenses)
                    debtors_value = sum(d.get('amount', 0) for d in debtors)
                    creditors_value = sum(c.get('amount', 0) for c in creditors)
                    inventory_value = sum(i.get('quantity', 0) * i.get('unitCost', 0) for i in inventory)
                    
                    print(f"[OK] SOA GENERATION: Metrics - Income: N{total_income:,.2f}, Expenses: N{total_expenses:,.2f}, Debtors: N{debtors_value:,.2f}, Creditors: N{creditors_value:,.2f}, Inventory: N{inventory_value:,.2f}")
                    
                    # Get opening cash balance (not current calculated balance)
                    print(f"[SUCCESS] SOA GENERATION: Getting opening cash balance...")
                    user = mongo.db.users.find_one({'_id': current_user['_id']})
                    cash_balance = user.get('openingCashBalance', 0.0) if user else 0.0
                    print(f"[OK] SOA GENERATION: Opening cash balance = N{cash_balance:,.2f}")
                    
                    # Calculate 3-Step P&L (align with SOA sync endpoint)
                    print(f"[SUCCESS] SOA GENERATION: Calculating 3-Step P&L...")
                    # CORRECTED REVENUE CLASSIFICATION (Mar 12, 2026):
                    # Sales Revenue = What we actually sell/earn (VAS Commissions + Inventory Sales + Subscriptions + FC Purchases)
                    # Other Income = Internal accounting (consumed promotional spends, grants, interest)
                    
                    # CRITICAL FIX (Mar 13, 2026): Get VAS commissions from vas_transactions.providerCommission
                    # This matches the treasury dashboard pattern and is the authoritative source
                    vas_commission_data = get_vas_commissions_from_transactions(
                        mongo, current_user['_id'], start_date, end_date
                    )
                    vas_commission_revenue = vas_commission_data['total_commission']
                    
                    # Define what constitutes "Sales Revenue" (actual business revenue)
                    # UPDATED: Remove 'vas_commission' from incomes query since we get it from vas_transactions
                    sales_revenue_sources = [
                        'inventory_sale',                    # Inventory sales ✅
                        'deposit_fee',                       # Deposit fees (single source of truth) ✅
                        'subscription_purchase_payment_received',  # Subscription payments ✅
                        'subscription_purchase_revenue_recognition',  # Subscription revenue ✅
                        'fc_purchase_payment_received',      # FC purchase payments ✅
                        'fc_purchase_revenue_recognition',   # FC purchase revenue ✅
                    ]
                    
                    # Define what constitutes "Other Income" (internal accounting, not real external revenue)
                    other_income_sources = [
                        'fc_consumption',                    # Consumed promotional FC spends (internal) ✅
                        'fee_waiver_consumption',           # Consumed promotional fee waivers (internal) ✅
                        'subscription_consumption',         # Consumed promotional subscriptions (internal) ✅
                        'manual',                          # Manual entries (could be grants, interest, etc.) ✅
                        'voice',                           # Voice entries (could be grants, interest, etc.) ✅
                    ]
                    
                    # Calculate Sales Revenue from incomes collection (excluding VAS commissions)
                    sales_revenue_from_incomes = sum(
                        inc.get('amount', 0) for inc in incomes 
                        if inc.get('sourceType') in sales_revenue_sources
                    )
                    
                    # Total Sales Revenue = VAS Commissions + Other Sales Revenue
                    sales_revenue = vas_commission_revenue + sales_revenue_from_incomes
                    
                    # Calculate Other Income (internal accounting, not real external revenue)
                    other_income = sum(
                        inc.get('amount', 0) for inc in incomes 
                        if inc.get('sourceType') in other_income_sources
                    )
                    
                    # CORRECTED COGS CLASSIFICATION (Mar 12, 2026):
                    # COGS = Direct costs of providing services (inventory COGS + gateway fees for VAS services)
                    cogs_categories = ['Cost of Goods Sold', 'Payment Processing Fees']
                    cogs_expenses = [exp for exp in expenses if exp.get('category') in cogs_categories]
                    operating_expenses = [exp for exp in expenses if exp.get('category') not in cogs_categories]
                    
                    total_cogs = sum(exp.get('amount', 0) for exp in cogs_expenses)
                    total_operating = sum(exp.get('amount', 0) for exp in operating_expenses)
                    
                    gross_profit = (sales_revenue + other_income) - total_cogs
                    gross_margin_pct = (gross_profit / (sales_revenue + other_income) * 100) if (sales_revenue + other_income) > 0 else 0
                    operating_profit = gross_profit - total_operating
                    net_income = operating_profit
                    
                    print(f"[OK] SOA GENERATION: 3-Step P&L - Sales: N{sales_revenue:,.2f}, Other: N{other_income:,.2f}, COGS: N{total_cogs:,.2f}, Gross: N{gross_profit:,.2f}, Operating: N{total_operating:,.2f}, Net: N{net_income:,.2f}")
                    
                    # Prepare comprehensive data structure
                    print(f"[SUCCESS] SOA GENERATION: Preparing comprehensive data structure...")
                    comprehensive_data = {
                        'incomes': incomes,
                        'expenses': expenses,
                        'assets': assets,
                        'debtors': debtors,
                        'creditors': creditors,
                        'inventory': inventory,
                        'total_income': total_income,
                        'total_expenses': total_expenses,
                        'net_income': net_income,
                        'sales_revenue': sales_revenue,
                        'other_income': other_income,
                        'cost_of_goods_sold': total_cogs,
                        'gross_profit': gross_profit,
                        'gross_margin_percentage': gross_margin_pct,
                        'operating_expenses': total_operating,
                        'operating_profit': operating_profit,
                        'debtors_value': debtors_value,
                        'creditors_value': creditors_value,
                        'inventory_value': inventory_value,
                        'cash_balance': cash_balance,
                        'tag_filter': tag_filter,
                        'tax_type': tax_type
                    }
                    
                    # Generate PDF
                    print(f"[SUCCESS] SOA GENERATION: Calling PDF generator...")
                    pdf_generator = PDFGenerator()
                    
                    # Prepare data in the format expected by generate_statement_of_affairs
                    financial_data = {
                        'incomes': comprehensive_data['incomes'],
                        'expenses': comprehensive_data['expenses']
                    }
                    
                    # CRITICAL FIX (Mar 10, 2026): Get FC Credit and Subscription liabilities
                    # PRIVACY FIX (Mar 12, 2026): Import from correct module and filter by user
                    from utils.liability_calculator import calculate_total_liabilities
                    
                    # PRIVACY FIX: Pass current user ID to filter liabilities to this user only
                    liability_result = calculate_total_liabilities(mongo, current_user['_id'])
                    fc_credit_liabilities = 0
                    subscription_liabilities = 0
                    fee_waiver_liabilities = 0
                    
                    if liability_result['success']:
                        fc_credit_liabilities = liability_result.get('fc_credit_liabilities', {}).get('total', 0)
                        subscription_liabilities = liability_result.get('subscription_liabilities', {}).get('total', 0)
                        fee_waiver_liabilities = liability_result.get('fee_waiver_liabilities', {}).get('total', 0)
                    
                    tax_data = {
                        'sales_revenue': comprehensive_data.get('sales_revenue', 0),
                        'other_income': comprehensive_data.get('other_income', 0),
                        'total_income': comprehensive_data['total_income'],
                        'cost_of_goods_sold': comprehensive_data.get('cost_of_goods_sold', 0),
                        'gross_profit': comprehensive_data.get('gross_profit', 0),
                        'gross_margin_percentage': comprehensive_data.get('gross_margin_percentage', 0),
                        'operating_expenses': comprehensive_data.get('operating_expenses', 0),
                        'operating_profit': comprehensive_data.get('operating_profit', 0),
                        'net_income': comprehensive_data['net_income'],
                        'deductible_expenses': comprehensive_data['total_expenses'],
                        'tax_type': tax_type,
                        'inventory_value': comprehensive_data['inventory_value'],
                        'debtors_value': comprehensive_data['debtors_value'],
                        'creditors_value': comprehensive_data['creditors_value'],
                        'cash_balance': comprehensive_data['cash_balance'],
                        'inventory_count': len(comprehensive_data['inventory']),
                        'debtors_count': len(comprehensive_data['debtors']),
                        'creditors_count': len(comprehensive_data['creditors']),
                        # CRITICAL FIX (Feb 28, 2026): Get actual opening equity and drawings from user
                        'opening_equity': user.get('openingEquity', 0) if user else 0,
                        'drawings': user.get('drawings', 0) if user else 0,
                        'capital': user.get('capital', 0) if user else 0,  # Capital contributions
                        'loans_outstanding': 0,  # TODO: Calculate outstanding loans
                        # CRITICAL FIX (Mar 10, 2026): Include FC Credit and Subscription liabilities
                        'fc_credit_liabilities': fc_credit_liabilities,
                        'subscription_liabilities': subscription_liabilities,
                        'fee_waiver_liabilities': fee_waiver_liabilities
                    }
                    
                    assets_data = comprehensive_data['assets']
                    
                    pdf_buffer = pdf_generator.generate_statement_of_affairs(
                        user_data=user_data,
                        financial_data=financial_data,
                        tax_data=tax_data,
                        assets_data=assets_data,
                        start_date=start_date,
                        end_date=end_date,
                        tax_type=tax_type,
                        profile_tax_type=tax_type,
                        tag_filter=tag_filter
                    )
                    
                    print(f"[OK] SOA GENERATION: PDF generated successfully! Size = {len(pdf_buffer.getvalue())} bytes")
                    return pdf_buffer
                    
                except Exception as gen_error:
                    print(f"[ERROR] SOA GENERATION ERROR: {str(gen_error)}")
                    print(f"[ERROR] SOA GENERATION ERROR TYPE: {type(gen_error).__name__}")
                    import traceback
                    print(f"[ERROR] SOA GENERATION TRACEBACK:\n{traceback.format_exc()}")
                    raise
            
            # Define wrapper function that deducts credits ONLY on success
            def generate_and_deduct_on_success():
                try:
                    # Generate PDF
                    pdf_buffer = generate_statement_of_affairs_pdf()
                    
                    # ONLY deduct credits if generation succeeded
                    if not is_premium and credit_cost > 0:
                        print(f"[INFO] SOA ASYNC: PDF generated successfully, deducting {credit_cost} credits...")
                        deduct_credits(current_user, credit_cost, report_type)
                        print(f"[OK] SOA ASYNC: Credits deducted after successful generation")
                    
                    # Log export event
                    log_export_event(current_user, report_type, 'pdf', success=True)
                    print(f"[OK] SOA ASYNC: Export event logged")
                    
                    return pdf_buffer
                except Exception as e:
                    # DO NOT deduct credits on failure
                    print(f"[ERROR] SOA ASYNC: Generation failed, credits NOT deducted")
                    log_export_event(current_user, report_type, 'pdf', success=False)
                    raise
            
            # Start background generation with wrapper
            print(f"[INFO] SOA ASYNC: Starting background generation...")
            bg_generator.start_generation(job_id, generate_and_deduct_on_success)
            print(f"[OK] SOA ASYNC: Background generation started")
            
            # Return job_id immediately
            print(f"[OK] SOA ASYNC: Returning job_id to client")
            return jsonify({
                'success': True,
                'message': 'Your comprehensive report is being prepared. This may take 3-5 minutes due to the detailed calculations.',
                'jobId': job_id,
                'statusUrl': f'/api/reports/job-status/{job_id}',
                'estimatedTime': '3-5 minutes'
            }), 202
            
        except Exception as e:
            print(f"[ERROR] SOA ASYNC ERROR: {str(e)}")
            print(f"[ERROR] SOA ASYNC ERROR TYPE: {type(e).__name__}")
            import traceback
            print(f"[ERROR] SOA ASYNC TRACEBACK:\n{traceback.format_exc()}")
            return jsonify({
                'success': False,
                'message': f'Unable to start preparing your report: {str(e)}'
            }), 500
    
    @reports_bp.route('/statement-of-affairs-csv', methods=['POST'])
    @token_required
    def export_statement_of_affairs_csv(current_user):
        """Export Statement of Affairs as CSV (NEW ENDPOINT - PRIORITY)"""
        try:
            request_data = request.get_json() or {}
            report_type = 'statement_of_affairs_csv'
            
            # Get tax type and tag filter
            tax_type = request_data.get('taxType', 'PIT').upper()
            if tax_type not in ['PIT', 'CIT']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tax type. Must be either PIT or CIT'
                }), 400
            
            tag_filter = request_data.get('tagFilter', 'business').lower()
            if tag_filter not in ['business', 'personal', 'all', 'untagged']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid tag filter'
                }), 400
            
            # Check user access
            has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
            
            if not has_access:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Build queries (same as PDF version)
            # CRITICAL FIX (Mar 9, 2026): Exclude capital contributions/expenditures from P&L
            income_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False, 'excludeFromProfitLoss': {'$ne': True}}
            expense_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False, 'excludeFromProfitLoss': {'$ne': True}}
            asset_query = {'userId': current_user['_id'], 'status': 'active'}
            debtors_query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            creditors_query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            inventory_query = {'userId': current_user['_id']}
            
            # Apply tag filtering
            if tag_filter == 'business':
                income_query['entryType'] = 'business'
                expense_query['entryType'] = 'business'
            elif tag_filter == 'personal':
                income_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False, 'entryType': 'personal', 'excludeFromProfitLoss': {'$ne': True}}
                expense_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False, 'entryType': 'personal', 'excludeFromProfitLoss': {'$ne': True}}
            
            # Apply date filtering
            if start_date or end_date:
                if start_date:
                    income_query['date'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('date', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            # Fetch all data
            results = fetch_collections_parallel({
                'incomes': lambda: list(mongo.db.incomes.find(income_query)),
                'expenses': lambda: list(mongo.db.expenses.find(expense_query)),
                'assets': lambda: list(mongo.db.assets.find(asset_query)),
                'debtors': lambda: list(mongo.db.debtors.find(debtors_query)),
                'creditors': lambda: list(mongo.db.creditors.find(creditors_query)),
                'inventory': lambda: list(mongo.db.inventory.find(inventory_query))
            }, max_workers=6)
            
            # Generate CSV
            import io
            import csv
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['STATEMENT OF AFFAIRS'])
            writer.writerow([f'Tax Type: {tax_type}'])
            writer.writerow([f'Tag Filter: {tag_filter}'])
            writer.writerow([f'Period: {start_date.strftime("%Y-%m-%d") if start_date else "All"} to {end_date.strftime("%Y-%m-%d") if end_date else "All"}'])
            writer.writerow([])
            
            # Income section
            writer.writerow(['INCOME'])
            writer.writerow(['Date', 'Source', 'Category', 'Amount (N)'])
            for inc in results['incomes']:
                writer.writerow([
                    inc.get('date', '').strftime('%Y-%m-%d') if isinstance(inc.get('date'), datetime) else str(inc.get('date', '')),
                    inc.get('source', ''),
                    inc.get('category', ''),
                    inc.get('amount', 0)
                ])
            writer.writerow(['Total Income', '', '', sum(inc.get('amount', 0) for inc in results['incomes'])])
            writer.writerow([])
            
            # Expenses section
            writer.writerow(['EXPENSES'])
            writer.writerow(['Date', 'Title', 'Category', 'Amount (N)'])
            for exp in results['expenses']:
                writer.writerow([
                    exp.get('date', '').strftime('%Y-%m-%d') if isinstance(exp.get('date'), datetime) else str(exp.get('date', '')),
                    exp.get('title', ''),
                    exp.get('category', ''),
                    exp.get('amount', 0)
                ])
            writer.writerow(['Total Expenses', '', '', sum(exp.get('amount', 0) for exp in results['expenses'])])
            writer.writerow([])
            
            # Assets section
            writer.writerow(['ASSETS'])
            writer.writerow(['Name', 'Purchase Date', 'Purchase Cost (N)', 'Current Value (N)'])
            for asset in results['assets']:
                writer.writerow([
                    asset.get('name', ''),
                    asset.get('purchaseDate', '').strftime('%Y-%m-%d') if isinstance(asset.get('purchaseDate'), datetime) else str(asset.get('purchaseDate', '')),
                    asset.get('purchaseCost', 0),
                    asset.get('currentValue', 0)
                ])
            writer.writerow([])
            
            # Debtors section
            writer.writerow(['DEBTORS (Accounts Receivable)'])
            writer.writerow(['Customer', 'Amount (N)', 'Due Date', 'Status'])
            for debtor in results['debtors']:
                writer.writerow([
                    debtor.get('customerName', ''),
                    debtor.get('amount', 0),
                    debtor.get('dueDate', '').strftime('%Y-%m-%d') if isinstance(debtor.get('dueDate'), datetime) else str(debtor.get('dueDate', '')),
                    debtor.get('status', '')
                ])
            writer.writerow(['Total Debtors', sum(d.get('amount', 0) for d in results['debtors']), '', ''])
            writer.writerow([])
            
            # Creditors section
            writer.writerow(['CREDITORS (Accounts Payable)'])
            writer.writerow(['Supplier', 'Amount (N)', 'Due Date', 'Status'])
            for creditor in results['creditors']:
                writer.writerow([
                    creditor.get('supplierName', ''),
                    creditor.get('amount', 0),
                    creditor.get('dueDate', '').strftime('%Y-%m-%d') if isinstance(creditor.get('dueDate'), datetime) else str(creditor.get('dueDate', '')),
                    creditor.get('status', '')
                ])
            writer.writerow(['Total Creditors', sum(c.get('amount', 0) for c in results['creditors']), '', ''])
            writer.writerow([])
            
            # Inventory section
            writer.writerow(['INVENTORY'])
            writer.writerow(['Item', 'Quantity', 'Unit Cost (N)', 'Total Value (N)'])
            for item in results['inventory']:
                qty = item.get('quantity', 0)
                cost = item.get('unitCost', 0)
                writer.writerow([
                    item.get('name', ''),
                    qty,
                    cost,
                    qty * cost
                ])
            writer.writerow(['Total Inventory', '', '', sum(i.get('quantity', 0) * i.get('unitCost', 0) for i in results['inventory'])])
            
            # Deduct credits
            if not is_premium and credit_cost > 0:
                deduct_credits(current_user, credit_cost, report_type)
            
            # Log export
            log_export_event(current_user, report_type, 'csv', success=True)
            
            # Return CSV
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'ficore_statement_of_affairs_{tax_type}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            
        except Exception as e:
            log_export_event(current_user, 'statement_of_affairs_csv', 'csv', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate CSV: {str(e)}'
            }), 500
    
    # ============================================================================
    # REMAINING REPORTS: Async endpoints not yet implemented
    # These reports will fall back to sync endpoints (working correctly)
    # ============================================================================
    # TODO (Low Priority): Add async endpoints for:
    # - Debtors PDF (/debtors-pdf-async)
    # - Creditors PDF (/creditors-pdf-async)
    # - Inventory PDF (/inventory-pdf-async)
    # - Credits PDF (/credits-pdf-async)
    # - Wallet Funding PDF (/wallet-funding-pdf-async)
    # - Bill Payments PDF (/bill-payments-pdf-async)
    # - Airtime Purchases PDF (/airtime-purchases-pdf-async)
    # - Full Wallet PDF (/full-wallet-pdf-async)
    # 
    # Pattern: Copy logic from sync endpoint into async wrapper (see examples above)
    # Estimated time: 15-20 minutes per endpoint
    # ============================================================================
    
    @reports_bp.route('/refund-corrupted/<job_id>', methods=['POST'])
    @token_required
    def refund_corrupted_report(current_user, job_id):
        """
        Refund credits for a corrupted/unusable report.
        
        This endpoint allows users to request refunds when they receive
        corrupted PDFs that can't be opened or used.
        """
        try:
            # Get the job details
            job = mongo.db.report_jobs.find_one({'jobId': job_id})
            if not job:
                return jsonify({
                    'success': False,
                    'message': 'Report job not found'
                }), 404
            
            # Verify the job belongs to the current user
            if str(job['userId']) != str(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized access to report job'
                }), 403
            
            # Check if job was completed (only completed jobs can be refunded)
            if job['status'] != 'completed':
                return jsonify({
                    'success': False,
                    'message': 'Only completed reports can be refunded'
                }), 400
            
            # Check if already refunded
            if job.get('refunded', False):
                return jsonify({
                    'success': False,
                    'message': 'This report has already been refunded'
                }), 400
            
            # Get the credit cost for this report type
            report_type = job['reportType']
            credit_cost = REPORT_CREDIT_COSTS.get(report_type, 0)
            
            if credit_cost == 0:
                return jsonify({
                    'success': False,
                    'message': 'This report type is free, no refund needed'
                }), 400
            
            # Find the original FC deduction transaction
            fc_transaction = mongo.db.credit_transactions.find_one({
                'userId': current_user['_id'],
                'type': 'deduction',
                'status': 'completed',
                'metadata.reportJobId': job_id
            })
            
            if not fc_transaction:
                return jsonify({
                    'success': False,
                    'message': 'Original FC transaction not found'
                }), 404
            
            # Create refund transaction
            refund_transaction = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'type': 'refund',
                'amount': credit_cost,  # Positive amount for refund
                'status': 'completed',
                'description': f'Refund for corrupted {report_type} report',
                'metadata': {
                    'originalTransactionId': str(fc_transaction['_id']),
                    'reportJobId': job_id,
                    'reportType': report_type,
                    'refundReason': 'corrupted_pdf',
                    'refundedAt': datetime.utcnow()
                },
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            # Update user's FC balance
            current_balance = current_user.get('ficore_credit_balance', 0)
            new_balance = current_balance + credit_cost
            
            # Perform atomic update
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {'ficore_credit_balance': new_balance}}
            )
            
            # Insert refund transaction
            mongo.db.credit_transactions.insert_one(refund_transaction)
            
            # Mark job as refunded
            mongo.db.report_jobs.update_one(
                {'jobId': job_id},
                {
                    '$set': {
                        'refunded': True,
                        'refundedAt': datetime.utcnow(),
                        'refundTransactionId': str(refund_transaction['_id'])
                    }
                }
            )
            
            print(f"[OK] REFUND: User {current_user['_id']} refunded {credit_cost} FCs for corrupted report {job_id}")
            
            return jsonify({
                'success': True,
                'message': f'Refund processed successfully. {credit_cost} FCs have been restored to your account.',
                'data': {
                    'refundAmount': credit_cost,
                    'newBalance': new_balance,
                    'refundTransactionId': str(refund_transaction['_id'])
                }
            })
            
        except Exception as e:
            print(f"[ERROR] REFUND ERROR: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to process refund',
                'error': str(e)
            }), 500


    @reports_bp.route('/validate-pdf/<job_id>', methods=['POST'])
    @token_required
    def validate_report_pdf(current_user, job_id):
        """
        Validate that a generated PDF is not corrupted.
        
        This endpoint allows the frontend to check if a PDF is valid
        before the user tries to open it.
        """
        try:
            # Get the job details
            job = mongo.db.report_jobs.find_one({'jobId': job_id})
            if not job:
                return jsonify({
                    'success': False,
                    'message': 'Report job not found'
                }), 404
            
            # Verify the job belongs to the current user
            if str(job['userId']) != str(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized access to report job'
                }), 403
            
            # Check if job was completed
            if job['status'] != 'completed':
                return jsonify({
                    'success': False,
                    'message': 'Report is not ready for validation'
                }), 400
            
            # Get the file from GridFS
            from gridfs import GridFS
            fs = GridFS(mongo.db)
            
            file_id = ObjectId(job['fileId'])
            if not fs.exists(file_id):
                return jsonify({
                    'success': False,
                    'message': 'Report file not found',
                    'corrupted': True
                })
            
            # Get the file and validate
            grid_file = fs.get(file_id)
            pdf_buffer = BytesIO(grid_file.read())
            
            # Validate PDF integrity
            is_valid = _validate_pdf_integrity(pdf_buffer)
            
            return jsonify({
                'success': True,
                'data': {
                    'isValid': is_valid,
                    'corrupted': not is_valid,
                    'fileSize': job.get('fileSize', 0),
                    'canRefund': not is_valid and not job.get('refunded', False)
                }
            })
            
        except Exception as e:
            print(f"[ERROR] PDF VALIDATION ERROR: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to validate PDF',
                'error': str(e)
            }), 500


    print("DEBUG: All routes defined successfully")
    print("DEBUG: About to return reports_bp")
    print(f"DEBUG: reports_bp = {reports_bp}")
    return reports_bp