#!/usr/bin/env python3
"""
Add Reconciliation and Admin Action Schemas

Creates proper indexes and validates schemas for:
1. VAS Transactions (reconciliation fields)
2. Admin Actions (all admin operations)
3. Plan Mismatch Logs
4. Reconciliation History

This ensures fast queries and proper audit trails.
"""

import os
from pymongo import MongoClient, ASCENDING, DESCENDING
from datetime import datetime

MONGO_URI = os.environ.get('MONGO_URI')

def add_reconciliation_schemas():
    """Add schemas and indexes for reconciliation system"""
    
    print("🔧 ADDING RECONCILIATION SCHEMAS AND INDEXES")
    print("=" * 60)
    
    try:
        client = MongoClient(MONGO_URI)
        db = client['ficore_africa']
        
        # ========================================
        # 1. VAS TRANSACTIONS - Reconciliation Indexes
        # ========================================
        print("\n1️⃣ VAS TRANSACTIONS - Adding reconciliation indexes...")
        
        vas_indexes = [
            {
                'name': 'reconciliation_status_idx',
                'keys': [('status', ASCENDING), ('reconciliationDismissed', ASCENDING)],
                'description': 'Fast lookup for pending reconciliations (not dismissed)'
            },
            {
                'name': 'reconciliation_dismissed_idx',
                'keys': [('reconciliationDismissed', ASCENDING), ('reconciliationDismissedAt', DESCENDING)],
                'description': 'Fast lookup for dismissed reconciliations'
            },
            {
                'name': 'reconciliation_reason_idx',
                'keys': [('reconciliationReason', ASCENDING), ('createdAt', DESCENDING)],
                'description': 'Group by reconciliation reason'
            },
            {
                'name': 'reconciliation_user_status_idx',
                'keys': [('userId', ASCENDING), ('status', ASCENDING), ('createdAt', DESCENDING)],
                'description': 'User-specific reconciliation lookup'
            },
            {
                'name': 'reconciliation_needs_idx',
                'keys': [('needsReconciliation', ASCENDING), ('createdAt', DESCENDING)],
                'description': 'Fast lookup for items needing reconciliation'
            }
        ]
        
        for index_def in vas_indexes:
            try:
                existing_indexes = db.vas_transactions.index_information()
                if index_def['name'] not in existing_indexes:
                    db.vas_transactions.create_index(
                        index_def['keys'],
                        name=index_def['name']
                    )
                    print(f"   ✅ Created: {index_def['name']}")
                    print(f"      {index_def['description']}")
                else:
                    print(f"   ⏭️  Exists: {index_def['name']}")
            except Exception as e:
                print(f"   ❌ Failed: {index_def['name']} - {e}")
        
        # ========================================
        # 2. ADMIN ACTIONS - Complete Audit Trail
        # ========================================
        print("\n2️⃣ ADMIN ACTIONS - Adding audit trail indexes...")
        
        admin_indexes = [
            {
                'name': 'admin_action_type_idx',
                'keys': [('action', ASCENDING), ('timestamp', DESCENDING)],
                'description': 'Group by action type (e.g., all refunds, all debits)'
            },
            {
                'name': 'admin_user_actions_idx',
                'keys': [('adminId', ASCENDING), ('timestamp', DESCENDING)],
                'description': 'All actions by specific admin'
            },
            {
                'name': 'admin_target_user_idx',
                'keys': [('details.userId', ASCENDING), ('timestamp', DESCENDING)],
                'description': 'All admin actions affecting specific user'
            },
            {
                'name': 'admin_transaction_idx',
                'keys': [('transactionId', ASCENDING), ('timestamp', DESCENDING)],
                'description': 'All admin actions on specific transaction'
            },
            {
                'name': 'admin_timestamp_idx',
                'keys': [('timestamp', DESCENDING)],
                'description': 'Recent admin actions (for dashboard)'
            },
            {
                'name': 'admin_email_idx',
                'keys': [('adminEmail', ASCENDING), ('timestamp', DESCENDING)],
                'description': 'Actions by admin email'
            }
        ]
        
        for index_def in admin_indexes:
            try:
                existing_indexes = db.admin_actions.index_information()
                if index_def['name'] not in existing_indexes:
                    db.admin_actions.create_index(
                        index_def['keys'],
                        name=index_def['name']
                    )
                    print(f"   ✅ Created: {index_def['name']}")
                    print(f"      {index_def['description']}")
                else:
                    print(f"   ⏭️  Exists: {index_def['name']}")
            except Exception as e:
                print(f"   ❌ Failed: {index_def['name']} - {e}")
        
        # ========================================
        # 3. PLAN MISMATCH LOGS
        # ========================================
        print("\n3️⃣ PLAN MISMATCH LOGS - Adding indexes...")
        
        mismatch_indexes = [
            {
                'name': 'mismatch_user_idx',
                'keys': [('userId', ASCENDING), ('created_at', DESCENDING)],
                'description': 'User-specific plan mismatches'
            },
            {
                'name': 'mismatch_provider_idx',
                'keys': [('provider', ASCENDING), ('created_at', DESCENDING)],
                'description': 'Mismatches by provider'
            },
            {
                'name': 'mismatch_status_idx',
                'keys': [('status', ASCENDING), ('created_at', DESCENDING)],
                'description': 'Mismatch resolution status'
            },
            {
                'name': 'mismatch_transaction_idx',
                'keys': [('details.transaction_id', ASCENDING)],
                'description': 'Lookup mismatch by transaction ID'
            }
        ]
        
        for index_def in mismatch_indexes:
            try:
                existing_indexes = db.plan_mismatch_logs.index_information()
                if index_def['name'] not in existing_indexes:
                    db.plan_mismatch_logs.create_index(
                        index_def['keys'],
                        name=index_def['name']
                    )
                    print(f"   ✅ Created: {index_def['name']}")
                    print(f"      {index_def['description']}")
                else:
                    print(f"   ⏭️  Exists: {index_def['name']}")
            except Exception as e:
                print(f"   ❌ Failed: {index_def['name']} - {e}")
        
        # ========================================
        # 4. DOCUMENT SCHEMAS (for reference)
        # ========================================
        print("\n4️⃣ DOCUMENT SCHEMAS - Creating reference...")
        
        schemas = {
            'vas_transactions_reconciliation': {
                'status': 'NEEDS_RECONCILIATION | SUCCESS | FAILED | PENDING',
                'reconciliationReason': 'PLAN_MISMATCH | GHOST_SUCCESS | STUCK_PENDING | PROVIDER_NONE | AUTO_SCAN_SUSPICIOUS_FAILURE',
                'reconciliationDetails': {
                    'original_status': 'string',
                    'provider': 'string',
                    'severity': 'HIGH | MEDIUM | LOW',
                    'marked_at': 'datetime',
                    'auto_detected': 'boolean',
                    'action_required': 'string',
                    'verification_steps': ['array of strings']
                },
                'needsReconciliation': 'boolean',
                'reconciliationDismissed': 'boolean',
                'reconciliationDismissedAt': 'datetime',
                'reconciliationDismissedBy': 'string (admin email)',
                'reconciliationDismissReason': 'string',
                'reconciliationDismissNotes': 'string',
                'reconciliationRecoveredAt': 'datetime',
                'reconciliationRecoveredBy': 'string (admin email)',
                'reconciliationRecoveryReason': 'string',
                'reconciliationResolved': 'boolean',
                'reconciliationResolvedAt': 'datetime'
            },
            'admin_actions': {
                '_id': 'ObjectId',
                'adminId': 'ObjectId (admin user ID)',
                'adminEmail': 'string',
                'action': 'string (e.g., dismiss_reconciliation, recover_reconciliation, admin_refund, admin_debit, grant_premium)',
                'transactionId': 'string (optional)',
                'reason': 'string',
                'notes': 'string (optional)',
                'timestamp': 'datetime',
                'details': {
                    'userId': 'string (affected user)',
                    'amount': 'number (optional)',
                    'transaction_type': 'string (optional)',
                    'original_status': 'string (optional)',
                    '...': 'action-specific fields'
                }
            },
            'plan_mismatch_logs': {
                '_id': 'ObjectId',
                'userId': 'ObjectId',
                'provider': 'string',
                'incident_type': 'PLAN_MISMATCH',
                'severity': 'HIGH | MEDIUM | LOW',
                'details': {
                    'transaction_id': 'string',
                    'requested_plan_id': 'string',
                    'requested_plan_name': 'string',
                    'requested_amount': 'number',
                    'delivered_plan': 'string',
                    'delivered_amount': 'number'
                },
                'status': 'LOGGED | RESOLVED | DISMISSED',
                'requires_investigation': 'boolean',
                'requires_refund': 'boolean',
                'created_at': 'datetime',
                'metadata': {
                    'user_impact': 'string',
                    'financial_impact': 'number',
                    'recovery_needed': 'boolean'
                }
            }
        }
        
        # Save schemas to a reference file
        schema_file = 'ficore_mobile_backend/schemas/reconciliation_schemas.json'
        os.makedirs(os.path.dirname(schema_file), exist_ok=True)
        
        import json
        with open(schema_file, 'w') as f:
            json.dump(schemas, f, indent=2, default=str)
        
        print(f"   ✅ Saved schema reference to: {schema_file}")
        
        # ========================================
        # 5. VALIDATION RULES
        # ========================================
        print("\n5️⃣ VALIDATION RULES - Summary...")
        
        validation_rules = {
            'vas_transactions': [
                'status must be one of: NEEDS_RECONCILIATION, SUCCESS, FAILED, PENDING',
                'reconciliationReason required if status = NEEDS_RECONCILIATION',
                'reconciliationDismissedBy required if reconciliationDismissed = true',
                'reconciliationRecoveredBy required if reconciliationRecoveredAt exists'
            ],
            'admin_actions': [
                'adminId and adminEmail are required',
                'action is required (describes what admin did)',
                'timestamp is required',
                'reason is required for sensitive actions (refund, debit, dismiss)',
                'details.userId should be included when action affects a user'
            ],
            'plan_mismatch_logs': [
                'userId and provider are required',
                'details.transaction_id is required',
                'details must include requested and delivered amounts',
                'status must be one of: LOGGED, RESOLVED, DISMISSED'
            ]
        }
        
        for collection, rules in validation_rules.items():
            print(f"\n   {collection}:")
            for rule in rules:
                print(f"      - {rule}")
        
        # ========================================
        # 6. STATISTICS
        # ========================================
        print("\n6️⃣ STATISTICS - Current counts...")
        
        stats = {
            'vas_transactions_needing_reconciliation': db.vas_transactions.count_documents({
                'status': 'NEEDS_RECONCILIATION',
                'reconciliationDismissed': {'$ne': True}
            }),
            'vas_transactions_dismissed': db.vas_transactions.count_documents({
                'reconciliationDismissed': True
            }),
            'admin_actions_total': db.admin_actions.count_documents({}),
            'admin_actions_last_24h': db.admin_actions.count_documents({
                'timestamp': {'$gte': datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)}
            }),
            'plan_mismatch_logs_total': db.plan_mismatch_logs.count_documents({}),
            'plan_mismatch_logs_unresolved': db.plan_mismatch_logs.count_documents({
                'status': 'LOGGED'
            })
        }
        
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        print("\n✅ RECONCILIATION SCHEMAS AND INDEXES COMPLETE")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = add_reconciliation_schemas()
    exit(0 if success else 1)

