from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
import uuid

def init_creditors_blueprint(mongo, token_required, serialize_doc):
    """Initialize the creditors blueprint with database and auth decorator"""
    creditors_bp = Blueprint('creditors', __name__, url_prefix='/creditors')

    def calculate_overdue_days(next_payment_due):
        """Calculate overdue days from next payment due date"""
        if not next_payment_due:
            return 0
        
        now = datetime.utcnow()
        if next_payment_due < now:
            return (now - next_payment_due).days
        return 0

    def calculate_next_payment_due(payment_terms, custom_days, last_transaction_date):
        """Calculate next payment due date based on payment terms"""
        if not last_transaction_date:
            return None
            
        if payment_terms == '30_days':
            return last_transaction_date + timedelta(days=30)
        elif payment_terms == '60_days':
            return last_transaction_date + timedelta(days=60)
        elif payment_terms == '90_days':
            return last_transaction_date + timedelta(days=90)
        elif payment_terms == 'custom' and custom_days:
            return last_transaction_date + timedelta(days=custom_days)
        
        return last_transaction_date + timedelta(days=30)  # Default to 30 days

    def update_creditor_balance(creditor_id, user_id):
        """Update creditor balance and status based on transactions"""
        try:
            # Get all transactions for this creditor
            transactions = list(mongo.db.creditor_transactions.find({
                'creditorId': creditor_id,
                'userId': user_id,
                'status': 'completed'
            }))
            
            total_owed = 0
            paid_amount = 0
            last_transaction_date = None
            
            for transaction in transactions:
                if transaction['type'] == 'purchase':
                    total_owed += transaction['amount']
                elif transaction['type'] == 'payment':
                    paid_amount += transaction['amount']
                elif transaction['type'] == 'adjustment':
                    # Adjustments can be positive or negative
                    total_owed += transaction['amount']
                
                # Track last transaction date
                trans_date = transaction['transactionDate']
                if not last_transaction_date or trans_date > last_transaction_date:
                    last_transaction_date = trans_date
            
            remaining_owed = total_owed - paid_amount
            
            # Get creditor to calculate next payment due
            creditor = mongo.db.creditors.find_one({'_id': creditor_id})
            if not creditor:
                return False
            
            # Calculate next payment due and overdue days
            next_payment_due = calculate_next_payment_due(
                creditor['paymentTerms'], 
                creditor.get('customPaymentDays'),
                last_transaction_date
            )
            
            overdue_days = calculate_overdue_days(next_payment_due)
            
            # Determine status
            if remaining_owed <= 0:
                status = 'paid'
            elif overdue_days > 0:
                status = 'overdue'
            else:
                status = 'active'
            
            # 🛡️ ATOMIC UPDATE: Update creditor record with error handling
            update_result = mongo.db.creditors.update_one(
                {'_id': creditor_id},
                {
                    '$set': {
                        'totalOwed': float(total_owed),
                        'paidAmount': float(paid_amount),
                        'remainingOwed': float(remaining_owed),
                        'status': status,
                        'lastPaymentDate': last_transaction_date if paid_amount > 0 else None,
                        'nextPaymentDue': next_payment_due,
                        'overdueDays': int(overdue_days),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # Verify update was successful
            if update_result.modified_count == 0:
                print(f"Warning: No creditor updated for ID {creditor_id}")
                return False
            
            return True
            
        except Exception as e:
            print(f"Error updating creditor balance: {str(e)}")
            return False

    # ==================== MAIN CREDITORS ENDPOINT ====================

    @creditors_bp.route('/', methods=['GET'])
    @token_required
    def get_creditors_overview(current_user):
        """Get creditors overview - main endpoint for /creditors route"""
        try:
            user_id = current_user['_id']
            
            # Get summary data
            vendors = list(mongo.db.creditors.find({'userId': user_id}))
            total_vendors = len(vendors)
            
            # Calculate totals
            total_owed = sum(vendor.get('totalOwed', 0) for vendor in vendors)
            total_outstanding = sum(vendor.get('outstandingBalance', 0) for vendor in vendors)
            
            # Get overdue vendors
            overdue_vendors = [v for v in vendors if v.get('isOverdue', False)]
            overdue_count = len(overdue_vendors)
            overdue_amount = sum(vendor.get('outstandingBalance', 0) for vendor in overdue_vendors)
            
            # Get recent transactions
            recent_transactions = list(mongo.db.creditor_transactions.find({
                'userId': user_id
            }).sort('createdAt', -1).limit(5))
            
            # Serialize transactions
            for transaction in recent_transactions:
                transaction = serialize_doc(transaction)
            
            overview_data = {
                'totalVendors': total_vendors,
                'totalOwed': total_owed,
                'totalOutstanding': total_outstanding,
                'overdueVendors': overdue_count,
                'overdueAmount': overdue_amount,
                'recentTransactions': recent_transactions,
                'summary': {
                    'activeVendors': len([v for v in vendors if v.get('status') == 'active']),
                    'paymentRate': round((total_owed - total_outstanding) / total_owed * 100, 2) if total_owed > 0 else 0
                }
            }
            
            return jsonify({
                'success': True,
                'data': overview_data,
                'message': 'Creditors overview retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f"Error getting creditors overview: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve creditors overview',
                'error': str(e)
            }), 500

    # ==================== VENDOR MANAGEMENT ENDPOINTS ====================

    @creditors_bp.route('/vendors', methods=['POST'])
    @token_required
    def add_vendor(current_user):
        """Add a new vendor"""
        try:
            data = request.get_json()
            
            # Validate required fields
            if not data.get('vendorName'):
                return jsonify({
                    'success': False,
                    'message': 'Vendor name is required',
                    'errors': {'vendorName': ['Vendor name is required']}
                }), 400
            
            # Check if vendor already exists
            existing_vendor = mongo.db.creditors.find_one({
                'userId': current_user['_id'],
                'vendorName': data['vendorName']
            })
            
            if existing_vendor:
                return jsonify({
                    'success': False,
                    'message': 'Vendor with this name already exists',
                    'errors': {'vendorName': ['Vendor already exists']}
                }), 400
            
            # Validate payment terms
            valid_payment_terms = ['30_days', '60_days', '90_days', 'custom']
            payment_terms = data.get('paymentTerms', '30_days')
            if payment_terms not in valid_payment_terms:
                return jsonify({
                    'success': False,
                    'message': 'Invalid payment terms',
                    'errors': {'paymentTerms': ['Invalid payment terms']}
                }), 400
            
            # Validate custom payment days if needed
            custom_payment_days = None
            if payment_terms == 'custom':
                custom_payment_days = data.get('customPaymentDays')
                if not custom_payment_days or custom_payment_days <= 0:
                    return jsonify({
                        'success': False,
                        'message': 'Custom payment days required for custom payment terms',
                        'errors': {'customPaymentDays': ['Custom payment days must be greater than 0']}
                    }), 400
            
            # 🛡️ CREATE VENDOR RECORD: Ensure all required fields are properly set
            vendor_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'vendorName': data['vendorName'].strip(),
                'vendorEmail': data.get('vendorEmail', '').strip() or None,
                'vendorPhone': data.get('vendorPhone', '').strip() or None,
                'vendorAddress': data.get('vendorAddress', '').strip() or None,
                'totalOwed': 0.0,
                'paidAmount': 0.0,
                'remainingOwed': 0.0,
                'status': 'active',
                'paymentTerms': payment_terms,
                'customPaymentDays': custom_payment_days,
                'lastPaymentDate': None,
                'nextPaymentDue': None,
                'overdueDays': 0,
                'creditLimit': float(data.get('creditLimit', 0)) if data.get('creditLimit') else None,
                'notes': data.get('notes', '').strip() or None,
                'tags': data.get('tags', []) if isinstance(data.get('tags'), list) else [],
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            # 🛡️ VALIDATE DATA TYPES: Ensure numeric fields are properly typed
            try:
                if vendor_data['creditLimit'] is not None:
                    vendor_data['creditLimit'] = float(vendor_data['creditLimit'])
                if vendor_data['customPaymentDays'] is not None:
                    vendor_data['customPaymentDays'] = int(vendor_data['customPaymentDays'])
            except (ValueError, TypeError) as e:
                return jsonify({
                    'success': False,
                    'message': 'Invalid numeric values provided',
                    'errors': {'general': [f'Data type validation failed: {str(e)}']}
                }), 400
            
            # 🛡️ ATOMIC INSERT: Insert vendor with error handling
            try:
                result = mongo.db.creditors.insert_one(vendor_data)
                if not result.inserted_id:
                    return jsonify({
                        'success': False,
                        'message': 'Failed to create vendor in database',
                        'errors': {'general': ['Database insertion failed']}
                    }), 500
            except Exception as db_error:
                print(f"Database error during vendor creation: {str(db_error)}")
                return jsonify({
                    'success': False,
                    'message': 'Database error occurred',
                    'errors': {'general': [f'Database operation failed: {str(db_error)}']}
                }), 500
            
            # Return created vendor with proper error handling
            created_vendor = mongo.db.creditors.find_one({'_id': result.inserted_id})
            if not created_vendor:
                return jsonify({
                    'success': False,
                    'message': 'Failed to retrieve created vendor',
                    'errors': {'general': ['Vendor creation verification failed']}
                }), 500
            
            vendor_response = serialize_doc(created_vendor.copy())
            
            # 🛡️ SAFE DATE FORMATTING: Handle dates properly
            vendor_response['createdAt'] = vendor_response.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            vendor_response['updatedAt'] = vendor_response.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            
            # Safe formatting for optional date fields
            last_payment = vendor_response.get('lastPaymentDate')
            vendor_response['lastPaymentDate'] = last_payment.isoformat() + 'Z' if last_payment else None
            
            next_payment = vendor_response.get('nextPaymentDue')
            vendor_response['nextPaymentDue'] = next_payment.isoformat() + 'Z' if next_payment else None
            
            # 🛡️ ENSURE DATA CONSISTENCY: Add required fields with defaults
            vendor_response.setdefault('totalOwed', 0.0)
            vendor_response.setdefault('paidAmount', 0.0)
            vendor_response.setdefault('remainingOwed', 0.0)
            vendor_response.setdefault('status', 'active')
            vendor_response.setdefault('overdueDays', 0)
            vendor_response.setdefault('tags', [])
            
            return jsonify({
                'success': True,
                'data': vendor_response,
                'message': 'Vendor added successfully'
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to add vendor',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/vendors', methods=['GET'])
    @token_required
    def get_vendors(current_user):
        """Get all vendors with pagination and filtering"""
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 10))
            status = request.args.get('status')
            search = request.args.get('search')
            
            # Build query
            query = {'userId': current_user['_id']}
            
            if status:
                query['status'] = status
            
            if search:
                query['$or'] = [
                    {'vendorName': {'$regex': search, '$options': 'i'}},
                    {'vendorEmail': {'$regex': search, '$options': 'i'}},
                    {'vendorPhone': {'$regex': search, '$options': 'i'}}
                ]
            
            # Get vendors with pagination
            skip = (page - 1) * limit
            vendors = list(mongo.db.creditors.find(query).sort('vendorName', 1).skip(skip).limit(limit))
            total = mongo.db.creditors.count_documents(query)
            
            # Serialize vendors with proper error handling
            vendor_list = []
            for vendor in vendors:
                try:
                    vendor_data = serialize_doc(vendor.copy())
                    
                    # 🛡️ SAFE DATE FORMATTING: Handle None values properly
                    vendor_data['createdAt'] = vendor_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                    vendor_data['updatedAt'] = vendor_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                    
                    # Safe date formatting for optional fields
                    last_payment = vendor_data.get('lastPaymentDate')
                    vendor_data['lastPaymentDate'] = last_payment.isoformat() + 'Z' if last_payment else None
                    
                    next_payment = vendor_data.get('nextPaymentDue')
                    vendor_data['nextPaymentDue'] = next_payment.isoformat() + 'Z' if next_payment else None
                    
                    # 🛡️ ENSURE REQUIRED FIELDS: Add defaults for missing fields
                    vendor_data.setdefault('totalOwed', 0.0)
                    vendor_data.setdefault('paidAmount', 0.0)
                    vendor_data.setdefault('remainingOwed', 0.0)
                    vendor_data.setdefault('status', 'active')
                    vendor_data.setdefault('overdueDays', 0)
                    vendor_data.setdefault('tags', [])
                    
                    vendor_list.append(vendor_data)
                except Exception as e:
                    print(f"Error serializing vendor {vendor.get('_id', 'unknown')}: {str(e)}")
                    # Skip problematic vendor but continue processing others
                    continue
            
            return jsonify({
                'success': True,
                'data': vendor_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                },
                'message': 'Vendors retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve vendors',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/vendors/<vendor_id>', methods=['GET'])
    @token_required
    def get_vendor(current_user, vendor_id):
        """Get vendor details"""
        try:
            if not ObjectId.is_valid(vendor_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid vendor ID'
                }), 400
            
            vendor = mongo.db.creditors.find_one({
                '_id': ObjectId(vendor_id),
                'userId': current_user['_id']
            })
            
            if not vendor:
                return jsonify({
                    'success': False,
                    'message': 'Vendor not found'
                }), 404
            
            # Get recent transactions
            transactions = list(mongo.db.creditor_transactions.find({
                'creditorId': ObjectId(vendor_id),
                'userId': current_user['_id']
            }).sort('transactionDate', -1).limit(10))
            
            # Serialize vendor and transactions
            vendor_data = serialize_doc(vendor.copy())
            vendor_data['createdAt'] = vendor_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            vendor_data['updatedAt'] = vendor_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            vendor_data['lastPaymentDate'] = vendor_data.get('lastPaymentDate').isoformat() + 'Z' if vendor_data.get('lastPaymentDate') else None
            vendor_data['nextPaymentDue'] = vendor_data.get('nextPaymentDue').isoformat() + 'Z' if vendor_data.get('nextPaymentDue') else None
            
            transaction_list = []
            for transaction in transactions:
                trans_data = serialize_doc(transaction.copy())
                trans_data['transactionDate'] = trans_data.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
                trans_data['dueDate'] = trans_data.get('dueDate').isoformat() + 'Z' if trans_data.get('dueDate') else None
                trans_data['createdAt'] = trans_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                trans_data['updatedAt'] = trans_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                transaction_list.append(trans_data)
            
            vendor_data['recentTransactions'] = transaction_list
            
            return jsonify({
                'success': True,
                'data': vendor_data,
                'message': 'Vendor retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve vendor',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/vendors/<vendor_id>', methods=['PUT'])
    @token_required
    def update_vendor(current_user, vendor_id):
        """Update vendor details"""
        try:
            if not ObjectId.is_valid(vendor_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid vendor ID'
                }), 400
            
            data = request.get_json()
            
            # Check if vendor exists
            vendor = mongo.db.creditors.find_one({
                '_id': ObjectId(vendor_id),
                'userId': current_user['_id']
            })
            
            if not vendor:
                return jsonify({
                    'success': False,
                    'message': 'Vendor not found'
                }), 404
            
            # Validate vendor name if provided
            if 'vendorName' in data:
                if not data['vendorName']:
                    return jsonify({
                        'success': False,
                        'message': 'Vendor name cannot be empty',
                        'errors': {'vendorName': ['Vendor name is required']}
                    }), 400
                
                # Check for duplicate name (excluding current vendor)
                existing_vendor = mongo.db.creditors.find_one({
                    'userId': current_user['_id'],
                    'vendorName': data['vendorName'],
                    '_id': {'$ne': ObjectId(vendor_id)}
                })
                
                if existing_vendor:
                    return jsonify({
                        'success': False,
                        'message': 'Vendor with this name already exists',
                        'errors': {'vendorName': ['Vendor already exists']}
                    }), 400
            
            # Validate payment terms if provided
            if 'paymentTerms' in data:
                valid_payment_terms = ['30_days', '60_days', '90_days', 'custom']
                if data['paymentTerms'] not in valid_payment_terms:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid payment terms',
                        'errors': {'paymentTerms': ['Invalid payment terms']}
                    }), 400
            
            # Build update data
            update_data = {
                'updatedAt': datetime.utcnow()
            }
            
            # Update allowed fields
            allowed_fields = [
                'vendorName', 'vendorEmail', 'vendorPhone', 'vendorAddress',
                'creditLimit', 'paymentTerms', 'customPaymentDays', 'notes', 'tags'
            ]
            
            for field in allowed_fields:
                if field in data:
                    if field in ['vendorEmail', 'vendorPhone', 'vendorAddress', 'notes']:
                        # Handle optional string fields
                        value = data[field].strip() if data[field] else None
                        update_data[field] = value
                    elif field == 'creditLimit':
                        # Handle optional numeric field
                        update_data[field] = float(data[field]) if data[field] else None
                    elif field == 'customPaymentDays':
                        # Handle custom payment days
                        if data.get('paymentTerms') == 'custom' or vendor.get('paymentTerms') == 'custom':
                            if data[field] and data[field] > 0:
                                update_data[field] = int(data[field])
                            else:
                                update_data[field] = None
                        else:
                            update_data[field] = None
                    elif field == 'tags':
                        # Handle tags array
                        update_data[field] = data[field] if isinstance(data[field], list) else []
                    else:
                        update_data[field] = data[field]
            
            # Update vendor
            mongo.db.creditors.update_one(
                {'_id': ObjectId(vendor_id)},
                {'$set': update_data}
            )
            
            # Get updated vendor with verification
            updated_vendor = mongo.db.creditors.find_one({'_id': ObjectId(vendor_id)})
            if not updated_vendor:
                return jsonify({
                    'success': False,
                    'message': 'Failed to retrieve updated vendor',
                    'errors': {'general': ['Vendor update verification failed']}
                }), 500
            
            vendor_response = serialize_doc(updated_vendor.copy())
            
            # 🛡️ SAFE DATE FORMATTING: Handle dates properly
            vendor_response['createdAt'] = vendor_response.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            vendor_response['updatedAt'] = vendor_response.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            
            # Safe formatting for optional date fields
            last_payment = vendor_response.get('lastPaymentDate')
            vendor_response['lastPaymentDate'] = last_payment.isoformat() + 'Z' if last_payment else None
            
            next_payment = vendor_response.get('nextPaymentDue')
            vendor_response['nextPaymentDue'] = next_payment.isoformat() + 'Z' if next_payment else None
            
            # 🛡️ ENSURE DATA CONSISTENCY: Add required fields with defaults
            vendor_response.setdefault('totalOwed', 0.0)
            vendor_response.setdefault('paidAmount', 0.0)
            vendor_response.setdefault('remainingOwed', 0.0)
            vendor_response.setdefault('status', 'active')
            vendor_response.setdefault('overdueDays', 0)
            vendor_response.setdefault('tags', [])
            
            return jsonify({
                'success': True,
                'data': vendor_response,
                'message': 'Vendor updated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update vendor',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/vendors/<vendor_id>', methods=['DELETE'])
    @token_required
    def delete_vendor(current_user, vendor_id):
        """Delete vendor and all related transactions"""
        try:
            if not ObjectId.is_valid(vendor_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid vendor ID'
                }), 400
            
            # Check if vendor exists
            vendor = mongo.db.creditors.find_one({
                '_id': ObjectId(vendor_id),
                'userId': current_user['_id']
            })
            
            if not vendor:
                return jsonify({
                    'success': False,
                    'message': 'Vendor not found'
                }), 404
            
            # Check if vendor has outstanding debt
            if vendor.get('remainingOwed', 0) > 0:
                return jsonify({
                    'success': False,
                    'message': 'Cannot delete vendor with outstanding payables',
                    'errors': {'general': ['Vendor has outstanding payables']}
                }), 400
            
            # Delete all transactions for this vendor
            mongo.db.creditor_transactions.delete_many({
                'creditorId': ObjectId(vendor_id),
                'userId': current_user['_id']
            })
            
            # Delete vendor
            mongo.db.creditors.delete_one({'_id': ObjectId(vendor_id)})
            
            return jsonify({
                'success': True,
                'message': 'Vendor deleted successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to delete vendor',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== TRANSACTION MANAGEMENT ENDPOINTS ====================

    @creditors_bp.route('/transactions', methods=['POST'])
    @token_required
    def add_transaction(current_user):
        """Add a new creditor transaction (purchase, payment, or adjustment)"""
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['creditorId', 'type', 'amount', 'description']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            # Validate creditor ID
            if not ObjectId.is_valid(data['creditorId']):
                return jsonify({
                    'success': False,
                    'message': 'Invalid creditor ID'
                }), 400
            
            # Check if creditor exists
            creditor = mongo.db.creditors.find_one({
                '_id': ObjectId(data['creditorId']),
                'userId': current_user['_id']
            })
            
            if not creditor:
                return jsonify({
                    'success': False,
                    'message': 'Vendor not found'
                }), 404
            
            # Validate transaction type
            valid_types = ['purchase', 'payment', 'adjustment']
            if data['type'] not in valid_types:
                return jsonify({
                    'success': False,
                    'message': 'Invalid transaction type',
                    'errors': {'type': ['Transaction type must be purchase, payment, or adjustment']}
                }), 400
            
            # Validate amount
            try:
                amount = float(data['amount'])
                if amount <= 0:
                    return jsonify({
                        'success': False,
                        'message': 'Amount must be greater than 0',
                        'errors': {'amount': ['Amount must be greater than 0']}
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False,
                    'message': 'Invalid amount',
                    'errors': {'amount': ['Amount must be a valid number']}
                }), 400
            
            # Parse transaction date
            transaction_date = datetime.utcnow()
            if data.get('transactionDate'):
                try:
                    transaction_date = datetime.fromisoformat(data['transactionDate'].replace('Z', ''))
                except ValueError:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid transaction date format',
                        'errors': {'transactionDate': ['Invalid date format']}
                    }), 400
            
            # Parse due date for purchases
            due_date = None
            if data['type'] == 'purchase' and data.get('dueDate'):
                try:
                    due_date = datetime.fromisoformat(data['dueDate'].replace('Z', ''))
                except ValueError:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid due date format',
                        'errors': {'dueDate': ['Invalid date format']}
                    }), 400
            
            # Calculate balance before transaction
            balance_before = creditor.get('remainingOwed', 0)
            
            # Calculate balance after transaction
            if data['type'] == 'purchase':
                balance_after = balance_before + amount
            elif data['type'] == 'payment':
                balance_after = balance_before - amount
            else:  # adjustment
                balance_after = balance_before + amount  # Adjustments can be positive or negative
            
            # Create transaction record
            transaction_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'creditorId': ObjectId(data['creditorId']),
                'type': data['type'],
                'amount': amount,
                'description': data['description'].strip(),
                'invoiceNumber': data.get('invoiceNumber', '').strip() or None,
                'paymentMethod': data.get('paymentMethod', '').strip() or None,
                'paymentReference': data.get('paymentReference', '').strip() or None,
                'dueDate': due_date,
                'transactionDate': transaction_date,
                'balanceBefore': balance_before,
                'balanceAfter': balance_after,
                'status': 'completed',
                'notes': data.get('notes', '').strip() or None,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            # 🛡️ ATOMIC TRANSACTION: Insert transaction and update balance atomically
            try:
                result = mongo.db.creditor_transactions.insert_one(transaction_data)
                if not result.inserted_id:
                    return jsonify({
                        'success': False,
                        'message': 'Failed to create transaction in database',
                        'errors': {'general': ['Database insertion failed']}
                    }), 500
                
                # Update creditor balance with error handling
                balance_updated = update_creditor_balance(ObjectId(data['creditorId']), current_user['_id'])
                if not balance_updated:
                    # Rollback transaction if balance update fails
                    mongo.db.creditor_transactions.delete_one({'_id': result.inserted_id})
                    return jsonify({
                        'success': False,
                        'message': 'Failed to update creditor balance',
                        'errors': {'general': ['Balance calculation failed']}
                    }), 500
                    
            except Exception as db_error:
                print(f"Database error during transaction creation: {str(db_error)}")
                return jsonify({
                    'success': False,
                    'message': 'Database error occurred',
                    'errors': {'general': [f'Database operation failed: {str(db_error)}']}
                }), 500
            
            # Return created transaction
            created_transaction = mongo.db.creditor_transactions.find_one({'_id': result.inserted_id})
            transaction_response = serialize_doc(created_transaction.copy())
            
            # Format dates
            transaction_response['transactionDate'] = transaction_response.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
            transaction_response['dueDate'] = transaction_response.get('dueDate').isoformat() + 'Z' if transaction_response.get('dueDate') else None
            transaction_response['createdAt'] = transaction_response.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            transaction_response['updatedAt'] = transaction_response.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': transaction_response,
                'message': 'Transaction added successfully'
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to add transaction',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/transactions', methods=['GET'])
    @token_required
    def get_transactions(current_user):
        """Get all creditor transactions with pagination and filtering"""
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 10))
            creditor_id = request.args.get('creditorId')
            transaction_type = request.args.get('type')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            # Build query
            query = {'userId': current_user['_id']}
            
            if creditor_id and ObjectId.is_valid(creditor_id):
                query['creditorId'] = ObjectId(creditor_id)
            
            if transaction_type:
                query['type'] = transaction_type
            
            if start_date or end_date:
                date_query = {}
                if start_date:
                    date_query['$gte'] = datetime.fromisoformat(start_date.replace('Z', ''))
                if end_date:
                    date_query['$lte'] = datetime.fromisoformat(end_date.replace('Z', ''))
                query['transactionDate'] = date_query
            
            # Get transactions with pagination
            skip = (page - 1) * limit
            transactions = list(mongo.db.creditor_transactions.find(query).sort('transactionDate', -1).skip(skip).limit(limit))
            total = mongo.db.creditor_transactions.count_documents(query)
            
            # Get creditor names for transactions
            creditor_ids = list(set([trans['creditorId'] for trans in transactions]))
            creditors = {creditor['_id']: creditor['vendorName'] for creditor in mongo.db.creditors.find({'_id': {'$in': creditor_ids}})}
            
            # Serialize transactions
            transaction_list = []
            for transaction in transactions:
                trans_data = serialize_doc(transaction.copy())
                trans_data['transactionDate'] = trans_data.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
                trans_data['dueDate'] = trans_data.get('dueDate').isoformat() + 'Z' if trans_data.get('dueDate') else None
                trans_data['createdAt'] = trans_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                trans_data['updatedAt'] = trans_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                trans_data['vendorName'] = creditors.get(transaction['creditorId'], 'Unknown')
                transaction_list.append(trans_data)
            
            return jsonify({
                'success': True,
                'data': transaction_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                },
                'message': 'Transactions retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve transactions',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/transactions/<transaction_id>', methods=['GET'])
    @token_required
    def get_transaction(current_user, transaction_id):
        """Get transaction details"""
        try:
            if not ObjectId.is_valid(transaction_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid transaction ID'
                }), 400
            
            transaction = mongo.db.creditor_transactions.find_one({
                '_id': ObjectId(transaction_id),
                'userId': current_user['_id']
            })
            
            if not transaction:
                return jsonify({
                    'success': False,
                    'message': 'Transaction not found'
                }), 404
            
            # Get creditor details
            creditor = mongo.db.creditors.find_one({'_id': transaction['creditorId']})
            
            # Serialize transaction
            transaction_data = serialize_doc(transaction.copy())
            transaction_data['transactionDate'] = transaction_data.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
            transaction_data['dueDate'] = transaction_data.get('dueDate').isoformat() + 'Z' if transaction_data.get('dueDate') else None
            transaction_data['createdAt'] = transaction_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            transaction_data['updatedAt'] = transaction_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            transaction_data['vendorName'] = creditor['vendorName'] if creditor else 'Unknown'
            
            return jsonify({
                'success': True,
                'data': transaction_data,
                'message': 'Transaction retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve transaction',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/transactions/<transaction_id>', methods=['DELETE'])
    @token_required
    def delete_transaction(current_user, transaction_id):
        """Delete a transaction and update creditor balance"""
        try:
            if not ObjectId.is_valid(transaction_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid transaction ID'
                }), 400
            
            # Check if transaction exists
            transaction = mongo.db.creditor_transactions.find_one({
                '_id': ObjectId(transaction_id),
                'userId': current_user['_id']
            })
            
            if not transaction:
                return jsonify({
                    'success': False,
                    'message': 'Transaction not found'
                }), 404
            
            creditor_id = transaction['creditorId']
            
            # Delete transaction
            mongo.db.creditor_transactions.delete_one({'_id': ObjectId(transaction_id)})
            
            # Update creditor balance
            update_creditor_balance(creditor_id, current_user['_id'])
            
            return jsonify({
                'success': True,
                'message': 'Transaction deleted successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to delete transaction',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== REPORTS & ANALYTICS ENDPOINTS ====================

    @creditors_bp.route('/statistics', methods=['GET'])
    @token_required
    def get_creditors_statistics(current_user):
        """Enhanced statistics endpoint with comprehensive metrics"""
        try:
            user_id = current_user['_id']
            
            # MongoDB aggregation pipeline for comprehensive stats
            pipeline = [
                {"$match": {"userId": user_id}},
                {"$group": {
                    "_id": None,
                    "totalCount": {"$sum": 1},
                    "totalOwed": {"$sum": "$totalOwed"},
                    "totalPaid": {"$sum": "$paidAmount"},
                    "totalOutstanding": {"$sum": "$remainingOwed"},
                    "averageOwed": {"$avg": "$remainingOwed"},
                    "maxOwed": {"$max": "$remainingOwed"},
                    "minOwed": {"$min": "$remainingOwed"},
                    "activeVendors": {
                        "$sum": {"$cond": [{"$eq": ["$status", "active"]}, 1, 0]}
                    },
                    "overdueVendors": {
                        "$sum": {"$cond": [{"$eq": ["$status", "overdue"]}, 1, 0]}
                    },
                    "paidVendors": {
                        "$sum": {"$cond": [{"$eq": ["$status", "paid"]}, 1, 0]}
                    },
                    "overdueAmount": {
                        "$sum": {"$cond": [
                            {"$eq": ["$status", "overdue"]}, 
                            "$remainingOwed", 
                            0
                        ]}
                    }
                }}
            ]
            
            result = mongo.db.creditors.aggregate(pipeline)
            statistics = next(result, {})
            
            # Calculate additional metrics
            total_owed = float(statistics.get('totalOwed', 0))
            total_paid = float(statistics.get('totalPaid', 0))
            payment_rate = (total_paid / total_owed * 100) if total_owed > 0 else 0
            
            enhanced_stats = {
                'totalCount': statistics.get('totalCount', 0),
                'totalVendors': statistics.get('totalCount', 0),  # Alias for consistency
                'totalOwed': total_owed,
                'totalPaid': total_paid,
                'totalOutstanding': float(statistics.get('totalOutstanding', 0)),
                'averageOwed': float(statistics.get('averageOwed', 0)),
                'maxOwed': float(statistics.get('maxOwed', 0)),
                'minOwed': float(statistics.get('minOwed', 0)),
                'activeVendors': statistics.get('activeVendors', 0),
                'overdueVendors': statistics.get('overdueVendors', 0),
                'paidVendors': statistics.get('paidVendors', 0),
                'overdueAmount': float(statistics.get('overdueAmount', 0)),
                'paymentRate': round(payment_rate, 2),
                'dateRange': {
                    'startDate': datetime.utcnow().replace(day=1).isoformat() + 'Z',
                    'endDate': datetime.utcnow().isoformat() + 'Z'
                }
            }
            
            return jsonify({
                'success': True,
                'data': enhanced_stats,
                'message': 'Creditors statistics retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve creditors statistics',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/summary', methods=['GET'])
    @token_required
    def get_summary(current_user):
        """Get creditor summary statistics"""
        try:
            # Get all creditors
            creditors = list(mongo.db.creditors.find({'userId': current_user['_id']}))
            
            # Calculate summary statistics
            total_vendors = len(creditors)
            total_owed = sum(creditor.get('totalOwed', 0) for creditor in creditors)
            total_paid = sum(creditor.get('paidAmount', 0) for creditor in creditors)
            total_outstanding = sum(creditor.get('remainingOwed', 0) for creditor in creditors)
            
            # Count by status
            active_vendors = len([c for c in creditors if c.get('status') == 'active'])
            overdue_vendors = len([c for c in creditors if c.get('status') == 'overdue'])
            paid_vendors = len([c for c in creditors if c.get('status') == 'paid'])
            
            # Calculate overdue amount
            overdue_amount = sum(creditor.get('remainingOwed', 0) for creditor in creditors if creditor.get('status') == 'overdue')
            
            # Get recent transactions
            recent_transactions = list(mongo.db.creditor_transactions.find({
                'userId': current_user['_id']
            }).sort('transactionDate', -1).limit(5))
            
            # Get creditor names for recent transactions
            creditor_ids = [trans['creditorId'] for trans in recent_transactions]
            creditor_names = {creditor['_id']: creditor['vendorName'] for creditor in mongo.db.creditors.find({'_id': {'$in': creditor_ids}})}
            
            # Serialize recent transactions
            recent_trans_list = []
            for transaction in recent_transactions:
                trans_data = serialize_doc(transaction.copy())
                trans_data['transactionDate'] = trans_data.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
                trans_data['vendorName'] = creditor_names.get(transaction['creditorId'], 'Unknown')
                recent_trans_list.append(trans_data)
            
            summary_data = {
                'totalVendors': total_vendors,
                'activeVendors': active_vendors,
                'overdueVendors': overdue_vendors,
                'paidVendors': paid_vendors,
                'totalOwed': total_owed,
                'totalPaid': total_paid,
                'totalOutstanding': total_outstanding,
                'overdueAmount': overdue_amount,
                'paymentRate': (total_paid / total_owed * 100) if total_owed > 0 else 0,
                'recentTransactions': recent_trans_list
            }
            
            return jsonify({
                'success': True,
                'data': summary_data,
                'message': 'Summary retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve summary',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/aging-report', methods=['GET'])
    @token_required
    def get_aging_report(current_user):
        """Get aging analysis of outstanding payables"""
        try:
            # Get all creditors with outstanding payables
            creditors = list(mongo.db.creditors.find({
                'userId': current_user['_id'],
                'remainingOwed': {'$gt': 0}
            }))
            
            # Categorize by aging buckets
            aging_buckets = {
                'current': {'count': 0, 'amount': 0, 'vendors': []},      # 0-30 days
                'days_31_60': {'count': 0, 'amount': 0, 'vendors': []},   # 31-60 days
                'days_61_90': {'count': 0, 'amount': 0, 'vendors': []},   # 61-90 days
                'over_90': {'count': 0, 'amount': 0, 'vendors': []}       # 90+ days
            }
            
            for creditor in creditors:
                overdue_days = creditor.get('overdueDays', 0)
                remaining_owed = creditor.get('remainingOwed', 0)
                
                vendor_info = {
                    'id': str(creditor['_id']),
                    'vendorName': creditor['vendorName'],
                    'remainingOwed': remaining_owed,
                    'overdueDays': overdue_days,
                    'nextPaymentDue': creditor.get('nextPaymentDue').isoformat() + 'Z' if creditor.get('nextPaymentDue') else None
                }
                
                if overdue_days <= 30:
                    aging_buckets['current']['count'] += 1
                    aging_buckets['current']['amount'] += remaining_owed
                    aging_buckets['current']['vendors'].append(vendor_info)
                elif overdue_days <= 60:
                    aging_buckets['days_31_60']['count'] += 1
                    aging_buckets['days_31_60']['amount'] += remaining_owed
                    aging_buckets['days_31_60']['vendors'].append(vendor_info)
                elif overdue_days <= 90:
                    aging_buckets['days_61_90']['count'] += 1
                    aging_buckets['days_61_90']['amount'] += remaining_owed
                    aging_buckets['days_61_90']['vendors'].append(vendor_info)
                else:
                    aging_buckets['over_90']['count'] += 1
                    aging_buckets['over_90']['amount'] += remaining_owed
                    aging_buckets['over_90']['vendors'].append(vendor_info)
            
            return jsonify({
                'success': True,
                'data': aging_buckets,
                'message': 'Aging report retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve aging report',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/overdue', methods=['GET'])
    @token_required
    def get_overdue_vendors(current_user):
        """Get vendors with overdue payments"""
        try:
            # Get overdue vendors
            overdue_vendors = list(mongo.db.creditors.find({
                'userId': current_user['_id'],
                'status': 'overdue',
                'remainingOwed': {'$gt': 0}
            }).sort('overdueDays', -1))
            
            # Serialize vendors
            vendor_list = []
            for vendor in overdue_vendors:
                vendor_data = serialize_doc(vendor.copy())
                vendor_data['nextPaymentDue'] = vendor_data.get('nextPaymentDue').isoformat() + 'Z' if vendor_data.get('nextPaymentDue') else None
                vendor_data['lastPaymentDate'] = vendor_data.get('lastPaymentDate').isoformat() + 'Z' if vendor_data.get('lastPaymentDate') else None
                vendor_list.append(vendor_data)
            
            return jsonify({
                'success': True,
                'data': vendor_list,
                'message': 'Overdue vendors retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve overdue vendors',
                'errors': {'general': [str(e)]}
            }), 500

    @creditors_bp.route('/payments-due', methods=['GET'])
    @token_required
    def get_payments_due(current_user):
        """Get vendors with payments due in the next 30 days"""
        try:
            # Calculate date range
            now = datetime.utcnow()
            thirty_days_from_now = now + timedelta(days=30)
            
            # Get vendors with payments due
            vendors_due = list(mongo.db.creditors.find({
                'userId': current_user['_id'],
                'nextPaymentDue': {
                    '$gte': now,
                    '$lte': thirty_days_from_now
                },
                'remainingOwed': {'$gt': 0}
            }).sort('nextPaymentDue', 1))
            
            # Serialize vendors
            vendor_list = []
            for vendor in vendors_due:
                vendor_data = serialize_doc(vendor.copy())
                vendor_data['nextPaymentDue'] = vendor_data.get('nextPaymentDue').isoformat() + 'Z' if vendor_data.get('nextPaymentDue') else None
                vendor_data['lastPaymentDate'] = vendor_data.get('lastPaymentDate').isoformat() + 'Z' if vendor_data.get('lastPaymentDate') else None
                
                # Calculate days until due
                if vendor.get('nextPaymentDue'):
                    days_until_due = (vendor['nextPaymentDue'] - now).days
                    vendor_data['daysUntilDue'] = days_until_due
                
                vendor_list.append(vendor_data)
            
            return jsonify({
                'success': True,
                'data': vendor_list,
                'message': 'Payments due retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve payments due',
                'errors': {'general': [str(e)]}
            }), 500

    return creditors_bp
