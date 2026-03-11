"""
KYC Encryption Utilities
Shared encryption functions for BVN/NIN data
"""

import os
import hashlib
import logging
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

def get_encryption_key():
    """Get or create encryption key for sensitive data"""
    key = os.environ.get('KYC_ENCRYPTION_KEY')
    if not key:
        # Generate a key if not provided (store this securely in production)
        key = Fernet.generate_key().decode()
        logger.warning("Using generated encryption key - set KYC_ENCRYPTION_KEY in production")
    return key.encode() if isinstance(key, str) else key

def encrypt_sensitive_data(data):
    """Encrypt sensitive data like BVN/NIN"""
    if not data or not data.strip():
        return ""
    
    try:
        fernet = Fernet(get_encryption_key())
        return fernet.encrypt(data.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption error: {str(e)}")
        # Fallback to hashing if encryption fails
        return hashlib.sha256(data.encode()).hexdigest()

def decrypt_sensitive_data(encrypted_data):
    """Decrypt sensitive data for admin viewing"""
    if not encrypted_data:
        return ""
    
    try:
        fernet = Fernet(get_encryption_key())
        return fernet.decrypt(encrypted_data.encode()).decode()
    except Exception as e:
        logger.error(f"Decryption error: {str(e)}")
        # Return masked version if decryption fails
        return f"***{encrypted_data[-4:]}" if len(encrypted_data) > 4 else "***"

def mask_sensitive_data(data):
    """Mask sensitive data for display"""
    if not data or len(data) < 4:
        return "***"
    return f"***{data[-4:]}"