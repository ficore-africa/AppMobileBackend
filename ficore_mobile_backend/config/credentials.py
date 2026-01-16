"""
Credential management for Firebase and Google Cloud Storage
Handles multiple service accounts for different Google Cloud projects
"""
import os
import firebase_admin
from firebase_admin import credentials
from google.cloud import storage
import logging

logger = logging.getLogger(__name__)

class CredentialManager:
    """Manages Firebase and GCS credentials for multi-project setup"""
    
    def __init__(self):
        self.firebase_app = None
        self.gcs_client = None
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize Firebase and GCS with separate credentials"""
        try:
            # Initialize Firebase (Project: ficoreafricaapp)
            self._initialize_firebase()
            
            # Initialize GCS (Project: ficore-app-storage)
            self._initialize_gcs()
            
        except Exception as e:
            logger.error(f"Failed to initialize credentials: {e}")
            raise
    
    def _initialize_firebase(self):
        """Initialize Firebase Admin SDK"""
        try:
            # Check if Firebase is already initialized
            if firebase_admin._apps:
                logger.info("Firebase already initialized")
                return
            
            # Try to get Firebase credentials from Secret File path
            firebase_key_path = os.environ.get('FIREBASE_KEY_PATH')
            
            if firebase_key_path and os.path.exists(firebase_key_path):
                # Use Secret File (Render production)
                logger.info(f"Initializing Firebase with Secret File: {firebase_key_path}")
                cred = credentials.Certificate(firebase_key_path)
                self.firebase_app = firebase_admin.initialize_app(cred)
                
            elif os.environ.get('FIREBASE_CREDENTIALS_JSON'):
                # Use environment variable JSON (fallback)
                import json
                firebase_creds = json.loads(os.environ.get('FIREBASE_CREDENTIALS_JSON'))
                logger.info("Initializing Firebase with environment variable JSON")
                cred = credentials.Certificate(firebase_creds)
                self.firebase_app = firebase_admin.initialize_app(cred)
                
            elif os.path.exists('firebase-adminsdk.json'):
                # Use local file (development)
                logger.info("Initializing Firebase with local file: firebase-adminsdk.json")
                cred = credentials.Certificate('firebase-adminsdk.json')
                self.firebase_app = firebase_admin.initialize_app(cred)
                
            else:
                logger.warning("No Firebase credentials found. Push notifications will not work.")
                
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            # Don't raise - app can still work without push notifications
    
    def _initialize_gcs(self):
        """Initialize Google Cloud Storage client"""
        try:
            # Try to get GCS credentials from Secret File path
            gcs_key_path = os.environ.get('GCS_KEY_PATH')
            
            if gcs_key_path and os.path.exists(gcs_key_path):
                # Use Secret File (Render production)
                logger.info(f"Initializing GCS with Secret File: {gcs_key_path}")
                self.gcs_client = storage.Client.from_service_account_json(gcs_key_path)
                
            elif os.environ.get('GCS_CREDENTIALS_JSON'):
                # Use environment variable JSON (fallback)
                import json
                import tempfile
                gcs_creds = json.loads(os.environ.get('GCS_CREDENTIALS_JSON'))
                
                # Write to temporary file for GCS client
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                    json.dump(gcs_creds, temp_file)
                    temp_path = temp_file.name
                
                logger.info("Initializing GCS with environment variable JSON")
                self.gcs_client = storage.Client.from_service_account_json(temp_path)
                
                # Clean up temp file
                os.unlink(temp_path)
                
            elif os.path.exists('gcs-service-account.json'):
                # Use local file (development)
                logger.info("Initializing GCS with local file: gcs-service-account.json")
                self.gcs_client = storage.Client.from_service_account_json('gcs-service-account.json')
                
            else:
                # Try default credentials (might work in some environments)
                logger.info("Trying default GCS credentials")
                self.gcs_client = storage.Client()
                
        except Exception as e:
            logger.error(f"Failed to initialize GCS: {e}")
            raise  # GCS is critical for attachments
    
    def get_firebase_app(self):
        """Get Firebase app instance"""
        return self.firebase_app
    
    def get_gcs_client(self):
        """Get GCS client instance"""
        return self.gcs_client
    
    def is_firebase_available(self):
        """Check if Firebase is properly initialized"""
        return self.firebase_app is not None
    
    def is_gcs_available(self):
        """Check if GCS is properly initialized"""
        return self.gcs_client is not None

# Global instance
credential_manager = CredentialManager()