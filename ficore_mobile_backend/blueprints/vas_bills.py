"""
VAS Bills Payment Module - Production Grade
Handles bill payments for electricity, cable TV, internet, transportation, etc.

Security: API keys in environment variables, validation, error handling
Provider: Monnify Bills API (primary)
Features: Category-based billing, customer validation, receipt generation
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId
import os
import requests
import uuid
import json
from blueprints.notifications import create_user_notification

def init_vas_bills_blueprint(mongo, token_required, serialize_doc):
    vas_bills_bp = Blueprint('vas_bills', __name__, url_prefix='/api/vas/bills')
    
    # ==================== ENVIRONMENT VARIABLES ====================
    # NEVER hardcode these - use environment variables
    
    # Peyflex (PRIMARY for bills - specialized VAS provider)
    PEYFLEX_BASE_URL = os.environ.get('PEYFLEX_BASE_URL', 'https://client.peyflex.com.ng')
    PEYFLEX_API_TOKEN = os.environ.get('PEYFLEX_API_TOKEN', '')
    
    # Monnify (FALLBACK for bills - primary for wallet/banking)
    MONNIFY_API_KEY = os.environ.get('MONNIFY_API_KEY', '')
    MONNIFY_SECRET_KEY = os.environ.get('MONNIFY_SECRET_KEY', '')
    MONNIFY_CONTRACT_CODE = os.environ.get('MONNIFY_CONTRACT_CODE', '')
    MONNIFY_BASE_URL = os.environ.get('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')
    MONNIFY_BILLS_BASE_URL = f"{MONNIFY_BASE_URL}/api/v1/vas/bills-payment"
    
    # ==================== PEYFLEX HELPER FUNCTIONS (PRIMARY) ====================
    
    def call_peyflex_bills_api(endpoint, method='GET', data=None, require_auth=True):
        """Generic Peyflex Bills API caller"""
        try:
            headers = {'Content-Type': 'application/json'}
            
            if require_auth:
                headers['Authorization'] = f'Token {PEYFLEX_API_TOKEN}'
            
            url = f"{PEYFLEX_BASE_URL}/api/{endpoint}"
            
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, timeout=8)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=8)
            else:
                raise Exception(f"Unsupported HTTP method: {method}")
            
            print(f'INFO: Peyflex Bills API {method} {endpoint}: {response.status_code}')
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f'ERROR: Peyflex Bills API error: {response.status_code} - {response.text}')
                raise Exception(f'Peyflex Bills API error: {response.status_code}')
                
        except Exception as e:
            print(f'ERROR: Peyflex Bills API call failed: {str(e)}')
            raise Exception(f'Peyflex Bills API failed: {str(e)}')
    
    def get_peyflex_electricity_providers():
        """Get electricity providers from Peyflex"""
        try:
            print('INFO: Fetching electricity providers from Peyflex')
            response = call_peyflex_bills_api(
                'electricity/plans/?identifier=electricity',
                'GET',
                require_auth=True  # ✅ FIX: Auth IS required (same as data endpoint)
            )
            
            # Transform Peyflex response to our format
            providers = []
            
            # ✅ FIX: Peyflex returns dict with 'plans' key, not a list
            plans_data = response.get('plans', []) if isinstance(response, dict) else response
            
            if isinstance(plans_data, list):
                for plan in plans_data:
                    provider_code = plan.get('plan_code', '')
                    provider_name = plan.get('plan_name', '')
                    
                    if provider_code and provider_name:
                        providers.append({
                            'id': provider_code,
                            'code': provider_code,
                            'name': provider_name,
                            'category': 'electricity',
                            'source': 'peyflex',
                            'description': f"{provider_name} - Electricity provider",
                            'minAmount': plan.get('min_amount', 100),
                            'maxAmount': plan.get('max_amount', 1000000)
                        })
            
            print(f'SUCCESS: Retrieved {len(providers)} electricity providers from Peyflex')
            return providers
            
        except Exception as e:
            print(f'ERROR: Failed to get Peyflex electricity providers: {str(e)}')
            raise
    
    def get_peyflex_cable_providers():
        """Get cable TV providers from Peyflex (no auth required)"""
        try:
            print('INFO: Fetching cable TV providers from Peyflex')
            response = call_peyflex_bills_api(
                'cable/providers/',
                'GET',
                require_auth=True  # ✅ FIX: Auth IS required (same as data endpoint)
            )
            
            # Transform Peyflex response to our format
            providers = []
            if isinstance(response, list):
                for provider in response:
                    provider_code = provider.get('code', '')
                    provider_name = provider.get('name', '')
                    
                    if provider_code and provider_name:
                        providers.append({
                            'id': provider_code,
                            'code': provider_code,
                            'name': provider_name,
                            'category': 'cable_tv',
                            'source': 'peyflex',
                            'description': f"{provider_name} - Cable TV provider"
                        })
            
            print(f'SUCCESS: Retrieved {len(providers)} cable TV providers from Peyflex')
            return providers
            
        except Exception as e:
            print(f'ERROR: Failed to get Peyflex cable providers: {str(e)}')
            raise
    
    def get_peyflex_cable_plans(provider_code):
        """Get cable TV plans for a specific provider from Peyflex"""
        try:
            print(f'INFO: Fetching cable plans for {provider_code} from Peyflex')
            response = call_peyflex_bills_api(
                f'cable/plans/{provider_code}/',
                'GET',
                require_auth=True  # ✅ FIX: Auth IS required (same as data endpoint)
            )
            
            # Transform Peyflex response to our format
            plans = []
            if isinstance(response, list):
                for plan in response:
                    plan_code = plan.get('code', '')
                    plan_name = plan.get('name', '')
                    plan_price = plan.get('price', 0)
                    
                    if plan_code and plan_name:
                        plans.append({
                            'code': plan_code,
                            'name': plan_name,
                            'price': plan_price,
                            'priceType': 'FIXED',
                            'source': 'peyflex'
                        })
            
            print(f'SUCCESS: Retrieved {len(plans)} plans for {provider_code} from Peyflex')
            return plans
            
        except Exception as e:
            print(f'ERROR: Failed to get Peyflex cable plans: {str(e)}')
            raise
    
    def verify_peyflex_electricity_meter(meter, plan, meter_type):
        """Verify electricity meter with Peyflex (no auth required)"""
        try:
            print(f'INFO: Verifying meter {meter} with Peyflex')
            response = call_peyflex_bills_api(
                f'electricity/verify/?identifier=electricity&meter={meter}&plan={plan}&type={meter_type}',
                'GET',
                require_auth=True  # ✅ FIX: Auth IS required (same as data endpoint)
            )
            
            return {
                'success': True,
                'customerName': response.get('customer_name', ''),
                'meterNumber': meter,
                'address': response.get('address', ''),
                'source': 'peyflex'
            }
            
        except Exception as e:
            print(f'ERROR: Peyflex meter verification failed: {str(e)}')
            raise
    
    def verify_peyflex_cable_iuc(iuc, provider):
        """Verify cable IUC with Peyflex (auth required)"""
        try:
            print(f'INFO: Verifying IUC {iuc} with Peyflex')
            response = call_peyflex_bills_api(
                'cable/verify/',
                'POST',
                data={'iuc': iuc, 'identifier': provider},
                require_auth=True
            )
            
            return {
                'success': True,
                'customerName': response.get('customer_name', ''),
                'iuc': iuc,
                'source': 'peyflex'
            }
            
        except Exception as e:
            print(f'ERROR: Peyflex IUC verification failed: {str(e)}')
            raise
    
    def purchase_peyflex_electricity(meter, plan, amount, meter_type, phone):
        """Purchase electricity via Peyflex"""
        try:
            print(f'INFO: Purchasing electricity via Peyflex: {meter}, ₦{amount}')
            response = call_peyflex_bills_api(
                'electricity/subscribe/',
                'POST',
                data={
                    'identifier': 'electricity',
                    'meter': meter,
                    'plan': plan,
                    'amount': str(amount),
                    'type': meter_type,
                    'phone': phone
                },
                require_auth=True
            )
            
            return {
                'success': True,
                'reference': response.get('reference', ''),
                'token': response.get('token', ''),
                'units': response.get('units', ''),
                'source': 'peyflex'
            }
            
        except Exception as e:
            print(f'ERROR: Peyflex electricity purchase failed: {str(e)}')
            raise
    
    def purchase_peyflex_cable(iuc, provider, plan, amount, phone):
        """Purchase cable TV subscription via Peyflex"""
        try:
            print(f'INFO: Purchasing cable TV via Peyflex: {iuc}, ₦{amount}')
            response = call_peyflex_bills_api(
                'cable/subscribe/',
                'POST',
                data={
                    'identifier': provider,
                    'plan': plan,
                    'iuc': iuc,
                    'phone': phone,
                    'amount': str(amount)
                },
                require_auth=True
            )
            
            return {
                'success': True,
                'reference': response.get('reference', ''),
                'source': 'peyflex'
            }
            
        except Exception as e:
            print(f'ERROR: Peyflex cable purchase failed: {str(e)}')
            raise
    
    # ==================== MONNIFY HELPER FUNCTIONS (FALLBACK) ====================
    
    def call_monnify_auth():
        """Get Monnify access token for Bills API"""
        try:
            import base64
            
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
    
    def generate_retention_description(base_description, savings_message, discount_applied):
        """Generate retention-focused transaction description"""
        try:
            if discount_applied > 0:
                return f"{base_description} (Saved ₦ {discount_applied:.0f})"
            else:
                return base_description
        except Exception as e:
            print(f'WARNING: Error generating retention description: {str(e)}')
            return base_description  # Fallback to base description
    
    def get_transaction_display_info(txn):
        """Generate user-friendly description and category for VAS transactions"""
        txn_type = txn.get('type', 'UNKNOWN').upper()
        bill_category = txn.get('billCategory', '').lower()
        provider = txn.get('provider', '')
        bill_provider = txn.get('billProvider', '')
        amount = txn.get('amount', 0)
        phone_number = txn.get('phoneNumber', '')
        plan_name = txn.get('planName', '')
        account_number = txn.get('accountNumber', '')
        
        # Generate description and category based on transaction type
        if txn_type == 'AIRTIME_PURCHASE':
            description = f"Airtime purchase ₦ {amount:,.2f}"
            if phone_number:
                masked_phone = phone_number[-4:] + '****' if len(phone_number) > 4 else phone_number
                description = f"Airtime ₦ {amount:,.2f} sent to {masked_phone}"
            category = "Utilities"
            
        elif txn_type == 'DATA_PURCHASE':
            description = f"Data purchase ₦ {amount:,.2f}"
            if plan_name and phone_number:
                masked_phone = phone_number[-4:] + '****' if len(phone_number) > 4 else phone_number
                description = f"{plan_name} for {masked_phone}"
            elif phone_number:
                masked_phone = phone_number[-4:] + '****' if len(phone_number) > 4 else phone_number
                description = f"Data ₦ {amount:,.2f} for {masked_phone}"
            category = "Utilities"
            
        elif txn_type == 'WALLET_FUNDING':
            description = f"Wallet funded ₦ {amount:,.2f}"
            category = "Transfer"
            
        elif txn_type == 'BILL':
            # Handle bill payments based on category
            if bill_category == 'electricity':
                description = f"Electricity bill ₦ {amount:,.2f}"
                if bill_provider:
                    description = f"Electricity bill ₦ {amount:,.2f} - {bill_provider}"
                category = "Utilities"
                
            elif bill_category == 'cable_tv':
                description = f"Cable TV subscription ₦ {amount:,.2f}"
                if bill_provider:
                    description = f"Cable TV ₦ {amount:,.2f} - {bill_provider}"
                category = "Entertainment"
                
            elif bill_category == 'internet':
                description = f"Internet subscription ₦ {amount:,.2f}"
                if bill_provider:
                    description = f"Internet ₦ {amount:,.2f} - {bill_provider}"
                category = "Utilities"
                
            elif bill_category == 'transportation':
                description = f"Transportation payment ₦ {amount:,.2f}"
                if bill_provider:
                    description = f"Transportation ₦ {amount:,.2f} - {bill_provider}"
                category = "Transportation"
                
            else:
                description = f"Bill payment ₦ {amount:,.2f}"
                if bill_provider:
                    description = f"Bill payment ₦ {amount:,.2f} - {bill_provider}"
                category = "Utilities"
                
        elif txn_type in ['BVN_VERIFICATION', 'NIN_VERIFICATION']:
            verification_type = 'BVN' if txn_type == 'BVN_VERIFICATION' else 'NIN'
            description = f"{verification_type} verification ₦ {amount:,.2f}"
            category = "Services"
            
        else:
            # Fallback for unknown types
            clean_type = txn_type.replace('_', ' ').title()
            description = f"{clean_type} ₦ {amount:,.2f}"
            category = "Services"
            
        return description, category
    
    # ==================== BILLS PAYMENT ENDPOINTS ====================
    
    @vas_bills_bp.route('/categories', methods=['GET'])
    @token_required
    def get_bill_categories(current_user):
        """Get available bill categories from Monnify Bills API"""
        try:
            # print('VAS_DEBUG: Fetching bill categories from Monnify Bills API')
            # print(f'VAS_DEBUG: Route /api/vas/bills/categories was called by user {current_user["_id"]}')
            print('INFO: Fetching bill categories from Monnify Bills API')
            
            access_token = call_monnify_auth()
            response = call_monnify_bills_api(
                'biller-categories?size=50',
                'GET',
                access_token=access_token
            )
            
            # print(f'VAS_DEBUG: Raw Monnify categories response: {json.dumps(response, indent=2)}')
            print(f'INFO: Monnify bill categories response: {response}')
            
            categories = []
            raw_categories = response['responseBody']['content']
            # print(f'VAS_DEBUG: Processing {len(raw_categories)} Monnify categories')
            
            for category in raw_categories:
                # Filter out categories we already handle (AIRTIME, DATA_BUNDLE)
                if category['code'] not in ['AIRTIME', 'DATA_BUNDLE']:
                    category_data = {
                        'id': category['code'].lower(),
                        'name': category['name'],
                        'code': category['code'],
                        'available': True,
                        'description': f"Pay {category['name'].lower().replace('_', ' ')} bills"
                    }
                    categories.append(category_data)
                    # print(f'VAS_DEBUG: ✅ INCLUDED: {category["code"]} - {category["name"]} (available=True)')
                else:
                    pass
                    # print(f'VAS_DEBUG: ❌ EXCLUDED: {category["code"]} - {category["name"]} (already handled by VAS)')
            
            # print(f'VAS_DEBUG: FINAL RESULT: {len(categories)} bill categories from Monnify (from {len(raw_categories)} total categories)')
            print(f'SUCCESS: Successfully retrieved {len(categories)} categories from Monnify')
            
            print(f'SUCCESS: Processed {len(categories)} bill categories')
            
            return jsonify({
                'success': True,
                'data': categories,
                'message': 'Bill categories retrieved successfully',
                'source': 'monnify_bills'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting bill categories: {str(e)}')
            return jsonify({
                'success': False,
                'message': f'Failed to get bill categories: {str(e)}',
                'errors': {'general': [str(e)]}
            }), 500

    @vas_bills_bp.route('/providers/<category>', methods=['GET'])
    @token_required
    def get_bill_providers(current_user, category):
        """
        Get bill providers for a specific category
        STRATEGY: Peyflex PRIMARY, Monnify FALLBACK
        """
        try:
            print(f'INFO: Fetching bill providers for category: {category}')
            
            providers = []
            peyflex_success = False
            monnify_success = False
            
            # ==================== PEYFLEX PRIMARY ====================
            try:
                print(f'INFO: Trying Peyflex (PRIMARY) for {category}')
                
                if category.lower() == 'electricity':
                    peyflex_providers = get_peyflex_electricity_providers()
                    if peyflex_providers and len(peyflex_providers) > 0:
                        providers.extend(peyflex_providers)
                        peyflex_success = True
                        print(f'SUCCESS: Peyflex returned {len(peyflex_providers)} electricity providers')
                
                elif category.lower() in ['cable_tv', 'cable', 'tv']:
                    peyflex_providers = get_peyflex_cable_providers()
                    if peyflex_providers and len(peyflex_providers) > 0:
                        providers.extend(peyflex_providers)
                        peyflex_success = True
                        print(f'SUCCESS: Peyflex returned {len(peyflex_providers)} cable TV providers')
                
                else:
                    print(f'INFO: Peyflex does not support {category} category')
                    
            except Exception as peyflex_error:
                print(f'WARNING: Peyflex failed for {category}: {peyflex_error}')
                print(f'INFO: Will try Monnify fallback')
            
            # ==================== MONNIFY FALLBACK ====================
            # Only try Monnify if Peyflex failed OR returned no providers
            if not peyflex_success:
                try:
                    print(f'INFO: Trying Monnify (FALLBACK) for {category}')
                    
                    # Dynamic category mapping
                    category_mapping = {
                        'electricity': 'ELECTRICITY',
                        'cable_tv': 'CABLE_TV', 
                        'cable': 'CABLE_TV',
                        'tv': 'CABLE_TV',
                        'water': 'WATER',
                        'internet': 'INTERNET',
                        'transportation': 'TRANSPORTATION',
                        'transport': 'TRANSPORTATION',
                    }
                    
                    monnify_category = category_mapping.get(category.lower())
                    
                    if not monnify_category:
                        raise Exception(f'Unsupported category: {category}')
                    
                    access_token = call_monnify_auth()
                    response = call_monnify_bills_api(
                        f'billers?category_code={monnify_category}&size=100',
                        'GET',
                        access_token=access_token
                    )
                    
                    raw_providers = response['responseBody']['content']
                    
                    for biller in raw_providers:
                        provider_data = {
                            'id': biller['code'],
                            'name': biller['name'],
                            'code': biller['code'],
                            'category': category,
                            'source': 'monnify',
                            'description': f"{biller['name']} - {category.replace('_', ' ').title()} provider"
                        }
                        providers.append(provider_data)
                    
                    monnify_success = True
                    print(f'SUCCESS: Monnify returned {len(raw_providers)} providers for {category}')
                    
                except Exception as monnify_error:
                    print(f'ERROR: Monnify fallback also failed: {monnify_error}')
            
            # ==================== RESULT ====================
            if len(providers) == 0:
                return jsonify({
                    'success': False,
                    'message': f'No providers available for {category} at this time',
                    'errors': {
                        'providers': [f'Both primary and fallback providers failed for {category}']
                    },
                    'debug': {
                        'peyflex_attempted': True,
                        'peyflex_success': peyflex_success,
                        'monnify_attempted': not peyflex_success,
                        'monnify_success': monnify_success
                    }
                }), 503
            
            print(f'SUCCESS: Returning {len(providers)} total providers for {category}')
            print(f'INFO: Provider sources - Peyflex: {peyflex_success}, Monnify: {monnify_success}')
            
            return jsonify({
                'success': True,
                'data': providers,
                'message': f'Providers for {category} retrieved successfully',
                'meta': {
                    'total': len(providers),
                    'category': category,
                    'primary_source': 'peyflex' if peyflex_success else 'monnify',
                    'fallback_used': monnify_success and not peyflex_success
                }
            }), 200
            
        except Exception as e:
            print(f'ERROR: Failed to get providers for {category}: {str(e)}')
            return jsonify({
                'success': False,
                'message': f'Failed to load providers: {str(e)}',
                'errors': {'general': [str(e)]}
            }), 500
            
        except Exception as e:
            print(f'ERROR: Error getting providers for {category}: {str(e)}')
            return jsonify({
                'success': False,
                'message': f'Failed to get providers for {category}: {str(e)}',
                'errors': {'general': [str(e)]}
            }), 500

    @vas_bills_bp.route('/products/<provider>', methods=['GET'])
    @token_required
    def get_bill_products(current_user, provider):
        """
        Get products/packages for a specific provider
        STRATEGY: Route based on provider code format (Peyflex vs Monnify)
        """
        try:
            print(f'INFO: Fetching bill products for provider: {provider}')
            
            products = []
            
            # ==================== DETECT PROVIDER SOURCE ====================
            # Peyflex codes: simple lowercase (e.g., 'startimes', 'kaduna-electric')
            # Monnify codes: 'biller-' prefix (e.g., 'biller-ibedc-post')
            
            is_peyflex = not provider.startswith('biller-')
            
            if is_peyflex:
                # ==================== PEYFLEX PROVIDER ====================
                try:
                    print(f'INFO: Provider {provider} detected as Peyflex format')
                    
                    # Determine category based on provider code
                    # Cable TV providers: startimes, dstv, gotv
                    # Electricity providers: kaduna-electric, benin-electric, etc.
                    
                    cable_providers = ['startimes', 'dstv', 'gotv', 'showmax']
                    
                    if provider.lower() in cable_providers:
                        # Cable TV - fetch plans
                        peyflex_plans = get_peyflex_cable_plans(provider)
                        products = peyflex_plans
                        print(f'SUCCESS: Retrieved {len(products)} cable plans from Peyflex for {provider}')
                    else:
                        # Electricity - Peyflex doesn't have separate products endpoint
                        # The provider itself IS the product
                        products = [{
                            'code': provider,
                            'name': 'Electricity Recharge',
                            'price': None,
                            'priceType': 'OPEN',
                            'minAmount': 100,
                            'maxAmount': 100000,
                            'source': 'peyflex',
                            'description': 'Variable amount electricity recharge'
                        }]
                        print(f'SUCCESS: Electricity provider {provider} uses variable pricing')
                    
                except Exception as peyflex_error:
                    print(f'ERROR: Peyflex products fetch failed: {peyflex_error}')
                    raise
            
            else:
                # ==================== MONNIFY PROVIDER ====================
                try:
                    print(f'INFO: Provider {provider} detected as Monnify format')
                    
                    access_token = call_monnify_auth()
                    response = call_monnify_bills_api(
                        f'biller-products?biller_code={provider}&size=100',
                        'GET',
                        access_token=access_token
                    )
                    
                    print(f'INFO: Monnify products response for {provider}: {response}')
                    
                    raw_products = response['responseBody']['content']
                    
                    for product in raw_products:
                        metadata = product.get('metadata', {})
                        duration = metadata.get('duration', 1)
                        duration_unit = metadata.get('durationUnit', 'MONTHLY')
                        product_type = metadata.get('productType', {})
                        
                        duration_display = f"{duration} {duration_unit.lower()}" if duration_unit else "One-time"
                        
                        product_data = {
                            'id': product['code'],
                            'name': product['name'],
                            'code': product['code'],
                            'price': product.get('price'),
                            'priceType': product.get('priceType', 'OPEN'),
                            'minAmount': product.get('minAmount'),
                            'maxAmount': product.get('maxAmount'),
                            'duration': duration_display,
                            'productType': product_type.get('name', 'Service'),
                            'description': f"{product['name']} - {duration_display}",
                            'source': 'monnify',
                            'metadata': metadata
                        }
                        products.append(product_data)
                    
                    print(f'SUCCESS: Retrieved {len(products)} products from Monnify for {provider}')
                    
                except Exception as monnify_error:
                    print(f'ERROR: Monnify products fetch failed: {monnify_error}')
                    raise
            
            # ==================== RESULT ====================
            if len(products) == 0:
                return jsonify({
                    'success': False,
                    'message': f'No products available for {provider}',
                    'errors': {'products': ['This provider has no products available']},
                    'data': []
                }), 200  # Return 200 with empty array, not 500
            
            return jsonify({
                'success': True,
                'data': products,
                'message': f'Products for {provider} retrieved successfully',
                'meta': {
                    'total': len(products),
                    'provider': provider,
                    'source': 'peyflex' if is_peyflex else 'monnify'
                }
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting products for {provider}: {str(e)}')
            return jsonify({
                'success': False,
                'message': f'Failed to get products: {str(e)}',
                'errors': {'general': [str(e)]},
                'data': []
            }), 500

    @vas_bills_bp.route('/validate', methods=['POST'])
    @token_required
    def validate_bill_account(current_user):
        """
        Validate customer account for bill payment
        STRATEGY: Route based on product code format (Peyflex vs Monnify)
        """
        try:
            data = request.get_json()
            
            product_code = data.get('productCode')
            customer_id = data.get('customerId')
            
            print(f'INFO: Validating bill account - Product: {product_code}, Customer: {customer_id}')
            
            if not product_code or not customer_id:
                return jsonify({
                    'success': False,
                    'message': 'Product code and customer ID are required',
                    'errors': {
                        'productCode': ['Product code is required'] if not product_code else [],
                        'customerId': ['Customer ID is required'] if not customer_id else []
                    }
                }), 400
            
            # Detect provider from product code
            is_peyflex = not product_code.startswith('biller-')
            
            if is_peyflex:
                # PEYFLEX VALIDATION
                try:
                    print(f'INFO: Using Peyflex validation for {product_code}')
                    
                    # Determine category
                    cable_providers = ['startimes', 'dstv', 'gotv', 'showmax']
                    
                    if product_code.lower() in cable_providers:
                        # Cable TV - verify IUC
                        response = verify_peyflex_cable_iuc(customer_id, product_code)
                    else:
                        # Electricity - verify meter
                        # Need meter type - default to prepaid
                        meter_type = data.get('meterType', 'prepaid')
                        response = verify_peyflex_electricity_meter(customer_id, product_code, meter_type)
                    
                    result = {
                        'customerName': response.get('customerName', ''),
                        'priceType': 'OPEN',
                        'requireValidationRef': False,
                        'validationReference': None,
                        'productCode': product_code,
                        'customerId': customer_id,
                        'source': 'peyflex'
                    }
                    
                    print(f'SUCCESS: Peyflex validation successful for {customer_id}')
                    
                    return jsonify({
                        'success': True,
                        'data': result,
                        'message': 'Account validated successfully'
                    }), 200
                    
                except Exception as peyflex_error:
                    print(f'ERROR: Peyflex validation failed: {peyflex_error}')
                    raise
            
            else:
                # MONNIFY VALIDATION
                try:
                    print(f'INFO: Using Monnify validation for {product_code}')
                    
                    access_token = call_monnify_auth()
                    response = call_monnify_bills_api(
                        'validate-customer',
                        'POST',
                        {
                            'productCode': product_code,
                            'customerId': customer_id
                        },
                        access_token=access_token
                    )
                    
                    validation_data = response['responseBody']
                    vend_instruction = validation_data.get('vendInstruction', {})
                    
                    result = {
                        'customerName': validation_data.get('customerName', ''),
                        'priceType': validation_data.get('priceType', 'OPEN'),
                        'requireValidationRef': vend_instruction.get('requireValidationRef', False),
                        'validationReference': validation_data.get('validationReference'),
                        'productCode': product_code,
                        'customerId': customer_id,
                        'source': 'monnify'
                    }
                    
                    print(f'SUCCESS: Monnify validation successful for {customer_id}')
                    
                    return jsonify({
                        'success': True,
                        'data': result,
                        'message': 'Account validated successfully'
                    }), 200
                    
                except Exception as monnify_error:
                    print(f'ERROR: Monnify validation failed: {monnify_error}')
                    raise
            
        except Exception as e:
            print(f'ERROR: Account validation failed: {str(e)}')
            
            error_message = str(e)
            if 'invalid customer' in error_message.lower():
                return jsonify({
                    'success': False,
                    'message': 'Invalid customer ID. Please check the account number and try again.',
                    'errors': {'customerId': ['Invalid customer ID']},
                    'user_message': {
                        'title': 'Invalid Account',
                        'message': 'The account number you entered is not valid. Please check and try again.',
                        'type': 'validation_error'
                    }
                }), 400
            else:
                return jsonify({
                    'success': False,
                    'message': f'Validation failed: {error_message}',
                    'errors': {'general': [error_message]},
                    'user_message': {
                        'title': 'Validation Failed',
                        'message': 'Unable to validate the account. Please try again later.',
                        'type': 'service_error'
                    }
                }), 400
    @vas_bills_bp.route('/buy', methods=['POST'])
    @token_required
    def buy_bill(current_user):
        """
        Purchase bill payment
        STRATEGY: Route based on product code format (Peyflex vs Monnify)
        """
        # 🔒 DEFENSIVE CODING: Pre-define all variables
        wallet_update_result = None
        transaction_update_result = None
        api_response = None
        success = False
        error_message = ''
        final_status = 'FAILED'
        provider_source = 'unknown'
        
        try:
            data = request.get_json()
            
            category = data.get('category')
            provider = data.get('provider')
            account_number = data.get('accountNumber')
            customer_name = data.get('customerName', '')
            amount = float(data.get('amount', 0))
            product_code = data.get('productCode')
            product_name = data.get('productName', '')
            validation_reference = data.get('validationReference')
            phone_number = current_user.get('phoneNumber', '')
            
            print(f'INFO: Processing bill purchase:')
            print(f'   Category: {category}')
            print(f'   Provider: {provider}')
            print(f'   Account: {account_number}')
            print(f'   Amount: ₦{amount:,.2f}')
            print(f'   Product: {product_code}')
            
            # Validate required fields
            required_fields = ['category', 'provider', 'accountNumber', 'amount', 'productCode']
            missing_fields = [field for field in required_fields if not data.get(field)]
            
            if missing_fields:
                return jsonify({
                    'success': False,
                    'message': 'Missing required fields',
                    'errors': {field: [f'{field} is required'] for field in missing_fields}
                }), 400
            
            if amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Amount must be greater than zero',
                    'errors': {'amount': ['Amount must be greater than zero']}
                }), 400
            
            # Check wallet balance
            wallet = mongo.db.vas_wallets.find_one({'userId': current_user['_id']})
            if not wallet:
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found. Please create a wallet first.',
                    'errors': {'wallet': ['Wallet not found']}
                }), 404
            
            if wallet['balance'] < amount:
                return jsonify({
                    'success': False,
                    'message': 'Insufficient wallet balance',
                    'errors': {'balance': ['Insufficient wallet balance']},
                    'user_message': {
                        'title': 'Insufficient Balance',
                        'message': f'You need ₦{amount:,.2f} but only have ₦{wallet["balance"]:,.2f} in your wallet.',
                        'type': 'insufficient_balance'
                    }
                }), 402
            
            # Generate unique transaction reference
            transaction_ref = f"BILL_{uuid.uuid4().hex[:12].upper()}"
            
            # Detect provider source
            is_peyflex = not product_code.startswith('biller-')
            provider_source = 'peyflex' if is_peyflex else 'monnify'
            
            print(f'INFO: Provider source detected: {provider_source}')
            
            # 🔒 ATOMIC: Create FAILED transaction first
            transaction = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'type': 'BILL',
                'subtype': category.upper(),
                'billCategory': category,
                'billProvider': provider,
                'accountNumber': account_number,
                'customerName': customer_name,
                'amount': amount,
                'status': 'FAILED',
                'failureReason': 'Transaction in progress',
                'transactionReference': transaction_ref,
                'description': f"Bill payment: {provider} - {account_number}",
                'provider': provider_source,
                'createdAt': datetime.utcnow(),
                'productCode': product_code,
                'productName': product_name,
                'vendReference': None,
                'billerCode': None,
                'billerName': None,
                'commission': 0,
                'payableAmount': amount,
                'vendAmount': amount
            }
            
            result = mongo.db.vas_transactions.insert_one(transaction)
            transaction_id = result.inserted_id
            print(f'INFO: Created atomic transaction with ID: {transaction_id}')
            
            # ==================== CALL PROVIDER API ====================
            if is_peyflex:
                # PEYFLEX PURCHASE
                try:
                    print(f'INFO: Using Peyflex for bill purchase')
                    
                    cable_providers = ['startimes', 'dstv', 'gotv', 'showmax']
                    
                    if product_code.lower() in cable_providers:
                        # Cable TV purchase
                        response = purchase_peyflex_cable(
                            iuc=account_number,
                            provider=product_code,
                            plan=product_name,
                            amount=amount,
                            phone=phone_number
                        )
                    else:
                        # Electricity purchase
                        meter_type = data.get('meterType', 'prepaid')
                        response = purchase_peyflex_electricity(
                            meter=account_number,
                            plan=product_code,
                            amount=amount,
                            meter_type=meter_type,
                            phone=phone_number
                        )
                    
                    # Peyflex returns success immediately
                    final_status = 'SUCCESS' if response.get('success') else 'FAILED'
                    vend_reference = response.get('reference', transaction_ref)
                    
                    print(f'INFO: Peyflex purchase status: {final_status}')
                    
                except Exception as peyflex_error:
                    print(f'ERROR: Peyflex purchase failed: {peyflex_error}')
                    final_status = 'FAILED'
                    error_message = str(peyflex_error)
                    vend_reference = None
            
            else:
                # MONNIFY PURCHASE
                try:
                    print(f'INFO: Using Monnify for bill purchase')
                    
                    access_token = call_monnify_auth()
                    
                    vend_data = {
                        'productCode': product_code,
                        'customerId': account_number,
                        'amount': amount,
                        'emailAddress': current_user.get('email', 'customer@ficoreafrica.com')
                    }
                    
                    if validation_reference:
                        vend_data['validationReference'] = validation_reference
                    
                    response = call_monnify_bills_api(
                        'vend',
                        'POST',
                        vend_data,
                        access_token=access_token
                    )
                    
                    vend_result = response['responseBody']
                    
                    # Handle IN_PROGRESS with requery
                    if vend_result.get('vendStatus') == 'IN_PROGRESS':
                        import time
                        time.sleep(3)
                        
                        requery_response = call_monnify_bills_api(
                            f'requery?reference={transaction_ref}',
                            'GET',
                            access_token=access_token
                        )
                        vend_result = requery_response['responseBody']
                    
                    final_status = vend_result.get('vendStatus', 'FAILED')
                    vend_reference = vend_result.get('vendReference')
                    
                    print(f'INFO: Monnify purchase status: {final_status}')
                    
                except Exception as monnify_error:
                    print(f'ERROR: Monnify purchase failed: {monnify_error}')
                    final_status = 'FAILED'
                    error_message = str(monnify_error)
                    vend_reference = None
            
            # ==================== UPDATE TRANSACTION ====================
            update_operation = {
                '$set': {
                    'status': final_status,
                    'vendReference': vend_reference,
                    'updatedAt': datetime.utcnow()
                }
            }
            
            if final_status == 'SUCCESS':
                update_operation['$unset'] = {'failureReason': ""}
            else:
                update_operation['$set']['failureReason'] = error_message or 'Bill payment failed'
            
            mongo.db.vas_transactions.update_one(
                {'_id': transaction_id},
                update_operation
            )
            
            updated_transaction = mongo.db.vas_wallets.find_one({'_id': transaction_id})
            
            # Update wallet balance if successful
            if final_status == 'SUCCESS':
                print(f'SUCCESS: Transaction successful, deducting ₦ {amount:,.2f} from wallet')
                
                # CRITICAL FIX: Update BOTH balances using centralized utility
                current_wallet = mongo.db.vas_wallets.find_one({'userId': current_user['_id']})
                new_balance = current_wallet.get('balance', 0.0) - amount
                
                from utils.balance_sync import update_liquid_wallet_balance
                
                # Use centralized balance update utility
                success = update_liquid_wallet_balance(
                    mongo=mongo,
                    user_id=str(current_user['_id']),
                    new_balance=new_balance,
                    transaction_reference=transaction_ref,
                    transaction_type='BILL_PAYMENT',
                    push_sse_update=True,
                    sse_data={
                        'amount_debited': amount,
                        'bill_category': category,
                        'provider': provider
                    }
                )
                
                if not success:
                    print(f'WARNING: Balance update may have failed for user {current_user["_id"]}')
                else:
                    print(f'SUCCESS: Updated BOTH balances using utility after bill payment - New balance: ₦{new_balance:,.2f}')
                
                # Auto-create expense entry (auto-bookkeeping) for bill payments
                try:
                    # Generate category-specific description
                    category_display = {
                        'electricity': 'Electricity Bill',
                        'cable_tv': 'Cable TV Subscription', 
                        'internet': 'Internet Subscription',
                        'transportation': 'Transportation Payment'
                    }.get(category.lower(), 'Bill Payment')
                    
                    base_description = f'{category_display} - {provider} ₦ {amount:,.2f}'
                    
                    # Generate retention-focused description
                    retention_description = generate_retention_description(
                        base_description,
                        '',  # No savings message for bills yet
                        0    # No discount applied for bills yet
                    )
                    
                    expense_entry = {
                        '_id': ObjectId(),
                        'userId': ObjectId(current_user['_id']),
                        'title': category_display,
                        'amount': amount,
                        'category': 'Utilities',  # All bill payments go under Utilities
                        'date': datetime.utcnow(),
                        'description': retention_description,
                        'isPending': False,
                        'isRecurring': False,
                        'sourceType': f'vas_{category}',  # Granular source type for VAS bill payments (e.g., 'vas_electricity', 'vas_cable_tv')
                        'status': 'active',  # CRITICAL: Required for immutability system (Jan 14, 2026)
                        'isDeleted': False,  # CRITICAL: Required for immutability system (Jan 14, 2026)
                        'metadata': {
                            'source': 'vas_bill_payment',
                            'billCategory': category,
                            'provider': provider,
                            'accountNumber': account_number,
                            'transactionId': str(transaction_id),
                            'automated': True,
                            'retentionData': {
                                'originalPrice': amount,
                                'finalPrice': amount,
                                'totalSaved': 0,
                                'userTier': 'basic'
                            }
                        },
                        'createdAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }
                    
                    # Import and apply auto-population for proper title/description
                    from utils.expense_utils import auto_populate_expense_fields
                    expense_entry = auto_populate_expense_fields(expense_entry)
                    
                    mongo.db.expenses.insert_one(expense_entry)
                    print(f'SUCCESS: Auto-created expense entry for {category_display}: ₦ {amount:,.2f}')
                    
                except Exception as e:
                    print(f'WARNING: Failed to create automated expense entry: {str(e)}')
                    # Don't fail the transaction if expense entry creation fails
                
                # Create success notification
                try:
                    create_user_notification(
                        mongo,
                        current_user['_id'],
                        'Bill Payment Successful',
                        f'Your {provider} bill payment of ₦ {amount:,.2f} was successful.',
                        'success',
                        {
                            'type': 'bill_payment',
                            'category': category,
                            'provider': provider,
                            'amount': amount,
                            'transactionId': str(transaction_id)
                        }
                    )
                except Exception as e:
                    print(f'WARNING: Failed to create notification: {str(e)}')
                
                print(f'SUCCESS: Bill payment completed successfully!')
                
                return jsonify({
                    'success': True,
                    'data': serialize_doc(updated_transaction),
                    'message': 'Bill payment processed successfully',
                    'user_message': {
                        'title': 'Payment Successful',
                        'message': f'Your {provider} bill payment of ₦ {amount:,.2f} was successful.',
                        'type': 'success'
                    }
                }), 200
                
            elif final_status == 'FAILED':
                print(f'ERROR: Transaction failed')
                return jsonify({
                    'success': False,
                    'data': serialize_doc(updated_transaction),
                    'message': 'Bill payment failed',
                    'user_message': {
                        'title': 'Payment Failed',
                        'message': f'Your {provider} bill payment could not be completed. Your wallet was not charged.',
                        'type': 'transaction_failed'
                    }
                }), 400
                
            else:  # PENDING or other status
                print(f'INFO: Transaction pending with status: {final_status}')
                return jsonify({
                    'success': True,
                    'data': serialize_doc(updated_transaction),
                    'message': 'Bill payment is being processed',
                    'user_message': {
                        'title': 'Payment Processing',
                        'message': f'Your {provider} bill payment is being processed. You will be notified once completed.',
                        'type': 'pending'
                    }
                }), 200
            
        except Exception as e:
            print(f'ERROR: Bill payment failed with error: {str(e)}')
            
            # 🔒 ATOMIC PATTERN: Ensure transaction is marked as FAILED on exception
            try:
                # Check if transaction_id exists (transaction was created)
                if 'transaction_id' in locals():
                    mongo.db.vas_transactions.update_one(
                        {'_id': transaction_id},
                        {
                            '$set': {
                                'status': 'FAILED',
                                'failureReason': f'Exception during processing: {str(e)}',
                                'updatedAt': datetime.utcnow()
                            }
                        }
                    )
                    print(f'INFO: Marked transaction {transaction_id} as FAILED due to exception')
            except Exception as update_error:
                print(f'WARNING: Failed to update transaction status: {str(update_error)}')
            
            # Handle specific errors
            error_message = str(e)
            if 'insufficient balance' in error_message.lower():
                return jsonify({
                    'success': False,
                    'message': 'Insufficient wallet balance',
                    'errors': {'balance': ['Insufficient wallet balance']},
                    'user_message': {
                        'title': 'Insufficient Balance',
                        'message': 'You don\'t have enough funds in your wallet to complete this transaction.',
                        'type': 'insufficient_balance'
                    }
                }), 402
            elif 'timeout' in error_message.lower():
                return jsonify({
                    'success': False,
                    'message': 'Transaction timeout',
                    'errors': {'timeout': ['Transaction timed out']},
                    'user_message': {
                        'title': 'Transaction Timeout',
                        'message': 'The transaction is taking longer than expected. Please try again.',
                        'type': 'timeout'
                    }
                }), 408
            else:
                return jsonify({
                    'success': False,
                    'message': f'Bill payment failed: {error_message}',
                    'errors': {'general': [error_message]},
                    'user_message': {
                        'title': 'Payment Failed',
                        'message': 'Unable to process your bill payment. Please try again later.',
                        'type': 'service_error'
                    }
                }), 500
    
    # ==================== TRANSACTION ENDPOINTS ====================
    
    # Cache for transaction queries (5 minute TTL)
    _transaction_cache = {}
    _cache_ttl = 300  # 5 minutes
    
    def _get_cache_key(user_id, limit, skip):
        """Generate cache key for transaction queries"""
        return f"transactions_{user_id}_{limit}_{skip}"
    
    def _is_cache_valid(cache_entry):
        """Check if cache entry is still valid"""
        return (datetime.utcnow() - cache_entry['timestamp']).total_seconds() < _cache_ttl
    
    @vas_bills_bp.route('/transactions/all', methods=['GET'])
    @token_required
    def get_all_user_transactions(current_user):
        """Get all user transactions (VAS + Income + Expenses) in unified chronological order - OPTIMIZED"""
        try:
            user_id = str(current_user['_id'])
            limit = int(request.args.get('limit', 50))
            skip = int(request.args.get('skip', 0))
            
            # OPTIMIZATION 0: Check cache first (5-minute TTL)
            cache_key = _get_cache_key(user_id, limit, skip)
            if cache_key in _transaction_cache:
                cache_entry = _transaction_cache[cache_key]
                if _is_cache_valid(cache_entry):
                    print(f"[CACHE HIT] Returning cached transactions for user {user_id}")
                    return jsonify(cache_entry['data']), 200
                else:
                    # Remove expired cache entry
                    del _transaction_cache[cache_key]
            
            print(f"[CACHE MISS] Loading transactions for user {user_id} (limit={limit}, skip={skip})")
            start_time = time.time()
            
            all_transactions = []
            
            # OPTIMIZATION 1: Use aggregation pipeline with $unionWith for better performance
            # CRITICAL FIX (Feb 8, 2026): Use get_active_transactions_query for income/expense filtering
            from utils.immutable_ledger_helper import get_active_transactions_query
            
            # Get active transactions query (returns dict with userId, status, isDeleted filters)
            active_query = get_active_transactions_query(ObjectId(user_id))
            
            # Build aggregation pipeline to combine all collections efficiently
            pipeline = [
                # Start with VAS transactions
                {
                    '$match': {
                        'userId': ObjectId(user_id),
                        'type': {
                            '$in': [
                                'AIRTIME', 'DATA', 'BILL', 'WALLET_FUNDING',
                                'REFUND_CORRECTION', 'FEE_REFUND', 'KYC_VERIFICATION',
                                'ACTIVATION_FEE', 'SUBSCRIPTION_FEE'
                            ]
                        }
                    }
                },
                {
                    '$addFields': {
                        'transactionType': 'VAS',
                        'subtype': '$type'
                    }
                },
                # Union with income transactions (with active filter)
                {
                    '$unionWith': {
                        'coll': 'incomes',
                        'pipeline': [
                            {'$match': active_query},  # Use active transactions filter
                            {
                                '$addFields': {
                                    'transactionType': 'INCOME',
                                    'subtype': 'INCOME',
                                    'status': 'SUCCESS'
                                }
                            }
                        ]
                    }
                },
                # Union with expense transactions (with active filter)
                {
                    '$unionWith': {
                        'coll': 'expenses',
                        'pipeline': [
                            {'$match': active_query},  # Use active transactions filter
                            {
                                '$addFields': {
                                    'transactionType': 'EXPENSE',
                                    'subtype': 'EXPENSE',
                                    'status': 'SUCCESS'
                                }
                            }
                        ]
                    }
                },
                # Sort by creation date (newest first)
                {'$sort': {'createdAt': -1}},
                # Apply pagination
                {'$skip': skip},
                {'$limit': limit}
            ]
            
            # Execute optimized aggregation
            print(f"[OPTIMIZED] Executing aggregation pipeline...")
            aggregation_start = time.time()
            
            cursor = mongo.db.vas_transactions.aggregate(pipeline)
            raw_transactions = list(cursor)
            
            aggregation_time = time.time() - aggregation_start
            print(f"[OPTIMIZED] Aggregation completed in {aggregation_time:.2f}s - found {len(raw_transactions)} transactions")
            
            # OPTIMIZATION 2: Streamlined data transformation
            
            transform_start = time.time()
            
            for txn in raw_transactions:
                txn_type = txn.get('transactionType', 'UNKNOWN')
                created_at = txn.get('createdAt')
                
                # Ensure valid datetime
                if not isinstance(created_at, datetime):
                    created_at = datetime.utcnow()
                    print(f"[WARN] Invalid createdAt for txn {txn['_id']} - using now")
                
                if txn_type == 'VAS':
                    description, category = get_transaction_display_info(txn)
                    all_transactions.append({
                        '_id': str(txn['_id']),
                        'type': 'VAS',
                        'subtype': txn.get('type', 'UNKNOWN'),
                        'amount': txn.get('amount', 0),
                        'amountPaid': txn.get('amountPaid', 0),
                        'fee': txn.get('depositFee', 0),
                        'description': description,
                        'reference': txn.get('reference', ''),
                        'status': txn.get('status', 'UNKNOWN'),
                        'provider': txn.get('provider', ''),
                        'createdAt': created_at.isoformat() + 'Z',
                        'date': created_at.isoformat() + 'Z',
                        'category': category,
                        'metadata': {
                            'phoneNumber': txn.get('phoneNumber', ''),
                            'planName': txn.get('planName', ''),
                        }
                    })
                elif txn_type == 'INCOME':
                    all_transactions.append({
                        '_id': str(txn['_id']),
                        'type': 'INCOME',
                        'subtype': 'INCOME',
                        'amount': txn.get('amount', 0),
                        'description': txn.get('description', 'Income received'),
                        'title': txn.get('source', 'Income'),
                        'source': txn.get('source', 'Unknown'),
                        'reference': '',
                        'status': 'SUCCESS',
                        'createdAt': created_at.isoformat() + 'Z',
                        'date': created_at.isoformat() + 'Z',
                        'category': txn.get('category', 'Income')
                    })
                elif txn_type == 'EXPENSE':
                    all_transactions.append({
                        '_id': str(txn['_id']),
                        'type': 'EXPENSE',
                        'subtype': 'EXPENSE',
                        'amount': -txn.get('amount', 0),
                        'description': txn.get('description', 'Expense recorded'),
                        'title': txn.get('title', 'Expense'),
                        'reference': '',
                        'status': 'SUCCESS',
                        'createdAt': created_at.isoformat() + 'Z',
                        'date': created_at.isoformat() + 'Z',
                        'category': txn.get('category', 'Expense')
                    })
            
            transform_time = time.time() - transform_start
            total_time = time.time() - start_time
            
            print(f"[OPTIMIZED] Transform completed in {transform_time:.2f}s")
            print(f"[OPTIMIZED] Total request time: {total_time:.2f}s (was ~6 minutes)")
            print(f"[OPTIMIZED] Performance improvement: {(360/total_time):.1f}x faster")
            
            # OPTIMIZATION 3: Cache the result for 5 minutes
            response_data = {
                'success': True,
                'data': all_transactions,
                'total': len(all_transactions),
                'limit': limit,
                'skip': skip,
                'message': 'All transactions loaded successfully',
                'performance': {
                    'total_time_seconds': round(total_time, 2),
                    'aggregation_time_seconds': round(aggregation_time, 2),
                    'transform_time_seconds': round(transform_time, 2),
                    'cached': False
                }
            }
            
            # Store in cache
            _transaction_cache[cache_key] = {
                'data': response_data,
                'timestamp': datetime.utcnow()
            }
            
            # Clean up old cache entries (keep cache size manageable)
            if len(_transaction_cache) > 100:
                oldest_key = min(_transaction_cache.keys(), 
                               key=lambda k: _transaction_cache[k]['timestamp'])
                del _transaction_cache[oldest_key]
                print(f"[CACHE] Cleaned up old entry: {oldest_key}")
            
            return jsonify(response_data), 200
            
        except Exception as e:
            print(f"[ERROR] /vas/bills/transactions/all failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to load transactions',
                'error': str(e)
            }), 500

    @vas_bills_bp.route('/transactions', methods=['GET'])
    @token_required
    def get_vas_transactions(current_user):
        """Get user's VAS transaction history"""
        try:
            user_id = str(current_user['_id'])
            
            limit = int(request.args.get('limit', 50))
            skip = int(request.args.get('skip', 0))
            transaction_type = request.args.get('type', None)
            
            query = {'userId': ObjectId(user_id)}
            if transaction_type:
                query['type'] = transaction_type.upper()
            
            transactions = list(
                mongo.db.vas_transactions.find(query)
                .sort('createdAt', -1)
                .skip(skip)
                .limit(limit)
            )
            
            serialized_transactions = []
            for txn in transactions:
                txn_data = serialize_doc(txn)
                txn_data['createdAt'] = txn.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                serialized_transactions.append(txn_data)
            
            return jsonify({
                'success': True,
                'data': serialized_transactions,
                'message': 'Transactions retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting transactions: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve transactions',
                'errors': {'general': [str(e)]}
            }), 500
    
    @vas_bills_bp.route('/transactions/<transaction_id>/receipt', methods=['GET'])
    @token_required
    def get_vas_transaction_receipt(current_user, transaction_id):
        """Get VAS transaction receipt for display"""
        try:
            user_id = str(current_user['_id'])
            
            # Find the transaction
            transaction = mongo.db.vas_transactions.find_one({
                '_id': ObjectId(transaction_id),
                'userId': ObjectId(user_id)
            })
            
            if not transaction:
                return jsonify({
                    'success': False,
                    'message': 'Transaction not found'
                }), 404
            
            # Build receipt data based on transaction type
            txn_type = transaction.get('type', 'UNKNOWN')
            amount = transaction.get('amount', 0)
            status = transaction.get('status', 'UNKNOWN')
            reference = transaction.get('reference', 'N/A')
            created_at = transaction.get('createdAt', datetime.utcnow())
            provider = transaction.get('provider', 'N/A')
            metadata = transaction.get('metadata', {})
            
            receipt_data = {
                'transactionId': str(transaction_id),
                'type': txn_type,
                'amount': amount,
                'status': status,
                'reference': reference,
                'provider': provider,
                'date': created_at.isoformat() + 'Z',
                'metadata': metadata
            }
            
            # Add type-specific details
            if txn_type == 'WALLET_FUNDING':
                receipt_data.update({
                    'title': 'Wallet Funding Receipt',
                    'description': f'₦ {amount:,.2f} added to your Liquid Wallet',
                    'details': {
                        'Amount Paid': f"₦ {transaction.get('amountPaid', amount):,.2f}",
                        'Deposit Fee': f"₦ {transaction.get('depositFee', 0):,.2f}",
                        'Amount Credited': f"₦ {amount:,.2f}",
                        'Payment Method': 'Bank Transfer',
                        'Provider': provider.title()
                    }
                })
            elif txn_type == 'AIRTIME_PURCHASE':
                phone = metadata.get('phoneNumber', 'Unknown')
                network = metadata.get('network', 'Unknown')
                receipt_data.update({
                    'title': 'Airtime Purchase Receipt',
                    'description': f'₦ {amount:,.2f} airtime sent successfully',
                    'details': {
                        'Phone Number': phone,
                        'Network': network,
                        'Amount': f"₦ {amount:,.2f}",
                        'Face Value': f"₦ {metadata.get('faceValue', amount):,.2f}",
                        'Provider': provider.title()
                    }
                })
            elif txn_type == 'DATA_PURCHASE':
                phone = metadata.get('phoneNumber', 'Unknown')
                network = metadata.get('network', 'Unknown')
                plan_name = metadata.get('planName', 'Data Plan')
                receipt_data.update({
                    'title': 'Data Purchase Receipt',
                    'description': f'{plan_name} purchased successfully',
                    'details': {
                        'Phone Number': phone,
                        'Network': network,
                        'Data Plan': plan_name,
                        'Amount': f"₦ {amount:,.2f}",
                        'Provider': provider.title()
                    }
                })
            elif txn_type == 'KYC_VERIFICATION':
                receipt_data.update({
                    'title': 'KYC Verification Receipt',
                    'description': 'Account verification completed',
                    'details': {
                        'Verification Fee': f"₦ {amount:,.2f}",
                        'Status': 'Verified',
                        'Provider': provider.title()
                    }
                })
            else:
                # Use the same helper function for receipt descriptions
                description, _ = get_transaction_display_info(transaction)
                
                receipt_data.update({
                    'title': f'{txn_type.replace("_", " ").title()} Receipt',
                    'description': description,
                    'details': {
                        'Amount': f"₦ {amount:,.2f}",
                        'Type': txn_type.replace("_", " ").title(),
                        'Provider': provider.title()
                    }
                })
            
            return jsonify({
                'success': True,
                'data': receipt_data,
                'message': 'Transaction receipt retrieved successfully'
            })
            
        except Exception as e:
            print(f'ERROR: Error getting VAS receipt: {str(e)}')
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve transaction receipt',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== BILL PAYMENT HISTORY & BENEFICIARIES ====================
    
    @vas_bills_bp.route('/recent', methods=['GET'])
    @token_required
    def get_recent_bill_transactions(current_user):
        """
        Get user's recent bill payment transactions
        Query params: billType (electricity, cable_tv, internet, transportation), limit (default 5)
        """
        try:
            user_id = current_user['_id']
            bill_type = request.args.get('billType')
            limit = int(request.args.get('limit', 5))
            
            # Query vas_transactions collection
            query = {
                'userId': ObjectId(user_id),
                'type': 'BILL',
                'status': {'$in': ['SUCCESS', 'PENDING']},
            }
            
            # Add bill type filter if provided
            if bill_type:
                query['billCategory'] = bill_type
            
            transactions = mongo.db.vas_transactions.find(query).sort('createdAt', -1).limit(limit)
            
            result = []
            for txn in transactions:
                result.append({
                    'providerId': txn.get('billProvider'),
                    'providerName': txn.get('billProvider', 'Unknown Provider'),
                    'accountNumber': txn.get('accountNumber'),
                    'customerName': txn.get('customerName'),
                    'amount': txn.get('amount'),
                    'productCode': txn.get('productCode'),
                    'status': txn.get('status'),
                    'createdAt': txn.get('createdAt').isoformat() if txn.get('createdAt') else None,
                })
            
            return jsonify({
                'success': True,
                'data': result
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting recent bill transactions: {str(e)}')
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500
    
    @vas_bills_bp.route('/beneficiaries', methods=['GET'])
    @token_required
    def get_saved_beneficiaries(current_user):
        """
        Get user's saved bill payment beneficiaries
        Query params: billType (electricity, cable_tv, internet, transportation)
        """
        try:
            user_id = current_user['_id']
            bill_type = request.args.get('billType')
            
            # Query bill_beneficiaries collection
            query = {
                'userId': ObjectId(user_id),
                'isDeleted': False,
            }
            
            # Add bill type filter if provided
            if bill_type:
                query['billType'] = bill_type
            
            beneficiaries = mongo.db.bill_beneficiaries.find(query).sort('lastUsed', -1)
            
            result = []
            for ben in beneficiaries:
                result.append({
                    '_id': str(ben['_id']),
                    'name': ben.get('name'),
                    'providerId': ben.get('providerId'),
                    'providerName': ben.get('providerName'),
                    'accountNumber': ben.get('accountNumber'),
                    'customerName': ben.get('customerName'),
                    'billType': ben.get('billType'),
                    'lastUsed': ben.get('lastUsed').isoformat() if ben.get('lastUsed') else None,
                })
            
            return jsonify({
                'success': True,
                'data': result
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting saved beneficiaries: {str(e)}')
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500
    
    @vas_bills_bp.route('/beneficiaries', methods=['POST'])
    @token_required
    def save_beneficiary(current_user):
        """
        Save a bill payment beneficiary for quick access
        Body: billType, providerId, accountNumber, customerName, name
        """
        try:
            user_id = current_user['_id']
            data = request.get_json()
            
            bill_type = data.get('billType')
            provider_id = data.get('providerId')
            account_number = data.get('accountNumber')
            customer_name = data.get('customerName')
            name = data.get('name')
            
            # Check if beneficiary already exists
            existing = mongo.db.bill_beneficiaries.find_one({
                'userId': ObjectId(user_id),
                'billType': bill_type,
                'providerId': provider_id,
                'accountNumber': account_number,
            })
            
            if existing:
                # Update last used timestamp
                mongo.db.bill_beneficiaries.update_one(
                    {'_id': existing['_id']},
                    {
                        '$set': {
                            'lastUsed': datetime.utcnow(),
                            'customerName': customer_name,
                            'name': name,
                        }
                    }
                )
                return jsonify({
                    'success': True,
                    'message': 'Beneficiary updated',
                    'data': {'_id': str(existing['_id'])}
                }), 200
            
            # Create new beneficiary
            beneficiary = {
                '_id': ObjectId(),
                'userId': ObjectId(user_id),
                'billType': bill_type,
                'providerId': provider_id,
                'providerName': data.get('providerName', 'Unknown Provider'),
                'accountNumber': account_number,
                'customerName': customer_name,
                'name': name,
                'isDeleted': False,
                'createdAt': datetime.utcnow(),
                'lastUsed': datetime.utcnow(),
            }
            
            mongo.db.bill_beneficiaries.insert_one(beneficiary)
            
            return jsonify({
                'success': True,
                'message': 'Beneficiary saved',
                'data': {'_id': str(beneficiary['_id'])}
            }), 201
            
        except Exception as e:
            print(f'ERROR: Error saving beneficiary: {str(e)}')
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500
    
    @vas_bills_bp.route('/beneficiaries/<beneficiary_id>', methods=['DELETE'])
    @token_required
    def delete_beneficiary(current_user, beneficiary_id):
        """
        Delete a saved beneficiary (soft delete)
        """
        try:
            user_id = current_user['_id']
            
            result = mongo.db.bill_beneficiaries.update_one(
                {
                    '_id': ObjectId(beneficiary_id),
                    'userId': ObjectId(user_id),
                },
                {
                    '$set': {
                        'isDeleted': True,
                        'deletedAt': datetime.utcnow(),
                    }
                }
            )
            
            if result.modified_count == 0:
                return jsonify({
                    'success': False,
                    'message': 'Beneficiary not found'
                }), 404
            
            return jsonify({
                'success': True,
                'message': 'Beneficiary deleted'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error deleting beneficiary: {str(e)}')
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500

    return vas_bills_bp