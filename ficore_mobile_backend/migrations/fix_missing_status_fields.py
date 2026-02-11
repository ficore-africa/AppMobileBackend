"""
Migration: Fix Missing Status Fields on Existing Entries

Date: February 8, 2026
Issue: Entries created before version control system don't have 'status' field
Solution: Add 'status': 'active' to all entries missing the field

Background:
- Version control was added recently (around Feb 7, 2026)
- Old entries created before this don't have 'status' field
- get_active_transactions_query() filters by status: 'active'
- Entries without status field are excluded from results
- Impact: Users can't see their old entries after reinstalling app

This migration:
1. Finds all entries WITHOUT a 'status' field
2. Sets status to 'active' for these entries
3. Also ensures isDeleted field exists (defaults to False)
4. Also ensures version field exists (defaults to 1)
"""

from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def run_migration():
    """Run the migration to add missing status fields"""
    
    # Connect to MongoDB
    mongo_uri = os.getenv('MONGO_URI')
    if not mongo_uri:
        print("ERROR: MONGO_URI not found in environment variables")
        return False
    
    client = MongoClient(mongo_uri)
    db = client.get_default_database()
    
    print("=" * 80)
    print("MIGRATION: Fix Missing Status Fields")
    print("=" * 80)
    
    # Process both incomes and expenses
    for collection_name in ['incomes', 'expenses']:
        print(f"\nProcessing {collection_name}...")
        collection = db[collection_name]
        
        # Find all entries WITHOUT a status field
        missing_status = list(collection.find({
            '$or': [
                {'status': {'$exists': False}},
                {'status': None},
                {'status': ''}
            ]
        }))
        print(f"   Found {len(missing_status)} entries without status field")
        
        if len(missing_status) == 0:
            print(f"   All entries in {collection_name} have status field")
            continue
        
        # Update each entry
        fixed_count = 0
        for entry in missing_status:
            entry_id = entry['_id']
            user_id = entry.get('userId', 'unknown')
            
            # Prepare update
            update_fields = {
                'status': 'active',
                'updatedAt': datetime.utcnow(),
                'migrationNote': 'Added missing status field (Feb 8, 2026 migration)'
            }
            
            # Also add isDeleted if missing
            if 'isDeleted' not in entry:
                update_fields['isDeleted'] = False
            
            # Also add version if missing
            if 'version' not in entry:
                update_fields['version'] = 1
            
            # Update the entry
            result = collection.update_one(
                {'_id': entry_id},
                {'$set': update_fields}
            )
            
            if result.modified_count == 1:
                fixed_count += 1
                date_field = entry.get('dateReceived') or entry.get('date')
                print(f"   Fixed {entry_id} for user {user_id} (date: {date_field})")
            else:
                print(f"   Failed to fix {entry_id}")
        
        print(f"\n   Summary for {collection_name}:")
        print(f"      - Entries without status: {len(missing_status)}")
        print(f"      - Fixed entries: {fixed_count}")
    
    print("\n" + "=" * 80)
    print("Migration completed successfully")
    print("=" * 80)
    
    client.close()
    return True


if __name__ == '__main__':
    run_migration()

