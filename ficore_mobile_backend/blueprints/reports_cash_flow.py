"""
Cash Flow Reports Blueprint - Handles cash flow report generation and export
Extracted from the original monolithic reports.py file
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
from utils.generator_cash_flow import CashFlowPDFGenerator
from utils.parallel_query_helper import fetch_collections_parallel
from utils.pdf_cache_helper import get_pdf_cache
from utils.background_report_generator import get_background_generator, ReportJobStatus

# ============================================================================
# QUERY PROJECTIONS FOR PDF EXPORT OPTIMIZATION
# ============================================================================
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
    }
}

def init_cash_flow_reports_blueprint(mongo, token_required):
    """Initialize the cash flow reports blueprint with database and auth decorator"""
    
    # Credit costs for different report types
    REPORT_CREDIT_COSTS = {
        'cash_flow_pdf': 3,
        'cash_flow_csv': 2,
    }
    
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

    # Create blueprint
    cash_flow_reports_bp = Blueprint('cash_flow_reports', __name__)

    @cash_flow_reports_bp.route('/cash-flow-pdf', methods=['POST'])
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
            pdf_generator = CashFlowPDFGenerator()
            tag_filter = "all"  # Default tag filter for cash flow
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

    @cash_flow_reports_bp.route('/cash-flow-pdf-async', methods=['POST'])
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
                pdf_generator = CashFlowPDFGenerator()
                tag_filter = "all"  # Default tag filter for cash flow
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

    # Cash Flow CSV
    @cash_flow_reports_bp.route('/cash-flow-csv', methods=['POST'])
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

    return cash_flow_reports_bp