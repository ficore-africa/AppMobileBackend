"""
Migration: Fix Superseded Entries from Old Version Control System

Date: February 8, 2026
Issue: Entries marked as 'superseded' before Feb 7, 2026 are hidden from users
Solution: Change status from 'superseded' back to 'active' for the latest version

Background:
- Before Feb 7, 2026: Updates created NEW documents and marked old ones as 'superseded'
- After Feb 7, 2026: Updates modify SAME document (primary key stability)
- Problem: Old 'superseded' entries are filtered out by get_active_transactions_query()
- Impact: Users can't see their entries after reinstalling app

This migration:
1. Finds all 'superseded' entries
2. For each originalEntryId, finds the LATEST version
3. Changes the latest version's status from 'superseded' to 'active'
4. Keeps older versions as 'superseded' (for history)
"""

from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def run_migration():
    """Run the migration to fix superseded entries"""
    
    # Connect to MongoDB
    mongo_uri = os.getenv('MONGO_URI', 'mongodb+srv://ficoreapp:ficoreapp2024@cluster0.ixqhj.mongodb.net/ficore_mobile?retryWrites=true&w=majority')
    if not mongo_uri:
        print("ERROR: MONGO_URI not found in environment variables")
        return False
    
    client = MongoClient(mongo_uri)
    db = client.get_default_database()
    
    print("=" * 80)
    print("MIGRATION: Fix Superseded Entries")
    print("=" * 80)
    
    # Process both incomes and expenses
    for collection_name in ['incomes', 'expenses']:
        print(f"\nProcessing {collection_name}...")
        collection = db[collection_name]
        
        # Find all superseded entries
        superseded_entries = list(collection.find({'status': 'superseded'}))
        print(f"   Found {len(superseded_entries)} superseded entries")
        
        if len(superseded_entries) == 0:
            print(f"   No superseded entries found in {collection_name}")
            continue
        
        # Group by originalEntryId
        by_original = {}
        for entry in superseded_entries:
            original_id = entry.get('originalEntryId', str(entry['_id']))
            if original_id not in by_original:
                by_original[original_id] = []
            by_original[original_id].append(entry)
        
        print(f"   Found {len(by_original)} unique entry chains")
        
        # For each chain, find the latest version and mark it as active
        fixed_count = 0
        for original_id, versions in by_original.items():
            # Sort by version number (descending) to get latest
            versions.sort(key=lambda x: x.get('version', 1), reverse=True)
            latest = versions[0]
            
            # Check if this is truly the latest (no active version exists)
            active_version = collection.find_one({
                'originalEntryId': original_id,
                'status': 'active'
            })
            
            if active_version:
                # An active version already exists, skip
                print(f"   Skipping {original_id} - active version already exists")
                continue
            
            # Update the latest superseded version to active
            result = collection.update_one(
                {'_id': latest['_id']},
                {
                    '$set': {
                        'status': 'active',
                        'updatedAt': datetime.utcnow(),
                        'migrationNote': 'Restored from superseded status (Feb 8, 2026 migration)'
                    }
                }
            )
            
            if result.modified_count == 1:
                fixed_count += 1
                print(f"   Fixed {latest['_id']} (version {latest.get('version', 1)}) for user {latest.get('userId')}")
            else:
                print(f"   Failed to fix {latest['_id']}")
        
        print(f"\n   Summary for {collection_name}:")
        print(f"      - Total superseded entries: {len(superseded_entries)}")
        print(f"      - Unique entry chains: {len(by_original)}")
        print(f"      - Fixed entries: {fixed_count}")
    
    print("\n" + "=" * 80)
    print("Migration completed successfully")
    print("=" * 80)
    
    client.close()
    return True


if __name__ == '__main__':
    run_migration()
