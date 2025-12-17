"""
One-time migration: Fix missing 'plan' field in subscriptions collection
Date: December 2, 2025
Issue: Admin grants were not setting the 'plan' field, causing frontend display issues

This migration:
1. Checks if migration already ran (using migration_log collection)
2. Finds all subscriptions with missing 'plan' field
3. Sets 'plan' from user.subscriptionType
4. Marks migration as complete to prevent re-running
"""

from pymongo import MongoClient
from datetime import datetime
import os

MIGRATION_NAME = 'fix_subscription_plan_field_v1'

def run_migration(mongo_uri=None):
    """Run the subscription plan field migration (one-time only)"""
    
    # Use provided URI or get from environment
    if not mongo_uri:
        mongo_uri = os.environ.get('MONGODB_URI') or os.environ.get('MONGO_URI')
    
    if not mongo_uri:
        print("⚠️  No MongoDB URI provided - skipping migration")
        return True  # Return True to not block app startup
    
    print("=" * 80)
    print("SUBSCRIPTION PLAN FIELD MIGRATION")
    print("=" * 80)
    print(f"Migration: {MIGRATION_NAME}")
    print(f"Started at: {datetime.utcnow().isoformat()}Z")
    
    try:
        client = MongoClient(mongo_uri)
        db = client.get_database()  # Gets default database from URI
        
        # Check if migration already ran
        migration_log = db.migration_log.find_one({'migration_name': MIGRATION_NAME})
        
        if migration_log and migration_log.get('status') == 'completed':
            print(f"\n✅ Migration already completed on {migration_log.get('completed_at')}")
            print("   Skipping to prevent duplicate execution")
            client.close()
            return True
        
        # Find all subscriptions with missing or null 'plan' field
        subscriptions_to_fix = list(db.subscriptions.find({
            '$or': [
                {'plan': None},
                {'plan': {'$exists': False}}
            ]
        }))
        
        print(f"\nFound {len(subscriptions_to_fix)} subscriptions with missing 'plan' field")
        
        if len(subscriptions_to_fix) == 0:
            print("✅ No subscriptions need fixing")
            # Mark migration as complete even if nothing to fix
            db.migration_log.insert_one({
                'migration_name': MIGRATION_NAME,
                'status': 'completed',
                'completed_at': datetime.utcnow(),
                'subscriptions_fixed': 0,
                'errors': 0
            })
            client.close()
            return True
        
        fixed_count = 0
        error_count = 0
        fixed_users = []
        
        for subscription in subscriptions_to_fix:
            try:
                user_id = subscription['userId']
                subscription_id = subscription['_id']
                
                # Get user document to find subscriptionType
                user = db.users.find_one({'_id': user_id})
                
                if not user:
                    print(f"⚠️  Subscription {subscription_id}: User not found")
                    error_count += 1
                    continue
                
                subscription_type = user.get('subscriptionType')
                
                # Fallback to planId if subscriptionType is missing
                if not subscription_type:
                    subscription_type = subscription.get('planId')
                
                if not subscription_type:
                    print(f"⚠️  Subscription {subscription_id}: No plan info (user: {user.get('email', 'N/A')})")
                    error_count += 1
                    continue
                
                # Update subscription with plan field
                result = db.subscriptions.update_one(
                    {'_id': subscription_id},
                    {'$set': {
                        'plan': subscription_type,
                        'updatedAt': datetime.utcnow()
                    }}
                )
                
                if result.modified_count > 0:
                    user_email = user.get('email', 'N/A')
                    print(f"✅ Fixed: {user_email} → plan = '{subscription_type}'")
                    fixed_count += 1
                    fixed_users.append(user_email)
                else:
                    print(f"⚠️  Subscription {subscription_id}: No changes made")
                    error_count += 1
                    
            except Exception as e:
                print(f"❌ Error: {str(e)}")
                error_count += 1
        
        # Mark migration as complete
        db.migration_log.insert_one({
            'migration_name': MIGRATION_NAME,
            'status': 'completed',
            'completed_at': datetime.utcnow(),
            'subscriptions_fixed': fixed_count,
            'errors': error_count,
            'fixed_users': fixed_users
        })
        
        print("\n" + "=" * 80)
        print("MIGRATION SUMMARY")
        print("=" * 80)
        print(f"Total found: {len(subscriptions_to_fix)}")
        print(f"Successfully fixed: {fixed_count}")
        print(f"Errors: {error_count}")
        print(f"Completed at: {datetime.utcnow().isoformat()}Z")
        print("\n✅ Migration marked as complete - will not run again")
        
        client.close()
        
        return error_count == 0
        
    except Exception as e:
        print(f"\n❌ MIGRATION FAILED: {str(e)}")
        return False

if __name__ == '__main__':
    # Run migration when script is executed directly
    import sys
    
    mongo_uri = None
    if len(sys.argv) > 1:
        mongo_uri = sys.argv[1]
    
    success = run_migration(mongo_uri)
    sys.exit(0 if success else 1)
