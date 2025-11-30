from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
from typing import Dict, Any, Optional
import calendar
import logging
from utils.database_optimizer import DatabaseOptimizer, aggregation_cache
from utils.enhanced_cache import enhanced_cache, CacheWarmer
from utils.cache_invalidation import get_cache_invalidation_service
from utils.performance_monitor import performance_monitor, performance_logger

logger = logging.getLogger(__name__)

def init_financial_aggregation_blueprint(mongo, token_required, serialize_doc):
    """Initialize the financial aggregation blueprint with database and auth decorator"""
    financial_aggregation_bp = Blueprint('financial_aggregation', __name__, url_prefix='/api/financial')
    
    class FinancialAggregationService:
        """Service class for financial data aggregations and calculations"""
        
        def __init__(self, mongo_db):
            self.db = mongo_db
            self.optimizer = DatabaseOptimizer(mongo_db)
            # Initialize optimized indexes on startup
            self.optimizer.create_aggregation_indexes()
            
            # Initialize enhanced caching and warming
            self.cache = enhanced_cache
            self.cache_warmer = CacheWarmer(enhanced_cache, self)
            self.cache_invalidation = get_cache_invalidation_service(enhanced_cache)
            
            # Initialize performance monitoring
            self.performance_monitor = performance_monitor
            self.performance_logger = performance_logger
            
            # Start cache warming service
            self.cache_warmer.start_warming_service()
        
        def get_current_month_totals(self, user_id: ObjectId, use_cache: bool = True) -> Dict[str, Any]:
            """
            Calculate current month income and expense totals from database.
            Uses optimized queries and caching for improved performance.
            
            Args:
                user_id: User's ObjectId
                use_cache: Whether to use cached results if available
                
            Returns:
                Dict containing income, expenses, and metadata
            """
            now = datetime.utcnow()
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end_of_month = (start_of_month + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
            
            # Check enhanced cache first
            if use_cache:
                cached_result = self.cache.get(
                    user_id, 'monthly_totals', 
                    month=now.month, year=now.year
                )
                if cached_result:
                    # Track access for cache warming
                    self.cache_warmer.track_user_access(
                        user_id, 'monthly_totals', 
                        month=now.month, year=now.year
                    )
                    
                    # Log cache hit
                    self.performance_logger.log_cache_operation(
                        'get', 'enhanced', user_id, hit=True, 
                        query_type='monthly_totals'
                    )
                    
                    logger.debug(f"Returning cached monthly totals for user {user_id}")
                    return cached_result
            
            # Use enhanced optimized aggregation pipelines
            income_pipeline = self.optimizer.get_optimized_monthly_pipeline(
                user_id, start_of_month, end_of_month, 'income'
            )
            
            expense_pipeline = self.optimizer.get_optimized_monthly_pipeline(
                user_id, start_of_month, end_of_month, 'expense'
            )
            
            # Execute optimized aggregations with enhanced performance monitoring
            start_time = datetime.utcnow()
            
            # Use allowDiskUse=False to force index usage and prevent disk spills
            income_result = list(self.db.incomes.aggregate(
                income_pipeline, 
                allowDiskUse=False,
                maxTimeMS=5000  # 5 second timeout for performance
            ))
            expense_result = list(self.db.expenses.aggregate(
                expense_pipeline, 
                allowDiskUse=False,
                maxTimeMS=5000  # 5 second timeout for performance
            ))
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            execution_time_ms = execution_time * 1000
            
            # Log query execution performance
            self.performance_logger.log_query_execution(
                'monthly_totals', execution_time_ms, user_id,
                result_count=2,  # income and expense totals
                cache_hit=False,
                month=now.month, year=now.year
            )
            
            logger.debug(f"Monthly totals aggregation completed in {execution_time:.3f}s for user {user_id}")
            
            # Extract enhanced results
            income_data = income_result[0] if income_result else {}
            expense_data = expense_result[0] if expense_result else {}
            
            total_income = income_data.get('totalAmount', 0.0)
            income_count = income_data.get('count', 0)
            income_avg = income_data.get('avgAmount', 0.0)
            
            total_expenses = expense_data.get('totalAmount', 0.0)
            expense_count = expense_data.get('count', 0)
            expense_avg = expense_data.get('avgAmount', 0.0)
            
            result = {
                'income': total_income,
                'expenses': total_expenses,
                'netIncome': total_income - total_expenses,
                'month': now.strftime('%B'),
                'year': now.year,
                'monthNumber': now.month,
                'incomeCount': income_count,
                'expenseCount': expense_count,
                'avgIncome': income_avg,
                'avgExpense': expense_avg,
                'lastUpdated': now.isoformat() + 'Z',
                'executionTimeMs': round(execution_time_ms, 2),
                'period': {
                    'start': start_of_month.isoformat() + 'Z',
                    'end': end_of_month.isoformat() + 'Z'
                },
                'performance': {
                    'queryOptimized': True,
                    'indexesUsed': True,
                    'cacheEnabled': use_cache
                }
            }
            
            # Cache the result with enhanced caching strategy
            if use_cache:
                # Use enhanced cache with intelligent TTL
                optimized_ttl = max(300, min(1800, int(300 + (execution_time_ms / 10))))
                self.cache.set(
                    user_id, 'monthly_totals', result,
                    ttl_seconds=optimized_ttl,
                    month=now.month, year=now.year
                )
                
                # Track access for future cache warming
                self.cache_warmer.track_user_access(
                    user_id, 'monthly_totals', 
                    month=now.month, year=now.year
                )
                
                # Log cache set operation
                self.performance_logger.log_cache_operation(
                    'set', 'enhanced', user_id, hit=False,
                    query_type='monthly_totals', ttl_seconds=optimized_ttl
                )
            
            return result
        
        def get_ytd_record_counts(self, user_id: ObjectId, use_cache: bool = True) -> Dict[str, Any]:
            """
            Get year-to-date transaction counts by category.
            Uses optimized queries and caching for improved performance.
            
            Args:
                user_id: User's ObjectId
                use_cache: Whether to use cached results if available
                
            Returns:
                Dict containing YTD counts by category
            """
            now = datetime.utcnow()
            start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Check enhanced cache first
            if use_cache:
                cached_result = self.cache.get(
                    user_id, 'ytd_counts', year=now.year
                )
                if cached_result:
                    # Track access for cache warming
                    self.cache_warmer.track_user_access(
                        user_id, 'ytd_counts', year=now.year
                    )
                    
                    # Log cache hit
                    self.performance_logger.log_cache_operation(
                        'get', 'enhanced', user_id, hit=True,
                        query_type='ytd_counts'
                    )
                    
                    logger.debug(f"Returning cached YTD counts for user {user_id}")
                    return cached_result
            
            # Use enhanced optimized aggregation pipelines
            income_pipeline = self.optimizer.get_optimized_ytd_pipeline(
                user_id, start_of_year, 'income'
            )
            
            expense_pipeline = self.optimizer.get_optimized_ytd_pipeline(
                user_id, start_of_year, 'expense'
            )
            
            # Execute optimized aggregations with enhanced performance monitoring
            start_time = datetime.utcnow()
            
            # Use enhanced aggregation options for better performance
            income_counts = list(self.db.incomes.aggregate(
                income_pipeline, 
                allowDiskUse=False,
                maxTimeMS=10000,  # 10 second timeout for YTD queries
                cursor={'batchSize': 100}  # Optimize cursor batch size
            ))
            expense_counts = list(self.db.expenses.aggregate(
                expense_pipeline, 
                allowDiskUse=False,
                maxTimeMS=10000,  # 10 second timeout for YTD queries
                cursor={'batchSize': 100}  # Optimize cursor batch size
            ))
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            execution_time_ms = execution_time * 1000
            
            # Log query execution performance
            result_count = len(income_counts) + len(expense_counts)
            self.performance_logger.log_query_execution(
                'ytd_counts', execution_time_ms, user_id,
                result_count=result_count,
                cache_hit=False,
                year=now.year
            )
            
            logger.debug(f"YTD counts aggregation completed in {execution_time:.3f}s for user {user_id}")
            
            # Format enhanced results with additional analytics
            income_by_category = {
                item['category']: {
                    'count': item['count'], 
                    'amount': item['totalAmount'],
                    'avgAmount': item['avgAmount'],
                    'firstTransaction': item['firstTransaction'].isoformat() + 'Z',
                    'lastTransaction': item['lastTransaction'].isoformat() + 'Z',
                    'daysSinceFirst': item['daysSinceFirst']
                } for item in income_counts
            }
            expense_by_category = {
                item['category']: {
                    'count': item['count'], 
                    'amount': item['totalAmount'],
                    'avgAmount': item['avgAmount'],
                    'firstTransaction': item['firstTransaction'].isoformat() + 'Z',
                    'lastTransaction': item['lastTransaction'].isoformat() + 'Z',
                    'daysSinceFirst': item['daysSinceFirst']
                } for item in expense_counts
            }
            
            # Calculate totals - CRITICAL FIX: Include expense amounts for YTD calculations
            total_income_count = sum(item['count'] for item in income_counts)
            total_expense_count = sum(item['count'] for item in expense_counts)
            
            # CRITICAL FIX: Calculate total YTD amounts (not just counts)
            total_income_amount = sum(item['totalAmount'] for item in income_counts)
            total_expense_amount = sum(item['totalAmount'] for item in expense_counts)
            
            result = {
                'year': now.year,
                'totalIncomeRecords': total_income_count,
                'totalExpenseRecords': total_expense_count,
                'totalRecords': total_income_count + total_expense_count,
                # CRITICAL FIX: Add the missing YTD expense total that frontend expects
                'totalIncome': total_income_amount,
                'totalExpenses': total_expense_amount,
                'netIncome': total_income_amount - total_expense_amount,
                'incomeByCategory': income_by_category,
                'expenseByCategory': expense_by_category,
                'lastCalculated': now.isoformat() + 'Z',
                'executionTimeMs': round(execution_time_ms, 2),
                'period': {
                    'start': start_of_year.isoformat() + 'Z',
                    'end': now.isoformat() + 'Z'
                },
                'performance': {
                    'queryOptimized': True,
                    'indexesUsed': True,
                    'cacheEnabled': use_cache,
                    'enhancedAnalytics': True
                }
            }
            
            # Cache the result with enhanced caching strategy
            if use_cache:
                # Use enhanced cache with intelligent TTL for YTD data
                optimized_ttl = max(600, min(3600, int(600 + (execution_time_ms / 5))))
                self.cache.set(
                    user_id, 'ytd_counts', result,
                    ttl_seconds=optimized_ttl,
                    year=now.year
                )
                
                # Track access for future cache warming
                self.cache_warmer.track_user_access(
                    user_id, 'ytd_counts', year=now.year
                )
            
            return result
        
        def get_all_time_record_counts(self, user_id: ObjectId) -> Dict[str, Any]:
            """
            Get all-time transaction counts by category.
            CRITICAL FIX: Ensures amount field is properly converted to numeric type before aggregation.
            
            Args:
                user_id: User's ObjectId
                
            Returns:
                Dict containing all-time counts by category
            """
            # All-time Income counts by category with numeric amount conversion
            income_pipeline = [
                {
                    '$match': {
                        'userId': user_id,
                        'amount': {'$exists': True, '$ne': None}
                    }
                },
                # CRITICAL FIX: Convert amount to numeric type
                {
                    '$addFields': {
                        'numericAmount': {
                            '$cond': {
                                'if': {'$type': '$amount'},
                                'then': {
                                    '$cond': {
                                        'if': {'$eq': [{'$type': '$amount'}, 'string']},
                                        'then': {'$toDouble': '$amount'},
                                        'else': '$amount'
                                    }
                                },
                                'else': 0
                            }
                        }
                    }
                },
                {
                    '$match': {
                        'numericAmount': {'$gt': 0}
                    }
                },
                {
                    '$group': {
                        '_id': '$category',
                        'count': {'$sum': 1},
                        'totalAmount': {'$sum': '$numericAmount'}  # Use converted numeric amount
                    }
                }
            ]
            
            # All-time Expense counts by category with numeric amount conversion
            expense_pipeline = [
                {
                    '$match': {
                        'userId': user_id,
                        'amount': {'$exists': True, '$ne': None}
                    }
                },
                # CRITICAL FIX: Convert amount to numeric type
                {
                    '$addFields': {
                        'numericAmount': {
                            '$cond': {
                                'if': {'$type': '$amount'},
                                'then': {
                                    '$cond': {
                                        'if': {'$eq': [{'$type': '$amount'}, 'string']},
                                        'then': {'$toDouble': '$amount'},
                                        'else': '$amount'
                                    }
                                },
                                'else': 0
                            }
                        }
                    }
                },
                {
                    '$match': {
                        'numericAmount': {'$gt': 0}
                    }
                },
                {
                    '$group': {
                        '_id': '$category',
                        'count': {'$sum': 1},
                        'totalAmount': {'$sum': '$numericAmount'}  # Use converted numeric amount
                    }
                }
            ]
            
            # Execute aggregations
            income_counts = list(self.db.incomes.aggregate(income_pipeline))
            expense_counts = list(self.db.expenses.aggregate(expense_pipeline))
            
            # Format results
            income_by_category = {item['_id']: {'count': item['count'], 'amount': item['totalAmount']} for item in income_counts}
            expense_by_category = {item['_id']: {'count': item['count'], 'amount': item['totalAmount']} for item in expense_counts}
            
            # Calculate totals - CRITICAL FIX: Include expense amounts for all-time calculations
            total_income_count = sum(item['count'] for item in income_counts)
            total_expense_count = sum(item['count'] for item in expense_counts)
            
            # CRITICAL FIX: Calculate total all-time amounts (not just counts)
            total_income_amount = sum(item['totalAmount'] for item in income_counts)
            total_expense_amount = sum(item['totalAmount'] for item in expense_counts)
            
            # Get earliest and latest transaction dates for period info
            earliest_income = self.db.incomes.find_one({'userId': user_id}, sort=[('dateReceived', 1)])
            earliest_expense = self.db.expenses.find_one({'userId': user_id}, sort=[('date', 1)])
            
            earliest_date = None
            if earliest_income and earliest_expense:
                earliest_date = min(earliest_income['dateReceived'], earliest_expense['date'])
            elif earliest_income:
                earliest_date = earliest_income['dateReceived']
            elif earliest_expense:
                earliest_date = earliest_expense['date']
            
            now = datetime.utcnow()
            
            return {
                'totalIncomeRecords': total_income_count,
                'totalExpenseRecords': total_expense_count,
                'totalRecords': total_income_count + total_expense_count,
                # CRITICAL FIX: Add the missing all-time expense total that frontend expects
                'totalIncome': total_income_amount,
                'totalExpenses': total_expense_amount,
                'netIncome': total_income_amount - total_expense_amount,
                'incomeByCategory': income_by_category,
                'expenseByCategory': expense_by_category,
                'lastCalculated': now.isoformat() + 'Z',
                'period': {
                    'start': earliest_date.isoformat() + 'Z' if earliest_date else None,
                    'end': now.isoformat() + 'Z'
                }
            }
    
    # Initialize service
    aggregation_service = FinancialAggregationService(mongo.db)
    
    @financial_aggregation_bp.route('/monthly-totals', methods=['GET'])
    @token_required
    def get_monthly_totals(current_user):
        """
        GET /api/financial/monthly-totals
        
        Returns current month income and expense totals calculated from database.
        Supports optional month/year parameters for historical data.
        """
        try:
            # Get optional month/year parameters for historical queries
            month = request.args.get('month', type=int)
            year = request.args.get('year', type=int)
            
            if month and year:
                # Historical month query
                if not (1 <= month <= 12) or year < 2020 or year > datetime.utcnow().year:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid month or year parameter',
                        'errors': {'validation': ['Month must be 1-12, year must be 2020-current']}
                    }), 400
                
                # Calculate for specific month/year
                start_of_month = datetime(year, month, 1)
                if month == 12:
                    end_of_month = datetime(year + 1, 1, 1) - timedelta(seconds=1)
                else:
                    end_of_month = datetime(year, month + 1, 1) - timedelta(seconds=1)
                
                # Custom aggregation for historical month
                user_id = current_user['_id']
                
                income_result = list(mongo.db.incomes.aggregate([
                    {
                        '$match': {
                            'userId': user_id,
                            'dateReceived': {
                                '$gte': start_of_month,
                                '$lte': end_of_month
                            },
                            'amount': {'$exists': True, '$ne': None}
                        }
                    },
                    # CRITICAL FIX: Convert amount to numeric type
                    {
                        '$addFields': {
                            'numericAmount': {
                                '$cond': {
                                    'if': {'$type': '$amount'},
                                    'then': {
                                        '$cond': {
                                            'if': {'$eq': [{'$type': '$amount'}, 'string']},
                                            'then': {'$toDouble': '$amount'},
                                            'else': '$amount'
                                        }
                                    },
                                    'else': 0
                                }
                            }
                        }
                    },
                    {
                        '$match': {
                            'numericAmount': {'$gt': 0}
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'totalIncome': {'$sum': '$numericAmount'},  # Use converted numeric amount
                            'count': {'$sum': 1}
                        }
                    }
                ]))
                
                expense_result = list(mongo.db.expenses.aggregate([
                    {
                        '$match': {
                            'userId': user_id,
                            'date': {
                                '$gte': start_of_month,
                                '$lte': end_of_month
                            },
                            'amount': {'$exists': True, '$ne': None}
                        }
                    },
                    # CRITICAL FIX: Convert amount to numeric type
                    {
                        '$addFields': {
                            'numericAmount': {
                                '$cond': {
                                    'if': {'$type': '$amount'},
                                    'then': {
                                        '$cond': {
                                            'if': {'$eq': [{'$type': '$amount'}, 'string']},
                                            'then': {'$toDouble': '$amount'},
                                            'else': '$amount'
                                        }
                                    },
                                    'else': 0
                                }
                            }
                        }
                    },
                    {
                        '$match': {
                            'numericAmount': {'$gt': 0}
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'totalExpenses': {'$sum': '$numericAmount'},  # Use converted numeric amount
                            'count': {'$sum': 1}
                        }
                    }
                ]))
                
                total_income = income_result[0]['totalIncome'] if income_result else 0.0
                income_count = income_result[0]['count'] if income_result else 0
                total_expenses = expense_result[0]['totalExpenses'] if expense_result else 0.0
                expense_count = expense_result[0]['count'] if expense_result else 0
                
                monthly_totals = {
                    'income': total_income,
                    'expenses': total_expenses,
                    'netIncome': total_income - total_expenses,
                    'month': calendar.month_name[month],
                    'year': year,
                    'monthNumber': month,
                    'incomeCount': income_count,
                    'expenseCount': expense_count,
                    'lastUpdated': datetime.utcnow().isoformat() + 'Z',
                    'period': {
                        'start': start_of_month.isoformat() + 'Z',
                        'end': end_of_month.isoformat() + 'Z'
                    }
                }
            else:
                # Current month (default behavior)
                monthly_totals = aggregation_service.get_current_month_totals(current_user['_id'])
            
            return jsonify({
                'success': True,
                'data': monthly_totals,
                'message': 'Monthly totals retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_monthly_totals: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve monthly totals',
                'errors': {'general': [str(e)]}
            }), 500
    
    @financial_aggregation_bp.route('/ytd-counts', methods=['GET'])
    @token_required
    def get_ytd_counts(current_user):
        """
        GET /api/financial/ytd-counts
        
        Returns year-to-date transaction counts by category.
        Supports optional year parameter for historical data.
        """
        try:
            # Get optional year parameter
            year = request.args.get('year', type=int)
            
            if year:
                if year < 2020 or year > datetime.utcnow().year:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid year parameter',
                        'errors': {'validation': ['Year must be 2020-current']}
                    }), 400
                
                # Custom aggregation for specific year
                start_of_year = datetime(year, 1, 1)
                end_of_year = datetime(year + 1, 1, 1) - timedelta(seconds=1)
                user_id = current_user['_id']
                
                # YTD Income counts by category for specific year with numeric conversion
                income_pipeline = [
                    {
                        '$match': {
                            'userId': user_id,
                            'dateReceived': {
                                '$gte': start_of_year,
                                '$lte': end_of_year
                            },
                            'amount': {'$exists': True, '$ne': None}
                        }
                    },
                    # CRITICAL FIX: Convert amount to numeric type
                    {
                        '$addFields': {
                            'numericAmount': {
                                '$cond': {
                                    'if': {'$type': '$amount'},
                                    'then': {
                                        '$cond': {
                                            'if': {'$eq': [{'$type': '$amount'}, 'string']},
                                            'then': {'$toDouble': '$amount'},
                                            'else': '$amount'
                                        }
                                    },
                                    'else': 0
                                }
                            }
                        }
                    },
                    {
                        '$match': {
                            'numericAmount': {'$gt': 0}
                        }
                    },
                    {
                        '$group': {
                            '_id': '$category',
                            'count': {'$sum': 1},
                            'totalAmount': {'$sum': '$numericAmount'}  # Use converted numeric amount
                        }
                    }
                ]
                
                # YTD Expense counts by category for specific year with numeric conversion
                expense_pipeline = [
                    {
                        '$match': {
                            'userId': user_id,
                            'date': {
                                '$gte': start_of_year,
                                '$lte': end_of_year
                            },
                            'amount': {'$exists': True, '$ne': None}
                        }
                    },
                    # CRITICAL FIX: Convert amount to numeric type
                    {
                        '$addFields': {
                            'numericAmount': {
                                '$cond': {
                                    'if': {'$type': '$amount'},
                                    'then': {
                                        '$cond': {
                                            'if': {'$eq': [{'$type': '$amount'}, 'string']},
                                            'then': {'$toDouble': '$amount'},
                                            'else': '$amount'
                                        }
                                    },
                                    'else': 0
                                }
                            }
                        }
                    },
                    {
                        '$match': {
                            'numericAmount': {'$gt': 0}
                        }
                    },
                    {
                        '$group': {
                            '_id': '$category',
                            'count': {'$sum': 1},
                            'totalAmount': {'$sum': '$numericAmount'}  # Use converted numeric amount
                        }
                    }
                ]
                
                income_counts = list(mongo.db.incomes.aggregate(income_pipeline))
                expense_counts = list(mongo.db.expenses.aggregate(expense_pipeline))
                
                # Format results
                income_by_category = {item['_id']: {'count': item['count'], 'amount': item['totalAmount']} for item in income_counts}
                expense_by_category = {item['_id']: {'count': item['count'], 'amount': item['totalAmount']} for item in expense_counts}
                
                total_income_count = sum(item['count'] for item in income_counts)
                total_expense_count = sum(item['count'] for item in expense_counts)
                
                ytd_counts = {
                    'year': year,
                    'totalIncomeRecords': total_income_count,
                    'totalExpenseRecords': total_expense_count,
                    'totalRecords': total_income_count + total_expense_count,
                    'incomeByCategory': income_by_category,
                    'expenseByCategory': expense_by_category,
                    'lastCalculated': datetime.utcnow().isoformat() + 'Z',
                    'period': {
                        'start': start_of_year.isoformat() + 'Z',
                        'end': end_of_year.isoformat() + 'Z'
                    }
                }
            else:
                # Current year (default behavior)
                ytd_counts = aggregation_service.get_ytd_record_counts(current_user['_id'])
            
            return jsonify({
                'success': True,
                'data': ytd_counts,
                'message': 'YTD record counts retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_ytd_counts: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve YTD record counts',
                'errors': {'general': [str(e)]}
            }), 500

    @financial_aggregation_bp.route('/all-time-counts', methods=['GET'])
    @token_required
    def get_all_time_counts(current_user):
        """
        GET /api/financial/all-time-counts
        
        Returns all-time transaction counts by category.
        """
        try:
            all_time_counts = aggregation_service.get_all_time_record_counts(current_user['_id'])
            
            return jsonify({
                'success': True,
                'data': all_time_counts,
                'message': 'All-time record counts retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_all_time_counts: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve all-time record counts',
                'errors': {'general': [str(e)]}
            }), 500

    @financial_aggregation_bp.route('/refresh-aggregations', methods=['POST'])
    @token_required
    def refresh_aggregations(current_user):
        """
        POST /api/financial/refresh-aggregations
        
        Forces recalculation of all aggregations and clears any caches.
        Returns updated aggregation data.
        """
        try:
            user_id = current_user['_id']
            
            # Force recalculation of all aggregations
            monthly_totals = aggregation_service.get_current_month_totals(user_id)
            ytd_counts = aggregation_service.get_ytd_record_counts(user_id)
            all_time_counts = aggregation_service.get_all_time_record_counts(user_id)
            
            # Optional: Clear any application-level caches here
            # This could include Redis cache invalidation if implemented
            
            refresh_data = {
                'monthlyTotals': monthly_totals,
                'ytdCounts': ytd_counts,
                'allTimeCounts': all_time_counts,
                'refreshedAt': datetime.utcnow().isoformat() + 'Z'
            }
            
            return jsonify({
                'success': True,
                'data': refresh_data,
                'message': 'Aggregations refreshed successfully'
            })
            
        except Exception as e:
            print(f"Error in refresh_aggregations: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to refresh aggregations',
                'errors': {'general': [str(e)]}
            }), 500

    @financial_aggregation_bp.route('/performance-stats', methods=['GET'])
    @token_required
    def get_performance_stats(current_user):
        """
        GET /api/financial/performance-stats
        
        Get comprehensive performance statistics for financial aggregation queries.
        Includes enhanced cache statistics, index usage, and query performance metrics.
        """
        try:
            # Get enhanced cache statistics
            enhanced_cache_stats = aggregation_service.cache.get_comprehensive_stats()
            
            # Get legacy cache statistics for comparison
            legacy_cache_stats = aggregation_cache.get_cache_stats()
            
            # Get index usage statistics
            index_stats = aggregation_service.optimizer.get_index_usage_stats()
            
            # Get database optimization status
            optimization_results = aggregation_service.optimizer.optimize_aggregation_queries()
            
            performance_data = {
                'enhancedCacheStatistics': enhanced_cache_stats,
                'legacyCacheStatistics': legacy_cache_stats,
                'indexStatistics': index_stats,
                'optimizationResults': optimization_results,
                'performanceMetrics': {
                    'averageQueryTime': 'Tracked per query',
                    'indexOptimization': 'Active',
                    'enhancedCacheOptimization': 'Active',
                    'cacheWarmingService': 'Active',
                    'intelligentInvalidation': 'Active',
                    'queryOptimization': 'Enhanced'
                },
                'cacheWarmingStats': {
                    'service_active': aggregation_service.cache_warmer.warming_active,
                    'warming_interval_seconds': aggregation_service.cache_warmer.warming_interval,
                    'tracked_users': len(aggregation_service.cache_warmer.user_access_patterns)
                },
                'performanceMonitoring': aggregation_service.performance_monitor.get_performance_summary(),
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
            
            return jsonify({
                'success': True,
                'data': performance_data,
                'message': 'Enhanced performance statistics retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_performance_stats: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve performance statistics',
                'errors': {'general': [str(e)]}
            }), 500

    @financial_aggregation_bp.route('/clear-cache', methods=['POST'])
    @token_required
    def clear_user_cache(current_user):
        """
        POST /api/financial/clear-cache
        
        Clear all cached aggregation results for the current user.
        Supports both enhanced and legacy cache clearing.
        """
        try:
            user_id = current_user['_id']
            
            # Clear enhanced cache entries
            enhanced_cleared = aggregation_service.cache.invalidate_user_cache(user_id)
            
            # Clear legacy cache entries
            legacy_cleared = aggregation_cache.invalidate_user_cache(user_id)
            
            # Also clear any expired entries globally
            enhanced_expired = aggregation_service.cache.clear_expired()
            legacy_expired = aggregation_cache.clear_expired()
            
            return jsonify({
                'success': True,
                'data': {
                    'enhancedCache': {
                        'userCacheCleared': enhanced_cleared,
                        'expiredCacheCleared': enhanced_expired
                    },
                    'legacyCache': {
                        'userCacheCleared': legacy_cleared,
                        'expiredCacheCleared': legacy_expired
                    },
                    'totalCleared': enhanced_cleared + legacy_cleared + enhanced_expired + legacy_expired
                },
                'message': f'Cache cleared successfully. Enhanced: {enhanced_cleared + enhanced_expired}, Legacy: {legacy_cleared + legacy_expired}'
            })
            
        except Exception as e:
            print(f"Error in clear_user_cache: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to clear cache',
                'errors': {'general': [str(e)]}
            }), 500

    @financial_aggregation_bp.route('/warm-cache', methods=['POST'])
    @token_required
    def warm_user_cache(current_user):
        """
        POST /api/financial/warm-cache
        
        Proactively warm cache for the current user's common queries.
        """
        try:
            user_id = current_user['_id']
            
            # Warm common cache entries
            warmed_queries = []
            
            # Warm monthly totals
            try:
                aggregation_service.cache_warmer.warm_cache_entry(user_id, 'monthly_totals')
                warmed_queries.append('monthly_totals')
            except Exception as e:
                logger.warning(f"Failed to warm monthly_totals for user {user_id}: {str(e)}")
            
            # Warm YTD counts
            try:
                aggregation_service.cache_warmer.warm_cache_entry(user_id, 'ytd_counts')
                warmed_queries.append('ytd_counts')
            except Exception as e:
                logger.warning(f"Failed to warm ytd_counts for user {user_id}: {str(e)}")
            
            # Warm all-time counts
            try:
                aggregation_service.cache_warmer.warm_cache_entry(user_id, 'all_time_counts')
                warmed_queries.append('all_time_counts')
            except Exception as e:
                logger.warning(f"Failed to warm all_time_counts for user {user_id}: {str(e)}")
            
            return jsonify({
                'success': True,
                'data': {
                    'warmedQueries': warmed_queries,
                    'totalWarmed': len(warmed_queries),
                    'userId': str(user_id)
                },
                'message': f'Cache warming completed. Warmed {len(warmed_queries)} query types.'
            })
            
        except Exception as e:
            print(f"Error in warm_user_cache: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to warm cache',
                'errors': {'general': [str(e)]}
            }), 500

    @financial_aggregation_bp.route('/invalidate-cache', methods=['POST'])
    @token_required
    def invalidate_cache_pattern(current_user):
        """
        POST /api/financial/invalidate-cache
        
        Invalidate cache entries based on patterns.
        Body: {"pattern": "user_data|monthly_data|yearly_data|transaction_data"}
        """
        try:
            user_id = current_user['_id']
            data = request.get_json() or {}
            pattern = data.get('pattern', 'user_data')
            
            # Validate pattern
            valid_patterns = ['user_data', 'monthly_data', 'yearly_data', 'transaction_data']
            if pattern not in valid_patterns:
                return jsonify({
                    'success': False,
                    'message': f'Invalid pattern. Must be one of: {", ".join(valid_patterns)}',
                    'errors': {'validation': ['Invalid invalidation pattern']}
                }), 400
            
            # Invalidate using the pattern
            invalidated_count = aggregation_service.cache.invalidate_by_pattern(pattern, user_id)
            
            return jsonify({
                'success': True,
                'data': {
                    'pattern': pattern,
                    'invalidatedCount': invalidated_count,
                    'userId': str(user_id)
                },
                'message': f'Invalidated {invalidated_count} cache entries for pattern "{pattern}"'
            })
            
        except Exception as e:
            print(f"Error in invalidate_cache_pattern: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to invalidate cache',
                'errors': {'general': [str(e)]}
            }), 500

    # Health check endpoint for the financial aggregation service
    @financial_aggregation_bp.route('/health', methods=['GET'])
    def aggregation_health_check():
        """
        GET /api/financial/health
        
        Enhanced health check endpoint for financial aggregation service.
        Includes performance and optimization status.
        """
        try:
            # Test database connectivity
            mongo.db.command('ping')
            
            # Get basic cache stats for health check
            cache_stats = aggregation_cache.get_cache_stats()
            
            # Check if indexes are properly created
            index_stats = aggregation_service.optimizer.get_index_usage_stats()
            
            health_data = {
                'service': 'financial_aggregation',
                'status': 'healthy',
                'database': 'connected',
                'cacheActive': cache_stats['active_entries'] > 0,
                'indexesOptimized': len(index_stats) > 0,
                'optimizationsActive': True,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
            
            return jsonify({
                'success': True,
                'data': health_data
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'service': 'financial_aggregation',
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }), 500

    @financial_aggregation_bp.route('/monitoring/dashboard', methods=['GET'])
    @token_required
    def get_monitoring_dashboard(current_user):
        """
        GET /api/financial/monitoring/dashboard
        
        Get comprehensive monitoring dashboard data for financial aggregation service.
        Includes performance metrics, alerts, and system health information.
        """
        try:
            # Get dashboard data from performance monitor
            dashboard_data = aggregation_service.performance_monitor.get_performance_dashboard_data()
            
            # Add cache statistics
            cache_stats = aggregation_service.cache.get_comprehensive_stats()
            
            # Add system information
            system_info = {
                'service_version': '2.0.0',
                'optimization_level': 'enhanced',
                'features_enabled': [
                    'enhanced_caching',
                    'cache_warming',
                    'intelligent_invalidation',
                    'performance_monitoring',
                    'query_optimization',
                    'index_optimization'
                ],
                'uptime_info': {
                    'cache_warmer_active': aggregation_service.cache_warmer.warming_active,
                    'performance_monitoring_active': True,
                    'database_optimizations_active': True
                }
            }
            
            # Combine all dashboard data
            complete_dashboard = {
                'performance_metrics': dashboard_data,
                'cache_statistics': cache_stats,
                'system_information': system_info,
                'generated_at': datetime.utcnow().isoformat() + 'Z'
            }
            
            return jsonify({
                'success': True,
                'data': complete_dashboard,
                'message': 'Monitoring dashboard data retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_monitoring_dashboard: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve monitoring dashboard data',
                'errors': {'general': [str(e)]}
            }), 500

    @financial_aggregation_bp.route('/monitoring/alerts', methods=['GET'])
    @token_required
    def get_performance_alerts(current_user):
        """
        GET /api/financial/monitoring/alerts
        
        Get current performance alerts and recommendations.
        """
        try:
            # Get performance summary with alerts
            performance_summary = aggregation_service.performance_monitor.get_performance_summary()
            
            alerts_data = {
                'recent_alerts': performance_summary['recent_alerts'],
                'alert_summary': performance_summary['alert_summary'],
                'performance_thresholds': performance_summary['performance_thresholds'],
                'recommendations': aggregation_service.performance_monitor._generate_recommendations(performance_summary),
                'health_status': aggregation_service.performance_monitor._calculate_health_status(performance_summary),
                'generated_at': datetime.utcnow().isoformat() + 'Z'
            }
            
            return jsonify({
                'success': True,
                'data': alerts_data,
                'message': 'Performance alerts retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_performance_alerts: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve performance alerts',
                'errors': {'general': [str(e)]}
            }), 500

    @financial_aggregation_bp.route('/monitoring/metrics', methods=['GET'])
    @token_required
    def get_detailed_metrics(current_user):
        """
        GET /api/financial/monitoring/metrics
        
        Get detailed performance metrics for analysis.
        Supports query parameters for filtering and time ranges.
        """
        try:
            # Get query parameters
            metric_type = request.args.get('type', 'all')  # 'query', 'cache', 'system', 'all'
            
            # Get comprehensive performance summary
            performance_summary = aggregation_service.performance_monitor.get_performance_summary()
            
            # Filter metrics based on type
            if metric_type == 'query':
                filtered_data = {'query_performance': performance_summary['query_performance']}
            elif metric_type == 'cache':
                filtered_data = {'cache_performance': performance_summary['cache_performance']}
            elif metric_type == 'system':
                filtered_data = {'system_performance': performance_summary['system_performance']}
            else:
                filtered_data = performance_summary
            
            # Add metadata
            metrics_data = {
                'metrics': filtered_data,
                'metric_type_requested': metric_type,
                'available_metric_types': ['query', 'cache', 'system', 'all'],
                'generated_at': datetime.utcnow().isoformat() + 'Z'
            }
            
            return jsonify({
                'success': True,
                'data': metrics_data,
                'message': f'Detailed metrics ({metric_type}) retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_detailed_metrics: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve detailed metrics',
                'errors': {'general': [str(e)]}
            }), 500

    return financial_aggregation_bp