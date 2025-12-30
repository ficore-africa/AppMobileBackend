from pymongo import MongoClient

try:
    client = MongoClient('mongodb://localhost:27017/')
    db = client['ficore_mobile']
    
    count = db.cancellation_requests.count_documents({})
    print(f"Cancellation requests count: {count}")
    
    if count > 0:
        print("\nSample request:")
        sample = db.cancellation_requests.find_one()
        print(sample)
    else:
        print("\nNo cancellation requests found in database")
        
except Exception as e:
    print(f"Error: {e}")
