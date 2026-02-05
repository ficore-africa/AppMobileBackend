#!/usr/bin/env python3
"""
Security Verification Script for FiCore Internal KYC System
Ensures FERNET_KEY is never hardcoded and PII encryption is secure
"""

import os
import sys
import re
from pathlib import Path

def check_hardcoded_keys():
    """Check for hardcoded encryption keys in the codebase"""
    print("🔍 Checking for hardcoded encryption keys...")
    
    # Patterns that indicate hardcoded keys
    dangerous_patterns = [
        r'FERNET_KEY\s*=\s*["\'][^"\']+["\']',  # FERNET_KEY = "hardcoded_key"
        r'KYC_ENCRYPTION_KEY\s*=\s*["\'][^"\']+["\']',  # KYC_ENCRYPTION_KEY = "hardcoded_key"
        r'Fernet\(["\'][^"\']+["\']\)',  # Fernet("hardcoded_key")
        r'fernet\s*=\s*Fernet\(["\'][^"\']+["\']\)',  # fernet = Fernet("hardcoded_key")
    ]
    
    # Files to check
    backend_dir = Path(__file__).parent.parent
    files_to_check = [
        backend_dir / "app.py",
        backend_dir / "blueprints" / "internal_kyc.py",
        backend_dir / "blueprints" / "vas_wallet.py",
    ]
    
    issues_found = []
    
    for file_path in files_to_check:
        if not file_path.exists():
            continue
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        for line_num, line in enumerate(content.split('\n'), 1):
            for pattern in dangerous_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    issues_found.append({
                        'file': str(file_path),
                        'line': line_num,
                        'content': line.strip(),
                        'issue': 'Potential hardcoded encryption key'
                    })
    
    if issues_found:
        print("❌ SECURITY ISSUES FOUND:")
        for issue in issues_found:
            print(f"  File: {issue['file']}")
            print(f"  Line {issue['line']}: {issue['content']}")
            print(f"  Issue: {issue['issue']}")
            print()
        return False
    else:
        print("✅ No hardcoded encryption keys found")
        return True

def check_environment_key():
    """Check if KYC_ENCRYPTION_KEY is properly set in environment"""
    print("🔍 Checking environment variable configuration...")
    
    key = os.environ.get('KYC_ENCRYPTION_KEY')
    if not key:
        print("⚠️  KYC_ENCRYPTION_KEY not set in environment")
        print("   This will cause the system to generate a temporary key")
        print("   Set KYC_ENCRYPTION_KEY in your .env file or environment")
        return False
    
    # Check key format (Fernet keys are 44 characters base64)
    if len(key) != 44:
        print("⚠️  KYC_ENCRYPTION_KEY appears to be invalid format")
        print(f"   Expected 44 characters, got {len(key)}")
        return False
    
    print("✅ KYC_ENCRYPTION_KEY properly configured")
    return True

def check_encryption_usage():
    """Check that encryption is properly used in the codebase"""
    print("🔍 Checking encryption usage patterns...")
    
    backend_dir = Path(__file__).parent.parent
    kyc_file = backend_dir / "blueprints" / "internal_kyc.py"
    
    if not kyc_file.exists():
        print("❌ Internal KYC blueprint not found")
        return False
    
    with open(kyc_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for proper encryption patterns
    required_patterns = [
        r'os\.environ\.get\(["\']KYC_ENCRYPTION_KEY["\']',  # Environment variable usage
        r'def encrypt_sensitive_data\(',  # Encryption function
        r'def decrypt_sensitive_data\(',  # Decryption function
        r'Fernet\(get_encryption_key\(\)\)',  # Proper key usage
    ]
    
    missing_patterns = []
    for pattern in required_patterns:
        if not re.search(pattern, content):
            missing_patterns.append(pattern)
    
    if missing_patterns:
        print("❌ Missing required encryption patterns:")
        for pattern in missing_patterns:
            print(f"  - {pattern}")
        return False
    
    print("✅ Encryption usage patterns are correct")
    return True

def generate_secure_key():
    """Generate a secure encryption key for production use"""
    print("🔑 Generating secure encryption key...")
    
    try:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        
        print("✅ Secure encryption key generated:")
        print(f"KYC_ENCRYPTION_KEY={key.decode()}")
        print()
        print("🚨 CRITICAL SECURITY INSTRUCTIONS:")
        print("1. Add this key to your .env file")
        print("2. NEVER commit this key to version control")
        print("3. Store this key securely - if lost, encrypted data becomes unreadable")
        print("4. Use different keys for development and production")
        print("5. Backup this key in a secure location")
        
        return True
    except ImportError:
        print("❌ cryptography package not installed")
        print("   Run: pip install cryptography")
        return False

def main():
    """Main security verification function"""
    print("=" * 60)
    print("🔒 FiCore Internal KYC Security Verification")
    print("=" * 60)
    print()
    
    all_checks_passed = True
    
    # Check 1: No hardcoded keys
    if not check_hardcoded_keys():
        all_checks_passed = False
    print()
    
    # Check 2: Environment configuration
    env_configured = check_environment_key()
    if not env_configured:
        all_checks_passed = False
    print()
    
    # Check 3: Encryption usage
    if not check_encryption_usage():
        all_checks_passed = False
    print()
    
    # Generate key if needed
    if not env_configured:
        print("🔧 Generating encryption key for you...")
        generate_secure_key()
        print()
    
    # Final result
    print("=" * 60)
    if all_checks_passed:
        print("✅ ALL SECURITY CHECKS PASSED")
        print("🔒 Your PII encryption is properly secured!")
    else:
        print("❌ SECURITY ISSUES DETECTED")
        print("🚨 Please fix the issues above before deploying to production")
    print("=" * 60)
    
    return all_checks_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)