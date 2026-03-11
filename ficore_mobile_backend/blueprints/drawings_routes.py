"""
Drawings Routes - Phase 2.2
GET endpoint for viewing drawings history
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Blueprint, request, jsonify
from datetime import datetime
from utils.decimal_helpers import safe_sum  # CRITICAL FIX (Mar 9, 2026): Handle Decimal128 in sum operations

def init_drawings_blueprint(mongo, token_required, serialize_doc):
    """Initialize the drawings blueprint"""
    drawings_bp = Blueprint('drawings', __name__, url_prefix='/drawings')
    
    @drawings_bp.route('', methods=['GET'])
    @token_required
    def get_drawings(current_user):
        """
        Get drawings history for current user
        
        Query params:
        - page: Page number (default: 1)
        - limit: Items per page (default: 20)
        - startDate: Filter start date
        - endDate: Filter end date
        """
        try:
            # Pagination
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            skip = (page - 1) * limit
            
            # Build query
            query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            
            # Date filters
            start_date = request.args.get('startDate')
            end_date = request.args.get('endDate')
            
            if start_date or end_date:
                query['date'] = {}
                if start_date:
                    query['date']['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    query['date']['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))
            
            # Get drawings from drawings collection (primary source as of Feb 28, 2026)
            # Fallback to cash_adjustments for backward compatibility
            drawings = list(mongo.db.drawings.find(query).sort('date', -1).skip(skip).limit(limit))
            total = mongo.db.drawings.count_documents(query)
            
            # If no drawings found in drawings collection, check cash_adjustments (backward compatibility)
            if total == 0:
                query['type'] = 'drawing'
                drawings = list(mongo.db.cash_adjustments.find(query).sort('date', -1).skip(skip).limit(limit))
                total = mongo.db.cash_adjustments.count_documents(query)
                print(f'⚠️ Fetched {total} drawings from cash_adjustments (backward compatibility)')
            else:
                print(f'✓ Fetched {total} drawings from drawings collection')
            
            # Serialize
            drawings_list = []
            for drawing in drawings:
                drawing_data = serialize_doc(drawing)
                
                # Get linked expense if exists
                if drawing.get('linkedExpenseId'):
                    expense = mongo.db.expenses.find_one({'_id': drawing['linkedExpenseId']})
                    if expense:
                        drawing_data['linkedExpense'] = {
                            'id': str(expense['_id']),
                            'description': expense.get('description'),
                            'category': expense.get('category'),
                            'amount': expense.get('amount')
                        }
                
                drawings_list.append(drawing_data)
            
            # Calculate total drawings
            total_drawings = safe_sum(d.get('amount', 0) for d in drawings)
            
            return jsonify({
                'success': True,
                'data': drawings_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                },
                'summary': {
                    'totalDrawings': total_drawings,
                    'count': len(drawings_list)
                },
                'message': 'Drawings retrieved successfully'
            }), 200
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve drawings',
                'error': str(e)
            }), 500
    
    @drawings_bp.route('/summary', methods=['GET'])
    @token_required
    def get_drawings_summary(current_user):
        """Get drawings summary for current user"""
        try:
            # Get user's total drawings
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            total_drawings = user.get('drawings', 0) if user else 0
            
            # Count active drawings from drawings collection (primary source as of Feb 28, 2026)
            # Fallback to cash_adjustments for backward compatibility
            count = mongo.db.drawings.count_documents({
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            })
            
            # If no drawings in drawings collection, check cash_adjustments (backward compatibility)
            if count == 0:
                count = mongo.db.cash_adjustments.count_documents({
                    'userId': current_user['_id'],
                    'type': 'drawing',
                    'status': 'active',
                    'isDeleted': False
                })
                print(f'⚠️ Counted {count} drawings from cash_adjustments (backward compatibility)')
            else:
                print(f'✓ Counted {count} drawings from drawings collection')
            
            return jsonify({
                'success': True,
                'data': {
                    'totalDrawings': total_drawings,
                    'count': count,
                    'lastUpdate': user.get('lastEquityUpdate').isoformat() + 'Z' if user and user.get('lastEquityUpdate') else None
                },
                'message': 'Drawings summary retrieved successfully'
            }), 200
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve drawings summary',
                'error': str(e)
            }), 500
    
    return drawings_bp
