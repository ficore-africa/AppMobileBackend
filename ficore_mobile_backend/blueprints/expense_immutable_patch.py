"""
Expense Blueprint - Immutable Ledger Patch
This file contains the refactored DELETE and UPDATE endpoints with immutability

Date: January 14, 2026
Purpose: Replace hard deletes with soft deletes + reversals, and overwrites with versioning

INTEGRATION INSTRUCTIONS:
1. Run migration script: python scripts/migrate_to_immutable_ledger.py
2. Replace the DELETE and UPDATE methods in expenses.py with these implementations
3. Update all query filters to include status='active' and isDeleted=False
"""

from flask import request, jsonify
from datetime import datetime
from bson import ObjectId
from utils.immutable_ledger_helper import soft_delete_transaction, supersede_transaction, get_active_transactions_query


def create_immutable_expense_endpoints(expenses_bp, mongo, token_required, serialize_doc):
    """
    Add immutable DELETE and UPDATE endpoints to the expense blueprint
    """
    
    @expenses_bp.route('/<expense_id>', methods=['DELETE'])
    def delete_expense_immutable(expense_id):
        @expenses_bp.token_required
        def _delete_expense_immutable(current_user):
            """
            IMMUTABLE DELETE: Soft delete + reversal entry
            
            Instead of deleting the record, we:
            1. Mark it as 'voided' and 'isDeleted=True'
            2. Create a reversal entry with negative amount
            3. Link them together for audit trail
            """
            try:
                if not ObjectId.is_valid(expense_id):
                    return jsonify({'success': False, 'message': 'Invalid expense ID'}), 400
                
                # Use the immutable ledger helper
                result = soft_delete_transaction(
                    db=mongo.db,
                    collection_name='expenses',
                    transaction_id=expense_id,
                    user_id=current_user['_id']
                )
                
                if not result['success']:
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
        
        return _delete_expense_immutable()
    
    @expenses_bp.route('/<expense_id>', methods=['PUT'])
    def update_expense_immutable(expense_id):
        @expenses_bp.token_required
        def _update_expense_immutable(current_user):
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
                            from utils.payment_utils import validate_payment_method, normalize_payment_method
                            if not validate_payment_method(data[field]):
                                return jsonify({
                                    'success': False,
                                    'message': 'Invalid payment method',
                                    'errors': {'paymentMethod': ['Unrecognized payment method']}
                                }), 400
                            update_data[field] = normalize_payment_method(data[field])
                        else:
                            update_data[field] = data[field]
                
                # Don't automatically override title with description on updates
                # Only set title if it's explicitly provided or missing
                if 'description' in update_data and not update_data.get('title'):
                    update_data['title'] = update_data['description']
                
                # Use the immutable ledger helper
                result = supersede_transaction(
                    db=mongo.db,
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
                expense_data = serialize_doc(new_version.copy())
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
        
        return _update_expense_immutable()
    
    @expenses_bp.route('/<expense_id>/history', methods=['GET'])
    def get_expense_history(expense_id):
        @expenses_bp.token_required
        def _get_expense_history(current_user):
            """
            Get the complete version history of an expense record
            Shows all edits, reversals, and audit trail
            """
            try:
                if not ObjectId.is_valid(expense_id):
                    return jsonify({'success': False, 'message': 'Invalid expense ID'}), 400
                
                from utils.immutable_ledger_helper import get_transaction_history
                
                history = get_transaction_history(
                    db=mongo.db,
                    collection_name='expenses',
                    transaction_id=expense_id
                )
                
                if not history:
                    return jsonify({
                        'success': False,
                        'message': 'Expense record not found'
                    }), 404
                
                # Serialize history
                history_data = []
                for record in history:
                    record_data = serialize_doc(record.copy())
                    record_data['date'] = record_data.get('date', datetime.utcnow()).isoformat() + 'Z'
                    record_data['createdAt'] = record_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                    record_data['updatedAt'] = record_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if record_data.get('updatedAt') else None
                    history_data.append(record_data)
                
                return jsonify({
                    'success': True,
                    'data': {
                        'history': history_data,
                        'totalVersions': len(history_data)
                    },
                    'message': 'Expense history retrieved successfully'
                })
                
            except Exception as e:
                return jsonify({
                    'success': False,
                    'message': 'Failed to retrieve expense history',
                    'errors': {'general': [str(e)]}
                }), 500
        
        return _get_expense_history()


# QUERY FILTER UPDATES
# Add this helper function to be used in all list endpoints

def get_expenses_with_immutable_filter(mongo, user_id, additional_filters=None):
    """
    Get expenses with immutable ledger filtering (only active, non-deleted records)
    
    Args:
        mongo: MongoDB instance
        user_id: ObjectId of the user
        additional_filters: dict of additional query filters
    
    Returns:
        list: Active expense records
    """
    query = get_active_transactions_query(user_id)
    
    if additional_filters:
        query.update(additional_filters)
    
    return list(mongo.db.expenses.find(query))


# EXAMPLE: Updated GET /expenses endpoint with immutable filtering
def get_expenses_immutable_example(mongo, current_user, request):
    """
    Example of how to update the GET /expenses endpoint with immutable filtering
    """
    try:
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = max(int(request.args.get('offset', 0)), 0)
        category = request.args.get('category')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        sort_by = request.args.get('sort_by', 'date')
        sort_order = request.args.get('sort_order', 'desc')
        
        # CRITICAL: Use immutable query filter
        query = get_active_transactions_query(current_user['_id'])  # NEW: Filters out voided/deleted
        
        if category:
            query['category'] = category
        if start_date or end_date:
            date_query = {}
            if start_date:
                date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
            if end_date:
                date_query['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))
            query['date'] = date_query
        
        # Rest of the endpoint logic remains the same...
        # The key change is using get_active_transactions_query() for the base query
        
    except Exception as e:
        pass  # Error handling


"""
INTEGRATION CHECKLIST FOR EXPENSES:

✅ Step 1: Ensure migration script has run
   python ficore_mobile_backend/scripts/migrate_to_immutable_ledger.py

✅ Step 2: Replace DELETE endpoint in expenses.py
   Replace the delete_expense function with delete_expense_immutable

✅ Step 3: Replace UPDATE endpoint in expenses.py
   Replace the update_expense function with update_expense_immutable

✅ Step 4: Add history endpoint
   Add get_expense_history to expenses.py

✅ Step 5: Update all query filters
   Replace {'userId': user_id} with get_active_transactions_query(user_id)
   in these endpoints:
   - get_expenses
   - get_expense_summary
   - get_expense_statistics
   - get_expense_insights
   - get_expense_categories

✅ Step 6: Test thoroughly
   - Create expense
   - Edit expense (should create new version)
   - Delete expense (should create reversal)
   - Verify dashboard only shows active records
   - Check audit trail with /history endpoint

✅ Step 7: Update frontend
   - Add status and isDeleted fields to Isar schemas
   - Update query filters in Flutter
   - Add "Show Audit Trail" toggle in settings
"""
