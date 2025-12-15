"""
Rate Limit Monitoring Blueprint - Admin endpoints for monitoring API usage
"""
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta

def init_rate_limit_monitoring_blueprint(mongo, token_required, admin_required, rate_limit_tracker):
    rate_limit_bp = Blueprint('rate_limit_monitoring', __name__, url_prefix='/admin/rate-limits')
    
    @rate_limit_bp.route('/overview', methods=['GET'])
    @token_required
    @admin_required
    def get_rate_limit_overview(current_user):
        """Get overview of API usage and rate limiting"""
        try:
            hours = int(request.args.get('hours', 1))
            
            overview = rate_limit_tracker.get_overview_stats(hours=hours)
            
            return jsonify({
                'success': True,
                'data': {
                    'overview': overview,
                    'timeframe': f'Last {hours} hour(s)',
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'Rate limit overview retrieved successfully'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get rate limit overview',
                'errors': {'general': [str(e)]}
            }), 500
    
    @rate_limit_bp.route('/heavy-users', methods=['GET'])
    @token_required
    @admin_required
    def get_heavy_users(current_user):
        """Get users making excessive API calls"""
        try:
            hours = int(request.args.get('hours', 1))
            min_calls = int(request.args.get('min_calls', 100))
            
            heavy_users = rate_limit_tracker.get_heavy_users(hours=hours, min_calls=min_calls)
            
            return jsonify({
                'success': True,
                'data': {
                    'heavyUsers': heavy_users,
                    'count': len(heavy_users),
                    'timeframe': f'Last {hours} hour(s)',
                    'threshold': f'{min_calls} calls',
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                },
                'message': f'Found {len(heavy_users)} heavy users'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get heavy users',
                'errors': {'general': [str(e)]}
            }), 500
    
    @rate_limit_bp.route('/endpoint-stats', methods=['GET'])
    @token_required
    @admin_required
    def get_endpoint_stats(current_user):
        """Get statistics per endpoint"""
        try:
            hours = int(request.args.get('hours', 1))
            
            endpoint_stats = rate_limit_tracker.get_endpoint_stats(hours=hours)
            
            return jsonify({
                'success': True,
                'data': {
                    'endpoints': endpoint_stats,
                    'count': len(endpoint_stats),
                    'timeframe': f'Last {hours} hour(s)',
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'Endpoint statistics retrieved successfully'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get endpoint statistics',
                'errors': {'general': [str(e)]}
            }), 500
    
    @rate_limit_bp.route('/violations', methods=['GET'])
    @token_required
    @admin_required
    def get_rate_limit_violations(current_user):
        """Get users who hit rate limits (429 errors)"""
        try:
            hours = int(request.args.get('hours', 1))
            
            violations = rate_limit_tracker.get_rate_limit_violations(hours=hours)
            
            return jsonify({
                'success': True,
                'data': {
                    'violations': violations,
                    'count': len(violations),
                    'timeframe': f'Last {hours} hour(s)',
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                },
                'message': f'Found {len(violations)} rate limit violations'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get rate limit violations',
                'errors': {'general': [str(e)]}
            }), 500
    
    @rate_limit_bp.route('/user/<user_id>', methods=['GET'])
    @token_required
    @admin_required
    def get_user_api_usage(current_user, user_id):
        """Get detailed API usage for a specific user"""
        try:
            from bson import ObjectId
            
            hours = int(request.args.get('hours', 1))
            
            # Convert user_id to ObjectId
            try:
                user_obj_id = ObjectId(user_id)
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid user ID format'
                }), 400
            
            # Get user details
            user = mongo.db.users.find_one({'_id': user_obj_id})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get endpoint breakdown
            breakdown = rate_limit_tracker.get_user_endpoint_breakdown(user_obj_id, hours=hours)
            
            # Calculate totals
            total_calls = sum(item['count'] for item in breakdown)
            
            return jsonify({
                'success': True,
                'data': {
                    'user': {
                        'id': str(user['_id']),
                        'email': user.get('email', 'Unknown'),
                        'displayName': user.get('displayName', 'Unknown'),
                        'isSubscribed': user.get('isSubscribed', False)
                    },
                    'totalCalls': total_calls,
                    'callsPerMinute': round(total_calls / (hours * 60), 2),
                    'endpointBreakdown': breakdown,
                    'timeframe': f'Last {hours} hour(s)',
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'User API usage retrieved successfully'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get user API usage',
                'errors': {'general': [str(e)]}
            }), 500
    
    @rate_limit_bp.route('/cleanup', methods=['POST'])
    @token_required
    @admin_required
    def cleanup_old_logs(current_user):
        """Clean up old API call logs"""
        try:
            days = int(request.args.get('days', 7))
            
            deleted_count = rate_limit_tracker.cleanup_old_logs(days=days)
            
            return jsonify({
                'success': True,
                'data': {
                    'deletedCount': deleted_count,
                    'daysKept': days
                },
                'message': f'Cleaned up {deleted_count} old log entries'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to cleanup old logs',
                'errors': {'general': [str(e)]}
            }), 500
    
    return rate_limit_bp
