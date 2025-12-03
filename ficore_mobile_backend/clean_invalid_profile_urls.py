"""
Clean invalid profile picture URLs from the database.
This script removes profile picture URLs that point to non-existent local files.
Users will need to re-upload their profile pictures to Google Cloud Storage.
"""
import os
from pymongo import MongoClient
from urllib.parse import urlparse

# MongoDB connection
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb+srv://ficoreafrica_db_user:ScSbMkRwkauvTPyx@cluster0.53rbo1f.mongodb.net/ficore_africa?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true')
client = MongoClient(MONGO_URI)
db = client['ficore_africa']

print("🔍 Checking for invalid profile picture URLs...")

# Find users with profile picture URLs pointing to local uploads
users_with_local_pics = db.users.find({
    'profilePictureUrl': {'$regex': '/uploads/profile_pictures/', '$options': 'i'}
})

invalid_count = 0
for user in users_with_local_pics:
    url = user.get('profilePictureUrl', '')
    email = user.get('email', 'N/A')
    
    # These are local URLs that won't work on Render (ephemeral filesystem)
    print(f"  ✗ Found local URL for {email}: {url}")
    
    # Clear the invalid URL
    db.users.update_one(
        {'_id': user['_id']},
        {
            '$unset': {'profilePictureUrl': ''},
            '$set': {'updatedAt': user.get('updatedAt')}
        }
    )
    invalid_count += 1

if invalid_count > 0:
    print(f"\n✓ Cleared {invalid_count} invalid profile picture URLs")
    print("  Users will need to re-upload their profile pictures.")
    print("  New uploads will be stored in Google Cloud Storage (persistent).")
else:
    print("\n✓ No invalid profile picture URLs found!")

# Check for users with GCS URLs (these are good)
users_with_gcs_pics = db.users.find({
    'profilePictureUrl': {'$regex': 'storage.googleapis.com', '$options': 'i'}
})

gcs_count = sum(1 for _ in users_with_gcs_pics)
if gcs_count > 0:
    print(f"\n✓ {gcs_count} users have valid Google Cloud Storage profile pictures")

print("\n✅ Done!")
