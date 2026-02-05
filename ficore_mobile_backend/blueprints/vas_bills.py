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
    
    # Environment variables (NEVER hardcode these)
    MONNIFY_API_KEY = os.environ.get('MONNIFY_API_KEY', '')
    MONNIFY_SECRET_KEY = os.environ.get('MONNIFY_SECRET_KEY', '')
    MONNIFY_CONTRACT_CODE = os.environ.get('MONNIFY_CONTRACT_CODE', '')
    MONNIFY_BASE_URL = os.environ.get('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')
    
    # Monnify Bills API specific
    MONNIFY_BILLS_BASE_URL = f"{MONNIFY_BASE_URL}/api/v1/vas/bills-payment"
    
    # ==================== HELPER FUNCTIONS ====================
    
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
        """Get bill providers for a specific category"""
        try:
            print(f'INFO: Fetching bill providers for category: {category}')
            
            # Dynamic category mapping - handle both frontend names and Monnify codes
            # First, try direct mapping for common frontend categories
            category_mapping = {
                'electricity': 'ELECTRICITY',
                'cable_tv': 'CABLE_TV', 
                'cable': 'CABLE_TV',
                'tv': 'CABLE_TV',
                'water': 'WATER',
                'internet': 'INTERNET',
                'transportation': 'TRANSPORTATION',
                'transport': 'TRANSPORTATION',
                'betting': 'BETTING',
                'gaming': 'BETTING',
                'insurance': 'INSURANCE',
                'education': 'EDUCATION',
                'government': 'GOVERNMENT',
                'tax': 'TAX',
                'religious': 'RELIGIOUS',
                'donation': 'DONATION',
                'charity': 'DONATION'
            }
            
            # Try direct mapping first
            monnify_category = category_mapping.get(category.lower())
            
            # If no direct mapping, try to match with actual Monnify categories
            if not monnify_category:
                # Get available categories from Monnify to find the best match
                try:
                    access_token_temp = call_monnify_auth()
                    categories_response = call_monnify_bills_api(
                        'biller-categories?size=50',
                        'GET',
                        access_token=access_token_temp
                    )
                    
                    available_categories = [cat['code'] for cat in categories_response['responseBody']['content']]
                    
                    # Try case-insensitive exact match
                    for available_cat in available_categories:
                        if available_cat.lower() == category.lower():
                            monnify_category = available_cat
                            break
                    
                    # Try partial match
                    if not monnify_category:
                        for available_cat in available_categories:
                            if category.lower() in available_cat.lower() or available_cat.lower() in category.lower():
                                monnify_category = available_cat
                                print(f'INFO: Using partial match: {category} -> {available_cat}')
                                break
                                
                except Exception as mapping_error:
                    print(f'WARNING: Could not fetch categories for dynamic mapping: {mapping_error}')
            
            if not monnify_category:
                print(f'ERROR: Unsupported category: {category}')
                return jsonify({
                    'success': False,
                    'message': f'Unsupported category: {category}',
                    'errors': {'category': [f'Category {category} is not supported']},
                    'available_categories': list(category_mapping.keys())
                }), 400
            
            print(f'INFO: Calling Monnify API for category: {monnify_category}')
            # print(f'VAS_DEBUG: Fetching bill providers for category: {category}')
            # print(f'VAS_DEBUG: Route /api/vas/bills/providers/{category} was called by user {current_user["_id"]}')
            # print(f'VAS_DEBUG: Mapped {category} → {monnify_category} for Monnify')
            
            access_token = call_monnify_auth()
            response = call_monnify_bills_api(
                f'billers?category_code={monnify_category}&size=100',
                'GET',
                access_token=access_token
            )
            
            # print(f'VAS_DEBUG: Raw Monnify response for {monnify_category}: {json.dumps(response, indent=2)}')
            print(f'INFO: Monnify providers response for {monnify_category}: {response}')
            
            # DEBUGGING: Check if we're getting wrong providers for transportation
            if category.lower() == 'transportation':
                print(f'WARNING: TRANSPORTATION DEBUG: Raw Monnify response: {json.dumps(response, indent=2)}')
                
                # Check if any providers contain electricity-related terms
                electricity_keywords = ['electricity', 'electric', 'distribution', 'disco', 'power', 'energy']
                raw_providers = response.get('responseBody', {}).get('content', [])
                
                electricity_providers = []
                for provider in raw_providers:
                    provider_name = provider.get('name', '').lower()
                    if any(keyword in provider_name for keyword in electricity_keywords):
                        electricity_providers.append(provider)
                
                if electricity_providers:
                    print(f'WARNING: TRANSPORTATION ISSUE: Found {len(electricity_providers)} electricity providers in transportation category!')
                    print(f'WARNING: Electricity providers: {[p.get("name") for p in electricity_providers]}')
                    print(f'WARNING: This indicates Monnify API configuration issue - transportation category returning electricity providers')
                    
                    # Return error with detailed explanation
                    return jsonify({
                        'success': False,
                        'message': 'Transportation providers are misconfigured on the payment gateway',
                        'errors': {
                            'backend_issue': [
                                'Monnify API is returning electricity providers for transportation category',
                                'This is a payment gateway configuration issue, not an app issue',
                                f'Found {len(electricity_providers)} electricity providers in transportation response'
                            ]
                        },
                        'debug_info': {
                            'requested_category': category,
                            'monnify_category': monnify_category,
                            'total_providers': len(raw_providers),
                            'electricity_providers_found': len(electricity_providers),
                            'electricity_provider_names': [p.get('name') for p in electricity_providers]
                        }
                    }), 503  # Service Unavailable
            
            providers = []
            raw_providers = response['responseBody']['content']
            # print(f'VAS_DEBUG: Processing {len(raw_providers)} Monnify providers for {category}')
            
            for biller in raw_providers:
                provider_data = {
                    'id': biller['code'],
                    'name': biller['name'],
                    'code': biller['code'],
                    'category': category,
                    'description': f"{biller['name']} - {category.replace('_', ' ').title()} provider"
                }
                providers.append(provider_data)
                # print(f'VAS_DEBUG: ✅ INCLUDED: {biller["code"]} - {biller["name"]} (category={category})')
            
            # print(f'VAS_DEBUG: FINAL RESULT: {len(providers)} {category} providers from Monnify (from {len(raw_providers)} total providers)')
            print(f'SUCCESS: Successfully retrieved {len(providers)} providers from Monnify for {category}')
            
            print(f'SUCCESS: Processed {len(providers)} providers for {category}')
            
            return jsonify({
                'success': True,
                'data': providers,
                'message': f'Providers for {category} retrieved successfully',
                'source': 'monnify_bills',
                'category': category,
                'monnify_category': monnify_category
            }), 200
            
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
        """Get products/packages for a specific provider"""
        try:
            # print(f'VAS_DEBUG: Fetching bill products for provider: {provider}')
            # print(f'VAS_DEBUG: Route /api/vas/bills/products/{provider} was called by user {current_user["_id"]}')
            print(f'INFO: Fetching bill products for provider: {provider}')
            
            access_token = call_monnify_auth()
            response = call_monnify_bills_api(
                f'biller-products?biller_code={provider}&size=100',
                'GET',
                access_token=access_token
            )
            
            # print(f'VAS_DEBUG: Raw Monnify products response for {provider}: {json.dumps(response, indent=2)}')
            print(f'INFO: Monnify products response for {provider}: {response}')
            
            products = []
            raw_products = response['responseBody']['content']
            # print(f'VAS_DEBUG: Processing {len(raw_products)} Monnify products for {provider}')
            
            for product in raw_products:
                # Extract metadata for better product information
                metadata = product.get('metadata', {})
                duration = metadata.get('duration', 1)
                duration_unit = metadata.get('durationUnit', 'MONTHLY')
                product_type = metadata.get('productType', {})
                
                # Format duration display
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
                    'metadata': metadata
                }
                products.append(product_data)
                
                price_info = f"₦{product.get('price', 'Variable')}" if product.get('price') else f"₦{product.get('minAmount', 0)}-{product.get('maxAmount', 'Open')}"
                # print(f'VAS_DEBUG: ✅ INCLUDED: {product["code"]} - {product["name"]} - {price_info} (duration={duration_display})')
            
            # print(f'VAS_DEBUG: FINAL RESULT: {len(products)} products for {provider} from Monnify (from {len(raw_products)} total products)')
            print(f'SUCCESS: Successfully retrieved {len(products)} products from Monnify for {provider}')
            
            print(f'SUCCESS: Processed {len(products)} products for {provider}')
            
            return jsonify({
                'success': True,
                'data': products,
                'message': f'Products for {provider} retrieved successfully',
                'source': 'monnify_bills',
                'provider': provider
            }), 200
            
        except Exception as e:
            print(f'ERROR: Error getting products for {provider}: {str(e)}')
            return jsonify({
                'success': False,
                'message': f'Failed to get products for {provider}: {str(e)}',
                'errors': {'general': [str(e)]}
            }), 500

    @vas_bills_bp.route('/validate', methods=['POST'])
    @token_required
    def validate_bill_account(current_user):
        """Validate customer account for bill payment"""
        try:
            data = request.get_json()
            
            # Extract required fields
            product_code = data.get('productCode')
            customer_id = data.get('customerId')
            
            print(f'INFO: Validating bill account - Product: {product_code}, Customer: {customer_id}')
            
            # Validate required fields
            if not product_code or not customer_id:
                print('ERROR: Missing required fields for validation')
                return jsonify({
                    'success': False,
                    'message': 'Product code and customer ID are required',
                    'errors': {
                        'productCode': ['Product code is required'] if not product_code else [],
                        'customerId': ['Customer ID is required'] if not customer_id else []
                    }
                }), 400
            
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
            
            print(f'INFO: Monnify validation response: {response}')
            
            validation_data = response['responseBody']
            vend_instruction = validation_data.get('vendInstruction', {})
            
            result = {
                'customerName': validation_data.get('customerName', ''),
                'priceType': validation_data.get('priceType', 'OPEN'),
                'requireValidationRef': vend_instruction.get('requireValidationRef', False),
                'validationReference': validation_data.get('validationReference'),
                'productCode': product_code,
                'customerId': customer_id
            }
            
            print(f'SUCCESS: Account validation successful for {customer_id}')
            
            return jsonify({
                'success': True,
                'data': result,
                'message': 'Account validated successfully',
                'source': 'monnify_bills'
            }), 200
            
        except Exception as e:
            print(f'ERROR: Account validation failed: {str(e)}')
            
            # Handle specific validation errors
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
            elif 'product not found' in error_message.lower():
                return jsonify({
                    'success': False,
                    'message': 'Product not found. Please select a valid product.',
                    'errors': {'productCode': ['Product not found']},
                    'user_message': {
                        'title': 'Product Not Found',
                        'message': 'The selected product is not available. Please choose another option.',
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
        """Purchase bill payment using Monnify Bills API"""
        # 🔒 DEFENSIVE CODING: Pre-define all variables to prevent NameError crashes
        wallet_update_result = None
        transaction_update_result = None
        api_response = None
        success = False
        error_message = ''
        final_status = 'FAILED'
        
        try:
            data = request.get_json()
            
            # Extract required fields
            category = data.get('category')
            provider = data.get('provider')
            account_number = data.get('accountNumber')
            customer_name = data.get('customerName', '')
            amount = float(data.get('amount', 0))
            product_code = data.get('productCode')
            product_name = data.get('productName', '')
            validation_reference = data.get('validationReference')
            
            print(f'INFO: Processing bill purchase:')
            print(f'   Category: {category}')
            print(f'   Provider: {provider}')
            print(f'   Account: {account_number}')
            print(f'   Amount: ₦ {amount:,.2f}')
            print(f'   Product: {product_code}')
            
            # Validate required fields
            required_fields = ['category', 'provider', 'accountNumber', 'amount', 'productCode']
            missing_fields = []
            for field in required_fields:
                if not data.get(field):
                    missing_fields.append(field)
            
            if missing_fields:
                print(f'ERROR: Missing required fields: {missing_fields}')
                return jsonify({
                    'success': False,
                    'message': 'Missing required fields',
                    'errors': {field: [f'{field} is required'] for field in missing_fields}
                }), 400
            
            # Validate amount
            if amount <= 0:
                print(f'ERROR: Invalid amount: {amount}')
                return jsonify({
                    'success': False,
                    'message': 'Amount must be greater than zero',
                    'errors': {'amount': ['Amount must be greater than zero']}
                }), 400
            
            # Check wallet balance
            wallet = mongo.db.vas_wallets.find_one({'userId': current_user['_id']})
            if not wallet:
                print('ERROR: Wallet not found')
                return jsonify({
                    'success': False,
                    'message': 'Wallet not found. Please create a wallet first.',
                    'errors': {'wallet': ['Wallet not found']}
                }), 404
            
            if wallet['balance'] < amount:
                print(f'ERROR: Insufficient balance: ₦ {wallet["balance"]:,.2f} < ₦ {amount:,.2f}')
                return jsonify({
                    'success': False,
                    'message': 'Insufficient wallet balance',
                    'errors': {'balance': ['Insufficient wallet balance']},
                    'user_message': {
                        'title': 'Insufficient Balance',
                        'message': f'You need ₦ {amount:,.2f} but only have ₦ {wallet["balance"]:,.2f} in your wallet.',
                        'type': 'insufficient_balance'
                    }
                }), 402
            
            # Generate unique transaction reference
            transaction_ref = f"BILL_{uuid.uuid4().hex[:12].upper()}"
            print(f'INFO: Generated transaction reference: {transaction_ref}')
            
            # 🔒 ATOMIC TRANSACTION PATTERN: Create FAILED transaction first
            # This prevents stuck PENDING states if backend crashes during processing
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
                'status': 'FAILED',  # 🔒 Start as FAILED, update to SUCCESS only when complete
                'failureReason': 'Transaction in progress',  # Will be updated if it actually fails
                'transactionReference': transaction_ref,
                'description': f"Bill payment: {provider} - {account_number}",
                'provider': 'monnify',
                'createdAt': datetime.utcnow(),
                'productCode': product_code,
                'productName': product_name,
                # These will be updated after successful processing:
                'vendReference': None,
                'billerCode': None,
                'billerName': None,
                'commission': 0,
                'payableAmount': amount,
                'vendAmount': amount
            }
            
            # Insert FAILED transaction first
            result = mongo.db.vas_transactions.insert_one(transaction)
            transaction_id = result.inserted_id
            print(f'INFO: Created atomic transaction with ID: {transaction_id}')
            
            # Call Monnify Bills API
            access_token = call_monnify_auth()
            
            vend_data = {
                'productCode': product_code,
                'customerId': account_number,
                'amount': amount,
                'emailAddress': current_user.get('email', 'customer@ficoreafrica.com')
            }
            
            # Add validation reference if required
            if validation_reference:
                vend_data['validationReference'] = validation_reference
                print(f'INFO: Using validation reference: {validation_reference}')
            
            print(f'INFO: Calling Monnify vend API with data: {vend_data}')
            
            response = call_monnify_bills_api(
                'vend',
                'POST',
                vend_data,
                access_token=access_token
            )
            
            print(f'INFO: Monnify vend response: {response}')
            
            vend_result = response['responseBody']
            
            # Handle IN_PROGRESS status with requery
            if vend_result.get('vendStatus') == 'IN_PROGRESS':
                print('INFO: Transaction in progress, waiting 3 seconds before requery...')
                import time
                time.sleep(3)
                
                requery_response = call_monnify_bills_api(
                    f'requery?reference={transaction_ref}',
                    'GET',
                    access_token=access_token
                )
                
                print(f'INFO: Monnify requery response: {requery_response}')
                vend_result = requery_response['responseBody']
            
            # Determine final status
            final_status = vend_result.get('vendStatus', 'FAILED')
            print(f'INFO: Final transaction status: {final_status}')
            
            # 🔒 ATOMIC PATTERN: Update transaction with final status and details
            update_operation = {
                '$set': {
                    'status': final_status,
                    'vendReference': vend_result.get('vendReference'),
                    'productName': vend_result.get('productName', product_name),
                    'billerCode': vend_result.get('billerCode'),
                    'billerName': vend_result.get('billerName'),
                    'commission': vend_result.get('commission', 0),
                    'payableAmount': vend_result.get('payableAmount', amount),
                    'vendAmount': vend_result.get('vendAmount', amount),
                    'updatedAt': datetime.utcnow()
                }
            }
            
            # 🔒 Clear failureReason on success, update it on failure
            if final_status == 'SUCCESS':
                update_operation['$unset'] = {'failureReason': ""}
            else:
                failure_reason = vend_result.get('message', 'Bill payment failed')
                update_operation['$set']['failureReason'] = failure_reason
            
            # Update the transaction record
            transaction_update_result = mongo.db.vas_transactions.update_one(
                {'_id': transaction_id},
                update_operation
            )
            
            # CRITICAL: Verify transaction was actually updated
            if transaction_update_result.modified_count == 0:
                print(f'ERROR: Failed to update bills transaction {transaction_id} to {final_status}')
                print(f'       Transaction ID type: {type(transaction_id)}')
                print(f'       Transaction ID value: {transaction_id}')
                
                # Try to find the transaction to debug
                debug_txn = mongo.db.vas_transactions.find_one({'_id': transaction_id})
                if debug_txn:
                    print(f'       Found transaction with status: {debug_txn.get("status")}')
                else:
                    print(f'       Transaction not found in database!')
            else:
                print(f'SUCCESS: Bills transaction {transaction_id} updated to {final_status} status')
                
                # Double-check the update worked for SUCCESS transactions
                if final_status == 'SUCCESS':
                    verify_txn = mongo.db.vas_transactions.find_one({'_id': transaction_id})
                    if verify_txn and verify_txn.get('status') == 'SUCCESS':
                        print(f'VERIFIED: Bills transaction {transaction_id} status is SUCCESS')
                    else:
                        print(f'WARNING: Bills transaction {transaction_id} status verification failed')
                        print(f'         Current status: {verify_txn.get("status") if verify_txn else "NOT_FOUND"}')
            
            print(f'INFO: Updated transaction {transaction_id} to {final_status}')
            
            # Get updated transaction for response
            updated_transaction = mongo.db.vas_transactions.find_one({'_id': transaction_id})
            
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
                # Union with income transactions
                {
                    '$unionWith': {
                        'coll': 'incomes',
                        'pipeline': [
                            {'$match': {'userId': ObjectId(user_id)}},
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
                # Union with expense transactions
                {
                    '$unionWith': {
                        'coll': 'expenses',
                        'pipeline': [
                            {'$match': {'userId': ObjectId(user_id)}},
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

    return vas_bills_bp