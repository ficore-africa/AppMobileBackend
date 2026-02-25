"""
Loans Management Blueprint

PHASE 2 (Feb 25, 2026): Long-term debt tracking separate from creditors (short-term trade payables)
Handles loan creation, repayments, and balance tracking

This is the "Long-Term Debt Hub" where users track:
- Loans (bank loans, personal loans, equipment financing)
- Loan repayments (principal + interest split)
- Outstanding loan balances
- Optional auto-generation of cash inflow when loan is received

Part of the Opening Balances redesign for complete liability tracking
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def init_loans_blueprint(mongo, token_required):
    """Initialize the loans management blueprint"""
    loans_bp = Blueprint('loans', __name__, url_prefix='/api/loans')
    
    @loans_bp.route('/', methods=['GET'])
    @token_required
    def get_loans(current_user):
        """
        Get all loans for the current user
        
        Returns:
            - List of loans with outstanding balances
            - Total outstanding liability
        """
        try:
            # Get all active loans
            loans_query = {
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': {'$ne': True}
            }
            
            loans = list(mongo.db.loans.find(loans_query).sort('startDate', -1))
            
            # Calculate outstanding balance for each loan
            for loan in loans:
                loan_id = loan['_id']
                
                # Get total principal repaid
                repayments_query = {
                    'userId': current_user['_id'],
                    'loanId': loan_id,
                    'status': 'completed',
                    'isDeleted': {'$ne': True}
                }
                repayments = list(mongo.db.loan_payments.find(repayments_query))
                total_principal_repaid = sum([r.get('principalAmount', 0.0) for r in repayments])
                
                # Calculate outstanding
                loan['outstandingBalance'] = loan['loanAmount'] - total_principal_repaid
                loan['totalPrincipalRepaid'] = total_principal_repaid
                loan['totalInterestPaid'] = sum([r.get('interestAmount', 0.0) for r in repayments])
                loan['numberOfPayments'] = len(repayments)
                
                # Convert ObjectId to string for JSON serialization
                loan['_id'] = str(loan['_id'])
                loan['userId'] = str(loan['userId'])
            
            # Calculate total outstanding liability
            total_outstanding = sum([loan['outstandingBalance'] for loan in loans])
            
            print(f'✓ Fetched {len(loans)} loans for user {current_user["_id"]}, total outstanding: ₦{total_outstanding}')
            
            return jsonify({
                'success': True,
                'data': {
                    'loans': loans,
                    'totalOutstanding': total_outstanding,
                    'count': len(loans)
                }
            }), 200
            
        except Exception as e:
            print(f'❌ Error fetching loans: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to fetch loans'
            }), 500
    
    @loans_bp.route('/', methods=['POST'])
    @token_required
    def create_loan(current_user):
        """
        Create a new loan
        
        Request body:
            - lenderName: str (required) - Name of lender (bank, person, etc.)
            - loanAmount: float (required) - Total loan amount
            - interestRate: float (optional) - Annual interest rate percentage
            - startDate: str (required) - ISO date string
            - maturityDate: str (optional) - ISO date string
            - purpose: str (optional) - Purpose of loan
            - collateral: str (optional) - Collateral description
            - addToCash: bool (optional) - Auto-generate cash inflow? Default: False
        
        Returns:
            - Created loan object
            - Whether cash inflow was created
        """
        try:
            data = request.get_json()
            
            # Validate required fields
            if not data.get('lenderName'):
                return jsonify({
                    'success': False,
                    'message': 'Lender name is required'
                }), 400
            
            if not data.get('loanAmount'):
                return jsonify({
                    'success': False,
                    'message': 'Loan amount is required'
                }), 400
            
            loan_amount = float(data['loanAmount'])
            if loan_amount <= 0:
                return jsonify({
                    'success': False,
                    'message': 'Loan amount must be greater than 0'
                }), 400
            
            if not data.get('startDate'):
                return jsonify({
                    'success': False,
                    'message': 'Start date is required'
                }), 400
            
            # Parse dates
            try:
                start_date = datetime.fromisoformat(data['startDate'].replace('Z', '+00:00'))
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid start date format'
                }), 400
            
            maturity_date = None
            if data.get('maturityDate'):
                try:
                    maturity_date = datetime.fromisoformat(data['maturityDate'].replace('Z', '+00:00'))
                except:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid maturity date format'
                    }), 400
            
            # Create loan entry
            loan = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'lenderName': data['lenderName'],
                'loanAmount': loan_amount,
                'interestRate': float(data.get('interestRate', 0.0)),
                'startDate': start_date,
                'maturityDate': maturity_date,
                'purpose': data.get('purpose', ''),
                'collateral': data.get('collateral', ''),
                'status': 'active',
                'isDeleted': False,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.loans.insert_one(loan)
            
            # Optional: Auto-generate cash inflow
            cash_inflow_created = False
            add_to_cash = data.get('addToCash', False)
            
            if add_to_cash:
                # Create income entry for loan proceeds
                income_entry = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'amount': loan_amount,
                    'source': f'Loan from {data["lenderName"]}',
                    'description': f'🏦 Auto-generated from Loan: {data.get("purpose", "Loan proceeds")}',
                    'category': 'Loan Proceeds',
                    'frequency': 'one_time',
                    'dateReceived': start_date,
                    'isRecurring': False,
                    'sourceType': 'loan_proceeds',  # System-generated marker
                    'loanId': str(loan['_id']),  # Link to loan
                    'isSystemGenerated': True,  # Flag for auto-generated entries
                    'systemGeneratedNote': f'This entry was automatically created when you added the loan "{data["lenderName"]}". Do not manually add this deposit again.',
                    'status': 'active',
                    'isDeleted': False,
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                }
                
                mongo.db.incomes.insert_one(income_entry)
                cash_inflow_created = True
                
                print(f'✓ Auto-generated cash inflow of ₦{loan_amount} for loan {loan["_id"]}')
            
            # Convert ObjectId to string for JSON response
            loan['_id'] = str(loan['_id'])
            loan['userId'] = str(loan['userId'])
            
            print(f'✓ Created loan: {data["lenderName"]} - ₦{loan_amount}, Cash inflow: {cash_inflow_created}')
            
            return jsonify({
                'success': True,
                'message': 'Loan created successfully',
                'data': {
                    'loan': loan,
                    'cashInflowCreated': cash_inflow_created
                }
            }), 201
            
        except Exception as e:
            print(f'❌ Error creating loan: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to create loan'
            }), 500
    
    @loans_bp.route('/<loan_id>', methods=['GET'])
    @token_required
    def get_loan(current_user, loan_id):
        """
        Get a specific loan with payment history
        """
        try:
            # Validate loan_id format
            if not ObjectId.is_valid(loan_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid loan ID format'
                }), 400
            
            # Get loan
            loan = mongo.db.loans.find_one({
                '_id': ObjectId(loan_id),
                'userId': current_user['_id'],
                'isDeleted': {'$ne': True}
            })
            
            if not loan:
                return jsonify({
                    'success': False,
                    'message': 'Loan not found'
                }), 404
            
            # Get payment history
            payments_query = {
                'userId': current_user['_id'],
                'loanId': ObjectId(loan_id),
                'isDeleted': {'$ne': True}
            }
            payments = list(mongo.db.loan_payments.find(payments_query).sort('paymentDate', -1))
            
            # Calculate totals
            total_principal_repaid = sum([p.get('principalAmount', 0.0) for p in payments])
            total_interest_paid = sum([p.get('interestAmount', 0.0) for p in payments])
            outstanding_balance = loan['loanAmount'] - total_principal_repaid
            
            # Convert ObjectIds to strings
            loan['_id'] = str(loan['_id'])
            loan['userId'] = str(loan['userId'])
            loan['outstandingBalance'] = outstanding_balance
            loan['totalPrincipalRepaid'] = total_principal_repaid
            loan['totalInterestPaid'] = total_interest_paid
            
            for payment in payments:
                payment['_id'] = str(payment['_id'])
                payment['userId'] = str(payment['userId'])
                payment['loanId'] = str(payment['loanId'])
            
            return jsonify({
                'success': True,
                'data': {
                    'loan': loan,
                    'payments': payments,
                    'summary': {
                        'loanAmount': loan['loanAmount'],
                        'outstandingBalance': outstanding_balance,
                        'totalPrincipalRepaid': total_principal_repaid,
                        'totalInterestPaid': total_interest_paid,
                        'numberOfPayments': len(payments)
                    }
                }
            }), 200
            
        except Exception as e:
            print(f'❌ Error fetching loan: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to fetch loan'
            }), 500
    
    @loans_bp.route('/<loan_id>/payments', methods=['POST'])
    @token_required
    def create_loan_payment(current_user, loan_id):
        """
        Record a loan payment (manual entry)
        
        Request body:
            - totalAmount: float (required) - Total payment amount
            - principalAmount: float (required) - Principal portion
            - interestAmount: float (required) - Interest portion
            - paymentDate: str (required) - ISO date string
            - notes: str (optional) - Payment notes
        
        Validation:
            - totalAmount must equal principalAmount + interestAmount
            - principalAmount cannot exceed outstanding balance
        """
        try:
            data = request.get_json()
            
            # Validate loan_id format
            if not ObjectId.is_valid(loan_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid loan ID format'
                }), 400
            
            # Get loan
            loan = mongo.db.loans.find_one({
                '_id': ObjectId(loan_id),
                'userId': current_user['_id'],
                'status': 'active',
                'isDeleted': {'$ne': True}
            })
            
            if not loan:
                return jsonify({
                    'success': False,
                    'message': 'Loan not found or already closed'
                }), 404
            
            # Validate required fields
            if not data.get('totalAmount'):
                return jsonify({
                    'success': False,
                    'message': 'Total amount is required'
                }), 400
            
            if not data.get('principalAmount'):
                return jsonify({
                    'success': False,
                    'message': 'Principal amount is required'
                }), 400
            
            if not data.get('interestAmount'):
                return jsonify({
                    'success': False,
                    'message': 'Interest amount is required'
                }), 400
            
            total_amount = float(data['totalAmount'])
            principal_amount = float(data['principalAmount'])
            interest_amount = float(data['interestAmount'])
            
            # Validate split
            if abs(total_amount - (principal_amount + interest_amount)) > 0.01:
                return jsonify({
                    'success': False,
                    'message': 'Total amount must equal principal + interest'
                }), 400
            
            # Calculate outstanding balance
            repayments_query = {
                'userId': current_user['_id'],
                'loanId': ObjectId(loan_id),
                'status': 'completed',
                'isDeleted': {'$ne': True}
            }
            existing_repayments = list(mongo.db.loan_payments.find(repayments_query))
            total_principal_repaid = sum([r.get('principalAmount', 0.0) for r in existing_repayments])
            outstanding_balance = loan['loanAmount'] - total_principal_repaid
            
            # Validate principal doesn't exceed outstanding
            if principal_amount > outstanding_balance + 0.01:  # Allow small rounding
                return jsonify({
                    'success': False,
                    'message': f'Principal amount (₦{principal_amount}) exceeds outstanding balance (₦{outstanding_balance})'
                }), 400
            
            # Parse payment date
            try:
                payment_date = datetime.fromisoformat(data['paymentDate'].replace('Z', '+00:00'))
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid payment date format'
                }), 400
            
            # Create payment record
            payment = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'loanId': ObjectId(loan_id),
                'totalAmount': total_amount,
                'principalAmount': principal_amount,
                'interestAmount': interest_amount,
                'paymentDate': payment_date,
                'notes': data.get('notes', ''),
                'status': 'completed',
                'isDeleted': False,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.loan_payments.insert_one(payment)
            
            # Check if loan is fully paid
            new_outstanding = outstanding_balance - principal_amount
            if new_outstanding < 0.01:  # Fully paid (allow small rounding)
                mongo.db.loans.update_one(
                    {'_id': ObjectId(loan_id)},
                    {
                        '$set': {
                            'status': 'paid_off',
                            'paidOffAt': datetime.utcnow(),
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                print(f'✓ Loan {loan_id} marked as paid off')
            
            # Convert ObjectId to string
            payment['_id'] = str(payment['_id'])
            payment['userId'] = str(payment['userId'])
            payment['loanId'] = str(payment['loanId'])
            
            print(f'✓ Recorded loan payment: ₦{total_amount} (Principal: ₦{principal_amount}, Interest: ₦{interest_amount})')
            
            return jsonify({
                'success': True,
                'message': 'Payment recorded successfully',
                'data': {
                    'payment': payment,
                    'newOutstandingBalance': new_outstanding,
                    'loanPaidOff': new_outstanding < 0.01
                }
            }), 201
            
        except Exception as e:
            print(f'❌ Error recording loan payment: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to record payment'
            }), 500
    
    @loans_bp.route('/<loan_id>', methods=['DELETE'])
    @token_required
    def delete_loan(current_user, loan_id):
        """
        Soft delete a loan (only if no payments have been made)
        """
        try:
            # Validate loan_id format
            if not ObjectId.is_valid(loan_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid loan ID format'
                }), 400
            
            # Get loan
            loan = mongo.db.loans.find_one({
                '_id': ObjectId(loan_id),
                'userId': current_user['_id'],
                'isDeleted': {'$ne': True}
            })
            
            if not loan:
                return jsonify({
                    'success': False,
                    'message': 'Loan not found'
                }), 404
            
            # Check if any payments have been made
            payments_count = mongo.db.loan_payments.count_documents({
                'loanId': ObjectId(loan_id),
                'userId': current_user['_id'],
                'isDeleted': {'$ne': True}
            })
            
            if payments_count > 0:
                return jsonify({
                    'success': False,
                    'message': 'Cannot delete loan with existing payments. Close the loan instead.'
                }), 400
            
            # Soft delete loan
            mongo.db.loans.update_one(
                {'_id': ObjectId(loan_id)},
                {
                    '$set': {
                        'isDeleted': True,
                        'deletedAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # Also soft delete any auto-generated income entry
            mongo.db.incomes.update_many(
                {
                    'userId': current_user['_id'],
                    'loanId': str(loan_id),
                    'sourceType': 'loan_proceeds',
                    'isSystemGenerated': True
                },
                {
                    '$set': {
                        'isDeleted': True,
                        'deletedAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            print(f'✓ Soft deleted loan {loan_id} and associated income entries')
            
            return jsonify({
                'success': True,
                'message': 'Loan deleted successfully'
            }), 200
            
        except Exception as e:
            print(f'❌ Error deleting loan: {str(e)}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': 'Failed to delete loan'
            }), 500
    
    return loans_bp
