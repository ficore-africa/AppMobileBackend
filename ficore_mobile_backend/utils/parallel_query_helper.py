"""
Parallel Query Helper for FiCore Mobile
Enables concurrent database queries for improved performance on multi-collection reports
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


def fetch_collections_parallel(fetch_functions, max_workers=5, timeout=30):
    """
    Execute multiple database fetch functions in parallel using ThreadPoolExecutor.
    
    This is safe because:
    - MongoDB connections are thread-safe by default
    - We're only reading data (no writes)
    - Each query is independent
    - Proper error handling for each thread
    
    Args:
        fetch_functions: Dict of {name: callable} where callable returns query results
        max_workers: Maximum number of concurrent threads (default: 5)
        timeout: Maximum time to wait for all queries (default: 30 seconds)
    
    Returns:
        Dict of {name: results} or {name: error} for failed queries
    
    Example:
        results = fetch_collections_parallel({
            'incomes': lambda: list(db.incomes.find(query)),
            'expenses': lambda: list(db.expenses.find(query)),
            'assets': lambda: list(db.assets.find(query))
        })
        
        incomes = results['incomes']
        expenses = results['expenses']
        assets = results['assets']
    """
    results = {}
    errors = {}
    
    # Execute all fetch functions in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_name = {
            executor.submit(func): name 
            for name, func in fetch_functions.items()
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_name, timeout=timeout):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                # Log error but don't fail entire operation
                errors[name] = str(e)
                results[name] = []  # Return empty list for failed queries
                print(f"⚠️ Parallel query failed for {name}: {e}")
    
    # If any errors occurred, log them
    if errors:
        print(f"⚠️ Parallel fetch completed with {len(errors)} error(s): {errors}")
    
    return results


def fetch_two_collections(mongo_db, collection1_name, query1, projection1,
                          collection2_name, query2, projection2):
    """
    Convenience function to fetch from two collections in parallel.
    
    Args:
        mongo_db: MongoDB database instance
        collection1_name: Name of first collection
        query1: Query for first collection
        projection1: Projection for first collection
        collection2_name: Name of second collection
        query2: Query for second collection
        projection2: Projection for second collection
    
    Returns:
        Tuple of (collection1_results, collection2_results)
    
    Example:
        incomes, expenses = fetch_two_collections(
            mongo.db,
            'incomes', income_query, PDF_PROJECTIONS['incomes'],
            'expenses', expense_query, PDF_PROJECTIONS['expenses']
        )
    """
    results = fetch_collections_parallel({
        collection1_name: lambda: list(mongo_db[collection1_name].find(query1, projection1)),
        collection2_name: lambda: list(mongo_db[collection2_name].find(query2, projection2))
    }, max_workers=2)
    
    return results[collection1_name], results[collection2_name]


def fetch_with_timing(fetch_function, label="Query"):
    """
    Wrapper to measure query execution time (useful for debugging).
    
    Args:
        fetch_function: Callable that executes the query
        label: Label for logging
    
    Returns:
        Query results
    """
    start_time = time.time()
    results = fetch_function()
    elapsed = time.time() - start_time
    print(f"⏱️ {label} took {elapsed:.3f}s")
    return results


# Example usage patterns for different report types:

def example_profit_loss_parallel(mongo_db, income_query, expense_query, projections):
    """
    Example: Profit & Loss report (2 collections)
    """
    results = fetch_collections_parallel({
        'incomes': lambda: list(mongo_db.incomes.find(income_query, projections['incomes'])),
        'expenses': lambda: list(mongo_db.expenses.find(expense_query, projections['expenses']))
    }, max_workers=2)
    
    return results['incomes'], results['expenses']


def example_tax_summary_parallel(mongo_db, income_query, expense_query, assets_query, 
                                 user_id, projections):
    """
    Example: Tax Summary report (5 collections)
    """
    results = fetch_collections_parallel({
        'incomes': lambda: list(mongo_db.incomes.find(income_query, projections['incomes'])),
        'expenses': lambda: list(mongo_db.expenses.find(expense_query, projections['expenses'])),
        'assets': lambda: list(mongo_db.assets.find(assets_query, projections['assets'])),
        'inventory': lambda: list(mongo_db.inventory.find({'userId': user_id})),
        'debtors': lambda: list(mongo_db.debtors.find(
            {'userId': user_id, 'status': {'$ne': 'paid'}}, 
            projections.get('debtors', {})
        )),
        'creditors': lambda: list(mongo_db.creditors.find(
            {'userId': user_id, 'status': {'$ne': 'paid'}},
            projections.get('creditors', {})
        ))
    }, max_workers=5)
    
    return (
        results['incomes'],
        results['expenses'],
        results['assets'],
        results['inventory'],
        results['debtors'],
        results['creditors']
    )
