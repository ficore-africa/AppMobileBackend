"""
Migration: Add sourceType field to existing income and expense entries
Date: February 18, 2026
Spec: source-tracking-standardization

This migration adds the sourceType field to all existing entries:
- Has vasTransactionId → sourceType: 'wallet_auto'
- Has metadata.source='voice_report' → sourceType: 'voice'
- Others → sourceType: 'manual'
"""

from pymongo import MongoClient
from datetime import datetime
import os

def migrate_source_type():
    # Connect to MongoDB
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/ficore')
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    print("Starting sourceType migration...")
    print("=" * 80)
    
    # Migrate incomes
    print("\n1. Migrating incomes...")
    
    # wallet_auto: Has vasTransactionId
    wallet_auto_incomes = db.incomes.update_many(
        {
            'vasTransactionId': {'$exists': True, '$ne': None},
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'wallet_auto',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"   - Wallet auto incomes: {wallet_auto_incomes.modified_count}")
    
    # voice: Has metadata.source='voice_report'
    voice_incomes = db.incomes.update_many(
        {
            'metadata.source': 'voice_report',
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'voice',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"   - Voice incomes: {voice_incomes.modified_count}")
    
    # manual: Everything else
    manual_incomes = db.incomes.update_many(
        {
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'manual',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"   - Manual incomes: {manual_incomes.modified_count}")
    
    # Migrate expenses
    print("\n2. Migrating expenses...")
    
    # wallet_auto: Has vasTransactionId
    wallet_auto_expenses = db.expenses.update_many(
        {
            'vasTransactionId': {'$exists': True, '$ne': None},
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'wallet_auto',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"   - Wallet auto expenses: {wallet_auto_expenses.modified_count}")
    
    # voice: Has metadata.source='voice_report'
    voice_expenses = db.expenses.update_many(
        {
            'metadata.source': 'voice_report',
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'voice',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"   - Voice expenses: {voice_expenses.modified_count}")
    
    # manual: Everything else
    manual_expenses = db.expenses.update_many(
        {
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'manual',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"   - Manual expenses: {manual_expenses.modified_count}")
    
    # Summary
    print("\n" + "=" * 80)
    print("Migration complete!")
    print(f"Total incomes migrated: {wallet_auto_incomes.modified_count + voice_incomes.modified_count + manual_incomes.modified_count}")
    print(f"Total expenses migrated: {wallet_auto_expenses.modified_count + voice_expenses.modified_count + manual_expenses.modified_count}")
    print("=" * 80)
    
    client.close()

if __name__ == '__main__':
    migrate_source_type()
