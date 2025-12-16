"""
Ensure all required upload directories exist
Run this after deployment or when setting up the server
"""
import os

# Get the directory where this script is located
base_dir = os.path.dirname(__file__)

# List of required upload directories
upload_dirs = [
    'uploads/profile_pictures',
    'uploads/receipts',
    'uploads/documents',
    'uploads/attachments',
]

print("Creating upload directories...")
for dir_path in upload_dirs:
    full_path = os.path.join(base_dir, dir_path)
    os.makedirs(full_path, exist_ok=True)
    print(f"✓ {dir_path}")

print("\n✓ All upload directories created successfully!")
