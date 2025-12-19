"""
Analytics Blueprint
Handles usage tracking and admin dashboard metrics.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
from typing import Dict, Any, List


def init_analytics_blueprint(mongo, token_required, admin_required, serialize_doc):
    """Initialize analytics blueprint with dependencies."""
    
    analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')
    
    # ==================== EVENT TRACKING ====================
    
    @analytics_bp.route('/track', methods=['POST'])
    @token_required
    def track_event(current_user):
        """
        Track a user activity event.
        
        Request body:
        {
            "eventType": "user_logged_in",
            "eventDetails": {"amount": 1500, "category": "Salary"}
        }
        
        Note: deviceInfo and IP address are automatically captured server-side.
        Mobile app should NOT send IP address or detailed device info.
        """
        try:
            data = request.get_json()
            
            # Validate required fields
            if not data or 'eventType' not in data:
                return jsonify({
                    'success': False,
                    'message': 'eventType is required'
                }), 400
            
            event_type = data['eventType']
            
            # Validate event type
            valid_event_types = [
                'user_logged_in',
                'user_registered',
                'income_entry_created',
                'income_entry_updated',
                'income_entry_deleted',
                'expense_entry_created',
                'expense_entry_updated',
                'expense_entry_deleted',
                'profile_updated',
                'subscription_started',
                'subscription_cancelled',
                'tax_calculation_performed',
                'tax_module_completed',
                'debtor_created',
                'creditor_created',
                'inventory_item_created',
                'asset_created',
                'dashboard_viewed',
                'report_generated',
            ]
            
            if event_type not in valid_event_types:
                return jsonify({
                    'success': False,
                    'message': f'Invalid eventType. Valid types: {", ".join(valid_event_types)}'
                }), 400
            
            # IMPORTANT: Always capture device info and IP server-side
            # Mobile app should NOT send this data - we extract it from request headers
            device_info = {
                'user_agent': request.headers.get('User-Agent', 'Unknown'),
                'ip_address': request.remote_addr or request.headers.get('X-Forwarded-For', 'Unknown'),
                'platform': request.headers.get('X-Platform', 'Unknown'),  # Optional: app can set this header
                'app_version': request.headers.get('X-App-Version', 'Unknown')  # Optional: app can set this header
            }
            
            # Create event document
            event = {
                'userId': current_user['_id'],
                'eventType': event_type,
                'timestamp': datetime.utcnow(),
                'eventDetails': data.get('eventDetails'),
                'deviceInfo': device_info,  # Always set server-side
                'sessionId': data.get('sessionId'),
                'createdAt': datetime.utcnow()
            }
            
            # Insert event
            result = mongo.db.analytics_events.insert_one(event)
            
            return jsonify({
                'success': True,
                'message': 'Event tracked successfully',
                'data': {
                    'eventId': str(result.inserted_id)
                }
            }), 201
            
        except Exception as e:
            print(f"Error tracking event: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to track event',
                'error': str(e)
            }), 500
    
    # ==================== ADMIN DASHBOARD ENDPOINTS ====================
    
    @analytics_bp.route('/dashboard/overview', methods=['GET'])
    @token_required
    @admin_required
    def get_dashboard_overview(current_user):
        """
        Get high-level dashboard metrics.
        
        Returns:
        - Total users
        - Active users (today, this week, this month)
        - Total entries (income + expense)
        - Recent activity
        """
        try:
            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=7)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Total users
            total_users = mongo.db.users.count_documents({'role': 'personal'})
            
            # Active users (users who logged in)
            dau = mongo.db.analytics_events.distinct('userId', {
                'eventType': 'user_logged_in',
                'timestamp': {'$gte': today_start}
            })
            
            wau = mongo.db.analytics_events.distinct('userId', {
                'eventType': 'user_logged_in',
                'timestamp': {'$gte': week_start}
            })
            
            mau = mongo.db.analytics_events.distinct('userId', {
                'eventType': 'user_logged_in',
                'timestamp': {'$gte': month_start}
            })
            
            # Total entries
            total_income_entries = mongo.db.incomes.count_documents({})
            total_expense_entries = mongo.db.expenses.count_documents({})
            
            # Entries this month
            income_entries_this_month = mongo.db.incomes.count_documents({
                'dateReceived': {'$gte': month_start}
            })
            expense_entries_this_month = mongo.db.expenses.count_documents({
                'date': {'$gte': month_start}
            })
            
            # Recent activity (last 10 events)
            recent_events = list(mongo.db.analytics_events.find().sort('timestamp', -1).limit(10))
            
            # Serialize recent events
            recent_activity = []
            for event in recent_events:
                user = mongo.db.users.find_one({'_id': event['userId']})
                recent_activity.append({
                    'eventType': event['eventType'],
                    'timestamp': event['timestamp'].isoformat() + 'Z',
                    'userEmail': user.get('email', 'Unknown') if user else 'Unknown',
                    'userName': f"{user.get('firstName', '')} {user.get('lastName', '')}".strip() if user else 'Unknown'
                })
            
            overview = {
                'users': {
                    'total': total_users,
                    'dailyActive': len(dau),
                    'weeklyActive': len(wau),
                    'monthlyActive': len(mau)
                },
                'entries': {
                    'totalIncome': total_income_entries,
                    'totalExpense': total_expense_entries,
                    'incomeThisMonth': income_entries_this_month,
                    'expenseThisMonth': expense_entries_this_month
                },
                'recentActivity': recent_activity
            }
            
            return jsonify({
                'success': True,
                'data': overview
            }), 200
            
        except Exception as e:
            print(f"Error getting dashboard overview: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get dashboard overview',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/dashboard/event-counts', methods=['GET'])
    @token_required
    @admin_required
    def get_event_counts(current_user):
        """
        Get event counts by type for a given period.
        
        Query params:
        - period: 'today', 'week', 'month', 'all' (default: 'month')
        """
        try:
            period = request.args.get('period', 'month')
            
            now = datetime.utcnow()
            
            # Determine time range
            if period == 'today':
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif period == 'week':
                start_date = now - timedelta(days=7)
            elif period == 'month':
                start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            else:  # 'all'
                start_date = datetime(2020, 1, 1)  # Far past date
            
            # Aggregate events by type
            pipeline = [
                {'$match': {'timestamp': {'$gte': start_date}}},
                {'$group': {
                    '_id': '$eventType',
                    'count': {'$sum': 1}
                }},
                {'$sort': {'count': -1}}
            ]
            
            results = list(mongo.db.analytics_events.aggregate(pipeline))
            
            event_counts = {
                result['_id']: result['count']
                for result in results
            }
            
            return jsonify({
                'success': True,
                'data': {
                    'period': period,
                    'eventCounts': event_counts
                }
            }), 200
            
        except Exception as e:
            print(f"Error getting event counts: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get event counts',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/dashboard/user-growth', methods=['GET'])
    @token_required
    @admin_required
    def get_user_growth(current_user):
        """
        Get user registration growth over time.
        
        Returns daily user registrations for the last 30 days.
        """
        try:
            now = datetime.utcnow()
            thirty_days_ago = now - timedelta(days=30)
            
            # Aggregate user registrations by day
            pipeline = [
                {'$match': {
                    'createdAt': {'$gte': thirty_days_ago},
                    'role': 'personal'
                }},
                {'$group': {
                    '_id': {
                        '$dateToString': {
                            'format': '%Y-%m-%d',
                            'date': '$createdAt'
                        }
                    },
                    'count': {'$sum': 1}
                }},
                {'$sort': {'_id': 1}}
            ]
            
            results = list(mongo.db.users.aggregate(pipeline))
            
            growth_data = [
                {
                    'date': result['_id'],
                    'newUsers': result['count']
                }
                for result in results
            ]
            
            return jsonify({
                'success': True,
                'data': {
                    'growthData': growth_data
                }
            }), 200
            
        except Exception as e:
            print(f"Error getting user growth: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get user growth',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/dashboard/mau-trend', methods=['GET'])
    @token_required
    @admin_required
    def get_mau_trend(current_user):
        """
        Get Monthly Active Users trend for the last 12 months.
        """
        try:
            now = datetime.utcnow()
            mau_data = []
            
            for i in range(12):
                # Calculate month boundaries
                month_date = now - timedelta(days=30 * i)
                month_start = month_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                # Calculate next month start
                if month_start.month == 12:
                    month_end = month_start.replace(year=month_start.year + 1, month=1)
                else:
                    month_end = month_start.replace(month=month_start.month + 1)
                
                # Count unique users who logged in during this month
                unique_users = mongo.db.analytics_events.distinct('userId', {
                    'eventType': 'user_logged_in',
                    'timestamp': {
                        '$gte': month_start,
                        '$lt': month_end
                    }
                })
                
                mau_data.insert(0, {
                    'month': month_start.strftime('%Y-%m'),
                    'mau': len(unique_users)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'mauTrend': mau_data
                }
            }), 200
            
        except Exception as e:
            print(f"Error getting MAU trend: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get MAU trend',
                'error': str(e)
            }), 500
    
    # ==================== USER DATA RIGHTS (NDPR COMPLIANCE) ====================
    
    @analytics_bp.route('/user-data', methods=['GET'])
    @token_required
    def get_user_analytics_data(current_user):
        """
        Get all analytics data for the current user (NDPR Right to Access).
        
        Returns all analytics events collected about the user.
        """
        try:
            # Get all events for the user
            events = list(mongo.db.analytics_events.find({'userId': current_user['_id']}))
            
            # Serialize events
            user_events = []
            for event in events:
                event_data = {
                    'eventId': str(event['_id']),
                    'eventType': event['eventType'],
                    'timestamp': event['timestamp'].isoformat() + 'Z',
                    'eventDetails': event.get('eventDetails'),
                    'deviceInfo': event.get('deviceInfo'),
                    'createdAt': event['createdAt'].isoformat() + 'Z'
                }
                user_events.append(event_data)
            
            # Get summary statistics
            total_events = len(user_events)
            event_types = {}
            for event in user_events:
                event_type = event['eventType']
                event_types[event_type] = event_types.get(event_type, 0) + 1
            
            return jsonify({
                'success': True,
                'data': {
                    'userId': str(current_user['_id']),
                    'userEmail': current_user.get('email'),
                    'totalEvents': total_events,
                    'eventTypes': event_types,
                    'events': user_events,
                    'dataRetentionPeriod': '12 months',
                    'exportedAt': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'User analytics data retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f"Error getting user analytics data: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve user analytics data',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/user-data', methods=['DELETE'])
    @token_required
    def delete_user_analytics_data(current_user):
        """
        Delete all analytics data for the current user (NDPR Right to Erasure).
        
        Permanently deletes all analytics events for the user.
        """
        try:
            # Delete all events for the user
            result = mongo.db.analytics_events.delete_many({'userId': current_user['_id']})
            
            deleted_count = result.deleted_count
            
            # Log the deletion for audit purposes
            print(f"User {current_user['email']} (ID: {current_user['_id']}) deleted {deleted_count} analytics events")
            
            return jsonify({
                'success': True,
                'data': {
                    'deletedEvents': deleted_count,
                    'deletedAt': datetime.utcnow().isoformat() + 'Z'
                },
                'message': f'Successfully deleted {deleted_count} analytics events'
            }), 200
            
        except Exception as e:
            print(f"Error deleting user analytics data: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to delete user analytics data',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/user-data/export', methods=['GET'])
    @token_required
    def export_user_analytics_data(current_user):
        """
        Export all analytics data for the current user in JSON format (NDPR Data Portability).
        
        Returns a downloadable JSON file with all user analytics data.
        """
        try:
            # Get all events for the user
            events = list(mongo.db.analytics_events.find({'userId': current_user['_id']}))
            
            # Serialize events
            user_events = []
            for event in events:
                event_data = {
                    'eventId': str(event['_id']),
                    'eventType': event['eventType'],
                    'timestamp': event['timestamp'].isoformat() + 'Z',
                    'eventDetails': event.get('eventDetails'),
                    'deviceInfo': event.get('deviceInfo'),
                    'createdAt': event['createdAt'].isoformat() + 'Z'
                }
                user_events.append(event_data)
            
            # Create export package
            export_data = {
                'exportInfo': {
                    'userId': str(current_user['_id']),
                    'userEmail': current_user.get('email'),
                    'exportedAt': datetime.utcnow().isoformat() + 'Z',
                    'dataType': 'Analytics Events',
                    'format': 'JSON',
                    'totalEvents': len(user_events)
                },
                'events': user_events,
                'metadata': {
                    'dataRetentionPeriod': '12 months',
                    'privacyPolicy': 'https://ficore.com/privacy-policy',
                    'contact': 'privacy@ficore.com'
                }
            }
            
            return jsonify({
                'success': True,
                'data': export_data,
                'message': 'Analytics data exported successfully'
            }), 200
            
        except Exception as e:
            print(f"Error exporting user analytics data: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to export user analytics data',
                'error': str(e)
            }), 500
    
    # ==================== ADMIN ANALYTICS MANAGEMENT ====================
    
    @analytics_bp.route('/admin/all-users-data', methods=['GET'])
    @token_required
    @admin_required
    def get_all_users_analytics_data(current_user):
        """
        Admin: Get analytics data for all users with filtering.
        
        Query params:
        - user_id: Filter by specific user (optional)
        - event_type: Filter by event type (optional)
        - start_date: Filter from date (optional)
        - end_date: Filter to date (optional)
        - limit: Number of events to return (default: 100)
        - offset: Pagination offset (default: 0)
        """
        try:
            # Get query parameters
            user_id = request.args.get('user_id')
            event_type = request.args.get('event_type')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            limit = min(int(request.args.get('limit', 100)), 1000)
            offset = int(request.args.get('offset', 0))
            
            # Build query
            query = {}
            
            if user_id:
                try:
                    query['userId'] = ObjectId(user_id)
                except:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid user_id format'
                    }), 400
            
            if event_type:
                query['eventType'] = event_type
            
            if start_date or end_date:
                date_query = {}
                if start_date:
                    date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    date_query['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))
                query['timestamp'] = date_query
            
            # Get total count
            total = mongo.db.analytics_events.count_documents(query)
            
            # Get events
            events = list(mongo.db.analytics_events.find(query)
                         .sort('timestamp', -1)
                         .skip(offset)
                         .limit(limit))
            
            # Enrich with user information
            enriched_events = []
            for event in events:
                user = mongo.db.users.find_one({'_id': event['userId']})
                enriched_events.append({
                    'eventId': str(event['_id']),
                    'userId': str(event['userId']),
                    'userEmail': user.get('email', 'Unknown') if user else 'Unknown',
                    'userName': f"{user.get('firstName', '')} {user.get('lastName', '')}".strip() if user else 'Unknown',
                    'eventType': event['eventType'],
                    'timestamp': event['timestamp'].isoformat() + 'Z',
                    'eventDetails': event.get('eventDetails'),
                    'deviceInfo': event.get('deviceInfo'),
                    'createdAt': event['createdAt'].isoformat() + 'Z'
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'events': enriched_events,
                    'pagination': {
                        'total': total,
                        'limit': limit,
                        'offset': offset,
                        'hasMore': offset + limit < total
                    }
                },
                'message': 'Analytics data retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f"Error getting all users analytics data: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve analytics data',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/admin/user/<user_id>/data', methods=['GET'])
    @token_required
    @admin_required
    def get_specific_user_analytics_data(current_user, user_id):
        """
        Admin: Get all analytics data for a specific user.
        
        Returns complete analytics profile for the user.
        """
        try:
            # Validate user_id
            try:
                user_object_id = ObjectId(user_id)
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid user_id format'
                }), 400
            
            # Get user info
            user = mongo.db.users.find_one({'_id': user_object_id})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404
            
            # Get all events for the user
            events = list(mongo.db.analytics_events.find({'userId': user_object_id}))
            
            # Serialize events
            user_events = []
            event_types = {}
            for event in events:
                event_data = {
                    'eventId': str(event['_id']),
                    'eventType': event['eventType'],
                    'timestamp': event['timestamp'].isoformat() + 'Z',
                    'eventDetails': event.get('eventDetails'),
                    'deviceInfo': event.get('deviceInfo'),
                    'createdAt': event['createdAt'].isoformat() + 'Z'
                }
                user_events.append(event_data)
                
                # Count event types
                event_type = event['eventType']
                event_types[event_type] = event_types.get(event_type, 0) + 1
            
            # Get first and last activity
            first_activity = events[0]['timestamp'] if events else None
            last_activity = events[-1]['timestamp'] if events else None
            
            return jsonify({
                'success': True,
                'data': {
                    'user': {
                        'userId': str(user['_id']),
                        'email': user.get('email'),
                        'name': f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(),
                        'createdAt': user.get('createdAt').isoformat() + 'Z' if user.get('createdAt') else None
                    },
                    'analytics': {
                        'totalEvents': len(user_events),
                        'eventTypes': event_types,
                        'firstActivity': first_activity.isoformat() + 'Z' if first_activity else None,
                        'lastActivity': last_activity.isoformat() + 'Z' if last_activity else None,
                        'events': user_events
                    },
                    'dataRetentionPeriod': '12 months'
                },
                'message': 'User analytics data retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f"Error getting user analytics data: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve user analytics data',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/admin/user/<user_id>/data', methods=['DELETE'])
    @token_required
    @admin_required
    def admin_delete_user_analytics_data(current_user, user_id):
        """
        Admin: Delete all analytics data for a specific user.
        
        Used for NDPR compliance when user requests deletion.
        """
        try:
            # Validate user_id
            try:
                user_object_id = ObjectId(user_id)
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid user_id format'
                }), 400
            
            # Get user info for logging
            user = mongo.db.users.find_one({'_id': user_object_id})
            user_email = user.get('email', 'Unknown') if user else 'Unknown'
            
            # Delete all events for the user
            result = mongo.db.analytics_events.delete_many({'userId': user_object_id})
            
            deleted_count = result.deleted_count
            
            # Log the deletion for audit purposes
            print(f"Admin {current_user['email']} deleted {deleted_count} analytics events for user {user_email} (ID: {user_id})")
            
            return jsonify({
                'success': True,
                'data': {
                    'userId': user_id,
                    'userEmail': user_email,
                    'deletedEvents': deleted_count,
                    'deletedAt': datetime.utcnow().isoformat() + 'Z',
                    'deletedBy': current_user.get('email')
                },
                'message': f'Successfully deleted {deleted_count} analytics events for user'
            }), 200
            
        except Exception as e:
            print(f"Error deleting user analytics data: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to delete user analytics data',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/admin/stats', methods=['GET'])
    @token_required
    @admin_required
    def get_admin_analytics_stats(current_user):
        """
        Admin: Get comprehensive analytics statistics.
        
        Returns system-wide analytics metrics.
        """
        try:
            # Total events
            total_events = mongo.db.analytics_events.count_documents({})
            
            # Events by type
            event_type_pipeline = [
                {'$group': {
                    '_id': '$eventType',
                    'count': {'$sum': 1}
                }},
                {'$sort': {'count': -1}}
            ]
            event_types = list(mongo.db.analytics_events.aggregate(event_type_pipeline))
            event_type_counts = {item['_id']: item['count'] for item in event_types}
            
            # Unique users with events
            unique_users = len(mongo.db.analytics_events.distinct('userId'))
            
            # Events per user average
            avg_events_per_user = total_events / unique_users if unique_users > 0 else 0
            
            # Date range
            oldest_event = mongo.db.analytics_events.find_one(sort=[('timestamp', 1)])
            newest_event = mongo.db.analytics_events.find_one(sort=[('timestamp', -1)])
            
            # Storage size (approximate)
            collection_stats = mongo.db.command('collStats', 'analytics_events')
            storage_size_mb = collection_stats.get('size', 0) / (1024 * 1024)
            
            # Events in last 24 hours
            yesterday = datetime.utcnow() - timedelta(days=1)
            events_last_24h = mongo.db.analytics_events.count_documents({
                'timestamp': {'$gte': yesterday}
            })
            
            # Events in last 7 days
            last_week = datetime.utcnow() - timedelta(days=7)
            events_last_7d = mongo.db.analytics_events.count_documents({
                'timestamp': {'$gte': last_week}
            })
            
            # Events in last 30 days
            last_month = datetime.utcnow() - timedelta(days=30)
            events_last_30d = mongo.db.analytics_events.count_documents({
                'timestamp': {'$gte': last_month}
            })
            
            return jsonify({
                'success': True,
                'data': {
                    'overview': {
                        'totalEvents': total_events,
                        'uniqueUsers': unique_users,
                        'avgEventsPerUser': round(avg_events_per_user, 2),
                        'storageSizeMB': round(storage_size_mb, 2)
                    },
                    'timeRanges': {
                        'last24Hours': events_last_24h,
                        'last7Days': events_last_7d,
                        'last30Days': events_last_30d
                    },
                    'eventTypes': event_type_counts,
                    'dateRange': {
                        'oldest': oldest_event['timestamp'].isoformat() + 'Z' if oldest_event else None,
                        'newest': newest_event['timestamp'].isoformat() + 'Z' if newest_event else None
                    },
                    'dataRetention': {
                        'policy': '12 months',
                        'autoCleanup': 'Enabled'
                    }
                },
                'message': 'Analytics statistics retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f"Error getting analytics stats: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve analytics statistics',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/admin/ndpr-requests', methods=['GET'])
    @token_required
    @admin_required
    def get_ndpr_requests(current_user):
        """
        Admin: Get summary of NDPR-related requests.
        
        Shows users who have accessed, deleted, or exported their data.
        """
        try:
            # This would track NDPR requests if we implement a requests log
            # For now, return a summary based on current data
            
            total_users = mongo.db.users.count_documents({'role': 'personal'})
            users_with_analytics = len(mongo.db.analytics_events.distinct('userId'))
            users_without_analytics = total_users - users_with_analytics
            
            return jsonify({
                'success': True,
                'data': {
                    'summary': {
                        'totalUsers': total_users,
                        'usersWithAnalytics': users_with_analytics,
                        'usersWithoutAnalytics': users_without_analytics
                    },
                    'note': 'Implement NDPR request logging for detailed tracking'
                },
                'message': 'NDPR requests summary retrieved'
            }), 200
            
        except Exception as e:
            print(f"Error getting NDPR requests: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve NDPR requests',
                'error': str(e)
            }), 500
    
    # ==================== PHASE 4: ACTIVATION EVENT TRACKING ====================
    
    @analytics_bp.route('/activation/track', methods=['POST'])
    @token_required
    def track_activation_event(current_user):
        """
        Track activation event from mobile app (Phase 4).
        
        Request body:
        {
            "eventType": "shown" | "dismissed" | "state_transition",
            "activationState": "S0" | "S1" | "S2" | "S3",
            "nudgeType": "noEntryYet" | "firstEntryDone" | "earlyStreak" | "sevenDayStreak",
            "streakCount": 0,
            "occurredAt": "2025-12-19T10:30:00Z",
            "timezoneOffset": -300
        }
        """
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['eventType', 'activationState', 'streakCount', 'occurredAt', 'timezoneOffset']
            for field in required_fields:
                if field not in data:
                    return jsonify({
                        'success': False,
                        'message': f'Missing required field: {field}'
                    }), 400
            
            # Validate event type
            valid_event_types = ['shown', 'dismissed', 'state_transition']
            if data['eventType'] not in valid_event_types:
                return jsonify({
                    'success': False,
                    'message': f'Invalid eventType. Must be one of: {", ".join(valid_event_types)}'
                }), 400
            
            # Validate activation state
            valid_states = ['S0', 'S1', 'S2', 'S3']
            if data['activationState'] not in valid_states:
                return jsonify({
                    'success': False,
                    'message': f'Invalid activationState. Must be one of: {", ".join(valid_states)}'
                }), 400
            
            # Validate nudge type if provided
            if data.get('nudgeType'):
                valid_nudge_types = ['noEntryYet', 'firstEntryDone', 'earlyStreak', 'sevenDayStreak']
                if data['nudgeType'] not in valid_nudge_types:
                    return jsonify({
                        'success': False,
                        'message': f'Invalid nudgeType. Must be one of: {", ".join(valid_nudge_types)}'
                    }), 400
            
            # Parse occurred_at timestamp
            try:
                occurred_at = datetime.fromisoformat(data['occurredAt'].replace('Z', ''))
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid occurredAt timestamp format. Use ISO 8601 format.'
                }), 400
            
            # Create activation event document
            activation_event = {
                'userId': current_user['_id'],
                'eventType': data['eventType'],
                'activationState': data['activationState'],
                'nudgeType': data.get('nudgeType'),
                'streakCount': int(data['streakCount']),
                'occurredAt': occurred_at,
                'timezoneOffset': int(data['timezoneOffset']),
                'createdAt': datetime.utcnow()
            }
            
            # Insert event (fire-and-forget, no blocking)
            result = mongo.db.activation_events.insert_one(activation_event)
            
            return jsonify({
                'success': True,
                'message': 'Activation event tracked successfully',
                'data': {
                    'eventId': str(result.inserted_id)
                }
            }), 201
            
        except Exception as e:
            print(f"Error tracking activation event: {str(e)}")
            # Don't fail hard - this is fire-and-forget
            return jsonify({
                'success': False,
                'message': 'Failed to track activation event',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/dashboard/top-users', methods=['GET'])
    @token_required
    @admin_required
    def get_top_users(current_user):
        """
        Get most active users based on event count.
        
        Query params:
        - limit: number of users to return (default: 10)
        - period: 'week', 'month', 'all' (default: 'month')
        """
        try:
            limit = int(request.args.get('limit', 10))
            period = request.args.get('period', 'month')
            
            now = datetime.utcnow()
            
            # Determine time range
            if period == 'week':
                start_date = now - timedelta(days=7)
            elif period == 'month':
                start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            else:  # 'all'
                start_date = datetime(2020, 1, 1)
            
            # Aggregate events by user
            pipeline = [
                {'$match': {'timestamp': {'$gte': start_date}}},
                {'$group': {
                    '_id': '$userId',
                    'eventCount': {'$sum': 1}
                }},
                {'$sort': {'eventCount': -1}},
                {'$limit': limit}
            ]
            
            results = list(mongo.db.analytics_events.aggregate(pipeline))
            
            # Get user details
            top_users = []
            for result in results:
                user = mongo.db.users.find_one({'_id': result['_id']})
                if user:
                    top_users.append({
                        'userId': str(user['_id']),
                        'email': user.get('email'),
                        'name': f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(),
                        'eventCount': result['eventCount']
                    })
            
            return jsonify({
                'success': True,
                'data': {
                    'topUsers': top_users
                }
            }), 200
            
        except Exception as e:
            print(f"Error getting top users: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get top users',
                'error': str(e)
            }), 500
    
    # ==================== PHASE 6: NOTIFICATION ANALYTICS ====================
    
    @analytics_bp.route('/notifications/track', methods=['POST'])
    @token_required
    def track_notification_event(current_user):
        """
        Track notification analytics event (Phase 6).
        
        Fire-and-forget endpoint for tracking notification delivery and engagement.
        
        Request body:
        {
            "eventType": "notification_sent" | "notification_opened" | "notification_dismissed",
            "notificationType": "inactivity" | "weekly_digest" | "activation" | "celebration",
            "notificationId": "unique_notification_id",
            "metadata": {
                "daysSince": 3,
                "income": 5000,
                "expenses": 3000
            },
            "occurredAt": "2025-12-19T10:30:00Z"
        }
        """
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['eventType', 'notificationType', 'notificationId', 'occurredAt']
            for field in required_fields:
                if field not in data:
                    return jsonify({
                        'success': False,
                        'message': f'Missing required field: {field}'
                    }), 400
            
            # Validate event type
            valid_event_types = ['notification_sent', 'notification_opened', 'notification_dismissed']
            if data['eventType'] not in valid_event_types:
                return jsonify({
                    'success': False,
                    'message': f'Invalid eventType. Must be one of: {", ".join(valid_event_types)}'
                }), 400
            
            # Validate notification type
            valid_notification_types = ['inactivity', 'weekly_digest', 'activation', 'celebration']
            if data['notificationType'] not in valid_notification_types:
                return jsonify({
                    'success': False,
                    'message': f'Invalid notificationType. Must be one of: {", ".join(valid_notification_types)}'
                }), 400
            
            # Parse occurred_at timestamp
            try:
                occurred_at = datetime.fromisoformat(data['occurredAt'].replace('Z', ''))
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid occurredAt timestamp format. Use ISO 8601 format.'
                }), 400
            
            # Create notification event document
            notification_event = {
                'userId': current_user['_id'],
                'eventType': data['eventType'],
                'notificationType': data['notificationType'],
                'notificationId': data['notificationId'],
                'metadata': data.get('metadata', {}),
                'occurredAt': occurred_at,
                'createdAt': datetime.utcnow()
            }
            
            # Insert event (fire-and-forget)
            result = mongo.db.notification_events.insert_one(notification_event)
            
            return jsonify({
                'success': True,
                'message': 'Notification event tracked successfully',
                'data': {
                    'eventId': str(result.inserted_id)
                }
            }), 201
            
        except Exception as e:
            print(f"Error tracking notification event: {str(e)}")
            # Don't fail hard - this is fire-and-forget
            return jsonify({
                'success': False,
                'message': 'Failed to track notification event',
                'error': str(e)
            }), 500
    
    @analytics_bp.route('/notifications/stats', methods=['GET'])
    @token_required
    @admin_required
    def get_notification_stats(current_user):
        """
        Admin: Get notification delivery and engagement statistics.
        
        Query params:
        - period: 'week', 'month', 'all' (default: 'month')
        """
        try:
            period = request.args.get('period', 'month')
            
            now = datetime.utcnow()
            
            # Determine time range
            if period == 'week':
                start_date = now - timedelta(days=7)
            elif period == 'month':
                start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            else:  # 'all'
                start_date = datetime(2020, 1, 1)
            
            # Get notification counts by type
            pipeline = [
                {'$match': {'occurredAt': {'$gte': start_date}}},
                {'$group': {
                    '_id': {
                        'notificationType': '$notificationType',
                        'eventType': '$eventType'
                    },
                    'count': {'$sum': 1}
                }}
            ]
            
            results = list(mongo.db.notification_events.aggregate(pipeline))
            
            # Organize stats
            stats = {}
            for result in results:
                notif_type = result['_id']['notificationType']
                event_type = result['_id']['eventType']
                count = result['count']
                
                if notif_type not in stats:
                    stats[notif_type] = {
                        'sent': 0,
                        'opened': 0,
                        'dismissed': 0
                    }
                
                if event_type == 'notification_sent':
                    stats[notif_type]['sent'] = count
                elif event_type == 'notification_opened':
                    stats[notif_type]['opened'] = count
                elif event_type == 'notification_dismissed':
                    stats[notif_type]['dismissed'] = count
            
            # Calculate engagement rates
            for notif_type in stats:
                sent = stats[notif_type]['sent']
                opened = stats[notif_type]['opened']
                
                if sent > 0:
                    stats[notif_type]['openRate'] = round((opened / sent) * 100, 2)
                else:
                    stats[notif_type]['openRate'] = 0
            
            return jsonify({
                'success': True,
                'data': {
                    'period': period,
                    'stats': stats
                }
            }), 200
            
        except Exception as e:
            print(f"Error getting notification stats: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to get notification stats',
                'error': str(e)
            }), 500
    
    return analytics_bp
