# Profit & Loss Report Blueprint
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime, timedelta
import io
import csv
import tempfile
import os

try:
    from utils.generator_profit_loss import ProfitLossGenerator
    from utils.generator_core import get_nigerian_time
except ImportError:
    # Fallback for missing modules
    class ProfitLossGenerator:
        def __init__(self, *args, **kwargs):
            pass
        def generate_profit_loss_report(self, *args, **kwargs):
            return {'success': False, 'message': 'Profit Loss generator not available'}
    
    def get_nigerian_time():
        return datetime.utcnow()

def init_profit_loss_blueprint(mongo, token_required):
    """Initialize Profit & Loss reports blueprint"""
    
    reports_pl_bp = Blueprint('reports_pl', __name__, url_prefix='/api/reports')
    
    def parse_date_range(request_data):
        """Parse date range from request data"""
        start_date = None
        end_date = None
        
        if 'startDate' in request_data and request_data['startDate']:
            try:
                start_date = datetime.fromisoformat(request_data['startDate'].replace('Z', '+00:00'))
            except ValueError:
                start_date = datetime.strptime(request_data['startDate'], '%Y-%m-%d')
        
        if 'endDate' in request_data and request_data['endDate']:
            try:
                end_date = datetime.fromisoformat(request_data['endDate'].replace('Z', '+00:00'))
            except ValueError:
                end_date = datetime.strptime(request_data['endDate'], '%Y-%m-%d')
        
        return start_date, end_date
    
    def filter_by_date_range(items, date_field, start_date, end_date):
        """Filter items by date range"""
        if not start_date and not end_date:
            return items
        
        filtered_items = []
        for item in items:
            item_date = item.get(date_field)
            if isinstance(item_date, str):
                try:
                    item_date = datetime.fromisoformat(item_date.replace('Z', '+00:00'))
                except ValueError:
                    try:
                        item_date = datetime.strptime(item_date, '%Y-%m-%d')
                    except ValueError:
                        continue
            elif not isinstance(item_date, datetime):
                continue
            
            if start_date and item_date < start_date:
                continue
            if end_date and item_date > end_date:
                continue
            
            filtered_items.append(item)
        
        return filtered_items
    
    def get_financial_data(current_user, start_date=None, end_date=None, tag_filter="all"):
        """Get financial data for reports"""
        user_id = current_user['_id']
        
        # Base query
        base_query = {
            'userId': user_id,
            'status': 'active',
            'isDeleted': False
        }
        
        # Add tag filter
        if tag_filter and tag_filter != 'all':
            base_query['tags'] = tag_filter
        
        # Get incomes and expenses
        incomes = list(mongo.db.incomes.find(base_query))
        expenses = list(mongo.db.expenses.find(base_query))
        
        # Filter by date range
        if start_date or end_date:
            incomes = filter_by_date_range(incomes, 'date', start_date, end_date)
            expenses = filter_by_date_range(expenses, 'date', start_date, end_date)
        
        # Get credit transactions
        credit_transactions = list(mongo.db.credit_transactions.find({
            'userId': user_id,
            'status': 'completed'
        }))
        
        if start_date or end_date:
            credit_transactions = filter_by_date_range(credit_transactions, 'createdAt', start_date, end_date)
        
        return {
            'incomes': incomes,
            'expenses': expenses,
            'creditTransactions': credit_transactions
        }
    
    @reports_pl_bp.route('/profit-loss-pdf', methods=['POST'])
    @token_required
    def export_profit_loss_pdf(current_user):
        """Export Profit & Loss statement as PDF"""
        try:
            request_data = request.get_json() or {}
            data_type = request_data.get('dataType', 'all')
            tag_filter = request_data.get('tagFilter', 'all')
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Get financial data
            export_data = get_financial_data(current_user, start_date, end_date, tag_filter)
            
            # Generate PDF
            pdf_generator = ProfitLossGenerator()
            pdf_buffer = pdf_generator.generate_financial_report(
                user_data=current_user,
                export_data=export_data,
                data_type=data_type,
                tag_filter=tag_filter
            )
            
            # Generate filename
            nigerian_time = get_nigerian_time()
            filename = f"profit_loss_{nigerian_time.strftime('%Y%m%d_%H%M%S')}.pdf"
            
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            print(f"Error generating P&L PDF: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to generate PDF report',
                'error': str(e)
            }), 500
    
    @reports_pl_bp.route('/profit-loss-csv', methods=['POST'])
    @token_required
    def export_profit_loss_csv(current_user):
        """Export Profit & Loss statement as CSV"""
        try:
            request_data = request.get_json() or {}
            data_type = request_data.get('dataType', 'all')
            tag_filter = request_data.get('tagFilter', 'all')
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Get financial data
            export_data = get_financial_data(current_user, start_date, end_date, tag_filter)
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Type', 'Date', 'Category', 'Description', 'Amount'])
            
            # Write expenses
            for expense in export_data.get('expenses', []):
                writer.writerow([
                    'Expense',
                    expense.get('date', ''),
                    expense.get('category', ''),
                    expense.get('description', ''),
                    expense.get('amount', 0)
                ])
            
            # Write incomes
            for income in export_data.get('incomes', []):
                writer.writerow([
                    'Income',
                    income.get('date', ''),
                    income.get('category', ''),
                    income.get('description', ''),
                    income.get('amount', 0)
                ])
            
            # Calculate totals
            total_expenses = sum(exp.get('amount', 0) for exp in export_data.get('expenses', []))
            total_income = sum(inc.get('amount', 0) for inc in export_data.get('incomes', []))
            net_profit = total_income - total_expenses
            
            # Write summary
            writer.writerow([])
            writer.writerow(['Summary', '', '', '', ''])
            writer.writerow(['Total Income', '', '', '', total_income])
            writer.writerow(['Total Expenses', '', '', '', total_expenses])
            writer.writerow(['Net Profit/(Loss)', '', '', '', net_profit])
            
            # Create response
            output.seek(0)
            
            # Generate filename
            nigerian_time = get_nigerian_time()
            filename = f"profit_loss_{nigerian_time.strftime('%Y%m%d_%H%M%S')}.csv"
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8') as temp_file:
                temp_file.write(output.getvalue())
                temp_file_path = temp_file.name
            
            def remove_file(response):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass
                return response
            
            return send_file(
                temp_file_path,
                as_attachment=True,
                download_name=filename,
                mimetype='text/csv'
            )
            
        except Exception as e:
            print(f"Error generating P&L CSV: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to generate CSV report',
                'error': str(e)
            }), 500
    
    return reports_pl_bp