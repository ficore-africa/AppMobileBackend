"""
Enhanced caching service for financial aggregation data.
Provides Redis-like functionality with in-memory fallback and cache warming strategies.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from bson import ObjectId
import logging
import json
import hashlib
import threading
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class CacheWarmer:
    """
    Cache warming service for frequently accessed aggregation data.
    Proactively calculates and caches common queries to improve response times.
    """
    
    def __init__(self, cache_service, aggregation_service):
        """
        Initialize cache warmer with cache and aggregation services.
        
        Args:
            cache_service: Enhanced cache service instance
            aggregation_service: Financial aggregation service instance
        """
        self.cache = cache_service
        self.aggregation_service = aggregation_service
        self.warming_active = False
        self.warming_thread = None
        self.warming_interval = 300  # 5 minutes
        self.user_access_patterns = defaultdict(list)
        
    def track_user_access(self, user_id: ObjectId, query_type: str, **kwargs):
        """
        Track user access patterns for intelligent cache warming.
        
        Args:
            user_id: User's ObjectId
            query_type: Type of query accessed
            **kwargs: Query parameters
        """
        access_record = {
            'query_type': query_type,
            'timestamp': datetime.utcnow(),
            'params': kwargs
        }
        
        # Keep only recent access patterns (last 24 hours)
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        self.user_access_patterns[str(user_id)] = [
            record for record in self.user_access_patterns[str(user_id)]
            if record['timestamp'] > cutoff_time
        ]
        
        self.user_access_patterns[str(user_id)].append(access_record)
        
    def get_warming_candidates(self) -> List[Dict[str, Any]]:
        """
        Get list of cache entries that should be warmed based on access patterns.
        
        Returns:
            List of warming candidates with user_id and query details
        """
        candidates = []
        now = datetime.utcnow()
        
        for user_id_str, access_history in self.user_access_patterns.items():
            if not access_history:
                continue
                
            # Analyze access patterns for this user
            query_frequency = defaultdict(int)
            for record in access_history:
                query_key = f"{record['query_type']}_{json.dumps(record['params'], sort_keys=True)}"
                query_frequency[query_key] += 1
            
            # Add frequently accessed queries to warming candidates
            for query_key, frequency in query_frequency.items():
                if frequency >= 3:  # Accessed 3+ times in 24 hours
                    query_type, params_json = query_key.split('_', 1)
                    params = json.loads(params_json) if params_json != '{}' else {}
                    
                    candidates.append({
                        'user_id': ObjectId(user_id_str),
                        'query_type': query_type,
                        'params': params,
                        'frequency': frequency,
                        'priority': frequency * 10  # Higher frequency = higher priority
                    })
        
        # Sort by priority (highest first)
        candidates.sort(key=lambda x: x['priority'], reverse=True)
        return candidates[:50]  # Limit to top 50 candidates
    
    def warm_cache_entry(self, user_id: ObjectId, query_type: str, **params):
        """
        Warm a specific cache entry by executing the query and caching the result.
        
        Args:
            user_id: User's ObjectId
            query_type: Type of query to warm
            **params: Query parameters
        """
        try:
            if query_type == 'monthly_totals':
                result = self.aggregation_service.get_current_month_totals(user_id, use_cache=False)
                # Cache with extended TTL for warmed entries
                self.cache.set(user_id, query_type, result, ttl_seconds=900, **params)
                
            elif query_type == 'ytd_counts':
                result = self.aggregation_service.get_ytd_record_counts(user_id, use_cache=False)
                self.cache.set(user_id, query_type, result, ttl_seconds=1200, **params)
                
            elif query_type == 'all_time_counts':
                result = self.aggregation_service.get_all_time_record_counts(user_id)
                self.cache.set(user_id, query_type, result, ttl_seconds=3600, **params)
                
            logger.debug(f"Warmed cache for user {user_id}, query {query_type}")
            
        except Exception as e:
            logger.error(f"Failed to warm cache for user {user_id}, query {query_type}: {str(e)}")
    
    def start_warming_service(self):
        """
        Start the background cache warming service.
        """
        if self.warming_active:
            return
            
        self.warming_active = True
        self.warming_thread = threading.Thread(target=self._warming_loop, daemon=True)
        self.warming_thread.start()
        logger.info("Cache warming service started")
    
    def stop_warming_service(self):
        """
        Stop the background cache warming service.
        """
        self.warming_active = False
        if self.warming_thread:
            self.warming_thread.join(timeout=5)
        logger.info("Cache warming service stopped")
    
    def _warming_loop(self):
        """
        Background loop for cache warming.
        """
        while self.warming_active:
            try:
                candidates = self.get_warming_candidates()
                
                # Warm top priority candidates
                for candidate in candidates[:10]:  # Warm top 10 per cycle
                    if not self.warming_active:
                        break
                        
                    self.warm_cache_entry(
                        candidate['user_id'],
                        candidate['query_type'],
                        **candidate['params']
                    )
                    
                    # Small delay between warming operations
                    time.sleep(1)
                
                # Wait for next warming cycle
                time.sleep(self.warming_interval)
                
            except Exception as e:
                logger.error(f"Error in cache warming loop: {str(e)}")
                time.sleep(60)  # Wait 1 minute before retrying


class EnhancedCacheService:
    """
    Enhanced caching service with Redis-like functionality and intelligent cache management.
    Provides advanced features like cache warming, invalidation patterns, and performance analytics.
    """
    
    def __init__(self, default_ttl_seconds: int = 300, max_cache_size: int = 2000):
        """
        Initialize enhanced cache service.
        
        Args:
            default_ttl_seconds: Default time-to-live for cached results
            max_cache_size: Maximum number of cache entries
        """
        self.cache = {}
        self.default_ttl = default_ttl_seconds
        self.max_cache_size = max_cache_size
        
        # Performance metrics
        self.hit_count = 0
        self.miss_count = 0
        self.eviction_count = 0
        self.invalidation_count = 0
        
        # Cache patterns for intelligent invalidation
        self.invalidation_patterns = {
            'user_data': ['monthly_totals', 'ytd_counts', 'all_time_counts'],
            'monthly_data': ['monthly_totals'],
            'yearly_data': ['ytd_counts'],
            'transaction_data': ['monthly_totals', 'ytd_counts', 'all_time_counts']
        }
        
        # Thread lock for thread-safe operations
        self._lock = threading.RLock()
        
    def _generate_cache_key(self, user_id: ObjectId, query_type: str, **kwargs) -> str:
        """
        Generate cache key with enhanced hashing for complex parameters.
        
        Args:
            user_id: User's ObjectId
            query_type: Type of query
            **kwargs: Additional parameters
            
        Returns:
            String cache key
        """
        key_parts = [str(user_id), query_type]
        
        # Sort kwargs for consistent keys
        for k, v in sorted(kwargs.items()):
            if isinstance(v, (dict, list)):
                # Hash complex objects for consistent keys
                v_str = json.dumps(v, sort_keys=True)
                v_hash = hashlib.md5(v_str.encode()).hexdigest()[:8]
                key_parts.append(f"{k}:{v_hash}")
            else:
                key_parts.append(f"{k}:{v}")
        
        return ":".join(key_parts)
    
    def get(self, user_id: ObjectId, query_type: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Get cached result with enhanced performance tracking.
        
        Args:
            user_id: User's ObjectId
            query_type: Type of query
            **kwargs: Additional cache key parameters
            
        Returns:
            Cached result or None if not found/expired
        """
        with self._lock:
            cache_key = self._generate_cache_key(user_id, query_type, **kwargs)
            
            if cache_key in self.cache:
                cached_item = self.cache[cache_key]
                
                # Check if expired
                if datetime.utcnow() < cached_item['expires_at']:
                    self.hit_count += 1
                    # Update access metrics
                    cached_item['last_accessed'] = datetime.utcnow()
                    cached_item['access_count'] += 1
                    
                    logger.debug(f"Cache hit for key: {cache_key}")
                    return cached_item['data']
                else:
                    # Remove expired item
                    del self.cache[cache_key]
                    logger.debug(f"Cache expired for key: {cache_key}")
            
            self.miss_count += 1
            return None
    
    def set(self, user_id: ObjectId, query_type: str, data: Dict[str, Any], 
            ttl_seconds: Optional[int] = None, **kwargs) -> None:
        """
        Cache query result with enhanced metadata and size management.
        
        Args:
            user_id: User's ObjectId
            query_type: Type of query
            data: Data to cache
            ttl_seconds: Time-to-live in seconds
            **kwargs: Additional cache key parameters
        """
        with self._lock:
            cache_key = self._generate_cache_key(user_id, query_type, **kwargs)
            ttl = ttl_seconds or self.default_ttl
            
            # Check cache size and evict if necessary
            if len(self.cache) >= self.max_cache_size:
                self._evict_lru_entries()
            
            now = datetime.utcnow()
            
            # Calculate data size for monitoring
            data_size = len(json.dumps(data, default=str))
            
            self.cache[cache_key] = {
                'data': data,
                'cached_at': now,
                'last_accessed': now,
                'expires_at': now + timedelta(seconds=ttl),
                'access_count': 1,
                'user_id': str(user_id),
                'query_type': query_type,
                'data_size_bytes': data_size,
                'ttl_seconds': ttl
            }
            
            logger.debug(f"Cached result for key: {cache_key}, TTL: {ttl}s, Size: {data_size} bytes")
    
    def invalidate_by_pattern(self, pattern: str, user_id: Optional[ObjectId] = None) -> int:
        """
        Invalidate cache entries based on patterns.
        
        Args:
            pattern: Invalidation pattern ('user_data', 'monthly_data', etc.)
            user_id: Optional user ID to limit invalidation scope
            
        Returns:
            Number of cache entries invalidated
        """
        with self._lock:
            if pattern not in self.invalidation_patterns:
                logger.warning(f"Unknown invalidation pattern: {pattern}")
                return 0
            
            query_types = self.invalidation_patterns[pattern]
            keys_to_remove = []
            
            for key, cached_item in self.cache.items():
                # Check if this entry matches the pattern
                if cached_item['query_type'] in query_types:
                    # If user_id specified, only invalidate for that user
                    if user_id is None or cached_item['user_id'] == str(user_id):
                        keys_to_remove.append(key)
            
            # Remove matched entries
            for key in keys_to_remove:
                del self.cache[key]
                self.invalidation_count += 1
            
            logger.info(f"Invalidated {len(keys_to_remove)} cache entries for pattern '{pattern}'")
            return len(keys_to_remove)
    
    def invalidate_user_cache(self, user_id: ObjectId) -> int:
        """
        Invalidate all cached results for a specific user.
        
        Args:
            user_id: User's ObjectId
            
        Returns:
            Number of cache entries removed
        """
        with self._lock:
            user_id_str = str(user_id)
            keys_to_remove = [
                key for key, cached_item in self.cache.items()
                if cached_item['user_id'] == user_id_str
            ]
            
            for key in keys_to_remove:
                del self.cache[key]
                self.invalidation_count += 1
            
            logger.info(f"Invalidated {len(keys_to_remove)} cache entries for user {user_id}")
            return len(keys_to_remove)
    
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
    
    def clear_expired(self) -> int:
        """
        Remove all expired cache entries.
        
        Returns:
            Number of expired entries removed
        """
        with self._lock:
            now = datetime.utcnow()
            expired_keys = [
                key for key, value in self.cache.items()
                if now >= value['expires_at']
            ]
            
            for key in expired_keys:
                del self.cache[key]
            
            logger.debug(f"Cleared {len(expired_keys)} expired cache entries")
            return len(expired_keys)
    
    def get_comprehensive_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics and analytics.
        
        Returns:
            Dict containing detailed cache statistics
        """
        with self._lock:
            now = datetime.utcnow()
            
            # Basic counts
            active_entries = sum(
                1 for value in self.cache.values()
                if now < value['expires_at']
            )
            
            # Calculate hit rate
            total_requests = self.hit_count + self.miss_count
            hit_rate = (self.hit_count / total_requests * 100) if total_requests > 0 else 0
            
            # Memory usage estimation
            total_data_size = sum(
                item['data_size_bytes'] for item in self.cache.values()
            )
            
            # Query type distribution
            query_type_counts = defaultdict(int)
            for item in self.cache.values():
                query_type_counts[item['query_type']] += 1
            
            # TTL distribution
            ttl_distribution = defaultdict(int)
            for item in self.cache.values():
                ttl_bucket = f"{item['ttl_seconds']}s"
                ttl_distribution[ttl_bucket] += 1
            
            return {
                'basic_stats': {
                    'total_entries': len(self.cache),
                    'active_entries': active_entries,
                    'expired_entries': len(self.cache) - active_entries,
                    'max_cache_size': self.max_cache_size,
                    'cache_utilization_percent': round((len(self.cache) / self.max_cache_size) * 100, 2)
                },
                'performance_metrics': {
                    'hit_count': self.hit_count,
                    'miss_count': self.miss_count,
                    'eviction_count': self.eviction_count,
                    'invalidation_count': self.invalidation_count,
                    'hit_rate_percentage': round(hit_rate, 2)
                },
                'memory_usage': {
                    'total_data_size_bytes': total_data_size,
                    'total_data_size_mb': round(total_data_size / (1024 * 1024), 2),
                    'average_entry_size_bytes': round(total_data_size / len(self.cache), 2) if self.cache else 0
                },
                'distribution_analysis': {
                    'query_types': dict(query_type_counts),
                    'ttl_distribution': dict(ttl_distribution)
                },
                'configuration': {
                    'default_ttl_seconds': self.default_ttl,
                    'max_cache_size': self.max_cache_size
                },
                'timestamp': now.isoformat() + 'Z'
            }


# Global enhanced cache instance
enhanced_cache = EnhancedCacheService(default_ttl_seconds=300, max_cache_size=2000)