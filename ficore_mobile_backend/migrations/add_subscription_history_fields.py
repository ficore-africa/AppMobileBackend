"""
Migration: Add Subscription History Fields
Adds new historical tracking fields to existing users
"""

from datetime import datetime
from pymongo import MongoClient
import os


def migrate_subscription_history_fields(mongo_uri):
    """
    Add subscription history fields to existing users.
    This migration is safe to run multiple times (idempotent).
    """
    print("Starting subscription history fields migration...")
    
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    # Step 1: Add wasPremium flag to users who have subscriptionType but isSubscribed=False
    result1 = db.users.update_many(
        {
            'isSubscribed': False,
            'subscriptionType': {'$ne': None},
            'wasPremium': {'$exists': False}
        },
        {
            '$set': {
                'wasPremium': True,
                'totalPremiumDays': 0,
                'premiumExpiryCount': 0,
                'subscriptionHistory': []
            }
        }
    )
    print(f"✅ Added wasPremium flag to {result1.modified_count} users")
    
    # Step 2: Initialize fields for currently premium users
    result2 = db.users.update_many(
        {
            'isSubscribed': True,
            'totalPremiumDays': {'$exists': False}
        },
        {
            '$set': {
                'totalPremiumDays': 0,
                'premiumExpiryCount': 0,
                'subscriptionHistory': []
            }
        }
    )
    print(f"✅ Initialized fields for {result2.modified_count} premium users")
    
    # Step 3: Initialize fields for free users who never had premium
    result3 = db.users.update_many(
        {
            'isSubscribed': False,
            'subscriptionType': None,
            'totalPremiumDays': {'$exists': False}
        },
        {
            '$set': {
                'wasPremium': False,
                'totalPremiumDays': 0,
                'premiumExpiryCount': 0,
                'subscriptionHistory': []
            }
        }
    )
    print(f"✅ Initialized fields for {result3.modified_count} free users")
    
    # Step 4: Create indexes for new fields
    try:
        db.users.create_index([('wasPremium', 1)], name='was_premium_index')
        db.users.create_index([('lastPremiumDate', -1)], name='last_premium_date_desc')
        print("✅ Created indexes for new fields")
    except Exception as e:
        print(f"⚠️  Index creation warning: {str(e)}")
    
    # Step 5: Create notifications collection with indexes
    try:
        db.create_collection('notifications')
        db.notifications.create_index([('userId', 1), ('sentAt', -1)], name='user_sent_desc')
        db.notifications.create_index([('type', 1), ('sentAt', -1)], name='type_sent_desc')
        print("✅ Created notifications collection with indexes")
    except Exception as e:
        print(f"⚠️  Notifications collection already exists or error: {str(e)}")
    
    # Step 6: Create system_alerts collection
    try:
        db.create_collection('system_alerts')
        db.system_alerts.create_index([('type', 1), ('timestamp', -1)], name='type_timestamp_desc')
        db.system_alerts.create_index([('severity', 1), ('timestamp', -1)], name='severity_timestamp_desc')
        print("✅ Created system_alerts collection with indexes")
    except Exception as e:
        print(f"⚠️  System alerts collection already exists or error: {str(e)}")
    
    print("\n✅ Migration completed successfully!")
    print(f"   - Users with wasPremium flag: {result1.modified_count}")
    print(f"   - Premium users initialized: {result2.modified_count}")
    print(f"   - Free users initialized: {result3.modified_count}")
    print(f"   - Total users updated: {result1.modified_count + result2.modified_count + result3.modified_count}")
    
    client.close()


if __name__ == '__main__':
    # Get MongoDB URI from environment or use default
    mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
    migrate_subscription_history_fields(mongo_uri)
