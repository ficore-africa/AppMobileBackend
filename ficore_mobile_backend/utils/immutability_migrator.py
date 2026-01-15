"""
Immutability Migration - Run Once on Startup
Date: January 14, 2026
Purpose: Add immutability fields to existing income/expense records

This migration is:
- IDEMPOTENT: Safe to run multiple times
- AUTOMATIC: Runs on app startup
- TRACKED: Uses migration_status collection to prevent re-runs
"""

from datetime import datetime
from bson import ObjectId


class ImmutabilityMigrator:
    """
    Handles the one-time migration to add immutability fields to financial transactions
    """
    
    MIGRATION_NAME = 'add_immutability_fields_v1'
    
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
                'message': 'Migration already completed previously'
            }
        
        print("\n" + "="*80)
        print("🏛️  IMMUTABILITY MIGRATION: Adding Ghost Ledger Fields")
        print("="*80)
        
        try:
            # Define the immutability fields with defaults
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
            
            results = {
                'incomes': self._migrate_collection('incomes', immutability_fields),
                'expenses': self._migrate_collection('expenses', immutability_fields)
            }
            
            # Create indexes for performance
            self._create_indexes()
            
            # Mark as completed
            self.mark_as_run(True, results)
            
            print("\n✅ IMMUTABILITY MIGRATION COMPLETE")
            print("="*80 + "\n")
            
            return {
                'success': True,
                'already_run': False,
                'results': results,
                'message': 'Migration completed successfully'
            }
            
        except Exception as e:
            error_msg = f"Migration failed: {str(e)}"
            print(f"\n❌ {error_msg}")
            print("="*80 + "\n")
            
            # Mark as failed (don't set completed=True so it can retry)
            self.mark_as_run(False, {'error': error_msg})
            
            return {
                'success': False,
                'already_run': False,
                'error': error_msg,
                'message': 'Migration failed - will retry on next startup'
            }
    
    def _migrate_collection(self, collection_name: str, fields: dict) -> dict:
        """
        Migrate a single collection by adding immutability fields
        
        Args:
            collection_name: Name of the collection to migrate
            fields: Dictionary of fields to add
        
        Returns:
            dict: Migration statistics for this collection
        """
        collection = self.db[collection_name]
        
        print(f"\n📊 Migrating {collection_name} collection...")
        print("-" * 80)
        
        # Count total records
        total_count = collection.count_documents({})
        print(f"Total records: {total_count}")
        
        if total_count == 0:
            print(f"⚠️  No records found in {collection_name}")
            return {
                'total': 0,
                'migrated': 0,
                'already_migrated': 0,
                'skipped': 0
            }
        
        # Find records that don't have the new fields
        records_to_update = collection.count_documents({'status': {'$exists': False}})
        print(f"Records needing migration: {records_to_update}")
        
        if records_to_update > 0:
            # Update records that don't have the status field
            result = collection.update_many(
                {'status': {'$exists': False}},
                {'$set': fields}
            )
            print(f"✅ Updated {result.modified_count} records")
            
            return {
                'total': total_count,
                'migrated': result.modified_count,
                'already_migrated': total_count - records_to_update,
                'skipped': 0
            }
        else:
            print(f"✅ All records already have immutability fields")
            return {
                'total': total_count,
                'migrated': 0,
                'already_migrated': total_count,
                'skipped': 0
            }
    
    def _create_indexes(self):
        """
        Create indexes for efficient querying of immutable records
        """
        print("\n🔍 Creating performance indexes...")
        print("-" * 80)
        
        # Income indexes
        try:
            self.db.incomes.create_index(
                [('status', 1), ('isDeleted', 1)],
                name='status_isDeleted_idx'
            )
            print("✅ Created compound index on incomes: (status, isDeleted)")
        except Exception as e:
            print(f"⚠️  Income index warning (may already exist): {e}")
        
        try:
            self.db.incomes.create_index(
                [('originalEntryId', 1)],
                name='originalEntryId_idx',
                sparse=True
            )
            print("✅ Created index on incomes: originalEntryId")
        except Exception as e:
            print(f"⚠️  Income index warning (may already exist): {e}")
        
        # Expense indexes
        try:
            self.db.expenses.create_index(
                [('status', 1), ('isDeleted', 1)],
                name='status_isDeleted_idx'
            )
            print("✅ Created compound index on expenses: (status, isDeleted)")
        except Exception as e:
            print(f"⚠️  Expense index warning (may already exist): {e}")
        
        try:
            self.db.expenses.create_index(
                [('originalEntryId', 1)],
                name='originalEntryId_idx',
                sparse=True
            )
            print("✅ Created index on expenses: originalEntryId")
        except Exception as e:
            print(f"⚠️  Expense index warning (may already exist): {e}")


def run_immutability_migration(db) -> dict:
    """
    Convenience function to run the immutability migration
    
    Args:
        db: MongoDB database instance
    
    Returns:
        dict: Migration results
    """
    migrator = ImmutabilityMigrator(db)
    return migrator.run()
