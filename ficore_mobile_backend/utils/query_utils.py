"""
Query utilities for FiCore backend
"""

def get_active_transactions_query():
    """
    Get the standard query for active transactions
    
    Returns:
        dict: MongoDB query for active transactions
    """
    return {
        'status': 'active',
        'isDeleted': False
    }

def supersede_transaction(mongo, transaction_id, new_data):
    """
    Supersede a transaction with new data (immutability pattern)
    
    Args:
        mongo: MongoDB connection
        transaction_id: ID of transaction to supersede
        new_data: New transaction data
    
    Returns:
        dict: Result of superseding operation
    """
    # Mark original as superseded
    result = mongo.update_one(
        {'_id': transaction_id},
        {'$set': {'status': 'superseded', 'supersededAt': datetime.utcnow()}}
    )
    
    # Create new version
    new_data['status'] = 'active'
    new_data['supersedes'] = transaction_id
    new_data['createdAt'] = datetime.utcnow()
    new_data['updatedAt'] = datetime.utcnow()
    
    return {'success': True, 'superseded_id': transaction_id}

def soft_delete_transaction(mongo, transaction_id, reason):
    """
    Soft delete a transaction (immutability pattern)
    
    Args:
        mongo: MongoDB connection
        transaction_id: ID of transaction to delete
        reason: Reason for deletion
    
    Returns:
        dict: Result of deletion operation
    """
    result = mongo.update_one(
        {'_id': transaction_id},
        {
            '$set': {
                'status': 'voided',
                'isDeleted': True,
                'voidedAt': datetime.utcnow(),
                'voidReason': reason
            }
        }
    )
    
    return {'success': result.modified_count > 0}
