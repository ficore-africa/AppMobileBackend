"""
Cash/Bank Management Blueprint
Handles opening balance, manual adjustments (drawings, capital deposits), and balance calculations
Part of the Virtual Vault strategy for double-entry bookkeeping
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def init_cash_bank_blueprint(mongo, token_required):
    """Initialize the cash/bank management blueprint"""
    cash_bank_bp = Blueprint('cash_bank', __name__, url_prefix='/api/cash-bank')
    
    @cash_bank_bp.route('/opening-balance', methods=['GET'])
    @token_required
    def get_opening_balance(current_user):
        """Get user's opening cash/bank balance"""
        try:
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            
            if not user:
                print(f'Error: User not found with ID: {current_user["_id"]}')
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Default to 0.0 if field doesn't exist
            opening_balance = user.get('openingCashBalance', 0.0)
            
            print(f'✓ Opening balance fetched for user {current_user["_id"]}: ₦{opening_balance}')
            
            return jsonify({
                'success': True,
                'openingBalance': opening_balance
            }), 200
            
        except Exception as e:
            print(f'❌ Error fetching opening balance: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to fetch opening balance'
            }), 500
    
    @cash_bank_bp.route('/opening-balance', methods=['POST'])
    @token_required
    def set_opening_balance(current_user):
        """Set user's opening cash/bank balance (one-time setup)"""
        try:
            data = request.get_json()
            opening_balance = float(data.get('openingBalance', 0.0))
            
            if opening_balance < 0:
                return jsonify({
                    'success': False,
                    'message': 'Opening balance cannot be negative'
                }), 400
            
            # Update user's opening balance
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {
                    '$set': {
                        'openingCashBalance': opening_balance,
                        'openingCashBalanceSetAt': datetime.utcnow()
                    }
                }
            )
            
            return jsonify({
                'success': True,
                'message': 'Opening balance set successfully',
                'openingBalance': opening_balance
            }), 200
            
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid balance amount'
            }), 400
        except Exception as e:
            print(f'Error setting opening balance: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to set opening balance'
            }), 500
    
    @cash_bank_bp.route('/adjustments', methods=['GET'])
    @token_required
    def get_adjustments(current_user):
        """Get all cash/bank adjustments (drawings, capital deposits)"""
        try:
            # Fetch adjustments sorted by date (newest first)
            adjustments = list(mongo.db.cash_adjustments.find(
                {'userId': current_user['_id']},
                sort=[('date', -1)]
            ))
            
            # Convert ObjectId to string for JSON serialization
            for adjustment in adjustments:
                adjustment['_id'] = str(adjustment['_id'])
                adjustment['userId'] = str(adjustment['userId'])
            
            return jsonify({
                'success': True,
                'adjustments': adjustments
            }), 200
            
        except Exception as e:
            print(f'Error fetching adjustments: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to fetch adjustments'
            }), 500
    
    @cash_bank_bp.route('/adjustments', methods=['POST'])
    @token_required
    def create_adjustment(current_user):
        """Create a new cash/bank adjustment (drawing or capital deposit)"""
        try:
            data = request.get_json()
            
            # Validate required fields
            adjustment_type = data.get('type')  # 'drawing' or 'capital'
            amount = float(data.get('amount', 0.0))
            description = data.get('description', '').strip()
            date_str = data.get('date')
            
            if not adjustment_type or adjustment_type not in ['drawing', 'capital']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid adjustment type. Must be "drawing" or "capital"'
                }), 400
            
            if amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Amount must be greater than zero'
                }), 400
            
            if not description:
                return jsonify({
                    'success': False,
                    'message': 'Description is required'
                }), 400
            
            # Parse date
            try:
                adjustment_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except:
                adjustment_date = datetime.utcnow()
            
            # Create adjustment entry
            adjustment = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'type': adjustment_type,
                'amount': amount,
                'description': description,
                'date': adjustment_date,
                'status': 'active',
                'isDeleted': False,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.cash_adjustments.insert_one(adjustment)
            
            # Convert ObjectId to string for response
            adjustment['_id'] = str(adjustment['_id'])
            adjustment['userId'] = str(adjustment['userId'])
            
            return jsonify({
                'success': True,
                'message': f'{"Drawing" if adjustment_type == "drawing" else "Capital deposit"} recorded successfully',
                'adjustment': adjustment
            }), 201
            
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid amount'
            }), 400
        except Exception as e:
            print(f'Error creating adjustment: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to create adjustment'
            }), 500
    
    @cash_bank_bp.route('/adjustments/<adjustment_id>', methods=['DELETE'])
    @token_required
    def delete_adjustment(current_user, adjustment_id):
        """Soft delete a cash/bank adjustment"""
        try:
            # Verify adjustment belongs to user
            adjustment = mongo.db.cash_adjustments.find_one({
                '_id': ObjectId(adjustment_id),
                'userId': current_user['_id']
            })
            
            if not adjustment:
                return jsonify({
                    'success': False,
                    'message': 'Adjustment not found'
                }), 404
            
            # Soft delete (mark as deleted, don't actually remove)
            mongo.db.cash_adjustments.update_one(
                {'_id': ObjectId(adjustment_id)},
                {
                    '$set': {
                        'status': 'voided',
                        'isDeleted': True,
                        'deletedAt': datetime.utcnow()
                    }
                }
            )
            
            return jsonify({
                'success': True,
                'message': 'Adjustment deleted successfully'
            }), 200
            
        except Exception as e:
            print(f'Error deleting adjustment: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to delete adjustment'
            }), 500
    
    @cash_bank_bp.route('/balance', methods=['GET'])
    @token_required
    def get_current_balance(current_user):
        """
        Calculate current cash/bank balance using virtual double-entry system
        Formula: Opening Balance + Total Income - Total Expenses - Total Drawings + Total Capital
        """
        try:
            # Get opening balance
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            opening_balance = user.get('openingCashBalance', 0.0)
            
            # Get total income (active entries only)
            total_income = 0.0
            income_cursor = mongo.db.incomes.find({
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            })
            for income in income_cursor:
                total_income += income.get('amount', 0.0)
            
            # Get total expenses (active entries only)
            total_expenses = 0.0
            expense_cursor = mongo.db.expenses.find({
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            })
            for expense in expense_cursor:
                total_expenses += expense.get('amount', 0.0)
            
            # Get total drawings and capital deposits (active entries only)
            total_drawings = 0.0
            total_capital = 0.0
            adjustment_cursor = mongo.db.cash_adjustments.find({
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            })
            for adjustment in adjustment_cursor:
                if adjustment.get('type') == 'drawing':
                    total_drawings += adjustment.get('amount', 0.0)
                elif adjustment.get('type') == 'capital':
                    total_capital += adjustment.get('amount', 0.0)
            
            # Calculate current balance
            current_balance = opening_balance + total_income - total_expenses - total_drawings + total_capital
            
            return jsonify({
                'success': True,
                'currentBalance': current_balance,
                'breakdown': {
                    'openingBalance': opening_balance,
                    'totalIncome': total_income,
                    'totalExpenses': total_expenses,
                    'totalDrawings': total_drawings,
                    'totalCapital': total_capital
                }
            }), 200
            
        except Exception as e:
            print(f'Error calculating balance: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to calculate balance'
            }), 500
    
    return cash_bank_bp
