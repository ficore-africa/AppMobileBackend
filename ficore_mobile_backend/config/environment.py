"""
Environment Configuration for VAS Services
Extracted from vas_purchase.py to avoid import errors in plan validation

This module provides centralized access to environment variables for:
- Peyflex API configuration
- Monnify API configuration
- Other VAS service configurations
"""

import os

# Peyflex API Configuration
PEYFLEX_API_TOKEN = os.environ.get('PEYFLEX_API_TOKEN', '')
PEYFLEX_BASE_URL = os.environ.get('PEYFLEX_BASE_URL', 'https://client.peyflex.com.ng')

# Monnify API Configuration
MONNIFY_API_KEY = os.environ.get('MONNIFY_API_KEY', '')
MONNIFY_SECRET_KEY = os.environ.get('MONNIFY_SECRET_KEY', '')
MONNIFY_CONTRACT_CODE = os.environ.get('MONNIFY_CONTRACT_CODE', '')
MONNIFY_BASE_URL = os.environ.get('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')

# VAS Configuration
VAS_TRANSACTION_FEE = 30.0