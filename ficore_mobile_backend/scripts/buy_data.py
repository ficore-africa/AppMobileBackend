#!/usr/bin/env python3
"""
FiCore Emergency Data Purchase Script
Buy data when you're out of data and can't access the app

Usage:
    python buy_data.py                          # Default: ₦500 MTN data
    python buy_data.py 200                      # ₦200 MTN data
    python buy_data.py 500 airtel               # ₦500 Airtel data
    python buy_data.py 1000 glo 08012345678     # ₦1000 Glo data for different number
"""

import requests
import json
from datetime import datetime
import time
import sys

# Configuration
API_BASE = "https://mobilebackend.ficoreafrica.com"
USER_EMAIL = "warpiiv@gmail.com"
USER_PASSWORD = "Abumeemah123!"
DEFAULT_PHONE = "08133128979"

# Parse command line arguments
DATA_AMOUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 500  # Default: ₦500
NETWORK = sys.argv[2].lower() if len(sys.argv) > 2 else 'mtn'  # Default: MTN
PHONE_NUMBER = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PHONE

print("=" * 100)
print("FICORE EMERGENCY DATA PURCHASE")
print("=" * 100)
print(f"User: {USER_EMAIL}")
print(f"Network: {NETWORK.upper()}")
print(f"Amount: ₦{DATA_AMOUNT}")
print(f"Phone: {PHONE_NUMBER}")
print(f"Time: {datetime.utcnow().isoformat()}")
print("=" * 100)
print()

# ===== STEP 1: LOGIN =====
print("🔐 Step 1: Logging in...")
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

# ===== STEP 3: GET DATA PLANS =====
print(f"📊 Step 3: Fetching {NETWORK.upper()} data plans...")

# Try different network identifier formats
network_ids = [NETWORK, NETWORK.upper(), f"{NETWORK}_data_share"]
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
                print(f"✅ Found {len(plans)} plans for {NETWORK.upper()}")
                break

if not plans:
    print(f"❌ Could not fetch data plans for {NETWORK.upper()}")
    print("Available networks: mtn, airtel, glo, 9mobile")
    exit(1)

# Find plan matching the amount
target_plan = None
for plan in plans:
    plan_price = plan.get('price', 0)
    if plan_price == DATA_AMOUNT:
        target_plan = plan
        break

if not target_plan:
    print(f"❌ No ₦{DATA_AMOUNT} plan found for {NETWORK.upper()}")
    print()
    print("Available plans:")
    # Group plans by price
    price_groups = {}
    for plan in plans:
        price = plan.get('price', 0)
        if price > 0:
            if price not in price_groups:
                price_groups[price] = []
            price_groups[price].append(plan)
    
    # Show unique prices
    for price in sorted(price_groups.keys())[:10]:
        example_plan = price_groups[price][0]
        count = len(price_groups[price])
        print(f"   ₦{price:,.0f} - {example_plan.get('name', 'Unknown')} ({count} plan{'s' if count > 1 else ''})")
    
    print()
    print(f"Try one of these amounts: {', '.join([f'₦{p}' for p in sorted(price_groups.keys())[:5]])}")
    exit(1)

print(f"✅ Found plan: {target_plan.get('name', 'Unknown')}")
print(f"   Price: ₦{target_plan.get('price', 0):,.0f}")
print(f"   Data: {target_plan.get('volume', 'Unknown')}MB")
print(f"   Validity: {target_plan.get('duration', 'Unknown')} {target_plan.get('durationUnit', '')}")
print()

# ===== STEP 4: PURCHASE DATA =====
print("🛒 Step 4: Purchasing data...")

purchase_payload = {
    "network": selected_network,
    "dataPlanId": target_plan.get('id'),
    "dataPlanName": target_plan.get('name', 'Unknown'),
    "phoneNumber": PHONE_NUMBER,
    "amount": DATA_AMOUNT
}

print(f"📤 Sending purchase request...")
print()

purchase_response = requests.post(
    f"{API_BASE}/api/vas/purchase/buy-data",
    json=purchase_payload,
    headers={
        "Authorization": f"Bearer {user_token}",
        "Content-Type": "application/json"
    },
    timeout=60
)

print(f"📥 Response received: {purchase_response.status_code}")
print()

if purchase_response.status_code != 200:
    print(f"❌ Purchase failed: {purchase_response.status_code}")
    print(f"Response: {purchase_response.text}")
    exit(1)

purchase_data = purchase_response.json()

if not purchase_data.get('success'):
    print(f"❌ Purchase failed: {purchase_data.get('message')}")
    user_message = purchase_data.get('user_message', {})
    if user_message:
        print(f"User Message: {user_message.get('message', 'Unknown error')}")
    exit(1)

# ===== SUCCESS =====
print("✅ Purchase successful!")
transaction_data = purchase_data.get('data', {})
transaction_id = transaction_data.get('transactionId', 'Unknown')
status = transaction_data.get('processingStatus', 'Unknown')
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
print(f"Plan Name: {transaction_data.get('planName', 'Unknown')}")
print("=" * 100)
print()

# ===== STEP 5: CHECK NEW BALANCE =====
print("💰 Step 5: Checking new wallet balance...")
time.sleep(2)

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
        new_balance = wallet_data.get('data', {}).get('availableBalance', 0)
        print(f"✅ New balance: ₦{new_balance:,.2f}")
        print(f"   Deducted: ₦{balance - new_balance:,.2f}")
print()

print("=" * 100)
print("SUMMARY")
print("=" * 100)
print(f"✅ Successfully purchased ₦{DATA_AMOUNT} {NETWORK.upper()} data for {PHONE_NUMBER}")
print(f"✅ Transaction ID: {transaction_id}")
print(f"✅ Status: {status}")
print()
print("⏳ Data will be delivered within 30-60 seconds")
print("🎉 Purchase completed successfully!")
print("=" * 100)
