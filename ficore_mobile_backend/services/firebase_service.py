"""
Firebase Push Notification Service
Uses the credential manager for proper Firebase initialization
"""
import logging
from typing import Optional, Dict, Any, List
from config.credentials import credential_manager

logger = logging.getLogger(__name__)

class FirebaseService:
    """Service for sending push notifications via Firebase Cloud Messaging"""
    
    def __init__(self):
        self.is_available = credential_manager.is_firebase_available()
        if not self.is_available:
            logger.warning("Firebase is not available. Push notifications will be disabled.")
    
    def send_push_notification(
        self, 
        fcm_token: str, 
        title: str, 
        body: str, 
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Send a push notification to a single device
        
        Args:
            fcm_token: Firebase Cloud Messaging token
            title: Notification title
            body: Notification body
            data: Optional data payload
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_available:
            logger.warning("Firebase not available, skipping push notification")
            return False
        
        try:
            from firebase_admin import messaging
            
            # Create the message
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body
                ),
                data=data or {},
                token=fcm_token
            )
            
            # Send the message
            response = messaging.send(message)
            logger.info(f"Push notification sent successfully: {response}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send push notification: {e}")
            return False
    
    def send_push_notifications_batch(
        self, 
        tokens: List[str], 
        title: str, 
        body: str, 
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send push notifications to multiple devices
        
        Args:
            tokens: List of FCM tokens
            title: Notification title
            body: Notification body
            data: Optional data payload
            
        Returns:
            dict: Results with success/failure counts
        """
        if not self.is_available:
            logger.warning("Firebase not available, skipping batch push notifications")
            return {
                'success_count': 0,
                'failure_count': len(tokens),
                'responses': []
            }
        
        if not tokens:
            return {
                'success_count': 0,
                'failure_count': 0,
                'responses': []
            }
        
        try:
            from firebase_admin import messaging
            
            # Create messages for all tokens
            messages = []
            for token in tokens:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=title,
                        body=body
                    ),
                    data=data or {},
                    token=token
                )
                messages.append(message)
            
            # Send batch
            response = messaging.send_all(messages)
            
            logger.info(f"Batch push notifications sent: {response.success_count} success, {response.failure_count} failures")
            
            return {
                'success_count': response.success_count,
                'failure_count': response.failure_count,
                'responses': [
                    {
                        'success': resp.success,
                        'message_id': resp.message_id if resp.success else None,
                        'error': str(resp.exception) if not resp.success else None
                    }
                    for resp in response.responses
                ]
            }
            
        except Exception as e:
            logger.error(f"Failed to send batch push notifications: {e}")
            return {
                'success_count': 0,
                'failure_count': len(tokens),
                'responses': [],
                'error': str(e)
            }
    
    def send_topic_notification(
        self, 
        topic: str, 
        title: str, 
        body: str, 
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Send a push notification to a topic
        
        Args:
            topic: Firebase topic name
            title: Notification title
            body: Notification body
            data: Optional data payload
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.is_available:
            logger.warning("Firebase not available, skipping topic notification")
            return False
        
        try:
            from firebase_admin import messaging
            
            # Create the message
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body
                ),
                data=data or {},
                topic=topic
            )
            
            # Send the message
            response = messaging.send(message)
            logger.info(f"Topic notification sent successfully: {response}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send topic notification: {e}")
            return False
    
    def validate_token(self, fcm_token: str) -> bool:
        """
        Validate if an FCM token is valid
        
        Args:
            fcm_token: Firebase Cloud Messaging token
            
        Returns:
            bool: True if valid, False otherwise
        """
        if not self.is_available:
            return False
        
        try:
            from firebase_admin import messaging
            
            # Try to send a dry-run message
            message = messaging.Message(
                notification=messaging.Notification(
                    title="Test",
                    body="Test"
                ),
                token=fcm_token
            )
            
            # Send as dry run (won't actually send)
            messaging.send(message, dry_run=True)
            return True
            
        except Exception as e:
            logger.debug(f"FCM token validation failed: {e}")
            return False

# Global instance
firebase_service = FirebaseService()