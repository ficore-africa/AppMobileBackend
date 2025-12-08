"""
Messaging Service for WhatsApp and SMS
Supports Twilio for production and fallback to URL generation for development
"""
import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class MessagingService:
    """Service for sending WhatsApp and SMS messages"""
    
    def __init__(self):
        self.twilio_enabled = False
        self.twilio_client = None
        self.twilio_phone = None
        self.twilio_whatsapp = None
        
        # Try to initialize Twilio if credentials are available
        self._init_twilio()
    
    def _init_twilio(self):
        """Initialize Twilio client if credentials are available"""
        try:
            account_sid = os.getenv('TWILIO_ACCOUNT_SID')
            auth_token = os.getenv('TWILIO_AUTH_TOKEN')
            self.twilio_phone = os.getenv('TWILIO_PHONE_NUMBER')
            self.twilio_whatsapp = os.getenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')
            
            if account_sid and auth_token:
                from twilio.rest import Client
                self.twilio_client = Client(account_sid, auth_token)
                self.twilio_enabled = True
                logger.info("Twilio messaging service initialized successfully")
            else:
                logger.info("Twilio credentials not found, using fallback URL generation")
        except ImportError:
            logger.warning("Twilio library not installed, using fallback URL generation")
        except Exception as e:
            logger.error(f"Failed to initialize Twilio: {str(e)}")
    
    def send_whatsapp(
        self, 
        to_phone: str, 
        message: str,
        debtor_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send WhatsApp message
        
        Args:
            to_phone: Recipient phone number (international format)
            message: Message content
            debtor_id: Optional debtor ID for tracking
            user_id: Optional user ID for tracking
            
        Returns:
            Dict with success status, message_sid (if sent), or whatsapp_url (if fallback)
        """
        try:
            # Clean phone number
            clean_phone = self._clean_phone_number(to_phone)
            
            if self.twilio_enabled and self.twilio_client:
                # Send via Twilio
                try:
                    message_obj = self.twilio_client.messages.create(
                        from_=self.twilio_whatsapp,
                        to=f'whatsapp:{clean_phone}',
                        body=message
                    )
                    
                    logger.info(f"WhatsApp message sent successfully: {message_obj.sid}")
                    
                    return {
                        'success': True,
                        'method': 'twilio',
                        'message_sid': message_obj.sid,
                        'status': message_obj.status,
                        'to': clean_phone,
                        'sent_at': datetime.utcnow().isoformat()
                    }
                except Exception as e:
                    logger.error(f"Twilio WhatsApp send failed: {str(e)}")
                    # Fall back to URL generation
                    return self._generate_whatsapp_url(clean_phone, message)
            else:
                # Fallback: Generate WhatsApp URL
                return self._generate_whatsapp_url(clean_phone, message)
                
        except Exception as e:
            logger.error(f"WhatsApp send error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'method': 'failed'
            }
    
    def send_sms(
        self,
        to_phone: str,
        message: str,
        debtor_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send SMS message
        
        Args:
            to_phone: Recipient phone number (international format)
            message: Message content
            debtor_id: Optional debtor ID for tracking
            user_id: Optional user ID for tracking
            
        Returns:
            Dict with success status, message_sid (if sent), or sms_url (if fallback)
        """
        try:
            # Clean phone number
            clean_phone = self._clean_phone_number(to_phone)
            
            if self.twilio_enabled and self.twilio_client and self.twilio_phone:
                # Send via Twilio
                try:
                    message_obj = self.twilio_client.messages.create(
                        from_=self.twilio_phone,
                        to=clean_phone,
                        body=message
                    )
                    
                    logger.info(f"SMS sent successfully: {message_obj.sid}")
                    
                    return {
                        'success': True,
                        'method': 'twilio',
                        'message_sid': message_obj.sid,
                        'status': message_obj.status,
                        'to': clean_phone,
                        'sent_at': datetime.utcnow().isoformat()
                    }
                except Exception as e:
                    logger.error(f"Twilio SMS send failed: {str(e)}")
                    # Fall back to URL generation
                    return self._generate_sms_url(clean_phone, message)
            else:
                # Fallback: Generate SMS URL
                return self._generate_sms_url(clean_phone, message)
                
        except Exception as e:
            logger.error(f"SMS send error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'method': 'failed'
            }
    
    def _clean_phone_number(self, phone: str) -> str:
        """Clean and format phone number to international format"""
        if not phone:
            raise ValueError("Phone number is required")
        
        # Remove all non-digit characters except +
        import re
        cleaned = re.sub(r'[^\d+]', '', phone)
        
        # Handle Nigerian numbers (234 country code)
        if cleaned.startswith('0'):
            # Replace leading 0 with +234
            cleaned = '+234' + cleaned[1:]
        elif cleaned.startswith('234') and not cleaned.startswith('+'):
            # Add + if missing
            cleaned = '+' + cleaned
        elif not cleaned.startswith('+') and len(cleaned) >= 10:
            # Assume Nigerian number if no country code
            cleaned = '+234' + cleaned
        
        # Validate format
        if not cleaned.startswith('+') or len(cleaned) < 10:
            raise ValueError(f"Invalid phone number format: {phone}")
        
        return cleaned
    
    def _generate_whatsapp_url(self, phone: str, message: str) -> Dict[str, Any]:
        """Generate WhatsApp URL for manual sending"""
        import urllib.parse
        encoded_message = urllib.parse.quote(message)
        whatsapp_url = f"https://wa.me/{phone.replace('+', '')}?text={encoded_message}"
        
        return {
            'success': True,
            'method': 'url',
            'whatsapp_url': whatsapp_url,
            'to': phone,
            'message': message,
            'requires_manual_action': True
        }
    
    def _generate_sms_url(self, phone: str, message: str) -> Dict[str, Any]:
        """Generate SMS URL for manual sending"""
        import urllib.parse
        encoded_message = urllib.parse.quote(message)
        sms_url = f"sms:{phone}?body={encoded_message}"
        
        return {
            'success': True,
            'method': 'url',
            'sms_url': sms_url,
            'to': phone,
            'message': message,
            'requires_manual_action': True
        }
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get current service status"""
        return {
            'twilio_enabled': self.twilio_enabled,
            'whatsapp_available': self.twilio_enabled or True,  # URL fallback always available
            'sms_available': self.twilio_enabled or True,  # URL fallback always available
            'mode': 'production' if self.twilio_enabled else 'development'
        }


# Singleton instance
_messaging_service = None

def get_messaging_service() -> MessagingService:
    """Get or create messaging service singleton"""
    global _messaging_service
    if _messaging_service is None:
        _messaging_service = MessagingService()
    return _messaging_service
