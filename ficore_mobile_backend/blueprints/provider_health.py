"""
Provider Health Monitoring Blueprint
Tracks VAS provider balance, success rates, and liquidity issues
"""

from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
from bson import ObjectId

def init_provider_health_blueprint(mongo, token_required):
    """Initialize the provider health blueprint with database and auth decorator"""
    provider_health_bp = Blueprint('provider_health', __name__, url_prefix='/api/admin/provider-health')
    
    # ============================================================================
    # PEYFLEX BALANCE TRACKING (Manual Entry + Automated Monitoring)
    # ============================================================================
    
    @provider_health_bp.route('/peyflex/balance', methods=['GET'])
    def get_peyflex_balance():
    """
    Get current Peyflex balance (manually entered by admin)
    Since Peyflex has no API for balance checking, admins must update this manually
    """
    try:
        # Get latest balance entry
        balance_entry = mongo.db.provider_balances.find_one(
            {'provider': 'peyflex'},
            sort=[('updatedAt', -1)]
        )
        
        if not balance_entry:
            # No balance entry yet - create default
            balance_entry = {
                'provider': 'peyflex',
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
            'provider': 'peyflex',
            'status': 'FAILED',
            'errorMessage': {'$regex': 'Insufficient wallet balance', '$options': 'i'},
            'createdAt': {'$gte': datetime.utcnow() - timedelta(hours=24)}
        })
        
        return jsonify({
            'success': True,
            'balance': float(balance_entry.get('balance', 0)),
            'lastUpdated': last_updated.isoformat() if last_updated else None,
            'hoursSinceUpdate': round(hours_since_update, 1) if hours_since_update else None,
            'updatedBy': balance_entry.get('updatedBy', 'unknown'),
            'notes': balance_entry.get('notes', ''),
            'recentFailures': failed_count,
            'needsUpdate': hours_since_update > 24 if hours_since_update else True
        }), 200
        
    except Exception as e:
        print(f"❌ Error getting Peyflex balance: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@provider_health_bp.route('/peyflex/balance', methods=['POST'])
def update_peyflex_balance():
    """
    Update Peyflex balance (admin manually enters after checking Peyflex dashboard)
    """
    try:
        data = request.get_json()
        balance = float(data.get('balance', 0))
        admin_email = data.get('adminEmail', 'unknown')
        notes = data.get('notes', '')
        
        # Update or create balance entry
        result = mongo.db.provider_balances.update_one(
            {'provider': 'peyflex'},
            {
                '$set': {
                    'balance': balance,
                    'lastUpdated': datetime.utcnow(),
                    'updatedBy': admin_email,
                    'notes': notes,
                    'updatedAt': datetime.utcnow()
                },
                '$setOnInsert': {
                    'provider': 'peyflex',
                    'createdAt': datetime.utcnow()
                }
            },
            upsert=True
        )
        
        print(f"✅ Peyflex balance updated: ₦{balance:,.2f} by {admin_email}")
        
        return jsonify({
            'success': True,
            'message': 'Peyflex balance updated successfully',
            'balance': balance,
            'updatedBy': admin_email
        }), 200
        
    except Exception as e:
        print(f"❌ Error updating Peyflex balance: {e}")
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
            provider = txn.get('provider', 'unknown')
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
# LIQUIDITY ALERTS
# ============================================================================

@provider_health_bp.route('/liquidity-alerts', methods=['GET'])
def get_liquidity_alerts():
    """
    Get active liquidity alerts
    Warns admins when provider balance is low or failures are increasing
    """
    try:
        alerts = []
        
        # Check Peyflex balance
        peyflex_balance = mongo.db.provider_balances.find_one({'provider': 'peyflex'})
        if peyflex_balance:
            balance = float(peyflex_balance.get('balance', 0))
            last_updated = peyflex_balance.get('lastUpdated')
            
            # Alert if balance is low
            if balance < 5000:
                alerts.append({
                    'severity': 'critical',
                    'provider': 'peyflex',
                    'type': 'low_balance',
                    'message': f'Peyflex balance critically low: ₦{balance:,.2f}',
                    'action': 'Fund Peyflex wallet immediately'
                })
            elif balance < 10000:
                alerts.append({
                    'severity': 'warning',
                    'provider': 'peyflex',
                    'type': 'low_balance',
                    'message': f'Peyflex balance low: ₦{balance:,.2f}',
                    'action': 'Consider funding Peyflex wallet soon'
                })
            
            # Alert if balance hasn't been updated in 24 hours
            if last_updated:
                hours_since_update = (datetime.utcnow() - last_updated).total_seconds() / 3600
                if hours_since_update > 24:
                    alerts.append({
                        'severity': 'warning',
                        'provider': 'peyflex',
                        'type': 'stale_balance',
                        'message': f'Peyflex balance not updated in {int(hours_since_update)} hours',
                        'action': 'Check Peyflex dashboard and update balance'
                    })
        
        # Check for recent failures
        recent_failures = mongo.db.vas_transactions.count_documents({
            'provider': 'peyflex',
            'status': 'FAILED',
            'errorMessage': {'$regex': 'Insufficient wallet balance', '$options': 'i'},
            'createdAt': {'$gte': datetime.utcnow() - timedelta(hours=1)}
        })
        
        if recent_failures > 0:
            alerts.append({
                'severity': 'critical',
                'provider': 'peyflex',
                'type': 'active_failures',
                'message': f'{recent_failures} transactions failed in last hour due to insufficient balance',
                'action': 'Fund Peyflex wallet NOW - users are being affected'
            })
        
        return jsonify({
            'success': True,
            'alertCount': len(alerts),
            'alerts': alerts
        }), 200
        
    except Exception as e:
        print(f"❌ Error getting liquidity alerts: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

    # Return the initialized blueprint
    return provider_health_bp
