"""
Income Blueprint - Immutable Ledger Patch
This file contains the refactored DELETE and UPDATE endpoints with immutability

Date: January 14, 2026
Purpose: Replace hard deletes with soft deletes + reversals, and overwrites with versioning

INTEGRATION INSTRUCTIONS:
1. Run migration script: python scripts/migrate_to_immutable_ledger.py
2. Replace the DELETE and UPDATE methods in income.py with these implementations
3. Update all query filters to include status='active' and isDeleted=False
"""

from flask import request, jsonify
from datetime import datetime
from bson import ObjectId
from utils.immutable_ledger_helper import soft_delete_transaction, supersede_transaction, get_active_transactions_query


def create_immutable_income_endpoints(income_bp, mongo, token_required, serialize_doc):
    """
    Add immutable DELETE and UPDATE endpoints to the income blueprint
    """
    
    @income_bp.route('/<income_id>', methods=['DELETE'])
    @token_required
    def delete_income_immutable(current_user, income_id):
        """
        IMMUTABLE DELETE: Soft delete + reversal entry
        
        Instead of deleting the record, we:
        1. Mark it as 'voided' and 'isDeleted=True'
        2. Create a reversal entry with negative amount
        3. Link them together for audit trail
        """
        try:
            if not ObjectId.is_valid(income_id):
                return jsonify({'success': False, 'message': 'Invalid income ID'}), 400
            
            # Use the immutable ledger helper
            result = soft_delete_transaction(
                db=mongo.db,
                collection_name='incomes',
                transaction_id=income_id,
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
                'message': 'Failed to delete income record',
                'errors': {'general': [str(e)]}
            }), 500
    
    @income_bp.route('/<income_id>', methods=['PUT'])
    @token_required
    def update_income_immutable(current_user, income_id):
        """
        IMMUTABLE UPDATE: Supersede + create new version
        
        Instead of overwriting the record, we:
        1. Mark the original as 'superseded'
        2. Create a new version with updated data
        3. Link them together for version history
        """
        try:
            if not ObjectId.is_valid(income_id):
                return jsonify({'success': False, 'message': 'Invalid income ID'}), 400

            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': 'No data provided'}), 400

            # Validation
            errors = {}
            if 'amount' in data and (not data.get('amount') or data.get('amount', 0) <= 0):
                errors['amount'] = ['Valid amount is required']
            if 'source' in data and not data.get('source'):
                errors['source'] = ['Income source is required']
            if 'category' in data and not data.get('category'):
                errors['category'] = ['Income category is required']
            if 'frequency' in data and not data.get('frequency'):
                errors['frequency'] = ['Income frequency is required']

            if errors:
                return jsonify({'success': False, 'message': 'Validation failed', 'errors': errors}), 400

            # Prepare update data
            update_data = {}
            
            if 'amount' in data:
                raw_amount = float(data['amount'])
                update_data['amount'] = raw_amount
                # DISABLED FOR VAS FOCUS
                # print(f"DEBUG: Updating income record {income_id} with amount: {raw_amount} for user: {current_user['_id']}")
            if 'source' in data:
                update_data['source'] = data['source']
            if 'description' in data:
                update_data['description'] = data['description']
            if 'category' in data:
                update_data['category'] = data['category']
            if 'frequency' in data:
                update_data['frequency'] = data['frequency']
            if 'dateReceived' in data:
                update_data['dateReceived'] = datetime.fromisoformat(data['dateReceived'].replace('Z', ''))
            if 'metadata' in data:
                update_data['metadata'] = data['metadata']

            # Force one-time frequency (simplified income tracking)
            update_data['isRecurring'] = False
            update_data['nextRecurringDate'] = None
            if 'frequency' in data:
                update_data['frequency'] = 'one_time'

            # Use the immutable ledger helper
            result = supersede_transaction(
                db=mongo.db,
                collection_name='incomes',
                transaction_id=income_id,
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
            income_data = serialize_doc(new_version.copy())
            income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
            income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            income_data['updatedAt'] = income_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            next_recurring = income_data.get('nextRecurringDate')
            income_data['nextRecurringDate'] = next_recurring.isoformat() + 'Z' if next_recurring else None

            return jsonify({
                'success': True,
                'data': income_data,
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
                'message': 'Failed to update income record',
                'errors': {'general': [str(e)]}
            }), 500
    
    @income_bp.route('/<income_id>/history', methods=['GET'])
    @token_required
    def get_income_history(current_user, income_id):
        """
        Get the complete version history of an income record
        Shows all edits, reversals, and audit trail
        """
        try:
            if not ObjectId.is_valid(income_id):
                return jsonify({'success': False, 'message': 'Invalid income ID'}), 400
            
            from utils.immutable_ledger_helper import get_transaction_history
            
            history = get_transaction_history(
                db=mongo.db,
                collection_name='incomes',
                transaction_id=income_id
            )
            
            if not history:
                return jsonify({
                    'success': False,
                    'message': 'Income record not found'
                }), 404
            
            # Serialize history
            history_data = []
            for record in history:
                record_data = serialize_doc(record.copy())
                record_data['dateReceived'] = record_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
                record_data['createdAt'] = record_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                record_data['updatedAt'] = record_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if record_data.get('updatedAt') else None
                history_data.append(record_data)
            
            return jsonify({
                'success': True,
                'data': {
                    'history': history_data,
                    'totalVersions': len(history_data)
                },
                'message': 'Income history retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income history',
                'errors': {'general': [str(e)]}
            }), 500


# QUERY FILTER UPDATES
# Add this helper function to be used in all list endpoints

def get_incomes_with_immutable_filter(mongo, user_id, additional_filters=None):
    """
    Get incomes with immutable ledger filtering (only active, non-deleted records)
    
    Args:
        mongo: MongoDB instance
        user_id: ObjectId of the user
        additional_filters: dict of additional query filters
    
    Returns:
        list: Active income records
    """
    query = get_active_transactions_query(user_id)
    
    if additional_filters:
        query.update(additional_filters)
    
    return list(mongo.db.incomes.find(query))


# EXAMPLE: Updated GET /income endpoint with immutable filtering
def get_incomes_immutable_example(mongo, current_user, request):
    """
    Example of how to update the GET /income endpoint with immutable filtering
    """
    try:
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = max(int(request.args.get('offset', 0)), 0)
        category = request.args.get('category')
        frequency = request.args.get('frequency')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        sort_by = request.args.get('sort_by', 'dateReceived')
        sort_order = request.args.get('sort_order', 'desc')
        
        # CRITICAL: Use immutable query filter
        now = datetime.utcnow()
        query = get_active_transactions_query(current_user['_id'])  # NEW: Filters out voided/deleted
        query['dateReceived'] = {'$lte': now}  # Only past and present incomes
        
        if category:
            query['category'] = category
        if frequency:
            query['frequency'] = frequency
        if start_date or end_date:
            date_query = query.get('dateReceived', {})
            if start_date:
                date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
            if end_date:
                date_query['$lte'] = min(datetime.fromisoformat(end_date.replace('Z', '')), now)
            query['dateReceived'] = date_query
        
        # Rest of the endpoint logic remains the same...
        # The key change is using get_active_transactions_query() for the base query
        
    except Exception as e:
        pass  # Error handling


"""
INTEGRATION CHECKLIST:

✅ Step 1: Run migration script
   python ficore_mobile_backend/scripts/migrate_to_immutable_ledger.py

✅ Step 2: Replace DELETE endpoint in income.py
   Replace the delete_income function with delete_income_immutable

✅ Step 3: Replace UPDATE endpoint in income.py
   Replace the update_income function with update_income_immutable

✅ Step 4: Add history endpoint
   Add get_income_history to income.py

✅ Step 5: Update all query filters
   Replace {'userId': user_id} with get_active_transactions_query(user_id)
   in these endpoints:
   - get_incomes
   - get_income_summary
   - get_income_statistics
   - get_income_insights
   - get_income_sources

✅ Step 6: Repeat for expenses.py
   Create expense_immutable_patch.py with same pattern

✅ Step 7: Test thoroughly
   - Create income/expense
   - Edit income/expense (should create new version)
   - Delete income/expense (should create reversal)
   - Verify dashboard only shows active records
   - Check audit trail with /history endpoint

✅ Step 8: Update golden rules
   Add immutability requirement to .kiro/steering/golden-rules.md
"""
