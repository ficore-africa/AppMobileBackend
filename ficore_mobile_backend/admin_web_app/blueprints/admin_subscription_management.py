"""
Admin Subscription Management Endpoints
Provides admin visibility into expired users, historical tracking, and statistics
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId


def init_admin_subscription_management_blueprint(mongo, token_required, admin_required, serialize_doc):
    admin_sub_mgmt_bp = Blueprint('admin_subscription_management', __name__, url_prefix='/admin/subscriptions')
    
    @admin_sub_mgmt_bp.route('/expired-users', methods=['GET'])
    @token_required
    @admin_required
    def get_expired_users(current_user):
        """
        Get list of users whose subscriptions have expired.
        Supports filtering by expiration date range.
        """
        try:
            # Get pagination parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            skip = (page - 1) * limit
            
            # Get filter parameters
            days_ago = int(request.args.get('days_ago', 30))  # Default: last 30 days
            cutoff_date = datetime.utcnow() - timedelta(days=days_ago)
            
            # Query for users who were premium but are no longer
            query = {
                'wasPremium': True,
                'isSubscribed': False,
                'lastPremiumDate': {'$gte': cutoff_date}
            }
            
            total = mongo.db.users.count_documents(query)
            
            users = list(mongo.db.users.find(query)
                        .sort('lastPremiumDate', -1)
                        .skip(skip)
                        .limit(limit))
            
            # Format user data
            user_list = []
            for user in users:
                # Get most recent subscription from history
                history = user.get('subscriptionHistory', [])
                last_subscription = history[-1] if history else None
                
                user_data = {
                    'id': str(user['_id']),
                    'email': user.get('email'),
                    'displayName': user.get('displayName'),
                    'lastPremiumDate': user.get('lastPremiumDate').isoformat() + 'Z' if user.get('lastPremiumDate') else None,
                    'totalPremiumDays': user.get('totalPremiumDays', 0),
                    'premiumExpiryCount': user.get('premiumExpiryCount', 0),
                    'ficoreCreditBalance': user.get('ficoreCreditBalance', 0.0),
                    'lastSubscription': {
                        'planType': last_subscription.get('planType') if last_subscription else None,
                        'startDate': last_subscription.get('startDate').isoformat() + 'Z' if last_subscription and last_subscription.get('startDate') else None,
                        'endDate': last_subscription.get('endDate').isoformat() + 'Z' if last_subscription and last_subscription.get('endDate') else None,
                        'terminatedAt': last_subscription.get('terminatedAt').isoformat() + 'Z' if last_subscription and last_subscription.get('terminatedAt') else None,
                        'terminationReason': last_subscription.get('terminationReason') if last_subscription else None,
                        'totalDaysActive': last_subscription.get('totalDaysActive') if last_subscription else 0
                    } if last_subscription else None,
                    'daysSinceExpiry': (datetime.utcnow() - user.get('lastPremiumDate')).days if user.get('lastPremiumDate') else None
                }
                user_list.append(user_data)
            
            return jsonify({
                'success': True,
                'data': {
                    'users': user_list,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit
                    },
                    'filters': {
                        'days_ago': days_ago,
                        'cutoff_date': cutoff_date.isoformat() + 'Z'
                    }
                },
                'message': f'Retrieved {len(user_list)} expired users'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expired users',
                'errors': {'general': [str(e)]}
            }), 500
    
    @admin_sub_mgmt_bp.route('/statistics', methods=['GET'])
    @token_required
    @admin_required
    def get_subscription_statistics(current_user):
        """
        Get comprehensive subscription statistics including expiration metrics.
        """
        try:
            from utils.subscription_expiration_manager import SubscriptionExpirationManager
            
            days = int(request.args.get('days', 30))
            
            expiration_manager = SubscriptionExpirationManager(mongo.db)
            stats = expiration_manager.get_expiration_statistics(days=days)
            
            # Add additional metrics
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Users in grace period
            grace_period_users = expiration_manager.check_grace_period_users()
            stats['grace_period_count'] = len(grace_period_users)
            
            # Expiring soon (next 7 days)
            expiring_soon_date = datetime.utcnow() + timedelta(days=7)
            expiring_soon_count = mongo.db.users.count_documents({
                'isSubscribed': True,
                'subscriptionEndDate': {
                    '$gte': datetime.utcnow(),
                    '$lte': expiring_soon_date
                }
            })
            stats['expiring_soon_count'] = expiring_soon_count
            
            # Average subscription duration
            pipeline = [
                {'$match': {'subscriptionHistory': {'$exists': True, '$ne': []}}},
                {'$unwind': '$subscriptionHistory'},
                {'$group': {
                    '_id': None,
                    'avgDuration': {'$avg': '$subscriptionHistory.totalDaysActive'}
                }}
            ]
            avg_result = list(mongo.db.users.aggregate(pipeline))
            stats['average_subscription_days'] = round(avg_result[0]['avgDuration'], 1) if avg_result else 0
            
            return jsonify({
                'success': True,
                'data': stats,
                'message': 'Subscription statistics retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve subscription statistics',
                'errors': {'general': [str(e)]}
            }), 500
    
    @admin_sub_mgmt_bp.route('/user/<user_id>/history', methods=['GET'])
    @token_required
    @admin_required
    def get_user_subscription_history(current_user, user_id):
        """
        Get complete subscription history for a specific user.
        """
        try:
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            history = user.get('subscriptionHistory', [])
            
            # Format history
            formatted_history = []
            for entry in history:
                formatted_entry = {
                    'planType': entry.get('planType'),
                    'startDate': entry.get('startDate').isoformat() + 'Z' if entry.get('startDate') else None,
                    'endDate': entry.get('endDate').isoformat() + 'Z' if entry.get('endDate') else None,
                    'terminatedAt': entry.get('terminatedAt').isoformat() + 'Z' if entry.get('terminatedAt') else None,
                    'status': entry.get('status'),
                    'terminationReason': entry.get('terminationReason'),
                    'totalDaysActive': entry.get('totalDaysActive', 0),
                    'autoRenew': entry.get('autoRenew', False),
                    'paymentMethod': entry.get('paymentMethod')
                }
                formatted_history.append(formatted_entry)
            
            # Get subscription events
            events = list(mongo.db.subscription_events.find({
                'userId': ObjectId(user_id)
            }).sort('timestamp', -1))
            
            formatted_events = []
            for event in events:
                formatted_event = serialize_doc(event.copy())
                formatted_event['timestamp'] = event.get('timestamp').isoformat() + 'Z' if event.get('timestamp') else None
                formatted_events.append(formatted_event)
            
            return jsonify({
                'success': True,
                'data': {
                    'user': {
                        'id': str(user['_id']),
                        'email': user.get('email'),
                        'displayName': user.get('displayName'),
                        'isSubscribed': user.get('isSubscribed', False),
                        'wasPremium': user.get('wasPremium', False),
                        'lastPremiumDate': user.get('lastPremiumDate').isoformat() + 'Z' if user.get('lastPremiumDate') else None,
                        'totalPremiumDays': user.get('totalPremiumDays', 0),
                        'premiumExpiryCount': user.get('premiumExpiryCount', 0)
                    },
                    'subscriptionHistory': formatted_history,
                    'events': formatted_events
                },
                'message': 'User subscription history retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve user subscription history',
                'errors': {'general': [str(e)]}
            }), 500
    
    @admin_sub_mgmt_bp.route('/notifications', methods=['GET'])
    @token_required
    @admin_required
    def get_subscription_notifications(current_user):
        """
        Get subscription-related notifications with filtering.
        """
        try:
            # Get pagination parameters
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            skip = (page - 1) * limit
            
            # Get filter parameters
            notification_type = request.args.get('type')  # Optional filter by type
            days_ago = int(request.args.get('days_ago', 7))
            cutoff_date = datetime.utcnow() - timedelta(days=days_ago)
            
            # Build query
            query = {
                'sentAt': {'$gte': cutoff_date}
            }
            
            if notification_type:
                query['type'] = notification_type
            
            total = mongo.db.notifications.count_documents(query)
            
            notifications = list(mongo.db.notifications.find(query)
                                .sort('sentAt', -1)
                                .skip(skip)
                                .limit(limit))
            
            # Format notifications
            notification_list = []
            for notif in notifications:
                # Get user info
                user = mongo.db.users.find_one({'_id': notif['userId']})
                
                notif_data = serialize_doc(notif.copy())
                notif_data['sentAt'] = notif.get('sentAt').isoformat() + 'Z' if notif.get('sentAt') else None
                notif_data['readAt'] = notif.get('readAt').isoformat() + 'Z' if notif.get('readAt') else None
                notif_data['user'] = {
                    'email': user.get('email') if user else None,
                    'displayName': user.get('displayName') if user else None
                }
                notification_list.append(notif_data)
            
            return jsonify({
                'success': True,
                'data': {
                    'notifications': notification_list,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit
                    }
                },
                'message': f'Retrieved {len(notification_list)} notifications'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve notifications',
                'errors': {'general': [str(e)]}
            }), 500
    
    @admin_sub_mgmt_bp.route('/process-expirations', methods=['POST'])
    @token_required
    @admin_required
    def manually_process_expirations(current_user):
        """
        Manually trigger expiration processing (for testing or emergency use).
        """
        try:
            from utils.subscription_expiration_manager import SubscriptionExpirationManager
            
            expiration_manager = SubscriptionExpirationManager(mongo.db)
            stats = expiration_manager.process_expired_subscriptions()
            
            return jsonify({
                'success': True,
                'data': stats,
                'message': f'Processed {stats["expired_count"]} expired subscriptions'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to process expirations',
                'errors': {'general': [str(e)]}
            }), 500
    
    @admin_sub_mgmt_bp.route('/scheduler/status', methods=['GET'])
    @admin_required
    def get_scheduler_status(current_user):
        """
        Get subscription scheduler status and next run times.
        """
        try:
            from utils.subscription_scheduler import SubscriptionScheduler
            
            # Try to get the global scheduler instance
            # Note: This assumes the scheduler is stored globally in app.py
            import sys
            scheduler_status = {
                'scheduler_initialized': False,
                'jobs': [],
                'message': 'Scheduler status unavailable - may need to restart app'
            }
            
            # Check if scheduler module is loaded
            if 'utils.subscription_scheduler' in sys.modules:
                scheduler_status['scheduler_initialized'] = True
                scheduler_status['message'] = 'Scheduler module loaded'
            
            return jsonify({
                'success': True,
                'data': scheduler_status,
                'message': 'Scheduler status retrieved'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get scheduler status',
                'errors': {'general': [str(e)]}
            }), 500
    
    return admin_sub_mgmt_bp
