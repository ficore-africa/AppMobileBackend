"""
Atomic Entry Creation Endpoints with Payment Integration
Handles Income & Expense creation with atomic FC deduction
Either BOTH entry creation AND FC deduction succeed, or NEITHER happens
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId
from utils.payment_utils import normalize_payment_method, validate_payment_method
from utils.monthly_entry_tracker import MonthlyEntryTracker
import traceback

def init_atomic_entries_blueprint(mongo, token_required, serialize_doc):
    """Initialize the atomic entries blueprint with database and auth decorator"""
    from utils.analytics_tracker import create_tracker
    
    atomic_entries_bp = Blueprint('atomic_entries', __name__, url_prefix='/atomic')
    atomic_entries_bp.mongo = mongo
    atomic_entries_bp.token_required = token_required
    atomic_entries_bp.serialize_doc = serialize_doc
    atomic_entries_bp.tracker = create_tracker(mongo.db)
    
    return atomic_entries_bp

# Initialize blueprint (will be called from app.py)
atomic_entries_bp = Blueprint('atomic_entries', __name__, url_prefix='/atomic')

@atomic_entries_bp.route('/expenses/create-with-payment', methods=['POST'])
def create_expense_with_payment():
    """
    Atomic transaction: Create expense + deduct FC (if required)
    Either BOTH succeed or NEITHER happens
    
    Request Body:
    {
        "amount": float (required),
        "description": string (required),
        "category": string (required),
        "date": ISO datetime string (optional),
        "budgetId": string (optional),
        "tags": array (optional),
        "paymentMethod": string (optional),
        "location": string (optional),
        "notes": string (optional)
    }
    
    Response:
    {
        "success": true/false,
        "data": {
            "expense": {...},
            "fc_charge_amount": float,
            "fc_balance": float,
            "monthly_entries": {
                "count": int,
                "limit": int/null,
                "remaining": int/null
            }
        },
        "message": string
    }
    """
    @atomic_entries_bp.token_required
    def _create_expense_with_payment(current_user):
        # Start tracking for rollback
        expense_id = None
        fc_transaction_id = None
        fc_deducted = False
        
        try:
            # STEP 1: Validate request data
            data = request.get_json()
            errors = {}
            
            if not data.get('amount') or data.get('amount', 0) <= 0:
                errors['amount'] = ['Valid amount is required']
            if not data.get('description'):
                errors['description'] = ['Description is required']
            if not data.get('category'):
                errors['category'] = ['Category is required']
            
            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400
            
            # Validate payment method
            raw_payment = data.get('paymentMethod')
            normalized_payment = normalize_payment_method(raw_payment) if raw_payment is not None else 'cash'
            if raw_payment is not None and not validate_payment_method(raw_payment):
                return jsonify({
                    'success': False,
                    'message': 'Invalid payment method',
                    'errors': {'paymentMethod': ['Unrecognized payment method']}
                }), 400
            
            # STEP 2: Check user status (Premium/Admin/Free)
            user = atomic_entries_bp.mongo.db.users.find_one({'_id': current_user['_id']})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            is_admin = user.get('isAdmin', False)
            is_subscribed = user.get('isSubscribed', False)
            subscription_end = user.get('subscriptionEndDate')
            is_premium = is_admin or (is_subscribed and subscription_end and subscription_end > datetime.utcnow())
            
            # STEP 3: Get monthly entry status
            entry_tracker = MonthlyEntryTracker(atomic_entries_bp.mongo)
            monthly_data = entry_tracker.get_monthly_stats(current_user['_id'])
            
            # STEP 4: Determine if FC charge is required
            fc_cost = 0.0
            fc_charge_required = False
            
            if is_premium:
                # Premium/Admin users: No charge, unlimited entries
                fc_charge_required = False
                fc_cost = 0.0
                charge_reason = f"{'Admin' if is_admin else 'Premium'} subscription active - unlimited entries"
                
            elif monthly_data['remaining'] > 0:
                # Free user within limit: No charge
                fc_charge_required = False
                fc_cost = 0.0
                charge_reason = f"Free entry ({monthly_data['remaining']} remaining this month)"
                
            else:
                # Free user over limit: Charge required
                fc_charge_required = True
                fc_cost = 1.0
                charge_reason = f"Monthly limit exceeded ({monthly_data['count']}/{monthly_data['limit']})"
                
                # Check if user has sufficient FC balance
                current_fc_balance = user.get('ficoreCreditBalance', 0.0)
                if current_fc_balance < fc_cost:
                    return jsonify({
                        'success': False,
                        'message': f'Insufficient FiCore Credits. Need {fc_cost} FC, have {current_fc_balance} FC.',
                        'error_type': 'insufficient_credits',
                        'data': {
                            'fc_required': fc_cost,
                            'fc_balance': current_fc_balance,
                            'monthly_entries': {
                                'count': monthly_data['count'],
                                'limit': monthly_data['limit'],
                                'remaining': 0
                            }
                        }
                    }), 402  # Payment Required
            
            # STEP 5: Create expense document
            expense_data = {
                'userId': current_user['_id'],
                'amount': float(data['amount']),
                'description': data['description'],
                'category': data['category'],
                'date': datetime.fromisoformat(data.get('date', datetime.utcnow().isoformat()).replace('Z', '')),
                'budgetId': data.get('budgetId'),
                'tags': data.get('tags', []),
                'paymentMethod': normalized_payment,
                'location': data.get('location', ''),
                'notes': data.get('notes', ''),
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
                # Track FC charge status
                'fcChargeRequired': fc_charge_required,
                'fcChargeCompleted': False,  # Will be set to True after successful deduction
                'fcChargeAmount': fc_cost,
                'fcChargeAttemptedAt': None
            }
            
            # STEP 6: Insert expense into database
            result = atomic_entries_bp.mongo.db.expenses.insert_one(expense_data)
            expense_id = str(result.inserted_id)
            
            print(f"✓ Expense created: {expense_id}")
            
            # STEP 7: Deduct FC if required (ATOMIC OPERATION)
            new_fc_balance = user.get('ficoreCreditBalance', 0.0)
            
            if fc_charge_required:
                try:
                    # Mark FC charge as attempted
                    atomic_entries_bp.mongo.db.expenses.update_one(
                        {'_id': result.inserted_id},
                        {'$set': {'fcChargeAttemptedAt': datetime.utcnow()}}
                    )
                    
                    # Get current balance again (double-check for race conditions)
                    user = atomic_entries_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                    current_fc_balance = user.get('ficoreCreditBalance', 0.0)
                    
                    if current_fc_balance < fc_cost:
                        # Balance changed between check and deduction - ROLLBACK
                        raise Exception(f'Insufficient credits. Balance changed to {current_fc_balance} FC.')
                    
                    # Deduct FC from user balance
                    new_fc_balance = current_fc_balance - fc_cost
                    
                    atomic_entries_bp.mongo.db.users.update_one(
                        {'_id': current_user['_id']},
                        {'$set': {'ficoreCreditBalance': new_fc_balance}}
                    )
                    
                    print(f"✓ FC deducted: {fc_cost} FC (Balance: {current_fc_balance} → {new_fc_balance})")
                    
                    # Create FC transaction record
                    fc_transaction = {
                        '_id': ObjectId(),
                        'userId': current_user['_id'],
                        'type': 'debit',
                        'amount': fc_cost,
                        'description': f'Expense entry over monthly limit (entry #{monthly_data["count"] + 1})',
                        'operation': 'create_expense_atomic',
                        'balanceBefore': current_fc_balance,
                        'balanceAfter': new_fc_balance,
                        'status': 'completed',
                        'createdAt': datetime.utcnow(),
                        'metadata': {
                            'expense_id': expense_id,
                            'operation': 'create_expense_atomic',
                            'deductionType': 'monthly_limit_exceeded',
                            'monthly_data': {
                                'count': monthly_data['count'],
                                'limit': monthly_data['limit'],
                                'remaining': 0
                            }
                        }
                    }
                    
                    atomic_entries_bp.mongo.db.credit_transactions.insert_one(fc_transaction)
                    fc_transaction_id = str(fc_transaction['_id'])
                    fc_deducted = True
                    
                    print(f"✓ FC transaction recorded: {fc_transaction_id}")
                    
                    # Mark FC charge as completed
                    atomic_entries_bp.mongo.db.expenses.update_one(
                        {'_id': result.inserted_id},
                        {'$set': {'fcChargeCompleted': True}}
                    )
                    
                except Exception as fc_error:
                    # FC deduction failed - ROLLBACK expense creation
                    print(f"✗ FC deduction failed: {str(fc_error)}")
                    print(f"✗ Rolling back expense: {expense_id}")
                    
                    # Delete the expense
                    atomic_entries_bp.mongo.db.expenses.delete_one({'_id': result.inserted_id})
                    
                    # Return error
                    return jsonify({
                        'success': False,
                        'message': f'Failed to process FiCore Credits: {str(fc_error)}',
                        'error_type': 'fc_deduction_failed',
                        'data': {
                            'fc_required': fc_cost,
                            'fc_balance': current_fc_balance
                        }
                    }), 500
            
            # STEP 8: Track analytics (best effort, non-blocking)
            try:
                atomic_entries_bp.tracker.track_expense_created(
                    user_id=current_user['_id'],
                    amount=float(data['amount']),
                    category=data['category']
                )
            except Exception as analytics_error:
                print(f"Analytics tracking failed (non-critical): {analytics_error}")
            
            # STEP 9: Prepare response
            created_expense = atomic_entries_bp.serialize_doc(expense_data.copy())
            created_expense['id'] = expense_id
            created_expense['title'] = created_expense.get('description', 'Expense')
            created_expense['date'] = created_expense.get('date', datetime.utcnow()).isoformat() + 'Z'
            created_expense['createdAt'] = created_expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            created_expense['updatedAt'] = created_expense.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            
            # Remove internal FC tracking fields from response
            created_expense.pop('fcChargeRequired', None)
            created_expense.pop('fcChargeCompleted', None)
            created_expense.pop('fcChargeAmount', None)
            created_expense.pop('fcChargeAttemptedAt', None)
            
            # Build success message
            if is_premium:
                message = f"Expense created successfully ({'Admin' if is_admin else 'Premium'} - unlimited entries)"
            elif fc_charge_required:
                message = f"Expense created successfully. {fc_cost} FC charged. New balance: {new_fc_balance} FC."
            else:
                message = f"Expense created successfully. {monthly_data['remaining'] - 1} free entries remaining this month."
            
            return jsonify({
                'success': True,
                'data': {
                    'expense': created_expense,
                    'fc_charge_amount': fc_cost,
                    'fc_balance': new_fc_balance if not is_premium else None,
                    'monthly_entries': {
                        'count': monthly_data['count'] + 1,
                        'limit': monthly_data['limit'] if not is_premium else None,
                        'remaining': max(0, monthly_data['remaining'] - 1) if not is_premium else None
                    }
                },
                'message': message
            }), 201
            
        except Exception as e:
            # Unexpected error - attempt rollback
            print(f"✗ Unexpected error in create_expense_with_payment: {str(e)}")
            traceback.print_exc()
            
            # Rollback expense if created
            if expense_id:
                try:
                    atomic_entries_bp.mongo.db.expenses.delete_one({'_id': ObjectId(expense_id)})
                    print(f"✓ Rolled back expense: {expense_id}")
                except Exception as rollback_error:
                    print(f"✗ Failed to rollback expense: {rollback_error}")
            
            # Rollback FC deduction if completed
            if fc_deducted and fc_transaction_id:
                try:
                    # Restore FC balance
                    user = atomic_entries_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                    current_balance = user.get('ficoreCreditBalance', 0.0)
                    restored_balance = current_balance + fc_cost
                    
                    atomic_entries_bp.mongo.db.users.update_one(
                        {'_id': current_user['_id']},
                        {'$set': {'ficoreCreditBalance': restored_balance}}
                    )
                    
                    # Mark transaction as reversed
                    atomic_entries_bp.mongo.db.credit_transactions.update_one(
                        {'_id': ObjectId(fc_transaction_id)},
                        {'$set': {'status': 'reversed', 'reversedAt': datetime.utcnow()}}
                    )
                    
                    print(f"✓ Rolled back FC deduction: {fc_cost} FC restored")
                except Exception as rollback_error:
                    print(f"✗ Failed to rollback FC deduction: {rollback_error}")
            
            return jsonify({
                'success': False,
                'message': f'An unexpected error occurred: {str(e)}',
                'error_type': 'server_error',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _create_expense_with_payment()


@atomic_entries_bp.route('/income/create-with-payment', methods=['POST'])
def create_income_with_payment():
    """
    Atomic transaction: Create income + deduct FC (if required)
    Either BOTH succeed or NEITHER happens
    
    Request Body:
    {
        "amount": float (required),
        "source": string (required),
        "description": string (optional),
        "frequency": string (optional),
        "category": string (required),
        "dateReceived": ISO datetime string (optional),
        "isRecurring": bool (optional),
        "nextRecurringDate": ISO datetime string (optional),
        "metadata": object (optional)
    }
    
    Response:
    {
        "success": true/false,
        "data": {
            "income": {...},
            "fc_charge_amount": float,
            "fc_balance": float,
            "monthly_entries": {
                "count": int,
                "limit": int/null,
                "remaining": int/null
            }
        },
        "message": string
    }
    """
    @atomic_entries_bp.token_required
    def _create_income_with_payment(current_user):
        # Start tracking for rollback
        income_id = None
        fc_transaction_id = None
        fc_deducted = False
        
        try:
            # STEP 1: Validate request data
            data = request.get_json()
            errors = {}
            
            if not data.get('amount') or data.get('amount', 0) <= 0:
                errors['amount'] = ['Valid amount is required']
            if not data.get('source'):
                errors['source'] = ['Income source is required']
            if not data.get('category'):
                errors['category'] = ['Category is required']
            
            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400
            
            # STEP 2: Check user status (Premium/Admin/Free)
            user = atomic_entries_bp.mongo.db.users.find_one({'_id': current_user['_id']})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            is_admin = user.get('isAdmin', False)
            is_subscribed = user.get('isSubscribed', False)
            subscription_end = user.get('subscriptionEndDate')
            is_premium = is_admin or (is_subscribed and subscription_end and subscription_end > datetime.utcnow())
            
            # STEP 3: Get monthly entry status
            entry_tracker = MonthlyEntryTracker(atomic_entries_bp.mongo)
            monthly_data = entry_tracker.get_monthly_stats(current_user['_id'])
            
            # STEP 4: Determine if FC charge is required
            fc_cost = 0.0
            fc_charge_required = False
            
            if is_premium:
                # Premium/Admin users: No charge, unlimited entries
                fc_charge_required = False
                fc_cost = 0.0
                charge_reason = f"{'Admin' if is_admin else 'Premium'} subscription active - unlimited entries"
                
            elif monthly_data['remaining'] > 0:
                # Free user within limit: No charge
                fc_charge_required = False
                fc_cost = 0.0
                charge_reason = f"Free entry ({monthly_data['remaining']} remaining this month)"
                
            else:
                # Free user over limit: Charge required
                fc_charge_required = True
                fc_cost = 1.0
                charge_reason = f"Monthly limit exceeded ({monthly_data['count']}/{monthly_data['limit']})"
                
                # Check if user has sufficient FC balance
                current_fc_balance = user.get('ficoreCreditBalance', 0.0)
                if current_fc_balance < fc_cost:
                    return jsonify({
                        'success': False,
                        'message': f'Insufficient FiCore Credits. Need {fc_cost} FC, have {current_fc_balance} FC.',
                        'error_type': 'insufficient_credits',
                        'data': {
                            'fc_required': fc_cost,
                            'fc_balance': current_fc_balance,
                            'monthly_entries': {
                                'count': monthly_data['count'],
                                'limit': monthly_data['limit'],
                                'remaining': 0
                            }
                        }
                    }), 402  # Payment Required
            
            # STEP 5: Create income document
            income_data = {
                'userId': current_user['_id'],
                'amount': float(data['amount']),
                'source': data['source'],
                'description': data.get('description', ''),
                'frequency': data.get('frequency', 'one_time'),
                'category': data['category'],
                'dateReceived': datetime.fromisoformat(data.get('dateReceived', datetime.utcnow().isoformat()).replace('Z', '')),
                'isRecurring': data.get('isRecurring', False),
                'nextRecurringDate': datetime.fromisoformat(data['nextRecurringDate'].replace('Z', '')) if data.get('nextRecurringDate') else None,
                'metadata': data.get('metadata', {}),
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
                # Track FC charge status
                'fcChargeRequired': fc_charge_required,
                'fcChargeCompleted': False,  # Will be set to True after successful deduction
                'fcChargeAmount': fc_cost,
                'fcChargeAttemptedAt': None
            }
            
            # STEP 6: Insert income into database
            result = atomic_entries_bp.mongo.db.incomes.insert_one(income_data)
            income_id = str(result.inserted_id)
            
            print(f"✓ Income created: {income_id}")
            
            # STEP 7: Deduct FC if required (ATOMIC OPERATION)
            new_fc_balance = user.get('ficoreCreditBalance', 0.0)
            
            if fc_charge_required:
                try:
                    # Mark FC charge as attempted
                    atomic_entries_bp.mongo.db.incomes.update_one(
                        {'_id': result.inserted_id},
                        {'$set': {'fcChargeAttemptedAt': datetime.utcnow()}}
                    )
                    
                    # Get current balance again (double-check for race conditions)
                    user = atomic_entries_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                    current_fc_balance = user.get('ficoreCreditBalance', 0.0)
                    
                    if current_fc_balance < fc_cost:
                        # Balance changed between check and deduction - ROLLBACK
                        raise Exception(f'Insufficient credits. Balance changed to {current_fc_balance} FC.')
                    
                    # Deduct FC from user balance
                    new_fc_balance = current_fc_balance - fc_cost
                    
                    atomic_entries_bp.mongo.db.users.update_one(
                        {'_id': current_user['_id']},
                        {'$set': {'ficoreCreditBalance': new_fc_balance}}
                    )
                    
                    print(f"✓ FC deducted: {fc_cost} FC (Balance: {current_fc_balance} → {new_fc_balance})")
                    
                    # Create FC transaction record
                    fc_transaction = {
                        '_id': ObjectId(),
                        'userId': current_user['_id'],
                        'type': 'debit',
                        'amount': fc_cost,
                        'description': f'Income entry over monthly limit (entry #{monthly_data["count"] + 1})',
                        'operation': 'create_income_atomic',
                        'balanceBefore': current_fc_balance,
                        'balanceAfter': new_fc_balance,
                        'status': 'completed',
                        'createdAt': datetime.utcnow(),
                        'metadata': {
                            'income_id': income_id,
                            'operation': 'create_income_atomic',
                            'deductionType': 'monthly_limit_exceeded',
                            'monthly_data': {
                                'count': monthly_data['count'],
                                'limit': monthly_data['limit'],
                                'remaining': 0
                            }
                        }
                    }
                    
                    atomic_entries_bp.mongo.db.credit_transactions.insert_one(fc_transaction)
                    fc_transaction_id = str(fc_transaction['_id'])
                    fc_deducted = True
                    
                    print(f"✓ FC transaction recorded: {fc_transaction_id}")
                    
                    # Mark FC charge as completed
                    atomic_entries_bp.mongo.db.incomes.update_one(
                        {'_id': result.inserted_id},
                        {'$set': {'fcChargeCompleted': True}}
                    )
                    
                except Exception as fc_error:
                    # FC deduction failed - ROLLBACK income creation
                    print(f"✗ FC deduction failed: {str(fc_error)}")
                    print(f"✗ Rolling back income: {income_id}")
                    
                    # Delete the income
                    atomic_entries_bp.mongo.db.incomes.delete_one({'_id': result.inserted_id})
                    
                    # Return error
                    return jsonify({
                        'success': False,
                        'message': f'Failed to process FiCore Credits: {str(fc_error)}',
                        'error_type': 'fc_deduction_failed',
                        'data': {
                            'fc_required': fc_cost,
                            'fc_balance': current_fc_balance
                        }
                    }), 500
            
            # STEP 8: Track analytics (best effort, non-blocking)
            try:
                atomic_entries_bp.tracker.track_income_created(
                    user_id=current_user['_id'],
                    amount=float(data['amount']),
                    source=data['source']
                )
            except Exception as analytics_error:
                print(f"Analytics tracking failed (non-critical): {analytics_error}")
            
            # STEP 9: Prepare response
            created_income = atomic_entries_bp.serialize_doc(income_data.copy())
            created_income['id'] = income_id
            created_income['dateReceived'] = created_income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
            created_income['createdAt'] = created_income.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            created_income['updatedAt'] = created_income.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            if created_income.get('nextRecurringDate'):
                created_income['nextRecurringDate'] = created_income['nextRecurringDate'].isoformat() + 'Z'
            
            # Remove internal FC tracking fields from response
            created_income.pop('fcChargeRequired', None)
            created_income.pop('fcChargeCompleted', None)
            created_income.pop('fcChargeAmount', None)
            created_income.pop('fcChargeAttemptedAt', None)
            
            # Build success message
            if is_premium:
                message = f"Income created successfully ({'Admin' if is_admin else 'Premium'} - unlimited entries)"
            elif fc_charge_required:
                message = f"Income created successfully. {fc_cost} FC charged. New balance: {new_fc_balance} FC."
            else:
                message = f"Income created successfully. {monthly_data['remaining'] - 1} free entries remaining this month."
            
            return jsonify({
                'success': True,
                'data': {
                    'income': created_income,
                    'fc_charge_amount': fc_cost,
                    'fc_balance': new_fc_balance if not is_premium else None,
                    'monthly_entries': {
                        'count': monthly_data['count'] + 1,
                        'limit': monthly_data['limit'] if not is_premium else None,
                        'remaining': max(0, monthly_data['remaining'] - 1) if not is_premium else None
                    }
                },
                'message': message
            }), 201
            
        except Exception as e:
            # Unexpected error - attempt rollback
            print(f"✗ Unexpected error in create_income_with_payment: {str(e)}")
            traceback.print_exc()
            
            # Rollback income if created
            if income_id:
                try:
                    atomic_entries_bp.mongo.db.incomes.delete_one({'_id': ObjectId(income_id)})
                    print(f"✓ Rolled back income: {income_id}")
                except Exception as rollback_error:
                    print(f"✗ Failed to rollback income: {rollback_error}")
            
            # Rollback FC deduction if completed
            if fc_deducted and fc_transaction_id:
                try:
                    # Restore FC balance
                    user = atomic_entries_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                    current_balance = user.get('ficoreCreditBalance', 0.0)
                    restored_balance = current_balance + fc_cost
                    
                    atomic_entries_bp.mongo.db.users.update_one(
                        {'_id': current_user['_id']},
                        {'$set': {'ficoreCreditBalance': restored_balance}}
                    )
                    
                    # Mark transaction as reversed
                    atomic_entries_bp.mongo.db.credit_transactions.update_one(
                        {'_id': ObjectId(fc_transaction_id)},
                        {'$set': {'status': 'reversed', 'reversedAt': datetime.utcnow()}}
                    )
                    
                    print(f"✓ Rolled back FC deduction: {fc_cost} FC restored")
                except Exception as rollback_error:
                    print(f"✗ Failed to rollback FC deduction: {rollback_error}")
            
            return jsonify({
                'success': False,
                'message': f'An unexpected error occurred: {str(e)}',
                'error_type': 'server_error',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _create_income_with_payment()
