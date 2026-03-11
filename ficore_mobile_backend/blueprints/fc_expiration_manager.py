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
        Get breakdown of user's FC balance by source
        Mirrors the detailed breakdown used in credits report
        
        Categories:
        1. Purchased - Bought FCs (never expire)
        2. Signup Bonus - 1000 FC welcome bonus (earned, expires)
        3. Rewards - From rewards screen (earned, expires)
        4. Tax Education - From tax modules (earned, expires)
        5. Other - Everything else (earned, expires)
        """
        try:
            # 1. PURCHASED CREDITS (never expire)
            purchased_credits = list(self.mongo.db.credit_transactions.aggregate([
                {
                    '$match': {
                        'userId': user_id,
                        'type': 'credit',
                        'operation': 'purchase'
                    }
                },
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ]))
            purchased_amount = purchased_credits[0]['total'] if purchased_credits else 0.0
            
            # 2. SIGNUP BONUS (earned, expires)
            signup_bonus = list(self.mongo.db.credit_transactions.aggregate([
                {
                    '$match': {
                        'userId': user_id,
                        'type': 'credit',
                        'operation': 'signup_bonus'
                    }
                },
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ]))
            signup_bonus_amount = signup_bonus[0]['total'] if signup_bonus else 0.0
            
            # 3. REWARDS SCREEN (engagement, streaks, exploration) (earned, expires)
            rewards_credits = list(self.mongo.db.credit_transactions.aggregate([
                {
                    '$match': {
                        'userId': user_id,
                        'type': 'credit',
                        '$or': [
                            {'operation': 'engagement_reward'},
                            {'operation': 'streak_milestone'},
                            {'operation': 'exploration_bonus'},
                            {'operation': 'profile_completion'},
                            {'description': {'$regex': 'reward|streak|exploration|milestone', '$options': 'i'}}
                        ]
                    }
                },
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ]))
            rewards_amount = rewards_credits[0]['total'] if rewards_credits else 0.0
            
            # 4. TAX EDUCATION MODULES (earned, expires)
            tax_education_credits = list(self.mongo.db.credit_transactions.aggregate([
                {
                    '$match': {
                        'userId': user_id,
                        'type': 'credit',
                        '$or': [
                            {'operation': 'tax_education_progress'},
                            {'description': {'$regex': 'tax education|tax module', '$options': 'i'}}
                        ]
                    }
                },
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ]))
            tax_education_amount = tax_education_credits[0]['total'] if tax_education_credits else 0.0
            
            # Get total credits to calculate "other"
            total_credits = list(self.mongo.db.credit_transactions.aggregate([
                {
                    '$match': {
                        'userId': user_id,
                        'type': 'credit'
                    }
                },
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ]))
            total_credits_amount = total_credits[0]['total'] if total_credits else 0.0
            
            # 5. OTHER (referral bonuses, admin awards, etc.) (earned, expires)
            other_amount = total_credits_amount - (purchased_amount + signup_bonus_amount + rewards_amount + tax_education_amount)
            if other_amount < 0:
                other_amount = 0.0
            
            # Calculate earned vs purchased totals
            total_earned = signup_bonus_amount + rewards_amount + tax_education_amount + other_amount
            total_purchased = purchased_amount
            
            # Get user's current balance
            user = self.mongo.db.users.find_one({'_id': user_id})
            current_balance = user.get('ficoreCreditBalance', 0.0) if user else 0.0
            
            return {
                'current_balance': current_balance,
                'earned_fc': total_earned,
                'purchased_fc': total_purchased,
                # Detailed breakdown
                'breakdown': {
                    'purchased': purchased_amount,
                    'signup_bonus': signup_bonus_amount,
                    'rewards': rewards_amount,
                    'tax_education': tax_education_amount,
                    'other': other_amount
                },
                'has_expiring_credits': total_earned > 0
            }
            
        except Exception as e:
            print(f"Error in get_user_fc_breakdown: {str(e)}")
            # Fallback to simple calculation
            user = self.mongo.db.users.find_one({'_id': user_id})
            current_balance = user.get('ficoreCreditBalance', 0.0) if user else 0.0
            
            return {
                'current_balance': current_balance,
                'earned_fc': current_balance,  # Assume all earned if error
                'purchased_fc': 0.0,
                'breakdown': {
                    'purchased': 0.0,
                    'signup_bonus': 0.0,
                    'rewards': 0.0,
                    'tax_education': 0.0,
                    'other': current_balance
                },
                'has_expiring_credits': True
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
