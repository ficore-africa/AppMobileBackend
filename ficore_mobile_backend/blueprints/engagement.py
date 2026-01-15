"""
Engagement Blueprint for ₦0 Communication Strategy
Handles weekly engagement reminders and user retention emails
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from utils.engagement_reminder_service import send_weekly_engagement_reminders

engagement_bp = Blueprint('engagement', __name__, url_prefix='/engagement')

def init_engagement_blueprint(mongo, app_config):
    """Initialize the engagement blueprint with database and config"""
    engagement_bp.mongo = mongo
    engagement_bp.config = app_config
    return engagement_bp

@engagement_bp.route('/send-weekly-reminders', methods=['POST'])
def trigger_weekly_reminders():
    """
    Trigger weekly engagement reminders
    This endpoint should be called by a cron job or scheduler
    
    Security: Should be protected by API key in production
    """
    try:
        # Optional: Add API key authentication for security
        api_key = request.headers.get('X-API-Key')
        expected_key = engagement_bp.config.get('ENGAGEMENT_API_KEY')
        
        if expected_key and api_key != expected_key:
            return jsonify({
                'success': False,
                'message': 'Unauthorized'
            }), 401
        
        # Send weekly engagement reminders
        results = send_weekly_engagement_reminders(engagement_bp.mongo)
        
        return jsonify({
            'success': True,
            'message': 'Weekly engagement reminders processed',
            'data': results
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to send weekly reminders',
            'errors': {'general': [str(e)]}
        }), 500

@engagement_bp.route('/stats', methods=['GET'])
def get_engagement_stats():
    """
    Get engagement statistics
    Shows how many users received reminders and engagement metrics
    """
    try:
        # Get engagement logs from last 30 days
        from datetime import timedelta
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        # Count reminders sent by type
        reminder_stats = list(engagement_bp.mongo.db.engagement_logs.aggregate([
            {
                '$match': {
                    'type': 'engagement_reminder',
                    'sentAt': {'$gte': thirty_days_ago}
                }
            },
            {
                '$group': {
                    '_id': '$reminderType',
                    'count': {'$sum': 1},
                    'successful': {
                        '$sum': {
                            '$cond': ['$emailSent', 1, 0]
                        }
                    }
                }
            }
        ]))
        
        # Get total active users
        total_users = engagement_bp.mongo.db.users.count_documents({
            'isActive': True,
            'email': {'$exists': True, '$ne': ''}
        })
        
        # Get users who logged in this week
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        active_this_week = engagement_bp.mongo.db.users.count_documents({
            'isActive': True,
            'lastLogin': {'$gte': one_week_ago}
        })
        
        return jsonify({
            'success': True,
            'data': {
                'total_users': total_users,
                'active_this_week': active_this_week,
                'engagement_rate': round((active_this_week / total_users * 100), 2) if total_users > 0 else 0,
                'reminder_stats': reminder_stats,
                'period': '30 days'
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to get engagement stats',
            'errors': {'general': [str(e)]}
        }), 500