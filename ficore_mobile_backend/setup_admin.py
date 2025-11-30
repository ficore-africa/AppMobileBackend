#!/usr/bin/env python3
"""
Admin Setup Script for FiCore Mobile Backend

This script creates an admin user in the MongoDB database.
Run this script to set up the initial admin account.

Usage:
    python setup_admin.py

Default admin credentials:
    Email: admin@ficore.com
    Password: admin123
    Role: admin
"""

import os
import sys
from datetime import datetime
from werkzeug.security import generate_password_hash
from pymongo import MongoClient
from bson import ObjectId

# MongoDB connection
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')

def setup_admin_user():
    """Create admin user in the database"""
    try:
        # Connect to MongoDB
        client = MongoClient(MONGO_URI)
        db = client.get_default_database()
        
        # Admin user data
        admin_email = "admin@ficore.com"
        admin_password = "admin123"
        
        # Check if admin already exists
        existing_admin = db.users.find_one({"email": admin_email})
        if existing_admin:
            print(f"❌ Admin user with email {admin_email} already exists!")
            print(f"   User ID: {existing_admin['_id']}")
            print(f"   Role: {existing_admin.get('role', 'personal')}")
            
            # Update role to admin if not already
            if existing_admin.get('role') != 'admin':
                db.users.update_one(
                    {"_id": existing_admin['_id']},
                    {"$set": {"role": "admin", "updatedAt": datetime.utcnow()}}
                )
                print(f"✅ Updated existing user role to admin")
            
            return existing_admin['_id']
        
        # Create new admin user
        admin_user = {
            "_id": ObjectId(),
            "email": admin_email,
            "password": generate_password_hash(admin_password),
            "firstName": "System",
            "lastName": "Administrator",
            "displayName": "System Administrator",
            "role": "admin",
            "ficoreCreditBalance": 0.0,
            "setupComplete": True,
            "isActive": True,
            "language": "en",
            "currency": "NGN",
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
            "settings": {
                "notifications": {
                    "push": True,
                    "email": True,
                    "budgetAlerts": True,
                    "expenseAlerts": True
                },
                "privacy": {
                    "profileVisibility": "private",
                    "dataSharing": False
                },
                "preferences": {
                    "currency": "NGN",
                    "language": "en",
                    "theme": "light",
                    "dateFormat": "DD/MM/YYYY"
                }
            }
        }
        
        # Insert admin user
        result = db.users.insert_one(admin_user)
        
        print("✅ Admin user created successfully!")
        print(f"   User ID: {result.inserted_id}")
        print(f"   Email: {admin_email}")
        print(f"   Password: {admin_password}")
        print(f"   Role: admin")
        print()
        print("🌐 Admin Web Interface:")
        print("   Open admin_web_app/index.html in your browser")
        print("   Or serve it with a local web server")
        print()
        print("🔐 Login Credentials:")
        print(f"   Email: {admin_email}")
        print(f"   Password: {admin_password}")
        
        return result.inserted_id
        
    except Exception as e:
        print(f"❌ Error setting up admin user: {str(e)}")
        return None
    finally:
        client.close()

def create_sample_data():
    """Create some sample data for testing"""
    try:
        client = MongoClient(MONGO_URI)
        db = client.get_default_database()
        
        # Create a sample regular user
        sample_user_email = "user@ficore.com"
        existing_user = db.users.find_one({"email": sample_user_email})
        
        if not existing_user:
            sample_user = {
                "_id": ObjectId(),
                "email": sample_user_email,
                "password": generate_password_hash("user123"),
                "firstName": "John",
                "lastName": "Doe",
                "displayName": "John Doe",
                "role": "personal",
                "ficoreCreditBalance": 1500.0,
                "setupComplete": True,
                "isActive": True,
                "language": "en",
                "currency": "NGN",
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }
            
            user_result = db.users.insert_one(sample_user)
            print(f"✅ Sample user created: {sample_user_email} / user123")
            
            # Create a sample credit request
            credit_request = {
                "_id": ObjectId(),
                "requestId": f"CR{datetime.now().strftime('%Y%m%d%H%M%S')}001",
                "userId": user_result.inserted_id,
                "amount": 5000.0,
                "paymentMethod": "Bank Transfer",
                "paymentReference": "TXN123456789",
                "status": "pending",
                "notes": "Need credits for app usage",
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }
            
            db.credit_requests.insert_one(credit_request)
            
            # Create corresponding transaction
            transaction = {
                "_id": ObjectId(),
                "userId": user_result.inserted_id,
                "requestId": credit_request["requestId"],
                "type": "request",
                "amount": 5000.0,
                "description": "Credit top-up request",
                "status": "pending",
                "paymentMethod": "Bank Transfer",
                "paymentReference": "TXN123456789",
                "createdAt": datetime.utcnow()
            }
            
            db.credit_transactions.insert_one(transaction)
            print("✅ Sample credit request created")
        
    except Exception as e:
        print(f"⚠️  Warning: Could not create sample data: {str(e)}")
    finally:
        client.close()

def main():
    print("🚀 FiCore Admin Setup")
    print("=" * 50)
    
    # Setup admin user
    admin_id = setup_admin_user()
    
    if admin_id:
        print()
        print("📊 Creating sample data...")
        create_sample_data()
        
        print()
        print("=" * 50)
        print("✅ Setup completed successfully!")
        print()
        print("Next steps:")
        print("1. Start your backend server: python app.py")
        print("2. Open admin_web_app/index.html in your browser")
        print("3. Login with admin credentials")
        print("4. Manage users and credit requests")
        print()
        print("Backend API endpoints:")
        print("- GET  /admin/credit-requests - View all credit requests")
        print("- POST /admin/credit-requests/{id}/approve - Approve request")
        print("- POST /admin/credit-requests/{id}/reject - Reject request")
        print("- GET  /admin/users - View all users")
        print("- POST /admin/users/{id}/credits - Adjust user credits")
    else:
        print("❌ Setup failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()