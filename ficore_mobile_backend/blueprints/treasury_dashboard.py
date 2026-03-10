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
# Import decorators from app.py - they're defined there
from functools import wraps
from flask import g
import jwt
import os

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # JWT is passed in the request header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'message': 'Token format invalid'}), 401
        
        # Return 401 if token is not passed
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        
        try:
            # Decoding the payload to fetch the stored details
            data = jwt.decode(token, os.getenv('JWT_SECRET_KEY'), algorithms=['HS256'])
            current_user = {
                'userId': data['userId'],
                'email': data['email']
            }
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Token is invalid'}), 401
        
        # Returns the current logged in users context to the routes
        return f(current_user, *args, **kwargs)
    
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(current_user, *args, **kwargs):
        # Check if user is admin (you can implement your admin logic here)
        # For now, we'll assume all authenticated users are admins for treasury access
        return f(current_user, *args, **kwargs)
    
    return decorated


def init_treasury_dashboard_blueprint(mongo):
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
