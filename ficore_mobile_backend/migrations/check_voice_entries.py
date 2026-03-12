"""
Check voice entry metadata structure
"""

from pymongo import MongoClient
import os

def check_voice_entries():
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/ficore')
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    print("Checking voice entry metadata structure...")
    print("=" * 80)
    
    # Check incomes with metadata
    print("\n1. Sample incomes with metadata:")
    incomes_with_metadata = db.incomes.find({'metadata': {'$exists': True, '$ne': {}}}).limit(5)
    for income in incomes_with_metadata:
        print(f"\nIncome ID: {income.get('_id')}")
        print(f"  Amount: {income.get('amount')}")
        print(f"  Metadata: {income.get('metadata')}")
        print(f"  Source Type: {income.get('sourceType', 'NOT SET')}")
    
    # Check expenses with metadata
    print("\n2. Sample expenses with metadata:")
    expenses_with_metadata = db.expenses.find({'metadata': {'$exists': True, '$ne': {}}}).limit(5)
    for expense in expenses_with_metadata:
        print(f"\nExpense ID: {expense.get('_id')}")
        print(f"  Amount: {expense.get('amount')}")
        print(f"  Metadata: {expense.get('metadata')}")
        print(f"  Source Type: {expense.get('sourceType', 'NOT SET')}")
    
    # Count entries with metadata.source
    print("\n3. Counts:")
    print(f"  Incomes with metadata.source: {db.incomes.count_documents({'metadata.source': {'$exists': True}})}")
    print(f"  Expenses with metadata.source: {db.expenses.count_documents({'metadata.source': {'$exists': True}})}")
    
    # Check for any field that might indicate voice
    print("\n4. Checking for voice indicators:")
    voice_indicators = ['voice', 'Voice', 'VOICE', 'voice_report', 'voice_entry']
    for indicator in voice_indicators:
        income_count = db.incomes.count_documents({'metadata.source': indicator})
        expense_count = db.expenses.count_documents({'metadata.source': indicator})
        if income_count > 0 or expense_count > 0:
            print(f"  '{indicator}': incomes={income_count}, expenses={expense_count}")
    
    print("\n" + "=" * 80)
    client.close()

if __name__ == '__main__':
    check_voice_entries()
