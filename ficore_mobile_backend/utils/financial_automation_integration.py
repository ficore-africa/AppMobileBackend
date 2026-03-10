"""
Financial Automation Integration
Ensures all marketing expenses, liabilities, and depreciation are properly integrated
"""

from datetime import datetime, timedelta
from bson import ObjectId
from typing import Dict, Any, List, Optional
from flask import current_app
from .business_bookkeeping import (
    record_fc_marketing_expense,
    record_subscription_marketing_expense,
    record_vas_commission_revenue,
    record_fc_consumption_revenue,
    record_monthly_depreciation,
    accrue_daily_subscription_revenue,
    BUSINESS_USER_ID
)
from .decimal_helpers import safe_float


def ensure_all_fc_credits_have_liabilities(mongo) -> Dict[str, Any]:
    """
    Ensure all FC Credits issued have corresponding liability entries
    This fixes any missing liabilities from past FC Credit awards
    """
    try:
        # Get all FC Credit transactions that should have liabilities
        fc_transactions = list(mongo.db.credit_transactions.find({
            'status': 'SUCCESS',
            'nairaAmount': 0,  # Free FC Credits (bonuses)
            'operation': {'$in': [
                'signup_bonus',
                'tax_education_progress', 
                'exploration_bonus',
                'streak_milestone',
                'engagement_reward',
                'admin_award'
            ]}
        }))
        
        created_liabilities = 0
        total_liability_value = 0
        
        for transaction in fc_transactions:
            user_id = transaction['userId']
            fc_amount = transaction.get('fcAmount', 0)
            operation = transaction.get('operation', 'unknown')
            
            # Check if liability already exists
            existing_liability = mongo.db.incomes.find_one({
                'userId': BUSINESS_USER_ID,
                'sourceType': 'fc_liability_accrual',
                'metadata.recipientUserId': str(user_id),
                'metadata.operation': operation,
                'metadata.fcAmount': fc_amount
            })
            
            if not existing_liability and fc_amount > 0:
                # Create missing liability
                result = record_fc_marketing_expense(
                    mongo=mongo,
                    user_id=user_id,
                    fc_amount=fc_amount,
                    operation=operation,
                    description=f"Retroactive liability for {operation}"
                )
                
                created_liabilities += 1
                total_liability_value += result['amount']
        
        return {
            'success': True,
            'created_liabilities': created_liabilities,
            'total_liability_value': total_liability_value,
            'message': f'Created {created_liabilities} missing liability entries worth ₦{safe_float(total_liability_value):,.2f}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to ensure FC Credit liabilities'
        }


def ensure_all_subscriptions_have_liabilities(mongo) -> Dict[str, Any]:
    """
    Ensure all admin-granted subscriptions have corresponding liability entries
    """
    try:
        # Get all admin-granted subscriptions (source != 'paystack')
        admin_subs = list(mongo.db.subscriptions.find({
            'status': 'active',
            'isDeleted': False,
            'source': {'$ne': 'paystack'}  # Admin-granted subscriptions
        }))
        
        created_liabilities = 0
        total_liability_value = 0
        
        for subscription in admin_subs:
            user_id = subscription['userId']
            amount = subscription.get('amount', 0)
            plan_type = subscription.get('planType', subscription.get('plan', 'Unknown'))
            
            # Check if liability already exists
            existing_liability = mongo.db.incomes.find_one({
                'userId': BUSINESS_USER_ID,
                'sourceType': 'subscription_liability_accrual',
                'metadata.subscriptionId': str(subscription['_id'])
            })
            
            if not existing_liability and amount > 0:
                # Create missing liability
                result = record_subscription_marketing_expense(
                    mongo=mongo,
                    user_id=user_id,
                    subscription_id=subscription['_id'],
                    amount=amount,
                    plan_type=plan_type,
                    granted_by='system_integration',
                    grant_reason='Retroactive liability creation'
                )
                
                created_liabilities += 1
                total_liability_value += result['amount']
        
        return {
            'success': True,
            'created_liabilities': created_liabilities,
            'total_liability_value': total_liability_value,
            'message': f'Created {created_liabilities} missing subscription liability entries worth ₦{safe_float(total_liability_value):,.2f}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to ensure subscription liabilities'
        }


def calculate_total_liabilities(mongo) -> Dict[str, Any]:
    """
    Calculate total outstanding liabilities for balance sheet reporting
    """
    try:
        # FC Credit Liabilities
        fc_liabilities = list(mongo.db.incomes.find({
            'userId': BUSINESS_USER_ID,
            'sourceType': 'fc_liability_accrual',
            'status': 'active',
            'isDeleted': False
        }))
        
        # Subscription Liabilities  
        subscription_liabilities = list(mongo.db.incomes.find({
            'userId': BUSINESS_USER_ID,
            'sourceType': 'subscription_liability_accrual',
            'status': 'active',
            'isDeleted': False
        }))
        
        # Calculate totals
        fc_liability_total = sum(entry.get('amount', 0) for entry in fc_liabilities)
        subscription_liability_total = sum(entry.get('amount', 0) for entry in subscription_liabilities)
        total_liabilities = fc_liability_total + subscription_liability_total
        
        return {
            'success': True,
            'fc_credit_liabilities': {
                'count': len(fc_liabilities),
                'total': fc_liability_total
            },
            'subscription_liabilities': {
                'count': len(subscription_liabilities),
                'total': subscription_liability_total
            },
            'total_liabilities': total_liabilities,
            'message': f'Total outstanding liabilities: ₦{safe_float(total_liabilities):,.2f}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to calculate total liabilities'
        }


def ensure_monthly_depreciation_recorded(mongo) -> Dict[str, Any]:
    """
    Ensure monthly depreciation is recorded for current month
    """
    try:
        # Check if depreciation already recorded this month
        current_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (current_month + timedelta(days=32)).replace(day=1)
        
        existing_depreciation = mongo.db.expenses.find_one({
            'userId': BUSINESS_USER_ID,
            'sourceType': 'depreciation',
            'status': 'active',
            'isDeleted': False,
            'date': {
                '$gte': current_month,
                '$lt': next_month
            }
        })
        
        if existing_depreciation:
            return {
                'success': True,
                'already_recorded': True,
                'depreciation_amount': existing_depreciation.get('amount', 0),
                'message': f'Monthly depreciation already recorded: ₦{safe_float(existing_depreciation.get("amount", 0)):,.2f}'
            }
        
        # Record monthly depreciation
        expense_id = record_monthly_depreciation(mongo)
        
        # Get the created expense
        expense = mongo.db.expenses.find_one({'_id': expense_id})
        depreciation_amount = expense.get('amount', 0) if expense else 0
        
        return {
            'success': True,
            'already_recorded': False,
            'expense_id': str(expense_id),
            'depreciation_amount': depreciation_amount,
            'message': f'Monthly depreciation recorded: ₦{safe_float(depreciation_amount):,.2f}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to ensure monthly depreciation'
        }


def get_balance_sheet_data(mongo) -> Dict[str, Any]:
    """
    Get comprehensive balance sheet data including liabilities and accumulated depreciation
    """
    try:
        # Assets (from assets collection)
        assets = list(mongo.db.assets.find({
            'userId': BUSINESS_USER_ID,
            'status': 'active',
            'isDeleted': False
        }))
        
        # Calculate gross asset value
        gross_assets = sum(asset.get('currentValue', 0) for asset in assets)
        
        # Get accumulated depreciation (stored as negative amounts in incomes collection)
        accumulated_depreciation_entries = list(mongo.db.incomes.find({
            'userId': BUSINESS_USER_ID,
            'sourceType': 'accumulated_depreciation',
            'status': 'active',
            'isDeleted': False
        }))
        
        # Sum accumulated depreciation (these are negative amounts)
        total_accumulated_depreciation = sum(entry.get('amount', 0) for entry in accumulated_depreciation_entries)
        
        # Net assets = Gross assets + Accumulated depreciation (since accumulated depreciation is negative)
        net_assets = gross_assets + total_accumulated_depreciation
        
        # Liabilities (from incomes collection with liability sourceTypes)
        liability_result = calculate_total_liabilities(mongo)
        total_liabilities = liability_result.get('total_liabilities', 0) if liability_result['success'] else 0
        
        # Equity calculation
        # Get total business income and expenses
        business_income = list(mongo.db.incomes.find({
            'userId': BUSINESS_USER_ID,
            'status': 'active',
            'isDeleted': False,
            'sourceType': {'$nin': ['fc_liability_accrual', 'subscription_liability_accrual', 'accumulated_depreciation']}  # Exclude liabilities and accumulated depreciation
        }))
        
        business_expenses = list(mongo.db.expenses.find({
            'userId': BUSINESS_USER_ID,
            'status': 'active',
            'isDeleted': False
        }))
        
        total_income = sum(entry.get('amount', 0) for entry in business_income)
        total_expenses = sum(entry.get('amount', 0) for entry in business_expenses)
        retained_earnings = total_income - total_expenses
        
        # Owner's equity (assuming initial capital of ₦1,200,000 from milestones tracker)
        initial_capital = 1200000.0
        total_equity = initial_capital + retained_earnings
        
        return {
            'success': True,
            'assets': {
                'gross_fixed_assets': gross_assets,
                'accumulated_depreciation': total_accumulated_depreciation,  # This will be negative
                'net_fixed_assets': net_assets,
                'total_assets': net_assets
            },
            'liabilities': {
                'fc_credit_liabilities': liability_result.get('fc_credit_liabilities', {}).get('total', 0) if liability_result['success'] else 0,
                'subscription_liabilities': liability_result.get('subscription_liabilities', {}).get('total', 0) if liability_result['success'] else 0,
                'total_liabilities': total_liabilities
            },
            'equity': {
                'initial_capital': initial_capital,
                'retained_earnings': retained_earnings,
                'total_equity': total_equity
            },
            'balance_check': {
                'assets': net_assets,
                'liabilities_plus_equity': total_liabilities + total_equity,
                'balanced': abs(net_assets - (total_liabilities + total_equity)) < 1.0  # Allow ₦1 rounding difference
            },
            'depreciation_summary': {
                'total_accumulated_depreciation': abs(total_accumulated_depreciation),  # Show as positive for readability
                'depreciation_entries_count': len(accumulated_depreciation_entries)
            }
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to get balance sheet data'
        }


def run_complete_financial_integration(mongo) -> Dict[str, Any]:
    """
    Run complete financial integration to ensure all automation is working
    """
    try:
        results = {}
        
        # 1. Ensure FC Credit liabilities
        print("🔄 Ensuring FC Credit liabilities...")
        results['fc_liabilities'] = ensure_all_fc_credits_have_liabilities(mongo)
        
        # 2. Ensure subscription liabilities
        print("🔄 Ensuring subscription liabilities...")
        results['subscription_liabilities'] = ensure_all_subscriptions_have_liabilities(mongo)
        
        # 3. Ensure monthly depreciation
        print("🔄 Ensuring monthly depreciation...")
        results['depreciation'] = ensure_monthly_depreciation_recorded(mongo)
        
        # 4. Calculate balance sheet
        print("🔄 Calculating balance sheet...")
        results['balance_sheet'] = get_balance_sheet_data(mongo)
        
        # 5. Summary
        total_fixes = 0
        if results['fc_liabilities']['success']:
            total_fixes += results['fc_liabilities'].get('created_liabilities', 0)
        if results['subscription_liabilities']['success']:
            total_fixes += results['subscription_liabilities'].get('created_liabilities', 0)
        
        return {
            'success': True,
            'results': results,
            'summary': {
                'total_fixes_applied': total_fixes,
                'fc_liabilities_created': results['fc_liabilities'].get('created_liabilities', 0),
                'subscription_liabilities_created': results['subscription_liabilities'].get('created_liabilities', 0),
                'depreciation_recorded': not results['depreciation'].get('already_recorded', True),
                'balance_sheet_balanced': results['balance_sheet'].get('balance_check', {}).get('balanced', False)
            },
            'message': f'Financial integration complete. Applied {total_fixes} fixes.'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to run complete financial integration'
        }


def get_liability_breakdown_for_reports(mongo) -> Dict[str, Any]:
    """
    Get detailed liability breakdown for inclusion in financial reports
    """
    try:
        # FC Credit Liabilities with details
        fc_liabilities = list(mongo.db.incomes.find({
            'userId': BUSINESS_USER_ID,
            'sourceType': 'fc_liability_accrual',
            'status': 'active',
            'isDeleted': False
        }))
        
        # Subscription Liabilities with details
        subscription_liabilities = list(mongo.db.incomes.find({
            'userId': BUSINESS_USER_ID,
            'sourceType': 'subscription_liability_accrual',
            'status': 'active',
            'isDeleted': False
        }))
        
        # Group FC liabilities by operation type
        fc_by_operation = {}
        for liability in fc_liabilities:
            operation = liability.get('metadata', {}).get('operation', 'unknown')
            if operation not in fc_by_operation:
                fc_by_operation[operation] = {'count': 0, 'total': 0}
            fc_by_operation[operation]['count'] += 1
            fc_by_operation[operation]['total'] += liability.get('amount', 0)
        
        # Group subscription liabilities by plan type
        sub_by_plan = {}
        for liability in subscription_liabilities:
            plan_type = liability.get('metadata', {}).get('planType', 'unknown')
            if plan_type not in sub_by_plan:
                sub_by_plan[plan_type] = {'count': 0, 'total': 0}
            sub_by_plan[plan_type]['count'] += 1
            sub_by_plan[plan_type]['total'] += liability.get('amount', 0)
        
        return {
            'success': True,
            'fc_credit_liabilities': {
                'total_amount': sum(entry.get('amount', 0) for entry in fc_liabilities),
                'total_count': len(fc_liabilities),
                'by_operation': fc_by_operation,
                'details': [
                    {
                        'id': str(entry['_id']),
                        'amount': entry.get('amount', 0),
                        'operation': entry.get('metadata', {}).get('operation', 'unknown'),
                        'recipient_user_id': entry.get('metadata', {}).get('recipientUserId'),
                        'fc_amount': entry.get('metadata', {}).get('fcAmount', 0),
                        'date': entry.get('date'),
                        'description': entry.get('description', '')
                    }
                    for entry in fc_liabilities
                ]
            },
            'subscription_liabilities': {
                'total_amount': sum(entry.get('amount', 0) for entry in subscription_liabilities),
                'total_count': len(subscription_liabilities),
                'by_plan_type': sub_by_plan,
                'details': [
                    {
                        'id': str(entry['_id']),
                        'amount': entry.get('amount', 0),
                        'plan_type': entry.get('metadata', {}).get('planType', 'unknown'),
                        'recipient_user_id': entry.get('metadata', {}).get('recipientUserId'),
                        'subscription_id': entry.get('metadata', {}).get('subscriptionId'),
                        'date': entry.get('date'),
                        'description': entry.get('description', '')
                    }
                    for entry in subscription_liabilities
                ]
            },
            'total_liabilities': sum(entry.get('amount', 0) for entry in fc_liabilities + subscription_liabilities)
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to get liability breakdown'
        }