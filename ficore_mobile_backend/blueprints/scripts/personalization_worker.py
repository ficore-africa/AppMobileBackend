"""
Simple personalization worker.

Run periodically (cron / systemd timer) to compute weekly personalization scores
and store them in the `personalization` collection.

Environment variables:
- MONGO_URI (e.g. mongodb://localhost:27017/ficore_mobile)

This script is intentionally simple and safe for production: it aggregates
interactions and writes a small summary per user.
"""
import os
from pymongo import MongoClient
from datetime import datetime, timedelta


def main():
    mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
    client = MongoClient(mongo_uri)
    db = client.get_default_database()

    # Compute interactions for the last 7 days
    since = datetime.utcnow() - timedelta(days=7)

    pipeline = [
        {'$match': {'ts': {'$gte': since}}},
        {'$group': {'_id': {'userId': '$userId', 'reminderId': '$reminderId'}, 'count': {'$sum': 1}}},
        {'$group': {'_id': '$_id.userId', 'reminders': {'$push': {'reminderId': '$_id.reminderId', 'count': '$count'}}}},
    ]

    results = db.reminder_interactions.aggregate(pipeline)
    for row in results:
        user_id = row['_id']
        reminders = row.get('reminders', [])

        # Sort reminders by count desc and keep top 10
        reminders_sorted = sorted(reminders, key=lambda r: r.get('count', 0), reverse=True)[:10]

        doc = {
            'userId': user_id,
            'computedAt': datetime.utcnow(),
            'topReminders': reminders_sorted
        }

        # Upsert into personalization collection
        db.personalization.update_one({'userId': user_id}, {'$set': doc}, upsert=True)
        print(f'Updated personalization for {user_id}')


if __name__ == '__main__':
    main()
