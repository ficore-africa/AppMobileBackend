"""
Cleanup Expired Quick Pay Transactions
Cron Job: Run every 5 minutes

Marks Quick Pay transactions as EXPIRED if:
1. Status is PENDING_PAYMENT
2. expiresAt timestamp has passed
3. No payment received

This keeps the vas_transactions collection clean and prevents
users from seeing "Pending" transactions forever in the UI.
"""

from datetime import datetime
from pymongo import MongoClient
import os

def cleanup_expired_quick_pay():
    """Mark expired Quick Pay transactions as EXPIRED"""
    try:
        # Connect to MongoDB
        mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore')
        client = MongoClient(mongo_uri)
        db = client.get_database()
        
        # Find expired Quick Pay transactions
        expired_txns = db.vas_transactions.find({
            'status': 'PENDING_PAYMENT',
            'paymentMethod': 'QUICK_PAY',
            'expiresAt': {'$lt': datetime.utcnow()}
        })
        
        expired_count = 0
        for txn in expired_txns:
            # Mark as EXPIRED
            db.vas_transactions.update_one(
                {'_id': txn['_id']},
                {
                    '$set': {
                        'status': 'EXPIRED',
                        'errorMessage': 'Payment window expired',
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            expired_count += 1
            print(f'✅ Marked transaction {txn["transactionReference"]} as EXPIRED')
        
        if expired_count > 0:
            print(f'✅ Cleanup complete: {expired_count} transactions marked as EXPIRED')
        else:
            print('✅ No expired transactions found')
        
        client.close()
        
    except Exception as e:
        print(f'❌ Error cleaning up expired transactions: {str(e)}')

if __name__ == '__main__':
    cleanup_expired_quick_pay()
