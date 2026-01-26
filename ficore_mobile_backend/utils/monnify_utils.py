"""
Monnify Bills API Utilities
Extracted from vas_purchase.py to avoid import errors in plan validation

This module provides reusable Monnify Bills API functions for:
- Authentication (access token generation)
- Generic API calls to Monnify Bills endpoints
"""

import os
import requests
import base64


def call_monnify_auth():
    """Get Monnify access token for Bills API"""
    try:
        # Environment variables
        MONNIFY_API_KEY = os.environ.get('MONNIFY_API_KEY', '')
        MONNIFY_SECRET_KEY = os.environ.get('MONNIFY_SECRET_KEY', '')
        MONNIFY_BASE_URL = os.environ.get('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')
        
        # Create basic auth header
        credentials = f"{MONNIFY_API_KEY}:{MONNIFY_SECRET_KEY}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            'Authorization': f'Basic {encoded_credentials}',
            'Content-Type': 'application/json'
        }
        
        url = f"{MONNIFY_BASE_URL}/api/v1/auth/login"
        
        response = requests.post(url, headers=headers, timeout=8)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('requestSuccessful'):
                access_token = data['responseBody']['accessToken']
                print(f'Monnify access token obtained: {access_token[:20]}...')
                return access_token
            else:
                raise Exception(f"Monnify auth failed: {data.get('responseMessage', 'Unknown error')}")
        else:
            raise Exception(f"Monnify auth HTTP error: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f'ERROR: Failed to get Monnify access token: {str(e)}')
        raise Exception(f'Monnify authentication failed: {str(e)}')


def call_monnify_bills_api(endpoint, method='GET', data=None, access_token=None):
    """Generic Monnify Bills API caller"""
    try:
        if not access_token:
            access_token = call_monnify_auth()
        
        # Environment variables
        MONNIFY_BASE_URL = os.environ.get('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')
        MONNIFY_BILLS_BASE_URL = f"{MONNIFY_BASE_URL}/api/v1/vas/bills-payment"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        url = f"{MONNIFY_BILLS_BASE_URL}/{endpoint}"
        
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, timeout=8)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, json=data, timeout=8)
        else:
            raise Exception(f"Unsupported HTTP method: {method}")
        
        print(f'INFO: Monnify Bills API {method} {endpoint}: {response.status_code}')
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f'ERROR: Monnify Bills API error: {response.status_code} - {response.text}')
            raise Exception(f'Monnify Bills API error: {response.status_code} - {response.text}')
            
    except Exception as e:
        print(f'ERROR: Monnify Bills API call failed: {str(e)}')
        raise Exception(f'Monnify Bills API failed: {str(e)}')