"""
Automatic Drawings - Phase 2.2
Auto-create Drawings entries when Personal-tagged wallet spends occur
"""

from datetime import datetime
from bson import ObjectId

def create_drawing_entry(mongo, user_id, amount, description, linked_expense_id=None):
    """
    Create a Drawings entry for owner's personal withdrawals
    
    Args:
        mongo: MongoDB instance
        user_id: User's ObjectId
        amount: Withdrawal amount
        description: Description of the drawing
        linked_expense_id: Optional expense ID that triggered this drawing
    
    Returns:
        ObjectId of created drawing entry
    """
    try:
        drawing_data = {
            '_id': ObjectId(),
            'userId': user_id,
            'amount': amount,
            'description': description,
            'linkedExpenseId': linked_expense_id,
            'date': datetime.utcnow(),
            'status': 'active',
            'isDeleted': False,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow()
        }
        
        result = mongo.db.drawings.insert_one(drawing_data)
        
        # Update user's total drawings
        user = mongo.db.users.find_one({'_id': user_id})
        current_drawings = user.get('drawings', 0) if user else 0
        new_drawings = current_drawings + amount
        
        mongo.db.users.update_one(
            {'_id': user_id},
            {
                '$set': {
                    'drawings': new_drawings,
                    'lastEquityUpdate': datetime.utcnow()
                }
            }
        )
        
        return result.inserted_id
        
    except Exception as e:
        print(f"Error creating drawing entry: {str(e)}")
        return None


def check_and_create_drawing(mongo, expense_data, user_id):
    """
    Check if an expense should trigger a drawing entry
    
    Triggers drawing if:
    1. Expense is tagged as 'Personal' (entryType == 'personal')
    2. Payment method is 'wallet' (paid from business wallet)
    
    Args:
        mongo: MongoDB instance
        expense_data: Expense document
        user_id: User's ObjectId
    
    Returns:
        ObjectId of drawing entry if created, None otherwise
    """
    try:
        # Check if expense is Personal
        entry_type = expense_data.get('entryType')
        if entry_type != 'personal':
            return None
        
        # Check if paid from wallet
        payment_method = expense_data.get('paymentMethod', '').lower()
        if payment_method != 'wallet':
            return None
        
        # Check if expense has vasTransactionId (wallet spend)
        vas_transaction_id = expense_data.get('vasTransactionId')
        if not vas_transaction_id:
            return None
        
        # Create drawing entry
        amount = expense_data.get('amount', 0)
        description = f"Owner's withdrawal - {expense_data.get('description', 'Personal expense')}"
        expense_id = expense_data.get('_id')
        
        drawing_id = create_drawing_entry(
            mongo=mongo,
            user_id=user_id,
            amount=amount,
            description=description,
            linked_expense_id=expense_id
        )
        
        if drawing_id:
            print(f"✅ Auto-created drawing entry: ₦{amount:,.2f} for expense {expense_id}")
        
        return drawing_id
        
    except Exception as e:
        print(f"Error checking/creating drawing: {str(e)}")
        return None


def void_drawing_entry(mongo, drawing_id):
    """
    Void a drawing entry (when linked expense is voided/refunded)
    
    EQUITY RESTORATION: This function restores the user's equity by reducing
    their drawings balance when a Personal wallet spend is refunded.
    
    Formula: New Drawings Balance = Current Drawings - Refunded Amount
    
    Args:
        mongo: MongoDB instance
        drawing_id: Drawing entry ObjectId
    
    Returns:
        bool: Success status
    """
    try:
        # Get drawing
        drawing = mongo.db.drawings.find_one({'_id': drawing_id})
        if not drawing:
            print(f"WARNING: Drawing entry {drawing_id} not found")
            return False
        
        # Mark as deleted (immutability)
        mongo.db.drawings.update_one(
            {'_id': drawing_id},
            {
                '$set': {
                    'status': 'voided',
                    'isDeleted': True,
                    'deletedAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                }
            }
        )
        
        # 🔍 EQUITY RESTORATION: Update user's total drawings
        user_id = drawing.get('userId')
        amount = drawing.get('amount', 0)
        
        user = mongo.db.users.find_one({'_id': user_id})
        if not user:
            print(f"ERROR: User {user_id} not found for drawing void")
            return False
        
        current_drawings = user.get('drawings', 0)
        new_drawings = max(0, current_drawings - amount)  # Don't go negative
        
        # Log the equity restoration
        print(f"💰 EQUITY RESTORATION:")
        print(f"   User ID: {user_id}")
        print(f"   Drawing Amount: ₦{amount:,.2f}")
        print(f"   Current Drawings: ₦{current_drawings:,.2f}")
        print(f"   New Drawings: ₦{new_drawings:,.2f}")
        print(f"   Equity Impact: +₦{amount:,.2f} (restored)")
        
        mongo.db.users.update_one(
            {'_id': user_id},
            {
                '$set': {
                    'drawings': new_drawings,
                    'lastEquityUpdate': datetime.utcnow()
                }
            }
        )
        
        print(f"✅ Drawing entry voided and equity restored for user {user_id}")
        
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to void drawing entry: {str(e)}")
        return False
