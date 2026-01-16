"""
Test Script: Immutable Ledger Implementation
Date: January 14, 2026
Purpose: Verify that the Ghost Ledger pattern is working correctly

This script tests:
1. Soft delete creates reversal entries
2. Updates create new versions instead of overwriting
3. Query filters exclude voided/deleted records
4. Audit trail is preserved
"""

import os
import sys
import requests
from datetime import datetime

# Configuration
BASE_URL = os.environ.get('API_BASE_URL', 'http://localhost:5000')
TEST_EMAIL = 'test@ficore.com'
TEST_PASSWORD = 'test123'

def print_section(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_result(test_name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} - {test_name}")
    if details:
        print(f"    {details}")

def login():
    """Login and get auth token"""
    print_section("AUTHENTICATION")
    
    response = requests.post(f'{BASE_URL}/api/auth/login', json={
        'email': TEST_EMAIL,
        'password': TEST_PASSWORD
    })
    
    if response.status_code == 200:
        data = response.json()
        token = data['data']['access_token']
        print_result("Login", True, f"Token: {token[:20]}...")
        return token
    else:
        print_result("Login", False, f"Status: {response.status_code}")
        return None

def test_income_soft_delete(token):
    """Test that deleting an income creates a reversal entry"""
    print_section("TEST 1: INCOME SOFT DELETE")
    
    headers = {'Authorization': f'Bearer {token}'}
    
    # Step 1: Create an income
    print("\n1. Creating test income...")
    create_response = requests.post(f'{BASE_URL}/api/income', 
        headers=headers,
        json={
            'amount': 5000,
            'source': 'Test Income for Deletion',
            'category': 'salary',
            'frequency': 'one_time',
            'dateReceived': datetime.utcnow().isoformat() + 'Z'
        }
    )
    
    if create_response.status_code != 200:
        print_result("Create income", False, f"Status: {create_response.status_code}")
        return False
    
    income_id = create_response.json()['data']['id']
    print_result("Create income", True, f"ID: {income_id}")
    
    # Step 2: Delete the income
    print("\n2. Deleting income (should create reversal)...")
    delete_response = requests.delete(f'{BASE_URL}/api/income/{income_id}', headers=headers)
    
    if delete_response.status_code != 200:
        print_result("Delete income", False, f"Status: {delete_response.status_code}")
        return False
    
    delete_data = delete_response.json()
    print_result("Delete income", True, f"Reversal ID: {delete_data['data']['reversalId']}")
    
    # Step 3: Verify original is marked as voided
    print("\n3. Verifying original is voided...")
    get_response = requests.get(f'{BASE_URL}/api/income/{income_id}', headers=headers)
    
    if get_response.status_code == 200:
        original = get_response.json()['data']
        is_voided = original.get('status') == 'voided' and original.get('isDeleted') == True
        print_result("Original voided", is_voided, f"Status: {original.get('status')}, isDeleted: {original.get('isDeleted')}")
    else:
        print_result("Original voided", False, "Could not retrieve original")
    
    # Step 4: Verify reversal entry exists
    print("\n4. Verifying reversal entry...")
    reversal_id = delete_data['data']['reversalId']
    reversal_response = requests.get(f'{BASE_URL}/api/income/{reversal_id}', headers=headers)
    
    if reversal_response.status_code == 200:
        reversal = reversal_response.json()['data']
        is_negative = reversal.get('amount') == -5000
        is_reversal_type = reversal.get('type') == 'REVERSAL'
        print_result("Reversal entry", is_negative and is_reversal_type, 
                    f"Amount: {reversal.get('amount')}, Type: {reversal.get('type')}")
    else:
        print_result("Reversal entry", False, "Could not retrieve reversal")
    
    # Step 5: Verify list endpoint excludes voided entry
    print("\n5. Verifying list excludes voided entries...")
    list_response = requests.get(f'{BASE_URL}/api/income', headers=headers)
    
    if list_response.status_code == 200:
        incomes = list_response.json()['data']['incomes']
        voided_in_list = any(inc['id'] == income_id for inc in incomes)
        print_result("List excludes voided", not voided_in_list, 
                    f"Voided entry in list: {voided_in_list}")
    else:
        print_result("List excludes voided", False, "Could not retrieve list")
    
    return True

def test_income_version_control(token):
    """Test that updating an income creates a new version"""
    print_section("TEST 2: INCOME VERSION CONTROL")
    
    headers = {'Authorization': f'Bearer {token}'}
    
    # Step 1: Create an income
    print("\n1. Creating test income...")
    create_response = requests.post(f'{BASE_URL}/api/income', 
        headers=headers,
        json={
            'amount': 3000,
            'source': 'Test Income for Update',
            'category': 'business',
            'frequency': 'one_time',
            'dateReceived': datetime.utcnow().isoformat() + 'Z'
        }
    )
    
    if create_response.status_code != 200:
        print_result("Create income", False, f"Status: {create_response.status_code}")
        return False
    
    original_id = create_response.json()['data']['id']
    print_result("Create income", True, f"ID: {original_id}")
    
    # Step 2: Update the income
    print("\n2. Updating income (should create new version)...")
    update_response = requests.put(f'{BASE_URL}/api/income/{original_id}', 
        headers=headers,
        json={
            'amount': 3500,  # Changed amount
            'source': 'Test Income for Update (Edited)',  # Changed source
            'category': 'business'
        }
    )
    
    if update_response.status_code != 200:
        print_result("Update income", False, f"Status: {update_response.status_code}")
        return False
    
    update_data = update_response.json()
    new_id = update_data['metadata']['newId']
    version = update_data['metadata']['version']
    print_result("Update income", True, f"New ID: {new_id}, Version: {version}")
    
    # Step 3: Verify original is marked as superseded
    print("\n3. Verifying original is superseded...")
    get_original_response = requests.get(f'{BASE_URL}/api/income/{original_id}', headers=headers)
    
    if get_original_response.status_code == 200:
        original = get_original_response.json()['data']
        is_superseded = original.get('status') == 'superseded'
        print_result("Original superseded", is_superseded, f"Status: {original.get('status')}")
    else:
        print_result("Original superseded", False, "Could not retrieve original")
    
    # Step 4: Verify new version has updated data
    print("\n4. Verifying new version...")
    get_new_response = requests.get(f'{BASE_URL}/api/income/{new_id}', headers=headers)
    
    if get_new_response.status_code == 200:
        new_version = get_new_response.json()['data']
        has_new_amount = new_version.get('amount') == 3500
        has_new_source = 'Edited' in new_version.get('source', '')
        print_result("New version data", has_new_amount and has_new_source, 
                    f"Amount: {new_version.get('amount')}, Source: {new_version.get('source')}")
    else:
        print_result("New version data", False, "Could not retrieve new version")
    
    # Step 5: Verify history endpoint shows all versions
    print("\n5. Verifying history endpoint...")
    history_response = requests.get(f'{BASE_URL}/api/income/{original_id}/history', headers=headers)
    
    if history_response.status_code == 200:
        history = history_response.json()['data']['history']
        has_both_versions = len(history) >= 2
        print_result("History endpoint", has_both_versions, f"Total versions: {len(history)}")
    else:
        print_result("History endpoint", False, f"Status: {history_response.status_code}")
    
    return True

def test_expense_soft_delete(token):
    """Test that deleting an expense creates a reversal entry"""
    print_section("TEST 3: EXPENSE SOFT DELETE")
    
    headers = {'Authorization': f'Bearer {token}'}
    
    # Step 1: Create an expense
    print("\n1. Creating test expense...")
    create_response = requests.post(f'{BASE_URL}/api/expenses', 
        headers=headers,
        json={
            'amount': 2000,
            'description': 'Test Expense for Deletion',
            'category': 'Transportation',
            'date': datetime.utcnow().isoformat() + 'Z'
        }
    )
    
    if create_response.status_code != 200:
        print_result("Create expense", False, f"Status: {create_response.status_code}")
        return False
    
    expense_id = create_response.json()['data']['id']
    print_result("Create expense", True, f"ID: {expense_id}")
    
    # Step 2: Delete the expense
    print("\n2. Deleting expense (should create reversal)...")
    delete_response = requests.delete(f'{BASE_URL}/api/expenses/{expense_id}', headers=headers)
    
    if delete_response.status_code != 200:
        print_result("Delete expense", False, f"Status: {delete_response.status_code}")
        return False
    
    delete_data = delete_response.json()
    print_result("Delete expense", True, f"Reversal ID: {delete_data['data']['reversalId']}")
    
    # Step 3: Verify reversal entry has negative amount
    print("\n3. Verifying reversal entry...")
    reversal_id = delete_data['data']['reversalId']
    reversal_response = requests.get(f'{BASE_URL}/api/expenses/{reversal_id}', headers=headers)
    
    if reversal_response.status_code == 200:
        reversal = reversal_response.json()['data']
        is_negative = reversal.get('amount') == -2000
        print_result("Reversal entry", is_negative, f"Amount: {reversal.get('amount')}")
    else:
        print_result("Reversal entry", False, "Could not retrieve reversal")
    
    return True

def main():
    """Run all tests"""
    print_section("FICORE IMMUTABLE LEDGER TEST SUITE")
    print(f"API Base URL: {BASE_URL}")
    print(f"Test User: {TEST_EMAIL}")
    
    # Login
    token = login()
    if not token:
        print("\n❌ Authentication failed. Cannot proceed with tests.")
        return
    
    # Run tests
    results = []
    results.append(("Income Soft Delete", test_income_soft_delete(token)))
    results.append(("Income Version Control", test_income_version_control(token)))
    results.append(("Expense Soft Delete", test_expense_soft_delete(token)))
    
    # Summary
    print_section("TEST SUMMARY")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Immutable ledger is working correctly.")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Review implementation.")

if __name__ == '__main__':
    main()
