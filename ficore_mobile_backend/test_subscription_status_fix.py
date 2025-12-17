#!/usr/bin/env python3
"""
Test script to verify /subscription/status endpoint fix

This script tests that /subscription/status now returns consistent,
validated subscription data just like /credits/monthly-entries
"""

import requests
import json
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId
import os

# Configuration
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000')
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')

# Test user credentials (update these)
TEST_USER_EMAIL = os.getenv('TEST_USER_EMAIL', 'test@example.com')
TEST_USER_PASSWORD = os.getenv('TEST_USER_PASSWORD', 'testpassword')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@example.com')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'adminpassword')


class SubscriptionStatusTester:
    def __init__(self):
        self.api_base = API_BASE_URL
        self.mongo_client = MongoClient(MONGO_URI)
        self.db = self.mongo_client.get_database()
        self.user_token = None
        self.admin_token = None
        self.test_user_id = None
        
    def login(self, email, password):
        """Login and get auth token"""
        response = requests.post(
            f'{self.api_base}/auth/login',
            json={'email': email, 'password': password}
        )
        
        if response.status_code == 200:
            data = response.json()
            return data['data']['access_token']
        else:
            raise Exception(f"Login failed: {response.text}")
    
    def setup(self):
        """Setup test environment"""
        print("🔧 Setting up test environment...")
        
        # Login as test user
        try:
            self.user_token = self.login(TEST_USER_EMAIL, TEST_USER_PASSWORD)
            print(f"✅ Logged in as test user: {TEST_USER_EMAIL}")
        except Exception as e:
            print(f"❌ Failed to login as test user: {e}")
            return False
        
        # Login as admin
        try:
            self.admin_token = self.login(ADMIN_EMAIL, ADMIN_PASSWORD)
            print(f"✅ Logged in as admin: {ADMIN_EMAIL}")
        except Exception as e:
            print(f"⚠️  Failed to login as admin: {e}")
            print("   (Admin tests will be skipped)")
        
        # Get test user ID
        user = self.db.users.find_one({'email': TEST_USER_EMAIL})
        if user:
            self.test_user_id = user['_id']
            print(f"✅ Found test user ID: {self.test_user_id}")
        else:
            print(f"❌ Test user not found in database")
            return False
        
        return True
    
    def call_subscription_status(self):
        """Call /subscription/status endpoint"""
        response = requests.get(
            f'{self.api_base}/subscription/status',
            headers={'Authorization': f'Bearer {self.user_token}'}
        )
        
        if response.status_code == 200:
            return response.json()['data']
        else:
            raise Exception(f"API call failed: {response.text}")
    
    def call_monthly_entries(self):
        """Call /credits/monthly-entries endpoint"""
        response = requests.get(
            f'{self.api_base}/credits/monthly-entries',
            headers={'Authorization': f'Bearer {self.user_token}'}
        )
        
        if response.status_code == 200:
            return response.json()['data']
        else:
            raise Exception(f"API call failed: {response.text}")
    
    def test_consistency(self):
        """Test 1: Verify consistency between endpoints"""
        print("\n📋 Test 1: Consistency Between Endpoints")
        print("=" * 60)
        
        try:
            # Call both endpoints
            status_data = self.call_subscription_status()
            monthly_data = self.call_monthly_entries()
            
            # Compare key fields
            status_subscribed = status_data.get('is_subscribed')
            monthly_subscribed = monthly_data.get('is_subscribed')
            
            status_tier = status_data.get('tier')
            monthly_tier = monthly_data.get('tier')
            
            status_admin = status_data.get('is_admin')
            monthly_admin = monthly_data.get('is_admin')
            
            print(f"\n/subscription/status:")
            print(f"  is_subscribed: {status_subscribed}")
            print(f"  tier: {status_tier}")
            print(f"  is_admin: {status_admin}")
            
            print(f"\n/credits/monthly-entries:")
            print(f"  is_subscribed: {monthly_subscribed}")
            print(f"  tier: {monthly_tier}")
            print(f"  is_admin: {monthly_admin}")
            
            # Verify consistency
            if status_subscribed == monthly_subscribed:
                print(f"\n✅ is_subscribed matches: {status_subscribed}")
            else:
                print(f"\n❌ is_subscribed MISMATCH!")
                print(f"   /subscription/status: {status_subscribed}")
                print(f"   /monthly-entries: {monthly_subscribed}")
                return False
            
            if status_tier == monthly_tier:
                print(f"✅ tier matches: {status_tier}")
            else:
                print(f"❌ tier MISMATCH!")
                print(f"   /subscription/status: {status_tier}")
                print(f"   /monthly-entries: {monthly_tier}")
                return False
            
            if status_admin == monthly_admin:
                print(f"✅ is_admin matches: {status_admin}")
            else:
                print(f"❌ is_admin MISMATCH!")
                print(f"   /subscription/status: {status_admin}")
                print(f"   /monthly-entries: {monthly_admin}")
                return False
            
            print(f"\n✅ Test 1 PASSED: Endpoints are consistent")
            return True
            
        except Exception as e:
            print(f"\n❌ Test 1 FAILED: {e}")
            return False
    
    def test_expired_subscription(self):
        """Test 2: Verify expired subscription is detected"""
        print("\n📋 Test 2: Expired Subscription Detection")
        print("=" * 60)
        
        try:
            # Save current subscription state
            user = self.db.users.find_one({'_id': self.test_user_id})
            original_subscribed = user.get('isSubscribed')
            original_end_date = user.get('subscriptionEndDate')
            
            print(f"\nOriginal state:")
            print(f"  isSubscribed: {original_subscribed}")
            print(f"  subscriptionEndDate: {original_end_date}")
            
            # Set expired subscription (stale data)
            past_date = datetime.utcnow() - timedelta(days=30)
            self.db.users.update_one(
                {'_id': self.test_user_id},
                {'$set': {
                    'isSubscribed': True,  # Stale: says subscribed
                    'subscriptionEndDate': past_date  # But end date is past
                }}
            )
            
            print(f"\nSet stale data:")
            print(f"  isSubscribed: True (stale)")
            print(f"  subscriptionEndDate: {past_date} (expired)")
            
            # Call endpoint
            status_data = self.call_subscription_status()
            
            print(f"\nEndpoint response:")
            print(f"  is_subscribed: {status_data.get('is_subscribed')}")
            print(f"  tier: {status_data.get('tier')}")
            
            # Verify it corrected the stale data
            if status_data.get('is_subscribed') == False:
                print(f"\n✅ Correctly detected expired subscription")
                print(f"✅ Returned is_subscribed: False (corrected stale data)")
            else:
                print(f"\n❌ Failed to detect expired subscription")
                print(f"   Expected is_subscribed: False")
                print(f"   Got is_subscribed: {status_data.get('is_subscribed')}")
                return False
            
            if status_data.get('tier') == 'Free':
                print(f"✅ Correctly returned tier: Free")
            else:
                print(f"❌ Incorrect tier: {status_data.get('tier')}")
                return False
            
            # Restore original state
            self.db.users.update_one(
                {'_id': self.test_user_id},
                {'$set': {
                    'isSubscribed': original_subscribed,
                    'subscriptionEndDate': original_end_date
                }}
            )
            
            print(f"\n✅ Test 2 PASSED: Expired subscription detected correctly")
            return True
            
        except Exception as e:
            print(f"\n❌ Test 2 FAILED: {e}")
            # Restore original state on error
            try:
                self.db.users.update_one(
                    {'_id': self.test_user_id},
                    {'$set': {
                        'isSubscribed': original_subscribed,
                        'subscriptionEndDate': original_end_date
                    }}
                )
            except:
                pass
            return False
    
    def test_active_subscription(self):
        """Test 3: Verify active subscription is recognized"""
        print("\n📋 Test 3: Active Subscription Recognition")
        print("=" * 60)
        
        try:
            # Save current subscription state
            user = self.db.users.find_one({'_id': self.test_user_id})
            original_subscribed = user.get('isSubscribed')
            original_end_date = user.get('subscriptionEndDate')
            original_type = user.get('subscriptionType')
            
            # Set active subscription
            future_date = datetime.utcnow() + timedelta(days=365)
            self.db.users.update_one(
                {'_id': self.test_user_id},
                {'$set': {
                    'isSubscribed': True,
                    'subscriptionEndDate': future_date,
                    'subscriptionType': 'annually'
                }}
            )
            
            print(f"\nSet active subscription:")
            print(f"  isSubscribed: True")
            print(f"  subscriptionEndDate: {future_date}")
            print(f"  subscriptionType: annually")
            
            # Call endpoint
            status_data = self.call_subscription_status()
            
            print(f"\nEndpoint response:")
            print(f"  is_subscribed: {status_data.get('is_subscribed')}")
            print(f"  tier: {status_data.get('tier')}")
            print(f"  subscription_type: {status_data.get('subscription_type')}")
            
            # Verify it recognized active subscription
            if status_data.get('is_subscribed') == True:
                print(f"\n✅ Correctly recognized active subscription")
            else:
                print(f"\n❌ Failed to recognize active subscription")
                return False
            
            if status_data.get('tier') == 'Premium':
                print(f"✅ Correctly returned tier: Premium")
            else:
                print(f"❌ Incorrect tier: {status_data.get('tier')}")
                return False
            
            # Restore original state
            self.db.users.update_one(
                {'_id': self.test_user_id},
                {'$set': {
                    'isSubscribed': original_subscribed,
                    'subscriptionEndDate': original_end_date,
                    'subscriptionType': original_type
                }}
            )
            
            print(f"\n✅ Test 3 PASSED: Active subscription recognized correctly")
            return True
            
        except Exception as e:
            print(f"\n❌ Test 3 FAILED: {e}")
            # Restore original state on error
            try:
                self.db.users.update_one(
                    {'_id': self.test_user_id},
                    {'$set': {
                        'isSubscribed': original_subscribed,
                        'subscriptionEndDate': original_end_date,
                        'subscriptionType': original_type
                    }}
                )
            except:
                pass
            return False
    
    def run_all_tests(self):
        """Run all tests"""
        print("\n" + "=" * 60)
        print("🧪 SUBSCRIPTION STATUS FIX - TEST SUITE")
        print("=" * 60)
        
        if not self.setup():
            print("\n❌ Setup failed. Cannot run tests.")
            return
        
        results = []
        
        # Run tests
        results.append(("Consistency", self.test_consistency()))
        results.append(("Expired Subscription", self.test_expired_subscription()))
        results.append(("Active Subscription", self.test_active_subscription()))
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{test_name}: {status}")
        
        print(f"\nTotal: {passed}/{total} tests passed")
        
        if passed == total:
            print("\n🎉 ALL TESTS PASSED! Backend fix is working correctly.")
        else:
            print(f"\n⚠️  {total - passed} test(s) failed. Please review the output above.")


if __name__ == '__main__':
    tester = SubscriptionStatusTester()
    tester.run_all_tests()
