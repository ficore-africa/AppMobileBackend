"""
VAS Reconciliation Scanner

Automatically scans for transactions that need reconciliation:
1. FAILED transactions older than 5 minutes WITH specific suspicious patterns
2. PENDING transactions older than 10 minutes (stuck transactions)
3. Transactions with Provider: None but might have succeeded

SMART FILTERING: Only flags transactions with HIGH probability of being ghost successes:
- Provider succeeded but backend crashed
- Plan mismatch scenarios
- Provider: None (never reached provider, but might have succeeded via retry)

Does NOT flag:
- Clear provider failures (e.g., "insufficient balance", "invalid number")
- Transactions where provider explicitly said "failed"
"""

from datetime import datetime, timedelta
from bson import ObjectId
import sys

# Import standardized reconciliation marker
from utils.reconciliation_marker import (
    mark_suspicious_failure_for_reconciliation,
    mark_stuck_pending_for_reconciliation,
    mark_provider_none_for_reconciliation
)

def is_suspicious_failure(txn):
    """
    Determine if a FAILED transaction is suspicious (might be ghost success)
    
    Returns: (is_suspicious: bool, reason: str)
    """
    failure_reason = txn.get('failureReason', '').lower()
    provider = txn.get('provider')
    
    # Clear failures - NOT suspicious
    clear_failures = [
        'insufficient balance',
        'insufficient wallet balance',
        'insufficient funds',
        'invalid phone number',
        'invalid number',
        'network not active',
        'network not found',
        'invalid request',
        'invalid data purchase request',
        'user cancelled',
        'timeout',
        'connection error'
    ]
    
    for clear_fail in clear_failures:
        if clear_fail in failure_reason:
            return (False, f"Clear failure: {clear_fail}")
    
    # Suspicious patterns - HIGH probability of ghost success
    suspicious_patterns = [
        'plan mismatch',
        'price mismatch',
        'successful payment',  # Monnify webhook says success but app thinks failed
        'provider succeeded',
        'delivered different',
        'mongo is not defined',  # Our bug!
        'name error',
        'crash',
        'exception'
    ]
    
    for pattern in suspicious_patterns:
        if pattern in failure_reason:
            return (True, f"Suspicious pattern: {pattern}")
    
    # Provider: None is VERY suspicious (backend crashed before recording provider)
    if provider is None or provider == 'None':
        return (True, "Provider: None - backend crashed before recording provider response")
    
    # Generic "Provider did not confirm" is suspicious if provider is set
    if 'provider did not confirm' in failure_reason and provider:
        return (True, "Provider set but did not confirm - might have succeeded")
    
    # If we get here, it's probably a legitimate failure
    return (False, "Appears to be legitimate failure")

def scan_for_reconciliation_candidates(mongo_db, dry_run=True):
    """
    Scan for transactions that need reconciliation review
    
    Args:
        mongo_db: MongoDB database instance
        dry_run: If True, only report findings without marking transactions
    
    Returns:
        dict with scan results
    """
    print("🔍 VAS RECONCILIATION SCANNER")
    print("=" * 60)
    
    results = {
        'failed_candidates': [],
        'pending_candidates': [],
        'provider_none_candidates': [],
        'total_marked': 0,
        'total_found': 0
    }
    
    try:
        # 1. Find FAILED transactions older than 5 minutes
        five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
        
        print(f"\n1️⃣ SCANNING FAILED TRANSACTIONS (older than 5 minutes)...")
        
        failed_txns = list(mongo_db.vas_transactions.find({
            'status': 'FAILED',
            'createdAt': {'$lt': five_minutes_ago},
            'needsReconciliation': {'$ne': True}  # Not already marked
        }).sort('createdAt', -1).limit(100))
        
        print(f"   Found {len(failed_txns)} FAILED transactions")
        
        # Filter for suspicious failures only
        suspicious_failed = []
        for txn in failed_txns:
            is_suspicious, reason = is_suspicious_failure(txn)
            if is_suspicious:
                suspicious_failed.append(txn)
                results['failed_candidates'].append({
                    'transaction_id': str(txn['_id']),
                    'user_id': str(txn['userId']),
                    'type': txn.get('type'),
                    'amount': txn.get('amount'),
                    'provider': txn.get('provider'),
                    'phone': txn.get('phoneNumber'),
                    'created_at': txn.get('createdAt'),
                    'failure_reason': txn.get('failureReason', 'Unknown'),
                    'age_minutes': (datetime.utcnow() - txn.get('createdAt')).total_seconds() / 60,
                    'suspicious_reason': reason
                })
        
        print(f"   Suspicious (potential ghost successes): {len(suspicious_failed)}")
        print(f"   Legitimate failures (ignored): {len(failed_txns) - len(suspicious_failed)}")
        
        for txn in suspicious_failed:
            if not dry_run:
                # Use standardized marker
                mark_suspicious_failure_for_reconciliation(
                    mongo_db=mongo_db,
                    transaction_id=txn['_id'],
                    suspicious_reason=is_suspicious_failure(txn)[1]
                )
                results['total_marked'] += 1
        
        # 2. Find PENDING transactions older than 10 minutes (stuck)
        ten_minutes_ago = datetime.utcnow() - timedelta(minutes=10)
        
        print(f"\n2️⃣ SCANNING PENDING TRANSACTIONS (older than 10 minutes)...")
        
        pending_txns = list(mongo_db.vas_transactions.find({
            'status': 'PENDING',
            'createdAt': {'$lt': ten_minutes_ago},
            'needsReconciliation': {'$ne': True}
        }).sort('createdAt', -1).limit(100))
        
        print(f"   Found {len(pending_txns)} PENDING transactions")
        
        for txn in pending_txns:
            results['pending_candidates'].append({
                'transaction_id': str(txn['_id']),
                'user_id': str(txn['userId']),
                'type': txn.get('type'),
                'amount': txn.get('amount'),
                'provider': txn.get('provider'),
                'phone': txn.get('phoneNumber'),
                'created_at': txn.get('createdAt'),
                'age_minutes': (datetime.utcnow() - txn.get('createdAt')).total_seconds() / 60
            })
            
            if not dry_run:
                # Use standardized marker
                stuck_duration = (datetime.utcnow() - txn.get('createdAt')).total_seconds() / 60
                mark_stuck_pending_for_reconciliation(
                    mongo_db=mongo_db,
                    transaction_id=txn['_id'],
                    stuck_duration_minutes=stuck_duration
                )
                results['total_marked'] += 1
        
        # 3. Find transactions with Provider: None (never reached provider) - ONLY recent ones
        print(f"\n3️⃣ SCANNING TRANSACTIONS WITH PROVIDER: NONE (last 24 hours only)...")
        
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        
        provider_none_txns = list(mongo_db.vas_transactions.find({
            'provider': None,
            'status': {'$in': ['FAILED', 'PENDING']},
            'createdAt': {'$gte': twenty_four_hours_ago, '$lt': five_minutes_ago},  # Last 24 hours only
            'needsReconciliation': {'$ne': True}
        }).sort('createdAt', -1).limit(50))
        
        print(f"   Found {len(provider_none_txns)} transactions with Provider: None")
        
        for txn in provider_none_txns:
            results['provider_none_candidates'].append({
                'transaction_id': str(txn['_id']),
                'user_id': str(txn['userId']),
                'type': txn.get('type'),
                'amount': txn.get('amount'),
                'status': txn.get('status'),
                'phone': txn.get('phoneNumber'),
                'created_at': txn.get('createdAt'),
                'age_minutes': (datetime.utcnow() - txn.get('createdAt')).total_seconds() / 60
            })
            
            if not dry_run:
                # Use standardized marker
                mark_provider_none_for_reconciliation(
                    mongo_db=mongo_db,
                    transaction_id=txn['_id']
                )
                results['total_marked'] += 1
        
        results['total_found'] = len(suspicious_failed) + len(pending_txns) + len(provider_none_txns)
        
        # Summary
        print(f"\n📊 SCAN SUMMARY:")
        print(f"   FAILED transactions (total scanned): {len(failed_txns)}")
        print(f"   FAILED transactions (suspicious): {len(suspicious_failed)}")
        print(f"   PENDING transactions: {len(pending_txns)}")
        print(f"   Provider: None transactions (last 24h): {len(provider_none_txns)}")
        print(f"   Total needing reconciliation: {results['total_found']}")
        
        if dry_run:
            print(f"\n⚠️  DRY RUN MODE - No transactions marked")
            print(f"   Run with dry_run=False to mark transactions")
        else:
            print(f"\n✅ MARKED {results['total_marked']} transactions for reconciliation")
        
        return results
        
    except Exception as e:
        print(f"❌ Error during scan: {e}")
        import traceback
        traceback.print_exc()
        return results


def schedule_reconciliation_scan(mongo_db):
    """
    This should be called periodically (e.g., every 15 minutes) via cron job or scheduler
    """
    print(f"\n🕐 SCHEDULED RECONCILIATION SCAN - {datetime.utcnow()}")
    results = scan_for_reconciliation_candidates(mongo_db, dry_run=False)
    
    if results['total_marked'] > 0:
        print(f"\n🚨 ALERT: {results['total_marked']} transactions marked for reconciliation")
        print(f"   Admin should review reconciliation dashboard")
    else:
        print(f"\n✅ No new reconciliation candidates found")
    
    return results


if __name__ == "__main__":
    # For testing
    import os
    from pymongo import MongoClient
    
    MONGO_URI = os.environ.get('MONGO_URI', 'true')
    
    client = MongoClient(MONGO_URI)
    db = client['ficore_africa']
    
    # Run scan in dry-run mode
    print("Running in DRY RUN mode...")
    results = scan_for_reconciliation_candidates(db, dry_run=True)
    
    print(f"\n\n{'=' * 60}")
    print("Would you like to mark these transactions? (y/n)")
    # In production, this would be automated

