"""
Treasury Management System - Triple-Layer Reconciliation
Ensures FiCore's custodial wallet system maintains 100% integrity

Layer 1: Bank (Cash Assets) - Physical Naira available
Layer 2: Users (Wallet Liability) - Money owed to users
Layer 3: Providers (Operational Float) - Stock available for purchases

Golden Equation: Bank Cash >= User Wallets + Reserved Amounts
"""

from datetime import datetime, timedelta
from bson import ObjectId
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class TreasuryManager:
    """
    Manages FiCore's custodial wallet system with triple-layer reconciliation
    Reuses existing infrastructure: reservedAmount, NEEDS_RECONCILIATION
    """
    
    def __init__(self, mongo_db):
        self.mongo = mongo_db
    
    # ============================================================================
    # LAYER 1: BANK CASH (Physical Assets)
    # ============================================================================
    
    def get_bank_cash_position(self):
        """
        Get total cash in bank accounts (Monnify, physical bank)
        This is manually tracked in business_account incomes/expenses
        
        Returns:
            dict: {
                'total_cash': float,
                'monnify_float': float,
                'physical_bank': float,
                'last_updated': datetime
            }
        """
        try:
            # Get business account ID
            business_account = self.mongo.users.find_one({'email': 'ficoreafrica@gmail.com'})
            if not business_account:
                return {'error': 'Business account not found'}
            
            business_id = business_account['_id']
            
            # Calculate total cash from business bookkeeping
            # Cash = Opening Balance + Income - Expenses - Drawings
            
            # Get all income (including capital contributions)
            total_income = 0.0
            incomes = self.mongo.incomes.find({
                'userId': business_id,
                'status': 'active',
                'isDeleted': False
            })
            for income in incomes:
                amount = income.get('amount', 0)
                if hasattr(amount, 'to_decimal'):
                    amount = float(amount.to_decimal())
                total_income += float(amount)
            
            # Get all expenses (excluding drawings)
            total_expenses = 0.0
            expenses = self.mongo.expenses.find({
                'userId': business_id,
                'status': 'active',
                'isDeleted': False,
                'category': {'$ne': 'Drawings'}  # Exclude drawings
            })
            for expense in expenses:
                amount = expense.get('amount', 0)
                if hasattr(amount, 'to_decimal'):
                    amount = float(amount.to_decimal())
                total_expenses += float(amount)
            
            # Get drawings separately
            total_drawings = 0.0
            drawings = self.mongo.expenses.find({
                'userId': business_id,
                'status': 'active',
                'isDeleted': False,
                'category': 'Drawings'
            })
            for drawing in drawings:
                amount = drawing.get('amount', 0)
                if hasattr(amount, 'to_decimal'):
                    amount = float(amount.to_decimal())
                total_drawings += float(amount)
            
            # Calculate net cash position
            # Cash = Income - Expenses - Drawings
            total_cash = total_income - total_expenses - total_drawings
            
            # Get provider floats (operational cash)
            peyflex_balance = self.mongo.provider_balances.find_one({'provider': 'peyflex'})
            monnify_balance = self.mongo.provider_balances.find_one({'provider': 'monnify'})
            
            peyflex_float = float(peyflex_balance.get('balance', 0)) if peyflex_balance else 0.0
            monnify_float = float(monnify_balance.get('balance', 0)) if monnify_balance else 0.0
            
            return {
                'total_cash': total_cash,
                'breakdown': {
                    'total_income': total_income,
                    'total_expenses': total_expenses,
                    'total_drawings': total_drawings,
                    'net_cash': total_cash
                },
                'provider_floats': {
                    'peyflex': peyflex_float,
                    'monnify': monnify_float,
                    'total': peyflex_float + monnify_float
                },
                'last_updated': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting bank cash position: {str(e)}")
            return {'error': str(e)}
    
    # ============================================================================
    # LAYER 2: USER WALLETS (Liabilities)
    # ============================================================================
    
    def get_user_wallet_liability(self):
        """
        Get FiCore's REAL liability - money users deposited that they haven't spent yet
        
        This includes:
        1. Wallet balances (money deposited via Monnify, not yet spent on VAS)
        2. Active subscriptions (users paid, we owe them subscription period)
        3. FC Credits outstanding (users bought FCs, haven't consumed yet)
        
        Note: The 4 wallet balance fields are mirrors (should be same value), count only once.
        
        Returns:
            dict: {
                'total_liability': float,
                'wallet_liability': float,
                'subscription_liability': float,
                'fc_credits_liability': float,
                'breakdown': {...},
                'last_updated': datetime
            }
        """
        try:
            # 1. WALLET LIABILITY (use vas_wallets.balance as primary source)
            pipeline_vas = [
                {
                    '$group': {
                        '_id': None,
                        'total_balance': {'$sum': '$balance'},
                        'total_reserved': {'$sum': '$reservedAmount'}
                    }
                }
            ]
            
            result_vas = list(self.mongo.vas_wallets.aggregate(pipeline_vas))
            
            if result_vas:
                wallet_liability = float(result_vas[0].get('total_balance', 0))
                total_reserved = float(result_vas[0].get('total_reserved', 0))
            else:
                wallet_liability = 0.0
                total_reserved = 0.0
            
            # 2. SUBSCRIPTION LIABILITY (active subscriptions not yet expired)
            # Users paid for subscriptions, we owe them the subscription period
            active_subscriptions = list(self.mongo.subscriptions.find({
                'status': 'active',
                'endDate': {'$gt': datetime.utcnow()}
            }))
            
            subscription_liability = 0.0
            subscription_count = 0
            for sub in active_subscriptions:
                # Calculate remaining value of subscription
                amount_paid = sub.get('amountPaid', 0)
                if hasattr(amount_paid, 'to_decimal'):
                    amount_paid = float(amount_paid.to_decimal())
                
                # For simplicity, count full subscription value as liability
                # (More accurate would be pro-rated based on days remaining)
                subscription_liability += float(amount_paid)
                subscription_count += 1
            
            # 3. FC CREDITS LIABILITY (outstanding FC credits not yet consumed)
            # Users bought FCs, we owe them the credit value
            pipeline_credits = [
                {
                    '$group': {
                        '_id': None,
                        'total_fc_outstanding': {'$sum': '$ficoreCreditBalance'}
                    }
                }
            ]
            
            result_credits = list(self.mongo.users.aggregate(pipeline_credits))
            
            if result_credits:
                total_fc_outstanding = float(result_credits[0].get('total_fc_outstanding', 0))
            else:
                total_fc_outstanding = 0.0
            
            # Convert FCs to Naira value (₦30 per FC as per golden rules)
            NAIRA_PER_FC = 30.0
            fc_credits_liability = total_fc_outstanding * NAIRA_PER_FC
            
            # TOTAL LIABILITY = Wallet + Subscriptions + FC Credits
            total_liability = wallet_liability + subscription_liability + fc_credits_liability
            
            return {
                'total_liability': total_liability,
                'wallet_liability': wallet_liability,
                'subscription_liability': subscription_liability,
                'fc_credits_liability': fc_credits_liability,
                'breakdown': {
                    'wallet': {
                        'balance': wallet_liability,
                        'reserved': total_reserved,
                        'description': 'Money deposited via Monnify, not yet spent on VAS'
                    },
                    'subscriptions': {
                        'liability': subscription_liability,
                        'active_count': subscription_count,
                        'description': 'Active subscriptions users paid for'
                    },
                    'fc_credits': {
                        'total_fcs': total_fc_outstanding,
                        'naira_value': fc_credits_liability,
                        'rate': NAIRA_PER_FC,
                        'description': 'FC Credits users bought but haven\'t consumed'
                    }
                },
                'last_updated': datetime.utcnow()
            }
                
        except Exception as e:
            logger.error(f"❌ Error getting user wallet liability: {str(e)}")
            return {'error': str(e)}
    
    # ============================================================================
    # LAYER 3: PROVIDER FLOAT (Operational Stock)
    # ============================================================================
    
    def get_provider_float_status(self):
        """
        Get provider float status (Peyflex, Monnify)
        This tells us if we have enough "stock" to fulfill user requests
        
        Returns:
            dict: {
                'peyflex': {...},
                'monnify': {...},
                'total_float': float,
                'last_updated': datetime
            }
        """
        try:
            providers = ['peyflex', 'monnify']
            provider_data = {}
            total_float = 0.0
            
            for provider in providers:
                balance_entry = self.mongo.provider_balances.find_one({'provider': provider})
                
                if balance_entry:
                    balance = float(balance_entry.get('balance', 0))
                    last_updated = balance_entry.get('lastUpdated')
                    updated_by = balance_entry.get('updatedBy', 'Unknown')
                    
                    # Calculate time since last update
                    hours_since_update = 999
                    if last_updated:
                        time_diff = datetime.utcnow() - last_updated
                        hours_since_update = time_diff.total_seconds() / 3600
                    
                    # Determine health status
                    if balance < 5000:
                        health = 'CRITICAL'
                    elif balance < 10000:
                        health = 'WARNING'
                    elif hours_since_update > 24:
                        health = 'STALE'
                    else:
                        health = 'HEALTHY'
                    
                    provider_data[provider] = {
                        'balance': balance,
                        'health': health,
                        'last_updated': last_updated,
                        'hours_since_update': round(hours_since_update, 1),
                        'updated_by': updated_by
                    }
                    
                    total_float += balance
                else:
                    provider_data[provider] = {
                        'balance': 0.0,
                        'health': 'UNKNOWN',
                        'last_updated': None,
                        'hours_since_update': 999,
                        'updated_by': 'Never updated'
                    }
            
            return {
                'providers': provider_data,
                'total_float': total_float,
                'last_checked': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting provider float status: {str(e)}")
            return {'error': str(e)}
    
    # ============================================================================
    # TRIPLE-LAYER RECONCILIATION
    # ============================================================================
    
    def check_treasury_integrity(self):
        """
        Perform triple-layer reconciliation check
        
        Golden Equation: Bank Cash >= User Wallets + Reserved Amounts
        
        Returns:
            dict: {
                'status': 'HEALTHY' | 'WARNING' | 'CRITICAL',
                'layer1_bank': {...},
                'layer2_users': {...},
                'layer3_providers': {...},
                'reconciliation': {...},
                'alerts': [...]
            }
        """
        try:
            # Get all three layers
            layer1 = self.get_bank_cash_position()
            layer2 = self.get_user_wallet_liability()
            layer3 = self.get_provider_float_status()
            
            # Check for errors
            if 'error' in layer1 or 'error' in layer2 or 'error' in layer3:
                return {
                    'status': 'ERROR',
                    'message': 'Failed to retrieve treasury data',
                    'errors': {
                        'layer1': layer1.get('error'),
                        'layer2': layer2.get('error'),
                        'layer3': layer3.get('error')
                    }
                }
            
            # Extract key values
            bank_cash = layer1.get('total_cash', 0)
            user_liability = layer2.get('total_liability', 0)
            provider_float = layer3.get('total_float', 0)
            
            # Calculate collateralization ratio
            # How much cash we have vs how much we owe users
            if user_liability > 0:
                collateralization_ratio = (bank_cash / user_liability) * 100
            else:
                collateralization_ratio = 100.0  # No liability = fully collateralized
            
            # Calculate operational coverage
            # How much provider float we have vs user liability
            if user_liability > 0:
                operational_coverage = (provider_float / user_liability) * 100
            else:
                operational_coverage = 100.0
            
            # Determine overall status
            alerts = []
            
            # Check collateralization
            if bank_cash < user_liability:
                status = 'CRITICAL'
                alerts.append({
                    'level': 'CRITICAL',
                    'message': f'Under-collateralized! Bank cash (₦{bank_cash:,.2f}) < User liability (₦{user_liability:,.2f})',
                    'action': 'URGENT: Deposit funds to bank immediately'
                })
            elif collateralization_ratio < 110:
                status = 'WARNING'
                alerts.append({
                    'level': 'WARNING',
                    'message': f'Low collateralization ratio: {collateralization_ratio:.1f}%',
                    'action': 'Consider depositing additional funds'
                })
            else:
                status = 'HEALTHY'
            
            # Check provider float
            if provider_float < 5000:
                alerts.append({
                    'level': 'CRITICAL',
                    'message': f'Provider float critically low: ₦{provider_float:,.2f}',
                    'action': 'URGENT: Fund provider wallets immediately'
                })
                if status == 'HEALTHY':
                    status = 'WARNING'
            elif provider_float < user_liability:
                alerts.append({
                    'level': 'WARNING',
                    'message': f'Provider float (₦{provider_float:,.2f}) < User liability (₦{user_liability:,.2f})',
                    'action': 'Fund provider wallets to match user demand'
                })
            
            # Check for stale provider balances
            for provider, data in layer3.get('providers', {}).items():
                if data.get('hours_since_update', 999) > 24:
                    alerts.append({
                        'level': 'INFO',
                        'message': f'{provider.capitalize()} balance not updated in {data["hours_since_update"]:.1f} hours',
                        'action': f'Check {provider.capitalize()} dashboard and update balance'
                    })
            
            return {
                'status': status,
                'timestamp': datetime.utcnow(),
                'layer1_bank': layer1,
                'layer2_users': layer2,
                'layer3_providers': layer3,
                'reconciliation': {
                    'bank_cash': bank_cash,
                    'user_liability': user_liability,
                    'provider_float': provider_float,
                    'collateralization_ratio': round(collateralization_ratio, 2),
                    'operational_coverage': round(operational_coverage, 2),
                    'surplus_deficit': bank_cash - user_liability
                },
                'alerts': alerts
            }
            
        except Exception as e:
            logger.error(f"❌ Error checking treasury integrity: {str(e)}")
            return {
                'status': 'ERROR',
                'message': str(e),
                'timestamp': datetime.utcnow()
            }
    
    # ============================================================================
    # SUSPENSE ACCOUNT (Reusing NEEDS_RECONCILIATION)
    # ============================================================================
    
    def get_suspense_transactions(self):
        """
        Get transactions in suspense (NEEDS_RECONCILIATION status)
        These are transactions where outcome is unclear and need manual review
        
        Returns:
            dict: {
                'count': int,
                'total_amount': float,
                'transactions': [...]
            }
        """
        try:
            # Find all transactions needing reconciliation (not dismissed)
            suspense_txns = list(self.mongo.vas_transactions.find({
                'status': 'NEEDS_RECONCILIATION',
                'reconciliationDismissed': {'$ne': True}
            }).sort('createdAt', -1))
            
            total_amount = 0.0
            for txn in suspense_txns:
                amount = txn.get('amount', 0)
                if hasattr(amount, 'to_decimal'):
                    amount = float(amount.to_decimal())
                total_amount += float(amount)
            
            return {
                'count': len(suspense_txns),
                'total_amount': total_amount,
                'transactions': suspense_txns
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting suspense transactions: {str(e)}")
            return {'error': str(e)}
    
    def get_reserved_amounts_breakdown(self):
        """
        Get breakdown of reserved amounts by user
        Shows which users have pending transactions
        
        Returns:
            dict: {
                'total_reserved': float,
                'users_with_reservations': int,
                'breakdown': [...]
            }
        """
        try:
            # Find all wallets with reserved amounts > 0
            wallets_with_reservations = list(self.mongo.vas_wallets.find({
                'reservedAmount': {'$gt': 0}
            }))
            
            total_reserved = 0.0
            breakdown = []
            
            for wallet in wallets_with_reservations:
                user_id = wallet.get('userId')
                reserved = float(wallet.get('reservedAmount', 0))
                total_reserved += reserved
                
                # Get user details
                user = self.mongo.users.find_one({'_id': user_id})
                user_email = user.get('email', 'Unknown') if user else 'Unknown'
                
                # Get pending transactions for this user
                pending_txns = list(self.mongo.vas_transactions.find({
                    'userId': user_id,
                    'status': 'PENDING'
                }))
                
                breakdown.append({
                    'user_id': str(user_id),
                    'user_email': user_email,
                    'reserved_amount': reserved,
                    'pending_transactions': len(pending_txns)
                })
            
            return {
                'total_reserved': total_reserved,
                'users_with_reservations': len(breakdown),
                'breakdown': breakdown
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting reserved amounts breakdown: {str(e)}")
            return {'error': str(e)}
