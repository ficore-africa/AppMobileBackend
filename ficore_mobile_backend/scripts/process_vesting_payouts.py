"""
Referral System - Vesting Period Automation
Created: February 4, 2026
Purpose: Process PENDING payouts that have completed their 7-day vesting period

Run this script daily via cron job:
0 2 * * * cd /path/to/ficore_mobile_backend && python scripts/process_vesting_payouts.py
"""
import os
import sys
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def process_vesting_payouts():
    """
    Find all PENDING payouts where vesting period has ended (7 days).
    Move them to WITHDRAWABLE status and update user balances.
    """
    try:
        # Connect to MongoDB
        mongo_uri = os.getenv('MONGO_URI')
        if not mongo_uri:
            print('ERROR: MONGO_URI environment variable not set')
            return False
        
        client = MongoClient(mongo_uri)
        db = client.ficore_db
        
        print('=' * 70)
        print('REFERRAL SYSTEM - VESTING PERIOD AUTOMATION')
        print('=' * 70)
        print(f'Started at: {datetime.utcnow().isoformat()}')
        print()
        
        # Find all PENDING payouts where vesting period has ended
        pending_payouts = list(db.referral_payouts.find({
            'status': 'PENDING',
            'vestingEndDate': {'$lte': datetime.utcnow()}
        }))
        
        if not pending_payouts:
            print('✅ No payouts ready for vesting')
            print()
            print('=' * 70)
            return True
        
        print(f'📊 Found {len(pending_payouts)} payouts ready for vesting')
        print()
        
        processed_count = 0
        total_amount = 0.0
        errors = []
        
        for payout in pending_payouts:
            try:
                payout_id = payout['_id']
                referrer_id = payout['referrerId']
                amount = payout['amount']
                payout_type = payout['type']
                
                print(f'Processing payout {payout_id}:')
                print(f'  Referrer: {referrer_id}')
                print(f'  Amount: ₦{amount:,.2f}')
                print(f'  Type: {payout_type}')
                
                # Move from PENDING to WITHDRAWABLE
                result = db.referral_payouts.update_one(
                    {'_id': payout_id},
                    {
                        '$set': {
                            'status': 'WITHDRAWABLE',
                            'vestedAt': datetime.utcnow(),
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                
                if result.modified_count == 0:
                    print(f'  ⚠️  WARNING: Payout not updated (may have been processed already)')
                    continue
                
                # Update referrer's balances (pending → withdrawable)
                user_result = db.users.update_one(
                    {'_id': referrer_id},
                    {
                        '$inc': {
                            'pendingCommissionBalance': -amount,
                            'withdrawableCommissionBalance': amount
                        }
                    }
                )
                
                if user_result.modified_count == 0:
                    print(f'  ⚠️  WARNING: User balance not updated (user may not exist)')
                    errors.append(f'User {referrer_id} not found for payout {payout_id}')
                    continue
                
                # Update corporate_revenue status
                db.corporate_revenue.update_one(
                    {
                        'relatedTransaction': payout.get('sourceTransaction'),
                        'type': 'REFERRAL_PAYOUT',
                        'userId': referrer_id
                    },
                    {
                        '$set': {
                            'status': 'WITHDRAWABLE',
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                
                print(f'  ✅ Vested: ₦{amount:,.2f} now WITHDRAWABLE')
                print()
                
                processed_count += 1
                total_amount += amount
                
            except Exception as e:
                error_msg = f'Error processing payout {payout.get("_id")}: {str(e)}'
                print(f'  ❌ {error_msg}')
                print()
                errors.append(error_msg)
                continue
        
        # Summary
        print('=' * 70)
        print('SUMMARY')
        print('=' * 70)
        print(f'Total payouts processed: {processed_count}/{len(pending_payouts)}')
        print(f'Total amount vested: ₦{total_amount:,.2f}')
        
        if errors:
            print(f'\nErrors encountered: {len(errors)}')
            for error in errors:
                print(f'  - {error}')
        
        print()
        print(f'Completed at: {datetime.utcnow().isoformat()}')
        print('=' * 70)
        
        client.close()
        return True
        
    except Exception as e:
        print(f'❌ FATAL ERROR: {str(e)}')
        return False

if __name__ == '__main__':
    success = process_vesting_payouts()
    sys.exit(0 if success else 1)
