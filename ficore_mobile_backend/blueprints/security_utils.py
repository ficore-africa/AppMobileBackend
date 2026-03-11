"""
Security Utilities

Functions for encrypting, decrypting, and masking sensitive data.
"""

import base64
import hashlib
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger(__name__)

# Simple key derivation for demo purposes
# In production, use proper key management
def _get_encryption_key():
    """Get encryption key (simplified for demo)"""
    # This should be stored securely in production
    key_material = "ficore_encryption_key_2026"
    key = hashlib.sha256(key_material.encode()).digest()
    return base64.urlsafe_b64encode(key)

def encrypt_sensitive_data(data):
    """
    Encrypt sensitive data
    
    Args:
        data: String data to encrypt
        
    Returns:
        str: Encrypted data as base64 string
    """
    try:
        if not data:
            return ""
        
        key = _get_encryption_key()
        f = Fernet(key)
        
        encrypted_data = f.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted_data).decode()
        
    except Exception as e:
        logger.error(f"Error encrypting data: {str(e)}")
        return data  # Return original if encryption fails

def decrypt_sensitive_data(encrypted_data):
    """
    Decrypt sensitive data
    
    Args:
        encrypted_data: Base64 encoded encrypted data
        
    Returns:
        str: Decrypted data
    """
    try:
        if not encrypted_data:
            return ""
        
        key = _get_encryption_key()
        f = Fernet(key)
        
        decoded_data = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted_data = f.decrypt(decoded_data)
        return decrypted_data.decode()
        
    except Exception as e:
        logger.error(f"Error decrypting data: {str(e)}")
        return encrypted_data  # Return original if decryption fails

def mask_sensitive_data(data, mask_char="*", visible_chars=4):
    """
    Mask sensitive data for display
    
    Args:
        data: String data to mask
        mask_char: Character to use for masking
        visible_chars: Number of characters to leave visible at the end
        
    Returns:
        str: Masked data
    """
    try:
        if not data or len(data) <= visible_chars:
            return mask_char * len(data) if data else ""
        
        masked_length = len(data) - visible_chars
        return mask_char * masked_length + data[-visible_chars:]
        
    except Exception as e:
        logger.error(f"Error masking data: {str(e)}")
        return mask_char * 8  # Default mask
