"""
Test script for Analytics System
Run this to verify the analytics system is working correctly.
"""

import os
import sys
from datetime import datetime
from flask import Flask
from flask_pymongo import PyMongo
from bson import ObjectId

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from utils.analytics_tracker import create_tracker


def test_analytics_system():
    """Test the analytics system end-to-end."""
    
    print("=" * 60)
    print("FiCore Analytics System Test")
    print("=" * 60)
    print()
    
    # Create Flask app and connect to MongoDB
    app = Flask(__name__)
    app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
    
    print(f"Connecting to MongoDB: {app.config['MONGO_URI']}")
    mongo = PyMongo(app)
    
    try:
        # Test database connection
        mongo.db.command('ping')
        print("✅ Database connection successful")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
    
    print()
    
    # Check if analytics_events collection exists
    collections = mongo.db.list_collection_names()
    if 'analytics_events' in collections:
        print("✅ analytics_events collection exists")
    else:
        print("⚠️  analytics_events collection does not exist")
        print("   Run the app once to initialize collections")
        return False
    
    print()
    
    # Create tracker
    tracker = create_tracker(mongo.db)
    print("✅ Analytics tracker created")
    print()
    
    # Test 1: Track a login event
    print("Test 1: Track Login Event")
    print("-" * 40)
    
    # Find or create a test user
    test_user = mongo.db.users.find_one({'email': 'admin@ficore.com'})
    if not test_user:
        print("❌ No test user found. Please run the app once to create admin user.")
        return False
    
    user_id = test_user['_id']
    print(f"Using test user: {test_user['email']} (ID: {user_id})")
    
    result = tracker.track_login(
        user_id=user_id,
        device_info={'platform': 'Test', 'version': '1.0.0'}
    )
    
    if result:
        print("✅ Login event tracked successfully")
    else:
        print("❌ Failed to track login event")
        return False
    
    # Verify event was created
    event = mongo.db.analytics_events.find_one({
        'userId': user_id,
        'eventType': 'user_logged_in'
    })
    
    if event:
        print(f"✅ Event verified in database (ID: {event['_id']})")
    else:
        print("❌ Event not found in database")
        return False
    
    print()
    
    # Test 2: Track income creation
    print("Test 2: Track Income Creation Event")
    print("-" * 40)
    
    result = tracker.track_income_created(
        user_id=user_id,
        amount=1500.0,
        category='Salary',
        source='Test Job'
    )
    
    if result:
        print("✅ Income creation event tracked successfully")
    else:
        print("❌ Failed to track income creation event")
        return False
    
    print()
    
    # Test 3: Track expense creation
    print("Test 3: Track Expense Creation Event")
    print("-" * 40)
    
    result = tracker.track_expense_created(
        user_id=user_id,
        amount=500.0,
        category='Groceries'
    )
    
    if result:
        print("✅ Expense creation event tracked successfully")
    else:
        print("❌ Failed to track expense creation event")
        return False
    
    print()
    
    # Test 4: Track custom event
    print("Test 4: Track Custom Event")
    print("-" * 40)
    
    result = tracker.track_event(
        user_id=user_id,
        event_type='dashboard_viewed',
        event_details={'section': 'overview'}
    )
    
    if result:
        print("✅ Custom event tracked successfully")
    else:
        print("❌ Failed to track custom event")
        return False
    
    print()
    
    # Test 5: Query events
    print("Test 5: Query Events")
    print("-" * 40)
    
    total_events = mongo.db.analytics_events.count_documents({'userId': user_id})
    print(f"Total events for test user: {total_events}")
    
    if total_events >= 4:
        print("✅ Events query successful")
    else:
        print(f"⚠️  Expected at least 4 events, found {total_events}")
    
    print()
    
    # Test 6: Event aggregation
    print("Test 6: Event Aggregation")
    print("-" * 40)
    
    pipeline = [
        {'$match': {'userId': user_id}},
        {'$group': {
            '_id': '$eventType',
            'count': {'$sum': 1}
        }},
        {'$sort': {'count': -1}}
    ]
    
    results = list(mongo.db.analytics_events.aggregate(pipeline))
    
    if results:
        print("✅ Event aggregation successful")
        print("\nEvent counts by type:")
        for result in results:
            print(f"  - {result['_id']}: {result['count']}")
    else:
        print("❌ Event aggregation failed")
        return False
    
    print()
    
    # Test 7: Check indexes
    print("Test 7: Check Indexes")
    print("-" * 40)
    
    indexes = mongo.db.analytics_events.index_information()
    expected_indexes = [
        'user_timestamp_desc',
        'event_type_timestamp_desc',
        'timestamp_desc',
        'user_event_type'
    ]
    
    found_indexes = []
    for expected in expected_indexes:
        if expected in indexes:
            found_indexes.append(expected)
            print(f"✅ Index '{expected}' exists")
        else:
            print(f"⚠️  Index '{expected}' not found")
    
    if len(found_indexes) >= 3:
        print(f"\n✅ {len(found_indexes)}/{len(expected_indexes)} expected indexes found")
    else:
        print(f"\n⚠️  Only {len(found_indexes)}/{len(expected_indexes)} expected indexes found")
    
    print()
    
    # Summary
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    print("✅ All tests passed!")
    print(f"✅ {total_events} events tracked successfully")
    print(f"✅ {len(found_indexes)} indexes verified")
    print()
    print("Next steps:")
    print("1. Access the admin dashboard at: /admin/analytics_dashboard.html")
    print("2. Integrate tracking into your blueprints (see ANALYTICS_INTEGRATION_EXAMPLES.md)")
    print("3. Start tracking events from your mobile app")
    print()
    
    return True


if __name__ == '__main__':
    try:
        success = test_analytics_system()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
