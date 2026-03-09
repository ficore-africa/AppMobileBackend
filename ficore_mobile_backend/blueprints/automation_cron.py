"""
Automation Cron Endpoints
Exposes HTTP endpoints that can be triggered by external cron services
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
import os

def init_automation_cron_blueprint(mongo):
    automation_cron_bp = Blueprint('automation_cron', __name__, url_prefix='/automation')
    
    # Secret key for authentication (set in environment variables)
    CRON_SECRET_KEY = os.getenv('CRON_SECRET_KEY', 'key-here')
    
    def verify_cron_secret():
        """Verify the cron secret key from request headers"""
        provided_key = request.headers.get('X-Cron-Secret')
        if provided_key != CRON_SECRET_KEY:
            return False
        return True
    
    @automation_cron_bp.route('/monthly-depreciation', methods=['POST'])
    def run_monthly_depreciation():
        """
        Run monthly depreciation
        Triggered by external cron service on 1st of each month
        
        Example curl:
        curl -X POST https://mobilebackend.ficoreafrica.com/automation/monthly-depreciation \
             -H "X-Cron-Secret: your-secret-key"
        """
        try:
            # Verify authentication
            if not verify_cron_secret():
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized - Invalid cron secret key'
                }), 401
            
            # Import and run depreciation
            from ficore_mobile_backend.utils.business_bookkeeping import record_monthly_depreciation
            
            expense_id = record_monthly_depreciation(mongo)
            
            return jsonify({
                'success': True,
                'message': 'Monthly depreciation recorded successfully',
                'data': {
                    'expense_id': str(expense_id),
                    'executed_at': datetime.utcnow().isoformat() + 'Z'
                }
            }), 200
            
        except Exception as e:
            print(f"Error in monthly depreciation cron: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to record monthly depreciation',
                'error': str(e)
            }), 500
    
    @automation_cron_bp.route('/daily-subscription-accrual', methods=['POST'])
    def run_daily_subscription_accrual():
        """
        Run daily subscription accrual
        Triggered by external cron service every day at 00:00
        
        Example curl:
        curl -X POST https://mobilebackend.ficoreafrica.com/automation/daily-subscription-accrual \
             -H "X-Cron-Secret: your-secret-key"
        """
        try:
            # Verify authentication
            if not verify_cron_secret():
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized - Invalid cron secret key'
                }), 401
            
            # Import and run subscription accrual
            from ficore_mobile_backend.utils.business_bookkeeping import accrue_daily_subscription_revenue
            
            revenue_ids = accrue_daily_subscription_revenue(mongo)
            
            return jsonify({
                'success': True,
                'message': f'Daily subscription accrual completed - {len(revenue_ids)} entries created',
                'data': {
                    'revenue_ids': [str(rid) for rid in revenue_ids],
                    'count': len(revenue_ids),
                    'executed_at': datetime.utcnow().isoformat() + 'Z'
                }
            }), 200
            
        except Exception as e:
            print(f"Error in daily subscription accrual cron: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to accrue daily subscription revenue',
                'error': str(e)
            }), 500
    
    @automation_cron_bp.route('/expire-subscriptions', methods=['POST'])
    def run_expire_subscriptions():
        """
        Run subscription expiration check
        Triggered by external cron service every day at 02:00
        
        Example curl:
        curl -X POST https://mobilebackend.ficoreafrica.com/automation/expire-subscriptions \
             -H "X-Cron-Secret: your-secret-key"
        """
        try:
            # Verify authentication
            if not verify_cron_secret():
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized - Invalid cron secret key'
                }), 401
            
            # Import and run subscription expiration
            from bson import ObjectId
            
            # Find all active subscriptions that have expired
            expired_subscriptions = list(mongo.db.subscriptions.find({
                'status': 'active',
                'endDate': {'$lt': datetime.utcnow()}
            }))
            
            expired_count = 0
            for subscription in expired_subscriptions:
                # Update subscription status to expired
                mongo.db.subscriptions.update_one(
                    {'_id': subscription['_id']},
                    {
                        '$set': {
                            'status': 'expired',
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                expired_count += 1
            
            return jsonify({
                'success': True,
                'message': f'Subscription expiration check completed - {expired_count} subscriptions expired',
                'data': {
                    'expired_count': expired_count,
                    'executed_at': datetime.utcnow().isoformat() + 'Z'
                }
            }), 200
            
        except Exception as e:
            print(f"Error in subscription expiration cron: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to process subscription expirations',
                'error': str(e)
            }), 500
    
    @automation_cron_bp.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint (no auth required)"""
        return jsonify({
            'success': True,
            'message': 'Automation cron endpoints are healthy',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 200
    
    return automation_cron_bp
