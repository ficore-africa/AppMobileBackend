"""
Quick test script for atomic entry endpoints
Run this after starting the server to verify endpoints are working
"""

import requests
import json
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:5000"
# Replace with a valid token from your test user
TEST_TOKEN = "YOUR_TEST_TOKEN_HERE"

headers = {
    "Authorization": f"Bearer {TEST_TOKEN}",
    "Content-Type": "application/json"
}

def test_health_check():
    """Test if server is running"""
    print("\n" + "="*60)
    print("TEST 1: Health Check")
    print("="*60)
    
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 200, "Health check failed"
    print("✓ Health check passed")

def test_create_expense_free_entry():
    """Test creating expense as free user within limit"""
    print("\n" + "="*60)
    print("TEST 2: Create Expense (Free Entry)")
    print("="*60)
    
    data = {
        "amount": 500.0,
        "description": "Test expense - free entry",
        "category": "Food",
        "date": datetime.utcnow().isoformat() + "Z"
    }
    
    response = requests.post(
        f"{BASE_URL}/atomic/expenses/create-with-payment",
        headers=headers,
        json=data
    )
    
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 201:
        result = response.json()
        assert result['success'] == True
        assert result['data']['fc_charge_amount'] == 0.0
        print("✓ Free expense created successfully")
    elif response.status_code == 402:
        print("⚠ User is over monthly limit - FC charge required")
    else:
        print(f"✗ Unexpected status code: {response.status_code}")

def test_create_income_free_entry():
    """Test creating income as free user within limit"""
    print("\n" + "="*60)
    print("TEST 3: Create Income (Free Entry)")
    print("="*60)
    
    data = {
        "amount": 1000.0,
        "source": "Test salary",
        "category": "salary",
        "dateReceived": datetime.utcnow().isoformat() + "Z"
    }
    
    response = requests.post(
        f"{BASE_URL}/atomic/income/create-with-payment",
        headers=headers,
        json=data
    )
    
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 201:
        result = response.json()
        assert result['success'] == True
        assert result['data']['fc_charge_amount'] == 0.0
        print("✓ Free income created successfully")
    elif response.status_code == 402:
        print("⚠ User is over monthly limit - FC charge required")
    else:
        print(f"✗ Unexpected status code: {response.status_code}")

def test_validation_errors():
    """Test validation errors"""
    print("\n" + "="*60)
    print("TEST 4: Validation Errors")
    print("="*60)
    
    # Test missing amount
    data = {
        "description": "Test",
        "category": "Food"
    }
    
    response = requests.post(
        f"{BASE_URL}/atomic/expenses/create-with-payment",
        headers=headers,
        json=data
    )
    
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 400, "Should return 400 for validation error"
    assert 'amount' in response.json()['errors']
    print("✓ Validation error handled correctly")

def test_unauthorized_access():
    """Test unauthorized access"""
    print("\n" + "="*60)
    print("TEST 5: Unauthorized Access")
    print("="*60)
    
    data = {
        "amount": 500.0,
        "description": "Test",
        "category": "Food"
    }
    
    # No authorization header
    response = requests.post(
        f"{BASE_URL}/atomic/expenses/create-with-payment",
        json=data
    )
    
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 401, "Should return 401 for unauthorized"
    print("✓ Unauthorized access blocked correctly")

def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("ATOMIC ENTRIES ENDPOINT TESTS")
    print("="*60)
    
    try:
        test_health_check()
        
        if TEST_TOKEN == "YOUR_TEST_TOKEN_HERE":
            print("\n⚠ WARNING: Please set TEST_TOKEN to a valid token")
            print("Skipping authenticated tests...")
        else:
            test_create_expense_free_entry()
            test_create_income_free_entry()
            test_validation_errors()
        
        test_unauthorized_access()
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
    except requests.exceptions.ConnectionError:
        print(f"\n✗ Cannot connect to {BASE_URL}")
        print("Make sure the server is running: python start_server.py")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")

if __name__ == "__main__":
    print("\nATOMIC ENTRIES ENDPOINT TEST SCRIPT")
    print("====================================")
    print(f"Base URL: {BASE_URL}")
    print(f"Token: {'Set' if TEST_TOKEN != 'YOUR_TEST_TOKEN_HERE' else 'NOT SET'}")
    
    run_all_tests()
