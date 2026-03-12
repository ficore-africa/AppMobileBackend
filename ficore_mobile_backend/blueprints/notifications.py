"""
from utils.messaging_service import create_user_notification
Notifications Blueprint - Persistent Notification System
Handles server-side notifications that survive app reinstalls
"""
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
from functools import wraps

def init_notifications_blueprint(mongo, token_required, serialize_doc):
    """Initialize the notifications blueprint with database and config"""
    notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')
    
    @notifications_bp.route('/list', methods=['GET'])
    @token_required
    def get_user_notifications(current_user):
        """
        Get all notifications for the current user
        Supports pagination and filtering
        """
        try:
            user_id = str(current_user['_id'])
            
            # Query parameters
            page = int(request.args.get('page', 1))
            limit = min(int(request.args.get('limit', 50)), 100)  # Max 100 per page
            category = request.args.get('category')  # Optional filter
            unread_only = request.args.get('unread_only', 'false').lower() == 'true'
            
            # Build query
            query = {'userId': ObjectId(user_id), 'isArchived': False}
            
            if category:
                query['category'] = category
                
            if unread_only:
                query['isRead'] = False
            
            # Get total count
            total_count = mongo.db.user_notifications.count_documents(query)
            
            # Get notifications with pagination
            skip = (page - 1) * limit
            notifications = list(mongo.db.user_notifications.find(query)
                               .sort('timestamp', -1)  # Newest first
                               .skip(skip)
                               .limit(limit))
            
            # Get unread count
            unread_count = mongo.db.user_notifications.count_documents({
                'userId': ObjectId(user_id),
                'isRead': False,
                'isArchived': False
            })
            
            return jsonify({
                'success': True,
                'data': {
                    'notifications': [serialize_doc(n) for n in notifications],
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total_count,
                        'pages': (total_count + limit - 1) // limit
                    },
                    'unreadCount': unread_count
                },
                'message': 'Notifications retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve notifications',
                'errors': {'general': [str(e)]}
            }), 500

    @notifications_bp.route('/mark-read', methods=['POST'])
    @token_required
    def mark_notifications_read(current_user):
        """
        Mark one or more notifications as read
        """
        try:
            data = request.get_json()
            user_id = str(current_user['_id'])
            notification_ids = data.get('notificationIds', [])
            mark_all = data.get('markAll', False)
            
            if mark_all:
                # Mark all unread notifications as read
                result = mongo.db.user_notifications.update_many(
                    {
                        'userId': ObjectId(user_id),
                        'isRead': False,
                        'isArchived': False
                    },
                    {
                        '$set': {
                            'isRead': True,
                            'readAt': datetime.utcnow()
                        }
                    }
                )
                
                return jsonify({
                    'success': True,
                    'data': {'markedCount': result.modified_count},
                    'message': f'Marked {result.modified_count} notifications as read'
                })
            
            elif notification_ids:
                # Mark specific notifications as read
                object_ids = [ObjectId(nid) for nid in notification_ids if ObjectId.is_valid(nid)]
                
                result = mongo.db.user_notifications.update_many(
                    {
                        '_id': {'$in': object_ids},
                        'userId': ObjectId(user_id),
                        'isArchived': False
                    },
                    {
                        '$set': {
                            'isRead': True,
                            'readAt': datetime.utcnow()
                        }
                    }
                )
                
                return jsonify({
                    'success': True,
                    'data': {'markedCount': result.modified_count},
                    'message': f'Marked {result.modified_count} notifications as read'
                })
            
            else:
                return jsonify({
                    'success': False,
                    'message': 'Either notificationIds or markAll must be provided'
                }), 400
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to mark notifications as read',
                'errors': {'general': [str(e)]}
            }), 500

    @notifications_bp.route('/archive', methods=['POST'])
    @token_required
    def archive_notifications(current_user):
        """
        Archive (soft delete) notifications
        """
        try:
            data = request.get_json()
            user_id = str(current_user['_id'])
            notification_ids = data.get('notificationIds', [])
            
            if not notification_ids:
                return jsonify({
                    'success': False,
                    'message': 'notificationIds is required'
                }), 400
            
            object_ids = [ObjectId(nid) for nid in notification_ids if ObjectId.is_valid(nid)]
            
            result = mongo.db.user_notifications.update_many(
                {
                    '_id': {'$in': object_ids},
                    'userId': ObjectId(user_id)
                },
                {
                    '$set': {
                        'isArchived': True,
                        'archivedAt': datetime.utcnow()
                    }
                }
            )
            
            return jsonify({
                'success': True,
                'data': {'archivedCount': result.modified_count},
                'message': f'Archived {result.modified_count} notifications'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to archive notifications',
                'errors': {'general': [str(e)]}
            }), 500

    @notifications_bp.route('/sync', methods=['POST'])
    @token_required
    def sync_notifications(current_user):
        """
        Bidirectional sync notifications between client and server
        - Client sends locally-created notifications (needsBackendSync=true)
        - Client sends last sync timestamp
        - Server saves incoming notifications
        - Server returns notifications newer than last sync
        """
        try:
            data = request.get_json()
            user_id = str(current_user['_id'])
            last_sync = data.get('lastSync')  # ISO timestamp string
            client_notifications = data.get('notifications', [])  # NEW: Notifications from client
            
            # ✅ NEW (Feb 26, 2026): Save client notifications to backend
            saved_count = 0
            for client_notif in client_notifications:
                try:
                    # Check if notification already exists (prevent duplicates)
                    existing = mongo.db.user_notifications.find_one({
                        'userId': ObjectId(user_id),
                        'timestamp': datetime.fromisoformat(client_notif['timestamp'].replace('Z', '+00:00'))
                    })
                    
                    if existing:
                        print(f"📱 Notification already exists, skipping: {client_notif.get('title')}")
                        continue
                    
                    # Create notification in backend
                    notification = {
                        '_id': ObjectId(),
                        'userId': ObjectId(user_id),
                        'category': client_notif.get('category', 'general'),
                        'title': client_notif['title'],
                        'body': client_notif['body'],
                        'relatedId': client_notif.get('relatedId'),
                        'metadata': client_notif.get('metadata', {}),
                        'priority': client_notif.get('priority', 'normal'),
                        'timestamp': datetime.fromisoformat(client_notif['timestamp'].replace('Z', '+00:00')),
                        'isRead': client_notif.get('isRead', False),
                        'isArchived': client_notif.get('isArchived', False),
                        'createdAt': datetime.utcnow()
                    }
                    
                    mongo.db.user_notifications.insert_one(notification)
                    saved_count += 1
                    
                    print(f"📱 ✅ Saved client notification: {notification['title']}")
                    
                except Exception as e:
                    print(f"📱 ⚠️ Failed to save client notification: {str(e)}")
                    continue
            
            # Parse last sync timestamp
            if last_sync:
                try:
                    last_sync_dt = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))
                except:
                    last_sync_dt = datetime.utcnow() - timedelta(days=30)  # Default to 30 days ago
            else:
                last_sync_dt = datetime.utcnow() - timedelta(days=30)  # First sync
            
            # Get notifications newer than last sync
            query = {
                'userId': ObjectId(user_id),
                'timestamp': {'$gt': last_sync_dt},
                'isArchived': False
            }
            
            notifications = list(mongo.db.user_notifications.find(query)
                               .sort('timestamp', -1)
                               .limit(200))  # Limit to prevent huge responses
            
            # Get current unread count
            unread_count = mongo.db.user_notifications.count_documents({
                'userId': ObjectId(user_id),
                'isRead': False,
                'isArchived': False
            })
            
            return jsonify({
                'success': True,
                'data': {
                    'notifications': [serialize_doc(n) for n in notifications],
                    'unreadCount': unread_count,
                    'syncTimestamp': datetime.utcnow().isoformat() + 'Z',
                    'savedCount': saved_count  # NEW: How many client notifications were saved
                },
                'message': f'Synced {len(notifications)} notifications (saved {saved_count} from client)'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to sync notifications',
                'errors': {'general': [str(e)]}
            }), 500

    return notifications_bp

def create_user_notification(mongo, user_id, category, title, body, 
                           related_id=None, metadata=None, priority='normal'):
    """
    Helper function to create a notification for a user
    This can be called from other parts of the system
    """
    try:
        notification = {
            '_id': ObjectId(),
            'userId': ObjectId(user_id),
            'category': category,
            'title': title,
            'body': body,
            'relatedId': related_id,
            'metadata': metadata or {},
            'priority': priority,
            'timestamp': datetime.utcnow(),
            'isRead': False,
            'isArchived': False,
            'createdAt': datetime.utcnow()
        }
        
        result = mongo.db.user_notifications.insert_one(notification)
        
        # DEBUG LOGGING
        print(f"📱 NOTIFICATION CREATED:")
        print(f"   User ID: {user_id}")
        print(f"   Category: {category}")
        print(f"   Title: {title}")
        print(f"   Body: {body[:100]}..." if len(body) > 100 else f"   Body: {body}")
        print(f"   Priority: {priority}")
        print(f"   Notification ID: {result.inserted_id}")
        print(f"   Timestamp: {datetime.utcnow().isoformat()}")
        
        return str(result.inserted_id)
        
    except Exception as e:
        print(f'❌ NOTIFICATION CREATION FAILED:')
        print(f'   User ID: {user_id}')
        print(f'   Error: {str(e)}')
        import traceback
        traceback.print_exc()
        return None

# Notification categories (matching frontend)
NOTIFICATION_CATEGORIES = {
    'missingReceipt': 'Missing Receipt',
    'incompleteDescription': 'Incomplete Description', 
    'achievement': 'Achievement',
    'syncError': 'Sync Error',
    'inactivity': 'Inactivity Reminder',
    'digest': 'Daily Digest',
    'credit': 'FiCore Credits',
    'general': 'Notification',
    'transaction': 'Transaction',
    'wallet': 'Wallet Activity'
}