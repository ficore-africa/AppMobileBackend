"""
Migration: Add Analytics Events Collection
Creates the analytics_events collection with proper indexes.
"""

from datetime import datetime


def upgrade(db):
    """
    Add analytics_events collection and indexes.
    
    Args:
        db: MongoDB database instance
    """
    print("Adding analytics_events collection...")
    
    # Check if collection already exists
    if 'analytics_events' in db.list_collection_names():
        print("✓ analytics_events collection already exists")
    else:
        # Create collection
        db.create_collection('analytics_events')
        print("✓ Created analytics_events collection")
    
    # Create indexes
    collection = db['analytics_events']
    existing_indexes = collection.index_information()
    
    indexes_to_create = [
        {
            'keys': [('userId', 1), ('timestamp', -1)],
            'name': 'user_timestamp_desc'
        },
        {
            'keys': [('eventType', 1), ('timestamp', -1)],
            'name': 'event_type_timestamp_desc'
        },
        {
            'keys': [('timestamp', -1)],
            'name': 'timestamp_desc'
        },
        {
            'keys': [('userId', 1), ('eventType', 1)],
            'name': 'user_event_type'
        },
        {
            'keys': [('createdAt', -1)],
            'name': 'created_at_desc'
        }
    ]
    
    for index_def in indexes_to_create:
        index_name = index_def['name']
        
        if index_name in existing_indexes:
            print(f"✓ Index '{index_name}' already exists")
        else:
            try:
                collection.create_index(
                    index_def['keys'],
                    name=index_name
                )
                print(f"✓ Created index '{index_name}'")
            except Exception as e:
                print(f"✗ Failed to create index '{index_name}': {e}")
    
    print("\n✅ Analytics collection migration completed successfully!")
    return True


def downgrade(db):
    """
    Remove analytics_events collection.
    
    Args:
        db: MongoDB database instance
    """
    print("Removing analytics_events collection...")
    
    if 'analytics_events' in db.list_collection_names():
        db.drop_collection('analytics_events')
        print("✓ Dropped analytics_events collection")
    else:
        print("✓ analytics_events collection does not exist")
    
    print("\n✅ Analytics collection rollback completed!")
    return True


if __name__ == '__main__':
    """
    Run this migration standalone.
    """
    import os
    import sys
    from flask import Flask
    from flask_pymongo import PyMongo
    
    # Create minimal Flask app
    app = Flask(__name__)
    app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
    
    print("=" * 60)
    print("Analytics Collection Migration")
    print("=" * 60)
    print(f"MongoDB URI: {app.config['MONGO_URI']}")
    print()
    
    # Initialize MongoDB
    mongo = PyMongo(app)
    
    try:
        # Test connection
        mongo.db.command('ping')
        print("✓ Database connection successful\n")
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        sys.exit(1)
    
    # Run migration
    try:
        action = sys.argv[1] if len(sys.argv) > 1 else 'upgrade'
        
        if action == 'upgrade':
            upgrade(mongo.db)
        elif action == 'downgrade':
            downgrade(mongo.db)
        else:
            print(f"Unknown action: {action}")
            print("Usage: python add_analytics_collection.py [upgrade|downgrade]")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
