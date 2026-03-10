"""
Financial Integration Blueprint
Endpoints for running financial automation integration and fixes
"""

from flask import Blueprint, jsonify, request
from bson import ObjectId
from datetime import datetime
from utils.financial_automation_integration import (
    run_complete_financial_integration,
    ensure_all_fc_credits_have_liabilities,
    ensure_all_subscriptions_have_liabilities,
    calculate_total_liabilities,
    ensure_monthly_depreciation_recorded,
    get_balance_sheet_data,
    get_liability_breakdown_for_reports
)
from utils.auth_helpers import require_auth
from utils.decimal_helpers import safe_float

# Create blueprint
financial_integration_bp = Blueprint('financial_integration', __name__, url_prefix='/api/financial-integration')

@financial_integration_bp.route('/run-complete-integration', methods=['POST'])
@require_auth
def run_complete_integration():
    """
    Run complete financial integration to fix all automation issues
    """
    try:
        mongo = financial_integration_bp.mongo
        
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
@require_auth
def fix_fc_liabilities():
    """
    Ensure all FC Credits have corresponding liability entries
    """
    try:
        mongo = financial_integration_bp.mongo
        
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
@require_auth
def fix_subscription_liabilities():
    """
    Ensure all admin-granted subscriptions have corresponding liability entries
    """
    try:
        mongo = financial_integration_bp.mongo
        
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
@require_auth
def record_monthly_depreciation():
    """
    Ensure monthly depreciation is recorded for current month
    """
    try:
        mongo = financial_integration_bp.mongo
        
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
@require_auth
def get_liabilities():
    """
    Get total liabilities for balance sheet reporting
    """
    try:
        mongo = financial_integration_bp.mongo
        
        result = calculate_total_liabilities(mongo)
        
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
@require_auth
def get_balance_sheet():
    """
    Get comprehensive balance sheet data including liabilities
    """
    try:
        mongo = financial_integration_bp.mongo
        
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
@require_auth
def get_liability_breakdown():
    """
    Get detailed liability breakdown for inclusion in financial reports
    """
    try:
        mongo = financial_integration_bp.mongo
        
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
@require_auth
def get_integration_status():
    """
    Get status of financial integration systems
    """
    try:
        mongo = financial_integration_bp.mongo
        
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


# Register blueprint with app
def register_financial_integration_blueprint(app, mongo):
    """Register the financial integration blueprint with the Flask app"""
    financial_integration_bp.mongo = mongo
    app.register_blueprint(financial_integration_bp)

    print("✅ Financial Integration Blueprint registered")
