#!/usr/bin/env python3
"""
Database Migration: Add Dashboard Performance Indexes
Date: January 26, 2026
Purpose: Add compound indexes to optimize dashboard aggregation queries

This migration adds critical indexes for:
- Income/Expense aggregation queries (userId + amount)
- Immutable ledger queries (userId + status + isDeleted)
- Dashboard overview performance optimization

IDEMPOTENT: Safe to run multiple times
AUTOMATIC: Runs on app startup
TRACKED: Uses migration_status collection to prevent re-runs
"""

import os
import sys
from pymongo import MongoClient
from datetime import datetime

class DashboardPerformanceMigrator:
    """
    Handles the one-time migration to add dashboard performance indexes
    """
    
    MIGRATION_NAME = 'add_dashboard_performance_indexes_v1'
    
    def __init__(self, db):
        """
        Initialize the migrator with database connection
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.migration_status_collection = db.migration_status
    
    def has_run(self) -> bool:
        """
        Check if this migration has already been executed
        
        Returns:
            bool: True if migration has run, False otherwise
        """
        status = self.migration_status_collection.find_one({
            'migration_name': self.MIGRATION_NAME
        })
        return status is not None and status.get('completed', False)
    
    def mark_as_run(self, success: bool, details: dict):
        """
        Mark this migration as completed in the database
        
        Args:
            success: Whether the migration succeeded
            details: Dictionary with migration statistics
        """
        self.migration_status_collection.update_one(
            {'migration_name': self.MIGRATION_NAME},
            {
                '$set': {
                    'migration_name': self.MIGRATION_NAME,
                    'completed': success,
                    'completed_at': datetime.utcnow(),
                    'details': details
                }
            },
            upsert=True
        )
    
    def run(self) -> dict:
        """
        Execute the migration if it hasn't run yet
        
        Returns:
            dict: Migration results with statistics
        """
        # Check if already run
        if self.has_run():
            return {
                'success': True,
                'already_run': True,
                'message': 'Dashboard performance migration already completed previously'
            }
        
        print("\n" + "="*80)
        print("🚀 DASHBOARD PERFORMANCE MIGRATION: Adding Optimized Indexes")
        print("="*80)
        
        try:
            # Add performance indexes
            results = self.add_dashboard_performance_indexes()
            
            # Mark as completed
            self.mark_as_run(True, results)
            
            print("\n✅ DASHBOARD PERFORMANCE MIGRATION COMPLETE")
            print("="*80 + "\n")
            
            return {
                'success': True,
                'already_run': False,
                'results': results,
                'message': 'Dashboard performance migration completed successfully'
            }
            
        except Exception as e:
            error_msg = f"Dashboard performance migration failed: {str(e)}"
            self.mark_as_run(False, {'error': error_msg})
            print(f"\n❌ {error_msg}")
            print("="*80 + "\n")
            
            return {
                'success': False,
                'already_run': False,
                'error': error_msg,
                'message': 'Dashboard performance migration failed - will retry on next startup'
            }
    
    def add_dashboard_performance_indexes(self):
        """Add performance indexes for dashboard queries"""
        
        print("🔍 Adding Dashboard Performance Indexes...")
        
        # Define indexes to add
        indexes_to_add = {
            'incomes': [
                {
                    'keys': [('userId', 1), ('amount', 1)],
                    'name': 'user_amount_agg',
                    'purpose': 'Optimize dashboard income aggregation queries'
                },
                {
                    'keys': [('userId', 1), ('status', 1), ('isDeleted', 1)],
                    'name': 'user_status_deleted',
                    'purpose': 'Optimize immutable ledger filtering queries'
                }
            ],
            'expenses': [
                {
                    'keys': [('userId', 1), ('amount', 1)],
                    'name': 'user_amount_agg',
                    'purpose': 'Optimize dashboard expense aggregation queries'
                },
                {
                    'keys': [('userId', 1), ('status', 1), ('isDeleted', 1)],
                    'name': 'user_status_deleted',
                    'purpose': 'Optimize immutable ledger filtering queries'
                }
            ],
            'debtors': [
                {
                    'keys': [('userId', 1), ('status', 1)],
                    'name': 'user_status_agg',
                    'purpose': 'Optimize debtors status aggregation queries'
                }
            ],
            'creditors': [
                {
                    'keys': [('userId', 1), ('status', 1)],
                    'name': 'user_status_agg',
                    'purpose': 'Optimize creditors status aggregation queries'
                }
            ],
            'inventory_items': [
                {
                    'keys': [('userId', 1), ('currentStock', 1), ('minimumStock', 1)],
                    'name': 'user_stock_levels',
                    'purpose': 'Optimize inventory stock level queries'
                }
            ]
        }
        
        results = {
            'created': [],
            'existing': [],
            'errors': []
        }
        
        for collection_name, indexes in indexes_to_add.items():
            print(f"  📊 Processing collection: {collection_name}")
            
            try:
                collection = self.db[collection_name]
                existing_indexes = collection.index_information()
                
                for index_def in indexes:
                    index_name = index_def['name']
                    index_keys = index_def['keys']
                    purpose = index_def['purpose']
                    
                    print(f"    🔍 Checking index: {index_name}")
                    
                    # Check if index already exists
                    if index_name in existing_indexes:
                        print(f"    ✅ Index '{index_name}' already exists")
                        results['existing'].append(f"{collection_name}.{index_name}")
                        continue
                    
                    # Check if an index with the same key pattern exists
                    index_exists_with_different_name = False
                    for existing_name, existing_info in existing_indexes.items():
                        if existing_name != '_id_':
                            existing_keys = existing_info.get('key', [])
                            existing_keys_list = list(existing_keys.items()) if isinstance(existing_keys, dict) else existing_keys
                            if existing_keys_list == index_keys:
                                print(f"    ✅ Index with same keys exists as '{existing_name}' (skipping)")
                                index_exists_with_different_name = True
                                break
                    
                    if index_exists_with_different_name:
                        results['existing'].append(f"{collection_name}.{existing_name}")
                        continue
                    
                    # Create the index
                    try:
                        created_index_name = collection.create_index(
                            index_keys,
                            name=index_name,
                            background=True  # Create in background to avoid blocking
                        )
                        print(f"    ✅ Created index: {created_index_name}")
                        results['created'].append(f"{collection_name}.{created_index_name}")
                        
                    except Exception as index_error:
                        error_msg = f"Failed to create index '{index_name}' on {collection_name}: {str(index_error)}"
                        print(f"    ❌ {error_msg}")
                        results['errors'].append(error_msg)
            
            except Exception as collection_error:
                error_msg = f"Failed to process collection {collection_name}: {str(collection_error)}"
                print(f"  ❌ {error_msg}")
                results['errors'].append(error_msg)
        
        # Print summary
        print(f"\n📊 Migration Summary:")
        print(f"  ✅ Indexes created: {len(results['created'])}")
        print(f"  ℹ️  Indexes existing: {len(results['existing'])}")
        print(f"  ❌ Errors: {len(results['errors'])}")
        
        if results['created']:
            print(f"\n🆕 New indexes created:")
            for index in results['created']:
                print(f"    • {index}")
        
        if results['errors']:
            print(f"\n❌ Errors encountered:")
            for error in results['errors']:
                print(f"    • {error}")
            raise Exception(f"Migration completed with {len(results['errors'])} errors")
        
        return results


def run_dashboard_performance_migration(db) -> dict:
    """
    Convenience function to run the dashboard performance migration
    
    Args:
        db: MongoDB database instance
    
    Returns:
        dict: Migration results
    """
    migrator = DashboardPerformanceMigrator(db)
    return migrator.run()


def get_database_connection():
    """Get MongoDB connection from environment variables"""
    mongo_uri = os.getenv('MONGO_URI')
    if not mongo_uri:
        raise ValueError("MONGO_URI environment variable not set")
    
    client = MongoClient(mongo_uri)
    db_name = mongo_uri.split('/')[-1].split('?')[0]
    return client[db_name]


def main():
    """Main migration function for standalone execution"""
    try:
        print("🚀 Dashboard Performance Indexes Migration")
        print("=" * 50)
        print(f"Started at: {datetime.now().isoformat()}")
        
        # Get database connection
        db = get_database_connection()
        print(f"✅ Connected to database: {db.name}")
        
        # Run migration
        result = run_dashboard_performance_migration(db)
        
        print(f"\n✅ Migration completed at: {datetime.now().isoformat()}")
        
        if not result['success']:
            sys.exit(1)  # Exit with error code if migration failed
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()