"""
VAS Pricing Engine

Handles VAS pricing calculations and emergency pricing logic.
"""

from utils.decimal_helpers import safe_float
import logging

logger = logging.getLogger(__name__)

def get_pricing_engine():
    """
    Get pricing engine configuration
    
    Returns:
        dict: Pricing engine configuration
    """
    return {
        'default_margin': 0.0,  # Face value pricing (no margin)
        'emergency_pricing_enabled': False,  # Disabled per golden rules
        'face_value_policy': True,
        'supported_services': ['airtime', 'data', 'electricity', 'bills']
    }

def calculate_vas_price(service_type, face_value, provider='peyflex'):
    """
    Calculate VAS price based on service type and face value
    
    Args:
        service_type: Type of VAS service (airtime, data, etc.)
        face_value: Face value amount
        provider: VAS provider (peyflex, monnify)
        
    Returns:
        dict: Pricing calculation result
    """
    try:
        face_value = safe_float(face_value)
        
        # Face value pricing policy (Golden Rules #31)
        selling_price = face_value
        cost_price = face_value
        margin = 0.0
        is_emergency_pricing = False
        
        savings_message = f"You pay exactly ₦{face_value:,.2f} - no hidden fees!"
        
        return {
            'selling_price': selling_price,
            'cost_price': cost_price,
            'margin': margin,
            'margin_percentage': 0.0,
            'savings_message': savings_message,
            'is_emergency_pricing': is_emergency_pricing,
            'provider': provider,
            'service_type': service_type,
            'face_value': face_value
        }
        
    except Exception as e:
        logger.error(f"Error calculating VAS price: {str(e)}")
        return {
            'selling_price': face_value,
            'cost_price': face_value,
            'margin': 0.0,
            'error': str(e)
        }

def get_emergency_pricing_status():
    """
    Get emergency pricing status (always disabled per golden rules)
    
    Returns:
        dict: Emergency pricing status
    """
    return {
        'enabled': False,
        'reason': 'Emergency pricing disabled per Golden Rules #31',
        'face_value_policy': True
    }
