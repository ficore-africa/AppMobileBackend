#!/usr/bin/env python3
"""
Real User Data Purchase Script
Simulates warpiiv@gmail.com buying ₦200 data for 08133128979

This script follows the EXACT flow a real user would take:
1. Login to get JWT token
2. Check wallet balance
3. Get available data plans
4. Purchase ₦200 data plan
5. Verify transaction success
"""

import requests
import json
from datetime import datetime
import time

# Configuration
API_BASE = "https://mobilebackend.ficoreafrica.com"
USER_EMAIL = "warpiiv@gmail.com"
USER_PASSWORD = "Abumeemah123!"
PHONE_NUMBER = "08133128979"
DATA_AMOUNT = 200  # ₦200 data plan

print("=" * 100)
print("FICORE DATA PURCHASE - REAL USER SIMULATION")
print("=" * 100)
print(f"User: {USER_EMAIL}")
print(f"Phone: {PHONE_NUMBER}")
print(f"Amount: ₦{DATA_AMOUNT}")
print(f"Time: {datetime.utcnow().isoformat()}")
print("=" * 100)
print()

# ===== STEP 1: LOGIN =====
print("🔐 Step 1: Logging in as user...")
login_response = requests.post(
    f"{API_BASE}/auth/login",
    json={
        "email": USER_EMAIL,
        "password": USER_PASSWORD
    },
    headers={"Content-Type": "application/json"}
)

if login_response.status_code != 200:
    print(f"❌ Login failed: {login_response.status_code}")
    print(f"Response: {login_response.text}")
    exit(1)

login_data = login_response.json()
if not login_data.get('success'):
    print(f"❌ Login failed: {login_data.get('message')}")
    exit(1)

user_token = login_data.get('token') or login_data.get('data', {}).get('token')
if not user_token:
    print("❌ No token in response")
    exit(1)

print(f"✅ Login successful!")
print(f"Token: {user_token[:30]}...")
print()

# ===== STEP 2: CHECK WALLET BALANCE =====
print("💰 Step 2: Checking wallet balance...")
wallet_response = requests.get(
    f"{API_BASE}/api/vas/wallet/balance",
    headers={
        "Authorization": f"Bearer {user_token}",
        "Content-Type": "application/json"
    }
)

if wallet_response.status_code == 200:
    wallet_data = wallet_response.json()
    if wallet_data.get('success'):
        data = wallet_data.get('data', {})
        # Use availableBalance, not balance
        balance = data.get('availableBalance', 0)
        total_balance = data.get('totalBalance', 0)
        reserved = data.get('reservedAmount', 0)
        
        print(f"✅ Wallet Status:")
        print(f"   Total Balance: ₦{total_balance:,.2f}")
        print(f"   Reserved: ₦{reserved:,.2f}")
        print(f"   Available: ₦{balance:,.2f}")
        
        if balance < DATA_AMOUNT:
            print(f"❌ Insufficient balance! Need ₦{DATA_AMOUNT}, have ₦{balance}")
            print("Please deposit funds first")
            exit(1)
    else:
        print(f"⚠️ Could not fetch balance: {wallet_data.get('message')}")
else:
    print(f"⚠️ Wallet check failed: {wallet_response.status_code}")
print()

# ===== STEP 3: GET DATA NETWORKS =====
print("📡 Step 3: Fetching available networks...")
networks_response = requests.get(
    f"{API_BASE}/api/vas/purchase/networks/data",
    headers={
        "Authorization": f"Bearer {user_token}",
        "Content-Type": "application/json"
    }
)

if networks_response.status_code != 200:
    print(f"❌ Failed to fetch networks: {networks_response.status_code}")
    print(f"Response: {networks_response.text}")
    exit(1)

networks_data = networks_response.json()
if not networks_data.get('success'):
    print(f"❌ Failed to fetch networks: {networks_data.get('message')}")
    exit(1)

# Handle both response formats
data = networks_data.get('data', {})
if isinstance(data, list):
    networks = data
else:
    networks = data.get('networks', [])

print(f"✅ Found {len(networks)} networks:")
for net in networks:
    if isinstance(net, dict):
        print(f"   - {net.get('name', 'Unknown')} (ID: {net.get('id', 'N/A')})")
    else:
        print(f"   - {net}")
print()

# ===== STEP 4: GET MTN DATA PLANS =====
print("📊 Step 4: Fetching MTN data plans...")
# Try different network identifiers (frontend might use different formats)
network_ids = ['mtn', 'MTN', 'mtn_data_share']
plans = []
selected_network = None

for network_id in network_ids:
    plans_response = requests.get(
        f"{API_BASE}/api/vas/purchase/data-plans/{network_id}",
        headers={
            "Authorization": f"Bearer {user_token}",
            "Content-Type": "application/json"
        }
    )
    
    if plans_response.status_code == 200:
        plans_data = plans_response.json()
        if plans_data.get('success'):
            # Handle both response formats
            data = plans_data.get('data', {})
            if isinstance(data, list):
                plans = data
            else:
                plans = data.get('plans', [])
            
            if plans:
                selected_network = network_id
                print(f"✅ Found {len(plans)} plans for network '{network_id}'")
                break
    else:
        print(f"⚠️ Network '{network_id}' failed: {plans_response.status_code}")

if not plans:
    print("❌ Could not fetch data plans for any network")
    exit(1)

# Find ₦200 plan
target_plan = None
for plan in plans:
    plan_price = plan.get('price', 0)  # Use 'price' not 'amount'
    if plan_price == DATA_AMOUNT:
        target_plan = plan
        break

if not target_plan:
    print(f"❌ No ₦{DATA_AMOUNT} plan found")
    print("Available plans:")
    for plan in plans[:10]:
        print(f"   - {plan.get('name', 'Unknown')}: ₦{plan.get('price', 0)}")
    exit(1)

print(f"✅ Found plan: {target_plan.get('name', 'Unknown')}")
print(f"   Price: ₦{target_plan.get('price', 0)}")
print(f"   Data: {target_plan.get('volume', 'Unknown')}MB")
print(f"   Validity: {target_plan.get('duration', 'Unknown')} {target_plan.get('durationUnit', '')}")
print(f"   Plan ID: {target_plan.get('id', 'Unknown')}")
print()

# ===== STEP 5: PURCHASE DATA =====
print("🛒 Step 5: Purchasing data...")
print(f"   Network: {selected_network}")
print(f"   Plan: {target_plan.get('name', 'Unknown')}")
print(f"   Phone: {PHONE_NUMBER}")
print(f"   Amount: ₦{DATA_AMOUNT}")
print()

purchase_payload = {
    "network": selected_network,
    "dataPlanId": target_plan.get('id'),  # Backend expects 'dataPlanId'
    "dataPlanName": target_plan.get('name', 'Unknown'),  # Also send plan name
    "phoneNumber": PHONE_NUMBER,
    "amount": DATA_AMOUNT
}

print(f"📤 Sending purchase request...")
print(f"Payload: {json.dumps(purchase_payload, indent=2)}")
print()

purchase_response = requests.post(
    f"{API_BASE}/api/vas/purchase/buy-data",
    json=purchase_payload,
    headers={
        "Authorization": f"Bearer {user_token}",
        "Content-Type": "application/json"
    },
    timeout=60  # 60 second timeout (data purchases can take time)
)

print(f"📥 Response received: {purchase_response.status_code}")
print()

if purchase_response.status_code != 200:
    print(f"❌ Purchase failed: {purchase_response.status_code}")
    print(f"Response: {purchase_response.text}")
    exit(1)

purchase_data = purchase_response.json()
print("=" * 100)
print("PURCHASE RESPONSE")
print("=" * 100)
print(json.dumps(purchase_data, indent=2))
print("=" * 100)
print()

if not purchase_data.get('success'):
    print(f"❌ Purchase failed: {purchase_data.get('message')}")
    
    # Check if it's a user-friendly error
    user_message = purchase_data.get('user_message', {})
    if user_message:
        print(f"User Message: {user_message.get('message', 'Unknown error')}")
    
    exit(1)

# ===== STEP 6: VERIFY TRANSACTION =====
print("✅ Purchase successful!")
transaction_data = purchase_data.get('data', {})
transaction_id = transaction_data.get('transactionId', 'Unknown')
status = transaction_data.get('status', 'Unknown')
provider = transaction_data.get('provider', 'Unknown')

print()
print("=" * 100)
print("TRANSACTION DETAILS")
print("=" * 100)
print(f"Transaction ID: {transaction_id}")
print(f"Status: {status}")
print(f"Provider: {provider}")
print(f"Network: {transaction_data.get('network', 'Unknown')}")
print(f"Phone Number: {transaction_data.get('phoneNumber', 'Unknown')}")
print(f"Amount: ₦{transaction_data.get('amount', 0):,.2f}")
print(f"Data Value: {transaction_data.get('dataValue', 'Unknown')}")
print(f"Plan Name: {transaction_data.get('planName', 'Unknown')}")
print(f"Created At: {transaction_data.get('createdAt', 'Unknown')}")
print("=" * 100)
print()

# ===== STEP 7: CHECK NEW BALANCE =====
print("💰 Step 7: Checking new wallet balance...")
time.sleep(2)  # Wait for balance to update

wallet_response = requests.get(
    f"{API_BASE}/api/vas/wallet/balance",
    headers={
        "Authorization": f"Bearer {user_token}",
        "Content-Type": "application/json"
    }
)

if wallet_response.status_code == 200:
    wallet_data = wallet_response.json()
    if wallet_data.get('success'):
        new_balance = wallet_data.get('data', {}).get('balance', 0)
        print(f"✅ New balance: ₦{new_balance:,.2f}")
        print(f"   Deducted: ₦{balance - new_balance:,.2f}")
    else:
        print(f"⚠️ Could not fetch new balance: {wallet_data.get('message')}")
else:
    print(f"⚠️ Balance check failed: {wallet_response.status_code}")
print()

print("=" * 100)
print("SUMMARY")
print("=" * 100)
print(f"✅ Successfully purchased ₦{DATA_AMOUNT} data for {PHONE_NUMBER}")
print(f"✅ Transaction ID: {transaction_id}")
print(f"✅ Status: {status}")
print(f"✅ Provider: {provider}")
print()
print("This transaction will appear in:")
print("1. Treasury Dashboard (Recent VAS Transactions)")
print("2. User's transaction history")
print("3. Provider breakdown (Monnify/Peyflex)")
print("4. Commission calculations")
print()
print("🎉 Purchase completed successfully!")
print("=" * 100)
