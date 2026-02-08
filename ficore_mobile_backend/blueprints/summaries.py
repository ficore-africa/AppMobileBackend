from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId

def init_summaries_blueprint(mongo, token_required, serialize_doc):
    """Initialize the summaries blueprint with database and dependencies"""
    summaries_bp = Blueprint('summaries', __name__, url_prefix='/summaries')

    @summaries_bp.route('/recent_activity', methods=['GET'])
    @token_required
    def get_recent_activity(current_user):
        """Get recent user activities across all modules (VAS + Business transactions)"""
        try:
            # Validate database connection
            if mongo is None or mongo.db is None:
                return jsonify({
                    'success': False,
                    'message': 'Database connection error',
                    'errors': {'general': ['Database not available']}
                }), 500

            # Get query parameters
            limit = min(int(request.args.get('limit', 10)), 50)  # Cap at 50
            
            activities = []
            
            # 1. Get recent expenses with smart filtering
            try:
                now = datetime.utcnow()
                one_minute_ago = now - timedelta(minutes=1)
                
                # CRITICAL FIX (Feb 8, 2026): Use get_active_transactions_query for consistency
                from utils.immutable_ledger_helper import get_active_transactions_query
                base_query = get_active_transactions_query(current_user['_id'])
                
                # Add date filtering
                base_query['$or'] = [
                    {'date': {'$lte': now}},  # Past & present entries
                    {'createdAt': {'$gte': one_minute_ago}}  # Recently created entries
                ]
                
                recent_expenses = list(mongo.db.expenses.find(base_query).sort('createdAt', -1).limit(limit))
                
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Found {len(recent_expenses)} expense transactions for user {current_user['_id']}")
                
                for expense in recent_expenses:
                    activity = {
                        'id': str(expense['_id']),
                        'type': 'EXPENSE',
                        'subtype': 'EXPENSE',
                        'title': expense.get('title', expense.get('description', 'Expense')),
                        'description': f"Spent ₦{expense.get('amount', 0):,.2f} on {expense.get('category', 'Unknown')}",
                        'amount': expense.get('amount', 0),
                        'category': expense.get('category', 'Unknown'),
                        'date': expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                        'timestamp': expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                        'transactionDate': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
                        'icon': 'expense',
                        'color': 'red'
                    }
                    activities.append(activity)
                    # DISABLED FOR LIQUID WALLET FOCUS
                    # print(f"Added expense activity: {activity['title']} - ₦{expense.get('amount', 0)}")
            except Exception as e:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Error fetching expenses: {e}")
                import traceback
                traceback.print_exc()

            # 2. Get recent incomes with smart filtering
            try:
                now = datetime.utcnow()
                one_minute_ago = now - timedelta(minutes=1)
                
                # CRITICAL FIX (Feb 8, 2026): Use get_active_transactions_query for consistency
                from utils.immutable_ledger_helper import get_active_transactions_query
                base_query = get_active_transactions_query(current_user['_id'])
                
                # Add date filtering
                base_query['$or'] = [
                    {'dateReceived': {'$lte': now}},  # Past & present entries
                    {'createdAt': {'$gte': one_minute_ago}}  # Recently created entries
                ]
                
                recent_incomes = list(mongo.db.incomes.find(base_query).sort('createdAt', -1).limit(limit))
                
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Found {len(recent_incomes)} income transactions for user {current_user['_id']}")
                
                for income in recent_incomes:
                    activity = {
                        'id': str(income['_id']),
                        'type': 'INCOME',
                        'subtype': 'INCOME',
                        'title': income.get('title', income.get('source', 'Income')),
                        'description': f"Received ₦{income.get('amount', 0):,.2f} from {income.get('source', 'Unknown')}",
                        'amount': income.get('amount', 0),
                        'source': income.get('source', 'Unknown'),
                        'date': income.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                        'timestamp': income.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                        'transactionDate': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z',
                        'icon': 'income',
                        'color': 'green'
                    }
                    activities.append(activity)
                    # DISABLED FOR LIQUID WALLET FOCUS
                    # print(f"Added income activity: {activity['title']} - ₦{income.get('amount', 0)}")
            except Exception as e:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Error fetching incomes: {e}")
                import traceback
                traceback.print_exc()

            # Sort all activities by date (most recent first)
            activities.sort(key=lambda x: x['date'], reverse=True)
            
            # Limit to requested number
            activities = activities[:limit]
            
            # DISABLED FOR LIQUID WALLET FOCUS
            # print(f"Final activities count: {len(activities)}")
            # print(f"Activity types: {[a['type'] for a in activities[:5]]}")  # Show first 5 types

            return jsonify({
                'success': True,
                'data': {
                    'activities': activities,
                    'total': len(activities),
                    'lastUpdated': datetime.utcnow().isoformat() + 'Z'
                },
                'message': 'Recent activities retrieved successfully'
            })

        except Exception as e:
            # DISABLED FOR LIQUID WALLET FOCUS
            # print(f"Error in get_recent_activity: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve recent activities',
                'errors': {'general': [str(e)]}
            }), 500

    @summaries_bp.route('/all_activities', methods=['GET'])
    @token_required
    def get_all_activities(current_user):
        """Get all user activities with pagination"""
        try:
            # Get query parameters
            page = int(request.args.get('page', 1))
            limit = min(int(request.args.get('limit', 20)), 100)
            activity_type = request.args.get('type', 'all')  # all, expense, income, vas
            
            activities = []
            
            # Get activities based on type filter
            # HYBRID QUERY: Applied to all_activities endpoint for consistency
            now = datetime.utcnow()
            one_minute_ago = now - timedelta(minutes=1)
            
            # 1. Get VAS transactions (if type is 'all' or 'vas')
            if activity_type in ['all', 'vas']:
                try:
                    vas_transactions = list(mongo.db.vas_transactions.find({
                        'userId': current_user['_id']
                    }).sort('createdAt', -1))
                    
                    for txn in vas_transactions:
                        # Create user-friendly description based on transaction type
                        txn_type = txn.get('type', 'UNKNOWN')
                        amount = txn.get('amount', 0)
                        
                        if txn_type == 'WALLET_FUNDING':
                            title = 'Wallet Funded'
                            description = f'Added ₦{amount:,.2f} to Liquid Wallet'
                            icon = 'wallet'
                        elif txn_type == 'AIRTIME_PURCHASE':
                            title = 'Airtime Purchase'
                            phone = txn.get('metadata', {}).get('phoneNumber', 'Unknown')
                            description = f'₦{amount:,.2f} airtime sent to {phone[-4:]}****' if phone != 'Unknown' else f'₦{amount:,.2f} airtime purchase'
                            icon = 'phone'
                        elif txn_type == 'DATA_PURCHASE':
                            title = 'Data Purchase'
                            phone = txn.get('metadata', {}).get('phoneNumber', 'Unknown')
                            plan = txn.get('metadata', {}).get('planName', 'Data')
                            description = f'{plan} for {phone[-4:]}****' if phone != 'Unknown' else f'₦{amount:,.2f} data purchase'
                            icon = 'data'
                        elif txn_type == 'KYC_VERIFICATION':
                            title = 'KYC Verification'
                            description = f'Account verification fee ₦{amount:,.2f}'
                            icon = 'verification'
                        else:
                            title = f'VAS {txn_type.replace("_", " ").title()}'
                            description = f'₦{amount:,.2f} VAS transaction'
                            icon = 'vas'
                        
                        activity = {
                            'id': str(txn['_id']),
                            'type': 'VAS',
                            'subtype': txn_type,
                            'title': title,
                            'description': description,
                            'amount': amount,
                            'reference': txn.get('reference', ''),
                            'status': txn.get('status', 'UNKNOWN'),
                            'provider': txn.get('provider', ''),
                            'date': txn.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                            'timestamp': txn.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
                            'icon': icon,
                            'color': 'blue',
                            'category': 'VAS Services'
                        }
                        activities.append(activity)
                except Exception as e:
                    # DISABLED FOR LIQUID WALLET FOCUS
                    # print(f"Error fetching VAS transactions: {e}")
                    pass

            if activity_type in ['all', 'expense']:
                try:
                    # HYBRID QUERY: Shows expenses where EITHER:
                    # 1. date is past/present (prevents future inflation)
                    # 2. OR createdAt is within last minute (shows just-created entries immediately)
                    expenses = list(mongo.db.expenses.find({
                        'userId': current_user['_id'],
                        '$or': [
                            {'date': {'$lte': now}},  # Past & present entries
                            {'createdAt': {'$gte': one_minute_ago}}  # Recently created entries
                        ]
                    }).sort('createdAt', -1))
                    
                    for expense in expenses:
                        activity = {
                            'id': str(expense['_id']),
                            'type': 'expense',
                            'title': expense.get('title', expense.get('description', 'Expense')),
                            'description': f"Spent ₦{expense.get('amount', 0):,.2f} on {expense.get('category', 'Unknown')}",
                            'amount': expense.get('amount', 0),
                            'category': expense.get('category', 'Unknown'),
                            'date': expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z',  # FIXED: Use createdAt for activity timestamp
                            'timestamp': expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z',  # ADDED: Explicit timestamp field
                            'transactionDate': expense.get('date', datetime.utcnow()).isoformat() + 'Z',  # ADDED: Keep user-selected date for reference
                            'icon': 'expense',
                            'color': 'red'
                        }
                        activities.append(activity)
                except Exception as e:
                    # DISABLED FOR LIQUID WALLET FOCUS
                    # print(f"Error fetching expenses: {e}")
                    pass

            if activity_type in ['all', 'income']:
                try:
                    # HYBRID QUERY: Shows incomes where EITHER:
                    # 1. dateReceived is past/present (prevents future inflation)
                    # 2. OR createdAt is within last minute (shows just-created entries immediately)
                    incomes = list(mongo.db.incomes.find({
                        'userId': current_user['_id'],
                        '$or': [
                            {'dateReceived': {'$lte': now}},  # Past & present entries
                            {'createdAt': {'$gte': one_minute_ago}}  # Recently created entries
                        ]
                    }).sort('createdAt', -1))
                    
                    for income in incomes:
                        activity = {
                            'id': str(income['_id']),
                            'type': 'income',
                            'title': income.get('title', income.get('source', 'Income')),
                            'description': f"Received ₦{income.get('amount', 0):,.2f} from {income.get('source', 'Unknown')}",
                            'amount': income.get('amount', 0),
                            'source': income.get('source', 'Unknown'),
                            'date': income.get('createdAt', datetime.utcnow()).isoformat() + 'Z',  # FIXED: Use createdAt for activity timestamp
                            'timestamp': income.get('createdAt', datetime.utcnow()).isoformat() + 'Z',  # ADDED: Explicit timestamp field
                            'transactionDate': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z',  # ADDED: Keep user-selected date for reference
                            'icon': 'income',
                            'color': 'green'
                        }
                        activities.append(activity)
                except Exception as e:
                    # DISABLED FOR LIQUID WALLET FOCUS
                    # print(f"Error fetching incomes: {e}")
                    pass

            # Sort all activities by date (most recent first)
            activities.sort(key=lambda x: x['date'], reverse=True)
            
            # Apply pagination
            total_count = len(activities)
            start_index = (page - 1) * limit
            end_index = start_index + limit
            paginated_activities = activities[start_index:end_index]

            return jsonify({
                'success': True,
                'data': {
                    'activities': paginated_activities,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total_count,
                        'pages': (total_count + limit - 1) // limit,
                        'hasNext': end_index < total_count,
                        'hasPrev': page > 1
                    }
                },
                'message': 'All activities retrieved successfully'
            })

        except Exception as e:
            # DISABLED FOR LIQUID WALLET FOCUS
            # print(f"Error in get_all_activities: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve activities',
                'errors': {'general': [str(e)]}
            }), 500

    @summaries_bp.route('/dashboard_summary', methods=['GET'])
    @token_required
    def get_dashboard_summary(current_user):
        """Get comprehensive dashboard summary with enhanced calculations"""
        try:
            # Get current month data
            now = datetime.utcnow()
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
            summary_data = {
                'totalIncome': 0.0,
                'totalExpenses': 0.0,
                'monthlyIncome': 0.0,
                'monthlyExpenses': 0.0,
                'yearlyIncome': 0.0,
                'yearlyExpenses': 0.0,
                'creditBalance': 0.0,
                'recentActivitiesCount': 0,
                'monthlyStats': {
                    'income': 0.0,
                    'expenses': 0.0,
                    'netIncome': 0.0
                },
                'yearlyStats': {
                    'income': 0.0,
                    'expenses': 0.0,
                    'netIncome': 0.0
                }
            }
            
            # Get user's credit balance
            try:
                user = mongo.db.users.find_one({'_id': current_user['_id']})
                if user:
                    summary_data['creditBalance'] = float(user.get('ficoreCreditBalance', 0.0))
            except Exception as e:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Error fetching user balance: {e}")
                pass
            
            # Get ALL income data with proper aggregation
            try:
                # Total income (all time, only received)
                total_income_pipeline = [
                    {
                        '$match': {
                            'userId': current_user['_id'],
                            'dateReceived': {'$lte': now}  # Only received incomes
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'total': {'$sum': '$amount'}
                        }
                    }
                ]
                total_income_result = list(mongo.db.incomes.aggregate(total_income_pipeline))
                summary_data['totalIncome'] = float(total_income_result[0]['total']) if total_income_result else 0.0
                
                # Monthly income
                monthly_income_pipeline = [
                    {
                        '$match': {
                            'userId': current_user['_id'],
                            'dateReceived': {
                                '$gte': start_of_month,
                                '$lte': now
                            }
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'total': {'$sum': '$amount'}
                        }
                    }
                ]
                monthly_income_result = list(mongo.db.incomes.aggregate(monthly_income_pipeline))
                monthly_income = float(monthly_income_result[0]['total']) if monthly_income_result else 0.0
                summary_data['monthlyIncome'] = monthly_income
                summary_data['monthlyStats']['income'] = monthly_income
                
                # Yearly income
                yearly_income_pipeline = [
                    {
                        '$match': {
                            'userId': current_user['_id'],
                            'dateReceived': {
                                '$gte': start_of_year,
                                '$lte': now
                            }
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'total': {'$sum': '$amount'}
                        }
                    }
                ]
                yearly_income_result = list(mongo.db.incomes.aggregate(yearly_income_pipeline))
                yearly_income = float(yearly_income_result[0]['total']) if yearly_income_result else 0.0
                summary_data['yearlyIncome'] = yearly_income
                summary_data['yearlyStats']['income'] = yearly_income
                
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"DEBUG ENHANCED SUMMARY - Total Income: {summary_data['totalIncome']}, Monthly: {monthly_income}, Yearly: {yearly_income}")
                
            except Exception as e:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Error fetching incomes: {e}")
                pass
            
            # CRITICAL FIX: Get ALL expense data with optimized single aggregation pipeline
            try:
                # OPTIMIZED: Single aggregation pipeline for all expense calculations
                expense_aggregation_pipeline = [
                    {
                        '$match': {
                            'userId': current_user['_id']
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'totalExpenses': {'$sum': '$amount'},
                            'totalExpenseRecords': {'$sum': 1},
                            'monthlyExpenses': {
                                '$sum': {
                                    '$cond': [
                                        {
                                            '$and': [
                                                {'$gte': ['$date', start_of_month]},
                                                {'$lte': ['$date', now]}
                                            ]
                                        },
                                        '$amount',
                                        0
                                    ]
                                }
                            },
                            'monthlyExpenseRecords': {
                                '$sum': {
                                    '$cond': [
                                        {
                                            '$and': [
                                                {'$gte': ['$date', start_of_month]},
                                                {'$lte': ['$date', now]}
                                            ]
                                        },
                                        1,
                                        0
                                    ]
                                }
                            },
                            'yearlyExpenses': {
                                '$sum': {
                                    '$cond': [
                                        {
                                            '$and': [
                                                {'$gte': ['$date', start_of_year]},
                                                {'$lte': ['$date', now]}
                                            ]
                                        },
                                        '$amount',
                                        0
                                    ]
                                }
                            },
                            'yearlyExpenseRecords': {
                                '$sum': {
                                    '$cond': [
                                        {
                                            '$and': [
                                                {'$gte': ['$date', start_of_year]},
                                                {'$lte': ['$date', now]}
                                            ]
                                        },
                                        1,
                                        0
                                    ]
                                }
                            }
                        }
                    }
                ]
                
                expense_result = list(mongo.db.expenses.aggregate(expense_aggregation_pipeline))
                
                if expense_result:
                    result = expense_result[0]
                    summary_data['totalExpenses'] = float(result.get('totalExpenses', 0))
                    summary_data['totalExpenseRecords'] = int(result.get('totalExpenseRecords', 0))
                    monthly_expenses = float(result.get('monthlyExpenses', 0))
                    monthly_expense_records = int(result.get('monthlyExpenseRecords', 0))
                    yearly_expenses = float(result.get('yearlyExpenses', 0))
                    yearly_expense_records = int(result.get('yearlyExpenseRecords', 0))
                    
                    summary_data['monthlyExpenses'] = monthly_expenses
                    summary_data['monthlyExpenseRecords'] = monthly_expense_records
                    summary_data['monthlyStats']['expenses'] = monthly_expenses
                    summary_data['yearlyExpenses'] = yearly_expenses
                    summary_data['yearlyExpenseRecords'] = yearly_expense_records
                    summary_data['yearlyStats']['expenses'] = yearly_expenses
                else:
                    summary_data['totalExpenses'] = 0.0
                    summary_data['totalExpenseRecords'] = 0
                    summary_data['monthlyExpenses'] = 0.0
                    summary_data['monthlyExpenseRecords'] = 0
                    summary_data['monthlyStats']['expenses'] = 0.0
                    summary_data['yearlyExpenses'] = 0.0
                    summary_data['yearlyExpenseRecords'] = 0
                    summary_data['yearlyStats']['expenses'] = 0.0
                
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"DEBUG OPTIMIZED SUMMARY - Total Expenses: {summary_data['totalExpenses']}, Monthly: {summary_data['monthlyExpenses']}, Yearly: {summary_data['yearlyExpenses']}")
                
            except Exception as e:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Error fetching expenses: {e}")
                # Fallback to zero values on error
                summary_data['totalExpenses'] = 0.0
                summary_data['totalExpenseRecords'] = 0
                summary_data['monthlyExpenses'] = 0.0
                summary_data['monthlyExpenseRecords'] = 0
                summary_data['monthlyStats']['expenses'] = 0.0
                summary_data['yearlyExpenses'] = 0.0
                summary_data['yearlyExpenseRecords'] = 0
                summary_data['yearlyStats']['expenses'] = 0.0
            
            # Calculate net income
            summary_data['monthlyStats']['netIncome'] = summary_data['monthlyStats']['income'] - summary_data['monthlyStats']['expenses']
            summary_data['yearlyStats']['netIncome'] = summary_data['yearlyStats']['income'] - summary_data['yearlyStats']['expenses']
            
            # CRITICAL FIX: Get debtors data with proper aggregation
            try:
                debtors_pipeline = [
                    {
                        '$match': {
                            'userId': current_user['_id']
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'totalCustomers': {'$sum': 1},
                            'totalOutstanding': {'$sum': '$remainingDebt'},
                            'overdueCustomers': {
                                '$sum': {'$cond': [{'$eq': ['$status', 'overdue']}, 1, 0]}
                            },
                            'overdueAmount': {
                                '$sum': {'$cond': [
                                    {'$eq': ['$status', 'overdue']}, 
                                    '$remainingDebt', 
                                    0
                                ]}
                            }
                        }
                    }
                ]
                debtors_result = list(mongo.db.debtors.aggregate(debtors_pipeline))
                
                if debtors_result:
                    debtors_data = debtors_result[0]
                    summary_data['debtorsData'] = {
                        'totalCustomers': int(debtors_data.get('totalCustomers', 0)),
                        'totalOutstanding': float(debtors_data.get('totalOutstanding', 0)),
                        'overdueCustomers': int(debtors_data.get('overdueCustomers', 0)),
                        'overdueAmount': float(debtors_data.get('overdueAmount', 0))
                    }
                else:
                    summary_data['debtorsData'] = {
                        'totalCustomers': 0,
                        'totalOutstanding': 0.0,
                        'overdueCustomers': 0,
                        'overdueAmount': 0.0
                    }
                
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"DEBUG ENHANCED SUMMARY - Debtors: {summary_data['debtorsData']}")
                
            except Exception as e:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Error fetching debtors data: {e}")
                summary_data['debtorsData'] = {
                    'totalCustomers': 0,
                    'totalOutstanding': 0.0,
                    'overdueCustomers': 0,
                    'overdueAmount': 0.0
                }
            
            # ENHANCED: Get creditors data with proper aggregation
            try:
                creditors_pipeline = [
                    {
                        '$match': {
                            'userId': current_user['_id']
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'totalVendors': {'$sum': 1},
                            'totalOwed': {'$sum': '$totalOwed'},
                            'totalOutstanding': {'$sum': '$remainingOwed'},
                            'overdueVendors': {
                                '$sum': {'$cond': [{'$eq': ['$status', 'overdue']}, 1, 0]}
                            },
                            'overdueAmount': {
                                '$sum': {'$cond': [
                                    {'$eq': ['$status', 'overdue']}, 
                                    '$remainingOwed', 
                                    0
                                ]}
                            }
                        }
                    }
                ]
                creditors_result = list(mongo.db.creditors.aggregate(creditors_pipeline))
                
                if creditors_result:
                    creditors_data = creditors_result[0]
                    summary_data['creditorsData'] = {
                        'totalVendors': int(creditors_data.get('totalVendors', 0)),
                        'totalOwed': float(creditors_data.get('totalOwed', 0)),
                        'totalOutstanding': float(creditors_data.get('totalOutstanding', 0)),
                        'overdueVendors': int(creditors_data.get('overdueVendors', 0)),
                        'overdueAmount': float(creditors_data.get('overdueAmount', 0))
                    }
                else:
                    summary_data['creditorsData'] = {
                        'totalVendors': 0,
                        'totalOwed': 0.0,
                        'totalOutstanding': 0.0,
                        'overdueVendors': 0,
                        'overdueAmount': 0.0
                    }
                
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"DEBUG ENHANCED SUMMARY - Creditors: {summary_data['creditorsData']}")
                
            except Exception as e:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Error fetching creditors data: {e}")
                summary_data['creditorsData'] = {
                    'totalVendors': 0,
                    'totalOwed': 0.0,
                    'totalOutstanding': 0.0,
                    'overdueVendors': 0,
                    'overdueAmount': 0.0
                }
            
            # ENHANCED: Get inventory data with proper aggregation
            try:
                inventory_pipeline = [
                    {
                        '$match': {
                            'userId': current_user['_id']
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'totalItems': {'$sum': 1},
                            'totalValue': {'$sum': {'$multiply': ['$currentStock', '$costPrice']}},
                            'totalStock': {'$sum': '$currentStock'},
                            'lowStockItems': {
                                '$sum': {'$cond': [{'$lte': ['$currentStock', '$minimumStock']}, 1, 0]}
                            },
                            'outOfStockItems': {
                                '$sum': {'$cond': [{'$lte': ['$currentStock', 0]}, 1, 0]}
                            },
                            'activeItems': {
                                '$sum': {'$cond': [{'$eq': ['$status', 'active']}, 1, 0]}
                            }
                        }
                    }
                ]
                inventory_result = list(mongo.db.inventory_items.aggregate(inventory_pipeline))
                
                if inventory_result:
                    inventory_data = inventory_result[0]
                    summary_data['inventoryData'] = {
                        'totalItems': int(inventory_data.get('totalItems', 0)),
                        'totalValue': float(inventory_data.get('totalValue', 0)),
                        'totalStock': int(inventory_data.get('totalStock', 0)),
                        'lowStockItems': int(inventory_data.get('lowStockItems', 0)),
                        'outOfStockItems': int(inventory_data.get('outOfStockItems', 0)),
                        'activeItems': int(inventory_data.get('activeItems', 0))
                    }
                else:
                    summary_data['inventoryData'] = {
                        'totalItems': 0,
                        'totalValue': 0.0,
                        'totalStock': 0,
                        'lowStockItems': 0,
                        'outOfStockItems': 0,
                        'activeItems': 0
                    }
                
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"DEBUG ENHANCED SUMMARY - Inventory: {summary_data['inventoryData']}")
                
            except Exception as e:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Error fetching inventory data: {e}")
                summary_data['inventoryData'] = {
                    'totalItems': 0,
                    'totalValue': 0.0,
                    'totalStock': 0,
                    'lowStockItems': 0,
                    'outOfStockItems': 0,
                    'activeItems': 0
                }
            
            # Get recent activities count
            try:
                recent_activities_count = (
                    mongo.db.expenses.count_documents({
                        'userId': current_user['_id'],
                        'createdAt': {'$gte': start_of_month}
                    }) +
                    mongo.db.incomes.count_documents({
                        'userId': current_user['_id'],
                        'createdAt': {'$gte': start_of_month}
                    })
                )
                summary_data['recentActivitiesCount'] = recent_activities_count
            except Exception as e:
                # DISABLED FOR LIQUID WALLET FOCUS
                # print(f"Error counting recent activities: {e}")
                pass

            # DISABLED FOR LIQUID WALLET FOCUS
            # print(f"DEBUG FINAL SUMMARY DATA: {summary_data}")

            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Enhanced dashboard summary retrieved successfully'
            })

        except Exception as e:
            # DISABLED FOR LIQUID WALLET FOCUS
            # print(f"Error in get_dashboard_summary: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve dashboard summary',
                'errors': {'general': [str(e)]}
            }), 500

    return summaries_bp