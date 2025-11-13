from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
from utils.payment_utils import normalize_payment_method, validate_payment_method
from utils.monthly_entry_tracker import MonthlyEntryTracker

expenses_bp = Blueprint('expenses', __name__, url_prefix='/expenses')

def init_expenses_blueprint(mongo, token_required, serialize_doc):
    """Initialize the expenses blueprint with database and auth decorator"""
    expenses_bp.mongo = mongo
    expenses_bp.token_required = token_required
    expenses_bp.serialize_doc = serialize_doc
    return expenses_bp

@expenses_bp.route('', methods=['GET'])
def get_expenses():
    @expenses_bp.token_required
    def _get_expenses(current_user):
        try:
            limit = min(int(request.args.get('limit', 50)), 100)
            offset = max(int(request.args.get('offset', 0)), 0)
            category = request.args.get('category')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            sort_by = request.args.get('sort_by', 'date')
            sort_order = request.args.get('sort_order', 'desc')
           
            query = {'userId': current_user['_id']}
            if category:
                query['category'] = category
            if start_date or end_date:
                date_query = {}
                if start_date:
                    date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    date_query['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))
                query['date'] = date_query
           
            sort_direction = -1 if sort_order == 'desc' else 1
            sort_field = sort_by if sort_by in ['date', 'amount', 'category', 'createdAt'] else 'date'
           
            expenses = list(expenses_bp.mongo.db.expenses.find(query)
                           .sort(sort_field, sort_direction)
                           .skip(offset).limit(limit))
            total = expenses_bp.mongo.db.expenses.count_documents(query)
           
            expense_list = []
            for expense in expenses:
                expense_data = expenses_bp.serialize_doc(expense.copy())
                expense_data['title'] = expense_data.get('description', expense_data.get('title', 'Expense'))
                expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
                expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                expense_data['updatedAt'] = expense_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if expense_data.get('updatedAt') else None
                expense_list.append(expense_data)
           
            has_more = offset + limit < total
           
            return jsonify({
                'success': True,
                'data': {
                    'expenses': expense_list,
                    'pagination': {
                        'total': total,
                        'limit': limit,
                        'offset': offset,
                        'hasMore': has_more,
                        'page': (offset // limit) + 1,
                        'pages': (total + limit - 1) // limit
                    }
                },
                'message': 'Expenses retrieved successfully'
            })
           
        except Exception as e:
            print(f"Error in get_expenses: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expenses',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expenses()

@expenses_bp.route('/<expense_id>', methods=['GET'])
def get_expense(expense_id):
    @expenses_bp.token_required
    def _get_expense(current_user):
        try:
            expense = expenses_bp.mongo.db.expenses.find_one({
                '_id': ObjectId(expense_id),
                'userId': current_user['_id']
            })
           
            if not expense:
                return jsonify({'success': False, 'message': 'Expense not found'}), 404
           
            expense_data = expenses_bp.serialize_doc(expense.copy())
            expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            expense_data['updatedAt'] = expense_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if expense_data.get('updatedAt') else None
           
            return jsonify({
                'success': True,
                'data': expense_data,
                'message': 'Expense retrieved successfully'
            })
           
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expense()

@expenses_bp.route('', methods=['POST'])
def create_expense():
    @expenses_bp.token_required
    def _create_expense(current_user):
        try:
            data = request.get_json()
            errors = {}
            if not data.get('amount') or data.get('amount', 0) <= 0:
                errors['amount'] = ['Valid amount is required']
            if not data.get('description'):
                errors['description'] = ['Description is required']
            if not data.get('category'):
                errors['category'] = ['Category is required']
           
            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400
           
            # NEW: Check monthly entry limit for free tier users
            entry_tracker = MonthlyEntryTracker(expenses_bp.mongo)
            fc_check = entry_tracker.should_deduct_fc(current_user['_id'], 'expense')
            
            # If FC deduction is required, check user has sufficient credits
            if fc_check['deduct_fc']:
                user = expenses_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                current_balance = user.get('ficoreCreditBalance', 0.0)
                
                if current_balance < fc_check['fc_cost']:
                    return jsonify({
                        'success': False,
                        'message': f'Insufficient credits. {fc_check["reason"]}',
                        'data': {
                            'required_credits': fc_check['fc_cost'],
                            'current_balance': current_balance,
                            'monthly_data': fc_check['monthly_data']
                        }
                    }), 402  # Payment Required
           
            raw_payment = data.get('paymentMethod')
            normalized_payment = normalize_payment_method(raw_payment) if raw_payment is not None else 'cash'
            if raw_payment is not None and not validate_payment_method(raw_payment):
                return jsonify({
                    'success': False,
                    'message': 'Invalid payment method',
                    'errors': {'paymentMethod': ['Unrecognized payment method']}
                }), 400

            expense_data = {
                'userId': current_user['_id'],
                'amount': float(data['amount']),
                'description': data['description'],
                'category': data['category'],
                'date': datetime.fromisoformat(data.get('date', datetime.utcnow().isoformat()).replace('Z', '')),
                'budgetId': data.get('budgetId'),
                'tags': data.get('tags', []),
                'paymentMethod': normalized_payment,
                'location': data.get('location', ''),
                'notes': data.get('notes', ''),
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
           
            result = expenses_bp.mongo.db.expenses.insert_one(expense_data)
            expense_id = str(result.inserted_id)
            
            # NEW: Deduct FC if required (over monthly limit)
            if fc_check['deduct_fc']:
                # Deduct credits from user account
                user = expenses_bp.mongo.db.users.find_one({'_id': current_user['_id']})
                current_balance = user.get('ficoreCreditBalance', 0.0)
                new_balance = current_balance - fc_check['fc_cost']
                
                expenses_bp.mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'ficoreCreditBalance': new_balance}}
                )
                
                # Create transaction record
                transaction = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'type': 'debit',
                    'amount': fc_check['fc_cost'],
                    'description': f'Expense entry over monthly limit (entry #{fc_check["monthly_data"]["count"] + 1})',
                    'operation': 'create_expense_over_limit',
                    'balanceBefore': current_balance,
                    'balanceAfter': new_balance,
                    'status': 'completed',
                    'createdAt': datetime.utcnow(),
                    'metadata': {
                        'operation': 'create_expense_over_limit',
                        'deductionType': 'monthly_limit_exceeded',
                        'monthly_data': fc_check['monthly_data']
                    }
                }
                
                expenses_bp.mongo.db.credit_transactions.insert_one(transaction)
           
            created_expense = expenses_bp.serialize_doc(expense_data.copy())
            created_expense['id'] = expense_id
            created_expense['title'] = created_expense.get('description', 'Expense')
            created_expense['date'] = created_expense.get('date', datetime.utcnow()).isoformat() + 'Z'
            created_expense['createdAt'] = created_expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            created_expense['updatedAt'] = created_expense.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
           
            return jsonify({
                'success': True,
                'data': created_expense,
                'message': 'Expense created successfully'
            })
           
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to create expense',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _create_expense()

@expenses_bp.route('/<expense_id>', methods=['PUT'])
def update_expense(expense_id):
    @expenses_bp.token_required
    def _update_expense(current_user):
        try:
            data = request.get_json()
            expense = expenses_bp.mongo.db.expenses.find_one({
                '_id': ObjectId(expense_id),
                'userId': current_user['_id']
            })
            if not expense:
                return jsonify({'success': False, 'message': 'Expense not found'}), 404
           
            update_data = {}
            updatable_fields = ['amount', 'description', 'category', 'date', 'budgetId', 'tags', 'paymentMethod', 'location', 'notes']
           
            for field in updatable_fields:
                if field in data:
                    if field == 'amount':
                        update_data[field] = float(data[field])
                    elif field == 'date':
                        update_data[field] = datetime.fromisoformat(data[field].replace('Z', ''))
                    elif field == 'paymentMethod':
                        if not validate_payment_method(data[field]):
                            return jsonify({
                                'success': False,
                                'message': 'Invalid payment method',
                                'errors': {'paymentMethod': ['Unrecognized payment method']}
                            }), 400
                        update_data[field] = normalize_payment_method(data[field])
                    else:
                        update_data[field] = data[field]
           
            update_data['updatedAt'] = datetime.utcnow()
           
            expenses_bp.mongo.db.expenses.update_one(
                {'_id': ObjectId(expense_id)},
                {'$set': update_data}
            )
           
            updated_expense = expenses_bp.mongo.db.expenses.find_one({'_id': ObjectId(expense_id)})
            expense_data = expenses_bp.serialize_doc(updated_expense.copy())
            expense_data['date'] = expense_data.get('date', datetime.utcnow()).isoformat() + 'Z'
            expense_data['createdAt'] = expense_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            expense_data['updatedAt'] = expense_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
           
            return jsonify({
                'success': True,
                'data': expense_data,
                'message': 'Expense updated successfully'
            })
           
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update expense',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _update_expense()

@expenses_bp.route('/<expense_id>', methods=['DELETE'])
def delete_expense(expense_id):
    @expenses_bp.token_required
    def _delete_expense(current_user):
        try:
            result = expenses_bp.mongo.db.expenses.delete_one({
                '_id': ObjectId(expense_id),
                'userId': current_user['_id']
            })
            if result.deleted_count == 0:
                return jsonify({'success': False, 'message': 'Expense not found'}), 404
           
            return jsonify({
                'success': True,
                'message': 'Expense deleted successfully'
            })
           
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to delete expense',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _delete_expense()

@expenses_bp.route('/summary', methods=['GET'])
def get_expense_summary():
    @expenses_bp.token_required
    def _get_expense_summary(current_user):
        try:
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            now = datetime.utcnow()
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start_of_last_month = (start_of_month - timedelta(days=1)).replace(day=1)
           
            filter_start = datetime.fromisoformat(start_date.replace('Z', '')) if start_date else start_of_month
            filter_end = datetime.fromisoformat(end_date.replace('Z', '')) if end_date else now
           
            all_expenses = list(expenses_bp.mongo.db.expenses.find({'userId': current_user['_id']}))
            filtered_expenses = [exp for exp in all_expenses if filter_start <= exp['date'] <= filter_end]
           
            total_this_month = sum(exp['amount'] for exp in all_expenses if exp['date'] >= start_of_month)
            total_last_month = sum(exp['amount'] for exp in all_expenses if start_of_last_month <= exp['date'] < start_of_month)
           
            category_totals = {}
            for expense in filtered_expenses:
                category = expense.get('category', 'Uncategorized')
                category_totals[category] = category_totals.get(category, 0) + expense['amount']
           
            recent_expenses = sorted(all_expenses, key=lambda x: x['date'], reverse=True)[:5]
            recent_expenses_data = []
            for expense in recent_expenses:
                e = expenses_bp.serialize_doc(expense.copy())
                e['title'] = e.get('description', e.get('title', 'Expense'))
                e['date'] = e.get('date', datetime.utcnow()).isoformat() + 'Z'
                e['createdAt'] = e.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                e['updatedAt'] = e.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                recent_expenses_data.append(e)
           
            summary_data = {
                'totalThisMonth': total_this_month,
                'totalLastMonth': total_last_month,
                'categoryBreakdown': category_totals,
                'recentExpenses': recent_expenses_data,
                'totalExpenses': len(filtered_expenses),
                'averageExpense': sum(exp['amount'] for exp in filtered_expenses) / len(filtered_expenses) if filtered_expenses else 0
            }
           
            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Expense summary retrieved successfully'
            })
           
        except Exception as e:
            print(f"Error in get_expense_summary: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense summary',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expense_summary()

@expenses_bp.route('/categories', methods=['GET'])
def get_expense_categories():
    @expenses_bp.token_required
    def _get_expense_categories(current_user):
        try:
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            query = {'userId': current_user['_id']}
            if start_date or end_date:
                date_query = {}
                if start_date:
                    date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    date_query['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))
                query['date'] = date_query
           
            expenses = list(expenses_bp.mongo.db.expenses.find(query))
            category_totals = {}
            categories = set()
           
            for expense in expenses:
                category = expense.get('category', 'Uncategorized')
                categories.add(category)
                category_totals[category] = category_totals.get(category, 0) + expense.get('amount', 0)
           
            if not categories:
                default_categories = {
                    'Food & Dining', 'Transportation', 'Shopping', 'Entertainment',
                    'Bills & Utilities', 'Healthcare', 'Education', 'Travel',
                    'Personal Care', 'Home & Garden', 'Gifts & Donations',
                    'Office & Admin', 'Staff & Wages', 'Business Transport', 'Rent & Utilities',
                    'Marketing & Sales Expenses', 'Cost of Goods Sold - COGS', 'Personal Expenses',
                    'Statutory & Legal Contributions', 'Other'
                }
                categories = default_categories
                for cat in default_categories:
                    category_totals[cat] = 0.0
           
            return jsonify({
                'success': True,
                'data': category_totals,
                'message': 'Expense categories retrieved successfully'
            })
           
        except Exception as e:
            print(f"Error in get_expense_categories: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense categories',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expense_categories()

# FIXED: Only ONE /statistics endpoint
@expenses_bp.route('/statistics', methods=['GET'])
def get_expense_statistics():
    @expenses_bp.token_required
    def _fetch_statistics(current_user):
        try:
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            now = datetime.utcnow()
            filter_start = datetime.fromisoformat(start_date.replace('Z', '')) if start_date else now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            filter_end = datetime.fromisoformat(end_date.replace('Z', '')) if end_date else now
           
            pipeline = [
                {'$match': {
                    'userId': current_user['_id'],
                    'date': {'$gte': filter_start, '$lte': filter_end}
                }},
                {'$group': {
                    '_id': None,
                    'totalAmount': {'$sum': '$amount'},
                    'totalCount': {'$sum': 1},
                    'averageAmount': {'$avg': '$amount'},
                    'maxAmount': {'$max': '$amount'},
                    'minAmount': {'$min': '$amount'}
                }}
            ]
           
            result = list(expenses_bp.mongo.db.expenses.aggregate(pipeline))
           
            stats = result[0] if result else {}
            statistics_data = {
                'totalAmount': float(stats.get('totalAmount', 0)),
                'totalCount': int(stats.get('totalCount', 0)),
                'averageAmount': float(stats.get('averageAmount', 0)) if stats.get('averageAmount') else 0,
                'maxAmount': float(stats.get('maxAmount', 0)) if stats.get('maxAmount') else 0,
                'minAmount': float(stats.get('minAmount', 0)) if stats.get('minAmount') else 0,
                'period': {
                    'startDate': filter_start.isoformat() + 'Z',
                    'endDate': filter_end.isoformat() + 'Z'
                }
            }
           
            return jsonify({
                'success': True,
                'data': statistics_data,
                'message': 'Expense statistics retrieved successfully'
            })
           
        except Exception as e:
            print(f"Error in get_expense_statistics: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense statistics',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _fetch_statistics()

@expenses_bp.route('/insights', methods=['GET'])
def get_expense_insights():
    @expenses_bp.token_required
    def _get_expense_insights(current_user):
        try:
            expenses = list(expenses_bp.mongo.db.expenses.find({'userId': current_user['_id']}))
            if not expenses:
                return jsonify({
                    'success': True,
                    'data': {'insights': [], 'message': 'No expense data available for insights'},
                    'message': 'Expense insights retrieved successfully'
                })
           
            now = datetime.utcnow()
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start_of_last_month = (start_of_month - timedelta(days=1)).replace(day=1)
           
            current_month_expenses = [e for e in expenses if e['date'] >= start_of_month]
            last_month_expenses = [e for e in expenses if start_of_last_month <= e['date'] < start_of_month]
           
            current_total = sum(e['amount'] for e in current_month_expenses)
            last_total = sum(e['amount'] for e in last_month_expenses)
           
            insights = []
            if last_total > 0:
                change = ((current_total - last_total) / last_total) * 100
                if change > 15:
                    insights.append({'type': 'increase', 'title': 'Spending Increase', 'message': f'Up {change:.1f}% this month', 'value': change, 'priority': 'high'})
                elif change < -15:
                    insights.append({'type': 'decrease', 'title': 'Spending Down', 'message': f'Down {abs(change):.1f}% – well done!', 'value': change, 'priority': 'high'})
           
            category_totals = {}
            for e in current_month_expenses:
                cat = e.get('category', 'Other')
                category_totals[cat] = category_totals.get(cat, 0) + e['amount']
           
            if category_totals:
                top_cat, top_amt = max(category_totals.items(), key=lambda x: x[1])
                pct = (top_amt / current_total) * 100 if current_total else 0
                insights.append({'type': 'top_category', 'title': 'Top Category', 'message': f'{top_cat}: {pct:.1f}% of spending', 'value': top_amt, 'priority': 'medium'})
           
            days = now.day
            avg_daily = current_total / days if days else 0
            insights.append({'type': 'daily_average', 'title': 'Daily Avg', 'message': f'₦{avg_daily:,.0f}/day', 'value': avg_daily, 'priority': 'low'})
           
            return jsonify({
                'success': True,
                'data': {
                    'insights': insights,
                    'summary': {
                        'current_month_total': current_total,
                        'last_month_total': last_total,
                        'total_categories': len(category_totals),
                        'total_expenses_count': len(current_month_expenses)
                    }
                },
                'message': 'Expense insights retrieved successfully'
            })
           
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve expense insights',
                'errors': {'general': [str(e)]}
            }), 500
   
    return _get_expense_insights()