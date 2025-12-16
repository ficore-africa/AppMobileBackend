"""
Performance monitoring and logging service for financial aggregation operations.
Tracks query performance, cache efficiency, and system metrics.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from bson import ObjectId
import logging
import time
import threading
from collections import defaultdict, deque
import json

logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """
    Container for performance metrics with statistical calculations.
    """
    
    def __init__(self, max_samples: int = 1000):
        """
        Initialize performance metrics container.
        
        Args:
            max_samples: Maximum number of samples to keep for calculations
        """
        self.max_samples = max_samples
        self.samples = deque(maxlen=max_samples)
        self.total_count = 0
        
    def add_sample(self, value: float, timestamp: Optional[datetime] = None):
        """
        Add a performance sample.
        
        Args:
            value: Performance value (e.g., execution time in ms)
            timestamp: Optional timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
            
        self.samples.append({
            'value': value,
            'timestamp': timestamp
        })
        self.total_count += 1
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Calculate performance statistics from samples.
        
        Returns:
            Dict containing statistical metrics
        """
        if not self.samples:
            return {
                'count': 0,
                'average': 0,
                'min': 0,
                'max': 0,
                'median': 0,
                'p95': 0,
                'p99': 0
            }
        
        values = [sample['value'] for sample in self.samples]
        values.sort()
        
        count = len(values)
        average = sum(values) / count
        minimum = min(values)
        maximum = max(values)
        
        # Calculate percentiles
        median_idx = count // 2
        median = values[median_idx] if count % 2 == 1 else (values[median_idx - 1] + values[median_idx]) / 2
        
        p95_idx = int(count * 0.95)
        p95 = values[min(p95_idx, count - 1)]
        
        p99_idx = int(count * 0.99)
        p99 = values[min(p99_idx, count - 1)]
        
        return {
            'count': count,
            'total_count': self.total_count,
            'average': round(average, 2),
            'min': minimum,
            'max': maximum,
            'median': median,
            'p95': p95,
            'p99': p99
        }


class PerformanceMonitor:
    """
    Comprehensive performance monitoring service for financial aggregation operations.
    Tracks execution times, cache performance, and system health metrics.
    """
    
    def __init__(self):
        """
        Initialize performance monitor.
        """
        # Query performance metrics by type
        self.query_metrics = {
            'monthly_totals': PerformanceMetrics(),
            'ytd_counts': PerformanceMetrics(),
            'all_time_counts': PerformanceMetrics(),
            'refresh_aggregations': PerformanceMetrics()
        }
        
        # Cache performance metrics
        self.cache_metrics = {
            'hit_rate': PerformanceMetrics(),
            'miss_rate': PerformanceMetrics(),
            'eviction_rate': PerformanceMetrics()
        }
        
        # System performance metrics
        self.system_metrics = {
            'concurrent_requests': PerformanceMetrics(),
            'error_rate': PerformanceMetrics(),
            'response_size': PerformanceMetrics()
        }
        
        # Performance alerts and thresholds
        self.performance_thresholds = {
            'monthly_totals_max_ms': 2000,    # 2 seconds
            'ytd_counts_max_ms': 5000,        # 5 seconds
            'all_time_counts_max_ms': 10000,  # 10 seconds
            'cache_hit_rate_min': 70,         # 70% minimum hit rate
            'error_rate_max': 5               # 5% maximum error rate
        }
        
        # Alert tracking
        self.alerts = deque(maxlen=100)
        self.alert_counts = defaultdict(int)
        
        # Thread lock for thread-safe operations
        self._lock = threading.RLock()
        
    def record_query_performance(self, query_type: str, execution_time_ms: float, 
                                user_id: Optional[ObjectId] = None, **kwargs):
        """
        Record query performance metrics.
        
        Args:
            query_type: Type of query executed
            execution_time_ms: Execution time in milliseconds
            user_id: Optional user ID for user-specific tracking
            **kwargs: Additional metadata
        """
        with self._lock:
            if query_type in self.query_metrics:
                self.query_metrics[query_type].add_sample(execution_time_ms)
                
                # Check for performance alerts
                threshold_key = f"{query_type}_max_ms"
                if threshold_key in self.performance_thresholds:
                    threshold = self.performance_thresholds[threshold_key]
                    if execution_time_ms > threshold:
                        self._create_alert(
                            'performance_threshold_exceeded',
                            f"{query_type} execution time {execution_time_ms}ms exceeded threshold {threshold}ms",
                            {
                                'query_type': query_type,
                                'execution_time_ms': execution_time_ms,
                                'threshold_ms': threshold,
                                'user_id': str(user_id) if user_id else None,
                                **kwargs
                            }
                        )
                
                logger.debug(f"Recorded {query_type} performance: {execution_time_ms}ms")
    
    def record_cache_performance(self, hit_count: int, miss_count: int, eviction_count: int):
        """
        Record cache performance metrics.
        
        Args:
            hit_count: Number of cache hits
            miss_count: Number of cache misses
            eviction_count: Number of cache evictions
        """
        with self._lock:
            total_requests = hit_count + miss_count
            
            if total_requests > 0:
                hit_rate = (hit_count / total_requests) * 100
                miss_rate = (miss_count / total_requests) * 100
                
                self.cache_metrics['hit_rate'].add_sample(hit_rate)
                self.cache_metrics['miss_rate'].add_sample(miss_rate)
                
                # Check cache hit rate threshold
                min_hit_rate = self.performance_thresholds['cache_hit_rate_min']
                if hit_rate < min_hit_rate:
                    self._create_alert(
                        'cache_hit_rate_low',
                        f"Cache hit rate {hit_rate:.1f}% below threshold {min_hit_rate}%",
                        {
                            'hit_rate': hit_rate,
                            'hit_count': hit_count,
                            'miss_count': miss_count,
                            'threshold': min_hit_rate
                        }
                    )
            
            if eviction_count > 0:
                self.cache_metrics['eviction_rate'].add_sample(eviction_count)
                
            logger.debug(f"Recorded cache performance: {hit_count} hits, {miss_count} misses, {eviction_count} evictions")
    
    def record_system_performance(self, concurrent_requests: int, error_count: int, 
                                 total_requests: int, response_size_bytes: int = 0):
        """
        Record system performance metrics.
        
        Args:
            concurrent_requests: Number of concurrent requests
            error_count: Number of errors
            total_requests: Total number of requests
            response_size_bytes: Response size in bytes
        """
        with self._lock:
            self.system_metrics['concurrent_requests'].add_sample(concurrent_requests)
            
            if response_size_bytes > 0:
                self.system_metrics['response_size'].add_sample(response_size_bytes)
            
            if total_requests > 0:
                error_rate = (error_count / total_requests) * 100
                self.system_metrics['error_rate'].add_sample(error_rate)
                
                # Check error rate threshold
                max_error_rate = self.performance_thresholds['error_rate_max']
                if error_rate > max_error_rate:
                    self._create_alert(
                        'error_rate_high',
                        f"Error rate {error_rate:.1f}% exceeds threshold {max_error_rate}%",
                        {
                            'error_rate': error_rate,
                            'error_count': error_count,
                            'total_requests': total_requests,
                            'threshold': max_error_rate
                        }
                    )
            
            logger.debug(f"Recorded system performance: {concurrent_requests} concurrent, {error_count}/{total_requests} errors")
    
    def _create_alert(self, alert_type: str, message: str, metadata: Dict[str, Any]):
        """
        Create a performance alert.
        
        Args:
            alert_type: Type of alert
            message: Alert message
            metadata: Additional alert metadata
        """
        alert = {
            'type': alert_type,
            'message': message,
            'metadata': metadata,
            'timestamp': datetime.utcnow(),
            'count': self.alert_counts[alert_type] + 1
        }
        
        self.alerts.append(alert)
        self.alert_counts[alert_type] += 1
        
        # Log alert
        logger.warning(f"Performance Alert [{alert_type}]: {message}")
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive performance summary.
        
        Returns:
            Dict containing performance metrics and statistics
        """
        with self._lock:
            # Calculate query performance statistics
            query_stats = {}
            for query_type, metrics in self.query_metrics.items():
                query_stats[query_type] = metrics.get_statistics()
            
            # Calculate cache performance statistics
            cache_stats = {}
            for metric_type, metrics in self.cache_metrics.items():
                cache_stats[metric_type] = metrics.get_statistics()
            
            # Calculate system performance statistics
            system_stats = {}
            for metric_type, metrics in self.system_metrics.items():
                system_stats[metric_type] = metrics.get_statistics()
            
            # Get recent alerts
            recent_alerts = [
                {
                    'type': alert['type'],
                    'message': alert['message'],
                    'timestamp': alert['timestamp'].isoformat() + 'Z',
                    'count': alert['count']
                }
                for alert in list(self.alerts)[-10:]  # Last 10 alerts
            ]
            
            return {
                'query_performance': query_stats,
                'cache_performance': cache_stats,
                'system_performance': system_stats,
                'performance_thresholds': self.performance_thresholds,
                'recent_alerts': recent_alerts,
                'alert_summary': dict(self.alert_counts),
                'summary_generated_at': datetime.utcnow().isoformat() + 'Z'
            }
    
    def get_performance_dashboard_data(self) -> Dict[str, Any]:
        """
        Get performance data formatted for dashboard display.
        
        Returns:
            Dict containing dashboard-ready performance data
        """
        summary = self.get_performance_summary()
        
        # Extract key metrics for dashboard
        dashboard_data = {
            'key_metrics': {
                'avg_monthly_totals_ms': summary['query_performance'].get('monthly_totals', {}).get('average', 0),
                'avg_ytd_counts_ms': summary['query_performance'].get('ytd_counts', {}).get('average', 0),
                'cache_hit_rate': summary['cache_performance'].get('hit_rate', {}).get('average', 0),
                'total_alerts': sum(summary['alert_summary'].values()),
                'active_thresholds': len(self.performance_thresholds)
            },
            'performance_trends': {
                'query_performance_trend': self._calculate_trend('query_performance'),
                'cache_performance_trend': self._calculate_trend('cache_performance'),
                'system_performance_trend': self._calculate_trend('system_performance')
            },
            'health_status': self._calculate_health_status(summary),
            'recommendations': self._generate_recommendations(summary),
            'last_updated': datetime.utcnow().isoformat() + 'Z'
        }
        
        return dashboard_data
    
    def _calculate_trend(self, metric_category: str) -> str:
        """
        Calculate performance trend for a metric category.
        
        Args:
            metric_category: Category of metrics to analyze
            
        Returns:
            Trend description ('improving', 'stable', 'degrading')
        """
        # Simplified trend calculation - in production, this would be more sophisticated
        return 'stable'  # Placeholder implementation
    
    def _calculate_health_status(self, summary: Dict[str, Any]) -> str:
        """
        Calculate overall system health status.
        
        Args:
            summary: Performance summary data
            
        Returns:
            Health status ('healthy', 'warning', 'critical')
        """
        # Check for critical alerts
        critical_alerts = ['performance_threshold_exceeded', 'error_rate_high']
        recent_critical = any(
            alert['type'] in critical_alerts 
            for alert in summary['recent_alerts']
        )
        
        if recent_critical:
            return 'warning'
        
        # Check cache performance
        cache_hit_rate = summary['cache_performance'].get('hit_rate', {}).get('average', 0)
        if cache_hit_rate < self.performance_thresholds['cache_hit_rate_min']:
            return 'warning'
        
        return 'healthy'
    
    def _generate_recommendations(self, summary: Dict[str, Any]) -> List[str]:
        """
        Generate performance improvement recommendations.
        
        Args:
            summary: Performance summary data
            
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        # Check query performance
        monthly_avg = summary['query_performance'].get('monthly_totals', {}).get('average', 0)
        if monthly_avg > 1000:  # > 1 second
            recommendations.append("Consider optimizing monthly totals queries - average execution time is high")
        
        # Check cache performance
        cache_hit_rate = summary['cache_performance'].get('hit_rate', {}).get('average', 0)
        if cache_hit_rate < 80:
            recommendations.append("Cache hit rate is below optimal - consider adjusting cache TTL or warming strategies")
        
        # Check for frequent alerts
        if sum(summary['alert_summary'].values()) > 10:
            recommendations.append("High number of performance alerts - review system configuration and thresholds")
        
        return recommendations


# Global performance monitor instance
performance_monitor = PerformanceMonitor()


class PerformanceLogger:
    """
    Enhanced logging service for performance and operational metrics.
    """
    
    def __init__(self, logger_name: str = 'financial_aggregation_performance'):
        """
        Initialize performance logger.
        
        Args:
            logger_name: Name for the logger instance
        """
        self.logger = logging.getLogger(logger_name)
        self.performance_monitor = performance_monitor
        
    def log_query_execution(self, query_type: str, execution_time_ms: float, 
                           user_id: Optional[ObjectId] = None, result_count: int = 0, 
                           cache_hit: bool = False, **kwargs):
        """
        Log query execution with performance metrics.
        
        Args:
            query_type: Type of query executed
            execution_time_ms: Execution time in milliseconds
            user_id: Optional user ID
            result_count: Number of results returned
            cache_hit: Whether result came from cache
            **kwargs: Additional metadata
        """
        # Record performance metrics
        self.performance_monitor.record_query_performance(
            query_type, execution_time_ms, user_id, **kwargs
        )
        
        # Log execution details
        log_data = {
            'event': 'query_execution',
            'query_type': query_type,
            'execution_time_ms': execution_time_ms,
            'user_id': str(user_id) if user_id else None,
            'result_count': result_count,
            'cache_hit': cache_hit,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            **kwargs
        }
        
        # Choose log level based on performance
        if execution_time_ms > 5000:  # > 5 seconds
            self.logger.warning(f"Slow query execution: {json.dumps(log_data)}")
        elif execution_time_ms > 2000:  # > 2 seconds
            self.logger.info(f"Query execution: {json.dumps(log_data)}")
        else:
            self.logger.debug(f"Query execution: {json.dumps(log_data)}")
    
    def log_cache_operation(self, operation: str, cache_type: str, user_id: Optional[ObjectId] = None, 
                           hit: bool = False, **kwargs):
        """
        Log cache operations.
        
        Args:
            operation: Cache operation ('get', 'set', 'invalidate', 'evict')
            cache_type: Type of cache ('enhanced', 'legacy')
            user_id: Optional user ID
            hit: Whether operation was a cache hit
            **kwargs: Additional metadata
        """
        log_data = {
            'event': 'cache_operation',
            'operation': operation,
            'cache_type': cache_type,
            'user_id': str(user_id) if user_id else None,
            'hit': hit,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            **kwargs
        }
        
        self.logger.debug(f"Cache operation: {json.dumps(log_data)}")
    
    def log_data_consistency_check(self, check_type: str, user_id: ObjectId, 
                                  consistent: bool, details: Dict[str, Any]):
        """
        Log data consistency check results.
        
        Args:
            check_type: Type of consistency check
            user_id: User ID being checked
            consistent: Whether data is consistent
            details: Check details and results
        """
        log_data = {
            'event': 'data_consistency_check',
            'check_type': check_type,
            'user_id': str(user_id),
            'consistent': consistent,
            'details': details,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        
        if not consistent:
            self.logger.warning(f"Data consistency issue: {json.dumps(log_data)}")
        else:
            self.logger.info(f"Data consistency check: {json.dumps(log_data)}")


# Global performance logger instance
performance_logger = PerformanceLogger()