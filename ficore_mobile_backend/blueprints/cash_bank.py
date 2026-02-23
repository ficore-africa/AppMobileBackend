"""
Opening Balances Management Blueprint

MODERNIZATION (Feb 22, 2026): Renamed from "Cash/Bank Management" to "Opening Balances"
Handles opening balances for cash/bank AND equity, plus manual adjustments (drawings, capital deposits)

This is the "Financial Setup Hub" where users establish their starting financial position:
- Opening Cash/Bank Balance (what's in the bank at start of period)
- Opening Equity (owner's capital invested at start of period)
- Drawings (owner withdrawals during period)
- Capital Deposits (additional owner investments during period)

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
        """
        Get user's opening balances (cash/bank and equity)
        
        MODERNIZATION (Feb 22, 2026): Renamed from "Cash/Bank Management" to "Opening Balances"
        Now handles both opening cash/bank balance AND opening equity
        """
        try:
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            
            if not user:
                print(f'Error: User not found with ID: {current_user["_id"]}')
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Default to 0.0 if fields don't exist
            opening_cash_balance = user.get('openingCashBalance', 0.0)
            opening_equity = user.get('openingEquity', 0.0)
            
            print(f'✓ Opening balances fetched for user {current_user["_id"]}: Cash=₦{opening_cash_balance}, Equity=₦{opening_equity}')
            
            return jsonify({
                'success': True,
                'openingCashBalance': opening_cash_balance,
                'openingEquity': opening_equity
            }), 200
            
        except Exception as e:
            print(f'❌ Error fetching opening balances: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to fetch opening balances'
            }), 500
    
    @cash_bank_bp.route('/opening-balance', methods=['POST'])
    @token_required
    def set_opening_balance(current_user):
        """
        Set user's opening balances (cash/bank and/or equity)
        
        MODERNIZATION (Feb 22, 2026): Now handles both cash/bank and equity opening balances
        Users can set one or both in a single request
        """
        try:
            data = request.get_json()
            
            # Get values from request (optional - user can set one or both)
            opening_cash_balance = data.get('openingCashBalance')
            opening_equity = data.get('openingEquity')
            
            # Validate if provided
            if opening_cash_balance is not None:
                opening_cash_balance = float(opening_cash_balance)
                if opening_cash_balance < 0:
                    return jsonify({
                        'success': False,
                        'message': 'Opening cash balance cannot be negative'
                    }), 400
            
            if opening_equity is not None:
                opening_equity = float(opening_equity)
                # Note: Opening equity CAN be negative (if business started with debt)
            
            # Build update document
            update_doc = {}
            if opening_cash_balance is not None:
                update_doc['openingCashBalance'] = opening_cash_balance
                update_doc['openingCashBalanceSetAt'] = datetime.utcnow()
            
            if opening_equity is not None:
                update_doc['openingEquity'] = opening_equity
                update_doc['openingEquitySetAt'] = datetime.utcnow()
            
            if not update_doc:
                return jsonify({
                    'success': False,
                    'message': 'No opening balance values provided'
                }), 400
            
            # Update user's opening balances
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': update_doc}
            )
            
            # Build response message
            updated_items = []
            if opening_cash_balance is not None:
                updated_items.append(f'Cash/Bank: ₦{opening_cash_balance:,.2f}')
            if opening_equity is not None:
                updated_items.append(f'Equity: ₦{opening_equity:,.2f}')
            
            message = f'Opening balances set successfully: {", ".join(updated_items)}'
            
            return jsonify({
                'success': True,
                'message': message,
                'openingCashBalance': opening_cash_balance,
                'openingEquity': opening_equity
            }), 200
            
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid balance amount'
            }), 400
        except Exception as e:
            print(f'Error setting opening balances: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to set opening balances'
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
