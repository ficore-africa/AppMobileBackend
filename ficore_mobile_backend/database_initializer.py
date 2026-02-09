#!/usr/bin/env python3
"""
Database Initialization Module
Automatically initializes database collections and indexes with idempotency.
Runs during deployment and app startup to ensure proper database schema.
"""

import os
import sys
from datetime import datetime, timedelta
from bson import ObjectId
from models import DatabaseInitializer, DatabaseSchema
import pymongo
from pymongo import MongoClient

class DeploymentDatabaseInitializer:
    """
    Production-ready database initializer with idempotency and deployment integration.
    """
    
    def __init__(self, mongo_uri=None):
        """Initialize with MongoDB connection"""
        self.mongo_uri = mongo_uri or os.environ.get('MONGO_URI')
        if not self.mongo_uri:
            raise ValueError("MONGO_URI environment variable not set")
        
        self.client = None
        self.db = None
        self.initializer = None
        self.schema = DatabaseSchema()
    
    def connect(self):
        """Establish MongoDB connection"""
        try:
            self.client = MongoClient(self.mongo_uri)
            # Test connection
            self.client.admin.command('ping')
            
            # Get database name from URI or use default
            if 'ficore_africa' in self.mongo_uri:
                self.db = self.client.ficore_africa
            elif 'ficore_mobile' in self.mongo_uri:
                self.db = self.client.ficore_mobile
            else:
                # Extract database name from URI or use default
                self.db = self.client.get_default_database()
            
            self.initializer = DatabaseInitializer(self.db)
            print(f"✅ Connected to MongoDB: {self.db.name}")
            return True
        except Exception as e:
            print(f"❌ MongoDB connection failed: {str(e)}")
            return False
    
    def is_initialization_needed(self):
        """
        Check if database initialization is needed using idempotency.
        Uses a special collection to track initialization status.
        """
        try:
            # Check if initialization tracking collection exists
            init_collection = self.db.database_initialization_log
            
            # Look for successful VAS initialization
            last_init = init_collection.find_one(
                {'component': 'vas_collections', 'status': 'completed'},
                sort=[('completed_at', -1)]
            )
            
            if last_init:
                completed_at = last_init.get('completed_at')
                if completed_at and isinstance(completed_at, datetime):
                    # Check if initialization was completed recently (within 30 days)
                    if datetime.utcnow() - completed_at < timedelta(days=30):
                        print(f"✅ VAS collections already initialized on {completed_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
                        return False
            
            print("🔍 Database initialization needed")
            return True
            
        except Exception as e:
            print(f"⚠️  Error checking initialization status: {str(e)}")
            # If we can't check, assume initialization is needed
            return True
    
    def log_initialization_start(self):
        """Log the start of initialization process"""
        try:
            init_collection = self.db.database_initialization_log
            
            log_entry = {
                '_id': ObjectId(),
                'component': 'vas_collections',
                'status': 'started',
                'started_at': datetime.utcnow(),
                'version': '1.0.0',
                'environment': os.environ.get('FLASK_ENV', 'unknown'),
                'deployment_id': os.environ.get('RENDER_SERVICE_ID', 'local'),
            }
            
            init_collection.insert_one(log_entry)
            print("📝 Logged initialization start")
            return str(log_entry['_id'])
            
        except Exception as e:
            print(f"⚠️  Error logging initialization start: {str(e)}")
            return None
    
    def log_initialization_complete(self, log_id, results):
        """Log the completion of initialization process"""
        try:
            init_collection = self.db.database_initialization_log
            
            if log_id:
                # Update existing log entry
                init_collection.update_one(
                    {'_id': ObjectId(log_id)},
                    {
                        '$set': {
                            'status': 'completed',
                            'completed_at': datetime.utcnow(),
                            'results': results,
                            'collections_created': results.get('created', []),
                            'collections_existing': results.get('existing', []),
                            'indexes_created': results.get('indexes_created', []),
                            'errors': results.get('errors', []),
                        }
                    }
                )
            else:
                # Create new log entry
                log_entry = {
                    '_id': ObjectId(),
                    'component': 'vas_collections',
                    'status': 'completed',
                    'completed_at': datetime.utcnow(),
                    'results': results,
                    'version': '1.0.0',
                    'environment': os.environ.get('FLASK_ENV', 'unknown'),
                    'deployment_id': os.environ.get('RENDER_SERVICE_ID', 'local'),
                }
                init_collection.insert_one(log_entry)
            
            print("✅ Logged initialization completion")
            
        except Exception as e:
            print(f"⚠️  Error logging initialization completion: {str(e)}")
    
    def log_initialization_error(self, log_id, error):
        """Log initialization error"""
        try:
            init_collection = self.db.database_initialization_log
            
            if log_id:
                init_collection.update_one(
                    {'_id': ObjectId(log_id)},
                    {
                        '$set': {
                            'status': 'failed',
                            'failed_at': datetime.utcnow(),
                            'error': str(error),
                        }
                    }
                )
            
            print(f"❌ Logged initialization error: {str(error)}")
            
        except Exception as e:
            print(f"⚠️  Error logging initialization error: {str(e)}")
    
    def fix_vas_transaction_data_integrity(self):
        """Fix VAS transaction data integrity issues"""
        try:
            print("🔍 Verifying VAS transaction data integrity...")
            
            vas_transactions = self.db.vas_transactions
            
            # Check for transactions missing isVAS flag
            missing_is_vas = vas_transactions.count_documents({'isVAS': {'$ne': True}})
            if missing_is_vas > 0:
                print(f"⚠️  Found {missing_is_vas} transactions missing isVAS flag")
                
                # Fix missing isVAS flags
                print("🔧 Fixing missing isVAS flags...")
                result = vas_transactions.update_many(
                    {'isVAS': {'$ne': True}},
                    {'$set': {'isVAS': True, 'updatedAt': datetime.utcnow()}}
                )
                print(f"✅ Updated {result.modified_count} transactions with isVAS flag")
            else:
                print("✅ All VAS transactions have proper isVAS flag")
            
            # Check for transactions missing navigation flags
            missing_nav_flags = vas_transactions.count_documents({
                '$or': [
                    {'isIncome': {'$exists': False}},
                    {'isExpense': {'$exists': False}}
                ]
            })
            
            if missing_nav_flags > 0:
                print(f"⚠️  Found {missing_nav_flags} transactions missing navigation flags")
                print("🔧 Fixing navigation flags...")
                
                # Fix navigation flags based on transaction type
                transactions = vas_transactions.find({
                    '$or': [
                        {'isIncome': {'$exists': False}},
                        {'isExpense': {'$exists': False}}
                    ]
                })
                
                fixed_count = 0
                for txn in transactions:
                    txn_type = txn.get('type', '').upper()
                    is_income = txn_type == 'WALLET_FUNDING' or 'REFUND' in txn_type
                    is_expense = txn_type in ['AIRTIME', 'DATA', 'BILLS', 'BILL']
                    
                    vas_transactions.update_one(
                        {'_id': txn['_id']},
                        {
                            '$set': {
                                'isIncome': is_income,
                                'isExpense': is_expense,
                                'updatedAt': datetime.utcnow()
                            }
                        }
                    )
                    fixed_count += 1
                
                print(f"✅ Fixed navigation flags for {fixed_count} transactions")
            else:
                print("✅ All VAS transactions have proper navigation flags")
                
            return True
            
        except Exception as e:
            print(f"❌ Error fixing VAS transaction data integrity: {str(e)}")
            return False
    
    def initialize_database(self, force=False):
        """
        Initialize database with idempotency.
        
        Args:
            force (bool): Force initialization even if already completed
        """
        if not self.connect():
            return False
        
        try:
            # Check if initialization is needed (unless forced)
            if not force and not self.is_initialization_needed():
                print("⏭️  Database initialization skipped - already completed")
                return True
            
            print("🚀 Starting database initialization...")
            
            # Log initialization start
            log_id = self.log_initialization_start()
            
            try:
                # Initialize all collections and indexes
                print("🔧 Initializing collections and indexes...")
                results = self.initializer.initialize_collections()
                
                # Fix VAS transaction data integrity
                self.fix_vas_transaction_data_integrity()
                
                # Log successful completion
                self.log_initialization_complete(log_id, results)
                
                print("\n" + "="*80)
                print("🎉 DATABASE INITIALIZATION COMPLETE")
                print("="*80)
                
                if results['created']:
                    print(f"✅ Collections created: {len(results['created'])}")
                    for collection in results['created']:
                        print(f"   - {collection}")
                
                if results['existing']:
                    print(f"📋 Collections already existing: {len(results['existing'])}")
                
                if results['indexes_created']:
                    print(f"🔗 Indexes created/verified: {len(results['indexes_created'])}")
                    vas_indexes = [idx for idx in results['indexes_created'] if 'vas_' in idx]
                    if vas_indexes:
                        print("   VAS-specific indexes:")
                        for index in vas_indexes:
                            print(f"     - {index}")
                
                if results['errors']:
                    print(f"❌ Errors encountered: {len(results['errors'])}")
                    for error in results['errors']:
                        print(f"   - {error}")
                
                print("\n🚀 VAS transaction persistence issues resolved!")
                print("   - VAS transactions will persist after app reinstall")
                print("   - Liquid wallet history will show proper data")
                print("   - Backend synchronization will work correctly")
                print()
                
                return True
                
            except Exception as e:
                # Log error
                self.log_initialization_error(log_id, e)
                raise
                
        except Exception as e:
            print(f"❌ Database initialization failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if self.client:
                self.client.close()

def initialize_database_for_deployment(mongo_uri=None, force=False):
    """
    Main function for deployment database initialization.
    
    Args:
        mongo_uri (str): MongoDB connection string
        force (bool): Force initialization even if already completed
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        initializer = DeploymentDatabaseInitializer(mongo_uri)
        return initializer.initialize_database(force=force)
    except Exception as e:
        print(f"❌ Deployment database initialization failed: {str(e)}")
        return False

if __name__ == '__main__':
    """
    Command-line interface for database initialization.
    Usage:
        python database_initializer.py [--force]
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Initialize FiCore database collections and indexes')
    parser.add_argument('--force', action='store_true', help='Force initialization even if already completed')
    parser.add_argument('--mongo-uri', help='MongoDB connection string (overrides MONGO_URI env var)')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("🚀 FICORE DATABASE INITIALIZATION")
    print("=" * 80)
    print("Initializing database collections and indexes for production deployment")
    print()
    
    success = initialize_database_for_deployment(
        mongo_uri=args.mongo_uri,
        force=args.force
    )
    
    if success:
        print("✅ Database initialization completed successfully")
        sys.exit(0)
    else:
        print("❌ Database initialization failed")
        sys.exit(1)