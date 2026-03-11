#!/usr/bin/env python3
"""
Setup FiCore Silent Auditor Cron Jobs
Configures automated monitoring with WhatsApp alerts

Author: Hassan Ahmad (Founder, FiCore Africa)
Created: March 11, 2026
"""

import os
import subprocess
import sys
from pathlib import Path

def setup_cron_jobs():
    """
    Setup cron jobs for FiCore Silent Auditor
    """
    print("🔧 Setting up FiCore Silent Auditor cron jobs...")
    
    # Get current directory
    current_dir = Path(__file__).parent.parent.absolute()
    auditor_script = current_dir / "utils" / "whatsapp_auditor.py"
    
    # Cron job entries
    cron_entries = [
        # Every 4 hours - Full audit
        f"0 */4 * * * cd {current_dir} && /usr/bin/python3 {auditor_script} >> /var/log/ficore_auditor.log 2>&1",
        
        # Every hour during business hours (8 AM - 8 PM) - Quick check
        f"0 8-20 * * * cd {current_dir} && /usr/bin/python3 {auditor_script} --quick >> /var/log/ficore_auditor.log 2>&1",
        
        # Daily at 8 AM - Full audit + summary
        f"0 8 * * * cd {current_dir} && /usr/bin/python3 {auditor_script} --daily >> /var/log/ficore_auditor.log 2>&1"
    ]
    
    # Create temporary cron file
    temp_cron_file = "/tmp/ficore_auditor_cron"
    
    try:
        # Get existing cron jobs
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        existing_cron = result.stdout if result.returncode == 0 else ""
        
        # Add new cron jobs (avoid duplicates)
        new_cron = existing_cron
        for entry in cron_entries:
            if "whatsapp_auditor.py" not in entry or entry not in existing_cron:
                new_cron += entry + "\n"
        
        # Write to temporary file
        with open(temp_cron_file, 'w') as f:
            f.write(new_cron)
        
        # Install new cron jobs
        subprocess.run(['crontab', temp_cron_file], check=True)
        
        # Clean up
        os.remove(temp_cron_file)
        
        print("✅ Cron jobs installed successfully:")
        for entry in cron_entries:
            print(f"  • {entry}")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to setup cron jobs: {e}")
        return False
    except Exception as e:
        print(f"❌ Error setting up cron jobs: {e}")
        return False

def setup_log_rotation():
    """
    Setup log rotation for auditor logs
    """
    print("📝 Setting up log rotation...")
    
    logrotate_config = """
/var/log/ficore_auditor.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 644 root root
}
"""
    
    try:
        # Create logrotate configuration
        with open('/etc/logrotate.d/ficore_auditor', 'w') as f:
            f.write(logrotate_config)
        
        print("✅ Log rotation configured")
        return True
        
    except PermissionError:
        print("⚠️  Need sudo access to setup log rotation")
        print("   Run: sudo python3 setup_auditor_cron.py")
        return False
    except Exception as e:
        print(f"❌ Failed to setup log rotation: {e}")
        return False

def create_environment_template():
    """
    Create environment template for CallMeBot configuration
    """
    print("🔑 Creating environment template...")
    
    env_template = """
# FiCore Silent Auditor Configuration
# Add these to your environment variables

# CallMeBot WhatsApp API Configuration
# 1. Add +34 644 20 47 56 to your WhatsApp contacts (CallMeBot)
# 2. Send message "I allow callmebot to send me messages" to that contact
# 3. Bot will reply with your API key
# 4. Set the API key below:
CALLMEBOT_API_KEY=your_api_key_here

# Your WhatsApp phone number (with country code, no + sign)
HASSAN_PHONE=2348012345678

# MongoDB connection (should already be set)
MONGO_URI=your_mongo_connection_string
"""
    
    try:
        env_file = Path(__file__).parent.parent / ".env.auditor.template"
        with open(env_file, 'w') as f:
            f.write(env_template)
        
        print(f"✅ Environment template created: {env_file}")
        print("\n📋 Next steps:")
        print("1. Add +34 644 20 47 56 to WhatsApp contacts (CallMeBot)")
        print("2. Send 'I allow callmebot to send me messages' to that contact")
        print("3. Copy API key from bot reply")
        print("4. Set CALLMEBOT_API_KEY in your environment")
        print("5. Update HASSAN_PHONE with your actual number")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to create environment template: {e}")
        return False

def test_auditor():
    """
    Test the auditor script
    """
    print("🧪 Testing auditor script...")
    
    current_dir = Path(__file__).parent.parent.absolute()
    auditor_script = current_dir / "utils" / "whatsapp_auditor.py"
    
    try:
        # Run auditor in test mode
        result = subprocess.run([
            sys.executable, str(auditor_script)
        ], capture_output=True, text=True, cwd=current_dir)
        
        print("📊 Auditor output:")
        print(result.stdout)
        
        if result.stderr:
            print("⚠️  Auditor warnings:")
            print(result.stderr)
        
        if result.returncode == 0:
            print("✅ Auditor test passed")
        else:
            print("❌ Auditor test failed")
        
        return result.returncode == 0
        
    except Exception as e:
        print(f"❌ Failed to test auditor: {e}")
        return False

def main():
    """
    Main setup function
    """
    print("🚀 FiCore Silent Auditor Setup")
    print("=" * 50)
    
    success = True
    
    # Create environment template
    if not create_environment_template():
        success = False
    
    print()
    
    # Test auditor script
    if not test_auditor():
        success = False
    
    print()
    
    # Setup cron jobs
    if not setup_cron_jobs():
        success = False
    
    print()
    
    # Setup log rotation (optional, needs sudo)
    setup_log_rotation()
    
    print()
    print("=" * 50)
    
    if success:
        print("✅ FiCore Silent Auditor setup complete!")
        print("\n🔔 Alert Schedule:")
        print("• Every 4 hours: Full integrity audit")
        print("• Business hours: Quick checks")
        print("• Daily 8 AM: Summary report")
        print("\n📱 WhatsApp alerts will be sent only when issues detected")
    else:
        print("❌ Setup completed with warnings")
        print("   Check error messages above and retry")
    
    return success

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)