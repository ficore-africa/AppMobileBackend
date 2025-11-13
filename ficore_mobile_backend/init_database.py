"""
Database Initialization Script
==============================

This script initializes the FiCore Mobile database with proper collections and indexes.
It can be run standalone or imported into the main application.

Usage:
    python init_database.py

Or import in app.py:
    from init_database import init_database
    init_database(mongo.db)
"""

import sys
import os
from datetime import datetime


def init_database(mongo_db, verbose=True):
    """
    Initialize database collections and indexes.
    Safe to run multiple times - will skip existing collections.
    
    Args:
        mongo_db: PyMongo database instance
        verbose: Print detailed output (default: True)
    
    Returns:
        dict: Initialization results with created/existing collections and any errors
    """
    try:
        from models import DatabaseInitializer
        
        if verbose:
            print("\n" + "=" * 60)
            print("FiCore Mobile - Database Initialization")
            print("=" * 60)
            print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
            print(f"Database: {mongo_db.name}")
            print()
        
        # Initialize database
        initializer = DatabaseInitializer(mongo_db)
        results = initializer.initialize_collections()
        
        if verbose:
            # Print summary
            print("\n" + "=" * 60)
            print("Initialization Summary")
            print("=" * 60)
            
            if results['created']:
                print(f"\n✅ Collections Created: {len(results['created'])}")
                for col in results['created']:
                    print(f"   - {col}")
            
            if results['existing']:
                print(f"\n✅ Collections Already Existing: {len(results['existing'])}")
                for col in results['existing']:
                    print(f"   - {col}")
            
            if results['indexes_created']:
                print(f"\n✅ Indexes Created/Verified: {len(results['indexes_created'])}")
            
            if results['errors']:
                print(f"\n⚠️  Errors Encountered: {len(results['errors'])}")
                for error in results['errors']:
                    print(f"   - {error}")
            else:
                print("\n✅ No errors encountered")
            
            # Get and display statistics
            print("\n" + "=" * 60)
            print("Database Statistics")
            print("=" * 60)
            
            stats = initializer.get_all_collections_stats()
            total_docs = 0
            total_size = 0
            
            for collection_name, collection_stats in stats.items():
                if 'error' not in collection_stats:
                    count = collection_stats['count']
                    size = collection_stats['size_bytes']
                    total_docs += count
                    total_size += size
                    
                    print(f"\n{collection_name}:")
                    print(f"   Documents: {count:,}")
                    print(f"   Size: {size:,} bytes ({size / 1024:.2f} KB)")
                    print(f"   Indexes: {len(collection_stats['indexes'])}")
            
            print(f"\nTotal Documents: {total_docs:,}")
            print(f"Total Size: {total_size:,} bytes ({total_size / 1024 / 1024:.2f} MB)")
            
            print("\n" + "=" * 60)
            print("✅ Database initialization complete!")
            print("=" * 60 + "\n")
        
        return results
    
    except ImportError as e:
        error_msg = f"Failed to import models module: {str(e)}"
        if verbose:
            print(f"\n❌ Error: {error_msg}")
            print("Make sure models.py is in the same directory.\n")
        return {'created': [], 'existing': [], 'indexes_created': [], 'errors': [error_msg]}
    
    except Exception as e:
        error_msg = f"Database initialization failed: {str(e)}"
        if verbose:
            print(f"\n❌ Error: {error_msg}\n")
        return {'created': [], 'existing': [], 'indexes_created': [], 'errors': [error_msg]}


def verify_database_health(mongo_db, verbose=True):
    """
    Verify database health and check all collections exist.
    
    Args:
        mongo_db: PyMongo database instance
        verbose: Print detailed output (default: True)
    
    Returns:
        dict: Health check results
    """
    try:
        from models import DatabaseInitializer
        
        initializer = DatabaseInitializer(mongo_db)
        
        required_collections = ['users', 'incomes', 'expenses', 'budgets', 
                               'credit_transactions', 'credit_requests']
        
        existing_collections = mongo_db.list_collection_names()
        
        health_status = {
            'healthy': True,
            'missing_collections': [],
            'existing_collections': [],
            'total_documents': 0,
            'errors': []
        }
        
        for collection in required_collections:
            if collection in existing_collections:
                health_status['existing_collections'].append(collection)
                try:
                    count = mongo_db[collection].count_documents({})
                    health_status['total_documents'] += count
                except Exception as e:
                    health_status['errors'].append(f"Error counting {collection}: {str(e)}")
            else:
                health_status['missing_collections'].append(collection)
                health_status['healthy'] = False
        
        if verbose:
            print("\n" + "=" * 60)
            print("Database Health Check")
            print("=" * 60)
            print(f"Status: {'✅ Healthy' if health_status['healthy'] else '⚠️  Issues Found'}")
            print(f"Existing Collections: {len(health_status['existing_collections'])}/{len(required_collections)}")
            print(f"Total Documents: {health_status['total_documents']:,}")
            
            if health_status['missing_collections']:
                print(f"\n⚠️  Missing Collections:")
                for col in health_status['missing_collections']:
                    print(f"   - {col}")
            
            if health_status['errors']:
                print(f"\n⚠️  Errors:")
                for error in health_status['errors']:
                    print(f"   - {error}")
            
            print("=" * 60 + "\n")
        
        return health_status
    
    except Exception as e:
        error_msg = f"Health check failed: {str(e)}"
        if verbose:
            print(f"\n❌ Error: {error_msg}\n")
        return {
            'healthy': False,
            'missing_collections': [],
            'existing_collections': [],
            'total_documents': 0,
            'errors': [error_msg]
        }


if __name__ == '__main__':
    """
    Standalone execution - initialize database from command line.
    """
    from flask import Flask
    from flask_pymongo import PyMongo
    
    # Get MongoDB URI from environment or use default
    mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
    
    # Create minimal Flask app for database connection
    app = Flask(__name__)
    app.config['MONGO_URI'] = mongo_uri
    
    try:
        # Initialize MongoDB
        mongo = PyMongo(app)
        
        print("\n" + "=" * 60)
        print("FiCore Mobile Backend - Database Setup")
        print("=" * 60)
        print(f"MongoDB URI: {mongo_uri}")
        print(f"Database: {mongo.db.name}")
        print("=" * 60)
        
        # Test connection
        try:
            mongo.db.command('ping')
            print("✅ MongoDB connection successful")
        except Exception as e:
            print(f"❌ MongoDB connection failed: {str(e)}")
            print("\nPlease ensure:")
            print("  1. MongoDB is running")
            print("  2. MONGO_URI is correct")
            print("  3. Network connectivity is available")
            sys.exit(1)
        
        # Initialize database
        results = init_database(mongo.db, verbose=True)
        
        # Verify health
        health = verify_database_health(mongo.db, verbose=True)
        
        # Exit with appropriate code
        if results['errors'] or not health['healthy']:
            print("⚠️  Database initialization completed with warnings")
            sys.exit(1)
        else:
            print("✅ Database setup completed successfully")
            sys.exit(0)
    
    except Exception as e:
        print(f"\n❌ Fatal error: {str(e)}")
        print("\nStack trace:")
        import traceback
        traceback.print_exc()
        sys.exit(1)
