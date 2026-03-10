"""
Treasury Dashboard Blueprint
Provides admin endpoints for treasury management and reconciliation
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.treasury_management import TreasuryManager


def init_treasury_dashboard_blueprint(mongo, token_required, admin_required):
    treasury_bp = Blueprint('treasury', __name__, url_prefix='/admin/treasury')
    
    @treasury_bp.route('/integrity-check', methods=['GET'])
    @token_required
    @admin_required
    def check_integrity(current_user):
        """
        Run triple-layer reconciliation check
        Returns treasury health status and alerts
        """
        try:
            treasury = TreasuryManager(mongo.db)
            result = treasury.check_treasury_integrity()
            
            return jsonify({
                'success': True,
                'data': result
            }), 200
            
        except Exception as e:
            print(f"❌ Error checking treasury integrity: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @treasury_bp.route('/bank-cash', methods=['GET'])
    @token_required
    @admin_required
    def get_bank_cash(current_user):
        """
        Get Layer 1: Bank cash position
        """
        try:
            treasury = TreasuryManager(mongo.db)
            result = treasury.get_bank_cash_position()
            
            return jsonify({
                'success': True,
                'data': result
            }), 200
            
        except Exception as e:
            print(f"❌ Error getting bank cash: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @treasury_bp.route('/user-liability', methods=['GET'])
    @token_required
    @admin_required
    def get_user_liability(current_user):
        """
        Get Layer 2: User wallet liability
        """
        try:
            treasury = TreasuryManager(mongo.db)
            result = treasury.get_user_wallet_liability()
            
            return jsonify({
                'success': True,
                'data': result
            }), 200
            
        except Exception as e:
            print(f"❌ Error getting user liability: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @treasury_bp.route('/provider-float', methods=['GET'])
    @token_required
    @admin_required
    def get_provider_float(current_user):
        """
        Get Layer 3: Provider float status
        """
        try:
            treasury = TreasuryManager(mongo.db)
            result = treasury.get_provider_float_status()
            
            return jsonify({
                'success': True,
                'data': result
            }), 200
            
        except Exception as e:
            print(f"❌ Error getting provider float: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @treasury_bp.route('/suspense-account', methods=['GET'])
    @token_required
    @admin_required
    def get_suspense_account(current_user):
        """
        Get transactions in suspense (NEEDS_RECONCILIATION)
        """
        try:
            treasury = TreasuryManager(mongo.db)
            result = treasury.get_suspense_transactions()
            
            return jsonify({
                'success': True,
                'data': result
            }), 200
            
        except Exception as e:
            print(f"❌ Error getting suspense account: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @treasury_bp.route('/reserved-amounts', methods=['GET'])
    @token_required
    @admin_required
    def get_reserved_amounts(current_user):
        """
        Get breakdown of reserved amounts by user
        """
        try:
            treasury = TreasuryManager(mongo.db)
            result = treasury.get_reserved_amounts_breakdown()
            
            return jsonify({
                'success': True,
                'data': result
            }), 200
            
        except Exception as e:
            print(f"❌ Error getting reserved amounts: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    return treasury_bp
