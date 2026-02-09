"""
Check Income Status - Debug Script
Shows the status of all income entries for a specific user
"""

from pymongo import MongoClient
from bson import ObjectId

# Direct MongoDB URI - PRODUCTION DATABASE
MONGO_URI = "mongodb+srv://ficoreafrica_db_user:ScSbMkRwkauvTPyx@cluster0.53rbo1f.mongodb.net/ficore_africa?retryWrites=true&w=majority&readPreference=primary&tlsAllowInvalidCertificates=true"

# User ID from logs: 68e11e3bd594fe6a85546181
USER_ID = "68e11e3bd594fe6a85546181"

def check_incomes():
    print("Connecting to MongoDB...")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.server_info()
    print("✅ Connected!\n")
    
    db = client.get_default_database()
    
    print("=" * 80)
    print(f"INCOME ENTRIES FOR USER: {USER_ID}")
    print("=" * 80)
    
    # Get all incomes for this user
    incomes = list(db.incomes.find({'userId': ObjectId(USER_ID)}).sort('dateReceived', -1))
    
    print(f"\nTotal incomes found: {len(incomes)}\n")
    
    # Group by status
    by_status = {}
    for income in incomes:
        status = income.get('status', 'NO_STATUS')
        if status not in by_status:
            by_status[status] = []
        by_status[status].append(income)
    
    # Print summary
    print("STATUS BREAKDOWN:")
    print("-" * 80)
    for status, entries in by_status.items():
        print(f"  {status}: {len(entries)} entries")
    
    # Print details for each status
    for status, entries in by_status.items():
        print(f"\n\n{status} ENTRIES ({len(entries)}):")
        print("=" * 80)
        for income in entries[:5]:  # Show first 5 of each status
            print(f"  ID: {income['_id']}")
            print(f"  Source: {income.get('source', 'N/A')}")
            print(f"  Amount: ₦{income.get('amount', 0):,.2f}")
            print(f"  Date: {income.get('dateReceived', 'N/A')}")
            print(f"  Status: {income.get('status', 'NO_STATUS')}")
            print(f"  IsDeleted: {income.get('isDeleted', False)}")
            print(f"  Version: {income.get('version', 'N/A')}")
            if income.get('originalEntryId'):
                print(f"  OriginalEntryId: {income.get('originalEntryId')}")
            print("-" * 80)
        
        if len(entries) > 5:
            print(f"  ... and {len(entries) - 5} more")
    
    client.close()

if __name__ == '__main__':
    check_incomes()
