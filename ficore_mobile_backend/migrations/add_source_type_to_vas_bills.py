"""
Migration: Add sourceType to VAS Expenses (Bills, Airtime, Data)

This migration adds/updates the sourceType field for all VAS expenses:
1. Adds sourceType to VAS bill payment expenses (electricity, cable_tv, internet, water)
2. Updates generic 'VAS_TRANSACTION' to granular types ('vas_airtime', 'vas_data')

This is CRITICAL for offline protection - without it, users can accidentally delete
system-generated VAS expenses.

Date: February 18, 2026
Priority: HIGH
"""

from pymongo import MongoClient
from datetime import datetime

def migrate():
    # Production MongoDB Atlas URI
    MONGO_URI = 'mongodb+srv://ficoreafrica_db_user:ScSbMkRwkauvTPyx@cluster0.53rbo1f.mongodb.net/ficore_africa?retryWrites=true&w=majority&readPreference=primary&tlsAllowInvalidCertificates=true'
    
    client = MongoClient(MONGO_URI)
    db = client['ficore_africa']
    
    print("\n" + "=" * 80)
    print("MIGRATION: Add/Update sourceType for ALL VAS Expenses")
    print("=" * 80)
    
    # ==================== PART 1: Update Existing VAS Purchases ====================
    print("\n📦 PART 1: Updating existing VAS purchases (airtime/data)...")
    
    # 1. Update Airtime purchases (currently 'VAS_TRANSACTION' OR 'wallet_auto' → 'vas_airtime')
    airtime_result = db.expenses.update_many(
        {
            '$or': [
                {'sourceType': 'VAS_TRANSACTION', 'tags': 'Airtime'},
                {'sourceType': 'wallet_auto', 'tags': 'Airtime'}
            ]
        },
        {
            '$set': {
                'sourceType': 'vas_airtime',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"✅ Airtime expenses: {airtime_result.modified_count} updated (VAS_TRANSACTION/wallet_auto → vas_airtime)")
    
    # 2. Update Data purchases (currently 'VAS_TRANSACTION' OR 'wallet_auto' → 'vas_data')
    data_result = db.expenses.update_many(
        {
            '$or': [
                {'sourceType': 'VAS_TRANSACTION', 'tags': 'Data'},
                {'sourceType': 'wallet_auto', 'tags': 'Data'}
            ]
        },
        {
            '$set': {
                'sourceType': 'vas_data',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"✅ Data expenses: {data_result.modified_count} updated (VAS_TRANSACTION/wallet_auto → vas_data)")
    
    # 3. Catch any remaining 'VAS_TRANSACTION' (fallback)
    remaining_result = db.expenses.update_many(
        {
            'sourceType': 'VAS_TRANSACTION'
        },
        {
            '$set': {
                'sourceType': 'vas_other',  # Generic fallback
                'updatedAt': datetime.utcnow()
            }
        }
    )
    if remaining_result.modified_count > 0:
        print(f"⚠️  Other VAS expenses: {remaining_result.modified_count} updated (VAS_TRANSACTION → vas_other)")
    
    # ==================== PART 2: Add sourceType to Bill Payments ====================
    print("\n💡 PART 2: Adding sourceType to VAS bill payments...")
    
    # 4. Add sourceType to Electricity bills
    electricity_result = db.expenses.update_many(
        {
            'metadata.source': 'vas_bill_payment',
            'metadata.billCategory': 'electricity',
            'sourceType': {'$exists': False}  # Only update if missing
        },
        {
            '$set': {
                'sourceType': 'vas_electricity',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"✅ Electricity bills: {electricity_result.modified_count} updated")
    
    # 5. Add sourceType to Cable TV bills
    cable_result = db.expenses.update_many(
        {
            'metadata.source': 'vas_bill_payment',
            'metadata.billCategory': 'cable_tv',
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'vas_cable_tv',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"✅ Cable TV bills: {cable_result.modified_count} updated")
    
    # 6. Add sourceType to Internet bills
    internet_result = db.expenses.update_many(
        {
            'metadata.source': 'vas_bill_payment',
            'metadata.billCategory': 'internet',
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'vas_internet',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"✅ Internet bills: {internet_result.modified_count} updated")
    
    # 7. Add sourceType to Water bills
    water_result = db.expenses.update_many(
        {
            'metadata.source': 'vas_bill_payment',
            'metadata.billCategory': 'water',
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'vas_water',
                'updatedAt': datetime.utcnow()
            }
        }
    )
    print(f"✅ Water bills: {water_result.modified_count} updated")
    
    # 8. Handle any other bill categories (generic fallback)
    other_result = db.expenses.update_many(
        {
            'metadata.source': 'vas_bill_payment',
            'sourceType': {'$exists': False}
        },
        {
            '$set': {
                'sourceType': 'vas_bill',  # Generic for unknown categories
                'updatedAt': datetime.utcnow()
            }
        }
    )
    if other_result.modified_count > 0:
        print(f"✅ Other bills: {other_result.modified_count} updated")
    
    # ==================== SUMMARY ====================
    total = (airtime_result.modified_count + 
             data_result.modified_count + 
             remaining_result.modified_count +
             electricity_result.modified_count + 
             cable_result.modified_count + 
             internet_result.modified_count + 
             water_result.modified_count + 
             other_result.modified_count)
    
    print("\n" + "=" * 80)
    print(f"✅ MIGRATION COMPLETE: {total} VAS expenses updated")
    print(f"   - Airtime: {airtime_result.modified_count}")
    print(f"   - Data: {data_result.modified_count}")
    print(f"   - Electricity: {electricity_result.modified_count}")
    print(f"   - Cable TV: {cable_result.modified_count}")
    print(f"   - Internet: {internet_result.modified_count}")
    print(f"   - Water: {water_result.modified_count}")
    if remaining_result.modified_count > 0 or other_result.modified_count > 0:
        print(f"   - Other: {remaining_result.modified_count + other_result.modified_count}")
    print("=" * 80 + "\n")
    
    client.close()

if __name__ == '__main__':
    migrate()
