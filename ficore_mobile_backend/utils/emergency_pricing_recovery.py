"""
Emergency Pricing Recovery System
Handles user compensation when emergency fallback pricing is triggered

Strategy: Correction, Compensation, and Communication
- Detect emergency pricing usage
- Calculate overage vs market rates
- Automatically compensate users
- Communicate transparently
"""

from datetime import datetime, timedelta
from bson import ObjectId
import logging
from utils.email_service import get_email_service
from blueprints.notifications import create_user_notification

logger = logging.getLogger(__name__)

class EmergencyPricingRecovery:
    def __init__(self, mongo_db):
        self.mongo = mongo_db
        
        # Recovery thresholds
        self.EMERGENCY_MULTIPLIER = 2.0  # 2x normal pricing
        self.MIN_REFUND_THRESHOLD = 50.0  # Minimum ₦50 overage to trigger refund
        self.MAX_RECOVERY_DAYS = 7  # Process recovery within 7 days
        
        # Compensation strategies
        self.COMPENSATION_METHODS = {
            'wallet_credit': 'Instant wallet credit',
            'next_trade_discount': 'Free fees on next 3 transactions', 
            'loyalty_boost': 'Tier upgrade for 30 days',
            'bonus_credit': 'Stress bonus credit'
        }

    def tag_emergency_transaction(self, transaction_id: str, emergency_cost: float, service_type: str, network: str):
        """
        Tag a transaction that used emergency pricing for later recovery
        """
        try:
            emergency_tag = {
                '_id': ObjectId(),
                'transactionId': ObjectId(transaction_id),
                'emergencyCost': emergency_cost,
                'serviceType': service_type,
                'network': network,
                'emergencyMultiplier': self.EMERGENCY_MULTIPLIER,
                'taggedAt': datetime.utcnow(),
                'status': 'PENDING_RECOVERY',
                'recoveryDeadline': datetime.utcnow() + timedelta(days=self.MAX_RECOVERY_DAYS),
                'metadata': {
                    'reason': 'API_OUTAGE_EMERGENCY_PRICING',
                    'multiplier_used': self.EMERGENCY_MULTIPLIER
                }
            }
            
            self.mongo.emergency_pricing_tags.insert_one(emergency_tag)
            logger.warning(f"🚨 Emergency pricing tagged: Transaction {transaction_id}, Cost: ₦{emergency_cost}")
            
            return str(emergency_tag['_id'])
            
        except Exception as e:
            logger.error(f"Error tagging emergency transaction: {str(e)}")
            return None

    def process_recovery_batch(self, limit: int = 50):
        """
        Process a batch of emergency transactions for recovery
        Run this periodically (every hour) to check for recoverable transactions
        
        CRITICAL: Includes pre-flight API check and memory-efficient processing
        """
        try:
            # 🚨 PRE-FLIGHT CHECK: Verify Peyflex API is stable before processing recoveries
            if not self._verify_api_stability():
                logger.warning("🚨 API still unstable - skipping recovery batch to prevent incorrect calculations")
                return {
                    'status': 'skipped',
                    'reason': 'API_UNSTABLE',
                    'message': 'Recovery skipped - waiting for API stability'
                }
            
            # Get pending recovery transactions with memory-efficient query
            pending_recoveries = list(self.mongo.emergency_pricing_tags.find({
                'status': 'PENDING_RECOVERY',
                'recoveryDeadline': {'$gt': datetime.utcnow()}
            }).limit(limit).hint([('status', 1), ('recoveryDeadline', 1)]))  # Use index hint
            
            logger.info(f"Processing {len(pending_recoveries)} emergency pricing recoveries")
            
            recovery_results = []
            
            for recovery in pending_recoveries:
                try:
                    # 🚨 IDEMPOTENCY PROTECTION: Mark as processing to prevent double-refunds
                    update_result = self.mongo.emergency_pricing_tags.update_one(
                        {'_id': recovery['_id'], 'status': 'PENDING_RECOVERY'},  # Atomic check
                        {'$set': {'status': 'PROCESSING', 'processingStartedAt': datetime.utcnow()}}
                    )
                    
                    # Skip if another process already claimed this recovery
                    if update_result.modified_count == 0:
                        logger.info(f"Recovery {recovery['_id']} already being processed by another instance")
                        continue
                    
                    result = self._process_single_recovery(recovery)
                    recovery_results.append(result)
                    
                except Exception as e:
                    logger.error(f"Error processing recovery {recovery['_id']}: {str(e)}")
                    # Mark as failed and revert from PROCESSING
                    self.mongo.emergency_pricing_tags.update_one(
                        {'_id': recovery['_id']},
                        {'$set': {'status': 'RECOVERY_FAILED', 'error': str(e), 'updatedAt': datetime.utcnow()}}
                    )
            
            return {
                'status': 'completed',
                'total_processed': len(recovery_results),
                'results': recovery_results
            }
            
        except Exception as e:
            logger.error(f"Error in recovery batch processing: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }

    def _verify_api_stability(self) -> bool:
        """
        Pre-flight check: Verify Peyflex API is stable before processing recoveries
        Prevents incorrect refund calculations during ongoing outages
        """
        try:
            from utils.dynamic_pricing_engine import get_pricing_engine
            pricing_engine = get_pricing_engine(self.mongo)
            
            # Test API with a simple MTN airtime rate fetch
            test_rates = pricing_engine.get_peyflex_rates('airtime', 'MTN')
            
            # Check if we got real rates (not emergency fallback)
            mtn_rate = test_rates.get('MTN', {}).get('rate', 1.0)
            
            # If rate is reasonable (0.95-1.05 range), API is stable
            if 0.95 <= mtn_rate <= 1.05:
                logger.info("✅ API stability check passed - proceeding with recovery")
                return True
            else:
                logger.warning(f"⚠️ API returning unusual rates: MTN={mtn_rate} - API may be unstable")
                return False
                
        except Exception as e:
            logger.error(f"❌ API stability check failed: {str(e)}")
            return False

    def _process_single_recovery(self, recovery_tag: dict):
        """
        Process recovery for a single emergency transaction
        CRITICAL: Only processes SUCCESS transactions to prevent double-refunds
        """
        transaction_id = recovery_tag['transactionId']
        emergency_cost = recovery_tag['emergencyCost']
        service_type = recovery_tag['serviceType']
        network = recovery_tag['network']
        
        # Get the original transaction
        transaction = self.mongo.vas_transactions.find_one({'_id': transaction_id})
        if not transaction:
            raise Exception(f"Transaction {transaction_id} not found")
        
        # 🚨 TRANSACTION TYPE FILTER: Only refund SUCCESS transactions
        if transaction.get('status') != 'SUCCESS':
            logger.warning(f"Skipping recovery for non-SUCCESS transaction: {transaction.get('status')}")
            # Mark as no recovery needed
            self.mongo.emergency_pricing_tags.update_one(
                {'_id': recovery_tag['_id']},
                {'$set': {'status': 'NO_RECOVERY_NEEDED', 'reason': f'Transaction status: {transaction.get("status")}', 'updatedAt': datetime.utcnow()}}
            )
            return {'status': 'no_recovery_needed', 'reason': 'transaction_not_successful'}
        
        user_id = transaction['userId']
        user = self.mongo.users.find_one({'_id': user_id})
        if not user:
            raise Exception(f"User {user_id} not found")
        
        # Calculate current market rate (now that API is working)
        try:
            from utils.dynamic_pricing_engine import get_pricing_engine
            pricing_engine = get_pricing_engine(self.mongo)
            
            # Get current market pricing
            if service_type == 'data':
                plan_id = transaction.get('dataPlanId')
                current_pricing = pricing_engine.calculate_selling_price(
                    service_type, network, transaction['amount'], 'basic', plan_id
                )
            else:
                current_pricing = pricing_engine.calculate_selling_price(
                    service_type, network, transaction['amount'], 'basic'
                )
            
            current_market_cost = current_pricing['cost_price']
            current_selling_price = current_pricing['selling_price']
            
        except Exception as e:
            logger.error(f"Could not get current market rate: {str(e)}")
            # 🚨 IMPROVED FALLBACK: Use more conservative estimate
            # Don't assume 2x - use 1.5x to be safer
            estimated_normal_cost = emergency_cost / 1.5  # More conservative than /2.0
            current_market_cost = estimated_normal_cost
            current_selling_price = estimated_normal_cost * 1.1  # Assume 10% margin
            
            logger.warning(f"Using conservative fallback estimate: Emergency ₦{emergency_cost} → Estimated Normal ₦{estimated_normal_cost}")
        
        # Calculate overage
        overage_amount = emergency_cost - current_market_cost
        selling_overage = transaction['sellingPrice'] - current_selling_price
        
        logger.info(f"Recovery calculation: Emergency ₦{emergency_cost} vs Market ₦{current_market_cost}, Overage: ₦{overage_amount}")
        
        # Only process if overage is significant
        if selling_overage < self.MIN_REFUND_THRESHOLD:
            # Mark as no recovery needed
            self.mongo.emergency_pricing_tags.update_one(
                {'_id': recovery_tag['_id']},
                {'$set': {'status': 'NO_RECOVERY_NEEDED', 'reason': 'Below threshold', 'updatedAt': datetime.utcnow()}}
            )
            return {'status': 'no_recovery_needed', 'overage': selling_overage}
        
        # Determine user tier for compensation strategy
        user_tier = 'basic'
        if user.get('subscriptionStatus') == 'active':
            user_tier = user.get('subscriptionPlan', 'premium').lower()
        
        # Apply compensation strategy
        compensation_result = self._apply_compensation(
            user_id, user, selling_overage, user_tier, transaction_id, service_type, network
        )
        
        # Update recovery status
        self.mongo.emergency_pricing_tags.update_one(
            {'_id': recovery_tag['_id']},
            {
                '$set': {
                    'status': 'RECOVERY_COMPLETED',
                    'overage': selling_overage,
                    'compensationMethod': compensation_result['method'],
                    'compensationAmount': compensation_result['amount'],
                    'recoveredAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                }
            }
        )
        
        # Send communication
        self._send_recovery_communication(user, selling_overage, compensation_result, service_type, network)
        
        logger.info(f"✅ Recovery completed for user {user_id}: ₦{selling_overage} via {compensation_result['method']}")
        
        return {
            'status': 'completed',
            'user_id': str(user_id),
            'overage': selling_overage,
            'compensation': compensation_result
        }

    def _apply_compensation(self, user_id: ObjectId, user: dict, overage: float, user_tier: str, transaction_id: ObjectId, service_type: str, network: str):
        """
        Apply appropriate compensation based on user tier and overage amount
        """
        try:
            # Strategy selection based on overage amount and user tier
            if overage >= 200:  # Large overage
                if user_tier == 'gold':
                    return self._apply_wallet_credit_plus_bonus(user_id, overage)
                else:
                    return self._apply_wallet_credit(user_id, overage)
            
            elif overage >= 100:  # Medium overage
                if user_tier in ['premium', 'gold']:
                    return self._apply_wallet_credit(user_id, overage)
                else:
                    return self._apply_next_trade_discount(user_id, overage)
            
            else:  # Small overage (₦50-99)
                return self._apply_next_trade_discount(user_id, overage)
                
        except Exception as e:
            logger.error(f"Error applying compensation: {str(e)}")
            # Fallback to wallet credit
            return self._apply_wallet_credit(user_id, overage)

    def _apply_wallet_credit(self, user_id: ObjectId, amount: float):
        """
        Apply instant wallet credit compensation
        CRITICAL: Includes idempotency protection against double-credits
        """
        try:
            # 🚨 IDEMPOTENCY CHECK: Prevent double-credits
            existing_credit = self.mongo.vas_transactions.find_one({
                'userId': user_id,
                'type': 'EMERGENCY_RECOVERY_CREDIT',
                'amount': amount,
                'createdAt': {'$gte': datetime.utcnow() - timedelta(hours=1)}  # Within last hour
            })
            
            if existing_credit:
                logger.warning(f"Duplicate credit attempt blocked for user {user_id}: ₦{amount}")
                return {
                    'method': 'wallet_credit',
                    'amount': amount,
                    'new_balance': 0,  # Will be updated below
                    'message': f'₦{amount:.0f} already credited to your Liquid Wallet',
                    'duplicate_prevented': True
                }
            
            # Credit the VAS wallet
            wallet = self.mongo.vas_wallets.find_one({'userId': user_id})
            if wallet:
                new_balance = wallet.get('balance', 0.0) + amount
                
                # 🚨 ATOMIC UPDATE: Prevent race conditions
                update_result = self.mongo.vas_wallets.update_one(
                    {'userId': user_id, 'balance': wallet.get('balance', 0.0)},  # Optimistic locking
                    {'$set': {'balance': new_balance, 'updatedAt': datetime.utcnow()}}
                )
                
                if update_result.modified_count == 0:
                    # Balance changed between read and write - retry once
                    wallet = self.mongo.vas_wallets.find_one({'userId': user_id})
                    new_balance = wallet.get('balance', 0.0) + amount
                    self.mongo.vas_wallets.update_one(
                        {'userId': user_id},
                        {'$set': {'balance': new_balance, 'updatedAt': datetime.utcnow()}}
                    )
                
                # Record the credit transaction with unique identifier
                credit_transaction = {
                    '_id': ObjectId(),
                    'userId': user_id,
                    'type': 'EMERGENCY_RECOVERY_CREDIT',
                    'amount': amount,
                    'description': f'Price protection adjustment',
                    'status': 'SUCCESS',
                    'transactionReference': f'recovery_{user_id}_{int(datetime.utcnow().timestamp())}',  # CRITICAL: Add this field for unique index
                    'createdAt': datetime.utcnow(),
                    'metadata': {
                        'reason': 'EMERGENCY_PRICING_COMPENSATION',
                        'compensation_type': 'wallet_credit',
                        'idempotency_key': f'recovery_{user_id}_{int(datetime.utcnow().timestamp())}'
                    }
                }
                self.mongo.vas_transactions.insert_one(credit_transaction)
                
                return {
                    'method': 'wallet_credit',
                    'amount': amount,
                    'new_balance': new_balance,
                    'message': f'₦{amount:.0f} credited to your Liquid Wallet'
                }
            
            raise Exception("Wallet not found")
            
        except Exception as e:
            logger.error(f"Error applying wallet credit: {str(e)}")
            raise

    def _apply_wallet_credit_plus_bonus(self, user_id: ObjectId, overage: float):
        """Apply wallet credit plus bonus for high-tier users with large overages"""
        try:
            # Base credit + 50% bonus for Gold users
            bonus_amount = overage * 0.5
            total_credit = overage + bonus_amount
            
            result = self._apply_wallet_credit(user_id, total_credit)
            result['method'] = 'wallet_credit_plus_bonus'
            result['bonus_amount'] = bonus_amount
            result['message'] = f'₦{overage:.0f} recovery + ₦{bonus_amount:.0f} Gold member bonus credited'
            
            return result
            
        except Exception as e:
            logger.error(f"Error applying wallet credit plus bonus: {str(e)}")
            # Fallback to regular credit
            return self._apply_wallet_credit(user_id, overage)

    def _apply_next_trade_discount(self, user_id: ObjectId, overage: float):
        """Apply free fees on next transactions"""
        try:
            # Calculate number of free transactions based on overage
            free_transactions = min(5, max(2, int(overage / 30)))  # 2-5 free transactions
            
            # Create discount voucher
            voucher = {
                '_id': ObjectId(),
                'userId': user_id,
                'type': 'EMERGENCY_RECOVERY_DISCOUNT',
                'discountType': 'FREE_FEES',
                'remainingUses': free_transactions,
                'originalAmount': overage,
                'description': f'Free fees on next {free_transactions} VAS transactions',
                'status': 'ACTIVE',
                'expiresAt': datetime.utcnow() + timedelta(days=30),
                'createdAt': datetime.utcnow(),
                'metadata': {
                    'reason': 'EMERGENCY_PRICING_COMPENSATION',
                    'compensation_type': 'next_trade_discount'
                }
            }
            
            self.mongo.user_vouchers.insert_one(voucher)
            
            return {
                'method': 'next_trade_discount',
                'amount': overage,
                'free_transactions': free_transactions,
                'voucher_id': str(voucher['_id']),
                'message': f'Free fees on your next {free_transactions} transactions (worth ₦{overage:.0f}+)'
            }
            
        except Exception as e:
            logger.error(f"Error applying next trade discount: {str(e)}")
            # Fallback to wallet credit
            return self._apply_wallet_credit(user_id, overage)

    def _send_recovery_communication(self, user: dict, overage: float, compensation: dict, service_type: str, network: str):
        """
        Send transparent communication about the recovery
        """
        try:
            user_id = str(user['_id'])
            user_name = user.get('displayName') or f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
            
            # Create in-app notification
            notification_title = "💰 Price Protection Adjustment"
            notification_body = f"We've automatically adjusted your account for market rate differences. {compensation['message']}"
            
            notification_id = create_user_notification(
                mongo=self.mongo,
                user_id=user_id,
                category='wallet',
                title=notification_title,
                body=notification_body,
                related_id=compensation.get('voucher_id', ''),
                metadata={
                    'compensation_type': compensation['method'],
                    'overage_amount': overage,
                    'compensation_amount': compensation['amount'],
                    'service_type': service_type,
                    'network': network,
                    'adjustment_reason': 'automated_market_rate_correction'
                },
                priority='high'
            )
            
            # Send email if available
            if user.get('email'):
                try:
                    email_service = get_email_service()
                    
                    email_data = {
                        'user_name': user_name,
                        'service': f"{network} {service_type.title()}",
                        'overage_amount': f"{overage:.0f}",
                        'compensation_method': compensation['method'].replace('_', ' ').title(),
                        'compensation_message': compensation['message'],
                        'date': datetime.utcnow().strftime('%B %d, %Y at %I:%M %p'),
                        'explanation': 'During a brief system maintenance period, your transaction used backup pricing to ensure completion. We\'ve automatically adjusted your account to reflect current market rates.'
                    }
                    
                    email_result = email_service.send_emergency_recovery_email(
                        to_email=user['email'],
                        email_data=email_data
                    )
                    
                    logger.info(f"Recovery email sent: {email_result.get('success', False)} to {user['email']}")
                    
                except Exception as e:
                    logger.error(f"Failed to send recovery email: {str(e)}")
            
            logger.info(f"Recovery communication sent to user {user_id}")
            
        except Exception as e:
            logger.error(f"Error sending recovery communication: {str(e)}")

    def get_recovery_stats(self, days: int = 30):
        """
        Get recovery statistics for monitoring
        CRITICAL: Uses allow_disk_use=True for large collections
        """
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            pipeline = [
                {'$match': {'taggedAt': {'$gte': start_date}}},
                {'$group': {
                    '_id': '$status',
                    'count': {'$sum': 1},
                    'total_overage': {'$sum': '$overage'},
                    'avg_overage': {'$avg': '$overage'}
                }}
            ]
            
            # CRITICAL: Use allow_disk_use=True for large collections
            stats = list(self.mongo.emergency_pricing_tags.aggregate(
                pipeline, 
                allowDiskUse=True,
                maxTimeMS=30000  # 30 second timeout
            ))
            
            return {
                'period_days': days,
                'stats': stats,
                'generated_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error getting recovery stats: {str(e)}")
            return {
                'period_days': days,
                'stats': [],
                'generated_at': datetime.utcnow(),
                'error': str(e)
            }

# Utility functions
def tag_emergency_transaction(mongo_db, transaction_id: str, emergency_cost: float, service_type: str, network: str):
    """Quick function to tag emergency transactions"""
    recovery_system = EmergencyPricingRecovery(mongo_db)
    return recovery_system.tag_emergency_transaction(transaction_id, emergency_cost, service_type, network)

def process_emergency_recoveries(mongo_db, limit: int = 50):
    """Quick function to process recovery batch"""
    recovery_system = EmergencyPricingRecovery(mongo_db)
    return recovery_system.process_recovery_batch(limit)