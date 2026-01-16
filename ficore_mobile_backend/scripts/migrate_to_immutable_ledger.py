"""
Migration Script: Add Immutability Fields to Income and Expense Collections
Date: January 14, 2026
Purpose: Transform FiCore from "bookkeeping app" to "financial institution"

This script adds the Ghost Ledger pattern fields to existing records.
"""

import os
import sys
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def migrate_to_immutable_ledger():
    """
    Add immutability fields to all existing income and expense records
    """
    
    # Connect to MongoDB
    mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    print("=" * 80)
    print("FICORE IMMUTABILITY MIGRATION")
    print("=" * 80)
    print(f"Database: {db.name}")
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
    print()
    
    # Define the new fields with defaults
    immutability_fields = {
        'status': 'active',
        'isDeleted': False,
        'deletedAt': None,
        'deletedBy': None,
        'originalEntryId': None,
        'reversalEntryId': None,
        'supersededBy': None,
        'version': 1,
        'auditLog': []
    }
    
    # Migrate Income Collection
    print("📊 Migrating Income Collection...")
    print("-" * 80)
    
    income_count = db.incomes.count_documents({})
    print(f"Total income records: {income_count}")
    
    if income_count > 0:
        # Find records that don't have the new fields
        incomes_to_update = db.incomes.count_documents({'status': {'$exists': False}})
        print(f"Records needing migration: {incomes_to_update}")
        
        if incomes_to_update > 0:
            result = db.incomes.update_many(
                {'status': {'$exists': False}},
                {'$set': immutability_fields}
            )
            print(f"✅ Updated {result.modified_count} income records")
        else:
            print("✅ All income records already migrated")
    else:
        print("⚠️  No income records found")
    
    print()
    
    # Migrate Expense Collection
    print("💰 Migrating Expense Collection...")
    print("-" * 80)
    
    expense_count = db.expenses.count_documents({})
    print(f"Total expense records: {expense_count}")
    
    if expense_count > 0:
        # Find records that don't have the new fields
        expenses_to_update = db.expenses.count_documents({'status': {'$exists': False}})
        print(f"Records needing migration: {expenses_to_update}")
        
        if expenses_to_update > 0:
            result = db.expenses.update_many(
                {'status': {'$exists': False}},
                {'$set': immutability_fields}
            )
            print(f"✅ Updated {result.modified_count} expense records")
        else:
            print("✅ All expense records already migrated")
    else:
        print("⚠️  No expense records found")
    
    print()
    
    # Create indexes for performance
    print("🔍 Creating Indexes for Performance...")
    print("-" * 80)
    
    # Income indexes
    try:
        db.incomes.create_index([('status', 1), ('isDeleted', 1)])
        print("✅ Created compound index on incomes: (status, isDeleted)")
    except Exception as e:
        print(f"⚠️  Index creation warning (may already exist): {e}")
    
    try:
        db.incomes.create_index([('originalEntryId', 1)])
        print("✅ Created index on incomes: originalEntryId")
    except Exception as e:
        print(f"⚠️  Index creation warning (may already exist): {e}")
    
    # Expense indexes
    try:
        db.expenses.create_index([('status', 1), ('isDeleted', 1)])
        print("✅ Created compound index on expenses: (status, isDeleted)")
    except Exception as e:
        print(f"⚠️  Index creation warning (may already exist): {e}")
    
    try:
        db.expenses.create_index([('originalEntryId', 1)])
        print("✅ Created index on expenses: originalEntryId")
    except Exception as e:
        print(f"⚠️  Index creation warning (may already exist): {e}")
    
    print()
    
    # Verification
    print("✅ Verification...")
    print("-" * 80)
    
    active_incomes = db.incomes.count_documents({'status': 'active', 'isDeleted': False})
    active_expenses = db.expenses.count_documents({'status': 'active', 'isDeleted': False})
    
    print(f"Active income records: {active_incomes}/{income_count}")
    print(f"Active expense records: {active_expenses}/{expense_count}")
    
    print()
    print("=" * 80)
    print("✅ MIGRATION COMPLETE")
    print("=" * 80)
    print()
    print("Next Steps:")
    print("1. Deploy updated API endpoints (DELETE and UPDATE)")
    print("2. Update frontend query filters")
    print("3. Test with sample data")
    print("4. Monitor for any issues")
    print()
    
    client.close()

if __name__ == '__main__':
    try:
        migrate_to_immutable_ledger()
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        sys.exit(1)
