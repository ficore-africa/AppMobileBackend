"""
FC Expiration Manager - Handles expiration of earned FiCore Credits
Recommendation #2: Implement expiration for earned FCs (60 days)
"""

from datetime import datetime, timedelta
from bson import ObjectId
from typing import Dict, Any, List


class FCExpirationManager:
    """
    Manages expiration of earned FiCore Credits
    - Earned FCs expire after 60 days
    - Purchased FCs NEVER expire
    - Runs as background job to clean up expired credits
    """
    
    def __init__(self, mongo):
        self.mongo = mongo
    
    def expire_old_credits(self) -> Dict[str, Any]:
        """
        Find and expire all earned FCs that have passed their expiration date
        Returns summary of expired credits
        """
        now = datetime.utcnow()
        
        # Find all expired earned credit transactions
        expired_transactions = list(self.mongo.db.credit_transactions.find({
            'type': 'credit',
            'isEarned': True,
            'expiresAt': {'$lte': now},
            'status': 'completed',
            'expired': {'$ne': True}  # Not already processed
        }))
        
        total_expired = 0
        users_affected = set()
        expired_details = []
        
        for transaction in expired_transactions:
            user_id = transaction['userId']
            amount = transaction['amount']
            
            # Get current user balance
            user = self.mongo.db.users.find_one({'_id': user_id})
            if not user:
                continue
            
            current_balance = user.get('ficoreCreditBalance', 0.0)
            
            # Only deduct if user has sufficient balance
            # (they might have already spent these credits)
            if current_balance >= amount:
                new_balance = current_balance - amount
                
                # Update user balance
                self.mongo.db.users.update_one(
                    {'_id': user_id},
                    {'$set': {'ficoreCreditBalance': new_balance}}
                )
                
                # Mark transaction as expired
                self.mongo.db.credit_transactions.update_one(
                    {'_id': transaction['_id']},
                    {
                        '$set': {
                            'expired': True,
                            'expiredAt': now,
                            'status': 'expired'
                        }
                    }
                )
                
                # Create expiration transaction record
                expiration_transaction = {
                    '_id': ObjectId(),
                    'userId': user_id,
                    'type': 'debit',
                    'amount': amount,
                    'description': f'Expired earned credits from {transaction.get("description", "bonus")}',
                    'operation': 'fc_expiration',
                    'balanceBefore': current_balance,
                    'balanceAfter': new_balance,
                    'status': 'completed',
                    'createdAt': now,
                    'metadata': {
                        'original_transaction_id': str(transaction['_id']),
                        'original_earned_date': transaction.get('createdAt'),
                        'expiration_reason': 'earned_fc_60day_expiry'
                    }
                }
                self.mongo.db.credit_transactions.insert_one(expiration_transaction)
                
                total_expired += amount
                users_affected.add(str(user_id))
                expired_details.append({
                    'user_id': str(user_id),
                    'amount': amount,
                    'original_description': transaction.get('description'),
                    'earned_date': transaction.get('createdAt'),
                    'expired_date': now
                })
            else:
                # User already spent these credits, just mark as expired
                self.mongo.db.credit_transactions.update_one(
                    {'_id': transaction['_id']},
                    {
                        '$set': {
                            'expired': True,
                            'expiredAt': now,
                            'status': 'expired_already_spent'
                        }
                    }
                )
        
        return {
            'total_expired_fc': total_expired,
            'users_affected_count': len(users_affected),
            'users_affected': list(users_affected),
            'expired_transactions_count': len(expired_transactions),
            'expired_details': expired_details,
            'processed_at': now.isoformat() + 'Z'
        }
    
    def get_user_expiring_credits(self, user_id: ObjectId, days_threshold: int = 7) -> List[Dict[str, Any]]:
        """
        Get list of user's earned FCs that will expire within the threshold
        Used to warn users about upcoming expirations
        """
        now = datetime.utcnow()
        threshold_date = now + timedelta(days=days_threshold)
        
        expiring_transactions = list(self.mongo.db.credit_transactions.find({
            'userId': user_id,
            'type': 'credit',
            'isEarned': True,
            'expiresAt': {
                '$gte': now,
                '$lte': threshold_date
            },
            'status': 'completed',
            'expired': {'$ne': True}
        }).sort('expiresAt', 1))
        
        expiring_credits = []
        for transaction in expiring_transactions:
            days_until_expiry = (transaction['expiresAt'] - now).days
            expiring_credits.append({
                'amount': transaction['amount'],
                'description': transaction.get('description'),
                'earned_date': transaction.get('createdAt').isoformat() + 'Z' if transaction.get('createdAt') else None,
                'expires_at': transaction['expiresAt'].isoformat() + 'Z',
                'days_until_expiry': days_until_expiry
            })
        
        return expiring_credits
    
    def get_user_fc_breakdown(self, user_id: ObjectId) -> Dict[str, Any]:
        """
        Get breakdown of user's FC balance by source (earned vs purchased)
        """
        # Get all active (non-expired) earned credits
        earned_credits = list(self.mongo.db.credit_transactions.find({
            'userId': user_id,
            'type': 'credit',
            'isEarned': True,
            'status': 'completed',
            'expired': {'$ne': True},
            'expiresAt': {'$gte': datetime.utcnow()}
        }))
        
        # Get all purchased credits (no expiration)
        purchased_credits = list(self.mongo.db.credit_transactions.find({
            'userId': user_id,
            'type': 'credit',
            'isEarned': {'$ne': True},
            'status': 'completed'
        }))
        
        # Calculate totals
        total_earned = sum(t['amount'] for t in earned_credits)
        total_purchased = sum(t['amount'] for t in purchased_credits)
        
        # Get user's current balance
        user = self.mongo.db.users.find_one({'_id': user_id})
        current_balance = user.get('ficoreCreditBalance', 0.0) if user else 0.0
        
        return {
            'current_balance': current_balance,
            'earned_fc': total_earned,
            'purchased_fc': total_purchased,
            'earned_credits_count': len(earned_credits),
            'purchased_credits_count': len(purchased_credits),
            'has_expiring_credits': len(earned_credits) > 0
        }


def run_fc_expiration_job(mongo):
    """
    Background job to expire old earned FCs
    Should be run daily via cron job or scheduler
    """
    manager = FCExpirationManager(mongo)
    result = manager.expire_old_credits()
    
    print(f"FC Expiration Job Completed:")
    print(f"  - Total FC Expired: {result['total_expired_fc']}")
    print(f"  - Users Affected: {result['users_affected_count']}")
    print(f"  - Transactions Processed: {result['expired_transactions_count']}")
    
    return result
