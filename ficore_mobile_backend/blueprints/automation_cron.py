from utils.business_bookkeeping import *
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
        Run daily subscription accrual for PAID subscriptions
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
            
            # Import and run subscription accrual for PAID subscriptions
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
    
    @automation_cron_bp.route('/daily-subscription-consumption', methods=['POST'])
    def run_daily_subscription_consumption():
        """
        Run daily subscription consumption for ADMIN-GRANTED subscriptions
        Triggered by external cron service every day at 01:00
        
        This processes liability consumption for admin-granted subscriptions,
        converting subscription liabilities into revenue over time.
        
        Example curl:
        curl -X POST https://mobilebackend.ficoreafrica.com/automation/daily-subscription-consumption \
             -H "X-Cron-Secret: your-secret-key"
        """
        try:
            # Verify authentication
            if not verify_cron_secret():
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized - Invalid cron secret key'
                }), 401
            
            # Import and run subscription consumption for admin-granted subscriptions
            processed_ids = process_daily_subscription_accruals(mongo)
            
            return jsonify({
                'success': True,
                'message': f'Daily subscription consumption completed - {len(processed_ids)} subscriptions processed',
                'data': {
                    'processed_subscription_ids': [str(sid) for sid in processed_ids],
                    'count': len(processed_ids),
                    'executed_at': datetime.utcnow().isoformat() + 'Z'
                }
            }), 200
            
        except Exception as e:
            print(f"Error in daily subscription consumption cron: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to process daily subscription consumption',
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
    
    @automation_cron_bp.route('/sync-provider-balances', methods=['POST'])
    def run_sync_provider_balances():
        """
        Run automated provider balance sync (Peyflex + Monnify)
        Triggered by external cron service every hour
        
        This implements the triple-check protocol:
        1. Fetch balance from provider API
        2. Calculate expected balance from transactions
        3. Detect discrepancies
        4. Update Provider Health Dashboard
        5. Send alerts if needed
        
        Example curl:
        curl -X POST https://mobilebackend.ficoreafrica.com/automation/sync-provider-balances \
             -H "X-Cron-Secret: your-secret-key"
        """
        try:
            # Verify authentication
            if not verify_cron_secret():
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized - Invalid cron secret key'
                }), 401
            
            # Import and run provider balance sync
            from services.provider_balance_sync import ProviderBalanceSyncService
            
            sync_service = ProviderBalanceSyncService(mongo)
            result = sync_service.sync_all_providers()
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'message': 'Provider balance sync completed successfully',
                    'data': result,
                    'executed_at': datetime.utcnow().isoformat() + 'Z'
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': 'Provider balance sync completed with errors',
                    'data': result,
                    'executed_at': datetime.utcnow().isoformat() + 'Z'
                }), 500
            
        except Exception as e:
            print(f"Error in provider balance sync cron: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to sync provider balances',
                'error': str(e)
            }), 500
    
    @automation_cron_bp.route('/sync-provider-balance/<provider>', methods=['POST'])
    def run_sync_single_provider(provider):
        """
        Run automated balance sync for a single provider
        Triggered manually or by external cron service
        
        Supported providers: peyflex, monnify
        
        Example curl:
        curl -X POST https://mobilebackend.ficoreafrica.com/automation/sync-provider-balance/peyflex \
             -H "X-Cron-Secret: your-secret-key"
        """
        try:
            # Verify authentication
            if not verify_cron_secret():
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized - Invalid cron secret key'
                }), 401
            
            provider_lower = provider.lower()
            if provider_lower not in ['peyflex', 'monnify']:
                return jsonify({
                    'success': False,
                    'message': f'Unsupported provider: {provider}. Supported: peyflex, monnify'
                }), 400
            
            # Import and run provider balance sync
            from services.provider_balance_sync import ProviderBalanceSyncService
            
            sync_service = ProviderBalanceSyncService(mongo)
            result = sync_service.sync_and_update_provider_balance(provider_lower)
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'message': f'{provider.capitalize()} balance synced successfully',
                    'data': result,
                    'executed_at': datetime.utcnow().isoformat() + 'Z'
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': f'Failed to sync {provider.capitalize()} balance',
                    'data': result,
                    'executed_at': datetime.utcnow().isoformat() + 'Z'
                }), 500
            
        except Exception as e:
            print(f"Error in {provider} balance sync cron: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'Failed to sync {provider} balance',
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
