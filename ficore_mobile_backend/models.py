from datetime import datetime
from typing import Dict, List, Optional, Any
from bson import ObjectId


class DatabaseSchema:
    """
    Centralized database schema definitions for all collections.
    Provides schema validation, index definitions, and helper methods.
    """
    
    # ==================== USERS COLLECTION ====================
    
    @staticmethod
    def get_user_schema() -> Dict[str, Any]:
        """
        Schema for users collection.
        Stores user authentication, profile, settings, and credit balance.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'email': str,  # Required, unique, lowercase
            'password': str,  # Required, hashed with werkzeug.security
            'firstName': str,  # Required
            'lastName': str,  # Required
            'displayName': str,  # Auto-generated from firstName + lastName
            'phone': Optional[str],  # Optional phone number
            'address': Optional[str],  # Optional address
            'dateOfBirth': Optional[str],  # Optional, ISO date string or DD/MM/YYYY
            'bvn': Optional[str],  # Bank Verification Number (11 digits)
            'nin': Optional[str],  # National Identification Number (11 digits)
            'kycStatus': str,  # 'pending', 'verified', 'rejected', default: 'pending'
            'kycVerifiedAt': Optional[datetime],  # KYC verification timestamp
            'role': str,  # 'personal' or 'admin', default: 'personal'
            'ficoreCreditBalance': float,  # FiCore Credits balance, default: 1000.0
            'isActive': bool,  # Account active status, default: True
            'language': str,  # User's preferred language, default: 'en'
            'currency': str,  # User's preferred currency, default: 'NGN'
            'financialGoals': List[str],  # List of selected financial goal keys
            'createdAt': datetime,  # Account creation timestamp
            'updatedAt': Optional[datetime],  # Last update timestamp
            'lastLogin': Optional[datetime],  # Last login timestamp
            'passwordChangedAt': Optional[datetime],  # Password change timestamp
            'settingsUpdatedAt': Optional[datetime],  # Settings update timestamp
            'goalsUpdatedAt': Optional[datetime],  # Goals update timestamp
            'deletedAt': Optional[datetime],  # Soft delete timestamp
            'resetToken': Optional[str],  # Password reset token
            'resetTokenExpiry': Optional[datetime],  # Reset token expiration
            
            # Profile completion fields for rewards
            'businessName': Optional[str],  # Business name
            'businessType': Optional[str],  # 'Sole Proprietor', 'Partnership', 'LLC', 'NGO', 'Other'
            'businessTypeOther': Optional[str],  # Custom business type if 'Other' selected
            'industry': Optional[str],  # 'Retail', 'Services', 'Manufacturing', etc.
            'physicalAddress': Optional[Dict[str, str]],  # {'street': '', 'city': '', 'state': '', 'postalCode': ''}
            'taxIdentificationNumber': Optional[str],  # Encrypted TIN
            'profilePictureUrl': Optional[str],  # Profile picture URL
            'socialMediaLinks': Optional[List[Dict[str, str]]],  # [{'platform': 'twitter', 'url': '...'}]
            'numberOfEmployees': Optional[int],  # Number of employees (0 for none)
            'profileCompletionPercentage': Optional[float],  # Calculated completion percentage
            
            # Subscription fields (current/active subscription)
            'isSubscribed': bool,  # Subscription status, default: False
            'subscriptionType': Optional[str],  # 'monthly', 'annually', null
            'subscriptionStartDate': Optional[datetime],  # Subscription start date
            'subscriptionEndDate': Optional[datetime],  # Subscription end date
            'subscriptionAutoRenew': bool,  # Auto-renewal setting, default: False
            'paymentMethodDetails': Optional[Dict[str, str]],  # Encrypted payment details
            'trialExpiryDate': Optional[datetime],  # Trial expiry date
            
            # Subscription history and tracking (NEW - for historical tracking)
            'wasPremium': Optional[bool],  # Flag indicating user was previously premium
            'lastPremiumDate': Optional[datetime],  # When user was last premium
            'totalPremiumDays': Optional[int],  # Lifetime total days as premium user
            'premiumExpiryCount': Optional[int],  # Number of times subscription expired
            'subscriptionHistory': Optional[List[Dict[str, Any]]],  # Historical subscription periods
            # subscriptionHistory structure:
            # [{
            #     'planType': str,  # 'monthly', 'annually'
            #     'startDate': datetime,
            #     'endDate': datetime,
            #     'autoRenew': bool,
            #     'status': str,  # 'expired', 'cancelled', 'completed'
            #     'terminatedAt': datetime,
            #     'terminationReason': str,  # 'natural_expiry', 'admin_revoked', 'payment_failed', 'user_cancelled'
            #     'totalDaysActive': int,
            #     'paymentMethod': str
            # }]
            'settings': {  # User preferences and settings
                'notifications': {
                    'push': bool,  # Push notifications enabled
                    'email': bool,  # Email notifications enabled
                    'expenseAlerts': bool,  # Expense alert notifications
                    'incomeAlerts': Optional[bool],  # Income alert notifications
                    'creditAlerts': Optional[bool],  # Credit alert notifications
                    'weeklyReports': Optional[bool],  # Weekly report emails
                    'monthlyReports': Optional[bool],  # Monthly report emails
                },
                'privacy': {
                    'profileVisibility': str,  # 'private' or 'public'
                    'dataSharing': bool,  # Data sharing consent
                },
                'preferences': {
                    'currency': str,  # Preferred currency code
                    'language': str,  # Preferred language code
                    'theme': str,  # 'light' or 'dark'
                    'dateFormat': str,  # Date format preference
                },
                'security': Optional[Dict[str, Any]],  # Security settings
            }
        }
    
    @staticmethod
    def get_user_indexes() -> List[Dict[str, Any]]:
        """Define indexes for users collection."""
        return [
            {'keys': [('email', 1)], 'unique': True, 'name': 'email_unique'},
            {'keys': [('role', 1)], 'name': 'role_index'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
            {'keys': [('isActive', 1)], 'name': 'active_users'},
            {'keys': [('resetToken', 1)], 'sparse': True, 'name': 'reset_token'},
        ]

    # ==================== INCOMES COLLECTION ====================
    
    @staticmethod
    def get_income_schema() -> Dict[str, Any]:
        """
        Schema for incomes collection.
        Stores user income records with sources (simplified - no recurring).
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'amount': float,  # Required, income amount (must be > 0)
            'source': str,  # Required, income source name
            'description': str,  # Optional description
            'category': str,  # Required, income category
            'frequency': str,  # Required: 'one_time', 'daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'yearly'
            'salesType': Optional[str],  # Optional: 'cash' or 'credit' for sales incomes
            'dateReceived': datetime,  # Required, date income was received
            'isRecurring': bool,  # Legacy field - always False now (simplified)
            'nextRecurringDate': Optional[datetime],  # Legacy field - always None now (simplified)
            'metadata': Optional[Dict[str, Any]],  # Additional metadata
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
        }
    
    @staticmethod
    @staticmethod
    def get_income_indexes() -> List[Dict[str, Any]]:
        """Define indexes for incomes collection."""
        return [
            {'keys': [('userId', 1), ('dateReceived', -1)], 'name': 'user_date_desc'},
            {'keys': [('userId', 1), ('category', 1)], 'name': 'user_category'},
            {'keys': [('userId', 1), ('frequency', 1)], 'name': 'user_frequency'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
            # CRITICAL FIX: Add compound index for dashboard aggregations
            {'keys': [('userId', 1), ('amount', 1)], 'name': 'user_amount_agg'},
            # CRITICAL FIX: Add index for immutable ledger queries
            {'keys': [('userId', 1), ('status', 1), ('isDeleted', 1)], 'name': 'user_status_deleted'},
        ]
    
    # ==================== EXPENSES COLLECTION ====================
    
    @staticmethod
    def get_expense_schema() -> Dict[str, Any]:
        """
        Schema for expenses collection.
        Stores user expense records with categories and budget linkage.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'amount': float,  # Required, expense amount (must be > 0)
            'title': Optional[str],  # Expense title
            'description': str,  # Required, expense description
            'category': str,  # Required, expense category
            'date': datetime,  # Required, expense date
            'tags': List[str],  # Optional tags for categorization
            'paymentMethod': str,  # Payment method: 'cash', 'card', 'bank_transfer', etc.
            'location': Optional[str],  # Optional location where expense occurred
            'notes': Optional[str],  # Additional notes
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
        }
    
    @staticmethod
    def get_expense_indexes() -> List[Dict[str, Any]]:
        """Define indexes for expenses collection."""
        return [
            {'keys': [('userId', 1), ('date', -1)], 'name': 'user_date_desc'},
            {'keys': [('userId', 1), ('category', 1)], 'name': 'user_category'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
            # CRITICAL FIX: Add compound index for dashboard aggregations
            {'keys': [('userId', 1), ('amount', 1)], 'name': 'user_amount_agg'},
            # CRITICAL FIX: Add index for immutable ledger queries
            {'keys': [('userId', 1), ('status', 1), ('isDeleted', 1)], 'name': 'user_status_deleted'},
        ]
    
    # ==================== CREDIT_TRANSACTIONS COLLECTION ====================
    
    @staticmethod
    def get_credit_transaction_schema() -> Dict[str, Any]:
        """
        Schema for credit_transactions collection.
        Stores FiCore Credits transaction history for users.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'requestId': Optional[str],  # Optional, reference to credit request ID
            'type': str,  # Required: 'credit' (add), 'debit' (deduct), 'request' (pending)
            'amount': float,  # Required, transaction amount (must be > 0)
            'description': str,  # Required, transaction description
            'status': str,  # Transaction status: 'pending', 'completed', 'approved', 'rejected'
            'operation': Optional[str],  # Operation type for deductions
            'paymentMethod': Optional[str],  # Payment method for credit requests
            'paymentReference': Optional[str],  # Payment reference number
            'balanceBefore': Optional[float],  # Balance before transaction
            'balanceAfter': Optional[float],  # Balance after transaction
            'processedBy': Optional[ObjectId],  # Admin user ID who processed (for approvals)
            'rejectionReason': Optional[str],  # Reason for rejection
            'createdAt': datetime,  # Transaction timestamp
            'updatedAt': Optional[datetime],  # Last update timestamp
            'metadata': Optional[Dict[str, Any]],  # Additional metadata
        }
    
    @staticmethod
    def get_credit_transaction_indexes() -> List[Dict[str, Any]]:
        """Define indexes for credit_transactions collection."""
        return [
            {'keys': [('userId', 1), ('createdAt', -1)], 'name': 'user_created_desc'},
            {'keys': [('userId', 1), ('type', 1)], 'name': 'user_type'},
            {'keys': [('userId', 1), ('status', 1)], 'name': 'user_status'},
            {'keys': [('requestId', 1)], 'sparse': True, 'name': 'request_id'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]
    
    # ==================== CREDIT_REQUESTS COLLECTION ====================
    
    @staticmethod
    def get_credit_request_schema() -> Dict[str, Any]:
        """
        Schema for credit_requests collection.
        Stores credit top-up requests submitted by users for admin approval.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'requestId': str,  # Required, unique request identifier (UUID)
            'amount': float,  # Required, requested credit amount (must be > 0)
            'paymentMethod': str,  # Required, payment method used
            'paymentReference': Optional[str],  # Optional payment reference
            'receiptUrl': Optional[str],  # Optional receipt/proof URL
            'notes': Optional[str],  # Optional user notes
            'status': str,  # Request status: 'pending', 'approved', 'rejected', 'processing'
            'createdAt': datetime,  # Request submission timestamp
            'updatedAt': datetime,  # Last update timestamp
            'processedBy': Optional[ObjectId],  # Admin user ID who processed
            'processedAt': Optional[datetime],  # Processing timestamp
            'rejectionReason': Optional[str],  # Reason for rejection
            'adminNotes': Optional[str],  # Admin notes
        }
    
    @staticmethod
    def get_credit_request_indexes() -> List[Dict[str, Any]]:
        """Define indexes for credit_requests collection."""
        return [
            {'keys': [('requestId', 1)], 'unique': True, 'name': 'request_id_unique'},
            {'keys': [('userId', 1), ('createdAt', -1)], 'name': 'user_created_desc'},
            {'keys': [('status', 1), ('createdAt', -1)], 'name': 'status_created_desc'},
            {'keys': [('processedBy', 1)], 'sparse': True, 'name': 'processed_by'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]
    
    # ==================== TAX_CALCULATIONS COLLECTION ====================
    
    @staticmethod
    def get_tax_calculation_schema() -> Dict[str, Any]:
        """
        Schema for tax_calculations collection.
        Stores Personal Income Tax (PIT) calculations for individual taxpayers.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'entity_type': str,  # Required: 'individual' (only individual supported for now)
            'tax_year': int,  # Required, tax year for calculation
            'calculation_date': datetime,  # Required, when calculation was performed
            
            # Step 1: Net Income
            'total_income': float,  # Required, total income before deductions
            'deductible_expenses': Dict[str, float],  # Breakdown of deductible expenses
            'net_income': float,  # Calculated: total_income - total_expenses
            
            # Step 2: Adjusted Income
            'statutory_contributions': float,  # Pension, NHF, NHIS, etc.
            'adjusted_income': float,  # Calculated: net_income - statutory_contributions
            
            # Step 3: Taxable Income
            'annual_rent': float,  # Annual rent paid
            'rent_relief': float,  # Calculated: min(20% of rent, ₦500,000)
            'taxable_income': float,  # Calculated: adjusted_income - rent_relief
            
            # Step 4: Tax Calculation
            'tax_breakdown': List[Dict[str, Any]],  # Progressive tax band breakdown
            'total_tax': float,  # Calculated total tax
            'effective_rate': float,  # Effective tax rate percentage
            'net_income_after_tax': float,  # Income after tax
            
            'createdAt': datetime,  # Record creation timestamp
        }
    
    @staticmethod
    def get_tax_calculation_indexes() -> List[Dict[str, Any]]:
        """Define indexes for tax_calculations collection."""
        return [
            {'keys': [('userId', 1), ('calculation_date', -1)], 'name': 'user_date_desc'},
            {'keys': [('userId', 1), ('tax_year', 1)], 'name': 'user_tax_year'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]
    
    # ==================== TAX_EDUCATION_PROGRESS COLLECTION ====================
    
    @staticmethod
    def get_tax_education_progress_schema() -> Dict[str, Any]:
        """
        Schema for tax_education_progress collection.
        Tracks user progress through tax education modules.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'module_id': str,  # Required, education module identifier
            'completed': bool,  # Required, completion status
            'completed_at': Optional[datetime],  # When module was completed
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
        }
    
    @staticmethod
    def get_tax_education_progress_indexes() -> List[Dict[str, Any]]:
        """Define indexes for tax_education_progress collection."""
        return [
            {'keys': [('userId', 1), ('module_id', 1)], 'unique': True, 'name': 'user_module_unique'},
            {'keys': [('userId', 1), ('completed', 1)], 'name': 'user_completed'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== DEBTORS COLLECTION ====================
    
    @staticmethod
    def get_debtor_schema() -> Dict[str, Any]:
        """
        Schema for debtors collection.
        Stores customer debt tracking and accounts receivable.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'customerName': str,  # Required, customer name
            'customerEmail': Optional[str],  # Optional customer email
            'customerPhone': Optional[str],  # Optional customer phone
            'customerAddress': Optional[str],  # Optional customer address
            'totalDebt': float,  # Current total debt amount
            'paidAmount': float,  # Amount paid so far
            'remainingDebt': float,  # Calculated: totalDebt - paidAmount
            'status': str,  # 'active', 'paid', 'overdue', 'written_off'
            'creditLimit': Optional[float],  # Credit limit for customer
            'paymentTerms': str,  # '30_days', '60_days', '90_days', 'custom'
            'customPaymentDays': Optional[int],  # For custom payment terms
            'lastPaymentDate': Optional[datetime],  # Last payment received
            'nextPaymentDue': Optional[datetime],  # Next payment due date
            'overdueDays': int,  # Calculated overdue days
            'notes': Optional[str],  # Additional notes
            'tags': List[str],  # Tags for categorization
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
        }
    
    @staticmethod
    def get_debtor_indexes() -> List[Dict[str, Any]]:
        """Define indexes for debtors collection."""
        return [
            {'keys': [('userId', 1), ('customerName', 1)], 'name': 'user_customer_name'},
            {'keys': [('userId', 1), ('status', 1)], 'name': 'user_status'},
            {'keys': [('userId', 1), ('nextPaymentDue', 1)], 'name': 'user_payment_due'},
            {'keys': [('userId', 1), ('overdueDays', -1)], 'name': 'user_overdue_desc'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== DEBTOR_TRANSACTIONS COLLECTION ====================
    
    @staticmethod
    def get_debtor_transaction_schema() -> Dict[str, Any]:
        """
        Schema for debtor_transactions collection.
        Stores sales and payment transactions for customers.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'debtorId': ObjectId,  # Required, reference to debtors._id
            'type': str,  # Required: 'sale', 'payment', 'adjustment'
            'amount': float,  # Required, transaction amount
            'description': str,  # Required, transaction description
            'invoiceNumber': Optional[str],  # Optional invoice number
            'paymentMethod': Optional[str],  # Payment method for payments
            'paymentReference': Optional[str],  # Payment reference
            'dueDate': Optional[datetime],  # Due date for sales
            'transactionDate': datetime,  # Required, transaction date
            'balanceBefore': float,  # Balance before transaction
            'balanceAfter': float,  # Balance after transaction
            'status': str,  # 'pending', 'completed', 'cancelled'
            'notes': Optional[str],  # Additional notes
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
        }
    
    @staticmethod
    def get_debtor_transaction_indexes() -> List[Dict[str, Any]]:
        """Define indexes for debtor_transactions collection."""
        return [
            {'keys': [('userId', 1), ('debtorId', 1), ('transactionDate', -1)], 'name': 'user_debtor_date_desc'},
            {'keys': [('userId', 1), ('type', 1)], 'name': 'user_type'},
            {'keys': [('userId', 1), ('status', 1)], 'name': 'user_status'},
            {'keys': [('invoiceNumber', 1)], 'sparse': True, 'name': 'invoice_number'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== CREDITORS COLLECTION ====================
    
    @staticmethod
    def get_creditor_schema() -> Dict[str, Any]:
        """
        Schema for creditors collection.
        Stores vendor payables tracking and accounts payable.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'vendorName': str,  # Required, vendor name
            'vendorEmail': Optional[str],  # Optional vendor email
            'vendorPhone': Optional[str],  # Optional vendor phone
            'vendorAddress': Optional[str],  # Optional vendor address
            'totalOwed': float,  # Current total amount owed
            'paidAmount': float,  # Amount paid so far
            'remainingOwed': float,  # Calculated: totalOwed - paidAmount
            'status': str,  # 'active', 'paid', 'overdue'
            'paymentTerms': str,  # '30_days', '60_days', '90_days', 'custom'
            'customPaymentDays': Optional[int],  # For custom payment terms
            'lastPaymentDate': Optional[datetime],  # Last payment made
            'nextPaymentDue': Optional[datetime],  # Next payment due date
            'overdueDays': int,  # Calculated overdue days
            'creditLimit': Optional[float],  # Credit limit from vendor
            'notes': Optional[str],  # Additional notes
            'tags': List[str],  # Tags for categorization
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
        }
    
    @staticmethod
    def get_creditor_indexes() -> List[Dict[str, Any]]:
        """Define indexes for creditors collection."""
        return [
            {'keys': [('userId', 1), ('vendorName', 1)], 'name': 'user_vendor_name'},
            {'keys': [('userId', 1), ('status', 1)], 'name': 'user_status'},
            {'keys': [('userId', 1), ('nextPaymentDue', 1)], 'name': 'user_payment_due'},
            {'keys': [('userId', 1), ('overdueDays', -1)], 'name': 'user_overdue_desc'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== CREDITOR_TRANSACTIONS COLLECTION ====================
    
    @staticmethod
    def get_creditor_transaction_schema() -> Dict[str, Any]:
        """
        Schema for creditor_transactions collection.
        Stores purchase and payment transactions for vendors.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'creditorId': ObjectId,  # Required, reference to creditors._id
            'type': str,  # Required: 'purchase', 'payment', 'adjustment'
            'amount': float,  # Required, transaction amount
            'description': str,  # Required, transaction description
            'invoiceNumber': Optional[str],  # Optional invoice number
            'paymentMethod': Optional[str],  # Payment method for payments
            'paymentReference': Optional[str],  # Payment reference
            'dueDate': Optional[datetime],  # Due date for purchases
            'transactionDate': datetime,  # Required, transaction date
            'balanceBefore': float,  # Balance before transaction
            'balanceAfter': float,  # Balance after transaction
            'status': str,  # 'pending', 'completed', 'cancelled'
            'notes': Optional[str],  # Additional notes
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
        }
    
    @staticmethod
    def get_creditor_transaction_indexes() -> List[Dict[str, Any]]:
        """Define indexes for creditor_transactions collection."""
        return [
            {'keys': [('userId', 1), ('creditorId', 1), ('transactionDate', -1)], 'name': 'user_creditor_date_desc'},
            {'keys': [('userId', 1), ('type', 1)], 'name': 'user_type'},
            {'keys': [('userId', 1), ('status', 1)], 'name': 'user_status'},
            {'keys': [('invoiceNumber', 1)], 'sparse': True, 'name': 'invoice_number'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== INVENTORY_ITEMS COLLECTION ====================
    
    @staticmethod
    def get_inventory_item_schema() -> Dict[str, Any]:
        """
        Schema for inventory_items collection.
        Stores product catalog with cost and selling prices.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'itemName': str,  # Required, item name
            'itemCode': Optional[str],  # Optional SKU/Product code
            'description': Optional[str],  # Optional description
            'category': str,  # Required, product category
            'costPrice': float,  # Required, cost per unit
            'sellingPrice': float,  # Required, selling price per unit
            'currentStock': int,  # Current stock quantity
            'minimumStock': int,  # Minimum stock alert level
            'maximumStock': Optional[int],  # Maximum stock level
            'unit': str,  # Required: 'pieces', 'kg', 'liters', etc.
            'supplier': Optional[str],  # Supplier name
            'location': Optional[str],  # Storage location
            'status': str,  # 'active', 'discontinued', 'out_of_stock'
            'lastRestocked': Optional[datetime],  # Last restock date
            'expiryDate': Optional[datetime],  # For perishable items
            'tags': List[str],  # Tags for categorization
            'images': List[str],  # Image URLs
            'notes': Optional[str],  # Additional notes
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
        }
    
    @staticmethod
    def get_inventory_item_indexes() -> List[Dict[str, Any]]:
        """Define indexes for inventory_items collection."""
        return [
            {'keys': [('userId', 1), ('itemName', 1)], 'name': 'user_item_name'},
            {'keys': [('userId', 1), ('category', 1)], 'name': 'user_category'},
            {'keys': [('userId', 1), ('status', 1)], 'name': 'user_status'},
            {'keys': [('userId', 1), ('currentStock', 1)], 'name': 'user_stock'},
            {'keys': [('itemCode', 1)], 'sparse': True, 'name': 'item_code'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== INVENTORY_MOVEMENTS COLLECTION ====================
    
    @staticmethod
    def get_inventory_movement_schema() -> Dict[str, Any]:
        """
        Schema for inventory_movements collection.
        Tracks all stock movements and changes.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'itemId': ObjectId,  # Required, reference to inventory_items._id
            'movementType': str,  # Required: 'in', 'out', 'adjustment', 'transfer'
            'quantity': int,  # Required, quantity moved (positive for in, negative for out)
            'unitCost': Optional[float],  # Cost per unit for stock in
            'totalCost': Optional[float],  # Total cost for movement
            'reason': str,  # Required: 'purchase', 'sale', 'damage', 'theft', 'adjustment'
            'reference': Optional[str],  # Invoice/receipt reference
            'stockBefore': int,  # Stock before movement
            'stockAfter': int,  # Stock after movement
            'movementDate': datetime,  # Required, movement date
            'notes': Optional[str],  # Additional notes
            'createdAt': datetime,  # Record creation timestamp
        }
    
    @staticmethod
    def get_inventory_movement_indexes() -> List[Dict[str, Any]]:
        """Define indexes for inventory_movements collection."""
        return [
            {'keys': [('userId', 1), ('itemId', 1), ('movementDate', -1)], 'name': 'user_item_date_desc'},
            {'keys': [('userId', 1), ('movementType', 1)], 'name': 'user_movement_type'},
            {'keys': [('userId', 1), ('reason', 1)], 'name': 'user_reason'},
            {'keys': [('reference', 1)], 'sparse': True, 'name': 'reference'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== ATTACHMENTS COLLECTION ====================
    
    @staticmethod
    def get_attachment_schema() -> Dict[str, Any]:
        """
        Schema for attachments collection.
        Stores file attachments for income and expense records.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'entityType': str,  # Required: 'income' or 'expense'
            'entityId': ObjectId,  # Required, reference to incomes._id or expenses._id
            'originalFilename': str,  # Required, original filename
            'storagePath': str,  # Required, path in Google Cloud Storage
            'fileSize': int,  # File size in bytes
            'mimeType': str,  # File MIME type
            'description': Optional[str],  # Optional description
            'createdAt': datetime,  # Upload timestamp
            'updatedAt': datetime,  # Last update timestamp
        }
    
    @staticmethod
    def get_attachment_indexes() -> List[Dict[str, Any]]:
        """Define indexes for attachments collection."""
        return [
            {'keys': [('userId', 1), ('entityType', 1), ('entityId', 1)], 'name': 'user_entity_type_id'},
            {'keys': [('userId', 1), ('createdAt', -1)], 'name': 'user_created_desc'},
            {'keys': [('entityType', 1), ('entityId', 1)], 'name': 'entity_type_id'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== ASSETS COLLECTION ====================
    
    @staticmethod
    def get_asset_schema() -> Dict[str, Any]:
        """
        Schema for assets collection.
        Tracks fixed assets for 0% tax qualification (≤₦250M threshold).
        
        DEPRECIATION STRATEGY (Option A + C Hybrid):
        - Core: On-the-fly calculation as system of record
        - Layer: Manual adjustments for special cases (damage, appreciation, market changes)
        - currentValue: DEPRECATED, kept for backward compatibility
        - manualValueAdjustment: Optional manual override
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'assetName': str,  # Required, name of the asset
            'assetCode': Optional[str],  # Optional asset code/identifier
            'description': Optional[str],  # Optional description
            'category': str,  # Required: 'Vehicles', 'Office Equipment', 'Machinery', etc.
            'purchasePrice': float,  # Required, original purchase price
            'currentValue': float,  # DEPRECATED: Use calculated value instead (kept for backward compatibility)
            'purchaseDate': datetime,  # Required, date of purchase
            'supplier': Optional[str],  # Optional supplier name
            'location': Optional[str],  # Optional physical location
            'status': str,  # Required: 'active', 'disposed', 'under_maintenance'
            'depreciationRate': Optional[float],  # Optional annual depreciation rate (%)
            'depreciationMethod': str,  # Required: 'straight_line', 'reducing_balance', 'none'
            'usefulLifeYears': Optional[int],  # Optional useful life in years
            'attachments': List[str],  # List of attachment URLs/IDs (purchase invoices, receipts)
            'notes': Optional[str],  # Optional notes
            'disposalDate': Optional[datetime],  # Optional disposal date
            'disposalValue': Optional[float],  # Optional disposal value
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
            
            # NEW: Manual adjustment fields (Option C layer on top of Option A)
            'manualValueAdjustment': Optional[float],  # Manual override for special cases
            'lastValueUpdate': Optional[datetime],  # When manual adjustment was made
            'valueAdjustmentReason': Optional[str],  # Why manual adjustment was made (e.g., "Accident damage", "Market appreciation")
        }
    
    @staticmethod
    def get_asset_indexes() -> List[Dict[str, Any]]:
        """Define indexes for assets collection."""
        return [
            {'keys': [('userId', 1), ('status', 1)], 'name': 'user_status'},
            {'keys': [('userId', 1), ('category', 1)], 'name': 'user_category'},
            {'keys': [('userId', 1), ('createdAt', -1)], 'name': 'user_created_desc'},
            {'keys': [('assetCode', 1)], 'sparse': True, 'name': 'asset_code'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== ANALYTICS_EVENTS COLLECTION ====================
    
    @staticmethod
    def get_analytics_event_schema() -> Dict[str, Any]:
        """
        Schema for analytics_events collection.
        Tracks user activity events for admin dashboard metrics.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'eventType': str,  # Required: 'user_logged_in', 'income_entry_created', 'expense_entry_created', etc.
            'timestamp': datetime,  # Required, when event occurred
            'eventDetails': Optional[Dict[str, Any]],  # Optional event-specific data
            'deviceInfo': Optional[Dict[str, str]],  # Optional device information
            'sessionId': Optional[str],  # Optional session identifier
            'createdAt': datetime,  # Record creation timestamp
        }
    
    @staticmethod
    def get_analytics_event_indexes() -> List[Dict[str, Any]]:
        """Define indexes for analytics_events collection."""
        return [
            {'keys': [('userId', 1), ('timestamp', -1)], 'name': 'user_timestamp_desc'},
            {'keys': [('eventType', 1), ('timestamp', -1)], 'name': 'event_type_timestamp_desc'},
            {'keys': [('timestamp', -1)], 'name': 'timestamp_desc'},
            {'keys': [('userId', 1), ('eventType', 1)], 'name': 'user_event_type'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
        ]

    # ==================== ACTIVATION_EVENTS COLLECTION (PHASE 4) ====================
    
    @staticmethod
    def get_activation_event_schema() -> Dict[str, Any]:
        """
        Schema for activation_events collection.
        Tracks user activation events for Phase 4 analytics.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'eventType': str,  # Required: 'shown' | 'dismissed' | 'state_transition'
            'activationState': str,  # Required: 'S0' | 'S1' | 'S2' | 'S3'
            'nudgeType': Optional[str],  # Optional: 'noEntryYet' | 'firstEntryDone' | 'earlyStreak' | 'sevenDayStreak'
            'streakCount': int,  # Current streak count
            'occurredAt': datetime,  # Device time when event occurred
            'timezoneOffset': int,  # Minutes from UTC
            'createdAt': datetime,  # Server time when event was recorded
        }
    
    @staticmethod
    def get_activation_event_indexes() -> List[Dict[str, Any]]:
        """Define indexes for activation_events collection."""
        return [
            {'keys': [('userId', 1), ('createdAt', -1)], 'name': 'user_created_desc'},
            {'keys': [('eventType', 1), ('createdAt', -1)], 'name': 'event_type_created_desc'},
            {'keys': [('activationState', 1), ('createdAt', -1)], 'name': 'activation_state_created_desc'},
            {'keys': [('nudgeType', 1), ('createdAt', -1)], 'name': 'nudge_type_created_desc', 'sparse': True},
            {'keys': [('createdAt', -1)], 'name': 'created_desc'},
        ]

    # ==================== ADMIN_ACTIONS COLLECTION ====================
    
    @staticmethod
    def get_admin_action_schema() -> Dict[str, Any]:
        """
        Schema for admin_actions collection.
        Tracks administrative actions for audit purposes.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'adminId': ObjectId,  # Required, reference to admin user's _id
            'adminEmail': str,  # Required, admin's email for easy identification
            'action': str,  # Required, action type (e.g., 'password_reset_direct', 'credit_grant', etc.)
            'targetUserId': Optional[ObjectId],  # Optional, target user's _id (if applicable)
            'targetUserEmail': Optional[str],  # Optional, target user's email (if applicable)
            'reason': str,  # Required, reason for the action
            'timestamp': datetime,  # Required, when action was performed
            'details': Optional[Dict[str, Any]],  # Optional, additional action details
            'ipAddress': Optional[str],  # Optional, admin's IP address
            'userAgent': Optional[str],  # Optional, admin's user agent
        }
    
    @staticmethod
    def get_admin_action_indexes() -> List[Dict[str, Any]]:
        """Define indexes for admin_actions collection."""
        return [
            {'keys': [('adminId', 1), ('timestamp', -1)], 'name': 'admin_timestamp_desc'},
            {'keys': [('action', 1), ('timestamp', -1)], 'name': 'action_timestamp_desc'},
            {'keys': [('targetUserId', 1), ('timestamp', -1)], 'name': 'target_user_timestamp_desc'},
            {'keys': [('timestamp', -1)], 'name': 'timestamp_desc'},
            {'keys': [('adminEmail', 1)], 'name': 'admin_email'},
        ]
    
    @staticmethod
    def get_cancellation_request_indexes() -> List[Dict[str, Any]]:
        """Define indexes for cancellation_requests collection."""
        return [
            {'keys': [('userId', 1), ('requestedAt', -1)], 'name': 'user_requested_desc'},
            {'keys': [('status', 1), ('requestedAt', -1)], 'name': 'status_requested_desc'},
            {'keys': [('requestedAt', -1)], 'name': 'requested_desc'},
            {'keys': [('processedAt', -1)], 'name': 'processed_desc', 'sparse': True},
            {'keys': [('processedBy', 1)], 'name': 'processed_by', 'sparse': True},
            {'keys': [('userEmail', 1)], 'name': 'user_email'},
        ]

    # ==================== VAS_WALLETS COLLECTION ====================
    
    @staticmethod
    def get_vas_wallet_schema() -> Dict[str, Any]:
        """
        Schema for vas_wallets collection.
        Stores VAS wallet information including balance, account details, and KYC status.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'balance': float,  # Current wallet balance, default: 0.0
            'accountReference': str,  # Monnify account reference (user ID)
            'contractCode': Optional[str],  # Monnify contract code
            'accountName': str,  # Account holder name
            'accountNumber': Optional[str],  # Primary account number
            'bankName': Optional[str],  # Primary bank name
            'bankCode': Optional[str],  # Primary bank code
            'accounts': List[Dict[str, Any]],  # List of all available bank accounts
            'status': str,  # 'active', 'inactive', 'suspended', default: 'active'
            'tier': str,  # 'TIER_0', 'TIER_1', 'TIER_2', default: 'TIER_1'
            'kycVerified': bool,  # KYC verification status, default: False
            'kycStatus': str,  # 'pending', 'verified', 'rejected', default: 'pending'
            'bvn': Optional[str],  # Bank Verification Number (11 digits)
            'nin': Optional[str],  # National Identification Number (11 digits)
            'transactionHistory': List[Dict[str, Any]],  # Transaction history for quick access
            'createdAt': datetime,  # Wallet creation timestamp
            'updatedAt': datetime,  # Last update timestamp
            'lastTransactionAt': Optional[datetime],  # Last transaction timestamp
            'metadata': Optional[Dict[str, Any]],  # Additional metadata
        }
    
    @staticmethod
    def get_vas_wallet_indexes() -> List[Dict[str, Any]]:
        """Define indexes for vas_wallets collection."""
        return [
            {'keys': [('userId', 1)], 'unique': True, 'name': 'user_id_unique'},
            {'keys': [('accountReference', 1)], 'unique': True, 'name': 'account_reference_unique'},
            {'keys': [('status', 1)], 'name': 'status_index'},
            {'keys': [('kycStatus', 1)], 'name': 'kyc_status_index'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
            {'keys': [('lastTransactionAt', -1)], 'name': 'last_transaction_desc'},
        ]

    # ==================== VAS_TRANSACTIONS COLLECTION ====================
    
    @staticmethod
    def get_vas_transaction_schema() -> Dict[str, Any]:
        """
        Schema for vas_transactions collection.
        Stores all VAS transaction records (airtime, data, wallet funding, bills, etc.).
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'walletId': Optional[ObjectId],  # Reference to vas_wallets._id
            'type': str,  # Required: 'AIRTIME', 'DATA', 'WALLET_FUNDING', 'BILLS', 'REFUND'
            'subtype': Optional[str],  # Specific subtype: 'airtime', 'data', 'electricity', etc.
            'amount': float,  # Required, transaction amount (must be > 0)
            'amountPaid': Optional[float],  # Amount actually paid by user
            'amountCredited': Optional[float],  # Amount credited to wallet
            'fee': Optional[float],  # Transaction fee
            'depositFee': Optional[float],  # Deposit fee for wallet funding
            'serviceFee': Optional[float],  # Service fee for VAS purchases
            'totalAmount': Optional[float],  # Total amount including fees
            'status': str,  # 'PENDING', 'SUCCESS', 'FAILED', 'PROCESSING', 'NEEDS_RECONCILIATION'
            'provider': str,  # 'monnify', 'peyflex', 'vtpass', 'optimistic'
            'providerReference': Optional[str],  # Provider's transaction reference
            'transactionReference': str,  # Our internal transaction reference
            'reference': Optional[str],  # Alternative reference field
            'description': str,  # Human-readable description
            'category': Optional[str],  # Transaction category
            
            # VAS-specific fields
            'phoneNumber': Optional[str],  # For airtime/data purchases
            'network': Optional[str],  # Network provider (MTN, Airtel, Glo, 9mobile)
            'dataPlan': Optional[str],  # Data plan name
            'dataPlanId': Optional[str],  # Data plan identifier
            'dataPlanName': Optional[str],  # Data plan display name
            
            # Bills-specific fields
            'billCategory': Optional[str],  # 'electricity', 'cable_tv', 'water', 'internet'
            'billProvider': Optional[str],  # DSTV, GOTV, EKEDC, etc.
            'accountNumber': Optional[str],  # Meter number, decoder number, etc.
            'customerName': Optional[str],  # Name on the account
            'packageId': Optional[str],  # For cable TV packages
            'packageName': Optional[str],  # For cable TV packages
            
            # Wallet funding specific fields
            'fundingMethod': Optional[str],  # 'bank_transfer', 'card', 'ussd'
            'bankName': Optional[str],  # Bank used for funding
            'bankCode': Optional[str],  # Bank code
            
            # Navigation and classification flags
            'isVAS': bool,  # Always True for VAS transactions, default: True
            'isIncome': bool,  # For wallet funding transactions, default: False
            'isExpense': bool,  # For VAS purchases, default: False
            'isOptimistic': Optional[bool],  # For immediate display before sync
            
            # Timestamps
            'createdAt': datetime,  # Transaction creation timestamp
            'completedAt': Optional[datetime],  # Transaction completion timestamp
            'expiresAt': Optional[datetime],  # Transaction expiry timestamp
            'updatedAt': datetime,  # Last update timestamp
            
            # Reconciliation and audit
            'reconciled': bool,  # Whether transaction has been reconciled, default: False
            'reconciledAt': Optional[datetime],  # Reconciliation timestamp
            'auditLog': List[Dict[str, Any]],  # Audit trail for status changes
            'metadata': Optional[Dict[str, Any]],  # Additional metadata
            
            # Immutability fields (for financial compliance)
            'version': int,  # Version number for updates, default: 1
            'originalEntryId': Optional[ObjectId],  # Reference to original entry if this is an update
            'supersededBy': Optional[ObjectId],  # Reference to newer version if superseded
            'isDeleted': bool,  # Soft delete flag, default: False
            'deletedAt': Optional[datetime],  # Soft delete timestamp
            'deletionReason': Optional[str],  # Reason for deletion
        }
    
    @staticmethod
    def get_vas_transaction_indexes() -> List[Dict[str, Any]]:
        """Define indexes for vas_transactions collection."""
        return [
            {'keys': [('userId', 1), ('createdAt', -1)], 'name': 'user_created_desc'},
            {'keys': [('userId', 1), ('type', 1)], 'name': 'user_type'},
            {'keys': [('userId', 1), ('status', 1)], 'name': 'user_status'},
            {'keys': [('userId', 1), ('isVAS', 1)], 'name': 'user_is_vas'},
            {'keys': [('transactionReference', 1)], 'unique': True, 'name': 'transaction_reference_unique'},
            {'keys': [('providerReference', 1)], 'sparse': True, 'name': 'provider_reference'},
            {'keys': [('status', 1), ('createdAt', -1)], 'name': 'status_created_desc'},
            {'keys': [('type', 1), ('createdAt', -1)], 'name': 'type_created_desc'},
            {'keys': [('provider', 1), ('createdAt', -1)], 'name': 'provider_created_desc'},
            {'keys': [('phoneNumber', 1)], 'sparse': True, 'name': 'phone_number'},
            {'keys': [('network', 1)], 'sparse': True, 'name': 'network'},
            {'keys': [('reconciled', 1)], 'name': 'reconciled_index'},
            {'keys': [('createdAt', -1)], 'name': 'created_at_desc'},
            # Compound indexes for complex queries
            {'keys': [('userId', 1), ('type', 1), ('status', 1)], 'name': 'user_type_status'},
            {'keys': [('userId', 1), ('isVAS', 1), ('createdAt', -1)], 'name': 'user_vas_created_desc'},
            # Immutability indexes
            {'keys': [('userId', 1), ('isDeleted', 1), ('status', 1)], 'name': 'user_deleted_status'},
            {'keys': [('originalEntryId', 1)], 'sparse': True, 'name': 'original_entry_id'},
        ]

    # ==================== VOICE_REPORTS COLLECTION ====================

    @staticmethod
    def get_voice_report_schema() -> Dict[str, Any]:
        """
        Schema for voice_reports collection.
        Stores voice recordings, transcriptions, and extracted financial data.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'userId': ObjectId,  # Required, reference to users._id
            'idempotencyKey': str,  # Required, unique UUID for retry safety
            'transcription': str,  # Required, transcribed text from audio
            'audioUrl': Optional[str],  # Optional, URL to audio file (GCS or cloud storage)
            'audioFileName': Optional[str],  # Original filename for display
            'audioFileSize': Optional[int],  # Size in bytes for tracking storage
            
            # Extracted financial data
            'extractedAmount': float,  # Extracted monetary amount
            'currencyCode': str,  # Currency code (e.g., 'NGN', 'USD'), default: 'NGN'
            'category': str,  # Category of transaction ('income', 'expense', 'debt', 'credit', etc.)
            'transactionType': Optional[str],  # More specific type (e.g., 'salary', 'purchase', 'loan')
            'description': str,  # Human-readable description
            'confidence': float,  # Extraction confidence score (0.0-1.0)
            
            # Processing status
            'status': str,  # 'pending', 'processing', 'completed', 'error', default: 'pending'
            'transcriptionStatus': str,  # 'pending', 'completed', 'failed'
            'syncStatus': str,  # 'synced', 'pending', 'failed'
            'processingError': Optional[str],  # Error message if processing failed
            
            # Transaction creation (after successful processing)
            'linkedTransactionId': Optional[ObjectId],  # Reference to created income/expense/debtor/creditor entry
            'linkedTransactionType': Optional[str],  # Type of linked transaction ('income', 'expense', 'debtor', 'creditor')
            
            # FCM notification tracking
            'notificationSent': bool,  # Whether FCM notification was sent, default: False
            'userNotified': bool,  # Whether user was notified in app, default: False
            
            # Timestamps
            'recordedAt': datetime,  # When audio was recorded
            'uploadedAt': datetime,  # When uploaded to backend
            'transcribedAt': Optional[datetime],  # When transcription completed
            'processedAt': Optional[datetime],  # When data extraction completed
            'syncedAt': Optional[datetime],  # When synced to backend
            'createdAt': datetime,  # Record creation timestamp
            'updatedAt': datetime,  # Last update timestamp
        }

    @staticmethod
    def get_voice_report_indexes() -> List[Dict[str, Any]]:
        """Define indexes for voice_reports collection."""
        return [
            {'keys': [('userId', 1), ('createdAt', -1)], 'name': 'user_created_desc'},
            {'keys': [('idempotencyKey', 1)], 'unique': True, 'name': 'idempotency_key_unique'},
            {'keys': [('status', 1), ('createdAt', -1)], 'name': 'status_created_desc'},
            {'keys': [('syncStatus', 1), ('createdAt', -1)], 'name': 'sync_status_created_desc'},
            {'keys': [('linkedTransactionId', 1)], 'sparse': True, 'name': 'linked_transaction_id'},
            {'keys': [('recordedAt', -1)], 'name': 'recorded_at_desc'},
            {'keys': [('uploadedAt', -1)], 'name': 'uploaded_at_desc'},
        ]

    # ==================== IDEMPOTENCY_KEYS COLLECTION ====================

    @staticmethod
    def get_idempotency_key_schema() -> Dict[str, Any]:
        """
        Schema for idempotency_keys collection.
        Stores request responses for idempotency on retries.
        """
        return {
            '_id': ObjectId,  # Auto-generated MongoDB ID
            'idempotencyKey': str,  # Required, unique UUID from client request
            'userId': ObjectId,  # Required, reference to users._id
            'endpoint': str,  # Required, API endpoint that was called (e.g., '/api/voice/create')
            'requestHash': str,  # Hash of request body for validation
            
            # Cached response for retry requests
            'responseStatus': int,  # HTTP status code (200, 201, 400, 500, etc.)
            'responseBody': Dict[str, Any],  # Full response JSON
            'responseHeaders': Optional[Dict[str, str]],  # Relevant response headers
            
            # Metadata
            'createdAt': datetime,  # When first request was processed
            'expiresAt': datetime,  # When this cache entry expires (24 hours from creation)
        }

    @staticmethod
    def get_idempotency_key_indexes() -> List[Dict[str, Any]]:
        """Define indexes for idempotency_keys collection."""
        return [
            {'keys': [('idempotencyKey', 1)], 'unique': True, 'name': 'idempotency_key_unique'},
            {'keys': [('userId', 1), ('createdAt', -1)], 'name': 'user_created_desc'},
            {'keys': [('endpoint', 1), ('createdAt', -1)], 'name': 'endpoint_created_desc'},
            {'keys': [('expiresAt', 1)], 'name': 'expires_at', 'expireAfterSeconds': 86400},  # TTL: 24 hours
        ]


class DatabaseInitializer:
    """
    Database initialization and management utilities.
    Handles collection creation, index setup, and validation.
    """
    
    def __init__(self, mongo_db):
        """
        Initialize with MongoDB database instance.
        
        Args:
            mongo_db: PyMongo database instance
        """
        self.db = mongo_db
        self.schema = DatabaseSchema()
    
    def initialize_collections(self):
        """
        Initialize all collections with proper indexes.
        Safe to run multiple times - will skip if collections exist.
        """
        collections = {
            'users': self.schema.get_user_indexes(),
            'incomes': self.schema.get_income_indexes(),
            'expenses': self.schema.get_expense_indexes(),
            'credit_transactions': self.schema.get_credit_transaction_indexes(),
            'credit_requests': self.schema.get_credit_request_indexes(),
            'tax_calculations': self.schema.get_tax_calculation_indexes(),
            'tax_education_progress': self.schema.get_tax_education_progress_indexes(),
            'debtors': self.schema.get_debtor_indexes(),
            'debtor_transactions': self.schema.get_debtor_transaction_indexes(),
            'creditors': self.schema.get_creditor_indexes(),
            'creditor_transactions': self.schema.get_creditor_transaction_indexes(),
            'inventory_items': self.schema.get_inventory_item_indexes(),
            'inventory_movements': self.schema.get_inventory_movement_indexes(),
            'attachments': self.schema.get_attachment_indexes(),
            'assets': self.schema.get_asset_indexes(),
            'analytics_events': self.schema.get_analytics_event_indexes(),
            'admin_actions': self.schema.get_admin_action_indexes(),
            'cancellation_requests': self.schema.get_cancellation_request_indexes(),
            # VAS collections
            'vas_wallets': self.schema.get_vas_wallet_indexes(),
            'vas_transactions': self.schema.get_vas_transaction_indexes(),
            # Voice reporting collections
            'voice_reports': self.schema.get_voice_report_indexes(),
            'idempotency_keys': self.schema.get_idempotency_key_indexes(),
        }
        
        results = {
            'created': [],
            'existing': [],
            'indexes_created': [],
            'errors': []
        }
        
        for collection_name, indexes in collections.items():
            try:
                # Check if collection exists
                if collection_name in self.db.list_collection_names():
                    results['existing'].append(collection_name)
                    print(f"✓ Collection '{collection_name}' already exists")
                else:
                    # Create collection
                    self.db.create_collection(collection_name)
                    results['created'].append(collection_name)
                    print(f"✓ Created collection '{collection_name}'")
                
                # Create indexes (will skip if they already exist)
                collection = self.db[collection_name]
                existing_indexes = collection.index_information()
                
                for index_def in indexes:
                    index_name = index_def.get('name')
                    index_keys = index_def['keys']
                    
                    # Check if index already exists by name
                    if index_name and index_name in existing_indexes:
                        print(f"  ✓ Index '{index_name}' already exists on '{collection_name}'")
                        continue
                    
                    # Check if an index with the same key pattern already exists (different name)
                    index_exists_with_different_name = False
                    for existing_name, existing_info in existing_indexes.items():
                        if existing_name != '_id_':  # Skip the default _id index
                            existing_keys = existing_info.get('key', [])
                            # Convert to list of tuples for comparison
                            existing_keys_list = list(existing_keys.items()) if isinstance(existing_keys, dict) else existing_keys
                            if existing_keys_list == index_keys:
                                print(f"  ✓ Index with same keys already exists as '{existing_name}' on '{collection_name}' (skipping '{index_name}')")
                                index_exists_with_different_name = True
                                break
                    
                    if index_exists_with_different_name:
                        continue
                    
                    try:
                        created_index_name = collection.create_index(
                            index_def['keys'],
                            unique=index_def.get('unique', False),
                            sparse=index_def.get('sparse', False),
                            name=index_name
                        )
                        results['indexes_created'].append(f"{collection_name}.{created_index_name}")
                        print(f"  ✓ Created index '{created_index_name}' on '{collection_name}'")
                    except Exception as index_error:
                        # Handle specific error cases
                        if 'already exists' in str(index_error).lower() or 'duplicate key' in str(index_error).lower():
                            print(f"  ✓ Index '{index_name}' already exists on '{collection_name}'")
                        else:
                            error_msg = f"Failed to create index '{index_name}' on {collection_name}: {str(index_error)}"
                            results['errors'].append(error_msg)
                            print(f"  ✗ {error_msg}")
            
            except Exception as e:
                error_msg = f"Failed to initialize collection {collection_name}: {str(e)}"
                results['errors'].append(error_msg)
                print(f"✗ {error_msg}")
        
        return results
    
    def validate_collection_exists(self, collection_name: str) -> bool:
        """
        Check if a collection exists in the database.
        
        Args:
            collection_name: Name of the collection to check
            
        Returns:
            bool: True if collection exists, False otherwise
        """
        return collection_name in self.db.list_collection_names()
    
    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """
        Get statistics for a collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            dict: Collection statistics including document count and indexes
        """
        if not self.validate_collection_exists(collection_name):
            return {'error': f"Collection '{collection_name}' does not exist"}
        
        collection = self.db[collection_name]
        
        return {
            'name': collection_name,
            'count': collection.count_documents({}),
            'indexes': list(collection.list_indexes()),
            'size_bytes': self.db.command('collStats', collection_name).get('size', 0),
        }
    
    def get_all_collections_stats(self) -> Dict[str, Any]:
        """
        Get statistics for all collections in the database.
        
        Returns:
            dict: Statistics for all collections
        """
        stats = {}
        for collection_name in collections:
            stats[collection_name] = self.get_collection_stats(collection_name)
        
        return stats


class ModelValidator:
    """
    Validation utilities for model data.
    Provides validation methods for common data types and business rules.
    """
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0.9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    @staticmethod
    def validate_amount(amount: float) -> bool:
        """Validate amount is positive."""
        try:
            return float(amount) > 0
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def validate_date(date_value) -> bool:
        """Validate date is a datetime object."""
        return isinstance(date_value, datetime)
    
    @staticmethod
    def validate_object_id(obj_id) -> bool:
        """Validate ObjectId."""
        return isinstance(obj_id, ObjectId) or ObjectId.is_valid(obj_id)
    
    @staticmethod
    def validate_frequency(frequency: str) -> bool:
        """Validate income frequency."""
        valid_frequencies = ['one_time', 'daily', 'weekly', 'biweekly', 
                           'monthly', 'quarterly', 'yearly']
        return frequency in valid_frequencies
    
    @staticmethod
    def validate_status(status: str, valid_statuses: List[str]) -> bool:
        """Validate status against allowed values."""
        return status in valid_statuses
    
    @staticmethod
    def validate_user_role(role: str) -> bool:
        """Validate user role."""
        return role in ['personal', 'admin']
    
    @staticmethod
    def validate_transaction_type(trans_type: str) -> bool:
        """Validate transaction type."""
        return trans_type in ['credit', 'debit', 'request']
    
    @staticmethod
    def validate_request_status(status: str) -> bool:
        """Validate credit request status."""
        return status in ['pending', 'approved', 'rejected', 'processing']


# Export main classes
__all__ = [
    'DatabaseSchema',
    'DatabaseInitializer',
    'ModelValidator',
]


if __name__ == '__main__':
    """
    Standalone script to initialize database collections and indexes.
    Can be run independently to set up the database schema.
    """
    import os
    from flask_pymongo import PyMongo
    from flask import Flask
    
    # Create minimal Flask app for database connection
    app = Flask(__name__)
    app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/ficore_mobile')
    
    # Initialize MongoDB
    mongo = PyMongo(app)
    
    print("=" * 60)
    print("FiCore Mobile Backend - Database Initialization")
    print("=" * 60)
    print(f"MongoDB URI: {app.config['MONGO_URI']}")
    print()
    
    # Initialize database
    initializer = DatabaseInitializer(mongo.db)
    
    print("Initializing collections and indexes...")
    print()
    
    results = initializer.initialize_collections()
    
    print()
    print("=" * 60)
    print("Initialization Summary")
    print("=" * 60)
    print(f"Collections created: {len(results['created'])}")
    for col in results['created']:
        print(f"  - {col}")
    
    print(f"\nCollections already existing: {len(results['existing'])}")
    for col in results['existing']:
        print(f"  - {col}")
    
    print(f"\nIndexes created/verified: {len(results['indexes_created'])}")
    
    if results['errors']:
        print(f"\nErrors encountered: {len(results['errors'])}")
        for error in results['errors']:
            print(f"  - {error}")
    
    print()
    print("=" * 60)
    print("Database Statistics")
    print("=" * 60)
    
    stats = initializer.get_all_collections_stats()
    for collection_name, collection_stats in stats.items():
        if 'error' not in collection_stats:
            print(f"\n{collection_name}:")
            print(f"  Documents: {collection_stats['count']}")
            print(f"  Size: {collection_stats['size_bytes']} bytes")
            print(f"  Indexes: {len(collection_stats['indexes'])}")
    
    print()
    print("=" * 60)
    print("Database initialization complete!")
    print("=" * 60)
