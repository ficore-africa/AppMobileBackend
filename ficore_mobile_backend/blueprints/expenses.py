from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
from utils.payment_utils import normalize_payment_method, validate_payment_method
from utils.monthly_entry_tracker import MonthlyEntryTracker

expenses_bp = Blueprint('expenses', __name__, url_prefix='/expenses')

def init_expenses_blueprint(mongo, token_required, serialize_doc):
    """Initialize the expenses blueprint with database and auth decorator"""
    from utils.analytics_tracker import create_tracker
    expenses_bp.mongo = mongo
    expenses_bp.token_required = token_required
    expenses_bp.serialize_doc = serialize_doc
    expenses_bp.tracker = create_tracker(mongo.db)
    return expenses_bp

@expenses_bp.route('', methods=['GET'])
def get_expenses():
    @expenses_bp.token_required
    def _get_expenses(current_user):
        try:
            # IMMUTABLE: Only include active, non-deleted records
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            limit = min(int(request.args.get('limit', 50)), 100)
            offset = max(int(request.args.get('offset', 0)), 0)
            category = request.args.get('category')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            sort_by = request.args.get('sort_by', 'createdAt')  # CRITICAL FIX: Default to createdAt for consistent "just now" timestamps
            sort_order = request.args.get('sort_order', 'desc')
           
            query = get_active_transactions_query(current_user['_id'])  # IMMUTABLE: Filters out voided/deleted
            
            if category:
                query['category'] = category
            if start_date or end_date:
                date_query = {}
                if start_date:
                    date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    date_query['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))
                query['date'] = date_query
           
            sort_direction = -1 if sort_order == 'desc' else 1
            sort_field = sort_by if sort_by in ['date', 'amount', 'category', 'createdAt'] else 'date'
           
            expenses = list(expenses_bp.mongo.db.expenses.find(query)
                           .sort(sort_field, sort_direction)
                           .skip(offset).limit(limit))
            total = expenses_bp.mongo.db.expenses.count_documents(query)
           
            expense_list = []
            for expense in expenses:
                expense_data = expenses_bp.serialize_doc(expense.copy())
                # Keep auto-generated title, don't override with description
                if not expense_data.get('title'):
                    expense_data['title'] = expense_data.get('description', 'Expense')
                expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
                expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                expense_data['updatedAt'] = expense_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if expense_data.get('updatedAt') else None
                # ENTRY TAGGING FIELDS: Format tagging fields for frontend
                expense_data['taggedAt'] = expense_data.get('taggedAt').isoformat() + 'Z' if expense_data.get('taggedAt') else None
                expense_list.append(expense_data)
           
            has_more = offset + limit < total
           
            return jsonify({
                'success': True,
                'data': {
                    'expenses': expense_list,
                    'pagination': {
                        'total': total,
                        'limit': limit,
                        'offset': offset,
                        'hasMore': has_more,
                        'page': (offset // limit) + 1,
                        'pages': (total + limit - 1) // limit
                    }
                },
                'message': 'Expenses retrieved successfully'
            })
           
        except Exception as e:
            print(f"Error in get_expenses: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expenses',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expenses()

@expenses_bp.route('/<expense_id>', methods=['GET'])
def get_expense(expense_id):
    @expenses_bp.token_required
    def _get_expense(current_user):
        try:
            # CRITICAL FIX: Handle optimistic/temp IDs from frontend
            # These IDs start with 'optimistic_' or 'temp_' and are not yet in the database
            if expense_id.startswith('optimistic_') or expense_id.startswith('temp_') or expense_id.startswith('local_'):
                return jsonify({
                    'success': False,
                    'message': 'Expense record is pending sync',
                    'error_type': 'pending_sync'
                }), 202  # 202 Accepted - processing in background
            
            # CRITICAL FIX (Feb 10, 2026): Strip frontend ID prefix before ObjectId conversion
            # Frontend sends: expense_<mongoId>, backend needs: <mongoId>
            # Golden Rule #46: ID Format Consistency
            clean_id = expense_id.replace('expense_', '').replace('income_', '')
            
            expense = expenses_bp.mongo.db.expenses.find_one({
                '_id': ObjectId(clean_id),
                'userId': current_user['_id']
            })
           
            if not expense:
                return jsonify({'success': False, 'message': 'Expense not found'}), 404
           
            expense_data = expenses_bp.serialize_doc(expense.copy())
            expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            expense_data['updatedAt'] = expense_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if expense_data.get('updatedAt') else None
            expense_data['taggedAt'] = expense_data.get('taggedAt').isoformat() + 'Z' if expense_data.get('taggedAt') else None
           
            return jsonify({
                'success': True,
                'data': expense_data,
                'message': 'Expense retrieved successfully'
            })
           
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expense()

@expenses_bp.route('', methods=['POST'])
def create_expense():
    @expenses_bp.token_required
    def _create_expense(current_user):
        try:
            print(f"\n{'='*80}")
            print(f"CREATING EXPENSE - DEBUG LOG")
            print(f"{'='*80}")
            
            data = request.get_json()
            print(f"Request data: {data}")
            print(f"User ID: {current_user['_id']}")
            print(f"User Email: {current_user.get('email', 'N/A')}")
            
            errors = {}
            if not data.get('amount') or data.get('amount', 0) <= 0:
                errors['amount'] = ['Valid amount is required']
            if not data.get('description'):
                errors['description'] = ['Description is required']
            if not data.get('category'):
                errors['category'] = ['Category is required']
           
            if errors:
                print(f"❌ Validation errors: {errors}")
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400
           
            # NEW: Check monthly entry limit for free tier users
            entry_tracker = MonthlyEntryTracker(expenses_bp.mongo)
            fc_check = entry_tracker.should_deduct_fc(current_user['_id'], 'expense')
            print(f"FC check result: {fc_check}")
            
            # If FC deduction is required, check user has sufficient credits
            if fc_check['deduct_fc']:
                user = expenses_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                current_balance = user.get('ficoreCreditBalance', 0.0)
                print(f"FC deduction required. Current balance: {current_balance}, Required: {fc_check['fc_cost']}")
                
                if current_balance < fc_check['fc_cost']:
                    print(f"❌ Insufficient credits!")
                    return jsonify({
                        'success': False,
                        'message': f'Insufficient credits. {fc_check["reason"]}',
                        'data': {
                            'required_credits': fc_check['fc_cost'],
                            'current_balance': current_balance,
                            'monthly_data': fc_check['monthly_data']
                        }
                    }), 402  # Payment Required
           
            raw_payment = data.get('paymentMethod')
            normalized_payment = normalize_payment_method(raw_payment) if raw_payment is not None else 'cash'
            if raw_payment is not None and not validate_payment_method(raw_payment):
                print(f"❌ Invalid payment method: {raw_payment}")
                return jsonify({
                    'success': False,
                    'message': 'Invalid payment method',
                    'errors': {'paymentMethod': ['Unrecognized payment method']}
                }), 400

            # Import auto-population utility
            from utils.expense_utils import auto_populate_expense_fields
            
            # QUICK TAG INTEGRATION (Feb 6, 2026): Accept entryType from frontend
            entry_type = data.get('entryType')  # 'business', 'personal', or None
            print(f"Entry type: {entry_type}")
            
            # ✅ CRITICAL FIX: Mark if entry was created during premium period
            # This prevents premium entries from counting against free tier limit after subscription expires
            user = expenses_bp.mongo.db.users.find_one({'_id': current_user['_id']})
            is_premium_entry = False
            if user:
                is_admin = user.get('isAdmin', False)
                is_subscribed = user.get('isSubscribed', False)
                subscription_end = user.get('subscriptionEndDate')
                # Entry is premium if user is admin OR has active subscription
                if is_admin or (is_subscribed and subscription_end and subscription_end > datetime.utcnow()):
                    is_premium_entry = True
            
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
                'status': 'active',  # CRITICAL: Required for immutability system
                'isDeleted': False,  # CRITICAL: Required for immutability system
                'entryType': entry_type,  # QUICK TAG: Save tag during creation
                'taggedAt': datetime.utcnow() if entry_type else None,  # QUICK TAG: Timestamp
                'taggedBy': 'user' if entry_type else None,  # QUICK TAG: Tagged by user
                'wasPremiumEntry': is_premium_entry,  # ✅ NEW: Track if created during premium period
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            # Auto-populate title and description if missing
            expense_data = auto_populate_expense_fields(expense_data)
            print(f"Expense data prepared: amount=₦{expense_data['amount']}, category={expense_data['category']}")
           
            result = expenses_bp.mongo.db.expenses.insert_one(expense_data)
            expense_id = str(result.inserted_id)
            print(f"✅ Expense created with ID: {expense_id}")
            
            # CRITICAL VERIFICATION: Check if expense actually exists in database
            verification = expenses_bp.mongo.db.expenses.find_one({'_id': result.inserted_id})
            if not verification:
                print(f"❌ CRITICAL ERROR: Expense {expense_id} was inserted but cannot be found in database!")
                raise Exception("Database insert verification failed - expense not found after insert")
            else:
                print(f"✅ VERIFIED: Expense {expense_id} exists in database with amount ₦{verification.get('amount')}")
            
            # Track expense creation event
            try:
                expenses_bp.tracker.track_expense_created(
                    user_id=current_user['_id'],
                    amount=float(data['amount']),
                    category=data['category']
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            # NEW: Deduct FC if required (over monthly limit)
            if fc_check['deduct_fc']:
                print(f"Deducting {fc_check['fc_cost']} FC credits...")
                # Deduct credits from user account
                user = expenses_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                current_balance = user.get('ficoreCreditBalance', 0.0)
                new_balance = current_balance - fc_check['fc_cost']
                
                expenses_bp.mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'ficoreCreditBalance': new_balance}}
                )
                
                # Create transaction record
                transaction = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'type': 'debit',
                    'amount': fc_check['fc_cost'],
                    'description': f'Expense entry over monthly limit (entry #{fc_check["monthly_data"]["count"] + 1})',
                    'operation': 'create_expense_over_limit',
                    'balanceBefore': current_balance,
                    'balanceAfter': new_balance,
                    'status': 'completed',
                    'createdAt': datetime.utcnow(),
                    'metadata': {
                        'operation': 'create_expense_over_limit',
                        'deductionType': 'monthly_limit_exceeded',
                        'monthly_data': fc_check['monthly_data']
                    }
                }
                
                expenses_bp.mongo.db.credit_transactions.insert_one(transaction)
                print(f"✅ FC credits deducted. New balance: {new_balance}")
           
            # NEW: Check if this is user's first entry and mark onboarding complete
            # This ensures backend state stays in sync with frontend wizard
            try:
                income_count = expenses_bp.mongo.db.incomes.count_documents({'userId': current_user['_id']})
                expense_count = expenses_bp.mongo.db.expenses.count_documents({'userId': current_user['_id']})
                
                if income_count + expense_count == 1:  # This is the first entry
                    expenses_bp.mongo.db.users.update_one(
                        {'_id': current_user['_id']},
                        {
                            '$set': {
                                'hasCompletedOnboarding': True,
                                'onboardingCompletedAt': datetime.utcnow()
                            }
                        }
                    )
                    print(f'✅ First entry created - onboarding marked complete for user {current_user["_id"]}')
            except Exception as e:
                print(f'⚠️ Failed to mark onboarding complete (non-critical): {e}')
            
            # PHASE 4: Create context-aware notification reminder to attach documents
            # This is the "Audit Shield" - persistent reminder that survives app reinstalls
            try:
                from blueprints.notifications import create_user_notification
                from utils.notification_context import get_notification_context
                
                # Determine entry title for notification
                entry_title = expense_data.get('title') or expense_data.get('description', 'Expense')
                entry_amount = float(data['amount'])
                
                # Get context-aware notification content
                notification_context = get_notification_context(
                    user=current_user,
                    entry_data=expense_data,
                    entry_type='expense'
                )
                
                # Create persistent notification with context
                notification_id = create_user_notification(
                    mongo=expenses_bp.mongo,
                    user_id=current_user['_id'],
                    category=notification_context['category'],
                    title=notification_context['title'],
                    body=notification_context['body'],
                    related_id=expense_id,
                    metadata={
                        'entryType': 'expense',
                        'entryTitle': entry_title,
                        'amount': entry_amount,
                        'category': data['category'],
                        'dateCreated': datetime.utcnow().isoformat(),
                        'businessStructure': current_user.get('taxProfile', {}).get('businessStructure'),
                        'entryTag': expense_data.get('entryType')
                    },
                    priority=notification_context['priority']
                )
                
                if notification_id:
                    print(f'📱 Context-aware notification created for expense {expense_id}: {notification_id} (priority: {notification_context["priority"]})')
                else:
                    print(f'⚠️ Failed to create notification for expense {expense_id}')
                    
            except Exception as e:
                # Don't fail the expense creation if notification fails
                print(f'⚠️ Failed to create notification (non-critical): {e}')
           
            created_expense = expenses_bp.serialize_doc(expense_data.copy())
            created_expense['id'] = expense_id
            # Keep auto-generated title, don't override with description
            if not created_expense.get('title'):
                created_expense['title'] = created_expense.get('description', 'Expense')
            created_expense['date'] = created_expense.get('date', datetime.utcnow()).isoformat() + 'Z'
            created_expense['createdAt'] = created_expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            created_expense['updatedAt'] = created_expense.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
           
            return jsonify({
                'success': True,
                'data': created_expense,
                'message': 'Expense created successfully'
            })
           
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ ERROR in create_expense: {str(e)}")
            print(f"❌ Full traceback:\n{error_trace}")
            return jsonify({
                'success': False,
                'message': 'Failed to create expense',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _create_expense()

@expenses_bp.route('/<expense_id>', methods=['PUT'])
def update_expense(expense_id):
    @expenses_bp.token_required
    def _update_expense(current_user):
        """
        IMMUTABLE UPDATE: Supersede + create new version
        
        Instead of overwriting the record, we:
        1. Mark the original as 'superseded'
        2. Create a new version with updated data
        3. Link them together for version history
        """
        try:
            if not ObjectId.is_valid(expense_id):
                return jsonify({'success': False, 'message': 'Invalid expense ID'}), 400
            
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': 'No data provided'}), 400
            
            # Validation
            errors = {}
            if 'amount' in data and (not data.get('amount') or data.get('amount', 0) <= 0):
                errors['amount'] = ['Valid amount is required']
            if 'description' in data and not data.get('description'):
                errors['description'] = ['Description is required']
            if 'category' in data and not data.get('category'):
                errors['category'] = ['Category is required']
            
            if errors:
                return jsonify({'success': False, 'message': 'Validation failed', 'errors': errors}), 400
            
            # Prepare update data
            update_data = {}
            
            updatable_fields = ['amount', 'description', 'category', 'date', 'budgetId', 'tags', 'paymentMethod', 'location', 'notes']
            
            for field in updatable_fields:
                if field in data:
                    if field == 'amount':
                        update_data[field] = float(data[field])
                    elif field == 'date':
                        update_data[field] = datetime.fromisoformat(data[field].replace('Z', ''))
                    elif field == 'paymentMethod':
                        if not validate_payment_method(data[field]):
                            return jsonify({
                                'success': False,
                                'message': 'Invalid payment method',
                                'errors': {'paymentMethod': ['Unrecognized payment method']}
                            }), 400
                        update_data[field] = normalize_payment_method(data[field])
                    else:
                        update_data[field] = data[field]
            
            # Also update title field for consistency
            # Don't automatically override title with description on updates
            # Only set title if it's explicitly provided or missing
            if 'description' in update_data and not update_data.get('title'):
                update_data['title'] = update_data['description']
            
            # Use the immutable ledger helper
            from utils.immutable_ledger_helper import supersede_transaction
            
            result = supersede_transaction(
                db=expenses_bp.mongo.db,
                collection_name='expenses',
                transaction_id=expense_id,
                user_id=current_user['_id'],
                update_data=update_data
            )
            
            if not result['success']:
                return jsonify({
                    'success': False,
                    'message': result['message']
                }), 404
            
            # Serialize the new version for response
            new_version = result['new_version']
            expense_data = expenses_bp.serialize_doc(new_version.copy())
            expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            expense_data['updatedAt'] = expense_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': expense_data,
                'message': result['message'],
                'metadata': {
                    'originalId': result['original_id'],
                    'newId': result['new_id'],
                    'version': new_version.get('version', 1)
                }
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update expense',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _update_expense()

@expenses_bp.route('/<expense_id>', methods=['DELETE'])
def delete_expense(expense_id):
    @expenses_bp.token_required
    def _delete_expense(current_user):
        """
        IMMUTABLE DELETE: Soft delete + reversal entry
        
        Instead of deleting the record, we:
        1. Mark it as 'voided' and 'isDeleted=True'
        2. Create a reversal entry with negative amount
        3. Link them together for audit trail
        
        IDEMPOTENT: Returns success if already deleted (prevents UI rollback)
        """
        try:
            if not ObjectId.is_valid(expense_id):
                return jsonify({'success': False, 'message': 'Invalid expense ID'}), 400
            
            # Use the immutable ledger helper
            from utils.immutable_ledger_helper import soft_delete_transaction
            
            result = soft_delete_transaction(
                db=expenses_bp.mongo.db,
                collection_name='expenses',
                transaction_id=expense_id,
                user_id=current_user['_id']
            )
            
            if not result['success']:
                # CRITICAL FIX: If already deleted, return success (idempotent operation)
                if 'already deleted' in result['message'].lower():
                    return jsonify({
                        'success': True,
                        'message': 'Expense already deleted',
                        'data': {
                            'originalId': expense_id,
                            'alreadyDeleted': True
                        }
                    }), 200  # ✓ Return 200 instead of 404
                
                # Only return 404 for "not found" errors
                return jsonify({
                    'success': False,
                    'message': result['message']
                }), 404
            
            return jsonify({
                'success': True,
                'message': result['message'],
                'data': {
                    'originalId': result['original_id'],
                    'reversalId': result['reversal_id'],
                    'auditTrail': 'Transaction marked as deleted, reversal entry created'
                }
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to delete expense',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _delete_expense()

@expenses_bp.route('/summary', methods=['GET'])
def get_expense_summary():
    @expenses_bp.token_required
    def _get_expense_summary(current_user):
        try:
            # IMMUTABLE: Only include active, non-deleted records
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            now = datetime.utcnow()
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start_of_last_month = (start_of_month - timedelta(days=1)).replace(day=1)
           
            filter_start = datetime.fromisoformat(start_date.replace('Z', '')) if start_date else start_of_month
            filter_end = datetime.fromisoformat(end_date.replace('Z', '')) if end_date else now
           
            base_query = get_active_transactions_query(current_user['_id'])
            all_expenses = list(expenses_bp.mongo.db.expenses.find(base_query))
            
            # CRITICAL DEBUG: Log expense summary calculation
            # DISABLED FOR VAS FOCUS
            # print(f"DEBUG EXPENSE SUMMARY - User: {current_user['_id']}")
            # print(f"DEBUG: Total expenses retrieved: {len(all_expenses)}")
            
            filtered_expenses = [exp for exp in all_expenses if exp.get('date') and filter_start <= exp['date'] <= filter_end]
           
            total_this_month = sum(exp.get('amount', 0) for exp in all_expenses if exp.get('date') and exp['date'] >= start_of_month)
            total_last_month = sum(exp.get('amount', 0) for exp in all_expenses if exp.get('date') and start_of_last_month <= exp['date'] < start_of_month)
            
            # DISABLED FOR VAS FOCUS
            # print(f"DEBUG EXPENSE SUMMARY: This month total: {total_this_month}")
            # print(f"DEBUG EXPENSE SUMMARY: Last month total: {total_last_month}")
           
            category_totals = {}
            for expense in filtered_expenses:
                category = expense.get('category', 'Uncategorized')
                category_totals[category] = category_totals.get(category, 0) + expense['amount']
           
            recent_expenses = sorted(
                [exp for exp in all_expenses if exp.get('date')],  # Filter out expenses without date
                key=lambda x: x['date'], 
                reverse=True
            )[:5]
            recent_expenses_data = []
            for expense in recent_expenses:
                e = expenses_bp.serialize_doc(expense.copy())
                # Keep auto-generated title, don't override with description
                if not e.get('title'):
                    e['title'] = e.get('description', 'Expense')
                e['date'] = e.get('date', datetime.utcnow()).isoformat() + 'Z'
                e['createdAt'] = e.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                e['updatedAt'] = e.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                recent_expenses_data.append(e)
           
            summary_data = {
                'totalThisMonth': total_this_month,
                'totalLastMonth': total_last_month,
                'categoryBreakdown': category_totals,
                'recentExpenses': recent_expenses_data,
                'totalExpenses': len(filtered_expenses),
                'averageExpense': sum(exp['amount'] for exp in filtered_expenses) / len(filtered_expenses) if filtered_expenses else 0
            }
           
            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Expense summary retrieved successfully'
            })
           
        except Exception as e:
            print(f"Error in get_expense_summary: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense summary',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expense_summary()

@expenses_bp.route('/categories', methods=['GET'])
def get_expense_categories():
    @expenses_bp.token_required
    def _get_expense_categories(current_user):
        try:
            # IMMUTABLE: Only include active, non-deleted records
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            query = get_active_transactions_query(current_user['_id'])
            
            if start_date or end_date:
                date_query = {}
                if start_date:
                    date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    date_query['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))
                query['date'] = date_query
           
            expenses = list(expenses_bp.mongo.db.expenses.find(query))
            category_totals = {}
            categories = set()
           
            for expense in expenses:
                category = expense.get('category', 'Uncategorized')
                categories.add(category)
                category_totals[category] = category_totals.get(category, 0) + expense.get('amount', 0)
           
            if not categories:
                default_categories = {
                    'Food & Dining', 'Transportation', 'Shopping', 'Entertainment',
                    'Bills & Utilities', 'Healthcare', 'Education', 'Travel',
                    'Personal Care', 'Home & Garden', 'Gifts & Donations',
                    'Office & Admin', 'Staff & Wages', 'Business Transport', 'Rent & Utilities',
                    'Marketing & Sales Expenses', 'Cost of Goods Sold - COGS', 'Personal Expenses',
                    'Statutory & Legal Contributions', 'Other'
                }
                categories = default_categories
                for cat in default_categories:
                    category_totals[cat] = 0.0
           
            return jsonify({
                'success': True,
                'data': category_totals,
                'message': 'Expense categories retrieved successfully'
            })
           
        except Exception as e:
            print(f"Error in get_expense_categories: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense categories',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expense_categories()

# FIXED: Only ONE /statistics endpoint
@expenses_bp.route('/statistics', methods=['GET'])
def get_expense_statistics():
    @expenses_bp.token_required
    def _fetch_statistics(current_user):
        try:
            # IMMUTABLE: Only include active, non-deleted records
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            now = datetime.utcnow()
            filter_start = datetime.fromisoformat(start_date.replace('Z', '')) if start_date else now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            filter_end = datetime.fromisoformat(end_date.replace('Z', '')) if end_date else now
           
            base_query = get_active_transactions_query(current_user['_id'])
            base_query['date'] = {'$gte': filter_start, '$lte': filter_end}
            
            pipeline = [
                {'$match': base_query},
                {'$group': {
                    '_id': None,
                    'totalAmount': {'$sum': '$amount'},
                    'totalCount': {'$sum': 1},
                    'averageAmount': {'$avg': '$amount'},
                    'maxAmount': {'$max': '$amount'},
                    'minAmount': {'$min': '$amount'}
                }}
            ]
           
            result = list(expenses_bp.mongo.db.expenses.aggregate(pipeline))
           
            stats = result[0] if result else {}
            statistics_data = {
                'totalAmount': float(stats.get('totalAmount', 0)),
                'totalCount': int(stats.get('totalCount', 0)),
                'averageAmount': float(stats.get('averageAmount', 0)) if stats.get('averageAmount') else 0,
                'maxAmount': float(stats.get('maxAmount', 0)) if stats.get('maxAmount') else 0,
                'minAmount': float(stats.get('minAmount', 0)) if stats.get('minAmount') else 0,
                'period': {
                    'startDate': filter_start.isoformat() + 'Z',
                    'endDate': filter_end.isoformat() + 'Z'
                }
            }
           
            return jsonify({
                'success': True,
                'data': statistics_data,
                'message': 'Expense statistics retrieved successfully'
            })
           
        except Exception as e:
            print(f"Error in get_expense_statistics: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense statistics',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _fetch_statistics()

@expenses_bp.route('/insights', methods=['GET'])
def get_expense_insights():
    @expenses_bp.token_required
    def _get_expense_insights(current_user):
        try:
            # IMMUTABLE: Only include active, non-deleted records
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            base_query = get_active_transactions_query(current_user['_id'])
            expenses = list(expenses_bp.mongo.db.expenses.find(base_query))
            
            # CRITICAL DEBUG: Log insights calculation
            # DISABLED FOR VAS FOCUS
            # print(f"DEBUG EXPENSE INSIGHTS - User: {current_user['_id']}")
            # print(f"DEBUG: Total expenses retrieved: {len(expenses)}")
            
            if not expenses:
                return jsonify({
                    'success': True,
                    'data': {'insights': [], 'message': 'No expense data available for insights'},
                    'message': 'Expense insights retrieved successfully'
                })
           
            now = datetime.utcnow()
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start_of_last_month = (start_of_month - timedelta(days=1)).replace(day=1)
           
            current_month_expenses = [e for e in expenses if e.get('date') and e['date'] >= start_of_month]
            last_month_expenses = [e for e in expenses if e.get('date') and start_of_last_month <= e['date'] < start_of_month]
           
            current_total = sum(e.get('amount', 0) for e in current_month_expenses)
            last_total = sum(e.get('amount', 0) for e in last_month_expenses)
            
            # DISABLED FOR VAS FOCUS
            # print(f"DEBUG EXPENSE INSIGHTS: This month expenses count: {len(current_month_expenses)}")
            # print(f"DEBUG EXPENSE INSIGHTS: This month total: {current_total}")
            # print(f"DEBUG EXPENSE INSIGHTS: Last month expenses count: {len(last_month_expenses)}")
            # print(f"DEBUG EXPENSE INSIGHTS: Last month total: {last_total}")
           
            insights = []
            # CRITICAL FIX: Consistent calculation with proper severity field
            if last_total > 0:
                change = ((current_total - last_total) / last_total) * 100
                # DISABLED FOR VAS FOCUS
                # print(f"DEBUG EXPENSE INSIGHTS: Calculated change = {change}%")
                
                if change > 15:
                    insights.append({
                        'type': 'increase', 
                        'title': 'Spending Increase', 
                        'message': f'Up {change:.1f}% this month', 
                        'severity': 'warning',  # Added severity
                        'value': change, 
                        'priority': 'high'
                    })
                elif change < -15:
                    insights.append({
                        'type': 'decrease', 
                        'title': 'Spending Down', 
                        'message': f'Down {abs(change):.1f}% – well done!', 
                        'severity': 'success',  # Added severity
                        'value': change, 
                        'priority': 'high'
                    })
            elif current_total > 0 and last_total == 0:
                # Special case: expenses this month but none last month
                insights.append({
                    'type': 'increase',
                    'title': 'Expenses Started',
                    'message': 'You have expenses this month.',
                    'severity': 'info',
                    'value': 100.0,
                    'priority': 'medium'
                })
           
            category_totals = {}
            for e in current_month_expenses:
                cat = e.get('category', 'Other')
                category_totals[cat] = category_totals.get(cat, 0) + e['amount']
           
            if category_totals:
                top_cat, top_amt = max(category_totals.items(), key=lambda x: x[1])
                pct = (top_amt / current_total) * 100 if current_total else 0
                insights.append({
                    'type': 'top_category', 
                    'title': 'Top Category', 
                    'message': f'{top_cat}: {pct:.1f}% of spending', 
                    'severity': 'info',  # Added severity
                    'value': top_amt, 
                    'priority': 'medium'
                })
           
            days = now.day
            avg_daily = current_total / days if days else 0
            insights.append({
                'type': 'daily_average', 
                'title': 'Daily Avg', 
                'message': f'₦{avg_daily:,.0f}/day', 
                'severity': 'info',  # Added severity
                'value': avg_daily, 
                'priority': 'low'
            })
           
            return jsonify({
                'success': True,
                'data': {
                    'insights': insights,
                    'summary': {
                        'current_month_total': current_total,
                        'last_month_total': last_total,
                        'total_categories': len(category_totals),
                        'total_expenses_count': len(current_month_expenses)
                    }
                },
                'message': 'Expense insights retrieved successfully'
            })
           
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense insights',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expense_insights()


# ============================================================================
# ENTRY TAGGING ENDPOINTS (Phase 3B)
# ============================================================================

@expenses_bp.route('/<entry_id>/tag', methods=['PATCH', 'PUT'])
def tag_expense_entry(entry_id):
    @expenses_bp.token_required
    def _tag_expense_entry(current_user):
        """Tag an expense entry as business or personal"""
        try:
            print(f"\n{'='*80}")
            print(f"TAGGING EXPENSE - DEBUG LOG")
            print(f"{'='*80}")
            print(f"Raw entry_id received: {entry_id}")
            print(f"User ID: {current_user['_id']}")
            
            data = request.get_json() or {}
            entry_type = data.get('entryType')
            print(f"Entry type requested: {entry_type}")
            
            # Validate entry type
            if entry_type not in ['business', 'personal', None]:
                print(f"❌ Invalid entry type: {entry_type}")
                return jsonify({
                    'success': False,
                    'message': 'Invalid entry type. Must be "business", "personal", or null'
                }), 400
            
            # CRITICAL FIX (Feb 6, 2026): Strip frontend ID prefix before ObjectId conversion
            # Frontend sends: expense_<mongoId>, backend needs: <mongoId>
            # Golden Rule #46: ID Format Consistency
            clean_id = entry_id.replace('expense_', '').replace('income_', '')
            print(f"Cleaned ID: {clean_id}")
            
            # Check if expense exists first
            expense = expenses_bp.mongo.db.expenses.find_one({
                '_id': ObjectId(clean_id),
                'userId': current_user['_id']
            })
            
            if not expense:
                print(f"❌ Expense not found with _id={clean_id} and userId={current_user['_id']}")
                print(f"Checking if expense exists with different userId...")
                any_expense = expenses_bp.mongo.db.expenses.find_one({'_id': ObjectId(clean_id)})
                if any_expense:
                    print(f"⚠️  Expense exists but belongs to different user: {any_expense.get('userId')}")
                else:
                    print(f"❌ Expense does not exist in database at all")
                return jsonify({
                    'success': False,
                    'message': 'Entry not found'
                }), 404
            
            print(f"✅ Expense found:")
            print(f"   Amount: ₦{expense.get('amount')}")
            print(f"   Category: {expense.get('category')}")
            print(f"   Current entryType: {expense.get('entryType', 'NOT SET')}")
            
            # Update entry
            update_data = {
                'entryType': entry_type,
                'taggedAt': datetime.utcnow() if entry_type else None,
                'taggedBy': 'user' if entry_type else None
            }
            
            print(f"Updating with: {update_data}")
            
            result = expenses_bp.mongo.db.expenses.update_one(
                {'_id': ObjectId(clean_id), 'userId': current_user['_id']},
                {'$set': update_data}
            )
            
            print(f"Update result: matched={result.matched_count}, modified={result.modified_count}")
            
            if result.matched_count > 0:
                # Fetch the updated expense to return to frontend
                updated_expense = expenses_bp.mongo.db.expenses.find_one({
                    '_id': ObjectId(clean_id),
                    'userId': current_user['_id']
                })
                
                if updated_expense:
                    # CRITICAL FIX: Use serialize_doc to properly convert _id → id
                    expense_data = expenses_bp.serialize_doc(updated_expense.copy())
                    
                    # Ensure date fields are properly formatted
                    expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
                    expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                    expense_data['updatedAt'] = expense_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if expense_data.get('updatedAt') else None
                    expense_data['taggedAt'] = expense_data.get('taggedAt').isoformat() + 'Z' if expense_data.get('taggedAt') else None
                    
                    print(f"✅ Entry tagged successfully, returning updated expense")
                    print(f"{'='*80}\n")
                    return jsonify({
                        'success': True,
                        'message': 'Entry tagged successfully',
                        'data': expense_data
                    })
                else:
                    print(f"⚠️  Entry updated but could not fetch updated data")
                    print(f"{'='*80}\n")
                    return jsonify({
                        'success': True,
                        'message': 'Entry tagged successfully'
                    })
            else:
                print(f"⚠️  Entry not found")
                print(f"{'='*80}\n")
                return jsonify({
                    'success': False,
                    'message': 'Entry not found'
                }), 404
                
        except Exception as e:
            print(f"❌ ERROR in tag_expense_entry: {e}")
            print(f"{'='*80}\n")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to tag entry',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _tag_expense_entry()

@expenses_bp.route('/bulk-tag', methods=['PATCH', 'PUT'])
def bulk_tag_expense_entries():
    @expenses_bp.token_required
    def _bulk_tag_expense_entries(current_user):
        """Tag multiple expense entries at once"""
        try:
            data = request.get_json() or {}
            entry_ids = data.get('entryIds', [])
            entry_type = data.get('entryType')
            
            # Validate entry type
            if entry_type not in ['business', 'personal']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid entry type. Must be "business" or "personal"'
                }), 400
            
            if not entry_ids:
                return jsonify({
                    'success': False,
                    'message': 'No entry IDs provided'
                }), 400
            
            # CRITICAL FIX (Feb 6, 2026): Strip frontend ID prefixes before ObjectId conversion
            # Golden Rule #46: ID Format Consistency
            clean_ids = [id.replace('expense_', '').replace('income_', '') for id in entry_ids]
            
            # Update entries
            update_data = {
                'entryType': entry_type,
                'taggedAt': datetime.utcnow(),
                'taggedBy': 'user'
            }
            
            result = expenses_bp.mongo.db.expenses.update_many(
                {
                    '_id': {'$in': [ObjectId(id) for id in clean_ids]},
                    'userId': current_user['_id']
                },
                {'$set': update_data}
            )
            
            return jsonify({
                'success': True,
                'message': f'{result.modified_count} entries tagged successfully',
                'count': result.modified_count
            })
                
        except Exception as e:
            print(f"Error in bulk_tag_expense_entries: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to bulk tag entries',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _bulk_tag_expense_entries()

@expenses_bp.route('/untagged-count', methods=['GET'])
def get_untagged_expense_count():
    @expenses_bp.token_required
    def _get_untagged_expense_count(current_user):
        """Get count of untagged expense entries"""
        try:
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            query = get_active_transactions_query(current_user['_id'])
            query['entryType'] = None
            
            count = expenses_bp.mongo.db.expenses.count_documents(query)
            
            return jsonify({
                'success': True,
                'count': count
            })
                
        except Exception as e:
            print(f"Error in get_untagged_expense_count: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to get untagged count',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_untagged_expense_count()

# ============================================================================
# AUDIT SHIELD: Report Discrepancy & Version Tracking (Feb 7, 2026)
# ============================================================================

@expenses_bp.route('/<expense_id>/discrepancy-check', methods=['GET'])
def check_expense_discrepancy(expense_id):
    @expenses_bp.token_required
    def _check_expense_discrepancy(current_user):
        """
        Check if expense was edited after being exported in a report
        
        GUARDIAN LOGIC: Detects when current version > exported version
        Returns data for "Report Discrepancy" warning in UI
        """
        try:
            if not ObjectId.is_valid(expense_id):
                return jsonify({'success': False, 'message': 'Invalid expense ID'}), 400
            
            # Verify ownership
            expense = expenses_bp.mongo.db.expenses.find_one({
                '_id': ObjectId(expense_id),
                'userId': current_user['_id']
            })
            
            if not expense:
                return jsonify({'success': False, 'message': 'Expense not found'}), 404
            
            # Use helper function
            from utils.immutable_ledger_helper import check_report_discrepancy
            
            result = check_report_discrepancy(
                db=expenses_bp.mongo.db,
                collection_name='expenses',
                transaction_id=expense_id
            )
            
            # Serialize dates
            for export in result.get('affected_exports', []):
                if export.get('exported_at'):
                    export['exported_at'] = export['exported_at'].isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': {
                    'hasDiscrepancy': result['has_discrepancy'],
                    'affectedExports': result['affected_exports'],
                    'currentVersion': result['current_version'],
                    'exportedVersions': result['exported_versions']
                }
            })
            
        except Exception as e:
            print(f"Error in check_expense_discrepancy: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to check discrepancy',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _check_expense_discrepancy()

@expenses_bp.route('/<expense_id>/version-comparison', methods=['GET'])
def get_expense_version_comparison(expense_id):
    @expenses_bp.token_required
    def _get_expense_version_comparison(current_user):
        """
        Get side-by-side comparison of two versions
        
        DIFF VIEW: Shows what changed between exported and current version
        Used in "Version Comparison Modal" in UI
        """
        try:
            version1 = int(request.args.get('version1', 1))
            version2 = int(request.args.get('version2', 2))
            
            if not ObjectId.is_valid(expense_id):
                return jsonify({'success': False, 'message': 'Invalid expense ID'}), 400
            
            # Verify ownership
            expense = expenses_bp.mongo.db.expenses.find_one({
                '_id': ObjectId(expense_id),
                'userId': current_user['_id']
            })
            
            if not expense:
                return jsonify({'success': False, 'message': 'Expense not found'}), 404
            
            # Use helper function
            from utils.immutable_ledger_helper import get_version_comparison
            
            result = get_version_comparison(
                db=expenses_bp.mongo.db,
                collection_name='expenses',
                transaction_id=expense_id,
                version1=version1,
                version2=version2
            )
            
            if not result['success']:
                return jsonify({
                    'success': False,
                    'message': result['message']
                }), 404
            
            # Serialize dates
            if result['version1_data'].get('date'):
                result['version1_data']['date'] = result['version1_data']['date'].isoformat() + 'Z'
            if result['version2_data'].get('date'):
                result['version2_data']['date'] = result['version2_data']['date'].isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': {
                    'version1': result['version1_data'],
                    'version2': result['version2_data'],
                    'changes': result['changes']
                }
            })
            
        except Exception as e:
            print(f"Error in get_expense_version_comparison: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to get version comparison',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_expense_version_comparison()

@expenses_bp.route('/<expense_id>/version-history', methods=['GET'])
def get_expense_version_history(expense_id):
    @expenses_bp.token_required
    def _get_expense_version_history(current_user):
        """
        Get complete version history for an expense entry
        
        TRANSPARENCY: Shows all versions with timestamps and changes
        Used in "Version History Modal" in UI
        """
        try:
            if not ObjectId.is_valid(expense_id):
                return jsonify({'success': False, 'message': 'Invalid expense ID'}), 400
            
            # Verify ownership
            expense = expenses_bp.mongo.db.expenses.find_one({
                '_id': ObjectId(expense_id),
                'userId': current_user['_id']
            })
            
            if not expense:
                return jsonify({'success': False, 'message': 'Expense not found'}), 404
            
            version_log = expense.get('versionLog', [])
            current_version = expense.get('version', 1)
            
            # Serialize dates
            for version in version_log:
                if version.get('createdAt'):
                    version['createdAt'] = version['createdAt'].isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': {
                    'versionLog': version_log,
                    'currentVersion': current_version,
                    'totalVersions': len(version_log) + 1  # +1 for current
                }
            })
            
        except Exception as e:
            print(f"Error in get_expense_version_history: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to get version history',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_expense_version_history()

@expenses_bp.route('/<expense_id>/export-history', methods=['GET'])
def get_expense_export_history(expense_id):
    @expenses_bp.token_required
    def _get_expense_export_history(current_user):
        """
        Get complete export history for an expense entry
        
        TRANSPARENCY: Shows all reports this entry was included in
        Used in "Export History Modal" in UI
        """
        try:
            if not ObjectId.is_valid(expense_id):
                return jsonify({'success': False, 'message': 'Invalid expense ID'}), 400
            
            # Verify ownership
            expense = expenses_bp.mongo.db.expenses.find_one({
                '_id': ObjectId(expense_id),
                'userId': current_user['_id']
            })
            
            if not expense:
                return jsonify({'success': False, 'message': 'Expense not found'}), 404
            
            export_history = expense.get('exportHistory', [])
            
            # Serialize dates
            for export in export_history:
                if export.get('exportedAt'):
                    export['exportedAt'] = export['exportedAt'].isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': {
                    'exportHistory': export_history,
                    'totalExports': len(export_history)
                }
            })
            
        except Exception as e:
            print(f"Error in get_expense_export_history: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to get export history',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_expense_export_history()

@expenses_bp.route('/<expense_id>/rollback/<int:target_version>', methods=['POST'])
def rollback_expense_version(expense_id, target_version):
    @expenses_bp.token_required
    def _rollback_expense_version(current_user):
        """
        Rollback expense entry to a previous version
        
        INSURANCE POLICY: Allows manual restore of accidentally overwritten data
        Creates NEW version with old data (maintains audit trail)
        
        Example: v1 → v2 → v3 → v4 (rollback to v2) = v4 looks like v2
        
        Usage:
        - High-value user accidentally overwrites complex entry
        - Admin can restore via API call or Postman
        - No data is actually deleted, just new version created
        """
        try:
            print(f"\n{'='*80}")
            print(f"ROLLBACK EXPENSE - DEBUG LOG")
            print(f"{'='*80}")
            print(f"Expense ID: {expense_id}")
            print(f"Target version: {target_version}")
            print(f"User ID: {current_user['_id']}")
            
            if not ObjectId.is_valid(expense_id):
                return jsonify({'success': False, 'message': 'Invalid expense ID'}), 400
            
            if target_version < 1:
                return jsonify({'success': False, 'message': 'Invalid target version'}), 400
            
            # Get the expense entry
            expense = expenses_bp.mongo.db.expenses.find_one({
                '_id': ObjectId(expense_id),
                'userId': current_user['_id'],
                'status': 'active'
            })
            
            if not expense:
                print(f"❌ Expense not found")
                return jsonify({'success': False, 'message': 'Expense not found'}), 404
            
            current_version = expense.get('version', 1)
            print(f"Current version: {current_version}")
            
            # Can't rollback to current version
            if target_version == current_version:
                print(f"⚠️ Target version is current version")
                return jsonify({
                    'success': False,
                    'message': f'Entry is already at version {target_version}'
                }), 400
            
            # Can't rollback to future version
            if target_version > current_version:
                print(f"❌ Target version is in the future")
                return jsonify({
                    'success': False,
                    'message': f'Cannot rollback to future version {target_version} (current: {current_version})'
                }), 400
            
            # Find the target version in versionLog
            version_log = expense.get('versionLog', [])
            target_data = None
            
            for version_entry in version_log:
                if version_entry.get('version') == target_version:
                    target_data = version_entry.get('data', {})
                    break
            
            if not target_data:
                print(f"❌ Target version not found in version log")
                return jsonify({
                    'success': False,
                    'message': f'Version {target_version} not found in version history'
                }), 404
            
            print(f"✅ Found target version data:")
            print(f"   Amount: ₦{target_data.get('amount')}")
            print(f"   Title: {target_data.get('title')}")
            
            # Prepare rollback data (restore old values)
            rollback_data = {}
            
            # Restore all fields from target version
            if 'amount' in target_data:
                rollback_data['amount'] = target_data['amount']
            if 'title' in target_data:
                rollback_data['title'] = target_data['title']
            if 'description' in target_data:
                rollback_data['description'] = target_data['description']
            if 'category' in target_data:
                rollback_data['category'] = target_data['category']
            if 'date' in target_data:
                rollback_data['date'] = target_data['date']
            
            print(f"Rollback data prepared: {list(rollback_data.keys())}")
            
            # Use supersede_transaction to create new version with old data
            from utils.immutable_ledger_helper import supersede_transaction
            
            result = supersede_transaction(
                db=expenses_bp.mongo.db,
                collection_name='expenses',
                transaction_id=expense_id,
                user_id=current_user['_id'],
                update_data=rollback_data
            )
            
            if not result['success']:
                print(f"❌ Rollback failed: {result['message']}")
                return jsonify({
                    'success': False,
                    'message': result['message']
                }), 500
            
            # Add rollback metadata to the new version
            new_version_number = result['new_version'].get('version', current_version + 1)
            
            # Update the new version to mark it as a rollback
            expenses_bp.mongo.db.expenses.update_one(
                {'_id': ObjectId(expense_id)},
                {'$set': {
                    'lastRollback': {
                        'rolledBackAt': datetime.utcnow(),
                        'rolledBackBy': current_user['_id'],
                        'fromVersion': current_version,
                        'toVersion': target_version,
                        'newVersion': new_version_number
                    }
                }}
            )
            
            print(f"✅ Rollback successful!")
            print(f"   From version: {current_version}")
            print(f"   To version: {target_version}")
            print(f"   New version: {new_version_number}")
            print(f"{'='*80}\n")
            
            # Serialize the restored version for response
            restored_expense = result['new_version']
            expense_data = expenses_bp.serialize_doc(restored_expense.copy())
            expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            expense_data['updatedAt'] = expense_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'message': f'Expense rolled back to version {target_version}',
                'data': expense_data,
                'metadata': {
                    'fromVersion': current_version,
                    'toVersion': target_version,
                    'newVersion': new_version_number,
                    'rolledBackAt': datetime.utcnow().isoformat() + 'Z'
                }
            })
            
        except Exception as e:
            print(f"❌ ERROR in rollback_expense_version: {e}")
            print(f"{'='*80}\n")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to rollback expense version',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _rollback_expense_version()
