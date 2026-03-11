"""
Profile Utilities

User profile management utilities.
"""

import hashlib
import logging

logger = logging.getLogger(__name__)

def generate_profile_picture_url(user_email, size=200):
    """
    Generate profile picture URL using Gravatar
    
    Args:
        user_email: User email address
        size: Image size in pixels
        
    Returns:
        str: Profile picture URL
    """
    try:
        if not user_email:
            return f"https://via.placeholder.com/{size}x{size}?text=User"
        
        # Generate Gravatar hash
        email_hash = hashlib.md5(user_email.lower().encode()).hexdigest()
        
        # Return Gravatar URL with fallback
        return f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d=identicon"
        
    except Exception as e:
        logger.error(f"Error generating profile picture URL: {str(e)}")
        return f"https://via.placeholder.com/{size}x{size}?text=User"

def generate_referral_code(user_id, length=8):
    """
    Generate referral code for user
    
    Args:
        user_id: User ObjectId
        length: Length of referral code
        
    Returns:
        str: Referral code
    """
    try:
        import random
        import string
        
        # Use user ID as seed for consistency
        random.seed(str(user_id))
        
        # Generate code with letters and numbers
        characters = string.ascii_uppercase + string.digits
        code = ''.join(random.choices(characters, k=length))
        
        return f"FC{code}"
        
    except Exception as e:
        logger.error(f"Error generating referral code: {str(e)}")
        return "FC00000000"
