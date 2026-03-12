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

def get_transaction_history(mongo, collection_name, original_transaction_id):
    """
    Get the complete history of a transaction including all versions
    
    Args:
        mongo: MongoDB connection
        collection_name: 'incomes' or 'expenses'
        original_transaction_id: ObjectId of original transaction
        
    Returns:
        list: All versions of the transaction
    """
    try:
        collection = getattr(mongo.db, collection_name)
        
        # Find all versions
        versions = list(collection.find({
            '$or': [
                {'_id': ObjectId(original_transaction_id)},
                {'originalTransactionId': ObjectId(original_transaction_id)}
            ]
        }).sort('createdAt', 1))
        
        return versions
        
    except Exception as e:
        logger.error(f"Error getting transaction history for {original_transaction_id}: {str(e)}")
        return []


def get_version_comparison(mongo, collection_name, transaction_id):
    """
    Compare different versions of a transaction
    
    Args:
        mongo: MongoDB connection
        collection_name: 'incomes' or 'expenses'
        transaction_id: ObjectId of any version of the transaction
        
    Returns:
        dict: Comparison data between versions
    """
    try:
        collection = getattr(mongo.db, collection_name)
        
        # Get the transaction
        transaction = collection.find_one({'_id': ObjectId(transaction_id)})
        if not transaction:
            return {'error': 'Transaction not found'}
        
        # Find original transaction ID
        original_id = transaction.get('originalTransactionId', transaction['_id'])
        
        # Get all versions
        versions = get_transaction_history(mongo, collection_name, original_id)
        
        if len(versions) < 2:
            return {'versions': versions, 'changes': []}
        
        # Compare versions
        changes = []
        for i in range(1, len(versions)):
            prev_version = versions[i-1]
            curr_version = versions[i]
            
            version_changes = []
            for key in ['amount', 'category', 'description', 'date']:
                if prev_version.get(key) != curr_version.get(key):
                    version_changes.append({
                        'field': key,
                        'old_value': prev_version.get(key),
                        'new_value': curr_version.get(key)
                    })
            
            if version_changes:
                changes.append({
                    'version': i + 1,
                    'timestamp': curr_version.get('createdAt'),
                    'changes': version_changes
                })
        
        return {'versions': versions, 'changes': changes}
        
    except Exception as e:
        logger.error(f"Error comparing versions for {transaction_id}: {str(e)}")
        return {'error': str(e)}


def check_report_discrepancy(mongo, user_id, start_date, end_date):
    """
    Check for discrepancies in financial reports
    
    Args:
        mongo: MongoDB connection
        user_id: User ObjectId
        start_date: Start date for checking
        end_date: End date for checking
        
    Returns:
        dict: Discrepancy report
    """
    try:
        from decimal_helpers import safe_float, safe_sum
        
        # Get active transactions
        query = get_active_transactions_query(user_id, start_date, end_date)
        
        incomes = list(mongo.db.incomes.find(query))
        expenses = list(mongo.db.expenses.find(query))
        
        # Calculate totals
        total_income = safe_sum([safe_float(inc.get('amount', 0)) for inc in incomes])
        total_expenses = safe_sum([safe_float(exp.get('amount', 0)) for exp in expenses])
        
        # Check for common discrepancies
        discrepancies = []
        
        # Check for duplicate entries
        income_descriptions = [inc.get('description', '') for inc in incomes]
        expense_descriptions = [exp.get('description', '') for exp in expenses]
        
        if len(income_descriptions) != len(set(income_descriptions)):
            discrepancies.append('Potential duplicate income entries found')
        
        if len(expense_descriptions) != len(set(expense_descriptions)):
            discrepancies.append('Potential duplicate expense entries found')
        
        # Check for unusual amounts
        if total_income > 10000000:  # 10M threshold
            discrepancies.append('Unusually high income total detected')
        
        if total_expenses > total_income * 2:
            discrepancies.append('Expenses significantly exceed income')
        
        return {
            'total_income': total_income,
            'total_expenses': total_expenses,
            'net_profit': total_income - total_expenses,
            'discrepancies': discrepancies,
            'income_count': len(incomes),
            'expense_count': len(expenses)
        }
        
    except Exception as e:
        logger.error(f"Error checking report discrepancy: {str(e)}")
        return {'error': str(e)}
