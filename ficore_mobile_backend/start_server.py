#!/usr/bin/env python3
"""
Start the FiCore Mobile Backend server
"""

import os
import sys
from app import app

if __name__ == '__main__':
    # Set environment variables for development
    os.environ.setdefault('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
    os.environ.setdefault('SECRET_KEY', 'ficore-mobile-secret-key-2024')
    
    print("Starting FiCore Mobile Backend...")
    print(f"MongoDB URI: {os.environ.get('MONGO_URI')}")
    print("Server will be available at: http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting server: {e}")
        sys.exit(1)