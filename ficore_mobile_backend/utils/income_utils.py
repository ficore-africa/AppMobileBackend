# -*- coding: utf-8 -*-
"""
Income utility functions for auto-generating titles and descriptions
"""

def generate_income_title(category, amount=None):
    """Generate smart title from income category and amount"""
    title_mapping = {
        # Employment Income
        'salary': 'Salary Payment',
        'freelance': 'Freelance Payment',
        'bonus': 'Bonus Payment',
        'commission': 'Commission Payment',
        
        # Business Income
        'business': 'Business Revenue',
        'sales': 'Sales Revenue',
        'service': 'Service Revenue',
        'consulting': 'Consulting Fee',
        
        # Investment Income
        'investment': 'Investment Return',
        'dividend': 'Dividend Payment',
        'interest': 'Interest Payment',
        'capital_gains': 'Capital Gains',
        
        # Property Income
        'rental': 'Rental Income',
        'property': 'Property Income',
        
        # Retirement Income
        'pension': 'Pension Payment',
        'retirement': 'Retirement Income',
        
        # Other Income
        'gift': 'Gift Received',
        'refund': 'Refund Received',
        'cashback': 'Cashback Received',
        'rebate': 'Rebate Received',
        'grant': 'Grant Received',
        'scholarship': 'Scholarship',
        'award': 'Award Money',
        'lottery': 'Lottery Winnings',
        'insurance': 'Insurance Payout',
        
        # Default
        'other': 'Income',
        'Other': 'Income',
    }
    
    base_title = title_mapping.get(category, f"{category} Income")
    
    # Add amount context for high-value income (100,000 Naira and above)
    if amount and amount >= 100000:
        return f"{base_title} (N{amount:,.0f})"
    
    return base_title

def generate_income_description(category, amount, user_description=None):
    """Generate smart description from category, amount, and optional user input"""
    if user_description and user_description.strip() and user_description.strip() != category:
        # User provided meaningful description, use it
        return user_description.strip()
    
    description_templates = {
        # Employment Income
        'salary': 'Monthly salary payment',
        'freelance': 'Freelance work payment',
        'bonus': 'Performance bonus payment',
        'commission': 'Sales commission payment',
        
        # Business Income
        'business': 'Business revenue from operations',
        'sales': 'Revenue from sales',
        'service': 'Service fee payment',
        'consulting': 'Consulting service fee',
        
        # Investment Income
        'investment': 'Return on investment',
        'dividend': 'Dividend payment from shares',
        'interest': 'Interest payment from savings/investment',
        'capital_gains': 'Capital gains from investment',
        
        # Property Income
        'rental': 'Rental income from property',
        'property': 'Property-related income',
        
        # Retirement Income
        'pension': 'Pension payment',
        'retirement': 'Retirement income',
        
        # Other Income
        'gift': 'Gift money received',
        'refund': 'Refund payment',
        'cashback': 'Cashback reward',
        'rebate': 'Rebate payment',
        'grant': 'Grant funding received',
        'scholarship': 'Scholarship payment',
        'award': 'Award money received',
        'lottery': 'Lottery winnings',
        'insurance': 'Insurance claim payout',
        
        # Default
        'other': 'General income',
        'Other': 'General income',
    }
    
    base_description = description_templates.get(category, f"{category} income")
    
    # Add amount context
    return f"N{amount:,.2f} received from {base_description.lower()}"

def auto_populate_income_fields(income_data):
    """Auto-populate title and description if missing"""
    category = income_data.get('category', 'other')
    amount = income_data.get('amount', 0)
    user_description = income_data.get('description', '')
    
    # Auto-generate title if missing (income uses 'source' field as title)
    if not income_data.get('title') and not income_data.get('source'):
        income_data['source'] = generate_income_title(category, amount)
    elif not income_data.get('title') and income_data.get('source') == category:
        # If source is just the category name, make it smarter
        income_data['source'] = generate_income_title(category, amount)
    
    # Auto-generate description if missing or same as category
    if not user_description or user_description == category:
        income_data['description'] = generate_income_description(category, amount, user_description)
    
    return income_data

def format_income_for_activity(income_data):
    """Format income data for recent activity creation"""
    title = income_data.get('title', income_data.get('source', 'Income'))
    amount = income_data.get('amount', 0)
    description = income_data.get('description', '')
    
    # Create activity description
    activity_description = f"Received N{amount:,.2f} from {description.lower()}"
    
    return {
        'title': title,
        'description': activity_description,
        'amount': amount,
        'type': 'income'
    }

def get_income_category_suggestions(amount):
    """Get smart category suggestions based on amount patterns"""
    suggestions = []
    
    if amount >= 500000:  # High amounts
        suggestions = ['salary', 'business', 'investment', 'property', 'bonus']
    elif amount >= 100000:  # Medium-high amounts
        suggestions = ['salary', 'freelance', 'business', 'rental', 'commission']
    elif amount >= 10000:  # Medium amounts
        suggestions = ['freelance', 'service', 'gift', 'refund', 'other']
    else:  # Small amounts
        suggestions = ['gift', 'refund', 'cashback', 'interest', 'other']
    
    return suggestions