"""Helper functions for profile picture URL generation"""
import os


def generate_profile_picture_url(user_doc):
    """Generate URL for profile picture from GCS or GridFS
    
    Args:
        user_doc: User document with gcsProfilePicturePath or gridfsProfilePictureId
        
    Returns:
        URL for profile picture, or None if not available
    """
    # Try GCS first
    gcs_path = user_doc.get('gcsProfilePicturePath')
    if gcs_path:
        try:
            from google.cloud import storage
            from datetime import timedelta
            
            storage_client = storage.Client()
            bucket_name = os.environ.get('GCS_BUCKET_NAME', 'ficore-attachments')
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(gcs_path)
            
            if blob.exists():
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(days=7),
                    method="GET"
                )
                print(f"✅ Generated GCS signed URL for: {gcs_path}")
                return signed_url
        except Exception as e:
            print(f"⚠️ Error generating GCS signed URL for {gcs_path}: {e}")
    
    # Fallback to GridFS
    gridfs_id = user_doc.get('gridfsProfilePictureId')
    if gridfs_id:
        try:
            # CRITICAL FIX: Return absolute URL for GridFS image
            # The Flutter app needs a full URL to load images via CachedNetworkImage
            base_url = os.environ.get('API_BASE_URL', 'https://mobilebackend.ficoreafrica.com')
            gridfs_url = f"{base_url}/api/users/profile-picture/{gridfs_id}"
            print(f"✅ Using GridFS URL: {gridfs_url}")
            return gridfs_url
        except Exception as e:
            print(f"⚠️ Error generating GridFS URL: {e}")
    
    return None
