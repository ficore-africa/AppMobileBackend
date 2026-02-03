# -*- coding: utf-8 -*-
"""
Expense utility functions for auto-generating titles and descriptions
"""

def generate_expense_title(category, amount=None):
    """Generate smart title from category and amount"""
    title_mapping = {
        'Rent': 'Rent Payment',
        'Utilities': 'Utility Bill',
        'Bills & Utilities': 'Utility Payment',
        'Electricity': 'Electricity Bill',
        'Water': 'Water Bill',
        'Internet': 'Internet Bill',
        'Transportation': 'Transportation',
        'Gas & Fuel': 'Fuel Purchase',
        'Vehicle Maintenance': 'Vehicle Service',
        'Parking': 'Parking Fee',
        'Public Transport': 'Transport Fare',
        'Food & Dining': 'Food Purchase',
        'Groceries': 'Grocery Shopping',
        'Restaurant': 'Restaurant Bill',
        'Fast Food': 'Fast Food',
        'Business': 'Business Expense',
        'Business Expenses': 'Business Expense',
        'Office & Admin': 'Office Expense',
        'Marketing & Sales Expenses': 'Marketing Expense',
        'Healthcare': 'Healthcare',
        'Personal Care': 'Personal Care',
        'Pharmacy': 'Pharmacy Purchase',
        'Entertainment': 'Entertainment',
        'Shopping': 'Shopping',
        'Travel': 'Travel Expense',
        'Education': 'Education',
        'Other': 'Expense',
        'other': 'Expense',
    }
    
    base_title = title_mapping.get(category, f"{category} Expense")
    
    # Add amount context for high-value expenses (50,000 Naira and above)
    if amount and amount >= 50000:
        return f"{base_title} (N{amount:,.0f})"
    
    return base_title

def generate_expense_description(category, amount, user_description=None):
    """Generate smart description from category, amount, and optional user input"""
    if user_description and user_description.strip() and user_description.strip() != category:
        # User provided meaningful description, use it
        return user_description.strip()
    
    description_templates = {
        'Rent': 'Monthly rent payment',
        'Utilities': 'Utility bill payment',
        'Bills & Utilities': 'Utility bill payment',
        'Electricity': 'Electricity bill payment',
        'Water': 'Water bill payment',
        'Internet': 'Internet service payment',
        'Transportation': 'Transportation expense',
        'Gas & Fuel': 'Fuel purchase',
        'Vehicle Maintenance': 'Vehicle maintenance and service',
        'Parking': 'Parking fee payment',
        'Public Transport': 'Public transportation fare',
        'Food & Dining': 'Food and dining expense',
        'Groceries': 'Grocery shopping',
        'Restaurant': 'Restaurant dining',
        'Fast Food': 'Fast food purchase',
        'Business': 'Business-related expense',
        'Business Expenses': 'Business operational expense',
        'Office & Admin': 'Office and administrative expense',
        'Marketing & Sales Expenses': 'Marketing and sales expense',
        'Healthcare': 'Healthcare expense',
        'Personal Care': 'Personal care expense',
        'Pharmacy': 'Pharmacy purchase',
        'Entertainment': 'Entertainment expense',
        'Shopping': 'Shopping expense',
        'Travel': 'Travel-related expense',
        'Education': 'Educational expense',
        'Other': 'General expense',
        'other': 'General expense',
    }
    
    base_description = description_templates.get(category, f"{category} expense")
    
    # Add amount context
    return f"N{amount:,.2f} spent on {base_description.lower()}"

def auto_populate_expense_fields(expense_data):
    """
    Auto-populate title, description, and date if missing
    
    CRITICAL: Always ensure 'date' field exists to prevent KeyError in expense summary
    """
    from datetime import datetime
    
    category = expense_data.get('category', 'Other')
    amount = expense_data.get('amount', 0)
    user_description = expense_data.get('description', '')
    
    # CRITICAL: Ensure date field always exists
    if 'date' not in expense_data or expense_data.get('date') is None:
        # Use createdAt if available, otherwise current time
        expense_data['date'] = expense_data.get('createdAt', datetime.utcnow())
    
    # Auto-generate title if missing
    if not expense_data.get('title'):
        expense_data['title'] = generate_expense_title(category, amount)
    
    # Auto-generate description if missing or same as category
    if not user_description or user_description == category:
        expense_data['description'] = generate_expense_description(category, amount, user_description)
    
    return expense_data

def format_expense_for_activity(expense_data):
    """Format expense data for recent activity creation"""
    title = expense_data.get('title', 'Expense')
    amount = expense_data.get('amount', 0)
    description = expense_data.get('description', '')
    
    # Create activity description
    activity_description = f"Spent N{amount:,.2f} on {description.lower()}"
    
    return {
        'title': title,
        'description': activity_description,
        'amount': amount,
        'type': 'expense'
    }