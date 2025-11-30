from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
from collections import defaultdict

def init_dashboard_blueprint(mongo, token_required, serialize_doc):
    """Initialize the enhanced dashboard blueprint with database and auth decorator"""
    dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

    def get_date_range(period='monthly'):
        """Get date range for analytics"""
        now = datetime.utcnow()
        
        if period == 'weekly':
            start_date = now - timedelta(days=7)
        elif period == 'monthly':
            start_date = now - timedelta(days=30)
        elif period == 'quarterly':
            start_date = now - timedelta(days=90)
        elif period == 'yearly':
            start_date = now - timedelta(days=365)
        else:
            start_date = now - timedelta(days=30)  # Default to monthly
        
        return start_date, now

    def calculate_profit_metrics(user_id, start_date, end_date):
        """Calculate comprehensive profit metrics including COGS"""
        try:
            # Get income data
            incomes = list(mongo.db.incomes.find({
                'userId': user_id,
                'dateReceived': {'$gte': start_date, '$lte': end_date}
            }))
            
            # Get expense data
            expenses = list(mongo.db.expenses.find({
                'userId': user_id,
                'date': {'$gte': start_date, '$lte': end_date}
            }))
            
            # Calculate totals
            total_revenue = sum(income['amount'] for income in incomes)
            total_expenses = sum(expense['amount'] for expense in expenses)
            
            # Separate COGS from other expenses
            cogs_expenses = [exp for exp in expenses if exp.get('category') == 'Cost of Goods Sold']
            other_expenses = [exp for exp in expenses if exp.get('category') != 'Cost of Goods Sold']
            
            total_cogs = sum(exp['amount'] for exp in cogs_expenses)
            total_operating_expenses = sum(exp['amount'] for exp in other_expenses)
            
            # Calculate profit metrics
            gross_profit = total_revenue - total_cogs
            net_profit = total_revenue - total_expenses
            
            # Calculate margins
            gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
            net_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
            
            return {
                'totalRevenue': total_revenue,
                'totalCogs': total_cogs,
                'totalOperatingExpenses': total_operating_expenses,
                'totalExpenses': total_expenses,
                'grossProfit': gross_profit,
                'netProfit': net_profit,
                'grossMargin': round(gross_margin, 2),
                'netMargin': round(net_margin, 2)
            }
            
        except Exception as e:
            print(f"Error calculating profit metrics: {str(e)}")
            return {
                'totalRevenue': 0,
                'totalCogs': 0,
                'totalOperatingExpenses': 0,
                'totalExpenses': 0,
                'grossProfit': 0,
                'netProfit': 0,
                'grossMargin': 0,
                'netMargin': 0
            }

    def get_alerts_and_reminders(user_id):
        """Get system alerts and reminders"""
        alerts = []
        
        try:
            # Low stock alerts
            low_stock_items = list(mongo.db.inventory_items.find({
                'userId': user_id,
                '$expr': {'$lte': ['$currentStock', '$minimumStock']}
            }))
            
            for item in low_stock_items:
                alerts.append({
                    'type': 'low_stock',
                    'severity': 'warning' if item['currentStock'] > 0 else 'critical',
                    'title': 'Low Stock Alert',
                    'message': f"{item['itemName']} is running low (Stock: {item['currentStock']}, Min: {item['minimumStock']})",
                    'itemId': str(item['_id']),
                    'itemName': item['itemName'],
                    'currentStock': item['currentStock'],
                    'minimumStock': item['minimumStock']
                })
            
            # Overdue debtors
            overdue_debtors = list(mongo.db.debtors.find({
                'userId': user_id,
                'status': 'overdue',
                'remainingDebt': {'$gt': 0}
            }))
            
            for debtor in overdue_debtors:
                alerts.append({
                    'type': 'overdue_debt',
                    'severity': 'high' if debtor.get('overdueDays', 0) > 30 else 'medium',
                    'title': 'Overdue Payment',
                    'message': f"{debtor['customerName']} payment is {debtor.get('overdueDays', 0)} days overdue (₦{debtor['remainingDebt']:,.2f})",
                    'debtorId': str(debtor['_id']),
                    'customerName': debtor['customerName'],
                    'remainingDebt': debtor['remainingDebt'],
                    'overdueDays': debtor.get('overdueDays', 0)
                })
            
            # Overdue creditors (payments we owe)
            overdue_creditors = list(mongo.db.creditors.find({
                'userId': user_id,
                'status': 'overdue',
                'remainingOwed': {'$gt': 0}
            }))
            
            for creditor in overdue_creditors:
                alerts.append({
                    'type': 'overdue_payment',
                    'severity': 'high' if creditor.get('overdueDays', 0) > 30 else 'medium',
                    'title': 'Payment Due',
                    'message': f"Payment to {creditor['vendorName']} is {creditor.get('overdueDays', 0)} days overdue (₦{creditor['remainingOwed']:,.2f})",
                    'creditorId': str(creditor['_id']),
                    'vendorName': creditor['vendorName'],
                    'remainingOwed': creditor['remainingOwed'],
                    'overdueDays': creditor.get('overdueDays', 0)
                })
            
            # Expiring inventory
            thirty_days_from_now = datetime.utcnow() + timedelta(days=30)
            expiring_items = list(mongo.db.inventory_items.find({
                'userId': user_id,
                'expiryDate': {
                    '$gte': datetime.utcnow(),
                    '$lte': thirty_days_from_now
                },
                'currentStock': {'$gt': 0}
            }))
            
            for item in expiring_items:
                days_to_expiry = (item['expiryDate'] - datetime.utcnow()).days
                alerts.append({
                    'type': 'expiring_inventory',
                    'severity': 'warning' if days_to_expiry > 7 else 'high',
                    'title': 'Expiring Inventory',
                    'message': f"{item['itemName']} expires in {days_to_expiry} days (Stock: {item['currentStock']})",
                    'itemId': str(item['_id']),
                    'itemName': item['itemName'],
                    'expiryDate': item['expiryDate'].isoformat() + 'Z',
                    'daysToExpiry': days_to_expiry,
                    'currentStock': item['currentStock']
                })
            
            # Sort alerts by severity
            severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'warning': 3, 'info': 4}
            alerts.sort(key=lambda x: severity_order.get(x['severity'], 5))
            
            return alerts
            
        except Exception as e:
            print(f"Error getting alerts: {str(e)}")
            return []

    def get_recent_activity(user_id, limit=20):
        """Get recent activity across all modules"""
        activities = []
        
        try:
            # Recent income transactions
            recent_incomes = list(mongo.db.incomes.find({
                'userId': user_id
            }).sort('dateReceived', -1).limit(limit // 4))
            
            for income in recent_incomes:
                activities.append({
                    'type': 'income',
                    'title': f'Income: {income["source"]}',
                    'description': income.get('description', ''),
                    'amount': income['amount'],
                    'date': income['dateReceived'],
                    'category': income.get('category', ''),
                    'id': str(income['_id'])
                })
            
            # Recent expense transactions
            recent_expenses = list(mongo.db.expenses.find({
                'userId': user_id
            }).sort('date', -1).limit(limit // 4))
            
            for expense in recent_expenses:
                activities.append({
                    'type': 'expense',
                    'title': f'Expense: {expense.get("title", expense["description"])}',
                    'description': expense['description'],
                    'amount': expense['amount'],
                    'date': expense['date'],
                    'category': expense.get('category', ''),
                    'id': str(expense['_id'])
                })
            
            # Recent debtor transactions
            recent_debtor_transactions = list(mongo.db.debtor_transactions.find({
                'userId': user_id
            }).sort('transactionDate', -1).limit(limit // 4))
            
            # Get debtor names
            debtor_ids = [trans['debtorId'] for trans in recent_debtor_transactions]
            debtors = {debtor['_id']: debtor['customerName'] for debtor in mongo.db.debtors.find({'_id': {'$in': debtor_ids}})}
            
            for transaction in recent_debtor_transactions:
                customer_name = debtors.get(transaction['debtorId'], 'Unknown Customer')
                activities.append({
                    'type': 'debtor_transaction',
                    'title': f'{transaction["type"].title()}: {customer_name}',
                    'description': transaction['description'],
                    'amount': transaction['amount'],
                    'date': transaction['transactionDate'],
                    'transactionType': transaction['type'],
                    'customerName': customer_name,
                    'id': str(transaction['_id'])
                })
            
            # Recent inventory movements
            recent_movements = list(mongo.db.inventory_movements.find({
                'userId': user_id
            }).sort('movementDate', -1).limit(limit // 4))
            
            # Get item names
            item_ids = [movement['itemId'] for movement in recent_movements]
            items = {item['_id']: item['itemName'] for item in mongo.db.inventory_items.find({'_id': {'$in': item_ids}})}
            
            for movement in recent_movements:
                item_name = items.get(movement['itemId'], 'Unknown Item')
                activities.append({
                    'type': 'inventory_movement',
                    'title': f'Stock {movement["movementType"].title()}: {item_name}',
                    'description': f'{movement["reason"]} - {movement["quantity"]} units',
                    'amount': movement.get('totalCost', 0),
                    'date': movement['movementDate'],
                    'movementType': movement['movementType'],
                    'quantity': movement['quantity'],
                    'itemName': item_name,
                    'id': str(movement['_id'])
                })
            
            # Sort all activities by date (most recent first)
            activities.sort(key=lambda x: x['date'], reverse=True)
            
            # Format dates and limit results
            for activity in activities[:limit]:
                activity['date'] = activity['date'].isoformat() + 'Z'
            
            return activities[:limit]
            
        except Exception as e:
            print(f"Error getting recent activity: {str(e)}")
            return []

    # ==================== DASHBOARD ENDPOINTS ====================

    @dashboard_bp.route('/overview', methods=['GET'])
    @token_required
    def get_overview(current_user):
        """Get comprehensive dashboard overview"""
        try:
            period = request.args.get('period', 'monthly')
            start_date, end_date = get_date_range(period)
            
            # Get profit metrics
            profit_metrics = calculate_profit_metrics(current_user['_id'], start_date, end_date)
            
            # Get module summaries
            # Income summary
            total_income = mongo.db.incomes.aggregate([
                {'$match': {'userId': current_user['_id']}},
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ])
            total_income = list(total_income)
            total_income_amount = total_income[0]['total'] if total_income else 0
            
            # Expense summary
            total_expenses = mongo.db.expenses.aggregate([
                {'$match': {'userId': current_user['_id']}},
                {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
            ])
            total_expenses = list(total_expenses)
            total_expenses_amount = total_expenses[0]['total'] if total_expenses else 0
            
            # Debtors summary
            debtors_summary = mongo.db.debtors.aggregate([
                {'$match': {'userId': current_user['_id']}},
                {'$group': {
                    '_id': None,
                    'totalCustomers': {'$sum': 1},
                    'totalDebt': {'$sum': '$totalDebt'},
                    'totalOutstanding': {'$sum': '$remainingDebt'},
                    'overdueCustomers': {
                        '$sum': {'$cond': [{'$eq': ['$status', 'overdue']}, 1, 0]}
                    }
                }}
            ])
            debtors_summary = list(debtors_summary)
            debtors_data = debtors_summary[0] if debtors_summary else {
                'totalCustomers': 0, 'totalDebt': 0, 'totalOutstanding': 0, 'overdueCustomers': 0
            }
            
            # Creditors summary
            creditors_summary = mongo.db.creditors.aggregate([
                {'$match': {'userId': current_user['_id']}},
                {'$group': {
                    '_id': None,
                    'totalVendors': {'$sum': 1},
                    'totalOwed': {'$sum': '$totalOwed'},
                    'totalOutstanding': {'$sum': '$remainingOwed'},
                    'overdueVendors': {
                        '$sum': {'$cond': [{'$eq': ['$status', 'overdue']}, 1, 0]}
                    }
                }}
            ])
            creditors_summary = list(creditors_summary)
            creditors_data = creditors_summary[0] if creditors_summary else {
                'totalVendors': 0, 'totalOwed': 0, 'totalOutstanding': 0, 'overdueVendors': 0
            }
            
            # Inventory summary
            inventory_summary = mongo.db.inventory_items.aggregate([
                {'$match': {'userId': current_user['_id']}},
                {'$group': {
                    '_id': None,
                    'totalItems': {'$sum': 1},
                    'totalValue': {'$sum': {'$multiply': ['$currentStock', '$costPrice']}},
                    'lowStockItems': {
                        '$sum': {'$cond': [{'$lte': ['$currentStock', '$minimumStock']}, 1, 0]}
                    },
                    'outOfStockItems': {
                        '$sum': {'$cond': [{'$eq': ['$currentStock', 0]}, 1, 0]}
                    }
                }}
            ])
            inventory_summary = list(inventory_summary)
            inventory_data = inventory_summary[0] if inventory_summary else {
                'totalItems': 0, 'totalValue': 0, 'lowStockItems': 0, 'outOfStockItems': 0
            }
            
            # Get alerts
            alerts = get_alerts_and_reminders(current_user['_id'])
            
            # Get recent activity
            recent_activity = get_recent_activity(current_user['_id'], 10)
            
            # Calculate key performance indicators
            kpis = {
                'totalRevenue': profit_metrics['totalRevenue'],
                'totalProfit': profit_metrics['netProfit'],
                'profitMargin': profit_metrics['netMargin'],
                'totalCustomers': debtors_data['totalCustomers'],
                'totalVendors': creditors_data['totalVendors'],
                'totalInventoryValue': inventory_data['totalValue'],
                'outstandingReceivables': debtors_data['totalOutstanding'],
                'outstandingPayables': creditors_data['totalOutstanding'],
                'alertsCount': len(alerts),
                'criticalAlertsCount': len([a for a in alerts if a['severity'] in ['critical', 'high']])
            }
            
            overview_data = {
                'period': period,
                'dateRange': {
                    'startDate': start_date.isoformat() + 'Z',
                    'endDate': end_date.isoformat() + 'Z'
                },
                'kpis': kpis,
                'profitMetrics': profit_metrics,
                'moduleSummaries': {
                    'income': {
                        'totalAmount': total_income_amount,
                        'periodAmount': profit_metrics['totalRevenue']
                    },
                    'expenses': {
                        'totalAmount': total_expenses_amount,
                        'periodAmount': profit_metrics['totalExpenses']
                    },
                    'debtors': debtors_data,
                    'creditors': creditors_data,
                    'inventory': inventory_data
                },
                'alerts': alerts[:5],  # Top 5 alerts
                'recentActivity': recent_activity
            }
            
            return jsonify({
                'success': True,
                'data': overview_data,
                'message': 'Dashboard overview retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve dashboard overview',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/alerts', methods=['GET'])
    @token_required
    def get_alerts(current_user):
        """Get all system alerts and notifications"""
        try:
            alerts = get_alerts_and_reminders(current_user['_id'])
            
            # Group alerts by type
            alerts_by_type = defaultdict(list)
            for alert in alerts:
                alerts_by_type[alert['type']].append(alert)
            
            # Count alerts by severity
            severity_counts = defaultdict(int)
            for alert in alerts:
                severity_counts[alert['severity']] += 1
            
            alerts_data = {
                'totalAlerts': len(alerts),
                'severityCounts': dict(severity_counts),
                'alertsByType': dict(alerts_by_type),
                'allAlerts': alerts
            }
            
            return jsonify({
                'success': True,
                'data': alerts_data,
                'message': 'Alerts retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve alerts',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/recent-activity', methods=['GET'])
    @token_required
    def get_recent_activity_endpoint(current_user):
        """Get recent activity feed"""
        try:
            limit = int(request.args.get('limit', 20))
            activity_type = request.args.get('type')  # Filter by activity type
            
            activities = get_recent_activity(current_user['_id'], limit * 2)  # Get more to filter
            
            # Filter by type if specified
            if activity_type:
                activities = [a for a in activities if a['type'] == activity_type]
            
            # Limit results
            activities = activities[:limit]
            
            return jsonify({
                'success': True,
                'data': activities,
                'message': 'Recent activity retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve recent activity',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/reminders', methods=['GET'])
    @token_required
    def get_reminders(current_user):
        """Get payment reminders and due dates"""
        try:
            now = datetime.utcnow()
            next_30_days = now + timedelta(days=30)
            
            reminders = []
            
            # Debtor payment reminders
            upcoming_debtor_payments = list(mongo.db.debtors.find({
                'userId': current_user['_id'],
                'nextPaymentDue': {
                    '$gte': now,
                    '$lte': next_30_days
                },
                'remainingDebt': {'$gt': 0}
            }).sort('nextPaymentDue', 1))
            
            for debtor in upcoming_debtor_payments:
                days_until_due = (debtor['nextPaymentDue'] - now).days
                reminders.append({
                    'type': 'debtor_payment_due',
                    'title': f'Payment Due: {debtor["customerName"]}',
                    'description': f'Payment of ₦{debtor["remainingDebt"]:,.2f} due in {days_until_due} days',
                    'dueDate': debtor['nextPaymentDue'].isoformat() + 'Z',
                    'daysUntilDue': days_until_due,
                    'amount': debtor['remainingDebt'],
                    'customerName': debtor['customerName'],
                    'debtorId': str(debtor['_id']),
                    'priority': 'high' if days_until_due <= 7 else 'medium'
                })
            
            # Creditor payment reminders
            upcoming_creditor_payments = list(mongo.db.creditors.find({
                'userId': current_user['_id'],
                'nextPaymentDue': {
                    '$gte': now,
                    '$lte': next_30_days
                },
                'remainingOwed': {'$gt': 0}
            }).sort('nextPaymentDue', 1))
            
            for creditor in upcoming_creditor_payments:
                days_until_due = (creditor['nextPaymentDue'] - now).days
                reminders.append({
                    'type': 'creditor_payment_due',
                    'title': f'Payment Due: {creditor["vendorName"]}',
                    'description': f'Payment of ₦{creditor["remainingOwed"]:,.2f} due in {days_until_due} days',
                    'dueDate': creditor['nextPaymentDue'].isoformat() + 'Z',
                    'daysUntilDue': days_until_due,
                    'amount': creditor['remainingOwed'],
                    'vendorName': creditor['vendorName'],
                    'creditorId': str(creditor['_id']),
                    'priority': 'high' if days_until_due <= 7 else 'medium'
                })
            
            # Sort by due date
            reminders.sort(key=lambda x: x['daysUntilDue'])
            
            return jsonify({
                'success': True,
                'data': reminders,
                'message': 'Reminders retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve reminders',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/profit-analysis', methods=['GET'])
    @token_required
    def get_profit_analysis(current_user):
        """Get detailed profit analysis with trends"""
        try:
            period = request.args.get('period', 'monthly')
            
            # Get data for different time periods for comparison
            periods = {
                'current': get_date_range(period),
                'previous': None
            }
            
            # Calculate previous period
            current_start, current_end = periods['current']
            period_length = current_end - current_start
            previous_end = current_start
            previous_start = previous_end - period_length
            periods['previous'] = (previous_start, previous_end)
            
            analysis_data = {}
            
            for period_name, (start_date, end_date) in periods.items():
                metrics = calculate_profit_metrics(current_user['_id'], start_date, end_date)
                analysis_data[period_name] = {
                    'dateRange': {
                        'startDate': start_date.isoformat() + 'Z',
                        'endDate': end_date.isoformat() + 'Z'
                    },
                    'metrics': metrics
                }
            
            # Calculate growth rates
            current_metrics = analysis_data['current']['metrics']
            previous_metrics = analysis_data['previous']['metrics']
            
            growth_rates = {}
            for key in ['totalRevenue', 'grossProfit', 'netProfit']:
                current_value = current_metrics[key]
                previous_value = previous_metrics[key]
                
                if previous_value != 0:
                    growth_rate = ((current_value - previous_value) / previous_value) * 100
                else:
                    growth_rate = 100 if current_value > 0 else 0
                
                growth_rates[key] = round(growth_rate, 2)
            
            # Get monthly trends for the last 12 months
            monthly_trends = []
            for i in range(12):
                month_end = datetime.utcnow().replace(day=1) - timedelta(days=i*30)
                month_start = month_end - timedelta(days=30)
                
                month_metrics = calculate_profit_metrics(current_user['_id'], month_start, month_end)
                monthly_trends.append({
                    'month': month_start.strftime('%Y-%m'),
                    'revenue': month_metrics['totalRevenue'],
                    'grossProfit': month_metrics['grossProfit'],
                    'netProfit': month_metrics['netProfit'],
                    'grossMargin': month_metrics['grossMargin'],
                    'netMargin': month_metrics['netMargin']
                })
            
            monthly_trends.reverse()  # Oldest to newest
            
            profit_analysis = {
                'currentPeriod': analysis_data['current'],
                'previousPeriod': analysis_data['previous'],
                'growthRates': growth_rates,
                'monthlyTrends': monthly_trends,
                'insights': {
                    'revenueGrowth': growth_rates['totalRevenue'],
                    'profitabilityTrend': 'improving' if growth_rates['netProfit'] > 0 else 'declining',
                    'marginTrend': 'improving' if current_metrics['netMargin'] > previous_metrics['netMargin'] else 'declining'
                }
            }
            
            return jsonify({
                'success': True,
                'data': profit_analysis,
                'message': 'Profit analysis retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve profit analysis',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== MODULE-SPECIFIC SUMMARY ENDPOINTS ====================

    @dashboard_bp.route('/income-summary', methods=['GET'])
    @token_required
    def get_income_summary(current_user):
        """Get income module summary for dashboard"""
        try:
            period = request.args.get('period', 'monthly')
            start_date, end_date = get_date_range(period)
            
            # Get income data for period
            incomes = list(mongo.db.incomes.find({
                'userId': current_user['_id'],
                'dateReceived': {'$gte': start_date, '$lte': end_date}
            }))
            
            # Calculate summary
            total_income = sum(income['amount'] for income in incomes)
            income_count = len(incomes)
            
            # Group by source
            income_by_source = defaultdict(float)
            for income in incomes:
                income_by_source[income['source']] += income['amount']
            
            # Group by category
            income_by_category = defaultdict(float)
            for income in incomes:
                income_by_category[income.get('category', 'Other')] += income['amount']
            
            # Recent incomes
            recent_incomes = sorted(incomes, key=lambda x: x['dateReceived'], reverse=True)[:5]
            recent_income_data = []
            for income in recent_incomes:
                income_data = serialize_doc(income.copy())
                income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
                recent_income_data.append(income_data)
            
            summary_data = {
                'period': period,
                'totalIncome': total_income,
                'incomeCount': income_count,
                'averageIncome': total_income / income_count if income_count > 0 else 0,
                'incomeBySource': dict(income_by_source),
                'incomeByCategory': dict(income_by_category),
                'recentIncomes': recent_income_data
            }
            
            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Income summary retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income summary',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/expense-summary', methods=['GET'])
    @token_required
    def get_expense_summary(current_user):
        """Get expense module summary for dashboard"""
        try:
            period = request.args.get('period', 'monthly')
            start_date, end_date = get_date_range(period)
            
            # Get expense data for period
            expenses = list(mongo.db.expenses.find({
                'userId': current_user['_id'],
                'date': {'$gte': start_date, '$lte': end_date}
            }))
            
            # Calculate summary
            total_expenses = sum(expense['amount'] for expense in expenses)
            expense_count = len(expenses)
            
            # Group by category
            expense_by_category = defaultdict(float)
            for expense in expenses:
                expense_by_category[expense.get('category', 'Other')] += expense['amount']
            
            # Separate COGS from other expenses
            cogs_expenses = [exp for exp in expenses if exp.get('category') == 'Cost of Goods Sold']
            operating_expenses = [exp for exp in expenses if exp.get('category') != 'Cost of Goods Sold']
            
            total_cogs = sum(exp['amount'] for exp in cogs_expenses)
            total_operating = sum(exp['amount'] for exp in operating_expenses)
            
            # Recent expenses
            recent_expenses = sorted(expenses, key=lambda x: x['date'], reverse=True)[:5]
            recent_expense_data = []
            for expense in recent_expenses:
                expense_data = serialize_doc(expense.copy())
                expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
                recent_expense_data.append(expense_data)
            
            summary_data = {
                'period': period,
                'totalExpenses': total_expenses,
                'totalCogs': total_cogs,
                'totalOperating': total_operating,
                'expenseCount': expense_count,
                'averageExpense': total_expenses / expense_count if expense_count > 0 else 0,
                'expenseByCategory': dict(expense_by_category),
                'recentExpenses': recent_expense_data
            }
            
            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Expense summary retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense summary',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/debtors-summary', methods=['GET'])
    @token_required
    def get_debtors_summary(current_user):
        """Get debtors module summary for dashboard"""
        try:
            # Get all debtors for user
            debtors = list(mongo.db.debtors.find({'userId': current_user['_id']}))
            
            # Calculate summary metrics
            total_customers = len(debtors)
            total_debt = sum(debtor['totalDebt'] for debtor in debtors)
            total_outstanding = sum(debtor['remainingDebt'] for debtor in debtors)
            total_paid = total_debt - total_outstanding
            
            # Status breakdown
            active_customers = len([d for d in debtors if d['status'] == 'active'])
            overdue_customers = len([d for d in debtors if d['status'] == 'overdue'])
            paid_customers = len([d for d in debtors if d['status'] == 'paid'])
            
            # Overdue amount
            overdue_amount = sum(debtor['remainingDebt'] for debtor in debtors if debtor['status'] == 'overdue')
            
            # Payment rate calculation
            payment_rate = (total_paid / total_debt * 100) if total_debt > 0 else 0
            
            # Top debtors by outstanding amount
            top_debtors = sorted(debtors, key=lambda x: x['remainingDebt'], reverse=True)[:5]
            top_debtors_data = []
            for debtor in top_debtors:
                debtor_data = serialize_doc(debtor.copy())
                top_debtors_data.append(debtor_data)
            
            # Recent transactions
            recent_transactions = list(mongo.db.debtor_transactions.find({
                'userId': current_user['_id']
            }).sort('transactionDate', -1).limit(5))
            
            recent_transaction_data = []
            for transaction in recent_transactions:
                transaction_data = serialize_doc(transaction.copy())
                transaction_data['transactionDate'] = transaction_data.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
                recent_transaction_data.append(transaction_data)
            
            summary_data = {
                'totalCustomers': total_customers,
                'activeCustomers': active_customers,
                'overdueCustomers': overdue_customers,
                'paidCustomers': paid_customers,
                'totalDebt': total_debt,
                'totalOutstanding': total_outstanding,
                'totalPaid': total_paid,
                'overdueAmount': overdue_amount,
                'paymentRate': round(payment_rate, 2),
                'topDebtors': top_debtors_data,
                'recentTransactions': recent_transaction_data
            }
            
            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Debtors summary retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve debtors summary',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/creditors-summary', methods=['GET'])
    @token_required
    def get_creditors_summary(current_user):
        """Get creditors module summary for dashboard"""
        try:
            # Get all creditors for user
            creditors = list(mongo.db.creditors.find({'userId': current_user['_id']}))
            
            # Calculate summary metrics
            total_vendors = len(creditors)
            total_owed = sum(creditor['totalOwed'] for creditor in creditors)
            total_outstanding = sum(creditor['remainingOwed'] for creditor in creditors)
            total_paid = total_owed - total_outstanding
            
            # Status breakdown
            active_vendors = len([c for c in creditors if c['status'] == 'active'])
            overdue_vendors = len([c for c in creditors if c['status'] == 'overdue'])
            paid_vendors = len([c for c in creditors if c['status'] == 'paid'])
            
            # Overdue amount
            overdue_amount = sum(creditor['remainingOwed'] for creditor in creditors if creditor['status'] == 'overdue')
            
            # Payment rate calculation
            payment_rate = (total_paid / total_owed * 100) if total_owed > 0 else 0
            
            # Top creditors by outstanding amount
            top_creditors = sorted(creditors, key=lambda x: x['remainingOwed'], reverse=True)[:5]
            top_creditors_data = []
            for creditor in top_creditors:
                creditor_data = serialize_doc(creditor.copy())
                top_creditors_data.append(creditor_data)
            
            # Recent transactions
            recent_transactions = list(mongo.db.creditor_transactions.find({
                'userId': current_user['_id']
            }).sort('transactionDate', -1).limit(5))
            
            recent_transaction_data = []
            for transaction in recent_transactions:
                transaction_data = serialize_doc(transaction.copy())
                transaction_data['transactionDate'] = transaction_data.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
                recent_transaction_data.append(transaction_data)
            
            summary_data = {
                'totalVendors': total_vendors,
                'activeVendors': active_vendors,
                'overdueVendors': overdue_vendors,
                'paidVendors': paid_vendors,
                'totalOwed': total_owed,
                'totalOutstanding': total_outstanding,
                'totalPaid': total_paid,
                'overdueAmount': overdue_amount,
                'paymentRate': round(payment_rate, 2),
                'topCreditors': top_creditors_data,
                'recentTransactions': recent_transaction_data
            }
            
            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Creditors summary retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve creditors summary',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/inventory-summary', methods=['GET'])
    @token_required
    def get_inventory_summary(current_user):
        """Get inventory module summary for dashboard"""
        try:
            # Get all inventory items for user
            items = list(mongo.db.inventory_items.find({'userId': current_user['_id']}))
            
            # Calculate summary metrics
            total_items = len(items)
            total_stock = sum(item['currentStock'] for item in items)
            total_value = sum(item['currentStock'] * item['costPrice'] for item in items)
            
            # Stock status breakdown
            in_stock_items = len([item for item in items if item['currentStock'] > item['minimumStock']])
            low_stock_items = len([item for item in items if 0 < item['currentStock'] <= item['minimumStock']])
            out_of_stock_items = len([item for item in items if item['currentStock'] == 0])
            
            # Category breakdown
            category_breakdown = defaultdict(lambda: {'items': 0, 'value': 0, 'stock': 0})
            for item in items:
                category = item.get('category', 'Other')
                category_breakdown[category]['items'] += 1
                category_breakdown[category]['stock'] += item['currentStock']
                category_breakdown[category]['value'] += item['currentStock'] * item['costPrice']
            
            # Low stock alerts
            low_stock_alerts = []
            for item in items:
                if item['currentStock'] <= item['minimumStock']:
                    low_stock_alerts.append({
                        'itemId': str(item['_id']),
                        'itemName': item['itemName'],
                        'currentStock': item['currentStock'],
                        'minimumStock': item['minimumStock'],
                        'status': 'out_of_stock' if item['currentStock'] == 0 else 'low_stock'
                    })
            
            # Recent movements
            recent_movements = list(mongo.db.inventory_movements.find({
                'userId': current_user['_id']
            }).sort('movementDate', -1).limit(10))
            
            recent_movement_data = []
            for movement in recent_movements:
                movement_data = serialize_doc(movement.copy())
                movement_data['movementDate'] = movement_data.get('movementDate', datetime.utcnow()).isoformat() + 'Z'
                recent_movement_data.append(movement_data)
            
            summary_data = {
                'totalItems': total_items,
                'totalStock': total_stock,
                'totalValue': total_value,
                'inStockItems': in_stock_items,
                'lowStockItems': low_stock_items,
                'outOfStockItems': out_of_stock_items,
                'categoryBreakdown': dict(category_breakdown),
                'lowStockAlerts': low_stock_alerts,
                'recentMovements': recent_movement_data,
                'averageItemValue': total_value / total_items if total_items > 0 else 0
            }
            
            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Inventory summary retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve inventory summary',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/analytics', methods=['GET'])
    @token_required
    def get_analytics_data(current_user):
        """Get comprehensive analytics data for the analytics screen"""
        try:
            period = request.args.get('period', 'monthly')
            start_date, end_date = get_date_range(period)
            
            # Get comprehensive profit metrics
            profit_metrics = calculate_profit_metrics(current_user['_id'], start_date, end_date)
            
            # Get trend data for the last 12 months
            monthly_trends = []
            for i in range(12):
                month_end = datetime.utcnow().replace(day=1) - timedelta(days=i*30)
                month_start = month_end - timedelta(days=30)
                
                month_metrics = calculate_profit_metrics(current_user['_id'], month_start, month_end)
                monthly_trends.append({
                    'month': month_start.strftime('%Y-%m'),
                    'revenue': month_metrics['totalRevenue'],
                    'expenses': month_metrics['totalExpenses'],
                    'grossProfit': month_metrics['grossProfit'],
                    'netProfit': month_metrics['netProfit'],
                    'grossMargin': month_metrics['grossMargin'],
                    'netMargin': month_metrics['netMargin']
                })
            
            monthly_trends.reverse()  # Oldest to newest
            
            # Business health score calculation
            health_score = 0
            health_factors = []
            
            # Revenue health (25 points)
            if profit_metrics['totalRevenue'] > 0:
                health_score += 25
                health_factors.append({'factor': 'Revenue Generation', 'score': 25, 'status': 'good'})
            else:
                health_factors.append({'factor': 'Revenue Generation', 'score': 0, 'status': 'poor'})
            
            # Profitability health (25 points)
            if profit_metrics['netProfit'] > 0:
                health_score += 25
                health_factors.append({'factor': 'Profitability', 'score': 25, 'status': 'good'})
            elif profit_metrics['netProfit'] == 0:
                health_score += 12
                health_factors.append({'factor': 'Profitability', 'score': 12, 'status': 'fair'})
            else:
                health_factors.append({'factor': 'Profitability', 'score': 0, 'status': 'poor'})
            
            # Cash flow health (20 points) - based on receivables vs payables
            debtors_outstanding = mongo.db.debtors.aggregate([
                {'$match': {'userId': current_user['_id']}},
                {'$group': {'_id': None, 'total': {'$sum': '$remainingDebt'}}}
            ])
            debtors_outstanding = list(debtors_outstanding)
            total_receivables = debtors_outstanding[0]['total'] if debtors_outstanding else 0
            
            creditors_outstanding = mongo.db.creditors.aggregate([
                {'$match': {'userId': current_user['_id']}},
                {'$group': {'_id': None, 'total': {'$sum': '$remainingOwed'}}}
            ])
            creditors_outstanding = list(creditors_outstanding)
            total_payables = creditors_outstanding[0]['total'] if creditors_outstanding else 0
            
            if total_receivables >= total_payables:
                health_score += 20
                health_factors.append({'factor': 'Cash Flow', 'score': 20, 'status': 'good'})
            else:
                health_score += 10
                health_factors.append({'factor': 'Cash Flow', 'score': 10, 'status': 'fair'})
            
            # Inventory health (15 points)
            low_stock_count = mongo.db.inventory_items.count_documents({
                'userId': current_user['_id'],
                '$expr': {'$lte': ['$currentStock', '$minimumStock']}
            })
            
            if low_stock_count == 0:
                health_score += 15
                health_factors.append({'factor': 'Inventory Management', 'score': 15, 'status': 'good'})
            elif low_stock_count <= 5:
                health_score += 10
                health_factors.append({'factor': 'Inventory Management', 'score': 10, 'status': 'fair'})
            else:
                health_score += 5
                health_factors.append({'factor': 'Inventory Management', 'score': 5, 'status': 'poor'})
            
            # Customer base health (15 points)
            total_customers = mongo.db.debtors.count_documents({'userId': current_user['_id']})
            if total_customers >= 10:
                health_score += 15
                health_factors.append({'factor': 'Customer Base', 'score': 15, 'status': 'good'})
            elif total_customers >= 5:
                health_score += 10
                health_factors.append({'factor': 'Customer Base', 'score': 10, 'status': 'fair'})
            elif total_customers > 0:
                health_score += 5
                health_factors.append({'factor': 'Customer Base', 'score': 5, 'status': 'poor'})
            else:
                health_factors.append({'factor': 'Customer Base', 'score': 0, 'status': 'poor'})
            
            # Determine health status
            if health_score >= 80:
                health_status = 'excellent'
            elif health_score >= 60:
                health_status = 'good'
            elif health_score >= 40:
                health_status = 'fair'
            else:
                health_status = 'needs_attention'
            
            # Generate insights and recommendations
            insights = []
            recommendations = []
            
            if profit_metrics['netMargin'] > 20:
                insights.append({
                    'type': 'positive',
                    'title': 'Strong Profitability',
                    'description': f'Your net profit margin of {profit_metrics["netMargin"]:.1f}% is excellent'
                })
            elif profit_metrics['netMargin'] < 5:
                insights.append({
                    'type': 'warning',
                    'title': 'Low Profit Margins',
                    'description': f'Your net profit margin of {profit_metrics["netMargin"]:.1f}% needs improvement'
                })
                recommendations.append({
                    'priority': 'high',
                    'title': 'Improve Profit Margins',
                    'description': 'Consider reducing costs or increasing prices to improve profitability'
                })
            
            if low_stock_count > 0:
                insights.append({
                    'type': 'warning',
                    'title': 'Inventory Alert',
                    'description': f'{low_stock_count} items are running low on stock'
                })
                recommendations.append({
                    'priority': 'medium',
                    'title': 'Restock Inventory',
                    'description': 'Review and restock low inventory items to avoid stockouts'
                })
            
            overdue_customers = mongo.db.debtors.count_documents({
                'userId': current_user['_id'],
                'status': 'overdue'
            })
            
            if overdue_customers > 0:
                insights.append({
                    'type': 'warning',
                    'title': 'Overdue Payments',
                    'description': f'{overdue_customers} customers have overdue payments'
                })
                recommendations.append({
                    'priority': 'high',
                    'title': 'Follow Up on Overdue Payments',
                    'description': 'Contact customers with overdue payments to improve cash flow'
                })
            
            analytics_data = {
                'period': period,
                'dateRange': {
                    'startDate': start_date.isoformat() + 'Z',
                    'endDate': end_date.isoformat() + 'Z'
                },
                'profitMetrics': profit_metrics,
                'monthlyTrends': monthly_trends,
                'businessHealth': {
                    'score': health_score,
                    'status': health_status,
                    'factors': health_factors
                },
                'insights': insights,
                'recommendations': recommendations,
                'kpis': {
                    'totalRevenue': profit_metrics['totalRevenue'],
                    'totalProfit': profit_metrics['netProfit'],
                    'profitMargin': profit_metrics['netMargin'],
                    'totalCustomers': total_customers,
                    'outstandingReceivables': total_receivables,
                    'outstandingPayables': total_payables,
                    'inventoryValue': 0,  # Will be calculated from inventory summary
                    'lowStockItems': low_stock_count
                }
            }
            
            return jsonify({
                'success': True,
                'data': analytics_data,
                'message': 'Analytics data retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve analytics data',
                'errors': {'general': [str(e)]}
            }), 500

    @dashboard_bp.route('/export-data', methods=['POST'])
    @token_required
    def export_dashboard_data(current_user):
        """Export comprehensive dashboard data for reports"""
        try:
            export_type = request.json.get('exportType', 'summary')
            start_date_str = request.json.get('startDate')
            end_date_str = request.json.get('endDate')
            
            # Parse dates if provided
            start_date = None
            end_date = None
            if start_date_str:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
            if end_date_str:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
            
            if not start_date or not end_date:
                start_date, end_date = get_date_range('monthly')
            
            export_data = {
                'user': {
                    'id': str(current_user['_id']),
                    'email': current_user['email'],
                    'displayName': current_user.get('displayName', ''),
                    'businessName': current_user.get('businessName', ''),
                },
                'dateRange': {
                    'startDate': start_date.isoformat() + 'Z',
                    'endDate': end_date.isoformat() + 'Z'
                },
                'exportType': export_type,
                'generatedAt': datetime.utcnow().isoformat() + 'Z'
            }
            
            if export_type in ['summary', 'complete']:
                # Include profit metrics
                export_data['profitMetrics'] = calculate_profit_metrics(current_user['_id'], start_date, end_date)
                
                # Include module summaries
                export_data['moduleSummaries'] = {}
                
                # Income summary
                incomes = list(mongo.db.incomes.find({
                    'userId': current_user['_id'],
                    'dateReceived': {'$gte': start_date, '$lte': end_date}
                }))
                export_data['moduleSummaries']['income'] = {
                    'totalAmount': sum(income['amount'] for income in incomes),
                    'transactionCount': len(incomes)
                }
                
                # Expense summary
                expenses = list(mongo.db.expenses.find({
                    'userId': current_user['_id'],
                    'date': {'$gte': start_date, '$lte': end_date}
                }))
                export_data['moduleSummaries']['expenses'] = {
                    'totalAmount': sum(expense['amount'] for expense in expenses),
                    'transactionCount': len(expenses)
                }
                
                # Debtors summary
                debtors = list(mongo.db.debtors.find({'userId': current_user['_id']}))
                export_data['moduleSummaries']['debtors'] = {
                    'totalCustomers': len(debtors),
                    'totalOutstanding': sum(debtor['remainingDebt'] for debtor in debtors),
                    'overdueCustomers': len([d for d in debtors if d['status'] == 'overdue'])
                }
                
                # Creditors summary
                creditors = list(mongo.db.creditors.find({'userId': current_user['_id']}))
                export_data['moduleSummaries']['creditors'] = {
                    'totalVendors': len(creditors),
                    'totalOutstanding': sum(creditor['remainingOwed'] for creditor in creditors),
                    'overdueVendors': len([c for c in creditors if c['status'] == 'overdue'])
                }
                
                # Inventory summary
                inventory_items = list(mongo.db.inventory_items.find({'userId': current_user['_id']}))
                export_data['moduleSummaries']['inventory'] = {
                    'totalItems': len(inventory_items),
                    'totalValue': sum(item['currentStock'] * item['costPrice'] for item in inventory_items),
                    'lowStockItems': len([item for item in inventory_items if item['currentStock'] <= item['minimumStock']])
                }
                
                # Include alerts
                export_data['alerts'] = get_alerts_and_reminders(current_user['_id'])
            
            if export_type == 'complete':
                # Include detailed transaction data
                export_data['detailedData'] = {
                    'incomes': [serialize_doc(income) for income in incomes],
                    'expenses': [serialize_doc(expense) for expense in expenses],
                    'debtors': [serialize_doc(debtor) for debtor in debtors],
                    'creditors': [serialize_doc(creditor) for creditor in creditors],
                    'inventoryItems': [serialize_doc(item) for item in inventory_items]
                }
            
            return jsonify({
                'success': True,
                'data': export_data,
                'message': 'Export data prepared successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to prepare export data',
                'errors': {'general': [str(e)]}
            }), 500

    return dashboard_bp