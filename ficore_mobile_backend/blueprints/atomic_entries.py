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
    
    @atomic_entries_bp.route('/expenses/create-with-payment', methods=['POST'])
    @atomic_entries_bp.token_required
    def create_expense_with_payment(current_user):
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
            
            # Import auto-population utility
            from utils.expense_utils import auto_populate_expense_fields
            
            # 🏷️ QUICK TAG INTEGRATION (Feb 21, 2026): Accept entryType from frontend
            entry_type = data.get('entryType')  # 'business', 'personal', or None
            print(f"\n{'🏷️ '*40}")
            print(f"🏷️  ATOMIC ENDPOINT - TAGGING DEBUG")
            print(f"{'🏷️ '*40}")
            print(f"🏷️  Entry type received: {entry_type}")
            print(f"🏷️  Entry type is None: {entry_type is None}")
            print(f"🏷️  Entry type is empty: {entry_type == ''}")
            print(f"🏷️  Entry type type: {type(entry_type)}")
            if entry_type:
                print(f"🏷️  ✅ TAG PROVIDED: '{entry_type}'")
            else:
                print(f"🏷️  ⚠️  NO TAG PROVIDED (will be saved as None)")
            print(f"{'🏷️ '*40}\n")
            
            # Validate entryType if provided
            if entry_type and entry_type not in ['business', 'personal']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid entryType. Must be "business" or "personal"',
                    'errors': {'entryType': ['Invalid value']}
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
            
            # STEP 3: Create expense data
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
                'updatedAt': datetime.utcnow()
            }
            
            # Auto-populate title and description if missing
            expense_data = auto_populate_expense_fields(expense_data)
            
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
            # ✅ CRITICAL FIX: Mark if entry was created during premium period
            is_premium_entry = is_premium  # Already calculated above
            
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
                'entryType': entry_type,  # 🏷️ QUICK TAG: Save tag during creation
                'taggedAt': datetime.utcnow() if entry_type else None,  # 🏷️ QUICK TAG: Timestamp
                'taggedBy': 'user' if entry_type else None,  # 🏷️ QUICK TAG: Tagged by user
                'wasPremiumEntry': is_premium_entry,  # ✅ NEW: Track if created during premium period
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
                # Track FC charge status
                'fcChargeRequired': fc_charge_required,
                'fcChargeCompleted': False,  # Will be set to True after successful deduction
                'fcChargeAmount': fc_cost,
                'fcChargeAttemptedAt': None
            }
            
            # 🏷️  TAGGING DEBUG: Log what will be saved to database
            print(f"\n{'🏷️ '*40}")
            print(f"🏷️  ATOMIC ENDPOINT - DATABASE INSERT")
            print(f"{'🏷️ '*40}")
            print(f"🏷️  entryType field: {expense_data.get('entryType')}")
            print(f"🏷️  taggedAt field: {expense_data.get('taggedAt')}")
            print(f"🏷️  taggedBy field: {expense_data.get('taggedBy')}")
            if expense_data.get('entryType'):
                print(f"🏷️  ✅ WILL SAVE WITH TAG: '{expense_data.get('entryType')}'")
            else:
                print(f"🏷️  ⚠️  WILL SAVE WITHOUT TAG (entryType=None)")
            print(f"{'🏷️ '*40}\n")
            
            # STEP 6: Insert expense into database
            result = atomic_entries_bp.mongo.db.expenses.insert_one(expense_data)
            expense_id = str(result.inserted_id)
            
            print(f"✓ Expense created: {expense_id}")
            
            # 🏷️  TAGGING DEBUG: Verify tag was saved correctly
            verification = atomic_entries_bp.mongo.db.expenses.find_one({'_id': result.inserted_id})
            print(f"\n{'🏷️ '*40}")
            print(f"🏷️  ATOMIC ENDPOINT - POST-INSERT VERIFICATION")
            print(f"{'🏷️ '*40}")
            print(f"🏷️  Expense ID: {expense_id}")
            print(f"🏷️  entryType in DB: {verification.get('entryType')}")
            print(f"🏷️  taggedAt in DB: {verification.get('taggedAt')}")
            print(f"🏷️  taggedBy in DB: {verification.get('taggedBy')}")
            if verification.get('entryType'):
                print(f"🏷️  ✅ TAG SAVED SUCCESSFULLY: '{verification.get('entryType')}'")
            else:
                print(f"🏷️  ⚠️  NO TAG IN DATABASE (entryType=None)")
            print(f"{'🏷️ '*40}\n")
            
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
            
            # STEP 9: Create notification to remind user to attach supporting documents
            notification_data = None  # FIX 3.1: Capture notification for response
            try:
                from blueprints.notifications import create_user_notification
                
                # CRITICAL: Format relatedId as "expense_<id>" for frontend navigation
                formatted_related_id = f'expense_{expense_id}'
                
                notification_id = create_user_notification(
                    mongo=atomic_entries_bp.mongo,
                    user_id=str(current_user['_id']),
                    category='missingReceipt',
                    title='Don\'t forget to attach supporting documents',
                    body=f'You can add receipts or documents to your ₦{data["amount"]:,.2f} expense entry to keep better records.',
                    related_id=formatted_related_id,
                    metadata={
                        'transactionType': 'expense',
                        'amount': float(data['amount']),
                        'category': data['category'],
                        'description': data['description']
                    },
                    priority='normal'
                )
                
                if notification_id:
                    print(f"✓ Notification created: {notification_id} (relatedId: {formatted_related_id})")
                    
                    # FIX 3: Send FCM push notification
                    try:
                        from services.firebase_service import firebase_service
                        
                        # Get user's FCM token
                        user = atomic_entries_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                        fcm_token = user.get('fcmToken')
                        
                        if fcm_token:
                            # Send push notification
                            push_sent = firebase_service.send_push_notification(
                                fcm_token=fcm_token,
                                title='Don\'t forget to attach supporting documents',
                                body=f'You can add receipts or documents to your ₦{data["amount"]:,.2f} expense entry to keep better records.',
                                data={
                                    'notificationId': notification_id,
                                    'category': 'missingReceipt',
                                    'relatedId': formatted_related_id,
                                    'transactionType': 'expense',
                                    'amount': str(data['amount']),
                                    'click_action': 'FLUTTER_NOTIFICATION_CLICK'
                                }
                            )
                            
                            if push_sent:
                                print(f"✓ FCM push sent successfully for notification {notification_id}")
                            else:
                                print(f"⚠ FCM push failed for notification {notification_id} (non-critical)")
                        else:
                            print(f"⚠ No FCM token for user {current_user['email']}, skipping push")
                            
                    except Exception as push_error:
                        print(f"⚠ FCM push failed (non-critical): {push_error}")
                    
                    # FIX 3.1: Prepare notification data for response (eliminates race condition)
                    notification_data = {
                        'id': notification_id,
                        'category': 'missingReceipt',
                        'title': 'Don\'t forget to attach supporting documents',
                        'body': f'You can add receipts or documents to your ₦{data["amount"]:,.2f} expense entry to keep better records.',
                        'relatedId': formatted_related_id,
                        'priority': 'normal',
                        'timestamp': datetime.utcnow().isoformat() + 'Z',
                        'isRead': False,
                        'isArchived': False,
                        'metadata': {
                            'transactionType': 'expense',
                            'amount': float(data['amount']),
                            'category': data['category'],
                            'description': data['description']
                        }
                    }
                else:
                    print(f"⚠ Notification creation returned None (non-critical)")
                    
            except Exception as notification_error:
                print(f"Notification creation failed (non-critical): {notification_error}")
            
            # STEP 10: Prepare response
            created_expense = atomic_entries_bp.serialize_doc(expense_data.copy())
            created_expense['id'] = expense_id
            # Keep auto-generated title, don't override with description
            if not created_expense.get('title'):
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
            
            # FIX 3.1: Include notification in response (eliminates race condition)
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
                    },
                    'notification': notification_data  # FIX 3.1: Include notification in response
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

    @atomic_entries_bp.route('/income/create-with-payment', methods=['POST'])
    @atomic_entries_bp.token_required
    def create_income_with_payment(current_user):
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
            # ✅ CRITICAL FIX: Mark if entry was created during premium period
            is_premium_entry = is_premium  # Already calculated above
            
            # 🏷️ QUICK TAG INTEGRATION (Feb 21, 2026): Accept entryType from frontend
            entry_type = data.get('entryType')  # 'business', 'personal', or None
            print(f"\n{'🏷️ '*40}")
            print(f"🏷️  INCOME ATOMIC ENDPOINT - TAGGING DEBUG")
            print(f"{'🏷️ '*40}")
            print(f"🏷️  Entry type received: {entry_type}")
            if entry_type:
                print(f"🏷️  ✅ TAG PROVIDED: '{entry_type}'")
            else:
                print(f"🏷️  ⚠️  NO TAG PROVIDED (will be saved as None)")
            print(f"{'🏷️ '*40}\n")
            
            # Validate entryType if provided
            if entry_type and entry_type not in ['business', 'personal']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid entryType. Must be "business" or "personal"',
                    'errors': {'entryType': ['Invalid value']}
                }), 400
            
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
                'status': 'active',  # CRITICAL: Required for immutability system
                'isDeleted': False,  # CRITICAL: Required for immutability system
                'entryType': entry_type,  # 🏷️ QUICK TAG: Save tag during creation
                'taggedAt': datetime.utcnow() if entry_type else None,  # 🏷️ QUICK TAG: Timestamp
                'taggedBy': 'user' if entry_type else None,  # 🏷️ QUICK TAG: Tagged by user
                'wasPremiumEntry': is_premium_entry,  # ✅ NEW: Track if created during premium period
                'metadata': data.get('metadata', {}),
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
                # Track FC charge status
                'fcChargeRequired': fc_charge_required,
                'fcChargeCompleted': False,  # Will be set to True after successful deduction
                'fcChargeAmount': fc_cost,
                'fcChargeAttemptedAt': None
            }
            
            # 🏷️  TAGGING DEBUG: Log what will be saved to database
            print(f"\n{'🏷️ '*40}")
            print(f"🏷️  INCOME ATOMIC ENDPOINT - DATABASE INSERT")
            print(f"{'🏷️ '*40}")
            print(f"🏷️  entryType field: {income_data.get('entryType')}")
            print(f"🏷️  taggedAt field: {income_data.get('taggedAt')}")
            print(f"🏷️  taggedBy field: {income_data.get('taggedBy')}")
            if income_data.get('entryType'):
                print(f"🏷️  ✅ WILL SAVE WITH TAG: '{income_data.get('entryType')}'")
            else:
                print(f"🏷️  ⚠️  WILL SAVE WITHOUT TAG (entryType=None)")
            print(f"{'🏷️ '*40}\n")
            
            # Import and apply auto-population for proper source/description
            from utils.income_utils import auto_populate_income_fields
            income_data = auto_populate_income_fields(income_data)
            
            # STEP 6: Insert income into database
            result = atomic_entries_bp.mongo.db.incomes.insert_one(income_data)
            income_id = str(result.inserted_id)
            
            print(f"✓ Income created: {income_id}")
            
            # 🏷️  TAGGING DEBUG: Verify tag was saved correctly
            verification = atomic_entries_bp.mongo.db.incomes.find_one({'_id': result.inserted_id})
            print(f"\n{'🏷️ '*40}")
            print(f"🏷️  INCOME ATOMIC ENDPOINT - POST-INSERT VERIFICATION")
            print(f"{'🏷️ '*40}")
            print(f"🏷️  Income ID: {income_id}")
            print(f"🏷️  entryType in DB: {verification.get('entryType')}")
            print(f"🏷️  taggedAt in DB: {verification.get('taggedAt')}")
            print(f"🏷️  taggedBy in DB: {verification.get('taggedBy')}")
            if verification.get('entryType'):
                print(f"🏷️  ✅ TAG SAVED SUCCESSFULLY: '{verification.get('entryType')}'")
            else:
                print(f"🏷️  ⚠️  NO TAG IN DATABASE (entryType=None)")
            print(f"{'🏷️ '*40}\n")
            
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
            
            # STEP 9: Create notification to remind user to attach supporting documents
            notification_data = None  # FIX 3.1: Capture notification for response
            try:
                from blueprints.notifications import create_user_notification
                
                # CRITICAL: Format relatedId as "income_<id>" for frontend navigation
                formatted_related_id = f'income_{income_id}'
                
                notification_id = create_user_notification(
                    mongo=atomic_entries_bp.mongo,
                    user_id=str(current_user['_id']),
                    category='missingReceipt',
                    title='Don\'t forget to attach supporting documents',
                    body=f'You can add receipts or documents to your ₦{data["amount"]:,.2f} income entry to keep better records.',
                    related_id=formatted_related_id,
                    metadata={
                        'transactionType': 'income',
                        'amount': float(data['amount']),
                        'category': data['category'],
                        'source': data['source']
                    },
                    priority='normal'
                )
                
                if notification_id:
                    print(f"✓ Notification created: {notification_id} (relatedId: {formatted_related_id})")
                    
                    # FIX 3: Send FCM push notification
                    try:
                        from services.firebase_service import firebase_service
                        
                        # Get user's FCM token
                        user = atomic_entries_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                        fcm_token = user.get('fcmToken')
                        
                        if fcm_token:
                            # Send push notification
                            push_sent = firebase_service.send_push_notification(
                                fcm_token=fcm_token,
                                title='Don\'t forget to attach supporting documents',
                                body=f'You can add receipts or documents to your ₦{data["amount"]:,.2f} income entry to keep better records.',
                                data={
                                    'notificationId': notification_id,
                                    'category': 'missingReceipt',
                                    'relatedId': formatted_related_id,
                                    'transactionType': 'income',
                                    'amount': str(data['amount']),
                                    'click_action': 'FLUTTER_NOTIFICATION_CLICK'
                                }
                            )
                            
                            if push_sent:
                                print(f"✓ FCM push sent successfully for notification {notification_id}")
                            else:
                                print(f"⚠ FCM push failed for notification {notification_id} (non-critical)")
                        else:
                            print(f"⚠ No FCM token for user {current_user['email']}, skipping push")
                            
                    except Exception as push_error:
                        print(f"⚠ FCM push failed (non-critical): {push_error}")
                    
                    # FIX 3.1: Prepare notification data for response (eliminates race condition)
                    notification_data = {
                        'id': notification_id,
                        'category': 'missingReceipt',
                        'title': 'Don\'t forget to attach supporting documents',
                        'body': f'You can add receipts or documents to your ₦{data["amount"]:,.2f} income entry to keep better records.',
                        'relatedId': formatted_related_id,
                        'priority': 'normal',
                        'timestamp': datetime.utcnow().isoformat() + 'Z',
                        'isRead': False,
                        'isArchived': False,
                        'metadata': {
                            'transactionType': 'income',
                            'amount': float(data['amount']),
                            'category': data['category'],
                            'source': data['source']
                        }
                    }
                else:
                    print(f"⚠ Notification creation returned None (non-critical)")
                    
            except Exception as notification_error:
                print(f"Notification creation failed (non-critical): {notification_error}")
            
            # STEP 10: Prepare response
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
            
            # FIX 3.1: Include notification in response (eliminates race condition)
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
                    },
                    'notification': notification_data  # FIX 3.1: Include notification in response
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

    # Return the configured blueprint with all routes registered
    return atomic_entries_bp