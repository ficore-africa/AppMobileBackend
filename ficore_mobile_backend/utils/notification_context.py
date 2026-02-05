"""
Context-Aware Notification Helper
Generates notification messages based on user context and entry type

Phase 4: Smart Notifications System
"""

# Tax-deductible expense categories (high priority)
# These match the exact category names used in the app
TAX_DEDUCTIBLE_CATEGORIES = {
    'Rent',  # Housing rent (Tax Relief: 20%, max ₦500,000)
    'Pension',  # Pension contributions (Fully tax-deductible)
    'Life Insurance',  # Life insurance premiums (Fully tax-deductible)
    'NHIS',  # National Health Insurance (Fully tax-deductible)
    'HMO',  # Health Maintenance Organization (Fully tax-deductible)
    'Rent & Utilities',  # Business rent and utilities
    'Statutory & Legal Contributions',  # Pension, NHIS, Life Insurance for business
    'Healthcare',  # Medical expenses
}

def get_notification_context(user, entry_data, entry_type='income'):
    """
    Determine notification message and priority based on context
    
    Args:
        user: User document from MongoDB
        entry_data: Income/expense document
        entry_type: 'income' or 'expense'
    
    Returns:
        dict: {
            'title': str,
            'body': str,
            'priority': 'high' | 'medium' | 'low',
            'category': str
        }
    """
    # Get user's tax profile (with safe defaults)
    tax_profile = user.get('taxProfile', {})
    business_structure = tax_profile.get('businessStructure', 'personal_income')
    
    # Get entry's tagging status
    entry_tag = entry_data.get('entryType')  # 'business', 'personal', or None
    
    # Get entry title with fallback (never None or empty)
    if entry_type == 'income':
        entry_title = entry_data.get('source') or 'Income'
    else:
        entry_title = entry_data.get('title') or entry_data.get('description') or 'Expense'
    
    # Get entry amount with type safety (always valid number)
    entry_amount = float(entry_data.get('amount', 0) or 0)
    
    # Get entry category with safe default
    entry_category = entry_data.get('category', '')
    
    # Determine priority and message based on context
    
    # CASE 1: Untagged entries (need tagging first)
    if entry_tag is None:
        if business_structure == 'llc':
            return {
                'title': "Tag this entry for tax compliance",
                'body': f"Tag {entry_title} (₦{entry_amount:,.2f}) as Business or Personal for accurate tax records",
                'priority': 'high',
                'category': 'missing_receipt'
            }
        else:  # personal_income
            return {
                'title': "Tag this entry",
                'body': f"Tag {entry_title} (₦{entry_amount:,.2f}) as Business or Personal to track your income properly",
                'priority': 'normal',  # Changed from 'medium' to match frontend enum
                'category': 'missing_receipt'
            }
    
    # CASE 2: Business entries (high priority for tax compliance)
    if entry_tag == 'business':
        if entry_type == 'expense' and entry_category in TAX_DEDUCTIBLE_CATEGORIES:
            # Tax-deductible business expense - HIGHEST priority
            return {
                'title': "Important: Attach receipt for tax deduction",
                'body': f"Attach receipt for {entry_title} (₦{entry_amount:,.2f}) - This is tax-deductible and reduces your tax bill",
                'priority': 'high',
                'category': 'missing_receipt'
            }
        else:
            # Regular business entry
            return {
                'title': "Attach receipt for business records",
                'body': f"Attach receipt for {entry_title} (₦{entry_amount:,.2f}) to support your business tax records",
                'priority': 'high',
                'category': 'missing_receipt'
            }
    
    # CASE 3: Personal entries (lower priority)
    if entry_tag == 'personal':
        return {
            'title': "Optional: Attach receipt",
            'body': f"Attach receipt for {entry_title} (₦{entry_amount:,.2f}) for your personal records (not tax-related)",
            'priority': 'low',
            'category': 'missing_receipt'
        }
    
    # FALLBACK: Generic message (shouldn't reach here)
    return {
        'title': "Don't forget to attach documents",
        'body': f"Attach receipt for {entry_title} (₦{entry_amount:,.2f}) to support your records",
        'priority': 'normal',
        'category': 'missing_receipt'
    }
