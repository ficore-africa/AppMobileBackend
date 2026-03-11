#!/usr/bin/env python3
"""
FiCore Silent Auditor - WhatsApp Alert System
Monitors financial integrity and sends alerts only when intervention needed.

Author: Hassan Ahmad (Founder, FiCore Africa)
Created: March 11, 2026
Purpose: "Lock the door" on data integrity - prevent issues, don't just fix them
"""

import requests
import os
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId
from decimal import Decimal
import json
import sys
from pathlib import Path

# Add utils directory to path for imports
sys.path.append(str(Path(__file__).parent))
from advanced_auditor_checks import AdvancedAuditorChecks

# Business User ID (Global Constant)
BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')

# CallMeBot Configuration
CALLMEBOT_API_KEY = os.getenv('CALLMEBOT_API_KEY')  # Set in environment
HASSAN_PHONE = "+2348012345678"  # Replace with actual number

class WhatsAppAuditor:
    """
    Silent Auditor that monitors FiCore financial integrity
    Sends WhatsApp alerts only when manual intervention needed
    """
    
    def __init__(self):
        self.mongo_uri = os.getenv('MONGO_URI')
        self.client = MongoClient(self.mongo_uri)
        self.db = self.client.ficore_db
        self.alerts = []
        
    def send_whatsapp_alert(self, message):
        """
        Send WhatsApp alert via CallMeBot
        """
        if not CALLMEBOT_API_KEY:
            print("⚠️  CALLMEBOT_API_KEY not set - alert not sent")
            return False
            
        url = f"https://api.callmebot.com/whatsapp.php"
        params = {
            'phone': HASSAN_PHONE.replace('+', ''),
            'text': message,
            'apikey': CALLMEBOT_API_KEY
        }
        
        try:
            response = requests.get(url, params=params)
            if response.status_code == 200:
                print(f"✅ WhatsApp alert sent: {message[:50]}...")
                return True
            else:
                print(f"❌ Failed to send WhatsApp alert: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ WhatsApp alert error: {str(e)}")
            return False
    
    def check_tri_point_reconciliation(self):
        """
        RED FLAG 1: Tri-Point Reconciliation Imbalance
        Point 1: FC Credits Outstanding vs Point 2: FC Liability
        """
        try:
            # Point 1: FC Credits Outstanding (from credit_transactions)
            fc_outstanding_pipeline = [
                {'$match': {'status': 'SUCCESS'}},
                {'$group': {'_id': None, 'total': {'$sum': '$fcAmount'}}}
            ]
            fc_outstanding_result = list(self.db.credit_transactions.aggregate(fc_outstanding_pipeline))
            fc_outstanding = fc_outstanding_result[0]['total'] if fc_outstanding_result else 0
            
            # Point 2: FC Liability (from incomes collection)
            fc_liability_pipeline = [
                {'$match': {
                    'userId': BUSINESS_USER_ID,
                    'sourceType': 'fc_liability_accrual',
                    'status': 'active',
                    'isDeleted': False
                }},
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ]
            fc_liability_result = list(self.db.incomes.aggregate(fc_liability_pipeline))
            fc_liability = fc_liability_result[0]['total'] if fc_liability_result else 0
            
            # Check for imbalance
            difference = abs(fc_outstanding - fc_liability)
            
            if difference > 0:
                alert_message = f"""🚨 FiCore Alert: FC IMBALANCE DETECTED

Point 1 (FC Outstanding): {fc_outstanding:,.0f} FCs
Point 2 (FC Liability): {fc_liability:,.0f} FCs
Difference: {difference:,.0f} FCs

Action Required: Check recent FC transactions for missing liability entries.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'FC_IMBALANCE',
                    'severity': 'HIGH',
                    'difference': difference,
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            error_message = f"""🚨 FiCore Alert: TRI-POINT CHECK FAILED

Error: {str(e)}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Action Required: Check database connection and audit script."""
            
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': error_message
            })
            return False
    
    def check_atomic_transaction_integrity(self):
        """
        RED FLAG 2: Failed Atomic Transactions
        Check for incomplete 4-transaction chains in last 24 hours
        """
        try:
            # Check last 24 hours
            since = datetime.utcnow() - timedelta(hours=24)
            
            # Find atomic operation groups (by metadata.atomicOperationGroup)
            atomic_expenses = list(self.db.expenses.find({
                'userId': BUSINESS_USER_ID,
                'createdAt': {'$gte': since},
                'sourceType': {'$regex': 'marketing_expense_|liability_adjustment_'},
                'metadata.atomicOperationGroup': {'$exists': True}
            }))
            
            failed_operations = []
            
            for expense in atomic_expenses:
                operation_group = expense.get('metadata', {}).get('atomicOperationGroup')
                if not operation_group:
                    continue
                
                # Count transactions in this atomic group
                total_transactions = (
                    self.db.expenses.count_documents({
                        'metadata.atomicOperationGroup': operation_group
                    }) +
                    self.db.incomes.count_documents({
                        'metadata.atomicOperationGroup': operation_group
                    })
                )
                
                # Should be exactly 4 transactions
                if total_transactions != 4:
                    failed_operations.append({
                        'operation_group': operation_group,
                        'transaction_count': total_transactions,
                        'expense_id': str(expense['_id']),
                        'source_type': expense['sourceType']
                    })
            
            if failed_operations:
                alert_message = f"""🚨 FiCore Alert: ATOMIC TRANSACTION FAILURES

{len(failed_operations)} incomplete atomic operations detected:

"""
                for op in failed_operations[:3]:  # Show first 3
                    alert_message += f"• {op['source_type']}: {op['transaction_count']}/4 transactions\n"
                
                if len(failed_operations) > 3:
                    alert_message += f"• ... and {len(failed_operations) - 3} more\n"
                
                alert_message += f"""
Action Required: Check atomic operation functions for error handling.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'ATOMIC_FAILURE',
                    'severity': 'HIGH',
                    'failed_count': len(failed_operations),
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            error_message = f"""🚨 FiCore Alert: ATOMIC CHECK FAILED

Error: {str(e)}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Action Required: Check atomic transaction monitoring."""
            
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': error_message
            })
            return False
    
    def check_high_value_fc_anomalies(self):
        """
        RED FLAG 3: Anti-Fraud - High Value FC Grants
        Alert if any user receives >50 FCs in single transaction (outside normal 5-10 FC range)
        """
        try:
            # Check last 24 hours for high-value FC grants
            since = datetime.utcnow() - timedelta(hours=24)
            
            high_value_transactions = list(self.db.credit_transactions.find({
                'createdAt': {'$gte': since},
                'fcAmount': {'$gt': 50},  # Above normal range
                'status': 'SUCCESS'
            }))
            
            if high_value_transactions:
                alert_message = f"""🚨 FiCore Alert: HIGH-VALUE FC DETECTED

{len(high_value_transactions)} transactions above 50 FCs:

"""
                for txn in high_value_transactions[:3]:  # Show first 3
                    user_email = txn.get('metadata', {}).get('userEmail', 'Unknown')
                    alert_message += f"• {txn['fcAmount']} FCs → {user_email}\n"
                
                if len(high_value_transactions) > 3:
                    alert_message += f"• ... and {len(high_value_transactions) - 3} more\n"
                
                alert_message += f"""
Action Required: Verify these are legitimate admin grants, not fraud.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'HIGH_VALUE_FC',
                    'severity': 'MEDIUM',
                    'transaction_count': len(high_value_transactions),
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            error_message = f"""🚨 FiCore Alert: FC ANOMALY CHECK FAILED

Error: {str(e)}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Action Required: Check FC transaction monitoring."""
            
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': error_message
            })
            return False
    
    def check_admin_action_anomalies(self):
        """
        RED FLAG 4: Admin Action Monitoring
        Alert for unusual admin activities (mass deletions, high-value operations)
        """
        try:
            # Check last 24 hours for admin actions
            since = datetime.utcnow() - timedelta(hours=24)
            
            # Check for mass admin operations
            admin_expenses = self.db.expenses.count_documents({
                'userId': BUSINESS_USER_ID,
                'createdAt': {'$gte': since},
                'sourceType': {'$regex': 'admin_|manual_adjustment'}
            })
            
            admin_incomes = self.db.incomes.count_documents({
                'userId': BUSINESS_USER_ID,
                'createdAt': {'$gte': since},
                'sourceType': {'$regex': 'admin_|manual_adjustment'}
            })
            
            total_admin_actions = admin_expenses + admin_incomes
            
            # Alert if >10 admin actions in 24 hours (unusual)
            if total_admin_actions > 10:
                alert_message = f"""🚨 FiCore Alert: HIGH ADMIN ACTIVITY

{total_admin_actions} admin transactions in last 24 hours:
• Admin Expenses: {admin_expenses}
• Admin Incomes: {admin_incomes}

Action Required: Verify admin actions are legitimate.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'HIGH_ADMIN_ACTIVITY',
                    'severity': 'MEDIUM',
                    'action_count': total_admin_actions,
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            error_message = f"""🚨 FiCore Alert: ADMIN CHECK FAILED

Error: {str(e)}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Action Required: Check admin activity monitoring."""
            
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': error_message
            })
            return False
    
    def check_provider_health(self):
        """
        RED FLAG 5: Provider Health Checks
        Monitor VAS provider balances and transaction success rates
        """
        try:
            # Check last 24 hours VAS transactions
            since = datetime.utcnow() - timedelta(hours=24)
            
            # Check VAS transaction success rates
            total_vas = self.db.vas_transactions.count_documents({
                'createdAt': {'$gte': since}
            })
            
            failed_vas = self.db.vas_transactions.count_documents({
                'createdAt': {'$gte': since},
                'status': 'FAILED'
            })
            
            if total_vas > 0:
                failure_rate = (failed_vas / total_vas) * 100
                
                # Alert if failure rate >20%
                if failure_rate > 20:
                    alert_message = f"""🚨 FiCore Alert: HIGH VAS FAILURE RATE

VAS Transaction Health (24h):
• Total Transactions: {total_vas}
• Failed Transactions: {failed_vas}
• Failure Rate: {failure_rate:.1f}%

Action Required: Check VAS provider connectivity and balances.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                    
                    self.alerts.append({
                        'type': 'VAS_HEALTH',
                        'severity': 'HIGH',
                        'failure_rate': failure_rate,
                        'message': alert_message
                    })
                    return False
            
            return True
            
        except Exception as e:
            error_message = f"""🚨 FiCore Alert: PROVIDER HEALTH CHECK FAILED

Error: {str(e)}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Action Required: Check VAS provider monitoring."""
            
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': error_message
            })
            return False
    
    def check_wallet_balance_sync(self):
        """
        RED FLAG 6: Wallet Balance Synchronization
        Check for mismatched wallet balances across 4 fields
        """
        try:
            # Find users with mismatched wallet balances
            users_with_wallets = list(self.db.users.find({
                'vasWalletBalance': {'$exists': True},
                'liquidWalletBalance': {'$exists': True}
            }))
            
            mismatched_users = []
            
            for user in users_with_wallets:
                # Get VAS wallet balance
                vas_wallet = self.db.vas_wallets.find_one({'userId': user['_id']})
                vas_balance = vas_wallet.get('balance', 0) if vas_wallet else 0
                
                # Compare 4 balance fields
                balances = {
                    'vas_wallet': float(vas_balance),
                    'user_wallet': float(user.get('walletBalance', 0)),
                    'liquid_wallet': float(user.get('liquidWalletBalance', 0)),
                    'vas_user': float(user.get('vasWalletBalance', 0))
                }
                
                # Check if all balances match
                unique_balances = set(balances.values())
                if len(unique_balances) > 1:
                    mismatched_users.append({
                        'user_id': str(user['_id']),
                        'email': user.get('email', 'Unknown'),
                        'balances': balances
                    })
            
            if mismatched_users:
                alert_message = f"""🚨 FiCore Alert: WALLET BALANCE MISMATCH

{len(mismatched_users)} users with mismatched wallet balances:

"""
                for user in mismatched_users[:3]:  # Show first 3
                    alert_message += f"• {user['email']}: VAS={user['balances']['vas_wallet']}, Liquid={user['balances']['liquid_wallet']}\n"
                
                if len(mismatched_users) > 3:
                    alert_message += f"• ... and {len(mismatched_users) - 3} more\n"
                
                alert_message += f"""
Action Required: Run wallet balance synchronization script.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'WALLET_MISMATCH',
                    'severity': 'HIGH',
                    'affected_users': len(mismatched_users),
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            error_message = f"""🚨 FiCore Alert: WALLET SYNC CHECK FAILED

Error: {str(e)}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Action Required: Check wallet balance monitoring."""
            
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': error_message
            })
            return False
    
    def run_full_audit(self, quick_mode=False):
        """
        Run all audit checks and send alerts if issues found
        """
        print("🔍 Starting FiCore Silent Auditor...")
        
        # Basic checks (always run)
        basic_checks = [
            ("Tri-Point Reconciliation", self.check_tri_point_reconciliation),
            ("Atomic Transaction Integrity", self.check_atomic_transaction_integrity),
            ("High-Value FC Anomalies", self.check_high_value_fc_anomalies),
            ("Wallet Balance Sync", self.check_wallet_balance_sync)
        ]
        
        # Extended checks (skip in quick mode)
        extended_checks = [
            ("Admin Action Monitoring", self.check_admin_action_anomalies),
            ("Provider Health", self.check_provider_health)
        ]
        
        # Advanced checks (full mode only)
        advanced_checks = []
        if not quick_mode:
            advanced_auditor = AdvancedAuditorChecks(self.db)
            advanced_checks = [
                ("Advanced Checks", lambda: advanced_auditor.run_all_advanced_checks())
            ]
        
        # Combine all checks based on mode
        if quick_mode:
            all_checks = basic_checks
            print("  Running in QUICK mode (basic checks only)")
        else:
            all_checks = basic_checks + extended_checks + advanced_checks
            print("  Running in FULL mode (all checks)")
        
        all_passed = True
        
        for check_name, check_function in all_checks:
            print(f"  Checking {check_name}...")
            try:
                result = check_function()
                if result:
                    print(f"    ✅ {check_name}: PASSED")
                else:
                    print(f"    ❌ {check_name}: FAILED")
                    all_passed = False
                    
                    # Collect advanced alerts if available
                    if check_name == "Advanced Checks" and not quick_mode:
                        advanced_alerts = advanced_auditor.get_all_alerts()
                        self.alerts.extend(advanced_alerts)
                        
            except Exception as e:
                print(f"    💥 {check_name}: ERROR - {str(e)}")
                all_passed = False
        
        # Send alerts if any issues found
        if not all_passed:
            print(f"\n🚨 {len(self.alerts)} issues detected - sending WhatsApp alerts...")
            
            for alert in self.alerts:
                if alert['severity'] in ['CRITICAL', 'HIGH']:
                    self.send_whatsapp_alert(alert['message'])
                else:
                    print(f"  📝 {alert['type']}: {alert['message'][:100]}...")
        else:
            print("\n✅ All checks passed - FiCore financial integrity maintained")
        
        return all_passed
    
    def generate_daily_summary(self):
        """
        Generate daily summary (no alerts unless issues)
        """
        try:
            # Get key metrics for last 24 hours
            since = datetime.utcnow() - timedelta(hours=24)
            
            # FC transactions
            fc_transactions = self.db.credit_transactions.count_documents({
                'createdAt': {'$gte': since},
                'status': 'SUCCESS'
            })
            
            # VAS transactions
            vas_transactions = self.db.vas_transactions.count_documents({
                'createdAt': {'$gte': since}
            })
            
            # New users
            new_users = self.db.users.count_documents({
                'createdAt': {'$gte': since}
            })
            
            # Only send summary if significant activity OR if it's 8 AM
            current_hour = datetime.now().hour
            significant_activity = fc_transactions > 5 or vas_transactions > 10 or new_users > 3
            
            if significant_activity or current_hour == 8:
                summary_message = f"""📊 FiCore Daily Summary

Activity (24h):
• FC Transactions: {fc_transactions}
• VAS Transactions: {vas_transactions}
• New Users: {new_users}

Status: All systems operational ✅

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.send_whatsapp_alert(summary_message)
                return True
            
            return False
            
        except Exception as e:
            print(f"❌ Daily summary error: {str(e)}")
            return False

def main():
    """
    Main function - run audit and send alerts if needed
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='FiCore Silent Auditor')
    parser.add_argument('--quick', action='store_true', help='Run quick checks only')
    parser.add_argument('--daily', action='store_true', help='Run daily summary')
    args = parser.parse_args()
    
    auditor = WhatsAppAuditor()
    
    # Run audit based on mode
    if args.quick:
        audit_passed = auditor.run_full_audit(quick_mode=True)
    else:
        audit_passed = auditor.run_full_audit(quick_mode=False)
    
    # Generate daily summary if requested
    if args.daily:
        auditor.generate_daily_summary()
    
    # Exit with appropriate code
    exit(0 if audit_passed else 1)

if __name__ == "__main__":
    main()