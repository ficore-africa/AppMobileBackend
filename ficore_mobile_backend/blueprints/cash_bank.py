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
from utils.decimal_helpers import safe_float, safe_sum

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def init_cash_bank_blueprint(mongo, token_required):
    """Initialize the cash/bank management blueprint"""
    cash_bank_bp = Blueprint('cash_bank', __name__, url_prefix='/api/cash-bank')
    
    @cash_bank_bp.route('/opening-balance', methods=['GET'])
    @token_required
    def get_opening_balance(current_user):
        """
        Get user's opening balances (cash/bank, equity, and liability)
        
        MODERNIZATION (Feb 22, 2026): Renamed from "Cash/Bank Management" to "Opening Balances"
        Now handles cash/bank, equity, AND liability (Feb 25, 2026)
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
            opening_liability = user.get('openingLiability', 0.0)  # NEW (Feb 25, 2026)
            is_locked = user.get('openingBalancesLocked', False)  # NEW (Feb 25, 2026)
            set_at = user.get('openingBalancesSetAt')  # NEW (Feb 25, 2026)
            
            # Calculate accounting equation balance
            assets = opening_cash_balance
            liabilities_plus_equity = opening_liability + opening_equity
            imbalance = assets - liabilities_plus_equity
            is_balanced = abs(imbalance) < 0.01
            
            print(f'✓ Opening balances fetched for user {current_user["_id"]}: Cash=₦{opening_cash_balance}, Equity=₦{opening_equity}, Liability=₦{opening_liability}')
            print(f'  Accounting Equation: ₦{assets} = ₦{opening_liability} + ₦{opening_equity} (Imbalance: ₦{imbalance})')
            
            # CRITICAL FIX: Wrap data in 'data' field for DioApiClient compatibility
            return jsonify({
                'success': True,
                'data': {
                    'openingCashBalance': opening_cash_balance,
                    'openingEquity': opening_equity,
                    'openingLiability': opening_liability,  # NEW
                    'isLocked': is_locked,  # NEW
                    'setAt': set_at.isoformat() if set_at else None,  # NEW
                    'accountingEquation': {  # NEW
                        'assets': assets,
                        'liabilities': opening_liability,
                        'equity': opening_equity,
                        'imbalance': imbalance,
                        'isBalanced': is_balanced
                    }
                }
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
        Set user's opening balances (cash/bank, equity, and/or liability)
        
        MODERNIZATION (Feb 22, 2026): Now handles cash/bank, equity, AND liability (Feb 25, 2026)
        LOCK MECHANISM (Feb 25, 2026): Locks opening balances after first set
        """
        try:
            data = request.get_json()
            
            # Check if opening balances are locked
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            if user.get('openingBalancesLocked'):
                return jsonify({
                    'success': False,
                    'message': 'Opening balances are locked. Use the "Danger Zone" to unlock, or use Adjustments screen to make changes.',
                    'locked': True,
                    'setAt': user.get('openingBalancesSetAt').isoformat() if user.get('openingBalancesSetAt') else None
                }), 403
            
            # Get values from request (optional - user can set one or more)
            opening_cash_balance = data.get('openingCashBalance')
            opening_equity = data.get('openingEquity')
            opening_liability = data.get('openingLiability')  # NEW (Feb 25, 2026)
            
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
            
            if opening_liability is not None:
                opening_liability = float(opening_liability)
                if opening_liability < 0:
                    return jsonify({
                        'success': False,
                        'message': 'Opening liability cannot be negative'
                    }), 400
            
            # Build update document
            update_doc = {}
            if opening_cash_balance is not None:
                update_doc['openingCashBalance'] = opening_cash_balance
                update_doc['openingCashBalanceSetAt'] = datetime.utcnow()
            
            if opening_equity is not None:
                update_doc['openingEquity'] = opening_equity
                update_doc['openingEquitySetAt'] = datetime.utcnow()
            
            if opening_liability is not None:
                update_doc['openingLiability'] = opening_liability
                update_doc['openingLiabilitySetAt'] = datetime.utcnow()
            
            if not update_doc:
                return jsonify({
                    'success': False,
                    'message': 'No opening balance values provided'
                }), 400
            
            # Lock opening balances after first set (NEW - Feb 25, 2026)
            if not user.get('openingBalancesLocked'):
                update_doc['openingBalancesLocked'] = True
                update_doc['openingBalancesSetAt'] = datetime.utcnow()
                print(f'🔒 Locking opening balances for user {current_user["_id"]}')
            
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
            if opening_liability is not None:
                updated_items.append(f'Liability: ₦{opening_liability:,.2f}')
            
            message = f'Opening balances set successfully: {", ".join(updated_items)}'
            
            # Calculate accounting equation balance for response
            final_cash = opening_cash_balance if opening_cash_balance is not None else user.get('openingCashBalance', 0.0)
            final_equity = opening_equity if opening_equity is not None else user.get('openingEquity', 0.0)
            final_liability = opening_liability if opening_liability is not None else user.get('openingLiability', 0.0)
            
            assets = final_cash
            liabilities_plus_equity = final_liability + final_equity
            imbalance = assets - liabilities_plus_equity
            is_balanced = abs(imbalance) < 0.01
            
            print(f'✓ Opening balances updated: Cash=₦{final_cash}, Equity=₦{final_equity}, Liability=₦{final_liability}')
            print(f'  Accounting Equation: ₦{assets} = ₦{final_liability} + ₦{final_equity} (Imbalance: ₦{imbalance})')
            
            return jsonify({
                'success': True,
                'message': message,
                'openingCashBalance': final_cash,
                'openingEquity': final_equity,
                'openingLiability': final_liability,
                'locked': True,  # Always locked after first set
                'accountingEquation': {
                    'assets': assets,
                    'liabilities': final_liability,
                    'equity': final_equity,
                    'imbalance': imbalance,
                    'isBalanced': is_balanced
                }
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
    
    @cash_bank_bp.route('/unlock-opening-balances', methods=['POST'])
    @token_required
    def unlock_opening_balances(current_user):
        """
        Unlock opening balances (Danger Zone feature)
        Requires confirmation and logs action for audit trail
        
        NEW (Feb 25, 2026): Allows users to unlock opening balances if they made mistakes
        """
        try:
            data = request.get_json()
            confirmation = data.get('confirmation', '')
            
            if confirmation != 'RESET':
                return jsonify({
                    'success': False,
                    'message': 'Invalid confirmation. Please type RESET to confirm.'
                }), 400
            
            # Unlock opening balances
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {
                    '$set': {
                        'openingBalancesLocked': False,
                        'openingBalancesUnlockedAt': datetime.utcnow(),
                        'openingBalancesUnlockedBy': current_user['_id']
                    }
                }
            )
            
            # Log action for audit trail
            try:
                mongo.db.audit_log.insert_one({
                    'userId': current_user['_id'],
                    'action': 'unlock_opening_balances',
                    'timestamp': datetime.utcnow(),
                    'reason': 'User requested unlock via Danger Zone',
                    'ipAddress': request.remote_addr,
                    'userAgent': request.headers.get('User-Agent')
                })
            except Exception as log_error:
                print(f'Warning: Failed to log unlock action: {str(log_error)}')
            
            print(f'🔓 Opening balances unlocked for user {current_user["_id"]}')
            
            return jsonify({
                'success': True,
                'message': 'Opening balances unlocked successfully. You can now edit them.'
            }), 200
            
        except Exception as e:
            print(f'Error unlocking opening balances: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to unlock opening balances'
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
            
            # Convert ALL ObjectId fields to string for JSON serialization
            for adjustment in adjustments:
                adjustment['_id'] = str(adjustment['_id'])
                adjustment['userId'] = str(adjustment['userId'])
                
                # CRITICAL FIX (Feb 28, 2026): Convert datetime fields to ISO format strings
                if 'date' in adjustment and adjustment['date']:
                    adjustment['date'] = adjustment['date'].isoformat()
                if 'createdAt' in adjustment and adjustment['createdAt']:
                    adjustment['createdAt'] = adjustment['createdAt'].isoformat()
                if 'updatedAt' in adjustment and adjustment['updatedAt']:
                    adjustment['updatedAt'] = adjustment['updatedAt'].isoformat()
                if 'deletedAt' in adjustment and adjustment['deletedAt']:
                    adjustment['deletedAt'] = adjustment['deletedAt'].isoformat()
                
                # CRITICAL FIX (Feb 28, 2026): Convert assetId if present
                if 'assetId' in adjustment and adjustment['assetId']:
                    adjustment['assetId'] = str(adjustment['assetId'])
                
                # CRITICAL FIX (Feb 28, 2026): Convert cashAdjustmentId if present
                if 'cashAdjustmentId' in adjustment and adjustment['cashAdjustmentId']:
                    adjustment['cashAdjustmentId'] = str(adjustment['cashAdjustmentId'])
                
                # CRITICAL FIX (Feb 28, 2026): Convert capitalEntryId if present
                if 'capitalEntryId' in adjustment and adjustment['capitalEntryId']:
                    adjustment['capitalEntryId'] = str(adjustment['capitalEntryId'])
            
            # CRITICAL FIX: Wrap data in 'data' field for DioApiClient compatibility
            return jsonify({
                'success': True,
                'data': {
                    'adjustments': adjustments
                }
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
            
            # NEW (Feb 28, 2026): Also save to dedicated collections for clarity
            # This avoids naming confusion and provides redundancy
            if adjustment_type == 'drawing':
                # Save to drawings collection
                drawing_entry = adjustment.copy()
                mongo.db.drawings.insert_one(drawing_entry)
                print(f'✓ Drawing saved to both cash_adjustments and drawings collections')
                
                # Calculate total drawings from all active drawing adjustments
                drawing_amounts = []
                all_drawings = mongo.db.cash_adjustments.find({
                    'userId': current_user['_id'],
                    'type': 'drawing',
                    'status': 'active',
                    'isDeleted': False
                })
                for drawing in all_drawings:
                    drawing_amounts.append(drawing.get('amount', 0.0))
                total_drawings = safe_sum(drawing_amounts)
                
                # Update user.drawings field
                mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'drawings': total_drawings}}
                )
            
            elif adjustment_type == 'capital':
                # Save to capital_contributions collection
                capital_entry = adjustment.copy()
                mongo.db.capital_contributions.insert_one(capital_entry)
                print(f'✓ Capital contribution saved to both cash_adjustments and capital_contributions collections')
                
                # Calculate total capital from all active capital adjustments
                capital_amounts = []
                all_capital = mongo.db.cash_adjustments.find({
                    'userId': current_user['_id'],
                    'type': 'capital',
                    'status': 'active',
                    'isDeleted': False
                })
                for capital in all_capital:
                    capital_amounts.append(capital.get('amount', 0.0))
                total_capital = safe_sum(capital_amounts)
                
                # Update user.capital field
                mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'capital': total_capital}}
                )
            
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
            
            # NEW (Feb 28, 2026): Also soft delete from dedicated collections
            adjustment_type = adjustment.get('type')
            
            if adjustment_type == 'drawing':
                # Soft delete from drawings collection
                mongo.db.drawings.update_one(
                    {'_id': ObjectId(adjustment_id)},
                    {
                        '$set': {
                            'status': 'voided',
                            'isDeleted': True,
                            'deletedAt': datetime.utcnow()
                        }
                    }
                )
                print(f'✓ Drawing soft deleted from both cash_adjustments and drawings collections')
                
                # Recalculate total drawings from remaining active drawing adjustments
                drawing_amounts = []
                all_drawings = mongo.db.cash_adjustments.find({
                    'userId': current_user['_id'],
                    'type': 'drawing',
                    'status': 'active',
                    'isDeleted': False
                })
                for drawing in all_drawings:
                    drawing_amounts.append(drawing.get('amount', 0.0))
                total_drawings = safe_sum(drawing_amounts)
                
                # Update user.drawings field
                mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'drawings': total_drawings}}
                )
            
            elif adjustment_type == 'capital':
                # Soft delete from capital_contributions collection
                mongo.db.capital_contributions.update_one(
                    {'_id': ObjectId(adjustment_id)},
                    {
                        '$set': {
                            'status': 'voided',
                            'isDeleted': True,
                            'deletedAt': datetime.utcnow()
                        }
                    }
                )
                print(f'✓ Capital contribution soft deleted from both cash_adjustments and capital_contributions collections')
                
                # Recalculate total capital from remaining active capital adjustments
                capital_amounts = []
                all_capital = mongo.db.cash_adjustments.find({
                    'userId': current_user['_id'],
                    'type': 'capital',
                    'status': 'active',
                    'isDeleted': False
                })
                for capital in all_capital:
                    capital_amounts.append(capital.get('amount', 0.0))
                total_capital = safe_sum(capital_amounts)
                
                # Update user.capital field
                mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'capital': total_capital}}
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
    
    @cash_bank_bp.route('/founder-capital', methods=['GET'])
    @token_required
    def get_founder_capital(current_user):
        """
        Get founder capital contributions from incomes collection
        These are historical capital contributions (sourceType='capital_contribution')
        that appear in Balance Sheet but not in regular adjustments
        """
        try:
            # Fetch founder capital contributions from incomes collection
            founder_capital = list(mongo.db.incomes.find(
                {
                    'userId': current_user['_id'],
                    'sourceType': 'capital_contribution',
                    'status': 'active',
                    'isDeleted': False
                },
                sort=[('date', -1)]
            ))
            
            # Convert ObjectId fields to string for JSON serialization
            for capital in founder_capital:
                capital['_id'] = str(capital['_id'])
                capital['userId'] = str(capital['userId'])
                
                # Convert datetime fields to ISO format strings
                if 'date' in capital and capital['date']:
                    capital['date'] = capital['date'].isoformat()
                if 'createdAt' in capital and capital['createdAt']:
                    capital['createdAt'] = capital['createdAt'].isoformat()
                if 'updatedAt' in capital and capital['updatedAt']:
                    capital['updatedAt'] = capital['updatedAt'].isoformat()
            
            print(f'✓ Found {len(founder_capital)} founder capital contributions for user {current_user["_id"]}')
            
            # Wrap data in 'data' field for DioApiClient compatibility
            return jsonify({
                'success': True,
                'data': {
                    'founderCapital': founder_capital
                }
            }), 200
            
        except Exception as e:
            print(f'Error fetching founder capital: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to fetch founder capital'
            }), 500

    @cash_bank_bp.route('/financial-overview', methods=['GET'])
    @token_required
    def get_financial_overview(current_user):
        """
        Get comprehensive financial overview for Financial Setup Hub
        Returns capital, cash/bank, liabilities, and assets data
        """
        try:
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # 1. CAPITAL DATA
            # Founder capital from incomes collection
            founder_capital = list(mongo.db.incomes.find(
                {
                    'userId': current_user['_id'],
                    'sourceType': 'capital_contribution',
                    'status': 'active',
                    'isDeleted': False
                }
            ))
            total_founder_capital = safe_sum([capital.get('amount', 0.0) for capital in founder_capital])
            
            # User capital from cash_adjustments collection
            user_capital = list(mongo.db.cash_adjustments.find(
                {
                    'userId': current_user['_id'],
                    'type': 'capital',
                    'status': 'active',
                    'isDeleted': False
                }
            ))
            total_user_capital = safe_sum([capital.get('amount', 0.0) for capital in user_capital])
            
            # 2. CASH & BANK DATA
            opening_cash_balance = safe_float(user.get('openingCashBalance', 0.0))
            
            # Calculate current balance using same logic as /balance endpoint
            income_query = get_active_transactions_query(current_user['_id'])
            income_amounts = []
            income_cursor = mongo.db.incomes.find(income_query)
            for income in income_cursor:
                income_amounts.append(income.get('amount', 0.0))
            total_income = safe_sum(income_amounts)
            
            expense_query = get_active_transactions_query(current_user['_id'])
            expense_amounts = []
            expense_cursor = mongo.db.expenses.find(expense_query)
            for expense in expense_cursor:
                expense_amounts.append(expense.get('amount', 0.0))
            total_expenses = safe_sum(expense_amounts)
            
            # Drawings and capital from adjustments
            adjustment_query = {
                'userId': current_user['_id'],
                '$or': [
                    {'status': 'active'},
                    {'status': {'$exists': False}},
                    {'status': None},
                ],
                'isDeleted': {'$ne': True}
            }
            drawing_amounts = []
            capital_amounts = []
            adjustment_cursor = mongo.db.cash_adjustments.find(adjustment_query)
            for adjustment in adjustment_cursor:
                if adjustment.get('type') == 'drawing':
                    drawing_amounts.append(adjustment.get('amount', 0.0))
                elif adjustment.get('type') == 'capital':
                    capital_amounts.append(adjustment.get('amount', 0.0))
            
            total_drawings = safe_sum(drawing_amounts)
            total_capital_adjustments = safe_sum(capital_amounts)
            
            current_cash_balance = opening_cash_balance + total_income - total_expenses - total_drawings + total_capital_adjustments
            
            # 3. LIABILITY DATA
            opening_liability = safe_float(user.get('openingLiability', 0.0))
            
            # Current liabilities (could be calculated from expenses marked as liabilities)
            # For now, use opening liability as current liability
            current_liability = opening_liability
            
            # 4. ASSET DATA
            # Get assets from assets collection
            assets = list(mongo.db.assets.find(
                {
                    'userId': current_user['_id'],
                    'status': 'active',
                    'isDeleted': False
                }
            ))
            
            # Separate current and long-term assets (simple rule: <1 year = current)
            current_assets = []
            long_term_assets = []
            
            for asset in assets:
                # For simplicity, consider all assets as long-term unless specified
                asset_type = asset.get('type', 'long-term')
                if asset_type in ['inventory', 'cash', 'receivables']:
                    current_assets.append(asset)
                else:
                    long_term_assets.append(asset)
            
            total_current_assets = safe_sum([asset.get('value', 0.0) for asset in current_assets])
            total_long_term_assets = safe_sum([asset.get('value', 0.0) for asset in long_term_assets])
            total_assets = total_current_assets + total_long_term_assets
            
            # Add cash balance to current assets
            total_current_assets += current_cash_balance
            
            # 5. SUMMARY CALCULATIONS
            total_capital = total_founder_capital + total_user_capital
            total_liabilities = current_liability  # For now, only opening liability
            
            # Accounting equation check
            accounting_assets = total_current_assets + total_long_term_assets
            accounting_liabilities_equity = total_liabilities + total_capital
            accounting_imbalance = accounting_assets - accounting_liabilities_equity
            is_balanced = abs(accounting_imbalance) < 0.01
            
            print(f'✓ Financial overview calculated for user {current_user["_id"]}:')
            print(f'   Total Capital: ₦{total_capital} (Founder: ₦{total_founder_capital}, User: ₦{total_user_capital})')
            print(f'   Cash & Bank: ₦{current_cash_balance}')
            print(f'   Total Assets: ₦{accounting_assets} (Current: ₦{total_current_assets}, Long-term: ₦{total_long_term_assets})')
            print(f'   Total Liabilities: ₦{total_liabilities}')
            print(f'   Accounting Equation: ₦{accounting_assets} = ₦{total_liabilities} + ₦{total_capital} (Imbalance: ₦{accounting_imbalance})')
            
            # Wrap data in 'data' field for DioApiClient compatibility
            return jsonify({
                'success': True,
                'data': {
                    'capital': {
                        'founderCapital': total_founder_capital,
                        'userCapital': total_user_capital,
                        'totalCapital': total_capital,
                        'founderCount': len(founder_capital),
                        'userCount': len(user_capital)
                    },
                    'cashBank': {
                        'openingBalance': opening_cash_balance,
                        'currentBalance': current_cash_balance,
                        'totalIncome': total_income,
                        'totalExpenses': total_expenses,
                        'totalDrawings': total_drawings
                    },
                    'liabilities': {
                        'openingLiability': opening_liability,
                        'currentLiability': current_liability,
                        'totalLiabilities': total_liabilities
                    },
                    'assets': {
                        'currentAssets': total_current_assets,
                        'longTermAssets': total_long_term_assets,
                        'totalAssets': accounting_assets,
                        'assetCount': len(assets)
                    },
                    'accountingEquation': {
                        'assets': accounting_assets,
                        'liabilities': total_liabilities,
                        'equity': total_capital,
                        'imbalance': accounting_imbalance,
                        'isBalanced': is_balanced
                    }
                }
            }), 200
            
        except Exception as e:
            print(f'❌ Error fetching financial overview: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to fetch financial overview'
            }), 500

    @cash_bank_bp.route('/balance', methods=['GET'])
    @token_required
    def get_current_balance(current_user):
        """
        Calculate current cash/bank balance using virtual double-entry system
        Formula: Opening Balance + Total Income - Total Expenses - Total Drawings + Total Capital
        
        CRITICAL FIX (Feb 25, 2026): Use get_active_transactions_query helper
        to handle entries without status/isDeleted fields (backward compatibility)
        """
        try:
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            # Get opening balance
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            opening_balance = safe_float(user.get('openingCashBalance', 0.0))
            
            # Get total income (active entries only - handles missing status/isDeleted fields)
            income_query = get_active_transactions_query(current_user['_id'])
            income_amounts = []
            income_cursor = mongo.db.incomes.find(income_query)
            for income in income_cursor:
                income_amounts.append(income.get('amount', 0.0))
            total_income = safe_sum(income_amounts)
            
            # Get total expenses (active entries only - handles missing status/isDeleted fields)
            expense_query = get_active_transactions_query(current_user['_id'])
            expense_amounts = []
            expense_cursor = mongo.db.expenses.find(expense_query)
            for expense in expense_cursor:
                expense_amounts.append(expense.get('amount', 0.0))
            total_expenses = safe_sum(expense_amounts)
            
            # Get total drawings and capital deposits (active entries only)
            # Use same pattern as get_active_transactions_query for consistency
            adjustment_query = {
                'userId': current_user['_id'],
                '$or': [
                    {'status': 'active'},
                    {'status': {'$exists': False}},
                    {'status': None},
                ],
                'isDeleted': {'$ne': True}
            }
            drawing_amounts = []
            capital_amounts = []
            adjustment_cursor = mongo.db.cash_adjustments.find(adjustment_query)
            for adjustment in adjustment_cursor:
                if adjustment.get('type') == 'drawing':
                    drawing_amounts.append(adjustment.get('amount', 0.0))
                elif adjustment.get('type') == 'capital':
                    capital_amounts.append(adjustment.get('amount', 0.0))
            
            total_drawings = safe_sum(drawing_amounts)
            total_capital = safe_sum(capital_amounts)
            
            # Calculate current balance
            current_balance = opening_balance + total_income - total_expenses - total_drawings + total_capital
            
            # Debug logging
            print(f'💰 Balance Calculation for user {current_user["_id"]}:')
            print(f'   Opening Balance: ₦{opening_balance}')
            print(f'   Total Income: ₦{total_income}')
            print(f'   Total Expenses: ₦{total_expenses}')
            print(f'   Total Drawings: ₦{total_drawings}')
            print(f'   Total Capital: ₦{total_capital}')
            print(f'   Current Balance: ₦{current_balance}')
            
            # CRITICAL FIX: Wrap data in 'data' field for DioApiClient compatibility
            return jsonify({
                'success': True,
                'data': {
                    'currentBalance': current_balance,
                    'breakdown': {
                        'openingBalance': opening_balance,
                        'totalIncome': total_income,
                        'totalExpenses': total_expenses,
                        'totalDrawings': total_drawings,
                        'totalCapital': total_capital
                    }
                }
            }), 200
            
        except Exception as e:
            print(f'Error calculating balance: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to calculate balance'
            }), 500
    
    @cash_bank_bp.route('/balance-breakdown-pdf', methods=['POST'])
    @token_required
    def export_balance_breakdown_pdf(current_user):
        """
        Export Balance Breakdown as PDF
        
        Generates a professional PDF showing how the current balance is calculated
        from opening balance, income, expenses, drawings, and capital deposits.
        
        This is a simplified version of the Statement of Affairs focused only on
        the cash/bank balance calculation.
        """
        try:
            # Get user data
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get opening balance
            opening_balance = safe_float(user.get('openingCashBalance', 0.0))
            
            # Calculate totals (same logic as /balance endpoint)
            # Get total income (active entries only)
            income_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            income_amounts = []
            income_cursor = mongo.db.incomes.find(income_query)
            for income in income_cursor:
                income_amounts.append(income.get('amount', 0.0))
            total_income = safe_sum(income_amounts)
            
            # Get total expenses (active entries only)
            expense_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': False
            }
            expense_amounts = []
            expense_cursor = mongo.db.expenses.find(expense_query)
            for expense in expense_cursor:
                expense_amounts.append(expense.get('amount', 0.0))
            total_expenses = safe_sum(expense_amounts)
            
            # Get total drawings and capital deposits (active entries only)
            adjustment_query = {
                'userId': current_user['_id'],
                '$or': [
                    {'status': 'active'},
                    {'status': None},
                ],
                'isDeleted': {'$ne': True}
            }
            drawing_amounts = []
            capital_amounts = []
            adjustment_cursor = mongo.db.cash_adjustments.find(adjustment_query)
            for adjustment in adjustment_cursor:
                if adjustment.get('type') == 'drawing':
                    drawing_amounts.append(adjustment.get('amount', 0.0))
                elif adjustment.get('type') == 'capital':
                    capital_amounts.append(adjustment.get('amount', 0.0))
            
            total_drawings = safe_sum(drawing_amounts)
            total_capital = safe_sum(capital_amounts)
            
            # Calculate current balance
            current_balance = opening_balance + total_income - total_expenses - total_drawings + total_capital
            
            # Prepare data for PDF generation
            balance_data = {
                'openingBalance': opening_balance,
                'totalIncome': total_income,
                'totalExpenses': total_expenses,
                'totalDrawings': total_drawings,
                'totalCapital': total_capital,
                'currentBalance': current_balance
            }
            
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', ''),
                'businessName': user.get('businessName', '') if user else '',
                'tin': user.get('taxIdentificationNumber', 'Not Provided') if user else 'Not Provided'
            }
            
            # Generate PDF using pdfgenerator
            from utils.pdfgenerator import generate_balance_breakdown_pdf
            
            pdf_bytes = generate_balance_breakdown_pdf(
                user_data=user_data,
                balance_data=balance_data
            )
            
            # Return PDF as binary response
            from flask import make_response
            response = make_response(pdf_bytes)
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'attachment; filename="balance_breakdown_{datetime.now().strftime("%Y%m%d")}.pdf"'
            
            print(f'✅ Balance breakdown PDF generated for user {current_user["_id"]}')
            
            return response
            
        except Exception as e:
            print(f'❌ Error generating balance breakdown PDF: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to generate PDF'
            }), 500
    
    return cash_bank_bp
