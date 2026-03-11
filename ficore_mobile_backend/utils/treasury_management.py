"""
Treasury Management

Manages treasury operations and financial reporting.
"""

from decimal_helpers import safe_float, safe_sum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class TreasuryManager:
    """
    Manages treasury operations and financial calculations
    """
    
    def __init__(self, mongo):
        self.mongo = mongo
    
    def get_financial_summary(self, start_date=None, end_date=None):
        """
        Get comprehensive financial summary
        
        Args:
            start_date: Start date for analysis
            end_date: End date for analysis
            
        Returns:
            dict: Financial summary data
        """
        try:
            # Build date filter
            date_filter = {}
            if start_date:
                date_filter['$gte'] = start_date
            if end_date:
                date_filter['$lte'] = end_date
            
            query = {}
            if date_filter:
                query['createdAt'] = date_filter
            
            # Get income data
            incomes = list(self.mongo.db.incomes.find({
                **query,
                'status': 'active',
                'isDeleted': False
            }))
            
            # Get expense data
            expenses = list(self.mongo.db.expenses.find({
                **query,
                'status': 'active',
                'isDeleted': False
            }))
            
            # Calculate totals
            total_income = safe_sum([safe_float(inc.get('amount', 0)) for inc in incomes])
            total_expenses = safe_sum([safe_float(exp.get('amount', 0)) for exp in expenses])
            net_profit = total_income - total_expenses
            
            # Get VAS transaction data
            vas_transactions = list(self.mongo.db.vas_transactions.find({
                **query,
                'status': 'SUCCESS'
            }))
            
            vas_revenue = safe_sum([safe_float(txn.get('amount', 0)) for txn in vas_transactions])
            
            return {
                'total_income': total_income,
                'total_expenses': total_expenses,
                'net_profit': net_profit,
                'vas_revenue': vas_revenue,
                'income_count': len(incomes),
                'expense_count': len(expenses),
                'vas_transaction_count': len(vas_transactions),
                'analysis_period': {
                    'start_date': start_date,
                    'end_date': end_date
                },
                'generated_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error getting financial summary: {str(e)}")
            return {'error': str(e)}
    
    def get_cash_flow_analysis(self, months_back=12):
        """
        Get cash flow analysis for specified months
        
        Args:
            months_back: Number of months to analyze
            
        Returns:
            dict: Cash flow analysis data
        """
        try:
            from datetime import datetime, timedelta
            
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=months_back * 30)
            
            # Monthly breakdown
            monthly_data = []
            
            for month_offset in range(months_back):
                month_start = end_date - timedelta(days=(month_offset + 1) * 30)
                month_end = end_date - timedelta(days=month_offset * 30)
                
                month_summary = self.get_financial_summary(month_start, month_end)
                month_summary['month'] = month_start.strftime('%Y-%m')
                monthly_data.append(month_summary)
            
            return {
                'monthly_breakdown': monthly_data,
                'analysis_period': f"{start_date.strftime('%Y-%m')} to {end_date.strftime('%Y-%m')}",
                'generated_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error getting cash flow analysis: {str(e)}")
            return {'error': str(e)}
    
    def get_liability_summary(self):
        """
        Get summary of outstanding liabilities
        
        Returns:
            dict: Liability summary data
        """
        try:
            # Get FC Credits liabilities
            fc_liabilities = list(self.mongo.db.incomes.find({
                'sourceType': 'fc_liability_accrual',
                'status': 'active',
                'isDeleted': False
            }))
            
            # Get subscription liabilities
            subscription_liabilities = list(self.mongo.db.incomes.find({
                'sourceType': 'subscription_liability_accrual',
                'status': 'active',
                'isDeleted': False
            }))
            
            # Get fee waiver liabilities
            fee_waiver_liabilities = list(self.mongo.db.incomes.find({
                'sourceType': 'fee_waiver_liability_accrual',
                'status': 'active',
                'isDeleted': False
            }))
            
            # Calculate totals
            fc_total = safe_sum([safe_float(lib.get('amount', 0)) for lib in fc_liabilities])
            subscription_total = safe_sum([safe_float(lib.get('amount', 0)) for lib in subscription_liabilities])
            fee_waiver_total = safe_sum([safe_float(lib.get('amount', 0)) for lib in fee_waiver_liabilities])
            
            total_liabilities = fc_total + subscription_total + fee_waiver_total
            
            return {
                'fc_credits_liability': fc_total,
                'subscription_liability': subscription_total,
                'fee_waiver_liability': fee_waiver_total,
                'total_liabilities': total_liabilities,
                'liability_breakdown': {
                    'fc_credits': {
                        'amount': fc_total,
                        'count': len(fc_liabilities)
                    },
                    'subscriptions': {
                        'amount': subscription_total,
                        'count': len(subscription_liabilities)
                    },
                    'fee_waivers': {
                        'amount': fee_waiver_total,
                        'count': len(fee_waiver_liabilities)
                    }
                },
                'generated_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error getting liability summary: {str(e)}")
            return {'error': str(e)}
