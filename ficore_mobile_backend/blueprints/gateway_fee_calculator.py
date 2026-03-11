"""
Gateway Fee Calculator - Centralized Fee Logic for FiCore
Handles fee calculations for all payment providers (Paystack, Monnify, Peyflex)

This module provides a unified interface for calculating gateway fees across:
- VAS transactions (Monnify, Peyflex)
- FC Credits purchases (Paystack)
- Subscription purchases (Paystack)
- Wallet funding (Monnify)

Follows DRY principle by centralizing all fee logic in one place.
"""

from typing import Dict, Any, Tuple
from decimal import Decimal, ROUND_HALF_UP


class GatewayFeeCalculator:
    """
    Centralized gateway fee calculator for all FiCore payment providers
    """
    
    # Fee structures for different providers
    FEE_STRUCTURES = {
        'paystack': {
            'type': 'percentage_plus_fixed',
            'percentage': 1.5,  # 1.5%
            'fixed_fee': 100.0,  # ₦100 fixed fee
            'cap': 2500.0,  # ₦2,500 maximum fee (CRITICAL: Paystack caps fees)
            'description': 'Paystack: 1.5% + ₦100 (capped at ₦2,500) (WE PAY THIS)'
        },
        'monnify_wallet_deposit': {
            'type': 'percentage',
            'percentage': 1.65,  # 1.65% on wallet deposits only
            'fixed_fee': 0.0,
            'cap': None,
            'description': 'Monnify Wallet Deposit Fee: 1.65% (WE PAY THIS)'
        },
        # COMMISSION STRUCTURES (WE EARN THESE - NOT FEES WE PAY)
        'monnify_commission': {
            'type': 'percentage',
            'percentage': 3.0,  # 3% commission on VAS (WE EARN THIS)
            'fixed_fee': 0.0,
            'cap': None,
            'description': 'Monnify VAS Commission: 3% (WE EARN THIS)'
        },
        'peyflex_commission': {
            'type': 'percentage',
            'percentage': 2.5,  # 2.5% commission on VAS (WE EARN THIS)
            'fixed_fee': 0.0,
            'cap': None,
            'description': 'Peyflex VAS Commission: 2.5% (WE EARN THIS)'
        },
        # VAS-specific fees (what we charge users)
        'vas_transaction': {
            'type': 'fixed',
            'percentage': 0.0,
            'fixed_fee': 30.0,  # ₦30 per VAS transaction
            'cap': None,
            'description': 'VAS Transaction Fee: ₦30'
        },
        'wallet_activation': {
            'type': 'fixed',
            'percentage': 0.0,
            'fixed_fee': 100.0,  # ₦100 activation fee
            'cap': None,
            'description': 'Wallet Activation Fee: ₦100'
        },
        'bvn_verification': {
            'type': 'fixed',
            'percentage': 0.0,
            'fixed_fee': 10.0,  # ₦10 BVN verification
            'cap': None,
            'description': 'BVN Verification: ₦10'
        },
        'nin_verification': {
            'type': 'fixed',
            'percentage': 0.0,
            'fixed_fee': 60.0,  # ₦60 NIN verification
            'cap': None,
            'description': 'NIN Verification: ₦60'
        }
    }
    
    @classmethod
    def calculate_fee(cls, amount: float, provider: str) -> Dict[str, Any]:
        """
        Calculate gateway fee for a given amount and provider
        
        Args:
            amount: Transaction amount in Naira
            provider: Provider name (paystack, monnify, peyflex, etc.)
            
        Returns:
            Dict containing:
            - gross_amount: Original amount
            - gateway_fee: Fee charged by gateway
            - net_amount: Amount after deducting gateway fee
            - fee_percentage: Effective fee percentage
            - provider: Provider name
            - fee_structure: Fee structure used
        """
        if provider not in cls.FEE_STRUCTURES:
            raise ValueError(f"Unknown provider: {provider}")
        
        fee_structure = cls.FEE_STRUCTURES[provider]
        
        # Calculate fee based on structure type
        if fee_structure['type'] == 'percentage_plus_fixed':
            # Paystack: 1.5% + ₦100
            percentage_fee = amount * (fee_structure['percentage'] / 100)
            gateway_fee = percentage_fee + fee_structure['fixed_fee']
        elif fee_structure['type'] == 'percentage':
            # Monnify, Peyflex: X%
            gateway_fee = amount * (fee_structure['percentage'] / 100)
        elif fee_structure['type'] == 'fixed':
            # VAS fees: Fixed amount
            gateway_fee = fee_structure['fixed_fee']
        else:
            raise ValueError(f"Unknown fee structure type: {fee_structure['type']}")
        
        # Apply cap if exists
        if fee_structure['cap'] and gateway_fee > fee_structure['cap']:
            gateway_fee = fee_structure['cap']
        
        # Apply VAT on gateway fees (7.5% VAT on the fee itself)
        # This is the "ghost" cost that many systems miss
        if provider in ['paystack', 'monnify_wallet_deposit']:
            vat_on_fee = gateway_fee * 0.075  # 7.5% VAT on the fee
            total_fee_with_vat = gateway_fee + vat_on_fee
            
            # Round to 2 decimal places
            vat_on_fee = round(vat_on_fee, 2)
            total_fee_with_vat = round(total_fee_with_vat, 2)
            
            print(f"   VAT on {provider} fee: ₦{gateway_fee:,.2f} + ₦{vat_on_fee:,.2f} VAT = ₦{total_fee_with_vat:,.2f} total")
            
            # Use the total fee (including VAT) for calculations
            gateway_fee = total_fee_with_vat
        
        # Round to 2 decimal places
        gateway_fee = round(gateway_fee, 2)
        net_amount = round(amount - gateway_fee, 2)
        fee_percentage = round((gateway_fee / amount * 100), 4) if amount > 0 else 0
        
        return {
            'gross_amount': amount,
            'gateway_fee': gateway_fee,
            'net_amount': net_amount,
            'fee_percentage': fee_percentage,
            'provider': provider,
            'fee_structure': fee_structure['description'],
            'vat_included': provider in ['paystack', 'monnify_wallet_deposit'],
            'calculation_details': {
                'fee_type': fee_structure['type'],
                'percentage_rate': fee_structure['percentage'],
                'fixed_fee': fee_structure['fixed_fee'],
                'cap': fee_structure['cap'],
                'vat_rate': 7.5 if provider in ['paystack', 'monnify_wallet_deposit'] else 0,
                'base_fee': round(gateway_fee / 1.075, 2) if provider in ['paystack', 'monnify_wallet_deposit'] else gateway_fee,
                'vat_amount': round(gateway_fee - (gateway_fee / 1.075), 2) if provider in ['paystack', 'monnify_wallet_deposit'] else 0
            }
        }
    
    @classmethod
    def calculate_vas_fees(cls, amount: float, provider: str) -> Dict[str, Any]:
        """
        Calculate fees for VAS transactions - CORRECTED VERSION
        
        CRITICAL: VAS providers (Monnify, Peyflex) PAY US commissions.
        We do NOT pay them fees on VAS transactions.
        We only pay Monnify fees on wallet deposits.
        
        Args:
            amount: VAS transaction amount
            provider: VAS provider (monnify, peyflex)
            
        Returns:
            Dict with commission earned and service fee charged
        """
        # Calculate commission we EARN from provider
        if provider == 'monnify':
            commission_calc = cls.calculate_fee(amount, 'monnify_commission')
            commission_earned = commission_calc['gateway_fee']  # This is actually commission we earn
        elif provider == 'peyflex':
            commission_calc = cls.calculate_fee(amount, 'peyflex_commission')
            commission_earned = commission_calc['gateway_fee']  # This is actually commission we earn
        else:
            raise ValueError(f"Unknown VAS provider: {provider}")
        
        # Calculate our service fee (what we charge user)
        service_calc = cls.calculate_fee(amount, 'vas_transaction')
        service_fee = service_calc['gateway_fee']  # ₦30 service fee
        
        # For VAS transactions:
        # - User pays: amount + service_fee (₦30)
        # - Provider pays us: commission (3% or 2.5%)
        # - We have NO gateway fees on VAS transactions
        user_pays = amount + service_fee
        commission_received = commission_earned
        our_total_profit = service_fee + commission_received
        
        return {
            'transaction_amount': amount,
            'service_fee': service_fee,
            'user_pays_total': user_pays,
            'commission_earned': commission_received,
            'gateway_fee': 0.0,  # NO gateway fees on VAS transactions
            'our_total_profit': our_total_profit,
            'provider': provider,
            'service_fee_structure': service_calc['fee_structure'],
            'commission_structure': commission_calc['fee_structure']
        }
    
    @classmethod
    def calculate_wallet_deposit_fees(cls, deposit_amount: float) -> Dict[str, Any]:
        """
        Calculate fees for wallet deposits via Monnify
        
        This is where Monnify DOES charge us fees (1.65% on deposits)
        
        Args:
            deposit_amount: Amount user is depositing to wallet
            
        Returns:
            Dict with Monnify deposit fee and net amount
        """
        monnify_calc = cls.calculate_fee(deposit_amount, 'monnify_wallet_deposit')
        
        return {
            'deposit_amount': deposit_amount,
            'gateway_fee': monnify_calc['gateway_fee'],
            'net_received': monnify_calc['net_amount'],
            'fee_percentage': monnify_calc['fee_percentage'],
            'provider': 'monnify',
            'fee_structure': monnify_calc['fee_structure']
        }
    
    @classmethod
    def calculate_fc_purchase_fees(cls, fc_amount: float, naira_amount: float) -> Dict[str, Any]:
        """
        Calculate fees for FC Credits purchase via Paystack
        
        Args:
            fc_amount: Number of FC Credits purchased
            naira_amount: Amount paid in Naira
            
        Returns:
            Dict with Paystack fee and net revenue
        """
        paystack_calc = cls.calculate_fee(naira_amount, 'paystack')
        
        return {
            'fc_amount': fc_amount,
            'gross_revenue': naira_amount,
            'gateway_fee': paystack_calc['gateway_fee'],
            'net_revenue': paystack_calc['net_amount'],
            'fee_percentage': paystack_calc['fee_percentage'],
            'provider': 'paystack',
            'fee_structure': paystack_calc['fee_structure'],
            'fc_rate': naira_amount / fc_amount if fc_amount > 0 else 0
        }
    
    @classmethod
    def calculate_subscription_fees(cls, subscription_amount: float) -> Dict[str, Any]:
        """
        Calculate fees for subscription purchase via Paystack
        
        Args:
            subscription_amount: Subscription amount in Naira
            
        Returns:
            Dict with Paystack fee and net revenue
        """
        paystack_calc = cls.calculate_fee(subscription_amount, 'paystack')
        
        return {
            'gross_revenue': subscription_amount,
            'gateway_fee': paystack_calc['gateway_fee'],
            'net_revenue': paystack_calc['net_amount'],
            'fee_percentage': paystack_calc['fee_percentage'],
            'provider': 'paystack',
            'fee_structure': paystack_calc['fee_structure']
        }
    
    @classmethod
    def get_provider_info(cls, provider: str) -> Dict[str, Any]:
        """
        Get fee structure information for a provider
        
        Args:
            provider: Provider name
            
        Returns:
            Dict with provider fee structure details
        """
        if provider not in cls.FEE_STRUCTURES:
            raise ValueError(f"Unknown provider: {provider}")
        
        return cls.FEE_STRUCTURES[provider].copy()
    
    @classmethod
    def get_all_providers(cls) -> Dict[str, str]:
        """
        Get all available providers and their descriptions
        
        Returns:
            Dict mapping provider names to descriptions
        """
        return {
            provider: structure['description'] 
            for provider, structure in cls.FEE_STRUCTURES.items()
        }


# Convenience functions for backward compatibility
def calculate_paystack_fee(amount: float) -> Tuple[float, float]:
    """
    Calculate Paystack fee (backward compatibility)
    
    Returns:
        Tuple of (gateway_fee, net_amount)
    """
    calc = GatewayFeeCalculator.calculate_fee(amount, 'paystack')
    return calc['gateway_fee'], calc['net_amount']


def calculate_monnify_fee(amount: float) -> Tuple[float, float]:
    """
    Calculate Monnify fee (backward compatibility)
    
    Returns:
        Tuple of (gateway_fee, net_amount)
    """
    calc = GatewayFeeCalculator.calculate_fee(amount, 'monnify')
    return calc['gateway_fee'], calc['net_amount']


def calculate_vas_service_fee(amount: float) -> float:
    """
    Calculate VAS service fee (backward compatibility)
    
    Returns:
        Service fee amount (₦30)
    """
    calc = GatewayFeeCalculator.calculate_fee(amount, 'vas_transaction')
    return calc['gateway_fee']


# Example usage and testing
if __name__ == "__main__":
    calculator = GatewayFeeCalculator()
    
    print("=== FiCore Gateway Fee Calculator Test ===\n")
    
    # Test Paystack fee (FC purchase)
    print("1. FC Credits Purchase (₦10,000 via Paystack):")
    fc_calc = calculator.calculate_fc_purchase_fees(333.33, 10000)
    print(f"   Gross Revenue: ₦{fc_calc['gross_revenue']:,.2f}")
    print(f"   Gateway Fee: ₦{fc_calc['gateway_fee']:,.2f}")
    print(f"   Net Revenue: ₦{fc_calc['net_revenue']:,.2f}")
    print(f"   Fee %: {fc_calc['fee_percentage']:.2f}%")
    print()
    
    # Test Monnify fee (VAS transaction)
    print("2. VAS Data Purchase (₦1,000 via Monnify):")
    vas_calc = calculator.calculate_vas_fees(1000, 'monnify')
    print(f"   Transaction Amount: ₦{vas_calc['transaction_amount']:,.2f}")
    print(f"   Service Fee (our charge): ₦{vas_calc['service_fee']:,.2f}")
    print(f"   User Pays Total: ₦{vas_calc['user_pays_total']:,.2f}")
    print(f"   Gateway Fee (we pay): ₦{vas_calc['gateway_fee']:,.2f}")
    print(f"   Commission Earned: ₦{vas_calc['commission_earned']:,.2f}")
    print(f"   Our Total Profit: ₦{vas_calc['our_total_profit']:,.2f}")
    print()
    
    # Test subscription fee
    print("3. Subscription Purchase (₦2,000 via Paystack):")
    sub_calc = calculator.calculate_subscription_fees(2000)
    print(f"   Gross Revenue: ₦{sub_calc['gross_revenue']:,.2f}")
    print(f"   Gateway Fee: ₦{sub_calc['gateway_fee']:,.2f}")
    print(f"   Net Revenue: ₦{sub_calc['net_revenue']:,.2f}")
    print(f"   Fee %: {sub_calc['fee_percentage']:.2f}%")
    print()
    
    # Show all providers
    print("4. All Available Providers:")
    for provider, description in calculator.get_all_providers().items():
        print(f"   {provider}: {description}")