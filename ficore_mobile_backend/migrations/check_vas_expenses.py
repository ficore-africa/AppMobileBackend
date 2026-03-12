"""
Check existing VAS expenses in the database
"""

from pymongo import MongoClient
from datetime import datetime

def check():
    # Production MongoDB Atlas URI
    MONGO_URI = 'mongodb+srv://ficoreafrica_db_user:ScSbMkRwkauvTPyx@cluster0.53rbo1f.mongodb.net/ficore_africa?retryWrites=true&w=majority&readPreference=primary&tlsAllowInvalidCertificates=true'
    
    client = MongoClient(MONGO_URI)
    db = client['ficore_africa']
    
    print("\n" + "=" * 80)
    print("VAS EXPENSES CHECK")
    print("=" * 80)
    
    # Check for expenses with VAS tags
    vas_expenses = list(db.expenses.find({
        'tags': {'$in': ['VAS', 'Airtime', 'Data']}
    }).limit(10))
    
    print(f"\n📊 Found {len(vas_expenses)} VAS-tagged expenses (showing first 10)")
    
    for exp in vas_expenses:
        print(f"\n  ID: {exp.get('_id')}")
        print(f"  Amount: ₦{exp.get('amount', 0):,.2f}")
        print(f"  Category: {exp.get('category', 'N/A')}")
        print(f"  Tags: {exp.get('tags', [])}")
        print(f"  SourceType: {exp.get('sourceType', 'MISSING')}")
        print(f"  Description: {exp.get('description', 'N/A')[:50]}...")
        print(f"  Date: {exp.get('date', 'N/A')}")
    
    # Check for bill payment expenses
    bill_expenses = list(db.expenses.find({
        'metadata.source': 'vas_bill_payment'
    }).limit(10))
    
    print(f"\n💡 Found {len(bill_expenses)} VAS bill payment expenses (showing first 10)")
    
    for exp in bill_expenses:
        print(f"\n  ID: {exp.get('_id')}")
        print(f"  Amount: ₦{exp.get('amount', 0):,.2f}")
        print(f"  Title: {exp.get('title', 'N/A')}")
        print(f"  SourceType: {exp.get('sourceType', 'MISSING')}")
        print(f"  Bill Category: {exp.get('metadata', {}).get('billCategory', 'N/A')}")
        print(f"  Provider: {exp.get('metadata', {}).get('provider', 'N/A')}")
        print(f"  Date: {exp.get('date', 'N/A')}")
    
    # Check for expenses with VAS_TRANSACTION sourceType
    vas_transaction_expenses = list(db.expenses.find({
        'sourceType': 'VAS_TRANSACTION'
    }).limit(10))
    
    print(f"\n🔍 Found {len(vas_transaction_expenses)} expenses with 'VAS_TRANSACTION' sourceType")
    
    # Check for expenses missing sourceType
    missing_sourcetype = db.expenses.count_documents({
        'sourceType': {'$exists': False}
    })
    
    print(f"\n⚠️  Found {missing_sourcetype} expenses missing sourceType field")
    
    # Check total expenses
    total_expenses = db.expenses.count_documents({})
    print(f"\n📈 Total expenses in database: {total_expenses}")
    
    print("\n" + "=" * 80)
    print("CHECK COMPLETE")
    print("=" * 80 + "\n")
    
    client.close()

if __name__ == '__main__':
    check()
