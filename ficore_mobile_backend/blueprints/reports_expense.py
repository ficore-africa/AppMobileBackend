# Expense Report Blueprint
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime, timedelta
import io
import csv
import tempfile
import os

try:
    from utils.generator_expense import ExpenseGenerator
    from utils.generator_core import get_nigerian_time
except ImportError:
    # Fallback for missing modules
    class ExpenseGenerator:
        def __init__(self, *args, **kwargs):
            pass
        def generate_expense_report(self, *args, **kwargs):
            return {'success': False, 'message': 'Expense generator not available'}
    
    def get_nigerian_time():
        return datetime.utcnow()

def init_expense_blueprint(mongo, token_required):
    """Initialize Expense reports blueprint"""
    
    reports_expense_bp = Blueprint('reports_expense', __name__, url_prefix='/api/reports')
    
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
    
    def get_expense_data(current_user, start_date=None, end_date=None, tag_filter="all"):
        """Get expense data for reports"""
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
        
        # Get expenses
        expenses = list(mongo.db.expenses.find(base_query))
        
        # Filter by date range
        if start_date or end_date:
            expenses = filter_by_date_range(expenses, 'date', start_date, end_date)
        
        return {
            'expenses': expenses
        }
    
    @reports_expense_bp.route('/expense-pdf', methods=['POST'])
    @token_required
    def export_expense_pdf(current_user):
        """Export Expense report as PDF"""
        try:
            request_data = request.get_json() or {}
            tag_filter = request_data.get('tagFilter', 'all')
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Get expense data
            export_data = get_expense_data(current_user, start_date, end_date, tag_filter)
            
            # Generate PDF
            pdf_generator = ExpenseGenerator()
            pdf_buffer = pdf_generator.generate_expense_report(
                user_data=current_user,
                export_data=export_data,
                tag_filter=tag_filter
            )
            
            # Generate filename
            nigerian_time = get_nigerian_time()
            filename = f"expense_report_{nigerian_time.strftime('%Y%m%d_%H%M%S')}.pdf"
            
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            print(f"Error generating Expense PDF: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to generate PDF report',
                'error': str(e)
            }), 500
    
    @reports_expense_bp.route('/expense-csv', methods=['POST'])
    @token_required
    def export_expense_csv(current_user):
        """Export Expense report as CSV"""
        try:
            request_data = request.get_json() or {}
            tag_filter = request_data.get('tagFilter', 'all')
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Get expense data
            export_data = get_expense_data(current_user, start_date, end_date, tag_filter)
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Date', 'Category', 'Description', 'Amount'])
            
            # Write expenses
            total_cogs = 0
            total_operating = 0
            
            for expense in export_data.get('expenses', []):
                writer.writerow([
                    expense.get('date', ''),
                    expense.get('category', ''),
                    expense.get('description', ''),
                    expense.get('amount', 0)
                ])
                
                # Separate COGS from Operating
                if expense.get('category') == 'Cost of Goods Sold':
                    total_cogs += safe_float(expense.get('amount', 0))
                else:
                    total_operating += safe_float(expense.get('amount', 0))
            
            total_expenses = round(total_cogs + total_operating, 2)
            
            # Write summary
            writer.writerow([])
            writer.writerow(['Summary', '', '', ''])
            writer.writerow(['Cost of Goods Sold', '', '', round(total_cogs, 2)])
            writer.writerow(['Operating Expenses', '', '', round(total_operating, 2)])
            writer.writerow(['Total Expenses', '', '', total_expenses])
            
            # Create response
            output.seek(0)
            
            # Generate filename
            nigerian_time = get_nigerian_time()
            filename = f"expense_report_{nigerian_time.strftime('%Y%m%d_%H%M%S')}.csv"
            
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
            print(f"Error generating Expense CSV: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to generate CSV report',
                'error': str(e)
            }), 500
    
    return reports_expense_bp