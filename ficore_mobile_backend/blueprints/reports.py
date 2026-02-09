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
from utils.pdf_generator import PDFGenerator

def init_reports_blueprint(mongo, token_required):
    """Initialize the reports blueprint with database and auth decorator"""
    reports_bp = Blueprint('reports', __name__, url_prefix='/api/reports')
    
    # Credit costs for different report types
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
    }
    
    def check_user_access(current_user, report_type):
        """
        Check if user has access to generate report (Premium or sufficient credits)
        Returns: (has_access: bool, is_premium: bool, current_balance: float, credit_cost: int)
        """
        user = mongo.db.users.find_one({'_id': current_user['_id']})
        is_premium = user.get('isSubscribed', False)
        is_admin = user.get('role') == 'admin'
        current_balance = user.get('ficoreCreditBalance', 0.0)
        credit_cost = REPORT_CREDIT_COSTS.get(report_type, 2)
        
        # Premium users and admins have unlimited access
        if is_premium or is_admin:
            return True, True, current_balance, 0
        
        # Free users need sufficient credits
        has_access = current_balance >= credit_cost
        return has_access, False, current_balance, credit_cost
    
    def deduct_credits(current_user, credit_cost, report_type):
        """
        Deduct credits from user account and log transaction
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
            'createdAt': datetime.utcnow()
        }
        mongo.db.credit_transactions.insert_one(credit_transaction)
        
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
    # INCOME REPORTS
    # ============================================================================
    
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
            
            # Fetch income data with tag filtering
            query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            
            # Apply tag filtering
            if tag_filter == 'business':
                query['tags'] = 'Business'
            elif tag_filter == 'personal':
                query['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                query['$or'] = [
                    {'tags': {'$exists': False}},
                    {'tags': {'$size': 0}},
                    {'tags': None}
                ]
            if start_date or end_date:
                query['dateReceived'] = {}
                if start_date:
                    query['dateReceived']['$gte'] = start_date
                if end_date:
                    query['dateReceived']['$lte'] = end_date
            
            incomes = list(mongo.db.incomes.find(query).sort('dateReceived', -1))
            
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
                'businessName': user.get('businessName', '') if user else ''
            }
            
            # Prepare export data
            export_data = {
                'incomes': []
            }
            
            for income in incomes:
                export_data['incomes'].append({
                    'source': income.get('source', ''),
                    'amount': income.get('amount', 0),
                    'dateReceived': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
                })
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_financial_report(user_data, export_data, 'incomes')
            
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
                print(f"⚠️ Export tracking failed (non-critical): {e}")
            
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
                download_name=f'ficore_income_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'income_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate income PDF: {str(e)}'
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
            
            # Fetch income data with tag filtering
            query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            
            # Apply tag filtering
            if tag_filter == 'business':
                query['tags'] = 'Business'
            elif tag_filter == 'personal':
                query['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                query['$or'] = [
                    {'tags': {'$exists': False}},
                    {'tags': {'$size': 0}},
                    {'tags': None}
                ]
            if start_date or end_date:
                query['dateReceived'] = {}
                if start_date:
                    query['dateReceived']['$gte'] = start_date
                if end_date:
                    query['dateReceived']['$lte'] = end_date
            
            incomes = list(mongo.db.incomes.find(query).sort('dateReceived', -1))
            
            if not incomes:
                return jsonify({
                    'success': False,
                    'message': 'No income records found for the selected period'
                }), 404
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Date', 'Source', 'Category', 'Amount (₦)', 'Description'])
            
            # Write data
            total_amount = 0
            for income in incomes:
                date_str = income.get('dateReceived', datetime.utcnow()).strftime('%Y-%m-%d')
                source = income.get('source', '')
                category = income.get('category', {}).get('name', 'Other')
                amount = income.get('amount', 0)
                description = income.get('description', '')
                
                writer.writerow([date_str, source, category, f'{amount:,.2f}', description])
                total_amount += amount
            
            # Write total
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
            
            # Fetch expense data with tag filtering
            query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            
            # Apply tag filtering
            if tag_filter == 'business':
                query['tags'] = 'Business'
            elif tag_filter == 'personal':
                query['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                query['$or'] = [
                    {'tags': {'$exists': False}},
                    {'tags': {'$size': 0}},
                    {'tags': None}
                ]
            if start_date or end_date:
                query['date'] = {}
                if start_date:
                    query['date']['$gte'] = start_date
                if end_date:
                    query['date']['$lte'] = end_date
            
            expenses = list(mongo.db.expenses.find(query).sort('date', -1))
            
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
                'businessName': user.get('businessName', '') if user else ''
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
            pdf_buffer = pdf_generator.generate_financial_report(user_data, export_data, 'expenses')
            
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
                print(f"⚠️ Export tracking failed (non-critical): {e}")
            
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
                download_name=f'ficore_expense_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'expense_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate expense PDF: {str(e)}'
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
            
            # Fetch expense data with tag filtering
            query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            
            # Apply tag filtering
            if tag_filter == 'business':
                query['tags'] = 'Business'
            elif tag_filter == 'personal':
                query['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                query['$or'] = [
                    {'tags': {'$exists': False}},
                    {'tags': {'$size': 0}},
                    {'tags': None}
                ]
            if start_date or end_date:
                query['date'] = {}
                if start_date:
                    query['date']['$gte'] = start_date
                if end_date:
                    query['date']['$lte'] = end_date
            
            expenses = list(mongo.db.expenses.find(query).sort('date', -1))
            
            if not expenses:
                return jsonify({
                    'success': False,
                    'message': 'No expense records found for the selected period'
                }), 404
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Date', 'Title', 'Category', 'Amount (₦)', 'Description'])
            
            # Write data
            total_amount = 0
            for expense in expenses:
                date_str = expense.get('date', datetime.utcnow()).strftime('%Y-%m-%d')
                title = expense.get('title', '')
                category = expense.get('category', 'Other')
                amount = expense.get('amount', 0)
                description = expense.get('description', '')
                
                writer.writerow([date_str, title, category, f'{amount:,.2f}', description])
                total_amount += amount
            
            # Write total
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
            
            # Fetch income and expense data with tag filtering
            income_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            expense_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            
            # Apply tag filtering
            if tag_filter == 'business':
                income_query['tags'] = 'Business'
                expense_query['tags'] = 'Business'
            elif tag_filter == 'personal':
                income_query['tags'] = 'Personal'
                expense_query['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                income_query['$or'] = [
                    {'tags': {'$exists': False}},
                    {'tags': {'$size': 0}},
                    {'tags': None}
                ]
                expense_query['$or'] = [
                    {'tags': {'$exists': False}},
                    {'tags': {'$size': 0}},
                    {'tags': None}
                ]
            
            if start_date or end_date:
                if start_date:
                    income_query['dateReceived'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('dateReceived', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            incomes = list(mongo.db.incomes.find(income_query))
            expenses = list(mongo.db.expenses.find(expense_query))
            
            # Prepare user data with business name
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', ''),
                'businessName': user.get('businessName', '') if user else ''
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
                    'dateReceived': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
                })
            
            for expense in expenses:
                export_data['expenses'].append({
                    'title': expense.get('title', ''),
                    'amount': expense.get('amount', 0),
                    'category': expense.get('category', 'Other'),
                    'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z'
                })
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_financial_report(user_data, export_data, 'all')
            
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
                print(f"⚠️ Export tracking failed (non-critical): {e}")
            
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
                download_name=f'ficore_profit_loss_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'profit_loss_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Profit & Loss PDF: {str(e)}'
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
            
            # Fetch income and expense data
            income_query = {'userId': current_user['_id']}
            expense_query = {'userId': current_user['_id']}
            
            if start_date or end_date:
                if start_date:
                    income_query['dateReceived'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('dateReceived', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            incomes = list(mongo.db.incomes.find(income_query))
            expenses = list(mongo.db.expenses.find(expense_query))
            
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
                'businessName': user.get('businessName', '') if user else ''
            }
            
            # Prepare transaction data
            transactions = {
                'incomes': [],
                'expenses': []
            }
            
            for income in incomes:
                transactions['incomes'].append({
                    'amount': income.get('amount', 0),
                    'date': income.get('dateReceived', datetime.utcnow())
                })
            
            for expense in expenses:
                transactions['expenses'].append({
                    'amount': expense.get('amount', 0),
                    'date': expense.get('date', datetime.utcnow())
                })
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_cash_flow_report(user_data, transactions, start_date, end_date)
            
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
                print(f"⚠️ Export tracking failed (non-critical): {e}")
            
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
            
            # Fetch income and expense data for tax calculation
            # CRITICAL: Apply tag filtering for tax compliance
            income_query = {
                'userId': current_user['_id'],
                'status': 'active',  # Only active entries
                'isDeleted': False   # Exclude soft-deleted entries
            }
            expense_query = {
                'userId': current_user['_id'],
                'status': 'active',  # Only active entries
                'isDeleted': False   # Exclude soft-deleted entries
            }
            
            # Apply tag filtering based on user selection
            if tag_filter == 'business':
                # Only entries tagged as "Business"
                income_query['tags'] = 'Business'
                expense_query['tags'] = 'Business'
            elif tag_filter == 'personal':
                # Only entries tagged as "Personal"
                income_query['tags'] = 'Personal'
                expense_query['tags'] = 'Personal'
            elif tag_filter == 'untagged':
                # Only entries without any tags
                income_query['$or'] = [
                    {'tags': {'$exists': False}},
                    {'tags': {'$size': 0}},
                    {'tags': None}
                ]
                expense_query['$or'] = [
                    {'tags': {'$exists': False}},
                    {'tags': {'$size': 0}},
                    {'tags': None}
                ]
            # If 'all', no tag filtering applied
            
            if start_date or end_date:
                if start_date:
                    income_query['dateReceived'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('dateReceived', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            incomes = list(mongo.db.incomes.find(income_query))
            expenses = list(mongo.db.expenses.find(expense_query))
            
            # Calculate totals
            total_income = sum(income.get('amount', 0) for income in incomes)
            total_expenses = sum(expense.get('amount', 0) for expense in expenses)
            
            # Prepare user data
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', ''),
                'businessName': user.get('businessName', '') if user else ''
            }
            
            # Prepare comprehensive tax data
            tax_data = {
                'total_income': total_income,
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
                # CIT Exemption Criteria: Turnover < ₦100M AND Fixed Assets NBV < ₦250M
                # Fixed Assets NBV = Original Cost - Accumulated Depreciation
                
                assets_query = {'userId': current_user['_id']}
                # Note: For CIT exemption, we consider ALL fixed assets owned, not just those purchased in period
                # Remove date filtering for exemption calculation
                
                assets = list(mongo.db.assets.find(assets_query))
                
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
                tax_data['fixed_assets_nbv'] = fixed_assets_nbv  # For exemption check (< ₦250M)
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
                
                # 1. Rent Relief (20% of annual rent, capped at ₦500,000)
                # Category dependency: "rent", "housing", "accommodation"
                # PHASE 5: Flexible keyword matching for frontend category compatibility
                rent_keywords = ['rent', 'housing', 'accommodation']
                rent_expenses = [exp for exp in expenses 
                                if any(keyword in exp.get('category', '').lower() 
                                       for keyword in rent_keywords)]
                annual_rent = sum(exp.get('amount', 0) for exp in rent_expenses)
                rent_relief = min(annual_rent * 0.20, 500000)  # 20% capped at ₦500k
                
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
                        'calculation': f"20% of ₦{annual_rent:,.2f}, capped at ₦500,000"
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
            pdf_buffer = pdf_generator.generate_tax_summary_report(user_data, tax_data, start_date, end_date, tax_type)
            
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
                print(f"⚠️ Export tracking failed (non-critical): {e}")
            
            # Deduct credits if not premium
            if not is_premium and credit_cost > 0:
                new_balance = deduct_credits(current_user, credit_cost, report_type)
            
            # Log export event
            log_export_event(current_user, report_type, 'pdf', success=True)
            
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
            
            # Fetch debtors data
            query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            if start_date or end_date:
                query['invoiceDate'] = {}
                if start_date:
                    query['invoiceDate']['$gte'] = start_date
                if end_date:
                    query['invoiceDate']['$lte'] = end_date
            
            debtors = list(mongo.db.debtors.find(query).sort('dueDate', 1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_debtors_report(user_data, debtors, start_date, end_date)
            
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
            
            # Fetch creditors data
            query = {'userId': current_user['_id'], 'status': {'$ne': 'paid'}}
            if start_date or end_date:
                query['invoiceDate'] = {}
                if start_date:
                    query['invoiceDate']['$gte'] = start_date
                if end_date:
                    query['invoiceDate']['$lte'] = end_date
            
            creditors = list(mongo.db.creditors.find(query).sort('dueDate', 1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_creditors_report(user_data, creditors, start_date, end_date)
            
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
            
            # Fetch assets data
            query = {'userId': current_user['_id']}
            if start_date or end_date:
                query['purchaseDate'] = {}
                if start_date:
                    query['purchaseDate']['$gte'] = start_date
                if end_date:
                    query['purchaseDate']['$lte'] = end_date
            
            assets = list(mongo.db.assets.find(query).sort('purchaseDate', -1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_assets_report(user_data, assets, start_date, end_date)
            
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
                download_name=f'ficore_assets_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'assets_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Assets PDF: {str(e)}'
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
            
            # Fetch assets data
            query = {'userId': current_user['_id']}
            if start_date or end_date:
                query['purchaseDate'] = {}
                if start_date:
                    query['purchaseDate']['$gte'] = start_date
                if end_date:
                    query['purchaseDate']['$lte'] = end_date
            
            assets = list(mongo.db.assets.find(query).sort('purchaseDate', -1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_asset_depreciation_report(user_data, assets, start_date, end_date)
            
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
                download_name=f'ficore_asset_depreciation_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            log_export_event(current_user, 'asset_depreciation_pdf', 'pdf', success=False, error=str(e))
            return jsonify({
                'success': False,
                'message': f'Failed to generate Asset Depreciation PDF: {str(e)}'
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
            
            # Fetch inventory data
            query = {'userId': current_user['_id']}
            inventory_items = list(mongo.db.inventory.find(query).sort('name', 1))
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_inventory_report(user_data, inventory_items)
            
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
            inventory_items = list(mongo.db.inventory.find(query).sort('name', 1))
            
            if not inventory_items:
                return jsonify({
                    'success': False,
                    'message': 'No inventory items found'
                }), 404
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Item Name', 'SKU', 'Category', 'Quantity', 'Unit Cost (₦)', 'Total Value (₦)', 'Min Stock Level', 'Status'])
            
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
            
            # Fetch income and expense data
            income_query = {'userId': current_user['_id']}
            expense_query = {'userId': current_user['_id']}
            
            if start_date or end_date:
                if start_date:
                    income_query['dateReceived'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('dateReceived', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            incomes = list(mongo.db.incomes.find(income_query))
            expenses = list(mongo.db.expenses.find(expense_query))
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Profit & Loss Statement'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            if start_date and end_date:
                writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
            writer.writerow([])
            
            # Income Section
            writer.writerow(['INCOME'])
            writer.writerow(['Date', 'Source', 'Category', 'Amount (₦)'])
            total_income = 0
            for income in incomes:
                date_str = income.get('dateReceived', datetime.utcnow()).strftime('%Y-%m-%d')
                writer.writerow([
                    date_str,
                    income.get('source', 'N/A'),
                    income.get('category', {}).get('name', 'Other'),
                    f'{income.get("amount", 0):,.2f}'
                ])
                total_income += income.get('amount', 0)
            writer.writerow(['', '', 'Total Income:', f'{total_income:,.2f}'])
            writer.writerow([])
            
            # Expenses Section
            writer.writerow(['EXPENSES'])
            writer.writerow(['Date', 'Title', 'Category', 'Amount (₦)'])
            total_expenses = 0
            for expense in expenses:
                date_str = expense.get('date', datetime.utcnow()).strftime('%Y-%m-%d')
                writer.writerow([
                    date_str,
                    expense.get('title', 'N/A'),
                    expense.get('category', 'Other'),
                    f'{expense.get("amount", 0):,.2f}'
                ])
                total_expenses += expense.get('amount', 0)
            writer.writerow(['', '', 'Total Expenses:', f'{total_expenses:,.2f}'])
            writer.writerow([])
            
            # Summary
            net_profit = total_income - total_expenses
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Income', f'{total_income:,.2f}'])
            writer.writerow(['Total Expenses', f'{total_expenses:,.2f}'])
            writer.writerow(['Net Profit/Loss', f'{net_profit:,.2f}'])
            
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
                    income_query['dateReceived'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('dateReceived', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            incomes = list(mongo.db.incomes.find(income_query))
            expenses = list(mongo.db.expenses.find(expense_query))
            
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
            writer.writerow(['Description', 'Amount (₦)'])
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
            income_query = {'userId': current_user['_id']}
            expense_query = {'userId': current_user['_id']}
            
            if start_date or end_date:
                if start_date:
                    income_query['dateReceived'] = {'$gte': start_date}
                    expense_query['date'] = {'$gte': start_date}
                if end_date:
                    income_query.setdefault('dateReceived', {})['$lte'] = end_date
                    expense_query.setdefault('date', {})['$lte'] = end_date
            
            incomes = list(mongo.db.incomes.find(income_query))
            expenses = list(mongo.db.expenses.find(expense_query))
            
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
            writer.writerow(['Description', 'Amount (₦)'])
            writer.writerow(['Gross Income', f'{total_income:,.2f}'])
            writer.writerow(['Less: Deductible Expenses', f'{total_expenses:,.2f}'])
            
            net_income = total_income - total_expenses
            writer.writerow(['Taxable Income', f'{net_income:,.2f}'])
            writer.writerow([])
            
            # Tax Calculation
            if tax_type == 'CIT':
                writer.writerow(['CORPORATE INCOME TAX CALCULATION'])
                writer.writerow(['Description', 'Amount (₦)'])
                cit_rate = 0.25
                total_tax = net_income * cit_rate if net_income > 0 else 0
                writer.writerow(['Taxable Profit', f'{net_income:,.2f}'])
                writer.writerow(['CIT Rate', '25%'])
                writer.writerow(['Calculated Tax', f'{total_tax:,.2f}'])
            else:
                writer.writerow(['PERSONAL INCOME TAX CALCULATION'])
                writer.writerow(['Income Band', 'Rate', 'Taxable Amount (₦)', 'Tax (₦)'])
                
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
                    
                    upper_display = f"₦{upper:,.0f}" if upper != float('inf') else "Above"
                    writer.writerow([
                        f"₦{lower:,.0f} - {upper_display}",
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
            
            debtors = list(mongo.db.debtors.find(query).sort('dueDate', 1))
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Debtors Report (Accounts Receivable)'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            writer.writerow([])
            
            # Data
            writer.writerow(['Debtor Name', 'Invoice Date', 'Due Date', 'Amount (₦)', 'Status'])
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
            
            creditors = list(mongo.db.creditors.find(query).sort('dueDate', 1))
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Creditors Report (Accounts Payable)'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            writer.writerow([])
            
            # Data
            writer.writerow(['Creditor Name', 'Invoice Date', 'Due Date', 'Amount (₦)', 'Status'])
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
            query = {'userId': current_user['_id']}
            if start_date or end_date:
                query['purchaseDate'] = {}
                if start_date:
                    query['purchaseDate']['$gte'] = start_date
                if end_date:
                    query['purchaseDate']['$lte'] = end_date
            
            assets = list(mongo.db.assets.find(query).sort('purchaseDate', -1))
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Assets Register'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            writer.writerow([])
            
            # Data
            writer.writerow(['Asset Name', 'Category', 'Purchase Date', 'Cost (₦)', 'Current Value (₦)'])
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
            query = {'userId': current_user['_id']}
            if start_date or end_date:
                query['purchaseDate'] = {}
                if start_date:
                    query['purchaseDate']['$gte'] = start_date
                if end_date:
                    query['purchaseDate']['$lte'] = end_date
            
            assets = list(mongo.db.assets.find(query).sort('purchaseDate', -1))
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow(['FiCore Africa - Asset Depreciation Schedule'])
            writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
            writer.writerow(['Depreciation Method: Straight-Line'])
            writer.writerow([])
            
            # Data
            writer.writerow(['Asset', 'Cost (₦)', 'Useful Life', 'Annual Dep. (₦)', 'Accumulated (₦)', 'Book Value (₦)'])
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
            pdf_buffer = pdf_generator.generate_credit_transactions_report(user_data, credit_data, start_date, end_date)
            
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
            query['dateReceived'] = {}
            if start_date:
                query['dateReceived']['$gte'] = start_date
            if end_date:
                query['dateReceived']['$lte'] = end_date
        
        total_count = mongo.db.incomes.count_documents(query)
        incomes = list(mongo.db.incomes.find(query).sort('dateReceived', -1).limit(limit))
        
        # Calculate summary
        all_incomes = list(mongo.db.incomes.find(query))
        total_amount = sum(inc.get('amount', 0) for inc in all_incomes)
        
        # Format data
        data = []
        for income in incomes:
            data.append({
                'id': str(income['_id']),
                'date': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z',
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
        """Preview expense records"""
        query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False}
        if start_date or end_date:
            query['date'] = {}
            if start_date:
                query['date']['$gte'] = start_date
            if end_date:
                query['date']['$lte'] = end_date
        
        total_count = mongo.db.expenses.count_documents(query)
        expenses = list(mongo.db.expenses.find(query).sort('date', -1).limit(limit))
        
        # Calculate summary
        all_expenses = list(mongo.db.expenses.find(query))
        total_amount = sum(exp.get('amount', 0) for exp in all_expenses)
        
        # Format data
        data = []
        for expense in expenses:
            data.append({
                'id': str(expense['_id']),
                'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                'title': expense.get('title', ''),
                'category': expense.get('category', 'Other'),
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
        """Preview profit & loss data"""
        income_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False}
        expense_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False}
        
        if start_date or end_date:
            if start_date:
                income_query['dateReceived'] = {'$gte': start_date}
                expense_query['date'] = {'$gte': start_date}
            if end_date:
                income_query.setdefault('dateReceived', {})['$lte'] = end_date
                expense_query.setdefault('date', {})['$lte'] = end_date
        
        # Get all for summary
        all_incomes = list(mongo.db.incomes.find(income_query))
        all_expenses = list(mongo.db.expenses.find(expense_query))
        
        total_income = sum(inc.get('amount', 0) for inc in all_incomes)
        total_expenses = sum(exp.get('amount', 0) for exp in all_expenses)
        net_profit = total_income - total_expenses
        
        # Get limited data for preview
        incomes = list(mongo.db.incomes.find(income_query).sort('dateReceived', -1).limit(limit // 2))
        expenses = list(mongo.db.expenses.find(expense_query).sort('date', -1).limit(limit // 2))
        
        # Format data
        data = {
            'incomes': [],
            'expenses': []
        }
        
        for income in incomes:
            data['incomes'].append({
                'date': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z',
                'source': income.get('source', ''),
                'amount': income.get('amount', 0)
            })
        
        for expense in expenses:
            data['expenses'].append({
                'date': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                'title': expense.get('title', ''),
                'category': expense.get('category', 'Other'),
                'amount': expense.get('amount', 0)
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
                'net_profit': net_profit
            }
        })
    
    def _preview_cash_flow(current_user, start_date, end_date, limit):
        """Preview cash flow data"""
        # Same as profit_loss but with different presentation
        return _preview_profit_loss(current_user, start_date, end_date, limit)
    
    def _preview_tax_summary(current_user, start_date, end_date, limit):
        """Preview tax summary data"""
        # Get income and expense data
        income_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False}
        expense_query = {'userId': current_user['_id'], 'status': 'active', 'isDeleted': False}
        
        if start_date or end_date:
            if start_date:
                income_query['dateReceived'] = {'$gte': start_date}
                expense_query['date'] = {'$gte': start_date}
            if end_date:
                income_query.setdefault('dateReceived', {})['$lte'] = end_date
                expense_query.setdefault('date', {})['$lte'] = end_date
        
        all_incomes = list(mongo.db.incomes.find(income_query))
        all_expenses = list(mongo.db.expenses.find(expense_query))
        
        total_income = sum(inc.get('amount', 0) for inc in all_incomes)
        total_expenses = sum(exp.get('amount', 0) for exp in all_expenses)
        taxable_income = total_income - total_expenses
        
        # Get user's tax profile
        user = mongo.db.users.find_one({'_id': current_user['_id']})
        tax_profile = user.get('taxProfile', {})
        
        # Calculate estimated tax (simplified)
        estimated_tax = 0
        if taxable_income > 0:
            # Use 7% flat rate for simplicity (actual calculation is more complex)
            estimated_tax = taxable_income * 0.07
        
        # Get limited transactions
        incomes = list(mongo.db.incomes.find(income_query).sort('dateReceived', -1).limit(limit // 2))
        expenses = list(mongo.db.expenses.find(expense_query).sort('date', -1).limit(limit // 2))
        
        data = {
            'incomes': [{'date': inc.get('dateReceived', datetime.utcnow()).isoformat() + 'Z', 'source': inc.get('source', ''), 'amount': inc.get('amount', 0)} for inc in incomes],
            'expenses': [{'date': exp.get('date', datetime.utcnow()).isoformat() + 'Z', 'title': exp.get('title', ''), 'amount': exp.get('amount', 0)} for exp in expenses]
        }
        
        return jsonify({
            'success': True,
            'preview': True,
            'total_count': len(all_incomes) + len(all_expenses),
            'showing_count': len(incomes) + len(expenses),
            'data': data,
            'summary': {
                'total_income': total_income,
                'total_expenses': total_expenses,
                'taxable_income': taxable_income,
                'estimated_tax': estimated_tax
            }
        })
    
    def _preview_debtors(current_user, start_date, end_date, limit):
        """Preview debtors data"""
        query = {'userId': current_user['_id']}
        
        total_count = mongo.db.debtors.count_documents(query)
        debtors = list(mongo.db.debtors.find(query).sort('createdAt', -1).limit(limit))
        
        # Calculate summary
        all_debtors = list(mongo.db.debtors.find(query))
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
        creditors = list(mongo.db.creditors.find(query).sort('createdAt', -1).limit(limit))
        
        # Calculate summary
        all_creditors = list(mongo.db.creditors.find(query))
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
        assets = list(mongo.db.assets.find(query).sort('purchaseDate', -1).limit(limit))
        
        # Calculate summary
        all_assets = list(mongo.db.assets.find(query))
        total_value = sum(a.get('purchasePrice', 0) for a in all_assets)
        total_depreciation = sum(a.get('accumulatedDepreciation', 0) for a in all_assets)
        
        data = []
        for asset in assets:
            data.append({
                'id': str(asset['_id']),
                'name': asset.get('name', ''),
                'category': asset.get('category', ''),
                'purchasePrice': asset.get('purchasePrice', 0),
                'currentValue': asset.get('currentValue', 0),
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
                'net_book_value': total_value - total_depreciation,
                'count': total_count
            }
        })
    
    def _preview_asset_depreciation(current_user, start_date, end_date, limit):
        """Preview asset depreciation schedule"""
        query = {'userId': current_user['_id'], 'depreciationMethod': {'$ne': 'None'}}
        
        total_count = mongo.db.assets.count_documents(query)
        assets = list(mongo.db.assets.find(query).sort('purchaseDate', -1).limit(limit))
        
        # Calculate summary
        all_assets = list(mongo.db.assets.find(query))
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
                    'description': f"Wallet Funding - ₦{txn.get('amount', 0):,.2f}"
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
            
            writer.writerow(['Date', 'Reference', 'Amount (₦)', 'Fee (₦)', 'Status'])
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
        """Export Bill Payments transactions as PDF"""
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
                    'fee': txn.get('fee', 0),
                    'status': txn.get('status', 'UNKNOWN'),
                    'category': txn.get('category', 'N/A'),
                    'description': txn.get('description', f"Bill Payment - {txn.get('category', 'N/A')}")
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
            
            writer.writerow(['Date', 'Reference', 'Category', 'Amount (₦)', 'Fee (₦)', 'Status'])
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
        """Export Airtime Purchases transactions as PDF"""
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
                    'fee': txn.get('fee', 0),
                    'status': txn.get('status', 'UNKNOWN'),
                    'phone': txn.get('phoneNumber', 'N/A'),
                    'description': f"Airtime - {txn.get('phoneNumber', 'N/A')}"
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
            
            writer.writerow(['Date', 'Reference', 'Phone Number', 'Amount (₦)', 'Fee (₦)', 'Status'])
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
                        description = f"Wallet Funding - ₦{txn.get('amount', 0):,.2f}"
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
            
            writer.writerow(['Date', 'Reference', 'Type', 'Description', 'Amount (₦)', 'Fee (₦)', 'Status'])
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
                        description = f"Wallet Funding - ₦{amount:,.2f}"
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
    
    return reports_bp
