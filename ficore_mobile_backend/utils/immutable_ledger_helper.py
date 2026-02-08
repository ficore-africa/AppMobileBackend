"""
Immutable Ledger Helper Functions
Implements the "Guardian" pattern for financial transactions

Date: January 14, 2026 (Original)
Updated: February 7, 2026 (Version Log + Primary Key Stability)

Purpose: Provide reusable functions for soft-delete and version control

CRITICAL CHANGE (Feb 7, 2026):
- supersede_transaction() now updates SAME document (not create new)
- Version history maintained in versionLog array
- Export history tracked in exportHistory array
- Primary key stability prevents duplicate entries in UI
- "Guardian, not Warden" philosophy: Allow edits, show warnings
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
    Update transaction with version logging (PRIMARY KEY STABILITY)
    
    CRITICAL CHANGE (Feb 7, 2026): Updates SAME document instead of creating new one
    This preserves the deduplication key in frontend and prevents duplicate entries in UI
    
    Version history is maintained in versionLog array, not separate documents
    
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
            'new_id': str,  # SAME as original_id (for backward compatibility)
            'new_version': dict,
            'message': str
        }
    """
    collection = db[collection_name]
    
    try:
        # Step 1: Get the current transaction
        current = collection.find_one({
            '_id': ObjectId(transaction_id),
            'userId': user_id,
            'status': 'active'  # Only update active transactions
        })
        
        if not current:
            return {
                'success': False,
                'message': 'Transaction not found or you do not have permission to update it'
            }
        
        # Step 2: Capture current state for version log
        current_version = current.get('version', 1)
        new_version = current_version + 1
        
        # Build version log entry with snapshot of OLD data
        version_entry = {
            'version': current_version,
            'createdAt': current.get('updatedAt', current.get('createdAt', datetime.utcnow())),
            'createdBy': user_id,
            'changes': list(update_data.keys()),
            'reason': 'user_edit',
            'data': {
                # Snapshot of data BEFORE this edit
                'amount': current.get('amount'),
                'category': current.get('category'),
                'description': current.get('description'),
            }
        }
        
        # Add collection-specific fields to snapshot
        if collection_name == 'incomes':
            version_entry['data']['source'] = current.get('source')
            version_entry['data']['dateReceived'] = current.get('dateReceived')
        elif collection_name == 'expenses':
            version_entry['data']['title'] = current.get('title')
            version_entry['data']['date'] = current.get('date')
        
        # Step 3: Prepare update fields
        update_fields = {
            'version': new_version,
            'updatedAt': datetime.utcnow(),
            **update_data  # Apply user's changes
        }
        
        # Step 4: Update SAME document with $set and $push atomically
        result = collection.update_one(
            {'_id': ObjectId(transaction_id), 'status': 'active'},
            {
                '$set': update_fields,
                '$push': {
                    'versionLog': version_entry
                }
            }
        )
        
        if result.modified_count == 1:
            # Get updated document
            updated = collection.find_one({'_id': ObjectId(transaction_id)})
            
            return {
                'success': True,
                'original_id': str(transaction_id),
                'new_id': str(transaction_id),  # SAME ID (primary key stability)
                'new_version': updated,
                'message': f'{collection_name.capitalize()[:-1]} updated successfully (version {new_version})'
            }
        else:
            return {
                'success': False,
                'message': 'Failed to update transaction'
            }
            
    except Exception as e:
        return {
            'success': False,
            'message': f'Database error during transaction update: {str(e)}'
        }


def get_active_transactions_query(user_id):
    """
    Get the standard query filter for active (non-deleted, non-voided, non-superseded) transactions
    
    CRITICAL FIX: Exclude superseded entries to prevent duplicate counting
    in balance calculations after edits
    
    CRITICAL FIX (Feb 8, 2026): Handle entries without status field (created before version control)
    - Old entries don't have 'status' field
    - These should be treated as 'active' by default
    - Use $in with 'active' and null to include both
    
    Args:
        user_id: ObjectId of the user
    
    Returns:
        dict: MongoDB query filter
    """
    return {
        'userId': user_id,
        '$or': [
            {'status': 'active'},  # Entries with explicit active status
            {'status': {'$exists': False}},  # Old entries without status field
            {'status': None},  # Entries with null status
        ],
        'isDeleted': {'$ne': True}  # Exclude deleted entries (handles missing field too)
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


def check_report_discrepancy(db, collection_name, transaction_id):
    """
    Check if transaction was edited after being exported in a report
    
    GUARDIAN LOGIC (Feb 7, 2026): Detects when current version > exported version
    This creates the "Report Discrepancy" warning in the UI
    
    Args:
        db: MongoDB database instance
        collection_name: 'incomes' or 'expenses'
        transaction_id: ObjectId of the transaction
    
    Returns:
        dict: {
            'has_discrepancy': bool,
            'affected_exports': list,
            'current_version': int,
            'exported_versions': list
        }
    """
    collection = db[collection_name]
    
    # Get the transaction
    transaction = collection.find_one({'_id': ObjectId(transaction_id)})
    
    if not transaction:
        return {
            'has_discrepancy': False,
            'affected_exports': [],
            'current_version': 1,
            'exported_versions': []
        }
    
    current_version = transaction.get('version', 1)
    export_history = transaction.get('exportHistory', [])
    
    if not export_history:
        return {
            'has_discrepancy': False,
            'affected_exports': [],
            'current_version': current_version,
            'exported_versions': []
        }
    
    # Find exports that used OLDER versions
    affected_exports = []
    for export in export_history:
        export_version = export.get('version', 1)
        if current_version > export_version:
            affected_exports.append({
                'report_name': export.get('reportName'),
                'exported_at': export.get('exportedAt'),
                'export_version': export_version,
                'export_type': export.get('exportType'),
                'report_id': export.get('reportId')
            })
    
    return {
        'has_discrepancy': len(affected_exports) > 0,
        'affected_exports': affected_exports,
        'current_version': current_version,
        'exported_versions': [e['export_version'] for e in affected_exports]
    }


def track_export(db, collection_name, entry_ids, report_id, report_name, export_type='tax_report'):
    """
    Track when entries are exported in a report (for transparency, not locking)
    
    TRANSPARENCY MECHANISM (Feb 7, 2026): Records which version was in which report
    This enables the "Report Discrepancy" warning system
    
    Args:
        db: MongoDB database instance
        collection_name: 'incomes' or 'expenses'
        entry_ids: list of entry IDs included in report
        report_id: unique identifier for the report
        report_name: human-readable report name
        export_type: 'tax_report', 'accountant', 'bank_loan', 'audit'
    
    Returns:
        dict: {
            'success': bool,
            'tracked_count': int,
            'message': str
        }
    """
    collection = db[collection_name]
    tracked_count = 0
    
    try:
        for entry_id in entry_ids:
            # Clean ID (remove prefixes like 'income_' or 'expense_')
            clean_id = entry_id.replace('income_', '').replace('expense_', '')
            
            if not ObjectId.is_valid(clean_id):
                continue
            
            # Get current version
            entry = collection.find_one({'_id': ObjectId(clean_id)})
            if not entry:
                continue
            
            # Create export history entry
            export_entry = {
                'exportedAt': datetime.utcnow(),
                'exportType': export_type,
                'reportId': report_id,
                'reportName': report_name,
                'version': entry.get('version', 1)
            }
            
            # Add to export history array
            collection.update_one(
                {'_id': ObjectId(clean_id)},
                {'$push': {'exportHistory': export_entry}}
            )
            
            tracked_count += 1
        
        return {
            'success': True,
            'tracked_count': tracked_count,
            'message': f'Export tracked for {tracked_count} entries'
        }
        
    except Exception as e:
        return {
            'success': False,
            'tracked_count': tracked_count,
            'message': f'Failed to track export: {str(e)}'
        }


def get_version_comparison(db, collection_name, transaction_id, version1, version2):
    """
    Get side-by-side comparison of two versions
    
    DIFF VIEW (Feb 7, 2026): Shows what changed between exported and current version
    Used in the "Version Comparison Modal" in the UI
    
    Args:
        db: MongoDB database instance
        collection_name: 'incomes' or 'expenses'
        transaction_id: ObjectId of the transaction
        version1: int (typically exported version)
        version2: int (typically current version)
    
    Returns:
        dict: {
            'success': bool,
            'version1_data': dict,
            'version2_data': dict,
            'changes': list,
            'message': str
        }
    """
    collection = db[collection_name]
    
    try:
        # Get the transaction
        transaction = collection.find_one({'_id': ObjectId(transaction_id)})
        
        if not transaction:
            return {
                'success': False,
                'message': 'Transaction not found'
            }
        
        version_log = transaction.get('versionLog', [])
        current_version = transaction.get('version', 1)
        
        # Find version1 data in log
        v1_data = None
        for v in version_log:
            if v.get('version') == version1:
                v1_data = v.get('data', {})
                break
        
        # If version2 is current version, use current transaction data
        if version2 == current_version:
            v2_data = {
                'amount': transaction.get('amount'),
                'category': transaction.get('category'),
                'description': transaction.get('description'),
            }
            
            if collection_name == 'incomes':
                v2_data['source'] = transaction.get('source')
                v2_data['dateReceived'] = transaction.get('dateReceived')
            elif collection_name == 'expenses':
                v2_data['title'] = transaction.get('title')
                v2_data['date'] = transaction.get('date')
        else:
            # Find version2 data in log
            v2_data = None
            for v in version_log:
                if v.get('version') == version2:
                    v2_data = v.get('data', {})
                    break
        
        if not v1_data or not v2_data:
            return {
                'success': False,
                'message': 'One or both versions not found in version log'
            }
        
        # Identify changes
        changes = []
        for key in v1_data.keys():
            if v1_data.get(key) != v2_data.get(key):
                changes.append(key)
        
        return {
            'success': True,
            'version1_data': v1_data,
            'version2_data': v2_data,
            'changes': changes,
            'message': 'Version comparison retrieved successfully'
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Failed to get version comparison: {str(e)}'
        }

