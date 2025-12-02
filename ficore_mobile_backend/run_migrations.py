"""
Migration Runner - Runs all pending migrations on app startup
Each migration checks if it already ran to prevent duplicate execution
"""

import os
import sys
from datetime import datetime

# Add migrations directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'migrations'))

def run_all_migrations(mongo_uri=None):
    """Run all pending migrations (one-time only, checks flags)"""
    
    print("\n" + "=" * 80)
    print("🔄 RUNNING DATABASE MIGRATIONS")
    print("=" * 80)
    
    migrations = [
        ('fix_subscription_plan_field', 'Fix missing plan field in subscriptions'),
    ]
    
    success_count = 0
    
    for migration_name, description in migrations:
        try:
            print(f"\n📦 {migration_name}")
            print(f"   {description}")
            
            # Import and run migration (it checks if already ran)
            migration_module = __import__(migration_name)
            result = migration_module.run_migration(mongo_uri)
            
            if result:
                success_count += 1
                
        except Exception as e:
            print(f"⚠️  Migration error (non-fatal): {str(e)}")
    
    print("\n" + "=" * 80)
    print(f"✅ Migrations complete ({success_count}/{len(migrations)} ran)")
    print("=" * 80 + "\n")
    
    return True  # Always return True to not block app startup

if __name__ == '__main__':
    mongo_uri = os.environ.get('MONGODB_URI') or os.environ.get('MONGO_URI')
    run_all_migrations(mongo_uri)
    sys.exit(0)
