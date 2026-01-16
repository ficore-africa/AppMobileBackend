"""
Migration Script: Add Missing Signup Bonus Credits and Transaction Records

This script fixes users who signed up with only 5 FC instead of 10 FC,
and adds the missing transaction record for the signup bonus.

Run this ONCE after deploying the auth.py fix.
"""

from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
DB_NAME = os.getenv('DB_NAME', 'ficore_db')

def migrate_signup_bonuses():
    """
    Find users with 5 FC or less who don't have a signup bonus transaction,
    add 5 FC to their balance, and create the transaction record.
    """
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    print("=" * 60)
    print("FICORE SIGNUP BONUS MIGRATION")
    print("=" * 60)
    print()
    
    # Find users who might need the adjustment
    # Criteria: Users with low FC balance and no signup_bonus transaction
    users_to_check = list(db.users.find({
        'role': 'personal',  # Only personal users, not admins
        'ficoreCreditBalance': {'$lt': 10.0}  # Less than 10 FC
    }))
    
    print(f"Found {len(users_to_check)} users with less than 10 FC")
    print()
    
    migrated_count = 0
    skipped_count = 0
    
    for user in users_to_check:
        user_id = user['_id']
        current_balance = user.get('ficoreCreditBalance', 0.0)
        display_name = user.get('displayName', 'Unknown User')
        email = user.get('email', 'unknown@email.com')
        created_at = user.get('createdAt', datetime.utcnow())
        
        # Check if user already has a signup bonus transaction
        existing_signup_bonus = db.credit_transactions.find_one({
            'userId': user_id,
            'operation': 'signup_bonus'
        })
        
        if existing_signup_bonus:
            print(f"⏭️  SKIP: {display_name} ({email}) - Already has signup bonus")
            skipped_count += 1
            continue
        
        # Check if user is premium (they don't need the adjustment)
        is_subscribed = user.get('isSubscribed', False)
        subscription_end = user.get('subscriptionEndDate')
        if is_subscribed and subscription_end and subscription_end > datetime.utcnow():
            print(f"⏭️  SKIP: {display_name} ({email}) - Premium user")
            skipped_count += 1
            continue
        
        # Calculate how much to add (should bring them to at least 10 FC)
        # If they have 5 FC, add 5 FC
        # If they have less (due to spending), still add 5 FC as the missing bonus
        adjustment_amount = 5.0
        new_balance = current_balance + adjustment_amount
        
        print(f"✅ MIGRATE: {display_name} ({email})")
        print(f"   Current Balance: {current_balance} FC")
        print(f"   Adjustment: +{adjustment_amount} FC")
        print(f"   New Balance: {new_balance} FC")
        
        # Update user balance
        db.users.update_one(
            {'_id': user_id},
            {'$set': {'ficoreCreditBalance': new_balance}}
        )
        
        # Create retroactive signup bonus transaction
        signup_transaction = {
            '_id': ObjectId(),
            'userId': user_id,
            'type': 'credit',
            'amount': 10.0,  # Show full 10 FC bonus
            'description': 'Welcome bonus - Thank you for joining Ficore! (Retroactive adjustment)',
            'operation': 'signup_bonus',
            'balanceBefore': 0.0,  # Retroactive, so show as if it was at signup
            'balanceAfter': 10.0,
            'status': 'completed',
            'createdAt': created_at,  # Use user's signup date
            'metadata': {
                'isWelcomeBonus': True,
                'isEarned': False,
                'source': 'registration',
                'isRetroactive': True,
                'migrationDate': datetime.utcnow(),
                'migrationReason': 'Missing signup bonus transaction - added via migration script'
            }
        }
        db.credit_transactions.insert_one(signup_transaction)
        
        # Create adjustment transaction for the actual balance change
        adjustment_transaction = {
            '_id': ObjectId(),
            'userId': user_id,
            'type': 'credit',
            'amount': adjustment_amount,
            'description': f'Signup bonus adjustment - Missing {adjustment_amount} FC added',
            'operation': 'admin_adjustment',
            'balanceBefore': current_balance,
            'balanceAfter': new_balance,
            'status': 'completed',
            'createdAt': datetime.utcnow(),
            'metadata': {
                'isAdjustment': True,
                'adjustmentReason': 'Missing signup bonus credits',
                'migrationScript': 'migrate_signup_bonus.py'
            }
        }
        db.credit_transactions.insert_one(adjustment_transaction)
        
        migrated_count += 1
        print(f"   ✓ Balance updated")
        print(f"   ✓ Transactions created")
        print()
    
    print("=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"✅ Migrated: {migrated_count} users")
    print(f"⏭️  Skipped: {skipped_count} users")
    print(f"📊 Total Processed: {len(users_to_check)} users")
    print()
    print("All affected users now have:")
    print("  • 10 FC signup bonus transaction in history")
    print("  • +5 FC adjustment added to their balance")
    print("  • Complete transaction audit trail")
    print()
    
    client.close()

if __name__ == '__main__':
    print()
    print("⚠️  WARNING: This script will modify user balances and create transactions.")
    print("⚠️  Make sure you have a database backup before proceeding.")
    print()
    
    confirm = input("Do you want to proceed? (yes/no): ").strip().lower()
    
    if confirm == 'yes':
        migrate_signup_bonuses()
    else:
        print("Migration cancelled.")
