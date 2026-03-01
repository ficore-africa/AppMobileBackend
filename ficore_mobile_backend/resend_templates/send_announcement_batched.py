"""
Send announcements in batches to stay within Resend free tier (100 emails/day)
"""

from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to MongoDB
MONGO_URI = os.getenv('MONGO_URI')
client = MongoClient(MONGO_URI)
db = client['ficore_mobile_app']

def get_users_to_send(batch_size=100, skip=0):
    """
    Get users in batches
    
    Args:
        batch_size: Number of users per batch (default 100 for free tier)
        skip: Number of users to skip (for pagination)
    
    Returns:
        List of user emails
    """
    users = list(db.users.find(
        {'resendContactId': {'$exists': True}},
        {'email': 1, '_id': 0}
    ).skip(skip).limit(batch_size))
    
    return [user['email'] for user in users]

def mark_batch_sent(batch_number, user_count):
    """
    Log which batch was sent
    """
    log_entry = {
        'batchNumber': batch_number,
        'userCount': user_count,
        'sentAt': datetime.utcnow(),
        'status': 'sent'
    }
    db.announcement_batch_logs.insert_one(log_entry)
    print(f'✅ Logged batch {batch_number}: {user_count} users')

def get_last_batch_sent():
    """
    Get the last batch number that was sent
    """
    last_batch = db.announcement_batch_logs.find_one(
        sort=[('batchNumber', -1)]
    )
    
    if last_batch:
        return last_batch['batchNumber']
    return 0

if __name__ == '__main__':
    # Get total user count
    total_users = db.users.count_documents({'resendContactId': {'$exists': True}})
    print(f'📊 Total users: {total_users}')
    
    # Get last batch sent
    last_batch = get_last_batch_sent()
    print(f'📝 Last batch sent: {last_batch}')
    
    # Calculate next batch
    next_batch = last_batch + 1
    skip = last_batch * 100
    
    # Get users for next batch
    users = get_users_to_send(batch_size=100, skip=skip)
    
    if not users:
        print('✅ All users have been sent announcements!')
    else:
        print(f'\n📧 Batch {next_batch}:')
        print(f'   Users: {len(users)}')
        print(f'   Emails: {", ".join(users[:5])}...')
        print(f'\n⚠️  MANUAL ACTION REQUIRED:')
        print(f'   1. Go to admin panel: https://mobilebackend.ficoreafrica.com/admin/announcements_manager.html')
        print(f'   2. Create your announcement')
        print(f'   3. Click "Send Announcement" (it will send to all users)')
        print(f'   4. After sending, run this script again to mark batch as sent:')
        print(f'      python send_announcement_batched.py --mark-sent {next_batch} {len(users)}')

    client.close()
