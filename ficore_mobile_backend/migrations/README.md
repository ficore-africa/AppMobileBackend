# Database Migrations

This directory contains one-time database migration scripts that fix data inconsistencies or update schema.

## How Migrations Work

1. **Automatic on Deployment**: Migrations run automatically when the app starts (via `app.py`)
2. **Manual Execution**: You can also run migrations manually using the scripts below
3. **Idempotent**: Migrations can be run multiple times safely - they only fix what needs fixing

## Running Migrations

### Automatic (Recommended)
Migrations run automatically when you deploy to Render or start the app locally:
```bash
python app.py
```

### Manual Execution
If you need to run migrations manually:

```bash
# From ficore_mobile_backend directory
python run_migrations_manual.py
```

Or with a custom MongoDB URI:
```bash
python run_migrations_manual.py "mongodb+srv://user:pass@cluster.mongodb.net/db"
```

### Run Single Migration
To run a specific migration:
```bash
cd migrations
python fix_subscription_plan_field.py "mongodb+srv://..."
```

## Current Migrations

### 1. fix_subscription_plan_field.py
**Date:** December 2, 2025  
**Issue:** Admin grants were not setting the `plan` field in subscriptions collection  
**Fix:** Sets `plan` field from `user.subscriptionType` for all subscriptions with missing `plan`

**What it does:**
- Finds all subscriptions where `plan` is NULL or missing
- Gets the user's `subscriptionType` 
- Sets `subscriptions.plan = user.subscriptionType`
- Adds migration metadata for audit trail

**Safe to run multiple times:** Yes - only updates subscriptions that need fixing

## Creating New Migrations

1. Create a new Python file in `migrations/` directory
2. Implement a `run_migration(mongo_uri)` function
3. Add the migration to `run_migrations.py` migrations list
4. Test locally before deploying

Example template:
```python
def run_migration(mongo_uri=None):
    """Run the migration"""
    from pymongo import MongoClient
    import os
    
    if not mongo_uri:
        mongo_uri = os.environ.get('MONGODB_URI')
    
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    # Your migration logic here
    
    client.close()
    return True  # Return True on success

if __name__ == '__main__':
    import sys
    mongo_uri = sys.argv[1] if len(sys.argv) > 1 else None
    success = run_migration(mongo_uri)
    sys.exit(0 if success else 1)
```

## Troubleshooting

### Migration fails on startup
- Check MongoDB connection string
- Check migration logs in console
- App will still start even if migrations fail (non-fatal)

### Need to re-run a migration
- Migrations are idempotent - just run them again
- Or run manually: `python run_migrations_manual.py`

### Check if migration was applied
Look for `migrationApplied` and `migrationDate` fields in affected documents:
```javascript
db.subscriptions.findOne({migrationApplied: 'fix_subscription_plan_field'})
```
