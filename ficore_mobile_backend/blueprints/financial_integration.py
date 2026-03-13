"""
Financial Integration Blueprint
Endpoints for running financial automation integration and fixes
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Blueprint, jsonify, request
from bson import ObjectId
from datetime import datetime
try:
    from utils.financial_automation_integration import (
        run_complete_financial_integration,
        ensure_all_fc_credits_have_liabilities,
        ensure_all_subscriptions_have_liabilities,
        calculate_total_liabilities,
        ensure_monthly_depreciation_recorded,
        get_balance_sheet_data,
        get_liability_breakdown_for_reports
    )
except ImportError:
    # Fallback for missing module
    def run_complete_financial_integration(*args, **kwargs):
        return {'success': False, 'message': 'Financial automation integration not available'}
    def ensure_all_fc_credits_have_liabilities(*args, **kwargs):
        return {'success': False, 'message': 'Financial automation integration not available'}
    def ensure_all_subscriptions_have_liabilities(*args, **kwargs):
        return {'success': False, 'message': 'Financial automation integration not available'}
    def calculate_total_liabilities(*args, **kwargs):
        return 0.0
    def ensure_monthly_depreciation_recorded(*args, **kwargs):
        return {'success': False, 'message': 'Financial automation integration not available'}
    def get_balance_sheet_data(*args, **kwargs):
        return {}
    def get_liability_breakdown_for_reports(*args, **kwargs):
        return {}

from utils.decimal_helpers import safe_float

def init_financial_integration_blueprint(mongo, token_required):
    """Initialize the financial integration blueprint"""
    financial_integration_bp = Blueprint('financial_integration', __name__, url_prefix='/api/financial-integration')

    @financial_integration_bp.route('/run-complete-integration', methods=['POST'])
    @token_required
    def run_complete_integration(current_user):
        """
        Run complete financial integration to fix all automation issues
        """
        try:
            # Run complete integration
            result = run_complete_financial_integration(mongo)
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'message': result['message'],
                    'results': result['results'],
                    'summary': result['summary']
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': result['message'],
                    'error': result.get('error')
                }), 500
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to run financial integration',
                'error': str(e)
            }), 500

    @financial_integration_bp.route('/fix-fc-liabilities', methods=['POST'])
    @token_required
    def fix_fc_liabilities(current_user):
        """
        Ensure all FC Credits have corresponding liability entries
        """
        try:
            result = ensure_all_fc_credits_have_liabilities(mongo)
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'message': result['message'],
                    'created_liabilities': result['created_liabilities'],
                    'total_liability_value': result['total_liability_value']
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': result['message'],
                    'error': result.get('error')
                }), 500
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to fix FC Credit liabilities',
                'error': str(e)
            }), 500

    @financial_integration_bp.route('/fix-subscription-liabilities', methods=['POST'])
    @token_required
    def fix_subscription_liabilities(current_user):
        """
        Ensure all admin-granted subscriptions have corresponding liability entries
        """
        try:
            result = ensure_all_subscriptions_have_liabilities(mongo)
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'message': result['message'],
                    'created_liabilities': result['created_liabilities'],
                    'total_liability_value': result['total_liability_value']
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': result['message'],
                    'error': result.get('error')
                }), 500
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to fix subscription liabilities',
                'error': str(e)
            }), 500

    @financial_integration_bp.route('/record-monthly-depreciation', methods=['POST'])
    @token_required
    def record_monthly_depreciation(current_user):
        """
        Ensure monthly depreciation is recorded for current month
        """
        try:
            result = ensure_monthly_depreciation_recorded(mongo)
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'message': result['message'],
                    'already_recorded': result.get('already_recorded', False),
                    'depreciation_amount': result.get('depreciation_amount', 0),
                    'expense_id': result.get('expense_id')
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': result['message'],
                    'error': result.get('error')
                }), 500
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to record monthly depreciation',
                'error': str(e)
            }), 500

    @financial_integration_bp.route('/liabilities', methods=['GET'])
    @token_required
    def get_liabilities(current_user):
        """
        Get total liabilities for balance sheet reporting
        """
        try:
            # PRIVACY FIX: Pass current user ID to filter liabilities to this user only
            result = calculate_total_liabilities(mongo, current_user['_id'])
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'message': result['message'],
                    'fc_credit_liabilities': result['fc_credit_liabilities'],
                    'subscription_liabilities': result['subscription_liabilities'],
                    'total_liabilities': result['total_liabilities']
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': result['message'],
                    'error': result.get('error')
                }), 500
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get liabilities',
                'error': str(e)
            }), 500

    @financial_integration_bp.route('/balance-sheet', methods=['GET'])
    @token_required
    def get_balance_sheet(current_user):
        """
        Get comprehensive balance sheet data including liabilities
        """
        try:
            result = get_balance_sheet_data(mongo)
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'assets': result['assets'],
                    'liabilities': result['liabilities'],
                    'equity': result['equity'],
                    'balance_check': result['balance_check']
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': result['message'],
                    'error': result.get('error')
                }), 500
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get balance sheet data',
                'error': str(e)
            }), 500

    @financial_integration_bp.route('/liability-breakdown', methods=['GET'])
    @token_required
    def get_liability_breakdown(current_user):
        """
        Get detailed liability breakdown for inclusion in financial reports
        """
        try:
            result = get_liability_breakdown_for_reports(mongo)
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'fc_credit_liabilities': result['fc_credit_liabilities'],
                    'subscription_liabilities': result['subscription_liabilities'],
                    'total_liabilities': result['total_liabilities']
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': result['message'],
                    'error': result.get('error')
                }), 500
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get liability breakdown',
                'error': str(e)
            }), 500

    @financial_integration_bp.route('/status', methods=['GET'])
    @token_required
    def get_integration_status(current_user):
        """
        Get status of financial integration systems
        """
        try:
            # Check various integration points
            status = {
                'fc_credits_automation': {
                    'description': 'FC Credits marketing expense automation',
                    'status': 'active',
                    'integration_points': [
                        'auth.py - signup bonus',
                        'credits.py - tax education progress',
                        'rewards.py - streak milestones and exploration bonuses'
                    ]
                },
                'subscription_automation': {
                    'description': 'Subscription marketing expense automation',
                    'status': 'active',
                    'integration_points': [
                        'admin.py - admin-granted subscriptions'
                    ]
                },
                'depreciation_automation': {
                    'description': 'Monthly depreciation recording',
                    'status': 'active',
                    'integration_points': [
                        'automation_cron.py - monthly cron job'
                    ]
                },
                'vas_commission_automation': {
                    'description': 'VAS commission revenue recording',
                    'status': 'needs_integration',
                    'integration_points': [
                        'VAS endpoints need to call record_vas_commission_revenue'
                    ]
                },
                'fc_consumption_automation': {
                    'description': 'FC Credits consumption revenue recording',
                    'status': 'needs_integration',
                    'integration_points': [
                        'Report export endpoints need to call record_fc_consumption_revenue'
                    ]
                }
            }
            
            return jsonify({
                'success': True,
                'integration_status': status,
                'message': 'Financial integration status retrieved'
            }), 200
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to get integration status',
                'error': str(e)
            }), 500

    return financial_integration_bp

# Alias for backward compatibility (in case deployment expects this name)
register_financial_integration_blueprint = init_financial_integration_blueprint