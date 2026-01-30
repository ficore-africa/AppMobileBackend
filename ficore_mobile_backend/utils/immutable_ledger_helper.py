"""
Immutable Ledger Helper Functions
Implements the "Ghost Ledger" pattern for financial transactions

Date: January 14, 2026
Purpose: Provide reusable functions for soft-delete and version control
"""

from datetime import datetime
from bson import ObjectId


def soft_delete_transaction(db, collection_name, transaction_id, user_id):
    """
    Soft delete a transaction by marking it as voided and creating a reversal entry
    
    Args:
        db: MongoDB database instance
        collection_name: 'incomes' or 'expenses'
        transaction_id: ObjectId of the transaction to delete
        user_id: ObjectId of the user performing the deletion
    
    Returns:
        dict: {
            'success': bool,
            'original_id': str,
            'reversal_id': str,
            'message': str
        }
    """
    collection = db[collection_name]
    
    # Step 1: Get the original transaction
    original = collection.find_one({
        '_id': ObjectId(transaction_id),
        'userId': user_id
    })
    
    if not original:
        return {
            'success': False,
            'message': 'Transaction not found or you do not have permission to delete it'
        }
    
    # Check if already deleted
    if original.get('isDeleted') or original.get('status') == 'voided':
        return {
            'success': False,
            'message': 'Transaction is already deleted'
        }
    
    # Step 2: Mark original as voided
    collection.update_one(
        {'_id': ObjectId(transaction_id)},
        {'$set': {
            'status': 'voided',
            'isDeleted': True,
            'deletedAt': datetime.utcnow(),
            'deletedBy': user_id,
            'updatedAt': datetime.utcnow()
        }}
    )
    
    # Step 3: Create reversal entry (negative amount to cancel out balance)
    # CRITICAL: Mark reversal as HIDDEN so it doesn't show in UI
    reversal = {
        '_id': ObjectId(),
        'userId': user_id,
        'amount': -original['amount'],  # NEGATIVE to cancel out
        'type': 'REVERSAL',
        'status': 'voided',  # CHANGED: Mark as voided so it's filtered out
        'isDeleted': True,  # CHANGED: Mark as deleted so it's filtered out
        'isHidden': True,  # ADDED: Extra flag for reversal entries
        'originalEntryId': str(transaction_id),
        'version': 1,
        'createdAt': datetime.utcnow(),
        'updatedAt': datetime.utcnow(),
        'auditLog': [{
            'action': 'reversal_created',
            'timestamp': datetime.utcnow(),
            'userId': str(user_id),
            'reason': 'User deleted original transaction'
        }]
    }
    
    # Add collection-specific fields
    if collection_name == 'incomes':
        reversal['source'] = f"Reversal: {original.get('source', 'Income')}"
        reversal['description'] = f"Reversal of deleted income: {original.get('description', '')}"
        reversal['category'] = original.get('category', 'other')
        reversal['frequency'] = 'one_time'
        reversal['dateReceived'] = datetime.utcnow()
        reversal['isRecurring'] = False
        reversal['nextRecurringDate'] = None
    elif collection_name == 'expenses':
        reversal['title'] = f"Reversal: {original.get('title', original.get('description', 'Expense'))}"
        reversal['description'] = f"Reversal of deleted expense: {original.get('description', '')}"
        reversal['category'] = original.get('category', 'Other')
        reversal['date'] = datetime.utcnow()
    
    reversal_result = collection.insert_one(reversal)
    reversal_id = str(reversal_result.inserted_id)
    
    # Step 4: Link them
    collection.update_one(
        {'_id': ObjectId(transaction_id)},
        {'$set': {'reversalEntryId': reversal_id}}
    )
    
    return {
        'success': True,
        'original_id': str(transaction_id),
        'reversal_id': reversal_id,
        'message': 'Transaction deleted successfully (reversal entry created)'
    }


def supersede_transaction(db, collection_name, transaction_id, user_id, update_data):
    """
    Create a new version of a transaction instead of overwriting the original
    OPTIMIZED: Uses atomic operations and proper error handling
    
    Args:
        db: MongoDB database instance
        collection_name: 'incomes' or 'expenses'
        transaction_id: ObjectId of the transaction to update
        user_id: ObjectId of the user performing the update
        update_data: dict of fields to update
    
    Returns:
        dict: {
            'success': bool,
            'original_id': str,
            'new_id': str,
            'new_version': dict,
            'message': str
        }
    """
    collection = db[collection_name]
    
    try:
        # Step 1: Get the original transaction with atomic check
        original = collection.find_one({
            '_id': ObjectId(transaction_id),
            'userId': user_id,
            'status': {'$nin': ['superseded', 'voided']}  # Ensure not already processed
        })
        
        if not original:
            return {
                'success': False,
                'message': 'Transaction not found, already processed, or you do not have permission to update it'
            }
        
        # Step 2: Prepare new version data
        new_entry = original.copy()
        new_entry['_id'] = ObjectId()  # New ID
        new_entry['version'] = original.get('version', 1) + 1
        new_entry['originalEntryId'] = str(transaction_id)
        new_entry['status'] = 'active'
        new_entry['createdAt'] = datetime.utcnow()
        new_entry['updatedAt'] = datetime.utcnow()
        
        # Apply updates
        for key, value in update_data.items():
            if key not in ['_id', 'userId', 'version', 'originalEntryId', 'status']:
                new_entry[key] = value
        
        # Add audit log entry
        if 'auditLog' not in new_entry:
            new_entry['auditLog'] = []
        
        new_entry['auditLog'].append({
            'action': 'version_created',
            'timestamp': datetime.utcnow(),
            'userId': str(user_id),
            'version': new_entry['version'],
            'changes': list(update_data.keys())
        })
        
        # Step 3: Use bulk operations for atomicity
        from pymongo import UpdateOne, InsertOne
        
        bulk_operations = [
            # Mark original as superseded
            UpdateOne(
                {'_id': ObjectId(transaction_id), 'status': {'$nin': ['superseded', 'voided']}},
                {'$set': {
                    'status': 'superseded',
                    'supersededAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow(),
                    'supersededBy': str(new_entry['_id'])
                }}
            ),
            # Insert new version
            InsertOne(new_entry)
        ]
        
        # Execute bulk operations atomically
        result = collection.bulk_write(bulk_operations, ordered=True)
        
        # Verify both operations succeeded
        if result.modified_count == 1 and result.inserted_count == 1:
            return {
                'success': True,
                'original_id': str(transaction_id),
                'new_id': str(new_entry['_id']),
                'new_version': new_entry,
                'message': f'{collection_name.capitalize()[:-1]} updated successfully (version {new_entry["version"]})'
            }
        else:
            # Rollback if partial success
            collection.delete_one({'_id': new_entry['_id']})
            collection.update_one(
                {'_id': ObjectId(transaction_id)},
                {'$unset': {'supersededBy': '', 'supersededAt': ''}, '$set': {'status': 'active'}}
            )
            return {
                'success': False,
                'message': 'Failed to complete transaction update atomically'
            }
            
    except Exception as e:
        # Ensure cleanup on any error
        try:
            collection.delete_one({'_id': new_entry['_id']})
            collection.update_one(
                {'_id': ObjectId(transaction_id)},
                {'$unset': {'supersededBy': '', 'supersededAt': ''}, '$set': {'status': 'active'}}
            )
        except:
            pass  # Best effort cleanup
            
        return {
            'success': False,
            'message': f'Database error during transaction update: {str(e)}'
        }
    
    return {
        'success': True,
        'original_id': str(transaction_id),
        'new_id': str(new_id),
        'new_version': new_entry,
        'message': f'Transaction updated successfully (version {new_entry["version"]} created)'
    }


def get_active_transactions_query(user_id):
    """
    Get the standard query filter for active (non-deleted, non-voided, non-superseded) transactions
    
    CRITICAL FIX: Exclude superseded entries to prevent duplicate counting
    in balance calculations after edits
    
    Args:
        user_id: ObjectId of the user
    
    Returns:
        dict: MongoDB query filter
    """
    return {
        'userId': user_id,
        'status': 'active',  # Only active entries (excludes voided AND superseded)
        'isDeleted': False
    }


def get_transaction_history(db, collection_name, transaction_id):
    """
    Get the complete history of a transaction (all versions and reversals)
    
    Args:
        db: MongoDB database instance
        collection_name: 'incomes' or 'expenses'
        transaction_id: ObjectId of the transaction
    
    Returns:
        list: All related transactions in chronological order
    """
    collection = db[collection_name]
    
    # Find the original transaction
    transaction = collection.find_one({'_id': ObjectId(transaction_id)})
    
    if not transaction:
        return []
    
    # Find the root (original) transaction
    original_id = transaction.get('originalEntryId', str(transaction_id))
    
    # Find all versions (transactions with this originalEntryId)
    versions = list(collection.find({
        '$or': [
            {'_id': ObjectId(original_id)},
            {'originalEntryId': original_id}
        ]
    }).sort('createdAt', 1))
    
    return versions
