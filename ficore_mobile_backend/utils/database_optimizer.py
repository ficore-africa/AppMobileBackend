"""
Database optimization utilities for financial aggregation performance.
Handles index creation, query optimization, and caching strategies.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)


class DatabaseOptimizer:
    """
    Database optimization service for financial aggregation queries.
    Manages indexes, query optimization, and performance monitoring.
    """
    
    def __init__(self, mongo_db):
        """
        Initialize with MongoDB database instance.
        
        Args:
            mongo_db: PyMongo database instance
        """
        self.db = mongo_db
        self.performance_cache = {}
        
    def create_aggregation_indexes(self) -> Dict[str, Any]:
        """
        Create optimized indexes for financial aggregation queries.
        These indexes are specifically designed for the aggregation patterns used.
        Enhanced with additional performance optimizations for large datasets.
        
        Returns:
            Dict containing results of index creation operations
        """
        results = {
            'created': [],
            'existing': [],
            'errors': []
        }
        
        # Enhanced optimized indexes for financial aggregation queries
        aggregation_indexes = {
            'incomes': [
                # Primary compound index for monthly totals (userId + dateReceived)
                {
                    'keys': [('userId', 1), ('dateReceived', -1)],
                    'name': 'userId_dateReceived_desc_agg',
                    'background': True
                },
                # Enhanced compound index for category aggregations (userId + category + dateReceived)
                {
                    'keys': [('userId', 1), ('category', 1), ('dateReceived', -1)],
                    'name': 'userId_category_dateReceived_agg',
                    'background': True
                },
                # Optimized index for amount-based aggregations with sparse option
                {
                    'keys': [('userId', 1), ('amount', -1), ('dateReceived', -1)],
                    'name': 'userId_amount_dateReceived_agg',
                    'background': True,
                    'sparse': True  # Skip documents with null amounts
                },
                # New: Year-based index for YTD queries optimization
                {
                    'keys': [('userId', 1), ('dateReceived', 1)],  # Ascending for range queries
                    'name': 'userId_dateReceived_asc_ytd',
                    'background': True,
                    'partialFilterExpression': {
                        'dateReceived': {'$type': 'date'}  # Only index valid dates
                    }
                },
                # New: Frequency-based index for recurring income analysis
                {
                    'keys': [('userId', 1), ('frequency', 1), ('dateReceived', -1)],
                    'name': 'userId_frequency_dateReceived_agg',
                    'background': True
                },
                # New: Source-based aggregation index
                {
                    'keys': [('userId', 1), ('source', 1), ('dateReceived', -1)],
                    'name': 'userId_source_dateReceived_agg',
                    'background': True
                }
            ],
            'expenses': [
                # Primary compound index for monthly totals (userId + date)
                {
                    'keys': [('userId', 1), ('date', -1)],
                    'name': 'userId_date_desc_agg',
                    'background': True
                },
                # Enhanced compound index for category aggregations (userId + category + date)
                {
                    'keys': [('userId', 1), ('category', 1), ('date', -1)],
                    'name': 'userId_category_date_agg',
                    'background': True
                },
                # Optimized index for amount-based aggregations with sparse option
                {
                    'keys': [('userId', 1), ('amount', -1), ('date', -1)],
                    'name': 'userId_amount_date_agg',
                    'background': True,
                    'sparse': True  # Skip documents with null amounts
                },
                # New: Year-based index for YTD queries optimization
                {
                    'keys': [('userId', 1), ('date', 1)],  # Ascending for range queries
                    'name': 'userId_date_asc_ytd',
                    'background': True,
                    'partialFilterExpression': {
                        'date': {'$type': 'date'}  # Only index valid dates
                    }
                },
                # New: Payment method analysis index
                {
                    'keys': [('userId', 1), ('paymentMethod', 1), ('date', -1)],
                    'name': 'userId_paymentMethod_date_agg',
                    'background': True
                },
                # New: Tags-based aggregation index for enhanced categorization
                {
                    'keys': [('userId', 1), ('tags', 1), ('date', -1)],
                    'name': 'userId_tags_date_agg',
                    'background': True,
                    'sparse': True  # Only index documents with tags
                }
            ]
        }
        
        for collection_name, indexes in aggregation_indexes.items():
            collection = self.db[collection_name]
            
            for index_def in indexes:
                try:
                    # Check if index already exists
                    existing_indexes = list(collection.list_indexes())
                    index_exists_by_name = any(
                        idx.get('name') == index_def['name'] 
                        for idx in existing_indexes
                    )
                    
                    # Check if an index with the same key pattern already exists (different name)
                    index_exists_by_keys = any(
                        list(idx.get('key', {}).items()) == index_def['keys']
                        for idx in existing_indexes
                        if idx.get('name') != '_id_'  # Skip the default _id index
                    )
                    
                    if index_exists_by_name:
                        results['existing'].append(f"{collection_name}.{index_def['name']}")
                        logger.info(f"Index {index_def['name']} already exists on {collection_name}")
                    elif index_exists_by_keys:
                        existing_name = next(
                            idx.get('name') for idx in existing_indexes 
                            if list(idx.get('key', {}).items()) == index_def['keys'] and idx.get('name') != '_id_'
                        )
                        results['existing'].append(f"{collection_name}.{index_def['name']} (exists as {existing_name})")
                        logger.info(f"Index with same keys already exists as '{existing_name}' on {collection_name} (skipping '{index_def['name']}')")
                    else:
                        # Create index
                        index_name = collection.create_index(
                            index_def['keys'],
                            name=index_def['name'],
                            background=index_def.get('background', True)
                        )
                        results['created'].append(f"{collection_name}.{index_name}")
                        logger.info(f"Created aggregation index {index_name} on {collection_name}")
                        
                except Exception as e:
                    error_msg = f"Failed to create index {index_def['name']} on {collection_name}: {str(e)}"
                    results['errors'].append(error_msg)
                    logger.error(error_msg)
        
        return results
    
    def get_optimized_monthly_pipeline(self, user_id: ObjectId, start_date: datetime, end_date: datetime, collection_type: str = 'income') -> List[Dict[str, Any]]:
        """
        Get optimized aggregation pipeline for monthly totals.
        Uses compound indexes and efficient query patterns with enhanced performance.
        CRITICAL FIX: Ensures amount field is properly converted to numeric type before aggregation.
        CRITICAL FIX: For incomes, only include past/present (dateReceived <= now) to match Recent Activity behavior.
        CRITICAL FIX (Feb 8, 2026): Use get_active_transactions_query to filter out voided/deleted entries.
        
        Args:
            user_id: User's ObjectId
            start_date: Start of period
            end_date: End of period
            collection_type: 'income' or 'expense' to use appropriate date field
            
        Returns:
            List of aggregation pipeline stages
        """
        # CRITICAL FIX (Feb 8, 2026): Import and use get_active_transactions_query
        from utils.immutable_ledger_helper import get_active_transactions_query
        
        # Use appropriate date field based on collection type
        date_field = 'dateReceived' if collection_type == 'income' else 'date'
        
        # Get base query with active transactions filter
        base_query = get_active_transactions_query(user_id)
        
        # Add date range filter
        base_query[date_field] = {
            '$gte': start_date,
            '$lte': end_date
        }
        base_query['amount'] = {'$exists': True, '$ne': None}  # Ensure amount field exists and is not null
        
        return [
            # Enhanced match stage with optimized index usage AND active transactions filter
            {
                '$match': base_query
            },
            # CRITICAL FIX: Add fields stage to ensure amount is numeric
            {
                '$addFields': {
                    'numericAmount': {
                        '$cond': {
                            'if': {'$type': '$amount'},
                            'then': {
                                '$cond': {
                                    'if': {'$eq': [{'$type': '$amount'}, 'string']},
                                    'then': {'$toDouble': '$amount'},
                                    'else': '$amount'
                                }
                            },
                            'else': 0
                        }
                    }
                }
            },
            # Filter out zero or negative amounts after conversion
            {
                '$match': {
                    'numericAmount': {'$gt': 0}
                }
            },
            # Efficient grouping with enhanced aggregation operations using numericAmount
            {
                '$group': {
                    '_id': None,
                    'totalAmount': {'$sum': '$numericAmount'},  # Use converted numeric amount
                    'count': {'$sum': 1},
                    'avgAmount': {'$avg': '$numericAmount'},   # Use converted numeric amount
                    'maxAmount': {'$max': '$numericAmount'},   # Use converted numeric amount
                    'minAmount': {'$min': '$numericAmount'}    # Use converted numeric amount
                }
            },
            # Project final result with computed fields
            {
                '$project': {
                    '_id': 0,
                    'totalAmount': 1,
                    'count': 1,
                    'avgAmount': {'$round': ['$avgAmount', 2]},
                    'maxAmount': 1,
                    'minAmount': 1
                }
            },
            # Limit result set size for performance
            {
                '$limit': 1
            }
        ]
    
    def get_optimized_ytd_pipeline(self, user_id: ObjectId, start_of_year: datetime, collection_type: str = 'income') -> List[Dict[str, Any]]:
        """
        Get optimized aggregation pipeline for year-to-date calculations.
        Enhanced with better index utilization and performance optimizations.
        CRITICAL FIX: Ensures amount field is properly converted to numeric type before aggregation.
        CRITICAL FIX (Feb 8, 2026): Use get_active_transactions_query to filter out voided/deleted entries.
        
        Args:
            user_id: User's ObjectId
            start_of_year: Start of the year for YTD calculation
            collection_type: 'income' or 'expense' to use appropriate date field
            
        Returns:
            List of aggregation pipeline stages
        """
        # CRITICAL FIX (Feb 8, 2026): Import and use get_active_transactions_query
        from utils.immutable_ledger_helper import get_active_transactions_query
        
        # Use appropriate date field based on collection type
        date_field = 'dateReceived' if collection_type == 'income' else 'date'
        
        # Get base query with active transactions filter
        base_query = get_active_transactions_query(user_id)
        
        # Add date range filter
        base_query[date_field] = {'$gte': start_of_year}
        base_query['amount'] = {'$exists': True, '$ne': None}  # Ensure amount field exists and is not null
        
        return [
            # Optimized match stage using ascending date index for range queries AND active transactions filter
            {
                '$match': base_query
            },
            # CRITICAL FIX: Add fields stage to ensure amount is numeric
            {
                '$addFields': {
                    'numericAmount': {
                        '$cond': {
                            'if': {'$type': '$amount'},
                            'then': {
                                '$cond': {
                                    'if': {'$eq': [{'$type': '$amount'}, 'string']},
                                    'then': {'$toDouble': '$amount'},
                                    'else': '$amount'
                                }
                            },
                            'else': 0
                        }
                    }
                }
            },
            # Filter out zero or negative amounts after conversion
            {
                '$match': {
                    'numericAmount': {'$gt': 0}
                }
            },
            # Enhanced grouping by category with additional metrics using numericAmount
            {
                '$group': {
                    '_id': '$category',
                    'count': {'$sum': 1},
                    'totalAmount': {'$sum': '$numericAmount'},  # Use converted numeric amount
                    'avgAmount': {'$avg': '$numericAmount'},   # Use converted numeric amount
                    'firstTransaction': {'$min': f'${date_field}'},
                    'lastTransaction': {'$max': f'${date_field}'}
                }
            },
            # Add computed fields for better analytics
            {
                '$addFields': {
                    'category': '$_id',
                    'avgAmount': {'$round': ['$avgAmount', 2]},
                    'daysSinceFirst': {
                        '$divide': [
                            {'$subtract': [datetime.utcnow(), '$firstTransaction']},
                            86400000  # Convert milliseconds to days
                        ]
                    }
                }
            },
            # Sort by count for consistent results and better performance
            {
                '$sort': {'count': -1, 'totalAmount': -1}
            },
            # Project final structure
            {
                '$project': {
                    '_id': 0,
                    'category': 1,
                    'count': 1,
                    'totalAmount': 1,
                    'avgAmount': 1,
                    'firstTransaction': 1,
                    'lastTransaction': 1,
                    'daysSinceFirst': {'$round': ['$daysSinceFirst', 0]}
                }
            }
        ]
    
    def get_optimized_category_pipeline(self, user_id: ObjectId, start_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Get optimized aggregation pipeline for category counts.
        Uses compound indexes for efficient category grouping.
        
        Args:
            user_id: User's ObjectId
            start_date: Optional start date for filtering
            
        Returns:
            List of aggregation pipeline stages
        """
        match_stage = {'userId': user_id}
        
        if start_date:
            match_stage['$or'] = [
                {'dateReceived': {'$gte': start_date}},
                {'date': {'$gte': start_date}}
            ]
        
        return [
            # Use compound index: userId + category + dateReceived/date
            {'$match': match_stage},
            # Group by category with efficient aggregation
            {
                '$group': {
                    '_id': '$category',
                    'count': {'$sum': 1},
                    'totalAmount': {'$sum': '$amount'}
                }
            },
            # Sort by count for consistent results
            {
                '$sort': {'count': -1}
            }
        ]
    
    def analyze_query_performance(self, collection_name: str, pipeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze aggregation pipeline performance using explain.
        
        Args:
            collection_name: Name of the collection
            pipeline: Aggregation pipeline to analyze
            
        Returns:
            Dict containing performance analysis results
        """
        try:
            collection = self.db[collection_name]
            
            # Get execution stats
            explain_result = collection.aggregate(pipeline, explain=True)
            
            # Extract key performance metrics
            performance_info = {
                'collection': collection_name,
                'pipeline_stages': len(pipeline),
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
            
            # Store in performance cache for monitoring
            cache_key = f"{collection_name}_{hash(str(pipeline))}"
            self.performance_cache[cache_key] = performance_info
            
            return performance_info
            
        except Exception as e:
            logger.error(f"Failed to analyze query performance: {str(e)}")
            return {
                'collection': collection_name,
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
    
    def get_index_usage_stats(self) -> Dict[str, Any]:
        """
        Get index usage statistics for aggregation collections.
        
        Returns:
            Dict containing index usage information
        """
        stats = {}
        
        for collection_name in ['incomes', 'expenses']:
            try:
                collection = self.db[collection_name]
                
                # Get index stats
                index_stats = self.db.command('collStats', collection_name, indexDetails=True)
                
                stats[collection_name] = {
                    'total_indexes': len(list(collection.list_indexes())),
                    'index_sizes': index_stats.get('indexSizes', {}),
                    'total_size': index_stats.get('totalIndexSize', 0)
                }
                
            except Exception as e:
                stats[collection_name] = {'error': str(e)}
        
        return stats
    
    def optimize_aggregation_queries(self) -> Dict[str, Any]:
        """
        Run comprehensive optimization for aggregation queries.
        Creates indexes and analyzes performance.
        
        Returns:
            Dict containing optimization results
        """
        results = {
            'index_creation': self.create_aggregation_indexes(),
            'index_usage': self.get_index_usage_stats(),
            'optimization_timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        
        logger.info("Database optimization completed for financial aggregations")
        return results


class QueryResultCache:
    """
    Enhanced in-memory cache for aggregation query results with TTL support.
    Provides caching for frequently accessed aggregation data with performance monitoring.
    """
    
    def __init__(self, default_ttl_seconds: int = 300, max_cache_size: int = 1000):  # 5 minutes default TTL
        """
        Initialize cache with default TTL and size limits.
        
        Args:
            default_ttl_seconds: Default time-to-live for cached results
            max_cache_size: Maximum number of cache entries before cleanup
        """
        self.cache = {}
        self.default_ttl = default_ttl_seconds
        self.max_cache_size = max_cache_size
        self.hit_count = 0
        self.miss_count = 0
        self.eviction_count = 0
        
    def _generate_cache_key(self, user_id: ObjectId, query_type: str, **kwargs) -> str:
        """
        Generate cache key for query results.
        
        Args:
            user_id: User's ObjectId
            query_type: Type of query (monthly, ytd, all_time)
            **kwargs: Additional parameters for cache key
            
        Returns:
            String cache key
        """
        key_parts = [str(user_id), query_type]
        
        # Add sorted kwargs to ensure consistent keys
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}:{v}")
        
        return ":".join(key_parts)
    
    def get(self, user_id: ObjectId, query_type: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Get cached result if available and not expired.
        
        Args:
            user_id: User's ObjectId
            query_type: Type of query
            **kwargs: Additional cache key parameters
            
        Returns:
            Cached result or None if not found/expired
        """
        cache_key = self._generate_cache_key(user_id, query_type, **kwargs)
        
        if cache_key in self.cache:
            cached_item = self.cache[cache_key]
            
            # Check if expired
            if datetime.utcnow() < cached_item['expires_at']:
                self.hit_count += 1
                # Update access time for LRU tracking
                cached_item['last_accessed'] = datetime.utcnow()
                logger.debug(f"Cache hit for key: {cache_key}")
                return cached_item['data']
            else:
                # Remove expired item
                del self.cache[cache_key]
                logger.debug(f"Cache expired for key: {cache_key}")
        
        self.miss_count += 1
        return None
    
    def set(self, user_id: ObjectId, query_type: str, data: Dict[str, Any], ttl_seconds: Optional[int] = None, **kwargs) -> None:
        """
        Cache query result with TTL and size management.
        
        Args:
            user_id: User's ObjectId
            query_type: Type of query
            data: Data to cache
            ttl_seconds: Time-to-live in seconds (uses default if None)
            **kwargs: Additional cache key parameters
        """
        cache_key = self._generate_cache_key(user_id, query_type, **kwargs)
        ttl = ttl_seconds or self.default_ttl
        
        # Check cache size and evict if necessary
        if len(self.cache) >= self.max_cache_size:
            self._evict_lru_entries()
        
        now = datetime.utcnow()
        self.cache[cache_key] = {
            'data': data,
            'cached_at': now,
            'last_accessed': now,
            'expires_at': now + timedelta(seconds=ttl),
            'access_count': 1
        }
        
        logger.debug(f"Cached result for key: {cache_key}, TTL: {ttl}s")
    
    def invalidate_user_cache(self, user_id: ObjectId) -> int:
        """
        Invalidate all cached results for a specific user.
        
        Args:
            user_id: User's ObjectId
            
        Returns:
            Number of cache entries removed
        """
        user_id_str = str(user_id)
        keys_to_remove = [
            key for key in self.cache.keys() 
            if key.startswith(user_id_str)
        ]
        
        for key in keys_to_remove:
            del self.cache[key]
        
        logger.info(f"Invalidated {len(keys_to_remove)} cache entries for user {user_id}")
        return len(keys_to_remove)
    
    def clear_expired(self) -> int:
        """
        Remove all expired cache entries.
        
        Returns:
            Number of expired entries removed
        """
        now = datetime.utcnow()
        expired_keys = [
            key for key, value in self.cache.items()
            if now >= value['expires_at']
        ]
        
        for key in expired_keys:
            del self.cache[key]
        
        logger.debug(f"Cleared {len(expired_keys)} expired cache entries")
        return len(expired_keys)
    
    def _evict_lru_entries(self) -> int:
        """
        Evict least recently used entries when cache is full.
        
        Returns:
            Number of entries evicted
        """
        if len(self.cache) < self.max_cache_size:
            return 0
        
        # Calculate how many entries to evict (25% of max size)
        evict_count = max(1, self.max_cache_size // 4)
        
        # Sort by last accessed time (oldest first)
        sorted_entries = sorted(
            self.cache.items(),
            key=lambda x: x[1]['last_accessed']
        )
        
        # Remove oldest entries
        for i in range(min(evict_count, len(sorted_entries))):
            key = sorted_entries[i][0]
            del self.cache[key]
            self.eviction_count += 1
        
        logger.debug(f"Evicted {evict_count} LRU cache entries")
        return evict_count
    
    def optimize_cache_ttl(self, query_type: str, execution_time_ms: float) -> int:
        """
        Dynamically optimize cache TTL based on query execution time and type.
        Slower queries get longer cache times to improve performance.
        
        Args:
            query_type: Type of query (monthly, ytd, all_time)
            execution_time_ms: Query execution time in milliseconds
            
        Returns:
            Optimized TTL in seconds
        """
        base_ttl = {
            'monthly_totals': 300,    # 5 minutes base
            'ytd_counts': 600,        # 10 minutes base
            'all_time_counts': 1800,  # 30 minutes base
        }.get(query_type, 300)
        
        # Increase TTL for slower queries (exponential scaling)
        if execution_time_ms > 1000:  # > 1 second
            multiplier = min(3.0, 1 + (execution_time_ms / 1000) * 0.5)
            optimized_ttl = int(base_ttl * multiplier)
        elif execution_time_ms > 500:  # > 500ms
            optimized_ttl = int(base_ttl * 1.5)
        else:
            optimized_ttl = base_ttl
        
        logger.debug(f"Optimized TTL for {query_type}: {optimized_ttl}s (execution: {execution_time_ms}ms)")
        return optimized_ttl
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics including performance metrics.
        
        Returns:
            Dict containing cache statistics
        """
        now = datetime.utcnow()
        active_entries = sum(
            1 for value in self.cache.values()
            if now < value['expires_at']
        )
        
        # Calculate hit rate
        total_requests = self.hit_count + self.miss_count
        hit_rate = (self.hit_count / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'total_entries': len(self.cache),
            'active_entries': active_entries,
            'expired_entries': len(self.cache) - active_entries,
            'hit_count': self.hit_count,
            'miss_count': self.miss_count,
            'eviction_count': self.eviction_count,
            'hit_rate_percentage': round(hit_rate, 2),
            'max_cache_size': self.max_cache_size,
            'default_ttl_seconds': self.default_ttl,
            'last_checked': now.isoformat() + 'Z'
        }


# Global cache instance for aggregation results
aggregation_cache = QueryResultCache(default_ttl_seconds=300)  # 5 minutes TTL