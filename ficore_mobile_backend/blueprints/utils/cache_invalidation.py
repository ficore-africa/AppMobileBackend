"""
Cache invalidation service for financial data updates.
Automatically invalidates relevant cache entries when financial data changes.
"""

from datetime import datetime
from typing import Dict, Any, Optional
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)


class CacheInvalidationService:
    """
    Service for intelligent cache invalidation based on data changes.
    Ensures cache consistency when financial data is modified.
    """
    
    def __init__(self, enhanced_cache):
        """
        Initialize cache invalidation service.
        
        Args:
            enhanced_cache: Enhanced cache service instance
        """
        self.cache = enhanced_cache
        
    def invalidate_on_transaction_create(self, user_id: ObjectId, transaction_type: str, 
                                       transaction_date: datetime, **kwargs) -> Dict[str, int]:
        """
        Invalidate cache entries when a new transaction is created.
        
        Args:
            user_id: User's ObjectId
            transaction_type: 'income' or 'expense'
            transaction_date: Date of the transaction
            **kwargs: Additional transaction details
            
        Returns:
            Dict containing invalidation counts by pattern
        """
        invalidation_results = {}
        
        # Always invalidate user's aggregation data
        invalidation_results['user_data'] = self.cache.invalidate_by_pattern('user_data', user_id)
        
        # Invalidate monthly data if transaction is in current month
        current_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if transaction_date >= current_month:
            invalidation_results['monthly_data'] = self.cache.invalidate_by_pattern('monthly_data', user_id)
        
        # Invalidate yearly data if transaction is in current year
        current_year_start = datetime.utcnow().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        if transaction_date >= current_year_start:
            invalidation_results['yearly_data'] = self.cache.invalidate_by_pattern('yearly_data', user_id)
        
        # Log invalidation
        total_invalidated = sum(invalidation_results.values())
        logger.info(f"Invalidated {total_invalidated} cache entries for user {user_id} after {transaction_type} creation")
        
        return invalidation_results
    
    def invalidate_on_transaction_update(self, user_id: ObjectId, old_transaction: Dict[str, Any], 
                                       new_transaction: Dict[str, Any]) -> Dict[str, int]:
        """
        Invalidate cache entries when a transaction is updated.
        
        Args:
            user_id: User's ObjectId
            old_transaction: Previous transaction data
            new_transaction: Updated transaction data
            
        Returns:
            Dict containing invalidation counts by pattern
        """
        invalidation_results = {}
        
        # Check if amount or date changed (affects aggregations)
        amount_changed = old_transaction.get('amount') != new_transaction.get('amount')
        date_changed = old_transaction.get('date') != new_transaction.get('date') or \
                      old_transaction.get('dateReceived') != new_transaction.get('dateReceived')
        category_changed = old_transaction.get('category') != new_transaction.get('category')
        
        if amount_changed or date_changed or category_changed:
            # Invalidate all user data if significant changes
            invalidation_results['user_data'] = self.cache.invalidate_by_pattern('user_data', user_id)
            
            # Check if changes affect current month/year
            current_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            current_year_start = datetime.utcnow().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
            old_date = old_transaction.get('date') or old_transaction.get('dateReceived')
            new_date = new_transaction.get('date') or new_transaction.get('dateReceived')
            
            # Invalidate monthly data if either date is in current month
            if (old_date and old_date >= current_month) or (new_date and new_date >= current_month):
                invalidation_results['monthly_data'] = self.cache.invalidate_by_pattern('monthly_data', user_id)
            
            # Invalidate yearly data if either date is in current year
            if (old_date and old_date >= current_year_start) or (new_date and new_date >= current_year_start):
                invalidation_results['yearly_data'] = self.cache.invalidate_by_pattern('yearly_data', user_id)
        
        total_invalidated = sum(invalidation_results.values())
        logger.info(f"Invalidated {total_invalidated} cache entries for user {user_id} after transaction update")
        
        return invalidation_results
    
    def invalidate_on_transaction_delete(self, user_id: ObjectId, transaction: Dict[str, Any]) -> Dict[str, int]:
        """
        Invalidate cache entries when a transaction is deleted.
        
        Args:
            user_id: User's ObjectId
            transaction: Deleted transaction data
            
        Returns:
            Dict containing invalidation counts by pattern
        """
        invalidation_results = {}
        
        # Always invalidate user's aggregation data
        invalidation_results['user_data'] = self.cache.invalidate_by_pattern('user_data', user_id)
        
        # Check if deletion affects current month/year
        transaction_date = transaction.get('date') or transaction.get('dateReceived')
        
        if transaction_date:
            current_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            current_year_start = datetime.utcnow().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
            if transaction_date >= current_month:
                invalidation_results['monthly_data'] = self.cache.invalidate_by_pattern('monthly_data', user_id)
            
            if transaction_date >= current_year_start:
                invalidation_results['yearly_data'] = self.cache.invalidate_by_pattern('yearly_data', user_id)
        
        total_invalidated = sum(invalidation_results.values())
        logger.info(f"Invalidated {total_invalidated} cache entries for user {user_id} after transaction deletion")
        
        return invalidation_results
    
    def invalidate_on_bulk_operation(self, user_id: ObjectId, operation_type: str, 
                                   affected_count: int) -> Dict[str, int]:
        """
        Invalidate cache entries after bulk operations.
        
        Args:
            user_id: User's ObjectId
            operation_type: Type of bulk operation ('import', 'bulk_update', 'bulk_delete')
            affected_count: Number of records affected
            
        Returns:
            Dict containing invalidation counts by pattern
        """
        invalidation_results = {}
        
        # For bulk operations, invalidate all user data to be safe
        invalidation_results['user_data'] = self.cache.invalidate_by_pattern('user_data', user_id)
        
        # Also clear any expired entries globally to free up space
        expired_cleared = self.cache.clear_expired()
        
        logger.info(f"Invalidated cache for user {user_id} after {operation_type} affecting {affected_count} records. Cleared {expired_cleared} expired entries.")
        
        return invalidation_results
    
    def schedule_cache_refresh(self, user_id: ObjectId, query_types: list = None) -> Dict[str, Any]:
        """
        Schedule cache refresh for specific query types.
        This can be used to proactively refresh cache after known data changes.
        
        Args:
            user_id: User's ObjectId
            query_types: List of query types to refresh (None for all)
            
        Returns:
            Dict containing refresh scheduling results
        """
        if query_types is None:
            query_types = ['monthly_totals', 'ytd_counts', 'all_time_counts']
        
        # For now, just invalidate the specified query types
        # In a more advanced implementation, this could queue background refresh jobs
        invalidated_count = 0
        
        for query_type in query_types:
            pattern_map = {
                'monthly_totals': 'monthly_data',
                'ytd_counts': 'yearly_data',
                'all_time_counts': 'user_data'
            }
            
            pattern = pattern_map.get(query_type, 'user_data')
            count = self.cache.invalidate_by_pattern(pattern, user_id)
            invalidated_count += count
        
        logger.info(f"Scheduled cache refresh for user {user_id}, invalidated {invalidated_count} entries")
        
        return {
            'user_id': str(user_id),
            'query_types_refreshed': query_types,
            'entries_invalidated': invalidated_count,
            'scheduled_at': datetime.utcnow().isoformat() + 'Z'
        }


# Global cache invalidation service instance
cache_invalidation_service = None

def get_cache_invalidation_service(enhanced_cache):
    """
    Get or create the global cache invalidation service instance.
    
    Args:
        enhanced_cache: Enhanced cache service instance
        
    Returns:
        CacheInvalidationService instance
    """
    global cache_invalidation_service
    if cache_invalidation_service is None:
        cache_invalidation_service = CacheInvalidationService(enhanced_cache)
    return cache_invalidation_service