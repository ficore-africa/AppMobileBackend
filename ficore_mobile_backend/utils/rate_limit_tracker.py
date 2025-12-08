"""
Rate Limit Tracker - Monitor API usage patterns and identify heavy users
"""
from datetime import datetime, timedelta
from collections import defaultdict
from flask import request, g
import time

class RateLimitTracker:
    """Track API calls per user/endpoint for monitoring and analytics"""
    
    def __init__(self, mongo):
        self.mongo = mongo
        self.collection = mongo.db.api_call_logs
        
        # Create indexes for efficient querying
        try:
            self.collection.create_index([('userId', 1), ('timestamp', -1)])
            self.collection.create_index([('endpoint', 1), ('timestamp', -1)])
            self.collection.create_index([('timestamp', -1)])
            self.collection.create_index([('userId', 1), ('endpoint', 1), ('timestamp', -1)])
        except Exception as e:
            print(f"Warning: Could not create indexes for rate limit tracking: {e}")
    
    def log_api_call(self, user_id, endpoint, method, status_code, response_time_ms):
        """Log an API call for tracking"""
        try:
            log_entry = {
                'userId': user_id,
                'endpoint': endpoint,
                'method': method,
                'statusCode': status_code,
                'responseTimeMs': response_time_ms,
                'timestamp': datetime.utcnow(),
                'ipAddress': request.remote_addr,
                'userAgent': request.headers.get('User-Agent', 'Unknown')
            }
            
            # Insert asynchronously (don't block the response)
            self.collection.insert_one(log_entry)
        except Exception as e:
            # Don't fail the request if logging fails
            print(f"Error logging API call: {e}")
    
    def get_heavy_users(self, hours=1, min_calls=100):
        """Get users making excessive API calls"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            pipeline = [
                {'$match': {'timestamp': {'$gte': cutoff_time}}},
                {'$group': {
                    '_id': '$userId',
                    'totalCalls': {'$sum': 1},
                    'endpoints': {'$addToSet': '$endpoint'},
                    'lastCall': {'$max': '$timestamp'},
                    'avgResponseTime': {'$avg': '$responseTimeMs'}
                }},
                {'$match': {'totalCalls': {'$gte': min_calls}}},
                {'$sort': {'totalCalls': -1}},
                {'$limit': 50}
            ]
            
            heavy_users = list(self.collection.aggregate(pipeline))
            
            # Enrich with user details
            for user in heavy_users:
                user_doc = self.mongo.db.users.find_one({'_id': user['_id']})
                if user_doc:
                    user['email'] = user_doc.get('email', 'Unknown')
                    user['displayName'] = user_doc.get('displayName', 'Unknown')
                    user['isSubscribed'] = user_doc.get('isSubscribed', False)
                else:
                    user['email'] = 'Unknown'
                    user['displayName'] = 'Unknown'
                    user['isSubscribed'] = False
                
                user['callsPerMinute'] = round(user['totalCalls'] / (hours * 60), 2)
                user['uniqueEndpoints'] = len(user['endpoints'])
            
            return heavy_users
        except Exception as e:
            print(f"Error getting heavy users: {e}")
            return []
    
    def get_endpoint_stats(self, hours=1):
        """Get statistics per endpoint"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            pipeline = [
                {'$match': {'timestamp': {'$gte': cutoff_time}}},
                {'$group': {
                    '_id': '$endpoint',
                    'totalCalls': {'$sum': 1},
                    'uniqueUsers': {'$addToSet': '$userId'},
                    'avgResponseTime': {'$avg': '$responseTimeMs'},
                    'errorCount': {
                        '$sum': {
                            '$cond': [{'$gte': ['$statusCode', 400]}, 1, 0]
                        }
                    }
                }},
                {'$sort': {'totalCalls': -1}},
                {'$limit': 50}
            ]
            
            endpoint_stats = list(self.collection.aggregate(pipeline))
            
            for stat in endpoint_stats:
                stat['endpoint'] = stat['_id']
                stat['uniqueUsers'] = len(stat['uniqueUsers'])
                stat['callsPerMinute'] = round(stat['totalCalls'] / (hours * 60), 2)
                stat['errorRate'] = round((stat['errorCount'] / stat['totalCalls']) * 100, 2) if stat['totalCalls'] > 0 else 0
                stat['avgResponseTime'] = round(stat['avgResponseTime'], 2)
            
            return endpoint_stats
        except Exception as e:
            print(f"Error getting endpoint stats: {e}")
            return []
    
    def get_user_endpoint_breakdown(self, user_id, hours=1):
        """Get detailed breakdown of API calls for a specific user"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            pipeline = [
                {'$match': {
                    'userId': user_id,
                    'timestamp': {'$gte': cutoff_time}
                }},
                {'$group': {
                    '_id': '$endpoint',
                    'count': {'$sum': 1},
                    'avgResponseTime': {'$avg': '$responseTimeMs'},
                    'lastCall': {'$max': '$timestamp'}
                }},
                {'$sort': {'count': -1}}
            ]
            
            breakdown = list(self.collection.aggregate(pipeline))
            
            for item in breakdown:
                item['endpoint'] = item['_id']
                item['avgResponseTime'] = round(item['avgResponseTime'], 2)
            
            return breakdown
        except Exception as e:
            print(f"Error getting user endpoint breakdown: {e}")
            return []
    
    def get_rate_limit_violations(self, hours=1):
        """Get users who hit rate limits (429 status codes)"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            pipeline = [
                {'$match': {
                    'timestamp': {'$gte': cutoff_time},
                    'statusCode': 429
                }},
                {'$group': {
                    '_id': {
                        'userId': '$userId',
                        'endpoint': '$endpoint'
                    },
                    'violationCount': {'$sum': 1},
                    'lastViolation': {'$max': '$timestamp'}
                }},
                {'$sort': {'violationCount': -1}},
                {'$limit': 50}
            ]
            
            violations = list(self.collection.aggregate(pipeline))
            
            # Enrich with user details
            for violation in violations:
                user_id = violation['_id']['userId']
                user_doc = self.mongo.db.users.find_one({'_id': user_id})
                if user_doc:
                    violation['email'] = user_doc.get('email', 'Unknown')
                    violation['displayName'] = user_doc.get('displayName', 'Unknown')
                else:
                    violation['email'] = 'Unknown'
                    violation['displayName'] = 'Unknown'
                
                violation['endpoint'] = violation['_id']['endpoint']
                violation['userId'] = str(user_id)
            
            return violations
        except Exception as e:
            print(f"Error getting rate limit violations: {e}")
            return []
    
    def get_overview_stats(self, hours=1):
        """Get overview statistics"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            total_calls = self.collection.count_documents({'timestamp': {'$gte': cutoff_time}})
            
            unique_users = len(self.collection.distinct('userId', {'timestamp': {'$gte': cutoff_time}}))
            
            rate_limit_hits = self.collection.count_documents({
                'timestamp': {'$gte': cutoff_time},
                'statusCode': 429
            })
            
            error_calls = self.collection.count_documents({
                'timestamp': {'$gte': cutoff_time},
                'statusCode': {'$gte': 400}
            })
            
            # Average response time
            avg_response_pipeline = [
                {'$match': {'timestamp': {'$gte': cutoff_time}}},
                {'$group': {
                    '_id': None,
                    'avgResponseTime': {'$avg': '$responseTimeMs'}
                }}
            ]
            avg_response = list(self.collection.aggregate(avg_response_pipeline))
            avg_response_time = round(avg_response[0]['avgResponseTime'], 2) if avg_response else 0
            
            return {
                'totalCalls': total_calls,
                'uniqueUsers': unique_users,
                'rateLimitHits': rate_limit_hits,
                'errorCalls': error_calls,
                'avgResponseTime': avg_response_time,
                'callsPerMinute': round(total_calls / (hours * 60), 2),
                'errorRate': round((error_calls / total_calls) * 100, 2) if total_calls > 0 else 0,
                'rateLimitRate': round((rate_limit_hits / total_calls) * 100, 2) if total_calls > 0 else 0
            }
        except Exception as e:
            print(f"Error getting overview stats: {e}")
            return {}
    
    def cleanup_old_logs(self, days=7):
        """Clean up logs older than specified days"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days)
            result = self.collection.delete_many({'timestamp': {'$lt': cutoff_time}})
            return result.deleted_count
        except Exception as e:
            print(f"Error cleaning up old logs: {e}")
            return 0
