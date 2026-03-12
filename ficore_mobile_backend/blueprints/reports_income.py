# Income Report Blueprint
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime, timedelta
import io
import csv
import tempfile
import os

try:
    from utils.generator_income import IncomeGenerator
    from utils.generator_core import get_nigerian_time
except ImportError:
    # Fallback for missing modules
    class IncomeGenerator:
        def __init__(self, *args, **kwargs):
            pass
        def generate_income_report(self, *args, **kwargs):
            return {'success': False, 'message': 'Income generator not available'}
    
    def get_nigerian_time():
        return datetime.utcnow()

def init_income_blueprint(mongo, token_required):
    """Initialize Income reports blueprint"""
    
    reports_income_bp = Blueprint('reports_income', __name__, url_prefix='/api/reports')
    
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
    
    def get_income_data(current_user, start_date=None, end_date=None, tag_filter="all"):
        """Get income data for reports"""
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
        
        # Get incomes
        incomes = list(mongo.db.incomes.find(base_query))
        
        # Filter by date range
        if start_date or end_date:
            incomes = filter_by_date_range(incomes, 'date', start_date, end_date)
        
        # Get credit transactions
        credit_transactions = list(mongo.db.credit_transactions.find({
            'userId': user_id,
            'status': 'completed'
        }))
        
        if start_date or end_date:
            credit_transactions = filter_by_date_range(credit_transactions, 'createdAt', start_date, end_date)
        
        return {
            'incomes': incomes,
            'creditTransactions': credit_transactions
        }
    
    @reports_income_bp.route('/income-pdf', methods=['POST'])
    @token_required
    def export_income_pdf(current_user):
        """Export Income report as PDF"""
        try:
            request_data = request.get_json() or {}
            tag_filter = request_data.get('tagFilter', 'all')
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Get income data
            export_data = get_income_data(current_user, start_date, end_date, tag_filter)
            
            # Generate PDF
            pdf_generator = IncomeGenerator()
            pdf_buffer = pdf_generator.generate_income_report(
                user_data=current_user,
                export_data=export_data,
                tag_filter=tag_filter
            )
            
            # Generate filename
            nigerian_time = get_nigerian_time()
            filename = f"income_report_{nigerian_time.strftime('%Y%m%d_%H%M%S')}.pdf"
            
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            print(f"Error generating Income PDF: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to generate PDF report',
                'error': str(e)
            }), 500
    
    @reports_income_bp.route('/income-csv', methods=['POST'])
    @token_required
    def export_income_csv(current_user):
        """Export Income report as CSV"""
        try:
            request_data = request.get_json() or {}
            tag_filter = request_data.get('tagFilter', 'all')
            
            # Parse date range
            start_date, end_date = parse_date_range(request_data)
            
            # Get income data
            export_data = get_income_data(current_user, start_date, end_date, tag_filter)
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Date', 'Category', 'Description', 'Amount'])
            
            # Write incomes
            total_income = 0
            for income in export_data.get('incomes', []):
                writer.writerow([
                    income.get('date', ''),
                    income.get('category', ''),
                    income.get('description', ''),
                    income.get('amount', 0)
                ])
                total_income += income.get('amount', 0)
            
            # Write credit transactions
            for transaction in export_data.get('creditTransactions', []):
                writer.writerow([
                    transaction.get('createdAt', ''),
                    'Credit Transaction',
                    transaction.get('description', ''),
                    f"{transaction.get('amount', 0)} FC"
                ])
            
            # Write summary
            writer.writerow([])
            writer.writerow(['Summary', '', '', ''])
            writer.writerow(['Total Income', '', '', total_income])
            
            # Create response
            output.seek(0)
            
            # Generate filename
            nigerian_time = get_nigerian_time()
            filename = f"income_report_{nigerian_time.strftime('%Y%m%d_%H%M%S')}.csv"
            
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
            print(f"Error generating Income CSV: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to generate CSV report',
                'error': str(e)
            }), 500
    
    return reports_income_bp