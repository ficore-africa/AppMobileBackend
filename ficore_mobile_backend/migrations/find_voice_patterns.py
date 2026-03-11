"""
Try to identify voice entries by patterns
"""

from pymongo import MongoClient
import os
from datetime import datetime

def find_voice_patterns():
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/ficore')
    client = MongoClient(mongo_uri)
    db = client.get_database()
    
    print("Looking for voice entry patterns...")
    print("=" * 80)
    
    # Get your user ID (assuming you're the one who created voice entries)
    # Let's check recent entries
    print("\n1. Recent incomes (last 20):")
    recent_incomes = db.incomes.find().sort('createdAt', -1).limit(20)
    for income in recent_incomes:
        print(f"\nID: {income.get('_id')}")
        print(f"  Amount: {income.get('amount')}")
        print(f"  Source: {income.get('source')}")
        print(f"  Description: {income.get('description')}")
        print(f"  Category: {income.get('category')}")
        print(f"  Created: {income.get('createdAt')}")
        print(f"  Source Type: {income.get('sourceType', 'NOT SET')}")
    
    print("\n2. Recent expenses (last 20):")
    recent_expenses = db.expenses.find().sort('createdAt', -1).limit(20)
    for expense in recent_expenses:
        print(f"\nID: {expense.get('_id')}")
        print(f"  Amount: {expense.get('amount')}")
        print(f"  Description: {expense.get('description')}")
        print(f"  Category: {expense.get('category')}")
        print(f"  Created: {expense.get('createdAt')}")
        print(f"  Source Type: {expense.get('sourceType', 'NOT SET')}")
        print(f"  VAS Transaction: {expense.get('vasTransactionId', 'None')}")
    
    print("\n" + "=" * 80)
    client.close()

if __name__ == '__main__':
    find_voice_patterns()
