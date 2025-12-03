"""
Fix profile picture issues by:
1. Creating the profile_pictures directory if it doesn't exist
2. Checking which users have profile picture URLs but missing files
3. Optionally clearing invalid URLs from the database
"""
import os
from pymongo import MongoClient
from urllib.parse import urlparse

# MongoDB connection
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client['ficore_db']

# Create profile_pictures directory
uploads_dir = os.path.join(os.path.dirname(__file__), 'uploads', 'profile_pictures')
os.makedirs(uploads_dir, exist_ok=True)
print(f"✓ Created/verified directory: {uploads_dir}")

# Check users with profile pictures
users_with_pics = db.users.find({'profilePictureUrl': {'$exists': True, '$ne': None}})

missing_files = []
for user in users_with_pics:
    url = user.get('profilePictureUrl', '')
    if url:
        # Extract filename from URL
        parsed = urlparse(url)
        path_parts = parsed.path.split('/')
        if 'profile_pictures' in path_parts:
            idx = path_parts.index('profile_pictures')
            if idx + 1 < len(path_parts):
                filename = path_parts[idx + 1]
                filepath = os.path.join(uploads_dir, filename)
                
                if not os.path.exists(filepath):
                    missing_files.append({
                        'user_id': str(user['_id']),
                        'email': user.get('email', 'N/A'),
                        'url': url,
                        'filename': filename
                    })
                    print(f"✗ Missing file for {user.get('email')}: {filename}")

if missing_files:
    print(f"\n{len(missing_files)} users have missing profile picture files")
    print("\nOptions:")
    print("1. Clear invalid URLs from database (users will see default avatar)")
    print("2. Keep URLs (users will see error widget)")
    
    choice = input("\nEnter choice (1 or 2): ").strip()
    
    if choice == '1':
        for item in missing_files:
            db.users.update_one(
                {'_id': item['user_id']},
                {'$unset': {'profilePictureUrl': ''}}
            )
        print(f"✓ Cleared {len(missing_files)} invalid profile picture URLs")
else:
    print("\n✓ All profile picture files exist!")

print("\nDone!")
