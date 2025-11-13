#!/usr/bin/env python3
"""
Diagnostic script to check upload folder permissions and system resources
for the receipt upload functionality.
"""

import os
import shutil
import stat
import traceback
from pathlib import Path

def check_upload_folder():
    """Check upload folder permissions and accessibility"""
    print("=== Upload Folder Diagnostic ===")
    
    # Define upload folder path (same as in credits.py)
    upload_folder = os.path.join(os.path.dirname(__file__), 'uploads', 'receipts')
    print(f"Upload folder path: {upload_folder}")
    print(f"Absolute path: {os.path.abspath(upload_folder)}")
    
    # Check if folder exists
    exists = os.path.exists(upload_folder)
    print(f"Folder exists: {exists}")
    
    if not exists:
        print("Creating upload folder...")
        try:
            os.makedirs(upload_folder, exist_ok=True)
            print("✓ Upload folder created successfully")
        except Exception as e:
            print(f"✗ Failed to create upload folder: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return False
    
    # Check permissions
    try:
        # Check read permission
        readable = os.access(upload_folder, os.R_OK)
        print(f"Readable: {readable}")
        
        # Check write permission
        writable = os.access(upload_folder, os.W_OK)
        print(f"Writable: {writable}")
        
        # Check execute permission (needed to list directory contents)
        executable = os.access(upload_folder, os.X_OK)
        print(f"Executable: {executable}")
        
        # Get detailed permissions
        if exists:
            stat_info = os.stat(upload_folder)
            permissions = stat.filemode(stat_info.st_mode)
            print(f"Permissions: {permissions}")
            print(f"Owner UID: {stat_info.st_uid}")
            print(f"Group GID: {stat_info.st_gid}")
    
    except Exception as e:
        print(f"✗ Error checking permissions: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return False
    
    # Test write operation
    test_file_path = os.path.join(upload_folder, 'test_write.txt')
    try:
        with open(test_file_path, 'w') as f:
            f.write('Test write operation')
        print("✓ Write test successful")
        
        # Clean up test file
        os.remove(test_file_path)
        print("✓ Test file cleanup successful")
        
    except Exception as e:
        print(f"✗ Write test failed: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return False
    
    return True

def check_disk_space():
    """Check available disk space"""
    print("\n=== Disk Space Diagnostic ===")
    
    try:
        # Get current directory disk usage
        current_dir = os.path.dirname(__file__)
        total, used, free = shutil.disk_usage(current_dir)
        
        print(f"Current directory: {current_dir}")
        print(f"Total space: {total / (1024**3):.2f} GB")
        print(f"Used space: {used / (1024**3):.2f} GB")
        print(f"Free space: {free / (1024**3):.2f} GB")
        print(f"Free space percentage: {(free/total)*100:.1f}%")
        
        # Check if we have enough space (at least 100MB free)
        min_free_space = 100 * 1024 * 1024  # 100MB
        if free < min_free_space:
            print(f"⚠️  Warning: Low disk space! Less than {min_free_space/(1024**2):.0f}MB available")
            return False
        else:
            print("✓ Sufficient disk space available")
            return True
            
    except Exception as e:
        print(f"✗ Error checking disk space: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return False

def check_python_environment():
    """Check Python environment and dependencies"""
    print("\n=== Python Environment Diagnostic ===")
    
    try:
        import sys
        print(f"Python version: {sys.version}")
        print(f"Python executable: {sys.executable}")
        
        # Check required modules
        required_modules = ['flask', 'werkzeug', 'bson', 'base64', 'uuid', 'os']
        for module in required_modules:
            try:
                __import__(module)
                print(f"✓ {module} module available")
            except ImportError as e:
                print(f"✗ {module} module missing: {e}")
                
    except Exception as e:
        print(f"✗ Error checking Python environment: {e}")
        print(f"Traceback: {traceback.format_exc()}")

def main():
    """Run all diagnostic checks"""
    print("FiCore Receipt Upload Diagnostic Tool")
    print("=" * 50)
    
    upload_ok = check_upload_folder()
    disk_ok = check_disk_space()
    check_python_environment()
    
    print("\n=== Summary ===")
    if upload_ok and disk_ok:
        print("✓ All checks passed - upload functionality should work")
    else:
        print("✗ Issues detected - please review the errors above")
        if not upload_ok:
            print("  - Upload folder permission issues")
        if not disk_ok:
            print("  - Disk space issues")

if __name__ == "__main__":
    main()