from flask import Blueprint, request, jsonify, make_response
from datetime import datetime, timedelta
from bson import ObjectId
import csv
import io
from collections import defaultdict
from utils.payment_utils import normalize_sales_type, validate_sales_type
from utils.monthly_entry_tracker import MonthlyEntryTracker

def init_income_blueprint(mongo, token_required, serialize_doc):
    """Initialize the income blueprint with database and auth decorator"""
    income_bp = Blueprint('income', __name__, url_prefix='/income')

    @income_bp.route('', methods=['GET'])
    @token_required
    def get_incomes(current_user):
        try:
            # FIXED: Use offset/limit instead of page for consistency with frontend
            limit = min(int(request.args.get('limit', 50)), 100)
            offset = max(int(request.args.get('offset', 0)), 0)
            category = request.args.get('category')
            frequency = request.args.get('frequency')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            sort_by = request.args.get('sort_by', 'dateReceived')
            sort_order = request.args.get('sort_order', 'desc')
            
            # Build query - ONLY actual received incomes
            now = datetime.utcnow()
            query = {
                'userId': current_user['_id'],
                'dateReceived': {'$lte': now}  # Only past and present incomes
            }
            
            if category:
                query['category'] = category
            if frequency:
                query['frequency'] = frequency
            if start_date or end_date:
                date_query = query.get('dateReceived', {})
                if start_date:
                    date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    date_query['$lte'] = min(datetime.fromisoformat(end_date.replace('Z', '')), now)
                query['dateReceived'] = date_query
            
            # FIXED: Proper sorting
            sort_direction = -1 if sort_order == 'desc' else 1
            sort_field = sort_by if sort_by in ['dateReceived', 'amount', 'source', 'createdAt'] else 'dateReceived'
            
            # Get incomes with pagination
            incomes = list(mongo.db.incomes.find(query).sort(sort_field, sort_direction).skip(offset).limit(limit))
            total = mongo.db.incomes.count_documents(query)
            
            # Serialize incomes with proper field mapping
            income_list = []
            for income in incomes:
                income_data = serialize_doc(income.copy())
                # FIXED: Map source to title for frontend compatibility
                income_data['title'] = income_data.get('source', income_data.get('title', 'Income'))
                income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
                income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                income_data['updatedAt'] = income_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if income_data.get('updatedAt') else None
                # Removed recurring date logic - simplified income tracking
                income_data['nextRecurringDate'] = None
                income_list.append(income_data)
            
            # FIXED: Pagination format expected by frontend
            has_more = offset + limit < total
            
            return jsonify({
                'success': True,
                'data': {
                    'incomes': income_list,
                    'pagination': {
                        'total': total,
                        'limit': limit,
                        'offset': offset,
                        'hasMore': has_more,
                        'page': (offset // limit) + 1,
                        'pages': (total + limit - 1) // limit
                    }
                },
                'message': 'Income records retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_incomes: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income records',
                'errors': {'general': [str(e)]}
            }), 500

    @income_bp.route('/<income_id>', methods=['GET'])
    @token_required
    def get_income(current_user, income_id):
        try:
            income = mongo.db.incomes.find_one({
                '_id': ObjectId(income_id),
                'userId': current_user['_id']
            })
            
            if not income:
                return jsonify({
                    'success': False,
                    'message': 'Income record not found'
                }), 404
            
            income_data = serialize_doc(income.copy())
            income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
            income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            income_data['updatedAt'] = income_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z' if income_data.get('updatedAt') else None
            # Removed recurring date logic - simplified income tracking
            income_data['nextRecurringDate'] = None
            
            return jsonify({
                'success': True,
                'data': income_data,
                'message': 'Income record retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income record',
                'errors': {'general': [str(e)]}
            }), 500

    @income_bp.route('', methods=['POST'])
    @token_required
    def create_income(current_user):
        try:
            data = request.get_json()
            
            # Validation
            errors = {}
            if not data.get('amount') or data.get('amount', 0) <= 0:
                errors['amount'] = ['Valid amount is required']
            if not data.get('source'):
                errors['source'] = ['Income source is required']
            if not data.get('category'):
                errors['category'] = ['Income category is required']
            # salesType is optional but when provided should be either 'cash' or 'credit'
            if data.get('salesType') and not validate_sales_type(data.get('salesType')):
                errors['salesType'] = ['Invalid salesType value']
            if not data.get('frequency'):
                errors['frequency'] = ['Income frequency is required']
            
            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400
            
            # NEW: Check monthly entry limit for free tier users
            entry_tracker = MonthlyEntryTracker(mongo)
            fc_check = entry_tracker.should_deduct_fc(current_user['_id'], 'income')
            
            # If FC deduction is required, check user has sufficient credits
            if fc_check['deduct_fc']:
                user = mongo.db.users.find_one({'_id': current_user['_id']})
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
            
            # NOTE: If within free limit, no FC deduction needed
            # If over limit, FC will be deducted after successful creation
            
            # Simplified: No recurring logic - all incomes are one-time entries
            
            # CRITICAL FIX: Ensure amount is stored exactly as provided, no multipliers
            raw_amount = float(data['amount'])
            
            # Normalize salesType if present
            normalized_sales_type = normalize_sales_type(data.get('salesType')) if data.get('salesType') else None

            income_data = {
                'userId': current_user['_id'],
                'amount': raw_amount,  # Store exact amount, no calculations
                'source': data['source'],
                'description': data.get('description', ''),
                'category': data['category'],
                'salesType': normalized_sales_type,
                'frequency': 'one_time',  # Always one-time now
                'dateReceived': datetime.fromisoformat(data.get('dateReceived', datetime.utcnow().isoformat()).replace('Z', '')),
                'isRecurring': False,  # Always false now
                'nextRecurringDate': None,  # Always null now
                'metadata': data.get('metadata', {}),
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            # DEBUG: Log the exact amount being stored
            print(f"DEBUG: Creating income record with amount: {raw_amount} for user: {current_user['_id']}")
            
            result = mongo.db.incomes.insert_one(income_data)
            income_id = str(result.inserted_id)
            
            # NEW: Deduct FC if required (over monthly limit)
            if fc_check['deduct_fc']:
                # Deduct credits from user account
                user = mongo.db.users.find_one({'_id': current_user['_id']})
                current_balance = user.get('ficoreCreditBalance', 0.0)
                new_balance = current_balance - fc_check['fc_cost']
                
                mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'ficoreCreditBalance': new_balance}}
                )
                
                # Create transaction record
                transaction = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'type': 'debit',
                    'amount': fc_check['fc_cost'],
                    'description': f'Income entry over monthly limit (entry #{fc_check["monthly_data"]["count"] + 1})',
                    'operation': 'create_income_over_limit',
                    'balanceBefore': current_balance,
                    'balanceAfter': new_balance,
                    'status': 'completed',
                    'createdAt': datetime.utcnow(),
                    'metadata': {
                        'operation': 'create_income_over_limit',
                        'deductionType': 'monthly_limit_exceeded',
                        'monthly_data': fc_check['monthly_data']
                    }
                }
                
                mongo.db.credit_transactions.insert_one(transaction)
            
            # FIXED: Return full income data like other endpoints
            created_income = serialize_doc(income_data.copy())
            created_income['id'] = income_id
            created_income['title'] = created_income.get('source', 'Income')  # Map for frontend
            created_income['dateReceived'] = created_income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
            created_income['createdAt'] = created_income.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            created_income['updatedAt'] = created_income.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            created_income['nextRecurringDate'] = None
            
            return jsonify({
                'success': True,
                'data': created_income,
                'message': 'Income record created successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to create income record',
                'errors': {'general': [str(e)]}
            }), 500

    @income_bp.route('/summary', methods=['GET'])
    @token_required
    def get_income_summary(current_user):
        try:
            # Validate database connection
            if mongo is None or mongo.db is None:
                return jsonify({
                    'success': False,
                    'message': 'Database connection error',
                    'errors': {'general': ['Database not available']}
                }), 500
            
            # Get date ranges with error handling
            try:
                now = datetime.utcnow()
                start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                start_of_last_month = (start_of_month - timedelta(days=1)).replace(day=1)
                start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            except Exception as date_error:
                return jsonify({
                    'success': False,
                    'message': 'Date calculation error',
                    'errors': {'general': [str(date_error)]}
                }), 500
            
            # CRITICAL: Calculate totals using MongoDB aggregation - NO LIMITS
            # Aggregation counts/sums ALL records matching the criteria
            # This ensures accurate totals regardless of how many records exist
            try:
                print(f"DEBUG INCOME SUMMARY - User: {current_user['_id']}")
                print(f"DEBUG: Date ranges - Start of month: {start_of_month}, Start of year: {start_of_year}")
                
                # Calculate this month total using aggregation - NO LIMIT, counts ALL records
                total_this_month_result = list(mongo.db.incomes.aggregate([
                    {'$match': {
                        'userId': current_user['_id'],
                        'dateReceived': {'$gte': start_of_month, '$lte': now}
                    }},
                    {'$group': {'_id': None, 'total': {'$sum': '$amount'}, 'count': {'$sum': 1}}}
                ]))
                total_this_month = total_this_month_result[0]['total'] if total_this_month_result else 0.0
                this_month_count = total_this_month_result[0]['count'] if total_this_month_result else 0
                print(f"DEBUG: CALCULATED total_this_month = {total_this_month}, count = {this_month_count}")
                
                # Calculate last month total using aggregation - NO LIMIT, counts ALL records
                total_last_month_result = list(mongo.db.incomes.aggregate([
                    {'$match': {
                        'userId': current_user['_id'],
                        'dateReceived': {'$gte': start_of_last_month, '$lt': start_of_month}
                    }},
                    {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
                ]))
                total_last_month = total_last_month_result[0]['total'] if total_last_month_result else 0.0
                print(f"DEBUG: CALCULATED total_last_month = {total_last_month}")
                
                # Calculate YTD total and count using aggregation - NO LIMIT, counts ALL records
                year_to_date_result = list(mongo.db.incomes.aggregate([
                    {'$match': {
                        'userId': current_user['_id'],
                        'dateReceived': {'$gte': start_of_year, '$lte': now}
                    }},
                    {'$group': {'_id': None, 'total': {'$sum': '$amount'}, 'count': {'$sum': 1}}}
                ]))
                year_to_date = year_to_date_result[0]['total'] if year_to_date_result else 0.0
                ytd_record_count = year_to_date_result[0]['count'] if year_to_date_result else 0
                print(f"DEBUG: CALCULATED year_to_date = {year_to_date}, ytd_record_count = {ytd_record_count}")
                
                # Get all-time record count for fallback - NO LIMIT, counts ALL records
                all_time_record_count = mongo.db.incomes.count_documents({'userId': current_user['_id']})
                print(f"DEBUG: CALCULATED all_time_record_count = {all_time_record_count}")
                
                # CRITICAL FIX: Fallback to all-time if YTD is 0
                final_record_count = ytd_record_count if ytd_record_count > 0 else all_time_record_count
                print(f"DEBUG: FINAL record_count (with fallback) = {final_record_count}")
                
                # Calculate average monthly (last 12 months) - NO LIMIT, processes ALL records
                twelve_months_ago = now - timedelta(days=365)
                monthly_totals = list(mongo.db.incomes.aggregate([
                    {'$match': {
                        'userId': current_user['_id'],
                        'dateReceived': {'$gte': twelve_months_ago, '$lte': now}
                    }},
                    {'$group': {
                        '_id': {'year': {'$year': '$dateReceived'}, 'month': {'$month': '$dateReceived'}},
                        'total': {'$sum': '$amount'}
                    }}
                ]))
                average_monthly = sum(item['total'] for item in monthly_totals) / max(len(monthly_totals), 1) if monthly_totals else 0
                
                # Get recent incomes (last 5)
                recent_incomes = list(mongo.db.incomes.find({
                    'userId': current_user['_id']
                }).sort('dateReceived', -1).limit(5))
                
                recent_incomes_data = []
                for income in recent_incomes:
                    income_data = serialize_doc(income.copy())
                    income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
                    income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                    recent_incomes_data.append(income_data)
                
                # Get top sources using aggregation
                top_sources_data = list(mongo.db.incomes.aggregate([
                    {'$match': {'userId': current_user['_id']}},
                    {'$group': {'_id': '$source', 'total': {'$sum': '$amount'}}},
                    {'$sort': {'total': -1}},
                    {'$limit': 5}
                ]))
                top_sources = {item['_id']: item['total'] for item in top_sources_data}
                
                # CRITICAL FIX: Consistent growth percentage calculation
                # Use the SAME logic as insights endpoint to prevent contradictions
                growth_percentage = 0
                if total_last_month > 0:
                    growth_percentage = ((total_this_month - total_last_month) / total_last_month) * 100
                elif total_this_month > 0 and total_last_month == 0:
                    # Special case: if there's income this month but none last month, show 100% growth
                    growth_percentage = 100.0
                
                print(f"DEBUG: CALCULATED growth_percentage = {growth_percentage}% (this_month={total_this_month}, last_month={total_last_month})")
                
                summary_data = {
                    'total_this_month': total_this_month,
                    'total_last_month': total_last_month,
                    'average_monthly': average_monthly,
                    'year_to_date': year_to_date,
                    'total_records': final_record_count,  # CRITICAL FIX: YTD count with fallback to all-time
                    'recent_incomes': recent_incomes_data,
                    'top_sources': top_sources,
                    'growth_percentage': growth_percentage
                }
                
                # CRITICAL DEBUG: Log the final response
                print(f"DEBUG: FINAL INCOME SUMMARY RESPONSE:")
                print(f"  total_this_month: {total_this_month}")
                print(f"  total_last_month: {total_last_month}")
                print(f"  year_to_date: {year_to_date}")
                print(f"  total_records: {final_record_count} (YTD: {ytd_record_count}, All-time: {all_time_record_count})")
                print(f"  growth_percentage: {growth_percentage}%")
                
                return jsonify({
                    'success': True,
                    'data': summary_data,
                    'message': 'Income summary retrieved successfully'
                })
                
            except Exception as calc_error:
                return jsonify({
                    'success': False,
                    'message': 'Calculation error in income summary',
                    'errors': {'general': [str(calc_error)]}
                }), 500
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income summary',
                'errors': {'general': [str(e)]}
            }), 500

    @income_bp.route('/counts', methods=['GET'])
    @token_required
    def get_income_counts(current_user):
        """Get total income counts bypassing pagination - for accurate record counts"""
        try:
            # Validate database connection
            if mongo is None or mongo.db is None:
                return jsonify({
                    'success': False,
                    'message': 'Database connection error',
                    'errors': {'general': ['Database not available']}
                }), 500
            
            now = datetime.utcnow()
            start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            print(f"DEBUG INCOME COUNTS - User: {current_user['_id']}")
            
            # Count YTD records - NO PAGINATION LIMIT
            ytd_count = mongo.db.incomes.count_documents({
                'userId': current_user['_id'],
                'dateReceived': {'$gte': start_of_year, '$lte': now}
            })
            print(f"DEBUG: YTD count = {ytd_count}")
            
            # Count all-time records - NO PAGINATION LIMIT
            all_time_count = mongo.db.incomes.count_documents({
                'userId': current_user['_id']
            })
            print(f"DEBUG: All-time count = {all_time_count}")
            
            # Count this month records - NO PAGINATION LIMIT
            this_month_count = mongo.db.incomes.count_documents({
                'userId': current_user['_id'],
                'dateReceived': {'$gte': start_of_month, '$lte': now}
            })
            print(f"DEBUG: This month count = {this_month_count}")
            
            return jsonify({
                'success': True,
                'data': {
                    'ytd_count': ytd_count,
                    'all_time_count': all_time_count,
                    'this_month_count': this_month_count
                },
                'message': 'Income counts retrieved successfully'
            })
            
        except Exception as e:
            print(f"ERROR in get_income_counts: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income counts',
                'errors': {'general': [str(e)]}
            }), 500

    @income_bp.route('/insights', methods=['GET'])
    @token_required
    def get_income_insights(current_user):
        try:
            # FIXED: Get user's income data for analysis - ONLY actual received incomes
            now = datetime.utcnow()
            incomes = list(mongo.db.incomes.find({
                'userId': current_user['_id'],
                'dateReceived': {'$lte': now}  # Only past and present incomes, no projections
            }))
            
            # CRITICAL DEBUG: Log insights calculation
            print(f"DEBUG INCOME INSIGHTS - User: {current_user['_id']}")
            print(f"DEBUG: Total incomes retrieved: {len(incomes)}")
            
            if not incomes:
                return jsonify({
                    'success': True,
                    'data': {
                        'insights': [],
                        'message': 'No income data available for insights'
                    },
                    'message': 'Income insights retrieved successfully'
                })
            
            # Calculate insights based on ACTUAL received amounts only
            insights = []
            
            # Get current month data - MUST USE EXACT SAME LOGIC AS SUMMARY ENDPOINT
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start_of_last_month = (start_of_month - timedelta(days=1)).replace(day=1)
            
            # Current month income
            current_month_incomes = [inc for inc in incomes if inc.get('dateReceived') and inc['dateReceived'] >= start_of_month]
            current_month_total = sum(inc.get('amount', 0) for inc in current_month_incomes)
            
            print(f"DEBUG INSIGHTS: This month incomes count: {len(current_month_incomes)}")
            print(f"DEBUG INSIGHTS: This month total: {current_month_total}")
            
            # Last month income
            last_month_incomes = [inc for inc in incomes if inc.get('dateReceived') and start_of_last_month <= inc['dateReceived'] < start_of_month]
            last_month_total = sum(inc.get('amount', 0) for inc in last_month_incomes)
            
            print(f"DEBUG INSIGHTS: Last month incomes count: {len(last_month_incomes)}")
            print(f"DEBUG INSIGHTS: Last month total: {last_month_total}")
            
            # CRITICAL FIX: Growth insight - MUST USE EXACT SAME CALCULATION AS SUMMARY
            if last_month_total > 0:
                growth_rate = ((current_month_total - last_month_total) / last_month_total) * 100
                print(f"DEBUG INSIGHTS: Calculated growth_rate = {growth_rate}%")
                
                if growth_rate > 10:
                    insights.append({
                        'type': 'growth',
                        'title': 'Income Growth',
                        'message': f'Your income increased by {growth_rate:.1f}% this month!',
                        'severity': 'success',
                        'value': growth_rate,
                        'priority': 'high'
                    })
                elif growth_rate < -10:
                    insights.append({
                        'type': 'decline',
                        'title': 'Income Decline',
                        'message': f'Your income decreased by {abs(growth_rate):.1f}% this month.',
                        'severity': 'warning',
                        'value': growth_rate,
                        'priority': 'medium'
                    })
            elif current_month_total > 0 and last_month_total == 0:
                # Special case: income this month but none last month
                insights.append({
                    'type': 'growth',
                    'title': 'Income Started',
                    'message': 'You have income this month! Keep it up.',
                    'severity': 'success',
                    'value': 100.0,
                    'priority': 'high'
                })
            
            # Top income source
            source_totals = defaultdict(float)
            for income in current_month_incomes:
                source_totals[income['source']] += income['amount']
            
            if source_totals:
                top_source = max(source_totals.items(), key=lambda x: x[1])
                insights.append({
                    'type': 'top_source',
                    'title': 'Top Income Source',
                    'message': f'{top_source[0]} is your highest income source this month',
                    'value': top_source[1],
                    'priority': 'low'
                })
            
            # Removed recurring income insight - simplified tracking
            
            # Average monthly income
            twelve_months_ago = now - timedelta(days=365)
            recent_incomes = [inc for inc in incomes if inc['dateReceived'] >= twelve_months_ago]
            if recent_incomes:
                avg_monthly = sum(inc['amount'] for inc in recent_incomes) / 12
                insights.append({
                    'type': 'average',
                    'title': 'Monthly Average',
                    'message': f'Your average monthly income is ₦{avg_monthly:,.0f}',
                    'value': avg_monthly,
                    'priority': 'low'
                })
            
            # Income consistency insight
            monthly_totals = []
            for i in range(6):  # Last 6 months
                month_start = (now - timedelta(days=30*i)).replace(day=1)
                month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                month_incomes = [inc for inc in incomes if month_start <= inc['dateReceived'] <= month_end]
                monthly_totals.append(sum(inc['amount'] for inc in month_incomes))
            
            if len(monthly_totals) >= 3:
                avg_monthly = sum(monthly_totals) / len(monthly_totals)
                variance = sum((x - avg_monthly) ** 2 for x in monthly_totals) / len(monthly_totals)
                std_dev = variance ** 0.5
                consistency_score = max(0, 100 - (std_dev / avg_monthly * 100)) if avg_monthly > 0 else 0
                
                if consistency_score > 80:
                    insights.append({
                        'type': 'consistency',
                        'title': 'Stable Income',
                        'message': f'Your income is very consistent ({consistency_score:.0f}% stability)',
                        'value': consistency_score,
                        'priority': 'medium'
                    })
                elif consistency_score < 50:
                    insights.append({
                        'type': 'volatility',
                        'title': 'Variable Income',
                        'message': 'Your income varies significantly month to month',
                        'value': consistency_score,
                        'priority': 'medium'
                    })
            
            return jsonify({
                'success': True,
                'data': {
                    'insights': insights,
                    'summary': {
                        'current_month_total': current_month_total,
                        'last_month_total': last_month_total,
                        'total_sources': len(source_totals)
                    }
                },
                'message': 'Income insights retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income insights',
                'errors': {'general': [str(e)]}
            }), 500

    @income_bp.route('/<income_id>', methods=['PUT'])
    @token_required
    def update_income(current_user, income_id):
        try:
            # Validate income_id
            if not ObjectId.is_valid(income_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid income ID'
                }), 400

            # Get request data
            data = request.get_json()
            if not data:
                return jsonify({
                    'success': False,
                    'message': 'No data provided'
                }), 400

            # Find existing income record
            existing_income = mongo.db.incomes.find_one({
                '_id': ObjectId(income_id),
                'userId': current_user['_id']
            })

            if not existing_income:
                return jsonify({
                    'success': False,
                    'message': 'Income record not found'
                }), 404

            # Validation
            errors = {}
            if 'amount' in data and (not data.get('amount') or data.get('amount', 0) <= 0):
                errors['amount'] = ['Valid amount is required']
            if 'source' in data and not data.get('source'):
                errors['source'] = ['Income source is required']
            if 'category' in data and not data.get('category'):
                errors['category'] = ['Income category is required']
            if 'frequency' in data and not data.get('frequency'):
                errors['frequency'] = ['Income frequency is required']

            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400

            # Prepare update data
            update_data = {'updatedAt': datetime.utcnow()}
            
            # CRITICAL FIX: Update fields if provided - ensure exact amounts
            if 'amount' in data:
                raw_amount = float(data['amount'])
                update_data['amount'] = raw_amount  # Store exact amount, no calculations
                # DEBUG: Log the exact amount being updated
                print(f"DEBUG: Updating income record {income_id} with amount: {raw_amount} for user: {current_user['_id']}")
            if 'source' in data:
                update_data['source'] = data['source']
            if 'description' in data:
                update_data['description'] = data['description']
            if 'category' in data:
                update_data['category'] = data['category']
            if 'frequency' in data:
                update_data['frequency'] = data['frequency']
            if 'dateReceived' in data:
                update_data['dateReceived'] = datetime.fromisoformat(data['dateReceived'].replace('Z', ''))
            if 'metadata' in data:
                update_data['metadata'] = data['metadata']

            # Simplified: Always set to non-recurring
            update_data['isRecurring'] = False
            update_data['nextRecurringDate'] = None
            if 'frequency' in data:
                update_data['frequency'] = 'one_time'  # Always one-time now

            # Update the income record
            result = mongo.db.incomes.update_one(
                {'_id': ObjectId(income_id), 'userId': current_user['_id']},
                {'$set': update_data}
            )

            if result.matched_count == 0:
                return jsonify({
                    'success': False,
                    'message': 'Income record not found'
                }), 404

            # Get updated income record
            updated_income = mongo.db.incomes.find_one({
                '_id': ObjectId(income_id),
                'userId': current_user['_id']
            })

            # Serialize the updated income
            income_data = serialize_doc(updated_income.copy())
            income_data['dateReceived'] = income_data.get('dateReceived', datetime.utcnow()).isoformat() + 'Z'
            income_data['createdAt'] = income_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            income_data['updatedAt'] = income_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            next_recurring = income_data.get('nextRecurringDate')
            income_data['nextRecurringDate'] = next_recurring.isoformat() + 'Z' if next_recurring else None

            return jsonify({
                'success': True,
                'data': income_data,
                'message': 'Income record updated successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update income record',
                'errors': {'general': [str(e)]}
            }), 500

    @income_bp.route('/<income_id>', methods=['PATCH'])
    @token_required
    def patch_income(current_user, income_id):
        """Partial update of income record (alias for PUT)"""
        return update_income(current_user, income_id)

    @income_bp.route('/<income_id>', methods=['DELETE'])
    @token_required
    def delete_income(current_user, income_id):
        try:
            # Validate income_id
            if not ObjectId.is_valid(income_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid income ID'
                }), 400

            # Find and delete the income record
            result = mongo.db.incomes.delete_one({
                '_id': ObjectId(income_id),
                'userId': current_user['_id']
            })

            # Check if a document was deleted
            if result.deleted_count == 0:
                return jsonify({
                    'success': False,
                    'message': 'Income record not found or you do not have permission to delete it'
                }), 404

            return jsonify({
                'success': True,
                'message': 'Income record deleted successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to delete income record',
                'errors': {'general': [str(e)]}
            }), 500

    @income_bp.route('/statistics', methods=['GET'])
    @token_required
    def get_income_statistics(current_user):
        """Get comprehensive income statistics in format expected by frontend"""
        try:
            # Get date range parameters
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            
            # Default to current month if no dates provided
            now = datetime.utcnow()
            if start_date_str:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', ''))
            else:
                start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            if end_date_str:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', ''))
            else:
                end_date = now
            
            # Get income data - ONLY actual received incomes within date range
            query = {
                'userId': current_user['_id'],
                'dateReceived': {
                    '$gte': start_date,
                    '$lte': end_date
                }
            }
            incomes = list(mongo.db.incomes.find(query))
            
            if not incomes:
                # Return empty statistics structure
                return jsonify({
                    'success': True,
                    'data': {
                        'statistics': {
                            'totals': {
                                'count': 0,
                                'totalAmount': 0,
                                'averageAmount': 0,
                                'maxAmount': 0,
                                'minAmount': 0
                            },
                            'breakdown': {
                                'bySource': {},
                                'byMonth': {}
                            },
                            'insights': {
                                'topSource': 'None',
                                'topSourceAmount': 0,
                                'sourcesCount': 0
                            }
                        }
                    },
                    'message': 'Income statistics retrieved successfully'
                })
            
            # Calculate statistics in the format expected by frontend
            amounts = [inc.get('amount', 0) for inc in incomes]
            total_amount = sum(amounts)
            avg_amount = total_amount / len(amounts) if amounts else 0
            max_amount = max(amounts) if amounts else 0
            min_amount = min(amounts) if amounts else 0
            
            # Source breakdown
            sources = {}
            for income in incomes:
                source = income.get('source', 'Unknown')
                sources[source] = sources.get(source, 0) + income.get('amount', 0)
            
            # Monthly breakdown
            monthly = {}
            for income in incomes:
                date = income.get('dateReceived', datetime.utcnow())
                month_key = date.strftime('%Y-%m')
                monthly[month_key] = monthly.get(month_key, 0) + income.get('amount', 0)
            
            # FIXED: Return statistics in the format expected by IncomeStatistics.fromJson()
            statistics_data = {
                'totals': {
                    'count': len(incomes),
                    'totalAmount': total_amount,
                    'averageAmount': avg_amount,
                    'maxAmount': max_amount,
                    'minAmount': min_amount
                },
                'breakdown': {
                    'bySource': sources,
                    'byMonth': monthly
                },
                'insights': {
                    'topSource': max(sources.items(), key=lambda x: x[1])[0] if sources else 'None',
                    'topSourceAmount': max(sources.values()) if sources else 0,
                    'sourcesCount': len(sources)
                }
            }
            
            return jsonify({
                'success': True,
                'data': {
                    'statistics': statistics_data
                },
                'message': 'Income statistics retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_income_statistics: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income statistics',
                'errors': {'general': [str(e)]}
            }), 500
            incomes = list(mongo.db.incomes.find({
                'userId': current_user['_id'],
                'dateReceived': {
                    '$gte': start_date,
                    '$lte': end_date
                }
            }))
            
            # Calculate comprehensive statistics
            total_income = sum(income.get('amount', 0) for income in incomes)
            total_count = len(incomes)
            
            # Monthly average calculation
            months_in_range = max(1, (end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1)
            monthly_average = total_income / months_in_range if months_in_range > 0 else 0
            
            # Yearly projection based on current monthly average
            yearly_projection = monthly_average * 12
            
            # Category breakdown
            category_breakdown = defaultdict(float)
            for income in incomes:
                category = income.get('category', 'other')
                category_breakdown[category] += income.get('amount', 0)
            
            # Source breakdown
            source_breakdown = defaultdict(float)
            for income in incomes:
                source = income.get('source', 'unknown')
                source_breakdown[source] += income.get('amount', 0)
            
            # Frequency breakdown (simplified since we removed recurring logic)
            frequency_breakdown = {'one_time': total_income}
            
            # Calculate trends (monthly data for the last 12 months)
            trends = []
            for i in range(12):
                month_start = (now - timedelta(days=30*i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                month_incomes = [inc for inc in incomes if month_start <= inc.get('dateReceived', now) <= month_end]
                month_total = sum(inc.get('amount', 0) for inc in month_incomes)
                trends.append({
                    'period': month_start.strftime('%Y-%m'),
                    'amount': month_total,
                    'count': len(month_incomes)
                })
            trends.reverse()  # Chronological order
            
            # Growth rate calculation (current month vs previous month)
            current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            prev_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
            prev_month_end = current_month_start - timedelta(days=1)
            
            current_month_incomes = [inc for inc in incomes if inc.get('dateReceived', now) >= current_month_start]
            prev_month_incomes = [inc for inc in incomes if prev_month_start <= inc.get('dateReceived', now) <= prev_month_end]
            
            current_month_total = sum(inc.get('amount', 0) for inc in current_month_incomes)
            prev_month_total = sum(inc.get('amount', 0) for inc in prev_month_incomes)
            
            growth_rate = 0
            if prev_month_total > 0:
                growth_rate = ((current_month_total - prev_month_total) / prev_month_total) * 100
            
            # Top category and source
            top_category = max(category_breakdown.items(), key=lambda x: x[1])[0] if category_breakdown else 'other'
            top_source = max(source_breakdown.items(), key=lambda x: x[1])[0] if source_breakdown else 'unknown'
            
            # Prepare response data matching frontend expectations
            statistics_data = {
                'total_income': float(total_income),
                'monthly_average': float(monthly_average),
                'yearly_projection': float(yearly_projection),
                'category_breakdown': dict(category_breakdown),
                'source_breakdown': dict(source_breakdown),
                'frequency_breakdown': dict(frequency_breakdown),
                'trends': trends,
                'growth_rate': float(growth_rate),
                'top_category': top_category,
                'top_source': top_source,
                'date_range': {
                    'start_date': start_date.isoformat() + 'Z',
                    'end_date': end_date.isoformat() + 'Z'
                },
                'total_count': total_count
            }
            
            return jsonify({
                'success': True,
                'data': statistics_data,
                'message': 'Income statistics retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_income_statistics: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income statistics',
                'errors': {'general': [str(e)]}
            }), 500

    @income_bp.route('/sources', methods=['GET'])
    @token_required
    def get_income_sources(current_user):
        try:
            # Get query parameters for date filtering
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            # Build query - ONLY actual received incomes
            now = datetime.utcnow()
            query = {
                'userId': current_user['_id'],
                'dateReceived': {'$lte': now}  # Only past and present incomes
            }
            
            if start_date or end_date:
                date_query = query.get('dateReceived', {})
                if start_date:
                    date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    date_query['$lte'] = min(datetime.fromisoformat(end_date.replace('Z', '')), now)
                query['dateReceived'] = date_query
            
            # Get incomes and calculate source totals
            incomes = list(mongo.db.incomes.find(query))
            source_totals = {}
            sources = set()
            
            for income in incomes:
                source = income.get('source', 'Unknown')
                sources.add(source)
                source_totals[source] = source_totals.get(source, 0) + income.get('amount', 0)
            
            # Default sources if none exist
            if not sources:
                default_sources = {
                    'Salary', 'Business Revenue', 'Freelance', 'Investment Returns',
                    'Rental Income', 'Commission', 'Bonus', 'Gift', 'Refund',
                    'Side Hustle', 'Consulting', 'Royalties', 'Other'
                }
                sources = default_sources
                # Set all default sources to 0
                for source in default_sources:
                    source_totals[source] = 0.0
            
            return jsonify({
                'success': True,
                'data': source_totals,  # Return totals instead of just sources
                'message': 'Income sources retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_income_sources: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve income sources',
                'errors': {'general': [str(e)]}
            }), 500

    return income_bp


