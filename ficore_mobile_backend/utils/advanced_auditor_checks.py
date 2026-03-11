#!/usr/bin/env python3
"""
Advanced FiCore Auditor Checks
Additional monitoring for edge cases and system health

Author: Hassan Ahmad (Founder, FiCore Africa)
Created: March 11, 2026
"""

from datetime import datetime, timedelta
from bson import ObjectId
from decimal import Decimal
import statistics

# Business User ID (Global Constant)
BUSINESS_USER_ID = ObjectId('69a18f7a4bf164fcbf7656be')

class AdvancedAuditorChecks:
    """
    Advanced monitoring checks for FiCore system health
    """
    
    def __init__(self, db):
        self.db = db
        self.alerts = []
    
    def check_orphaned_transactions(self):
        """
        RED FLAG 7: Orphaned Transactions
        Find transactions that should be linked but aren't
        """
        try:
            # Check for VAS transactions without corresponding expense entries
            since = datetime.utcnow() - timedelta(hours=24)
            
            vas_transactions = list(self.db.vas_transactions.find({
                'createdAt': {'$gte': since},
                'status': 'SUCCESS'
            }))
            
            orphaned_vas = []
            
            for vas_txn in vas_transactions:
                # Check if corresponding expense entry exists
                expense_entry = self.db.expenses.find_one({
                    'vasTransactionId': str(vas_txn['_id']),
                    'sourceType': {'$regex': 'vas_'}
                })
                
                if not expense_entry:
                    orphaned_vas.append({
                        'transaction_id': str(vas_txn['_id']),
                        'user_id': str(vas_txn['userId']),
                        'amount': vas_txn['amount'],
                        'type': vas_txn['type']
                    })
            
            if orphaned_vas:
                alert_message = f"""🚨 FiCore Alert: ORPHANED VAS TRANSACTIONS

{len(orphaned_vas)} VAS transactions without expense entries:

"""
                for txn in orphaned_vas[:3]:  # Show first 3
                    alert_message += f"• {txn['type']} ₦{txn['amount']} - User: {txn['user_id'][:8]}...\n"
                
                if len(orphaned_vas) > 3:
                    alert_message += f"• ... and {len(orphaned_vas) - 3} more\n"
                
                alert_message += f"""
Action Required: Check VAS auto-entry generation logic.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'ORPHANED_VAS',
                    'severity': 'HIGH',
                    'count': len(orphaned_vas),
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': f"Orphaned transaction check failed: {str(e)}"
            })
            return False
    
    def check_duplicate_transactions(self):
        """
        RED FLAG 8: Duplicate Transactions
        Detect potential duplicate entries that could inflate numbers
        """
        try:
            # Check for duplicate expenses (same user, amount, date, description)
            since = datetime.utcnow() - timedelta(hours=24)
            
            pipeline = [
                {'$match': {
                    'createdAt': {'$gte': since},
                    'status': 'active',
                    'isDeleted': False
                }},
                {'$group': {
                    '_id': {
                        'userId': '$userId',
                        'amount': '$amount',
                        'description': '$description',
                        'date': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$date'}}
                    },
                    'count': {'$sum': 1},
                    'ids': {'$push': '$_id'}
                }},
                {'$match': {'count': {'$gt': 1}}}
            ]
            
            duplicate_expenses = list(self.db.expenses.aggregate(pipeline))
            duplicate_incomes = list(self.db.incomes.aggregate(pipeline))
            
            total_duplicates = len(duplicate_expenses) + len(duplicate_incomes)
            
            if total_duplicates > 0:
                alert_message = f"""🚨 FiCore Alert: DUPLICATE TRANSACTIONS

Potential duplicates detected:
• Duplicate Expenses: {len(duplicate_expenses)}
• Duplicate Incomes: {len(duplicate_incomes)}

Action Required: Review for actual duplicates vs legitimate repeated transactions.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'DUPLICATE_TRANSACTIONS',
                    'severity': 'MEDIUM',
                    'count': total_duplicates,
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': f"Duplicate transaction check failed: {str(e)}"
            })
            return False
    
    def check_negative_balances(self):
        """
        RED FLAG 9: Negative Wallet Balances
        Users should never have negative wallet balances
        """
        try:
            # Check for negative balances in VAS wallets
            negative_wallets = list(self.db.vas_wallets.find({
                'balance': {'$lt': 0}
            }))
            
            if negative_wallets:
                alert_message = f"""🚨 FiCore Alert: NEGATIVE WALLET BALANCES

{len(negative_wallets)} users with negative balances:

"""
                for wallet in negative_wallets[:3]:  # Show first 3
                    user = self.db.users.find_one({'_id': wallet['userId']})
                    user_email = user.get('email', 'Unknown') if user else 'Unknown'
                    alert_message += f"• {user_email}: ₦{wallet['balance']:.2f}\n"
                
                if len(negative_wallets) > 3:
                    alert_message += f"• ... and {len(negative_wallets) - 3} more\n"
                
                alert_message += f"""
Action Required: Investigate how balances went negative. Check for transaction errors.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'NEGATIVE_BALANCES',
                    'severity': 'HIGH',
                    'count': len(negative_wallets),
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': f"Negative balance check failed: {str(e)}"
            })
            return False
    
    def check_transaction_volume_anomalies(self):
        """
        RED FLAG 10: Transaction Volume Anomalies
        Detect unusual spikes or drops in transaction volume
        """
        try:
            # Get transaction counts for last 7 days
            daily_counts = []
            
            for i in range(7):
                day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
                day_end = day_start + timedelta(days=1)
                
                daily_transactions = (
                    self.db.expenses.count_documents({
                        'createdAt': {'$gte': day_start, '$lt': day_end},
                        'status': 'active'
                    }) +
                    self.db.incomes.count_documents({
                        'createdAt': {'$gte': day_start, '$lt': day_end},
                        'status': 'active'
                    })
                )
                
                daily_counts.append(daily_transactions)
            
            if len(daily_counts) >= 3:
                # Calculate average and standard deviation
                avg_transactions = statistics.mean(daily_counts)
                std_dev = statistics.stdev(daily_counts) if len(daily_counts) > 1 else 0
                
                # Check today's count against average
                today_count = daily_counts[0]
                
                # Alert if today is >2 standard deviations from average
                if std_dev > 0 and abs(today_count - avg_transactions) > (2 * std_dev):
                    if today_count > avg_transactions:
                        anomaly_type = "SPIKE"
                        severity = "MEDIUM"
                    else:
                        anomaly_type = "DROP"
                        severity = "HIGH"
                    
                    alert_message = f"""🚨 FiCore Alert: TRANSACTION VOLUME {anomaly_type}

Today's transactions: {today_count}
7-day average: {avg_transactions:.1f}
Standard deviation: {std_dev:.1f}

Daily counts (last 7 days): {daily_counts}

Action Required: Investigate cause of volume {anomaly_type.lower()}.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                    
                    self.alerts.append({
                        'type': f'VOLUME_{anomaly_type}',
                        'severity': severity,
                        'today_count': today_count,
                        'average': avg_transactions,
                        'message': alert_message
                    })
                    return False
            
            return True
            
        except Exception as e:
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': f"Volume anomaly check failed: {str(e)}"
            })
            return False
    
    def check_user_registration_anomalies(self):
        """
        RED FLAG 11: User Registration Anomalies
        Detect unusual user registration patterns (potential bot attacks)
        """
        try:
            # Check registrations in last 24 hours
            since = datetime.utcnow() - timedelta(hours=24)
            
            new_users = list(self.db.users.find({
                'createdAt': {'$gte': since}
            }))
            
            # Check for suspicious patterns
            suspicious_patterns = []
            
            # Pattern 1: Too many registrations from same IP (if tracked)
            if len(new_users) > 50:  # More than 50 registrations in 24h
                suspicious_patterns.append(f"High registration volume: {len(new_users)} users")
            
            # Pattern 2: Similar email patterns
            email_domains = {}
            for user in new_users:
                email = user.get('email', '')
                if '@' in email:
                    domain = email.split('@')[1]
                    email_domains[domain] = email_domains.get(domain, 0) + 1
            
            for domain, count in email_domains.items():
                if count > 10:  # More than 10 from same domain
                    suspicious_patterns.append(f"High registrations from {domain}: {count} users")
            
            # Pattern 3: Registrations without any activity
            inactive_new_users = 0
            for user in new_users:
                # Check if user has any transactions
                has_activity = (
                    self.db.expenses.count_documents({'userId': user['_id']}) > 0 or
                    self.db.incomes.count_documents({'userId': user['_id']}) > 0 or
                    self.db.vas_transactions.count_documents({'userId': user['_id']}) > 0
                )
                if not has_activity:
                    inactive_new_users += 1
            
            if inactive_new_users > 20:  # More than 20 inactive users
                suspicious_patterns.append(f"High inactive registrations: {inactive_new_users} users")
            
            if suspicious_patterns:
                alert_message = f"""🚨 FiCore Alert: SUSPICIOUS REGISTRATION PATTERNS

{len(suspicious_patterns)} suspicious patterns detected:

"""
                for pattern in suspicious_patterns:
                    alert_message += f"• {pattern}\n"
                
                alert_message += f"""
Total new users (24h): {len(new_users)}

Action Required: Review for potential bot attacks or fraud.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'SUSPICIOUS_REGISTRATIONS',
                    'severity': 'MEDIUM',
                    'new_users': len(new_users),
                    'patterns': len(suspicious_patterns),
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': f"Registration anomaly check failed: {str(e)}"
            })
            return False
    
    def check_database_performance(self):
        """
        RED FLAG 12: Database Performance Issues
        Monitor for slow queries and connection issues
        """
        try:
            # Check database connection
            start_time = datetime.utcnow()
            
            # Simple query to test responsiveness
            test_count = self.db.users.count_documents({})
            
            end_time = datetime.utcnow()
            query_time = (end_time - start_time).total_seconds()
            
            # Alert if query takes more than 5 seconds
            if query_time > 5.0:
                alert_message = f"""🚨 FiCore Alert: DATABASE PERFORMANCE ISSUE

Simple count query took {query_time:.2f} seconds (expected <1s)

Possible causes:
• High database load
• Network connectivity issues
• Index problems
• Resource constraints

Action Required: Check database performance and server resources.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                self.alerts.append({
                    'type': 'DB_PERFORMANCE',
                    'severity': 'HIGH',
                    'query_time': query_time,
                    'message': alert_message
                })
                return False
            
            return True
            
        except Exception as e:
            self.alerts.append({
                'type': 'SYSTEM_ERROR',
                'severity': 'CRITICAL',
                'message': f"Database performance check failed: {str(e)}"
            })
            return False
    
    def get_all_alerts(self):
        """
        Return all alerts from advanced checks
        """
        return self.alerts
    
    def run_all_advanced_checks(self):
        """
        Run all advanced checks
        """
        checks = [
            ("Orphaned Transactions", self.check_orphaned_transactions),
            ("Duplicate Transactions", self.check_duplicate_transactions),
            ("Negative Balances", self.check_negative_balances),
            ("Volume Anomalies", self.check_transaction_volume_anomalies),
            ("Registration Anomalies", self.check_user_registration_anomalies),
            ("Database Performance", self.check_database_performance)
        ]
        
        all_passed = True
        
        for check_name, check_function in checks:
            try:
                result = check_function()
                if not result:
                    all_passed = False
            except Exception as e:
                print(f"    💥 {check_name}: ERROR - {str(e)}")
                all_passed = False
        
        return all_passed