"""
Provider Health Monitoring Blueprint
Tracks VAS provider balance, success rates, and liquidity issues
Supports multiple providers: Peyflex, Monnify
Sends automatic email alerts when balances are critically low
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
from bson import ObjectId
from utils.email_service import get_email_service

def init_provider_health_blueprint(mongo, token_required):
    """Initialize the provider health blueprint with database and auth decorator"""
    provider_health_bp = Blueprint('provider_health', __name__, url_prefix='/api/admin/provider-health')
    
    # ============================================================================
    # PROVIDER BALANCE TRACKING (Multi-Provider Support)
    # Supports: Peyflex, Monnify
    # ============================================================================
    
    @provider_health_bp.route('/balance/<provider>', methods=['GET'])
    def get_provider_balance(provider):
        """
        Get current provider balance (manually entered by admin)
        Supports: peyflex, monnify
        """
        try:
            provider_lower = provider.lower()
            if provider_lower not in ['peyflex', 'monnify']:
                return jsonify({
                    'success': False,
                    'error': f'Unsupported provider: {provider}. Supported: peyflex, monnify'
                }), 400
            
            # Get latest balance entry
            balance_entry = mongo.db.provider_balances.find_one(
                {'provider': provider_lower},
                sort=[('updatedAt', -1)]
            )
            
            if not balance_entry:
                # No balance entry yet - create default
                balance_entry = {
                    'provider': provider_lower,
                    'balance': 0.0,
                    'lastUpdated': None,
                    'updatedBy': 'system',
                    'notes': 'No balance recorded yet',
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                }
                mongo.db.provider_balances.insert_one(balance_entry)
            
            # Calculate time since last update
            last_updated = balance_entry.get('lastUpdated')
            hours_since_update = None
            if last_updated:
                hours_since_update = (datetime.utcnow() - last_updated).total_seconds() / 3600
            
            # Get recent failed transactions due to insufficient balance
            failed_count = mongo.db.vas_transactions.count_documents({
                'provider': provider_lower,
                'status': 'FAILED',
                'errorMessage': {'$regex': 'Insufficient wallet balance', '$options': 'i'},
                'createdAt': {'$gte': datetime.utcnow() - timedelta(hours=24)}
            })
            
            return jsonify({
                'success': True,
                'provider': provider_lower,
                'balance': float(balance_entry.get('balance', 0)),
                'lastUpdated': last_updated.isoformat() if last_updated else None,
                'hoursSinceUpdate': round(hours_since_update, 1) if hours_since_update else None,
                'updatedBy': balance_entry.get('updatedBy', 'unknown'),
                'notes': balance_entry.get('notes', ''),
                'recentFailures': failed_count,
                'needsUpdate': hours_since_update > 24 if hours_since_update else True
            }), 200
            
        except Exception as e:
            print(f"❌ Error getting {provider} balance: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500


    @provider_health_bp.route('/balance/<provider>', methods=['POST'])
    def update_provider_balance(provider):
        """
        Update provider balance (admin manually enters after checking provider dashboard)
        Automatically sends email alert if balance is critically low
        Supports: peyflex, monnify
        """
        try:
            provider_lower = provider.lower()
            if provider_lower not in ['peyflex', 'monnify']:
                return jsonify({
                    'success': False,
                    'error': f'Unsupported provider: {provider}. Supported: peyflex, monnify'
                }), 400
            
            data = request.get_json()
            balance = float(data.get('balance', 0))
            admin_email = data.get('adminEmail', 'unknown')
            notes = data.get('notes', '')
            
            # Get previous balance for history tracking
            previous_entry = mongo.db.provider_balances.find_one({'provider': provider_lower})
            previous_balance = float(previous_entry.get('balance', 0)) if previous_entry else 0.0
            
            # Update or create balance entry
            result = mongo.db.provider_balances.update_one(
                {'provider': provider_lower},
                {
                    '$set': {
                        'balance': balance,
                        'lastUpdated': datetime.utcnow(),
                        'updatedBy': admin_email,
                        'notes': notes,
                        'updatedAt': datetime.utcnow()
                    },
                    '$setOnInsert': {
                        'provider': provider_lower,
                        'createdAt': datetime.utcnow()
                    }
                },
                upsert=True
            )
            
            # Save to balance update history
            history_entry = {
                'provider': provider_lower,
                'previousBalance': previous_balance,
                'newBalance': balance,
                'change': balance - previous_balance,
                'updatedBy': admin_email,
                'notes': notes,
                'updatedAt': datetime.utcnow()
            }
            history_result = mongo.db.provider_balance_history.insert_one(history_entry)
            print(f"📝 Balance history saved: {history_result.inserted_id} - {provider_lower} from ₦{previous_balance:,.2f} to ₦{balance:,.2f}")
            
            print(f"✅ {provider.capitalize()} balance updated: ₦{balance:,.2f} by {admin_email}")
            
            # Check if balance is critically low and send email alert
            failed_count = mongo.db.vas_transactions.count_documents({
                'provider': provider_lower,
                'status': 'FAILED',
                'errorMessage': {'$regex': 'Insufficient wallet balance', '$options': 'i'},
                'createdAt': {'$gte': datetime.utcnow() - timedelta(hours=1)}
            })
            
            alert_sent = False
            alert_type = None
            
            if balance < 5000:
                # Critical alert
                alert_type = 'critical'
                print(f'🚨 CRITICAL: {provider.capitalize()} balance below ₦5,000! Sending email alert...')
                try:
                    # Pass None for mongo_db to avoid database object comparison issues
                    email_service = get_email_service(mongo_db=None)
                    email_result = email_service.send_provider_alert_email(
                        provider_name=provider.capitalize(),
                        balance=balance,
                        failed_count=failed_count,
                        alert_type='critical'
                    )
                    alert_sent = email_result.get('success', False)
                    print(f'✅ Critical alert email sent: {alert_sent}')
                except Exception as email_error:
                    print(f'❌ Email alert failed: {email_error}')
                    alert_sent = False
            elif balance < 10000:
                # Warning alert
                alert_type = 'warning'
                print(f'⚠️ WARNING: {provider.capitalize()} balance below ₦10,000! Sending email alert...')
                try:
                    # Pass None for mongo_db to avoid database object comparison issues
                    email_service = get_email_service(mongo_db=None)
                    email_result = email_service.send_provider_alert_email(
                        provider_name=provider.capitalize(),
                        balance=balance,
                        failed_count=failed_count,
                        alert_type='warning'
                    )
                    alert_sent = email_result.get('success', False)
                    print(f'✅ Warning alert email sent: {alert_sent}')
                except Exception as email_error:
                    print(f'❌ Email alert failed: {email_error}')
                    alert_sent = False
            
            response_data = {
                'success': True,
                'message': f'{provider.capitalize()} balance updated successfully',
                'provider': provider_lower,
                'balance': balance,
                'updatedBy': admin_email
            }
            
            if alert_sent:
                response_data['alertSent'] = True
                response_data['alertType'] = alert_type
                response_data['alertMessage'] = f'Email alert sent to admin ({alert_type})'
            
            return jsonify(response_data), 200
            
        except Exception as e:
            print(f"❌ Error updating {provider} balance: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500


    # ============================================================================
    # FAILED TRANSACTION MONITORING
    # ============================================================================

    @provider_health_bp.route('/failed-transactions', methods=['GET'])
    def get_failed_transactions():
        """
        Get recent failed transactions grouped by error type
        Helps identify liquidity issues before users complain
        """
        try:
            hours = int(request.args.get('hours', 24))
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            # Get failed transactions
            failed_txns = list(mongo.db.vas_transactions.find({
                'status': 'FAILED',
                'createdAt': {'$gte': cutoff_time}
            }).sort('createdAt', -1).limit(100))
            
            # Group by error type
            error_groups = {}
            for txn in failed_txns:
                error_msg = txn.get('errorMessage', 'Unknown error')
                
                # Categorize errors
                if 'Insufficient wallet balance' in error_msg:
                    category = 'Insufficient Balance (Peyflex)'
                elif 'Insufficient balance' in error_msg:
                    category = 'Insufficient Balance (User)'
                elif 'Invalid' in error_msg:
                    category = 'Invalid Request'
                elif 'timeout' in error_msg.lower():
                    category = 'Timeout'
                else:
                    category = 'Other'
                
                if category not in error_groups:
                    error_groups[category] = {
                        'count': 0,
                        'totalAmount': 0,
                        'examples': []
                    }
                
                error_groups[category]['count'] += 1
                error_groups[category]['totalAmount'] += float(txn.get('amount', 0))
                
                if len(error_groups[category]['examples']) < 5:
                    error_groups[category]['examples'].append({
                        'transactionId': str(txn['_id']),
                        'type': txn.get('type', 'unknown'),
                        'amount': float(txn.get('amount', 0)),
                        'phone': txn.get('phoneNumber', 'N/A'),
                        'error': error_msg,
                        'timestamp': txn.get('createdAt').isoformat()
                    })
            
            # Calculate total impact
            total_failed = sum(group['count'] for group in error_groups.values())
            total_lost_revenue = sum(group['totalAmount'] for group in error_groups.values())
            
            return jsonify({
                'success': True,
                'period': f'Last {hours} hours',
                'summary': {
                    'totalFailed': total_failed,
                    'totalLostRevenue': total_lost_revenue,
                    'errorCategories': len(error_groups)
                },
                'errorGroups': error_groups
            }), 200
            
        except Exception as e:
            print(f"❌ Error getting failed transactions: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500


    # ============================================================================
    # PROVIDER SUCCESS RATE MONITORING
    # ============================================================================

    @provider_health_bp.route('/success-rates', methods=['GET'])
    def get_provider_success_rates():
        """
        Calculate success rates for each provider
        Helps identify which provider is having issues
        """
        try:
            hours = int(request.args.get('hours', 24))
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            # Get all transactions in period
            all_txns = list(mongo.db.vas_transactions.find({
                'createdAt': {'$gte': cutoff_time}
            }))
            
            # Group by provider
            provider_stats = {}
            for txn in all_txns:
                provider = txn.get('provider')
                # Skip transactions without provider field or with None/empty provider
                if not provider:
                    provider = 'unknown'
                
                status = txn.get('status', 'UNKNOWN')
                
                if provider not in provider_stats:
                    provider_stats[provider] = {
                        'total': 0,
                        'success': 0,
                        'failed': 0,
                        'pending': 0,
                        'totalAmount': 0,
                        'successAmount': 0
                    }
                
                provider_stats[provider]['total'] += 1
                provider_stats[provider]['totalAmount'] += float(txn.get('amount', 0))
                
                if status == 'SUCCESS':
                    provider_stats[provider]['success'] += 1
                    provider_stats[provider]['successAmount'] += float(txn.get('amount', 0))
                elif status == 'FAILED':
                    provider_stats[provider]['failed'] += 1
                else:
                    provider_stats[provider]['pending'] += 1
            
            # Calculate success rates
            for provider, stats in provider_stats.items():
                if stats['total'] > 0:
                    stats['successRate'] = (stats['success'] / stats['total']) * 100
                else:
                    stats['successRate'] = 0
            
            return jsonify({
                'success': True,
                'period': f'Last {hours} hours',
                'providers': provider_stats
            }), 200
            
        except Exception as e:
            print(f"❌ Error calculating success rates: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500


    # ============================================================================
    # LIQUIDITY ALERTS (Multi-Provider Support)
    # ============================================================================

    @provider_health_bp.route('/liquidity-alerts', methods=['GET'])
    def get_liquidity_alerts():
        """
        Get active liquidity alerts for all providers
        Warns admins when provider balance is low or failures are increasing
        """
        try:
            alerts = []
            
            # Check all providers (Peyflex and Monnify)
            for provider_name in ['peyflex', 'monnify']:
                provider_balance = mongo.db.provider_balances.find_one({'provider': provider_name})
                if provider_balance:
                    balance = float(provider_balance.get('balance', 0))
                    last_updated = provider_balance.get('lastUpdated')
                    
                    # Alert if balance is low
                    if balance < 5000:
                        alerts.append({
                            'severity': 'critical',
                            'provider': provider_name,
                            'type': 'low_balance',
                            'message': f'{provider_name.capitalize()} balance critically low: ₦{balance:,.2f}',
                            'action': f'Fund {provider_name.capitalize()} wallet immediately'
                        })
                    elif balance < 10000:
                        alerts.append({
                            'severity': 'warning',
                            'provider': provider_name,
                            'type': 'low_balance',
                            'message': f'{provider_name.capitalize()} balance low: ₦{balance:,.2f}',
                            'action': f'Consider funding {provider_name.capitalize()} wallet soon'
                        })
                    
                    # Alert if balance hasn't been updated in 24 hours
                    if last_updated:
                        hours_since_update = (datetime.utcnow() - last_updated).total_seconds() / 3600
                        if hours_since_update > 24:
                            alerts.append({
                                'severity': 'warning',
                                'provider': provider_name,
                                'type': 'stale_balance',
                                'message': f'{provider_name.capitalize()} balance not updated in {int(hours_since_update)} hours',
                                'action': f'Check {provider_name.capitalize()} dashboard and update balance'
                            })
                
                # Check for recent failures
                recent_failures = mongo.db.vas_transactions.count_documents({
                    'provider': provider_name,
                    'status': 'FAILED',
                    'errorMessage': {'$regex': 'Insufficient wallet balance', '$options': 'i'},
                    'createdAt': {'$gte': datetime.utcnow() - timedelta(hours=1)}
                })
                
                if recent_failures > 0:
                    alerts.append({
                        'severity': 'critical',
                        'provider': provider_name,
                        'type': 'active_failures',
                        'message': f'{recent_failures} {provider_name.capitalize()} transactions failed in last hour due to insufficient balance',
                        'action': f'Fund {provider_name.capitalize()} wallet NOW - users are being affected'
                    })
            
            return jsonify({
                'success': True,
                'alertCount': len(alerts),
                'alerts': alerts
            }), 200
            
        except Exception as e:
            print(f"❌ Error getting liquidity alerts: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500


    # ============================================================================
    # BALANCE UPDATE HISTORY
    # ============================================================================

    @provider_health_bp.route('/balance-history', methods=['GET'])
    def get_balance_history():
        """
        Get balance update history for all providers or specific provider
        Supports filtering by provider and date range
        
        FALLBACK: If provider_balance_history collection is empty, 
        constructs history from provider_balances collection
        """
        try:
            # Get query parameters
            provider = request.args.get('provider')  # Optional: filter by provider
            days = int(request.args.get('days', 30))  # Default: last 30 days
            limit = int(request.args.get('limit', 100))  # Default: 100 records
            
            print(f"📊 Balance history request - Provider: {provider}, Days: {days}, Limit: {limit}")
            
            # Build query
            query = {}
            if provider:
                query['provider'] = provider.lower()
            
            # Add date filter
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            query['updatedAt'] = {'$gte': cutoff_date}
            
            print(f"📊 Query: {query}")
            
            # Try to get history from dedicated history collection
            history = list(mongo.db.provider_balance_history.find(
                query,
                {'_id': 0}  # Exclude MongoDB _id from response
            ).sort('updatedAt', -1).limit(limit))
            
            print(f"📊 Found {len(history)} entries in provider_balance_history collection")
            
            # FALLBACK: If no history found, construct from provider_balances collection
            if len(history) == 0:
                print(f"⚠️ No history in dedicated collection, using fallback from provider_balances")
                
                # Get current balances for all providers (or specific provider)
                balance_query = {}
                if provider:
                    balance_query['provider'] = provider.lower()
                
                balances = list(mongo.db.provider_balances.find(balance_query))
                
                print(f"📊 Found {len(balances)} entries in provider_balances collection")
                
                # Convert to history format
                for balance_entry in balances:
                    # Only include if it has been updated (has lastUpdated field)
                    if balance_entry.get('lastUpdated'):
                        history.append({
                            'provider': balance_entry.get('provider', 'unknown'),
                            'previousBalance': 0.0,  # We don't have previous balance in fallback
                            'newBalance': float(balance_entry.get('balance', 0)),
                            'change': float(balance_entry.get('balance', 0)),  # Assume all is change
                            'updatedBy': balance_entry.get('updatedBy', 'unknown'),
                            'notes': balance_entry.get('notes', 'Current balance (no history available)'),
                            'updatedAt': balance_entry.get('lastUpdated', balance_entry.get('updatedAt')),
                            'isFallback': True  # Flag to indicate this is from fallback
                        })
                
                # Sort by date
                history.sort(key=lambda x: x.get('updatedAt', datetime.min), reverse=True)
                history = history[:limit]  # Apply limit
                
                print(f"📊 Constructed {len(history)} history entries from fallback")
            
            # Format dates for JSON serialization
            for entry in history:
                if 'updatedAt' in entry and isinstance(entry['updatedAt'], datetime):
                    entry['updatedAt'] = entry['updatedAt'].isoformat()
            
            return jsonify({
                'success': True,
                'count': len(history),
                'history': history,
                'filters': {
                    'provider': provider,
                    'days': days,
                    'limit': limit
                },
                'usingFallback': any(entry.get('isFallback') for entry in history)
            }), 200
            
        except Exception as e:
            print(f"❌ Error getting balance history: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)}), 500


    @provider_health_bp.route('/balance-history/export', methods=['GET'])
    def export_balance_history():
        """
        Export balance update history as CSV
        """
        try:
            from flask import make_response
            import csv
            from io import StringIO
            
            # Get query parameters
            provider = request.args.get('provider')
            days = int(request.args.get('days', 30))
            
            # Build query
            query = {}
            if provider:
                query['provider'] = provider.lower()
            
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            query['updatedAt'] = {'$gte': cutoff_date}
            
            # Get history entries
            history = list(mongo.db.provider_balance_history.find(query).sort('updatedAt', -1))
            
            # Create CSV
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Date/Time',
                'Provider',
                'Previous Balance',
                'New Balance',
                'Change',
                'Updated By',
                'Notes'
            ])
            
            # Write data
            for entry in history:
                writer.writerow([
                    entry.get('updatedAt', '').strftime('%Y-%m-%d %H:%M:%S') if entry.get('updatedAt') else '',
                    entry.get('provider', '').capitalize(),
                    f"₦{entry.get('previousBalance', 0):,.2f}",
                    f"₦{entry.get('newBalance', 0):,.2f}",
                    f"₦{entry.get('change', 0):,.2f}",
                    entry.get('updatedBy', ''),
                    entry.get('notes', '')
                ])
            
            # Create response
            output.seek(0)
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename=provider_balance_history_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            
            return response
            
        except Exception as e:
            print(f"❌ Error exporting balance history: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # Return the initialized blueprint
    return provider_health_bp
