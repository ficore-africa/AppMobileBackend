"""
Verification Script: Stale Data Cleanup
Verifies that expired subscriptions have NO stale data in active fields
"""

from pymongo import MongoClient
from datetime import datetime
import os


def verify_no_stale_data(mongo_uri):
    """
    Verify that no users have stale subscription data.
    
    Checks:
    1. Users with isSubscribed=False should have None in all active subscription fields
    2. Users with isSubscribed=True should have valid subscription data
    3. All expired users should have wasPremium=True
    """
    print("=" * 70)
    print("STALE DATA CLEANUP VERIFICATION")
    print("=" * 70)
    print()
    
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    # Test 1: Check for stale data in non-subscribed users
    print("Test 1: Checking for stale data in non-subscribed users...")
    stale_users = list(db.users.find({
        'isSubscribed': False,
        '$or': [
            {'subscriptionType': {'$ne': None}},
            {'subscriptionStartDate': {'$ne': None}},
            {'subscriptionEndDate': {'$ne': None}},
            {'paymentMethodDetails': {'$ne': None}}
        ]
    }))
    
    if len(stale_users) == 0:
        print("✅ PASS: No stale data found in non-subscribed users")
    else:
        print(f"❌ FAIL: Found {len(stale_users)} users with stale data:")
        for user in stale_users[:5]:  # Show first 5
            print(f"   - {user.get('email')}: ", end="")
            issues = []
            if user.get('subscriptionType') is not None:
                issues.append(f"subscriptionType={user.get('subscriptionType')}")
            if user.get('subscriptionStartDate') is not None:
                issues.append(f"subscriptionStartDate={user.get('subscriptionStartDate')}")
            if user.get('subscriptionEndDate') is not None:
                issues.append(f"subscriptionEndDate={user.get('subscriptionEndDate')}")
            if user.get('paymentMethodDetails') is not None:
                issues.append(f"paymentMethodDetails={user.get('paymentMethodDetails')}")
            print(", ".join(issues))
    print()
    
    # Test 2: Check subscribed users have valid data
    print("Test 2: Checking subscribed users have valid subscription data...")
    subscribed_users = list(db.users.find({'isSubscribed': True}))
    invalid_subscribed = []
    
    for user in subscribed_users:
        if user.get('subscriptionType') is None or user.get('subscriptionEndDate') is None:
            invalid_subscribed.append(user)
    
    if len(invalid_subscribed) == 0:
        print(f"✅ PASS: All {len(subscribed_users)} subscribed users have valid data")
    else:
        print(f"❌ FAIL: Found {len(invalid_subscribed)} subscribed users with invalid data")
    print()
    
    # Test 3: Check wasPremium flag
    print("Test 3: Checking wasPremium flag for expired users...")
    expired_without_flag = list(db.users.find({
        'isSubscribed': False,
        'subscriptionHistory': {'$exists': True, '$ne': []},
        'wasPremium': {'$ne': True}
    }))
    
    if len(expired_without_flag) == 0:
        print("✅ PASS: All expired users have wasPremium=True")
    else:
        print(f"❌ FAIL: Found {len(expired_without_flag)} expired users without wasPremium flag")
    print()
    
    # Test 4: Check subscription history
    print("Test 4: Checking subscription history integrity...")
    users_with_history = list(db.users.find({
        'subscriptionHistory': {'$exists': True, '$ne': []}
    }))
    
    invalid_history = []
    for user in users_with_history:
        history = user.get('subscriptionHistory', [])
        for entry in history:
            if not entry.get('planType') or not entry.get('status'):
                invalid_history.append(user)
                break
    
    if len(invalid_history) == 0:
        print(f"✅ PASS: All {len(users_with_history)} users with history have valid entries")
    else:
        print(f"❌ FAIL: Found {len(invalid_history)} users with invalid history entries")
    print()
    
    # Test 5: Check FC balance preservation
    print("Test 5: Checking FC balance integrity...")
    users_with_zero_balance = list(db.users.find({
        'ficoreCreditBalance': {'$lte': 0},
        'subscriptionHistory': {'$exists': True, '$ne': []}
    }))
    
    # This is just a warning, not a failure (users might legitimately have 0 balance)
    if len(users_with_zero_balance) > 0:
        print(f"⚠️  WARNING: Found {len(users_with_zero_balance)} expired users with 0 FC balance")
        print("   (This may be legitimate, but verify no corruption occurred)")
    else:
        print("✅ PASS: All expired users have positive FC balance")
    print()
    
    # Summary
    print("=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    
    total_tests = 5
    passed_tests = 0
    
    if len(stale_users) == 0:
        passed_tests += 1
    if len(invalid_subscribed) == 0:
        passed_tests += 1
    if len(expired_without_flag) == 0:
        passed_tests += 1
    if len(invalid_history) == 0:
        passed_tests += 1
    if len(users_with_zero_balance) == 0:
        passed_tests += 1
    
    print(f"Tests Passed: {passed_tests}/{total_tests}")
    print()
    
    # Statistics
    print("DATABASE STATISTICS:")
    print(f"  - Total users: {db.users.count_documents({})}")
    print(f"  - Currently subscribed: {db.users.count_documents({'isSubscribed': True})}")
    print(f"  - Was premium (expired): {db.users.count_documents({'wasPremium': True, 'isSubscribed': False})}")
    print(f"  - Never premium: {db.users.count_documents({'wasPremium': {'$ne': True}, 'isSubscribed': False})}")
    print(f"  - Users with history: {db.users.count_documents({'subscriptionHistory': {'$exists': True, '$ne': []}})}")
    print()
    
    if passed_tests == total_tests:
        print("✅ ALL TESTS PASSED - NO STALE DATA DETECTED")
        print("✅ DATA CLEANUP IS WORKING CORRECTLY")
        return True
    else:
        print("❌ SOME TESTS FAILED - STALE DATA DETECTED")
        print("❌ REVIEW EXPIRATION MANAGER IMPLEMENTATION")
        return False


if __name__ == '__main__':
    # Get MongoDB URI from environment or use default
    mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
    
    print()
    print("Starting verification...")
    print(f"MongoDB URI: {mongo_uri}")
    print()
    
    success = verify_no_stale_data(mongo_uri)
    
    exit(0 if success else 1)
