#!/usr/bin/env python3
"""
Automated script to refresh GitHub Actions ADMIN_TOKEN.
This script logs in to the backend, gets a fresh token, and shows you how to update it.

Usage:
    python refresh_github_token.py
"""

import requests
import json
import sys

# Configuration
BACKEND_URL = "https://mobilebackend.ficoreafrica.com"
ADMIN_EMAIL = "admin@ficore.com"
ADMIN_PASSWORD = "admin123"
GITHUB_REPO = "ficore-africa/AppMobileBackend"

def get_admin_token():
    """Login and get a fresh admin token."""
    print("🔐 Logging in to backend...")
    
    try:
        response = requests.post(
            f"{BACKEND_URL}/auth/login",
            headers={"Content-Type": "application/json"},
            json={
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Debug: Print response structure
            print(f"   Response: {json.dumps(data, indent=2)[:500]}")
            
            # Try different response formats
            token = None
            user = None
            
            if data.get('success') and 'data' in data:
                # Format 1: {"success": true, "data": {"accessToken": "...", "user": {...}}}
                token = data['data'].get('accessToken') or data['data'].get('access_token')
                user = data['data'].get('user', {})
            elif 'data' in data:
                # Format 2: {"data": {"access_token": "..."}}
                token = data['data'].get('access_token') or data['data'].get('accessToken')
                user = data.get('user', {})
            elif 'accessToken' in data:
                # Format 3: {"accessToken": "...", "user": {...}}
                token = data.get('accessToken')
                user = data.get('user', {})
            elif 'access_token' in data:
                # Format 4: {"access_token": "..."}
                token = data.get('access_token')
                user = data.get('user', {})
            
            if token:
                print(f"✅ Login successful!")
                if user:
                    print(f"   Email: {user.get('email', 'N/A')}")
                    print(f"   Role: {user.get('role', 'N/A')}")
                print()
                return token
            else:
                print(f"❌ Login failed: Could not find token in response")
                return None
        else:
            print(f"❌ HTTP {response.status_code}: {response.text}")
            return None
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to {BACKEND_URL}")
        print("   Check if backend is running")
        return None
    except requests.exceptions.Timeout:
        print(f"❌ Request timed out")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def test_token(token):
    """Test if the token works by calling the expiration endpoint."""
    print("🧪 Testing token...")
    
    try:
        response = requests.post(
            f"{BACKEND_URL}/admin/subscriptions/process-expirations",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Token works!")
            print(f"   Processed: {data.get('data', {}).get('expired_count', 0)} expired subscriptions")
            print(f"   Total checked: {data.get('data', {}).get('total_checked', 0)}")
            return True
        elif response.status_code == 401:
            print(f"❌ Token invalid or expired")
            return False
        elif response.status_code == 403:
            print(f"❌ Token valid but not admin")
            return False
        else:
            print(f"⚠️  HTTP {response.status_code}: {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing token: {e}")
        return False

def main():
    print("=" * 60)
    print("GitHub Actions Token Refresh Script")
    print("=" * 60)
    print()
    
    # Step 1: Get token
    token = get_admin_token()
    if not token:
        print("\n❌ Failed to get admin token")
        sys.exit(1)
    
    # Step 2: Test token
    print()
    if not test_token(token):
        print("\n⚠️  Token obtained but test failed")
        print("   Continuing anyway...")
    
    # Step 3: Show token and instructions
    print()
    print("=" * 60)
    print("✅ SUCCESS! Here's your fresh admin token:")
    print("=" * 60)
    print()
    print(token)
    print()
    print("=" * 60)
    print("📋 Next Steps:")
    print("=" * 60)
    print()
    print("1. Copy the token above (the long string)")
    print()
    print("2. Go to GitHub Secrets:")
    print(f"   https://github.com/{GITHUB_REPO}/settings/secrets/actions")
    print()
    print("3. Click on 'ADMIN_TOKEN'")
    print()
    print("4. Click 'Update'")
    print()
    print("5. Paste the token")
    print()
    print("6. Click 'Update secret'")
    print()
    print("7. Test the workflow:")
    print(f"   https://github.com/{GITHUB_REPO}/actions/workflows/expire-subscriptions.yml")
    print("   Click 'Run workflow' → 'Run workflow'")
    print()
    print("=" * 60)
    print("⏰ Token Expiration:")
    print("=" * 60)
    print()
    print("This token will expire in 24-30 days.")
    print("Run this script again when the workflow fails with 'Token has expired'")
    print()
    print("💡 Tip: Set a calendar reminder to refresh monthly")
    print()

if __name__ == '__main__':
    main()
