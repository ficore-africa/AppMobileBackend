"""
Dynamic Pricing Engine for FiCore VAS Services
Implements intelligent pricing strategies based on Peyflex rates, user tiers, and market psychology

Key Features:
- Real-time Peyflex rate integration with 5% API discount
- Subscription-based pricing tiers (Basic, Premium, Gold)
- Psychological pricing ceiling rules (₦500 barrier)
- Competitive margin optimization
- Auto-fallback to cached rates if API fails
"""

import os
import requests
import json
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DynamicPricingEngine:
    def __init__(self, mongo_db):
        self.mongo = mongo_db
        self.peyflex_base_url = os.environ.get('PEYFLEX_BASE_URL', 'https://client.peyflex.com.ng')
        self.peyflex_token = os.environ.get('PEYFLEX_API_TOKEN', '')
        
        # Pricing Strategy Constants
        self.PSYCHOLOGICAL_CEILING = 500.0  # ₦500 barrier
        # REMOVED: self.API_DISCOUNT_RATE - Peyflex API already returns discounted prices
        self.CACHE_DURATION_HOURS = 6  # Cache rates for 6 hours
        self.EMERGENCY_FALLBACK_MULTIPLIER = 2.0  # 2x markup when no cache available (prevents losses)
        
        # POLICY COMPLIANCE: No markup on VAS purchases
        self.NETWORK_MARGINS = {
            'MTN': {
                'airtime': 0.0,   # NO MARGIN (policy compliance)
                'data': 0.0,      # NO MARGIN (policy compliance)
                'min_margin': 0   # NO MINIMUM PROFIT (policy compliance)
            },
            'GLO': {
                'airtime': 0.0,   # NO MARGIN (policy compliance)
                'data': 0.0,      # NO MARGIN (policy compliance)
                'min_margin': 0   # NO MINIMUM PROFIT (policy compliance)
            },
            'AIRTEL': {
                'airtime': 0.0,   # NO MARGIN (policy compliance)
                'data': 0.0,      # NO MARGIN (policy compliance)
                'min_margin': 0   # NO MINIMUM PROFIT (policy compliance)
            },
            '9MOBILE': {
                'airtime': 0.0,   # NO MARGIN (policy compliance)
                'data': 0.0,      # NO MARGIN (policy compliance)
                'min_margin': 0   # NO MINIMUM PROFIT (policy compliance)
            }
        }
        
        # Subscription Discount Strategy
        self.SUBSCRIPTION_DISCOUNTS = {
            'basic': 0.0,      # No discount
            'premium': 0.03,   # 3% discount
            'gold': 0.05       # 5% discount (Cost + ₦5 strategy)
        }

    def get_peyflex_rates(self, service_type: str, network: str = None) -> Dict:
        """
        Fetch real-time rates from Peyflex API
        Returns cached rates if API fails
        """
        try:
            cache_key = f"peyflex_rates_{service_type}_{network or 'all'}"
            
            # Check cache first (only for non-expired cache)
            # FIXED: self.mongo is already the database, no need for .db
            cached_rates = self.mongo.pricing_cache.find_one({
                'cache_key': cache_key,
                'expires_at': {'$gt': datetime.utcnow()}
            })
            
            if cached_rates:
                logger.info(f"Using cached rates for {service_type} {network}")
                return cached_rates['data']
            
            # Fetch fresh rates from Peyflex
            if service_type == 'airtime':
                rates = self._fetch_airtime_rates(network)
            elif service_type == 'data':
                rates = self._fetch_data_rates(network)
            else:
                raise ValueError(f"Unsupported service type: {service_type}")
            
            # Cache the rates
            # FIXED: self.mongo is already the database, no need for .db
            self.mongo.pricing_cache.replace_one(
                {'cache_key': cache_key},
                {
                    'cache_key': cache_key,
                    'data': rates,
                    'created_at': datetime.utcnow(),
                    'expires_at': datetime.utcnow() + timedelta(hours=self.CACHE_DURATION_HOURS)
                },
                upsert=True
            )
            
            logger.info(f"Fetched and cached fresh rates for {service_type} {network}")
            return rates
            
        except Exception as e:
            logger.error(f"Error fetching Peyflex rates: {str(e)}")
            
            # Return fallback rates if API fails
            return self._get_fallback_rates(service_type, network)

    def _fetch_airtime_rates(self, network: str = None) -> Dict:
        """
        Fetch airtime rates from Peyflex
        CRITICAL: Peyflex API already returns discounted prices (5% off face value)
        Do NOT apply additional discounts in code
        """
        # These rates represent what Peyflex charges us (already discounted)
        base_rates = {
            'MTN': {'rate': 0.99, 'min_amount': 100, 'max_amount': 5000},      # Already discounted
            'AIRTEL': {'rate': 0.986, 'min_amount': 100, 'max_amount': 5000},  # Already discounted  
            'GLO': {'rate': 0.98, 'min_amount': 100, 'max_amount': 5000},      # Already discounted
            '9MOBILE': {'rate': 0.98, 'min_amount': 100, 'max_amount': 5000}   # Already discounted
        }
        
        if network:
            return {network.upper(): base_rates.get(network.upper(), base_rates['MTN'])}
        
        return base_rates

    def _fetch_data_rates(self, network: str = None) -> Dict:
        """
        Fetch data plan rates from Peyflex with connection retry strategies
        """
        try:
            if network:
                url = f'{self.peyflex_base_url}/api/data/plans/?network={network.lower()}'
            else:
                url = f'{self.peyflex_base_url}/api/data/networks/'
            
            logger.info(f"🔍 Attempting to fetch data rates from: {url}")
            
            # Use the most reliable strategy first (Simple Request)
            strategies = [
                {
                    'name': 'Simple Request (Most Reliable)',
                    'headers': {
                        'Authorization': f'Token {self.peyflex_token}',
                        'User-Agent': 'FiCore-Backend/1.0',
                        'Accept': 'application/json',
                        'Connection': 'close'
                    },
                    'timeout': 30,
                    'retry_count': 2,
                    'session_config': {'pool_connections': 1, 'pool_maxsize': 1}
                },
                {
                    'name': 'Standard Request',
                    'headers': {
                        'Authorization': f'Token {self.peyflex_token}',
                        'User-Agent': 'FiCore-Backend/1.0 (Nigeria; Python-Requests)',
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    },
                    'timeout': 25,
                    'session_config': {'pool_connections': 1, 'pool_maxsize': 1}
                },
                {
                    'name': 'Fallback Request',
                    'headers': {
                        'Authorization': f'Token {self.peyflex_token}',
                        'User-Agent': 'FiCore-Fallback/1.0',
                        'Accept': 'application/json'
                    },
                    'timeout': 20,
                    'retry_count': 1,
                    'session_config': {'pool_connections': 1, 'pool_maxsize': 1}
                }
            ]
            
            last_error = None
            
            for strategy in strategies:
                try:
                    logger.info(f"Trying {strategy['name']} for Peyflex API")
                    
                    # Create a fresh session for each strategy
                    session = requests.Session()
                    if 'session_config' in strategy:
                        adapter = requests.adapters.HTTPAdapter(**strategy['session_config'])
                        session.mount('https://', adapter)
                        session.mount('http://', adapter)
                    
                    retry_count = strategy.get('retry_count', 1)
                    
                    for attempt in range(retry_count):
                        try:
                            if attempt > 0:
                                import time
                                time.sleep(2 ** attempt)  # Exponential backoff
                                logger.info(f"Retry attempt {attempt + 1}/{retry_count}")
                            
                            response = session.get(
                                url,
                                headers=strategy['headers'],
                                timeout=strategy['timeout'],
                                verify=True,
                                allow_redirects=True
                            )
                            
                            logger.info(f"📡 Peyflex API response: {response.status_code}")
                            
                            if response.status_code == 200:
                                data = response.json()
                                logger.info(f"✅ Successfully fetched data from Peyflex: {len(str(data))} chars")
                                
                                # Transform Peyflex response to our format
                                if isinstance(data, list):
                                    rates = {}
                                    for plan in data:
                                        plan_id = plan.get('plan_code', plan.get('id', ''))
                                        rates[plan_id] = {
                                            'name': plan.get('name', plan.get('plan_name', '')),
                                            'price': float(plan.get('price', plan.get('amount', 0))),
                                            'validity': plan.get('validity', 30),
                                            'network': network.upper() if network else 'UNKNOWN'
                                        }
                                    logger.info(f"✅ {strategy['name']} succeeded - got {len(rates)} plans")
                                    session.close()
                                    return rates
                                elif isinstance(data, dict) and 'plans' in data:
                                    rates = {}
                                    for plan in data['plans']:
                                        plan_id = plan.get('plan_code', plan.get('id', ''))
                                        rates[plan_id] = {
                                            'name': plan.get('name', plan.get('plan_name', '')),
                                            'price': float(plan.get('price', plan.get('amount', 0))),
                                            'validity': plan.get('validity', 30),
                                            'network': network.upper() if network else 'UNKNOWN'
                                        }
                                    logger.info(f"✅ {strategy['name']} succeeded - got {len(rates)} plans")
                                    session.close()
                                    return rates
                                else:
                                    logger.warning(f"❌ {strategy['name']} unexpected response format: {type(data)}")
                                    last_error = f"Unexpected response format: {type(data)}"
                            else:
                                logger.warning(f"❌ {strategy['name']} failed: HTTP {response.status_code}")
                                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                                
                        except requests.exceptions.ConnectionError as e:
                            logger.warning(f"❌ {strategy['name']} connection error (attempt {attempt + 1}): {str(e)}")
                            last_error = f"Connection error: {str(e)}"
                            if attempt == retry_count - 1:  # Last attempt
                                break
                            continue
                        except requests.exceptions.Timeout as e:
                            logger.warning(f"❌ {strategy['name']} timeout (attempt {attempt + 1}): {str(e)}")
                            last_error = f"Timeout error: {str(e)}"
                            if attempt == retry_count - 1:  # Last attempt
                                break
                            continue
                        except Exception as e:
                            logger.warning(f"❌ {strategy['name']} error (attempt {attempt + 1}): {str(e)}")
                            last_error = str(e)
                            if attempt == retry_count - 1:  # Last attempt
                                break
                            continue
                    
                    session.close()
                        
                except requests.exceptions.ConnectionError as e:
                    logger.warning(f"❌ {strategy['name']} connection error: {str(e)}")
                    last_error = f"Connection error: {str(e)}"
                    continue
                except requests.exceptions.SSLError as e:
                    logger.warning(f"❌ {strategy['name']} SSL error: {str(e)}")
                    last_error = f"SSL error: {str(e)}"
                    continue
                except Exception as e:
                    logger.warning(f"❌ {strategy['name']} failed: {str(e)}")
                    last_error = str(e)
                    continue
            
            # All strategies failed
            logger.error(f"All connection strategies failed. Last error: {last_error}")
            raise Exception(f"All Peyflex connection strategies failed: {last_error}")
            
        except Exception as e:
            logger.error(f"Error fetching data rates: {str(e)}")
            return self._get_emergency_data_rates(network)

    def _get_fallback_rates(self, service_type: str, network: str = None) -> Dict:
        """
        Return fallback rates when API fails
        CRITICAL: Use last known good prices from cache, not hardcoded 2024 prices
        """
        try:
            # Try to get last known good price from cache (even if expired)
            cache_key = f"peyflex_rates_{service_type}_{network or 'all'}"
            # FIXED: self.mongo is already the database, no need for .db
            last_known_rates = self.mongo.pricing_cache.find_one(
                {'cache_key': cache_key},
                sort=[('created_at', -1)]  # Get most recent
            )
            
            if last_known_rates and last_known_rates.get('data'):
                logger.warning(f"Using last known good rates for {service_type} {network}")
                return last_known_rates['data']
            
            # If no cache exists, use emergency high pricing to prevent losses
            logger.error(f"NO CACHE AVAILABLE - Using emergency high pricing for {service_type} {network}")
            return self._get_emergency_fallback_rates(service_type, network)
            
        except Exception as e:
            logger.error(f"Error getting fallback rates: {str(e)}")
            return self._get_emergency_fallback_rates(service_type, network)

    def _get_emergency_fallback_rates(self, service_type: str, network: str = None) -> Dict:
        """
        Emergency fallback with intentionally HIGH prices to prevent losses
        Better to lose customers temporarily than lose money on every transaction
        """
        if service_type == 'airtime':
            # Set airtime rates high enough to ensure profit
            emergency_rates = {
                'MTN': {'rate': 1.1, 'min_amount': 100, 'max_amount': 5000},      # 10% markup
                'AIRTEL': {'rate': 1.1, 'min_amount': 100, 'max_amount': 5000},   # 10% markup
                'GLO': {'rate': 1.1, 'min_amount': 100, 'max_amount': 5000},      # 10% markup
                '9MOBILE': {'rate': 1.1, 'min_amount': 100, 'max_amount': 5000}   # 10% markup
            }
            
            if network:
                return {network.upper(): emergency_rates.get(network.upper(), emergency_rates['MTN'])}
            return emergency_rates
            
        elif service_type == 'data':
            return self._get_emergency_data_rates(network)
        
        return {}

    def _get_emergency_data_rates(self, network: str = None) -> Dict:
        """
        Emergency data rates - intentionally high to prevent losses during API outages
        """
        # Use 2x current market rates to ensure we don't lose money
        emergency_rates = {
            'MTN': {
                'M500MBS': {'name': '500MB - 30 Days', 'price': 600, 'validity': 30},  # 2x normal
                'M1GB': {'name': '1GB - 30 Days', 'price': 800, 'validity': 30},       # 2x normal
                'M2GB': {'name': '2GB - 30 Days', 'price': 1200, 'validity': 30},     # 2x normal
                'M5GB': {'name': '5GB - 30 Days', 'price': 2700, 'validity': 30},     # 2x normal
            },
            'GLO': {
                'GLO_1GB': {'name': '1GB - 30 Days', 'price': 800, 'validity': 30},   # 2x normal
                'GLO_2GB': {'name': '2GB - 30 Days', 'price': 1200, 'validity': 30},  # 2x normal
            },
            'AIRTEL': {
                'AIRTEL_1GB': {'name': '1GB - 30 Days', 'price': 1500, 'validity': 30},  # 2x normal
                'AIRTEL_2GB': {'name': '2GB - 30 Days', 'price': 3000, 'validity': 30},  # 2x normal
            },
            '9MOBILE': {
                '9MOB_1GB': {'name': '1GB - 30 Days', 'price': 800, 'validity': 30},   # 2x normal
                '9MOB_2GB': {'name': '2GB - 30 Days', 'price': 1200, 'validity': 30},  # 2x normal
            }
        }
        
        if network:
            return emergency_rates.get(network.upper(), {})
        
        return emergency_rates



    def calculate_selling_price(
        self, 
        service_type: str, 
        network: str, 
        base_amount: float, 
        user_tier: str = 'basic',
        plan_id: str = None,
        user_id: str = None
    ) -> Dict:
        """
        Calculate optimal selling price using dynamic pricing strategy
        
        Returns:
        {
            'selling_price': float,
            'cost_price': float,
            'margin': float,
            'margin_percentage': float,
            'discount_applied': float,
            'strategy_used': str,
            'savings_message': str
        }
        """
        try:
            network = network.upper()
            
            # Get base cost from Peyflex (already includes 5% API discount)
            if service_type == 'airtime':
                rates = self.get_peyflex_rates('airtime', network)
                network_rate = rates.get(network, {})
                # CRITICAL FIX: Do NOT apply additional discount - Peyflex API already returns discounted price
                cost_price = base_amount * network_rate.get('rate', 1.0)
            
            elif service_type == 'data':
                if not plan_id:
                    raise ValueError("Plan ID required for data pricing")
                
                rates = self.get_peyflex_rates('data', network)
                plan_data = rates.get(plan_id, {})
                # CRITICAL FIX: Do NOT apply additional discount - Peyflex API already returns discounted price
                cost_price = plan_data.get('price', base_amount)
            
            else:
                raise ValueError(f"Unsupported service type: {service_type}")
            
            # REMOVED: cost_price = cost_price * (1 - self.API_DISCOUNT_RATE)
            # Peyflex API already returns the discounted price we pay
            
            # Get margin strategy for this network
            margin_config = self.NETWORK_MARGINS.get(network, self.NETWORK_MARGINS['MTN'])
            margin_percentage = margin_config[service_type]
            min_margin = margin_config['min_margin']
            
            # 🚨 POLICY COMPLIANCE: NO MARKUP ON VAS PURCHASES
            # Selling price = Cost price (no fees, no margins, no markups)
            margin_amount = 0.0  # NO MARGIN (policy compliance)
            base_selling_price = cost_price  # NO MARKUP (policy compliance)
            
            # Apply psychological pricing rules (but maintain no-markup policy)
            selling_price = cost_price  # NO MARKUP - ignore psychological pricing for policy compliance
            
            # Apply subscription discounts
            discount_applied = 0.0
            voucher_discount = 0.0
            
            # 🚨 CHECK FOR FREE FEE VOUCHERS (Emergency Recovery)
            # CRITICAL: Wrapped in try-except to prevent transaction crashes
            if user_id:
                try:
                    active_voucher = self._check_free_fee_voucher(user_id, service_type)
                    if active_voucher:
                        # Apply free fee (reduce to cost price only)
                        voucher_discount = selling_price - cost_price
                        selling_price = cost_price
                        discount_applied = voucher_discount
                        
                        # Mark voucher as used (with atomic protection)
                        voucher_used = self._use_voucher(active_voucher['_id'])
                        
                        if voucher_used:
                            logger.info(f"Free fee voucher applied: ₦{voucher_discount} discount for user {user_id}")
                        else:
                            # Voucher couldn't be used (expired/exhausted), revert to normal pricing
                            logger.warning(f"Voucher application failed for user {user_id}, reverting to normal pricing")
                            voucher_discount = 0.0
                            selling_price = base_selling_price
                            discount_applied = 0.0
                            
                except Exception as e:
                    # CRITICAL: Fail-silent on voucher errors to prevent transaction crashes
                    logger.error(f"Voucher processing error for user {user_id} (failing silent): {str(e)}")
                    voucher_discount = 0.0
                    # Continue with normal pricing
            
            # POLICY COMPLIANCE: No subscription discounts needed since there's no markup
            # selling_price already equals cost_price (no markup to discount from)
            if voucher_discount == 0.0:
                # No additional discounts needed - already at cost price
                pass
            
            # POLICY COMPLIANCE: Already at cost price, no loss possible
            # selling_price = cost_price (no markup applied)
            
            # Calculate final metrics
            actual_margin = selling_price - cost_price
            actual_margin_percentage = (actual_margin / cost_price) * 100 if cost_price > 0 else 0
            
            # Generate policy-compliant savings message
            savings_message = "No fees on VAS purchases - you pay exactly what we pay!"
            
            # Policy-compliant strategy
            strategy_used = "no_markup_policy"
            
            return {
                'selling_price': round(selling_price, 2),
                'cost_price': round(cost_price, 2),
                'margin': round(actual_margin, 2),
                'margin_percentage': round(actual_margin_percentage, 2),
                'discount_applied': round(discount_applied, 2),
                'voucher_discount': round(voucher_discount, 2),
                'strategy_used': strategy_used,
                'savings_message': savings_message,
                'psychological_ceiling_applied': False,
                'free_fee_applied': voucher_discount > 0,
                'policy_compliant': True  # Confirms no-markup policy compliance
            }
            
        except Exception as e:
            logger.error(f"Error calculating selling price: {str(e)}")
            
            # Return safe fallback pricing (NO MARKUP even in fallback)
            return {
                'selling_price': base_amount,  # NO MARKUP - policy compliance
                'cost_price': base_amount,
                'margin': 0.0,
                'margin_percentage': 0.0,
                'discount_applied': 0.0,
                'strategy_used': 'fallback_no_markup',
                'savings_message': 'No fees policy maintained even in fallback',
                'psychological_ceiling_applied': False,
                'policy_compliant': True
            }

    def _apply_psychological_pricing(self, base_price: float, network: str, service_type: str) -> float:
        """
        Apply psychological pricing rules
        CRITICAL FIX: Always round UP to prevent selling below cost
        """
        
        # Rule 1: ₦500 ceiling for popular plans
        if base_price > self.PSYCHOLOGICAL_CEILING:
            if service_type == 'data' and '1GB' in str(base_price):
                # For 1GB plans, try to stay under ₦500
                return min(base_price, self.PSYCHOLOGICAL_CEILING - 1)
        
        # Rule 2: End prices with 9 for amounts over ₦200
        # CRITICAL FIX: Use math.ceil to always round UP, never down into our margin
        if base_price > 200:
            # Round UP to nearest 10, then subtract 1
            rounded = math.ceil(base_price / 10) * 10
            return rounded - 1
        
        # Rule 3: Round UP to nearest 5 for smaller amounts
        # CRITICAL FIX: Use math.ceil to ensure we never round down below cost
        if base_price <= 200:
            return math.ceil(base_price / 5) * 5
        
        return base_price

    def _check_free_fee_voucher(self, user_id: str, service_type: str):
        """
        Check if user has active free fee voucher from emergency recovery
        CRITICAL: Fail-silent on voucher errors to prevent transaction crashes
        """
        try:
            from bson import ObjectId
            
            # Validate user_id format first
            if not user_id:
                return None
                
            try:
                user_object_id = ObjectId(user_id)
            except Exception:
                logger.warning(f"Invalid user_id format for voucher check: {user_id}")
                return None
            
            # Query with additional safety checks
            current_time = datetime.utcnow()
            
            active_voucher = self.mongo.user_vouchers.find_one({
                'userId': user_object_id,
                'type': 'EMERGENCY_RECOVERY_DISCOUNT',
                'discountType': 'FREE_FEES',
                'status': 'ACTIVE',
                'remainingUses': {'$gt': 0},
                'expiresAt': {'$gt': current_time}
            })
            
            # Double-check expiry to handle race conditions
            if active_voucher:
                expires_at = active_voucher.get('expiresAt')
                if expires_at and expires_at <= current_time:
                    logger.info(f"Voucher {active_voucher['_id']} expired during check, marking as expired")
                    # Mark as expired atomically
                    self.mongo.user_vouchers.update_one(
                        {'_id': active_voucher['_id']},
                        {'$set': {'status': 'EXPIRED', 'expiredAt': current_time}}
                    )
                    return None
            
            return active_voucher
            
        except Exception as e:
            # CRITICAL: Fail-silent to prevent transaction crashes
            logger.error(f"Error checking free fee voucher (failing silent): {str(e)}")
            return None

    def _use_voucher(self, voucher_id):
        """
        Mark voucher as used (decrement remaining uses)
        CRITICAL: Atomic operations with race condition protection
        """
        try:
            from bson import ObjectId
            
            # Handle both ObjectId and string inputs
            if isinstance(voucher_id, str):
                voucher_id = ObjectId(voucher_id)
            
            # Atomic decrement with expiry check
            current_time = datetime.utcnow()
            
            # First, try to decrement remaining uses atomically
            result = self.mongo.user_vouchers.update_one(
                {
                    '_id': voucher_id, 
                    'remainingUses': {'$gt': 0},
                    'status': 'ACTIVE',
                    'expiresAt': {'$gt': current_time}  # Ensure not expired
                },
                {
                    '$inc': {'remainingUses': -1},
                    '$set': {'lastUsedAt': current_time}
                }
            )
            
            if result.modified_count == 0:
                logger.warning(f"Voucher {voucher_id} could not be used (expired, inactive, or no uses left)")
                return False
            
            # Check if voucher is now exhausted and mark as expired
            updated_voucher = self.mongo.user_vouchers.find_one({'_id': voucher_id})
            if updated_voucher and updated_voucher.get('remainingUses', 0) <= 0:
                self.mongo.user_vouchers.update_one(
                    {'_id': voucher_id},
                    {'$set': {'status': 'EXPIRED', 'expiredAt': current_time}}
                )
                logger.info(f"Voucher {voucher_id} exhausted and marked as expired")
            
            logger.info(f"Voucher {voucher_id} used successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error using voucher (failing silent): {str(e)}")
            return False

    def _generate_savings_message(
        self, 
        user_tier: str, 
        discount_applied: float, 
        margin: float, 
        network: str, 
        service_type: str,
        free_fee_applied: bool = False
    ) -> str:
        """Generate user-friendly savings message"""
        
        if free_fee_applied:
            return f"🎁 FREE transaction! Emergency recovery voucher applied"
        
        elif user_tier == 'gold' and discount_applied > 0:
            return f"💰 You saved ₦{discount_applied:.0f} as a Gold Member!"
        
        elif user_tier == 'premium' and discount_applied > 0:
            return f"✨ You saved ₦{discount_applied:.0f} as a Premium Member!"
        
        elif network == 'GLO' and service_type == 'data':
            return f"🔥 Best value! GLO data at unbeatable prices"
        
        elif network == 'MTN' and service_type == 'airtime':
            return f"⚡ Instant delivery guaranteed"
        
        return ""

    def _determine_strategy(
        self, 
        network: str, 
        service_type: str, 
        user_tier: str, 
        selling_price: float, 
        cost_price: float,
        free_fee_applied: bool = False
    ) -> str:
        """Determine which pricing strategy was applied"""
        
        if free_fee_applied:
            return "emergency_recovery_free_fee"
        
        margin_percentage = ((selling_price - cost_price) / cost_price) * 100
        
        if user_tier == 'gold':
            return "gold_cost_plus_5"
        elif margin_percentage < 3:
            return "loss_leader"
        elif margin_percentage > 10:
            return "high_margin"
        elif selling_price < self.PSYCHOLOGICAL_CEILING:
            return "psychological_ceiling"
        else:
            return "standard_margin"

    def get_competitive_analysis(self, service_type: str, network: str, amount: float) -> Dict:
        """
        Get competitive analysis vs market rates
        """
        try:
            # Your pricing
            your_pricing = self.calculate_selling_price(service_type, network, amount)
            
            # Estimated competitor pricing (based on market research)
            competitor_rates = {
                'OPay': amount * 1.02,      # 2% markup
                'PalmPay': amount * 1.025,  # 2.5% markup
                'Kuda': amount * 1.03,      # 3% markup
                'Moniepoint': amount * 1.015 # 1.5% markup
            }
            
            your_price = your_pricing['selling_price']
            
            # Find cheapest competitor
            cheapest_competitor = min(competitor_rates.items(), key=lambda x: x[1])
            
            # Calculate competitive position
            if your_price <= cheapest_competitor[1]:
                position = "cheapest"
                message = f"🏆 Cheapest in market! ₦{cheapest_competitor[1] - your_price:.0f} cheaper than {cheapest_competitor[0]}"
            elif your_price <= cheapest_competitor[1] * 1.02:  # Within 2%
                position = "competitive"
                message = f"💪 Competitive pricing! Only ₦{your_price - cheapest_competitor[1]:.0f} more than cheapest"
            else:
                position = "premium"
                message = f"⭐ Premium service with extra value"
            
            return {
                'your_price': your_price,
                'competitors': competitor_rates,
                'cheapest_competitor': cheapest_competitor[0],
                'cheapest_price': cheapest_competitor[1],
                'position': position,
                'message': message,
                'price_difference': your_price - cheapest_competitor[1]
            }
            
        except Exception as e:
            logger.error(f"Error in competitive analysis: {str(e)}")
            return {}

    def update_pricing_strategy(self, network: str, service_type: str, new_margin: float):
        """
        Update pricing strategy for a specific network/service
        """
        try:
            if network.upper() in self.NETWORK_MARGINS:
                self.NETWORK_MARGINS[network.upper()][service_type] = new_margin
                
                # Save to database for persistence
                self.mongo.pricing_strategies.replace_one(
                    {'network': network.upper(), 'service_type': service_type},
                    {
                        'network': network.upper(),
                        'service_type': service_type,
                        'margin': new_margin,
                        'updated_at': datetime.utcnow()
                    },
                    upsert=True
                )
                
                logger.info(f"Updated {network} {service_type} margin to {new_margin}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating pricing strategy: {str(e)}")
            return False

# Utility functions for easy integration
def get_pricing_engine(mongo_db):
    """Factory function to get pricing engine instance"""
    return DynamicPricingEngine(mongo_db)

def calculate_vas_price(mongo_db, service_type: str, network: str, amount: float, user_tier: str = 'basic', plan_id: str = None, user_id: str = None):
    """Quick function to calculate VAS pricing with voucher support"""
    engine = get_pricing_engine(mongo_db)
    return engine.calculate_selling_price(service_type, network, amount, user_tier, plan_id, user_id)