from flask import Blueprint, request, jsonify, render_template_string, make_response, send_file
from datetime import datetime, timedelta
from bson import ObjectId
import uuid
import re
import csv
import io
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import urllib.parse
import logging

def init_debtors_blueprint(mongo, token_required, serialize_doc):
    """Initialize the comprehensive debtors blueprint with all features"""
    debtors_bp = Blueprint('debtors', __name__, url_prefix='/debtors')

    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    def calculate_debt_age(created_date):
        """Calculate debt age in days"""
        if not created_date:
            return 0
        return (datetime.utcnow() - created_date).days

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

    def update_debtor_balance(debtor_id, user_id):
        """Update debtor balance and status based on transactions"""
        try:
            # Get all transactions for this debtor
            transactions = list(mongo.db.debtor_transactions.find({
                'debtorId': debtor_id,
                'userId': user_id,
                'status': 'completed'
            }))
            
            total_debt = 0
            paid_amount = 0
            last_transaction_date = None
            
            for transaction in transactions:
                if transaction['type'] == 'sale':
                    total_debt += transaction['amount']
                elif transaction['type'] == 'payment':
                    paid_amount += transaction['amount']
                elif transaction['type'] == 'adjustment':
                    # Adjustments can be positive or negative
                    total_debt += transaction['amount']
                
                # Track last transaction date
                trans_date = transaction['transactionDate']
                if not last_transaction_date or trans_date > last_transaction_date:
                    last_transaction_date = trans_date
            
            remaining_debt = total_debt - paid_amount
            
            # Get debtor to calculate next payment due
            debtor = mongo.db.debtors.find_one({'_id': debtor_id})
            if not debtor:
                return False
            
            # Calculate next payment due and overdue days
            next_payment_due = calculate_next_payment_due(
                debtor['paymentTerms'], 
                debtor.get('customPaymentDays'),
                last_transaction_date
            )
            
            overdue_days = calculate_overdue_days(next_payment_due)
            debt_age = calculate_debt_age(debtor.get('createdAt'))
            
            # Determine status
            if remaining_debt <= 0:
                status = 'paid'
            elif overdue_days > 0:
                status = 'overdue'
            else:
                status = 'active'
            
            # Update debtor record
            mongo.db.debtors.update_one(
                {'_id': debtor_id},
                {
                    '$set': {
                        'totalDebt': total_debt,
                        'paidAmount': paid_amount,
                        'remainingDebt': remaining_debt,
                        'status': status,
                        'lastPaymentDate': last_transaction_date if paid_amount > 0 else None,
                        'nextPaymentDue': next_payment_due,
                        'overdueDays': overdue_days,
                        'debtAge': debt_age,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating debtor balance: {str(e)}")
            return False

    def create_notification(user_id, debtor_id, notification_type, message, priority='normal'):
        """Create a notification for the user"""
        try:
            notification_data = {
                '_id': ObjectId(),
                'userId': user_id,
                'debtorId': debtor_id,
                'type': notification_type,
                'message': message,
                'priority': priority,
                'isRead': False,
                'createdAt': datetime.utcnow()
            }
            
            mongo.db.debtor_notifications.insert_one(notification_data)
            return True
        except Exception as e:
            logger.error(f"Error creating notification: {str(e)}")
            return False

    def generate_overdue_notifications(user_id):
        """Generate notifications for overdue debts"""
        try:
            overdue_debtors = list(mongo.db.debtors.find({
                'userId': user_id,
                'status': 'overdue',
                'remainingDebt': {'$gt': 0}
            }))
            
            for debtor in overdue_debtors:
                # Check if notification already exists for today
                today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                existing_notification = mongo.db.debtor_notifications.find_one({
                    'userId': user_id,
                    'debtorId': debtor['_id'],
                    'type': 'overdue_reminder',
                    'createdAt': {'$gte': today}
                })
                
                if not existing_notification:
                    message = f"{debtor['customerName']} has an overdue payment of ₦{debtor['remainingDebt']:,.2f} ({debtor['overdueDays']} days overdue)"
                    create_notification(user_id, debtor['_id'], 'overdue_reminder', message, 'high')
            
            return True
        except Exception as e:
            logger.error(f"Error generating overdue notifications: {str(e)}")
            return False

    def sanitize_phone_number(phone):
        """Sanitize and format phone number for WhatsApp"""
        if not phone:
            return None
        
        # Remove all non-digit characters
        phone = re.sub(r'\D', '', phone)
        
        # Add country code if not present (assuming Nigeria +234)
        if phone.startswith('0'):
            phone = '234' + phone[1:]
        elif not phone.startswith('234'):
            phone = '234' + phone
        
        return phone

    def format_whatsapp_message(debtor_name, amount, description, due_date=None):
        """Format WhatsApp message for IOU sharing"""
        message = f"Hello {debtor_name},\n\n"
        message += f"This is a reminder about your outstanding debt:\n"
        message += f"Amount: ₦{amount:,.2f}\n"
        if description:
            message += f"Description: {description}\n"
        if due_date:
            message += f"Due Date: {due_date.strftime('%B %d, %Y')}\n"
        message += f"\nPlease make payment at your earliest convenience.\n"
        message += f"Thank you for your business.\n\n"
        message += f"Powered by FiCore Africa"
        
        return message

    def check_subscription_status(user_id):
        """Check if user has active subscription (placeholder for now)"""
        # TODO: Implement actual subscription checking logic
        # For now, return True to allow all operations
        return True

    def log_reminder_action(user_id, debtor_id, action_type, details=None):
        """Log reminder actions for audit trail"""
        try:
            log_data = {
                '_id': ObjectId(),
                'userId': user_id,
                'debtorId': debtor_id,
                'actionType': action_type,
                'details': details or {},
                'timestamp': datetime.utcnow()
            }
            
            mongo.db.debtor_reminder_logs.insert_one(log_data)
            return True
        except Exception as e:
            logger.error(f"Error logging reminder action: {str(e)}")
            return False

    # ==================== MAIN ROUTES ====================

    @debtors_bp.route('/', methods=['GET'])
    @token_required
    def index(current_user):
        """Main debtors list with debt age calculation and notifications"""
        try:
            # Generate overdue notifications
            generate_overdue_notifications(current_user['_id'])
            
            # Get all debtors sorted by creation date
            debtors = list(mongo.db.debtors.find({
                'userId': current_user['_id']
            }).sort('createdAt', -1))
            
            # Calculate debt ages and update records
            for debtor in debtors:
                debt_age = calculate_debt_age(debtor.get('createdAt'))
                overdue_days = calculate_overdue_days(debtor.get('nextPaymentDue'))
                
                # Update debt age in database
                mongo.db.debtors.update_one(
                    {'_id': debtor['_id']},
                    {'$set': {'debtAge': debt_age, 'overdueDays': overdue_days}}
                )
                
                debtor['debtAge'] = debt_age
                debtor['overdueDays'] = overdue_days
            
            # Serialize debtors
            debtor_list = []
            for debtor in debtors:
                debtor_data = serialize_doc(debtor.copy())
                debtor_data['createdAt'] = debtor_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                debtor_data['updatedAt'] = debtor_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                debtor_data['lastPaymentDate'] = debtor_data.get('lastPaymentDate').isoformat() + 'Z' if debtor_data.get('lastPaymentDate') else None
                debtor_data['nextPaymentDue'] = debtor_data.get('nextPaymentDue').isoformat() + 'Z' if debtor_data.get('nextPaymentDue') else None
                debtor_list.append(debtor_data)
            
            return jsonify({
                'success': True,
                'data': debtor_list,
                'message': 'Debtors retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve debtors',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/manage', methods=['GET'])
    @token_required
    def manage(current_user):
        """Management-focused debtors page with subscription checks"""
        try:
            # Check subscription status
            if not check_subscription_status(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Subscription required for management features',
                    'errors': {'subscription': ['Active subscription required']}
                }), 403
            
            # Get debtors with management statistics
            debtors = list(mongo.db.debtors.find({
                'userId': current_user['_id']
            }).sort('remainingDebt', -1))
            
            # Calculate management statistics
            total_debtors = len(debtors)
            total_outstanding = sum(d.get('remainingDebt', 0) for d in debtors)
            overdue_count = len([d for d in debtors if d.get('status') == 'overdue'])
            
            # Serialize debtors with management info
            debtor_list = []
            for debtor in debtors:
                debtor_data = serialize_doc(debtor.copy())
                debtor_data['createdAt'] = debtor_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                debtor_data['updatedAt'] = debtor_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                debtor_data['lastPaymentDate'] = debtor_data.get('lastPaymentDate').isoformat() + 'Z' if debtor_data.get('lastPaymentDate') else None
                debtor_data['nextPaymentDue'] = debtor_data.get('nextPaymentDue').isoformat() + 'Z' if debtor_data.get('nextPaymentDue') else None
                
                # Add management-specific fields
                debtor_data['riskLevel'] = 'high' if debtor.get('overdueDays', 0) > 60 else 'medium' if debtor.get('overdueDays', 0) > 30 else 'low'
                debtor_data['collectionPriority'] = debtor.get('remainingDebt', 0) * (debtor.get('overdueDays', 0) + 1)
                
                debtor_list.append(debtor_data)
            
            return jsonify({
                'success': True,
                'data': debtor_list,
                'statistics': {
                    'totalDebtors': total_debtors,
                    'totalOutstanding': total_outstanding,
                    'overdueCount': overdue_count
                },
                'message': 'Management data retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve management data',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/view/<debtor_id>', methods=['GET'])
    @token_required
    def view_debtor_api(current_user, debtor_id):
        """API endpoint for detailed debtor data with timezone conversion"""
        try:
            if not ObjectId.is_valid(debtor_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid debtor ID'
                }), 400
            
            # Get debtor with ownership check
            debtor = mongo.db.debtors.find_one({
                '_id': ObjectId(debtor_id),
                'userId': current_user['_id']
            })
            
            if not debtor:
                return jsonify({
                    'success': False,
                    'message': 'Debtor not found'
                }), 404
            
            # Get transactions for this debtor
            transactions = list(mongo.db.debtor_transactions.find({
                'debtorId': ObjectId(debtor_id),
                'userId': current_user['_id']
            }).sort('transactionDate', -1))
            
            # Serialize debtor data with timezone handling
            debtor_data = serialize_doc(debtor.copy())
            debtor_data['createdAt'] = debtor_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            debtor_data['updatedAt'] = debtor_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            debtor_data['lastPaymentDate'] = debtor_data.get('lastPaymentDate').isoformat() + 'Z' if debtor_data.get('lastPaymentDate') else None
            debtor_data['nextPaymentDue'] = debtor_data.get('nextPaymentDue').isoformat() + 'Z' if debtor_data.get('nextPaymentDue') else None
            
            # Serialize transactions
            transaction_list = []
            for transaction in transactions:
                trans_data = serialize_doc(transaction.copy())
                trans_data['transactionDate'] = trans_data.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
                trans_data['createdAt'] = trans_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                trans_data['updatedAt'] = trans_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                transaction_list.append(trans_data)
            
            debtor_data['transactions'] = transaction_list
            
            return jsonify({
                'success': True,
                'data': debtor_data,
                'message': 'Debtor details retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve debtor details',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/view_page/<debtor_id>', methods=['GET'])
    @token_required
    def view_debtor_page(current_user, debtor_id):
        """HTML page with detailed debtor information"""
        try:
            # Check subscription status
            if not check_subscription_status(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Subscription required to view detailed pages',
                    'errors': {'subscription': ['Active subscription required']}
                }), 403
            
            if not ObjectId.is_valid(debtor_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid debtor ID'
                }), 400
            
            # Get debtor with ownership check
            debtor = mongo.db.debtors.find_one({
                '_id': ObjectId(debtor_id),
                'userId': current_user['_id']
            })
            
            if not debtor:
                return jsonify({
                    'success': False,
                    'message': 'Debtor not found'
                }), 404
            
            # Get transactions
            transactions = list(mongo.db.debtor_transactions.find({
                'debtorId': ObjectId(debtor_id),
                'userId': current_user['_id']
            }).sort('transactionDate', -1))
            
            # Create HTML template (simplified for API response)
            debtor_data = serialize_doc(debtor.copy())
            debtor_data['transactions'] = [serialize_doc(t.copy()) for t in transactions]
            
            return jsonify({
                'success': True,
                'data': debtor_data,
                'message': 'Debtor page data retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve debtor page',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== CUSTOMER MANAGEMENT ENDPOINTS ====================

    @debtors_bp.route('/customers', methods=['POST'])
    @token_required
    def add_customer(current_user):
        """Add a new customer"""
        try:
            data = request.get_json()
            
            # Validate required fields
            if not data.get('customerName'):
                return jsonify({
                    'success': False,
                    'message': 'Customer name is required',
                    'errors': {'customerName': ['Customer name is required']}
                }), 400
            
            # Check if customer already exists
            existing_customer = mongo.db.debtors.find_one({
                'userId': current_user['_id'],
                'customerName': data['customerName']
            })
            
            if existing_customer:
                return jsonify({
                    'success': False,
                    'message': 'Customer with this name already exists',
                    'errors': {'customerName': ['Customer already exists']}
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
            
            # Create customer record
            customer_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'customerName': data['customerName'].strip(),
                'customerEmail': data.get('customerEmail', '').strip() or None,
                'customerPhone': data.get('customerPhone', '').strip() or None,
                'customerAddress': data.get('customerAddress', '').strip() or None,
                'totalDebt': 0.0,
                'paidAmount': 0.0,
                'remainingDebt': 0.0,
                'status': 'active',
                'creditLimit': float(data.get('creditLimit', 0)) if data.get('creditLimit') else None,
                'paymentTerms': payment_terms,
                'customPaymentDays': custom_payment_days,
                'lastPaymentDate': None,
                'nextPaymentDue': None,
                'overdueDays': 0,
                'notes': data.get('notes', '').strip() or None,
                'tags': data.get('tags', []) if isinstance(data.get('tags'), list) else [],
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            result = mongo.db.debtors.insert_one(customer_data)
            
            # Return created customer
            created_customer = mongo.db.debtors.find_one({'_id': result.inserted_id})
            customer_response = serialize_doc(created_customer.copy())
            
            # Format dates
            customer_response['createdAt'] = customer_response.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            customer_response['updatedAt'] = customer_response.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': customer_response,
                'message': 'Customer added successfully'
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to add customer',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/customers', methods=['GET'])
    @token_required
    def get_customers(current_user):
        """Get all customers with pagination and filtering"""
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
                    {'customerName': {'$regex': search, '$options': 'i'}},
                    {'customerEmail': {'$regex': search, '$options': 'i'}},
                    {'customerPhone': {'$regex': search, '$options': 'i'}}
                ]
            
            # Get customers with pagination
            skip = (page - 1) * limit
            customers = list(mongo.db.debtors.find(query).sort('customerName', 1).skip(skip).limit(limit))
            total = mongo.db.debtors.count_documents(query)
            
            # Serialize customers
            customer_list = []
            for customer in customers:
                customer_data = serialize_doc(customer.copy())
                customer_data['createdAt'] = customer_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                customer_data['updatedAt'] = customer_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                customer_data['lastPaymentDate'] = customer_data.get('lastPaymentDate').isoformat() + 'Z' if customer_data.get('lastPaymentDate') else None
                customer_data['nextPaymentDue'] = customer_data.get('nextPaymentDue').isoformat() + 'Z' if customer_data.get('nextPaymentDue') else None
                customer_list.append(customer_data)
            
            # For mobile app compatibility, return data directly if no pagination requested
            if page == 1 and limit >= total:
                return jsonify({
                    'success': True,
                    'data': customer_list,
                    'message': 'Customers retrieved successfully'
                })
            else:
                return jsonify({
                    'success': True,
                    'data': customer_list,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit
                    },
                    'message': 'Customers retrieved successfully'
                })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve customers',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/transactions', methods=['POST'])
    @token_required
    def add_transaction(current_user):
        """Add a new debt transaction (sale, payment, or adjustment)"""
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['debtorId', 'type', 'amount', 'description']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            # Validate debtor ID
            if not ObjectId.is_valid(data['debtorId']):
                return jsonify({
                    'success': False,
                    'message': 'Invalid debtor ID'
                }), 400
            
            # Check if debtor exists
            debtor = mongo.db.debtors.find_one({
                '_id': ObjectId(data['debtorId']),
                'userId': current_user['_id']
            })
            
            if not debtor:
                return jsonify({
                    'success': False,
                    'message': 'Customer not found'
                }), 404
            
            # Validate transaction type
            valid_types = ['sale', 'payment', 'adjustment']
            if data['type'] not in valid_types:
                return jsonify({
                    'success': False,
                    'message': 'Invalid transaction type',
                    'errors': {'type': ['Transaction type must be sale, payment, or adjustment']}
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
            
            # Calculate balance before transaction
            balance_before = debtor.get('remainingDebt', 0)
            
            # Calculate balance after transaction
            if data['type'] == 'sale':
                balance_after = balance_before + amount
            elif data['type'] == 'payment':
                balance_after = balance_before - amount
            else:  # adjustment
                balance_after = balance_before + amount  # Adjustments can be positive or negative
            
            # Create transaction record
            transaction_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'debtorId': ObjectId(data['debtorId']),
                'type': data['type'],
                'amount': amount,
                'description': data['description'].strip(),
                'invoiceNumber': data.get('invoiceNumber', '').strip() or None,
                'paymentMethod': data.get('paymentMethod', '').strip() or None,
                'paymentReference': data.get('paymentReference', '').strip() or None,
                'dueDate': None,
                'transactionDate': transaction_date,
                'balanceBefore': balance_before,
                'balanceAfter': balance_after,
                'status': 'completed',
                'notes': data.get('notes', '').strip() or None,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            result = mongo.db.debtor_transactions.insert_one(transaction_data)
            
            # Update debtor balance
            update_debtor_balance(ObjectId(data['debtorId']), current_user['_id'])
            
            # Return created transaction
            created_transaction = mongo.db.debtor_transactions.find_one({'_id': result.inserted_id})
            transaction_response = serialize_doc(created_transaction.copy())
            
            # Format dates
            transaction_response['transactionDate'] = transaction_response.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
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

    @debtors_bp.route('/customers/<customer_id>', methods=['GET'])
    @token_required
    def get_customer(current_user, customer_id):
        """Get a specific customer"""
        try:
            if not ObjectId.is_valid(customer_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid customer ID'
                }), 400
            
            customer = mongo.db.debtors.find_one({
                '_id': ObjectId(customer_id),
                'userId': current_user['_id']
            })
            
            if not customer:
                return jsonify({
                    'success': False,
                    'message': 'Customer not found'
                }), 404
            
            customer_data = serialize_doc(customer.copy())
            customer_data['createdAt'] = customer_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            customer_data['updatedAt'] = customer_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            customer_data['lastPaymentDate'] = customer_data.get('lastPaymentDate').isoformat() + 'Z' if customer_data.get('lastPaymentDate') else None
            customer_data['nextPaymentDue'] = customer_data.get('nextPaymentDue').isoformat() + 'Z' if customer_data.get('nextPaymentDue') else None
            
            return jsonify({
                'success': True,
                'data': customer_data,
                'message': 'Customer retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve customer',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/customers/<customer_id>', methods=['PUT'])
    @token_required
    def update_customer(current_user, customer_id):
        """Update a customer"""
        try:
            if not ObjectId.is_valid(customer_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid customer ID'
                }), 400
            
            data = request.get_json()
            
            # Check if customer exists
            customer = mongo.db.debtors.find_one({
                '_id': ObjectId(customer_id),
                'userId': current_user['_id']
            })
            
            if not customer:
                return jsonify({
                    'success': False,
                    'message': 'Customer not found'
                }), 404
            
            # Validate required fields
            if not data.get('customerName'):
                return jsonify({
                    'success': False,
                    'message': 'Customer name is required',
                    'errors': {'customerName': ['Customer name is required']}
                }), 400
            
            # Check if another customer with same name exists
            existing_customer = mongo.db.debtors.find_one({
                'userId': current_user['_id'],
                'customerName': data['customerName'],
                '_id': {'$ne': ObjectId(customer_id)}
            })
            
            if existing_customer:
                return jsonify({
                    'success': False,
                    'message': 'Customer with this name already exists',
                    'errors': {'customerName': ['Customer already exists']}
                }), 400
            
            # Validate payment terms
            valid_payment_terms = ['30_days', '60_days', '90_days', 'custom']
            payment_terms = data.get('paymentTerms', customer.get('paymentTerms', '30_days'))
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
            
            # Update customer data
            update_data = {
                'customerName': data['customerName'].strip(),
                'customerEmail': data.get('customerEmail', '').strip() or None,
                'customerPhone': data.get('customerPhone', '').strip() or None,
                'customerAddress': data.get('customerAddress', '').strip() or None,
                'creditLimit': float(data.get('creditLimit', 0)) if data.get('creditLimit') else None,
                'paymentTerms': payment_terms,
                'customPaymentDays': custom_payment_days,
                'notes': data.get('notes', '').strip() or None,
                'tags': data.get('tags', []) if isinstance(data.get('tags'), list) else [],
                'updatedAt': datetime.utcnow()
            }
            
            mongo.db.debtors.update_one(
                {'_id': ObjectId(customer_id)},
                {'$set': update_data}
            )
            
            # Return updated customer
            updated_customer = mongo.db.debtors.find_one({'_id': ObjectId(customer_id)})
            customer_response = serialize_doc(updated_customer.copy())
            
            # Format dates
            customer_response['createdAt'] = customer_response.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            customer_response['updatedAt'] = customer_response.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            customer_response['lastPaymentDate'] = customer_response.get('lastPaymentDate').isoformat() + 'Z' if customer_response.get('lastPaymentDate') else None
            customer_response['nextPaymentDue'] = customer_response.get('nextPaymentDue').isoformat() + 'Z' if customer_response.get('nextPaymentDue') else None
            
            return jsonify({
                'success': True,
                'data': customer_response,
                'message': 'Customer updated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update customer',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/customers/<customer_id>', methods=['DELETE'])
    @token_required
    def delete_customer(current_user, customer_id):
        """Delete a customer"""
        try:
            if not ObjectId.is_valid(customer_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid customer ID'
                }), 400
            
            # Check if customer exists
            customer = mongo.db.debtors.find_one({
                '_id': ObjectId(customer_id),
                'userId': current_user['_id']
            })
            
            if not customer:
                return jsonify({
                    'success': False,
                    'message': 'Customer not found'
                }), 404
            
            # Check if customer has outstanding debt
            if customer.get('remainingDebt', 0) > 0:
                return jsonify({
                    'success': False,
                    'message': 'Cannot delete customer with outstanding debt',
                    'errors': {'general': ['Customer has outstanding debt']}
                }), 400
            
            # Delete all transactions for this customer
            mongo.db.debtor_transactions.delete_many({
                'debtorId': ObjectId(customer_id),
                'userId': current_user['_id']
            })
            
            # Delete customer
            mongo.db.debtors.delete_one({'_id': ObjectId(customer_id)})
            
            return jsonify({
                'success': True,
                'message': 'Customer deleted successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to delete customer',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/transactions', methods=['GET'])
    @token_required
    def get_transactions(current_user):
        """Get all transactions with pagination and filtering"""
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 10))
            debtor_id = request.args.get('debtorId')
            transaction_type = request.args.get('type')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            # Build query
            query = {'userId': current_user['_id']}
            
            if debtor_id and ObjectId.is_valid(debtor_id):
                query['debtorId'] = ObjectId(debtor_id)
            
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
            transactions = list(mongo.db.debtor_transactions.find(query)
                              .sort('transactionDate', -1)
                              .skip(skip)
                              .limit(limit))
            total = mongo.db.debtor_transactions.count_documents(query)
            
            # Enrich transactions with customer names
            transaction_list = []
            for transaction in transactions:
                transaction_data = serialize_doc(transaction.copy())
                
                # Get customer name
                customer = mongo.db.debtors.find_one({'_id': transaction['debtorId']})
                transaction_data['customerName'] = customer.get('customerName', 'Unknown Customer') if customer else 'Unknown Customer'
                
                # Format dates
                transaction_data['transactionDate'] = transaction_data.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
                transaction_data['createdAt'] = transaction_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                transaction_data['updatedAt'] = transaction_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                transaction_data['dueDate'] = transaction_data.get('dueDate').isoformat() + 'Z' if transaction_data.get('dueDate') else None
                
                transaction_list.append(transaction_data)
            
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

    @debtors_bp.route('/transactions/<transaction_id>', methods=['GET'])
    @token_required
    def get_transaction(current_user, transaction_id):
        """Get a specific transaction"""
        try:
            if not ObjectId.is_valid(transaction_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid transaction ID'
                }), 400
            
            transaction = mongo.db.debtor_transactions.find_one({
                '_id': ObjectId(transaction_id),
                'userId': current_user['_id']
            })
            
            if not transaction:
                return jsonify({
                    'success': False,
                    'message': 'Transaction not found'
                }), 404
            
            transaction_data = serialize_doc(transaction.copy())
            
            # Get customer name
            customer = mongo.db.debtors.find_one({'_id': transaction['debtorId']})
            transaction_data['customerName'] = customer.get('customerName', 'Unknown Customer') if customer else 'Unknown Customer'
            
            # Format dates
            transaction_data['transactionDate'] = transaction_data.get('transactionDate', datetime.utcnow()).isoformat() + 'Z'
            transaction_data['createdAt'] = transaction_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            transaction_data['updatedAt'] = transaction_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            transaction_data['dueDate'] = transaction_data.get('dueDate').isoformat() + 'Z' if transaction_data.get('dueDate') else None
            
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

    @debtors_bp.route('/transactions/<transaction_id>', methods=['DELETE'])
    @token_required
    def delete_transaction(current_user, transaction_id):
        """Delete a transaction"""
        try:
            if not ObjectId.is_valid(transaction_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid transaction ID'
                }), 400
            
            # Check if transaction exists
            transaction = mongo.db.debtor_transactions.find_one({
                '_id': ObjectId(transaction_id),
                'userId': current_user['_id']
            })
            
            if not transaction:
                return jsonify({
                    'success': False,
                    'message': 'Transaction not found'
                }), 404
            
            # Delete transaction
            mongo.db.debtor_transactions.delete_one({'_id': ObjectId(transaction_id)})
            
            # Update debtor balance
            update_debtor_balance(transaction['debtorId'], current_user['_id'])
            
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

    @debtors_bp.route('/summary', methods=['GET'])
    @token_required
    def get_summary(current_user):
        """Get debt summary statistics"""
        try:
            # Get all debtors
            debtors = list(mongo.db.debtors.find({'userId': current_user['_id']}))
            
            # Calculate summary statistics
            total_customers = len(debtors)
            total_debt = sum(debtor.get('totalDebt', 0) for debtor in debtors)
            total_paid = sum(debtor.get('paidAmount', 0) for debtor in debtors)
            total_outstanding = sum(debtor.get('remainingDebt', 0) for debtor in debtors)
            
            # Count by status
            active_customers = len([d for d in debtors if d.get('status') == 'active'])
            overdue_customers = len([d for d in debtors if d.get('status') == 'overdue'])
            paid_customers = len([d for d in debtors if d.get('status') == 'paid'])
            
            # Calculate overdue amount
            overdue_amount = sum(debtor.get('remainingDebt', 0) for debtor in debtors if debtor.get('status') == 'overdue')
            
            summary_data = {
                'totalCustomers': total_customers,
                'activeCustomers': active_customers,
                'overdueCustomers': overdue_customers,
                'paidCustomers': paid_customers,
                'totalDebt': total_debt,
                'totalPaid': total_paid,
                'totalOutstanding': total_outstanding,
                'overdueAmount': overdue_amount,
                'collectionRate': (total_paid / total_debt * 100) if total_debt > 0 else 0
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

    @debtors_bp.route('/aging-report', methods=['GET'])
    @token_required
    def get_aging_report(current_user):
        """Get aging report for debt analysis"""
        try:
            # Get all active and overdue debtors
            debtors = list(mongo.db.debtors.find({
                'userId': current_user['_id'],
                'status': {'$in': ['active', 'overdue']},
                'remainingDebt': {'$gt': 0}
            }))
            
            # Categorize by aging buckets
            current_bucket = []  # 0-30 days
            bucket_30_60 = []    # 31-60 days
            bucket_60_90 = []    # 61-90 days
            bucket_90_plus = []  # 90+ days
            
            for debtor in debtors:
                overdue_days = debtor.get('overdueDays', 0)
                remaining_debt = debtor.get('remainingDebt', 0)
                
                debtor_data = {
                    'id': str(debtor['_id']),
                    'customerName': debtor.get('customerName', 'Unknown'),
                    'remainingDebt': remaining_debt,
                    'overdueDays': overdue_days,
                    'lastPaymentDate': debtor.get('lastPaymentDate'),
                    'nextPaymentDue': debtor.get('nextPaymentDue')
                }
                
                if overdue_days <= 30:
                    current_bucket.append(debtor_data)
                elif overdue_days <= 60:
                    bucket_30_60.append(debtor_data)
                elif overdue_days <= 90:
                    bucket_60_90.append(debtor_data)
                else:
                    bucket_90_plus.append(debtor_data)
            
            # Calculate totals for each bucket
            current_total = sum(d['remainingDebt'] for d in current_bucket)
            bucket_30_60_total = sum(d['remainingDebt'] for d in bucket_30_60)
            bucket_60_90_total = sum(d['remainingDebt'] for d in bucket_60_90)
            bucket_90_plus_total = sum(d['remainingDebt'] for d in bucket_90_plus)
            
            aging_report = {
                'current': {
                    'customers': current_bucket,
                    'count': len(current_bucket),
                    'total': current_total
                },
                'days_31_60': {
                    'customers': bucket_30_60,
                    'count': len(bucket_30_60),
                    'total': bucket_30_60_total
                },
                'days_61_90': {
                    'customers': bucket_60_90,
                    'count': len(bucket_60_90),
                    'total': bucket_60_90_total
                },
                'days_90_plus': {
                    'customers': bucket_90_plus,
                    'count': len(bucket_90_plus),
                    'total': bucket_90_plus_total
                },
                'grandTotal': current_total + bucket_30_60_total + bucket_60_90_total + bucket_90_plus_total
            }
            
            return jsonify({
                'success': True,
                'data': aging_report,
                'message': 'Aging report retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve aging report',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/overdue', methods=['GET'])
    @token_required
    def get_overdue_customers(current_user):
        """Get all overdue customers"""
        try:
            overdue_customers = list(mongo.db.debtors.find({
                'userId': current_user['_id'],
                'status': 'overdue'
            }).sort('overdueDays', -1))
            
            customer_list = []
            for customer in overdue_customers:
                customer_data = serialize_doc(customer.copy())
                customer_data['createdAt'] = customer_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                customer_data['updatedAt'] = customer_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                customer_data['lastPaymentDate'] = customer_data.get('lastPaymentDate').isoformat() + 'Z' if customer_data.get('lastPaymentDate') else None
                customer_data['nextPaymentDue'] = customer_data.get('nextPaymentDue').isoformat() + 'Z' if customer_data.get('nextPaymentDue') else None
                customer_list.append(customer_data)
            
            return jsonify({
                'success': True,
                'data': customer_list,
                'message': 'Overdue customers retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve overdue customers',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/payments-due', methods=['GET'])
    @token_required
    def get_payments_due(current_user):
        """Get customers with payments due soon"""
        try:
            # Get customers with payments due in the next 7 days
            next_week = datetime.utcnow() + timedelta(days=7)
            
            customers_due = list(mongo.db.debtors.find({
                'userId': current_user['_id'],
                'status': 'active',
                'nextPaymentDue': {
                    '$lte': next_week,
                    '$gte': datetime.utcnow()
                }
            }).sort('nextPaymentDue', 1))
            
            customer_list = []
            for customer in customers_due:
                customer_data = serialize_doc(customer.copy())
                customer_data['createdAt'] = customer_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                customer_data['updatedAt'] = customer_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                customer_data['lastPaymentDate'] = customer_data.get('lastPaymentDate').isoformat() + 'Z' if customer_data.get('lastPaymentDate') else None
                customer_data['nextPaymentDue'] = customer_data.get('nextPaymentDue').isoformat() + 'Z' if customer_data.get('nextPaymentDue') else None
                
                # Calculate days until due
                if customer_data.get('nextPaymentDue'):
                    due_date = datetime.fromisoformat(customer_data['nextPaymentDue'].replace('Z', ''))
                    days_until_due = (due_date - datetime.utcnow()).days
                    customer_data['daysUntilDue'] = days_until_due
                
                customer_list.append(customer_data)
            
            return jsonify({
                'success': True,
                'data': customer_list,
                'message': 'Payments due retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve payments due',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== SHARING AND COMMUNICATION ENDPOINTS ====================

    @debtors_bp.route('/share/<debtor_id>', methods=['GET'])
    @token_required
    def share_iou(current_user, debtor_id):
        """Generate WhatsApp link to share IOU details"""
        try:
            # Check subscription status
            if not check_subscription_status(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Active subscription required for sharing features',
                    'errors': {'subscription': ['Active subscription required']}
                }), 403
            
            if not ObjectId.is_valid(debtor_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid debtor ID'
                }), 400
            
            # Get debtor with ownership check
            debtor = mongo.db.debtors.find_one({
                '_id': ObjectId(debtor_id),
                'userId': current_user['_id']
            })
            
            if not debtor:
                return jsonify({
                    'success': False,
                    'message': 'Debtor not found'
                }), 404
            
            # Sanitize phone number
            phone = sanitize_phone_number(debtor.get('customerPhone'))
            if not phone:
                return jsonify({
                    'success': False,
                    'message': 'Valid phone number required for sharing',
                    'errors': {'phone': ['Customer phone number is required']}
                }), 400
            
            # Format WhatsApp message
            message = format_whatsapp_message(
                debtor.get('customerName', 'Customer'),
                debtor.get('remainingDebt', 0),
                debtor.get('notes', 'Outstanding debt'),
                debtor.get('nextPaymentDue')
            )
            
            # Create WhatsApp URL
            encoded_message = urllib.parse.quote(message)
            whatsapp_url = f"https://wa.me/{phone}?text={encoded_message}"
            
            # Log sharing action
            log_reminder_action(
                current_user['_id'],
                ObjectId(debtor_id),
                'whatsapp_share',
                {'phone': phone, 'amount': debtor.get('remainingDebt', 0)}
            )
            
            return jsonify({
                'success': True,
                'data': {
                    'whatsappUrl': whatsapp_url,
                    'phone': phone,
                    'message': message,
                    'debtorName': debtor.get('customerName'),
                    'amount': debtor.get('remainingDebt', 0)
                },
                'message': 'WhatsApp share link generated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to generate share link',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/send_reminder', methods=['POST'])
    @token_required
    def send_reminder(current_user):
        """Send SMS/WhatsApp reminders or set snooze period"""
        try:
            # Check subscription status
            if not check_subscription_status(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Active subscription required for reminder features',
                    'errors': {'subscription': ['Active subscription required']}
                }), 403
            
            data = request.get_json()
            
            # Validate required fields
            if not data.get('debtorId'):
                return jsonify({
                    'success': False,
                    'message': 'Debtor ID is required',
                    'errors': {'debtorId': ['Debtor ID is required']}
                }), 400
            
            if not ObjectId.is_valid(data['debtorId']):
                return jsonify({
                    'success': False,
                    'message': 'Invalid debtor ID'
                }), 400
            
            # Get debtor
            debtor = mongo.db.debtors.find_one({
                '_id': ObjectId(data['debtorId']),
                'userId': current_user['_id']
            })
            
            if not debtor:
                return jsonify({
                    'success': False,
                    'message': 'Debtor not found'
                }), 404
            
            action_type = data.get('action', 'reminder')
            
            if action_type == 'snooze':
                # Set snooze period (1-30 days)
                snooze_days = data.get('snoozeDays', 7)
                if not isinstance(snooze_days, int) or snooze_days < 1 or snooze_days > 30:
                    return jsonify({
                        'success': False,
                        'message': 'Snooze days must be between 1 and 30',
                        'errors': {'snoozeDays': ['Snooze days must be between 1 and 30']}
                    }), 400
                
                snooze_until = datetime.utcnow() + timedelta(days=snooze_days)
                
                # Update debtor with snooze information
                mongo.db.debtors.update_one(
                    {'_id': ObjectId(data['debtorId'])},
                    {
                        '$set': {
                            'snoozedUntil': snooze_until,
                            'lastSnoozeDate': datetime.utcnow(),
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                
                # Log snooze action
                log_reminder_action(
                    current_user['_id'],
                    ObjectId(data['debtorId']),
                    'snooze',
                    {'snoozeDays': snooze_days, 'snoozeUntil': snooze_until.isoformat()}
                )
                
                return jsonify({
                    'success': True,
                    'data': {
                        'snoozedUntil': snooze_until.isoformat() + 'Z',
                        'snoozeDays': snooze_days
                    },
                    'message': f'Reminders snoozed for {snooze_days} days'
                })
            
            else:
                # Send reminder (SMS/WhatsApp)
                reminder_type = data.get('reminderType', 'whatsapp')
                phone = sanitize_phone_number(debtor.get('customerPhone'))
                
                if not phone:
                    return jsonify({
                        'success': False,
                        'message': 'Valid phone number required for reminders',
                        'errors': {'phone': ['Customer phone number is required']}
                    }), 400
                
                # Create reminder message
                message = format_whatsapp_message(
                    debtor.get('customerName', 'Customer'),
                    debtor.get('remainingDebt', 0),
                    data.get('customMessage', 'Payment reminder'),
                    debtor.get('nextPaymentDue')
                )
                
                # Log reminder action
                log_reminder_action(
                    current_user['_id'],
                    ObjectId(data['debtorId']),
                    f'{reminder_type}_reminder',
                    {
                        'phone': phone,
                        'message': message,
                        'amount': debtor.get('remainingDebt', 0)
                    }
                )
                
                # Update last reminder date
                mongo.db.debtors.update_one(
                    {'_id': ObjectId(data['debtorId'])},
                    {
                        '$set': {
                            'lastReminderDate': datetime.utcnow(),
                            'reminderCount': debtor.get('reminderCount', 0) + 1,
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                
                # For WhatsApp, return the URL for manual sending
                if reminder_type == 'whatsapp':
                    encoded_message = urllib.parse.quote(message)
                    whatsapp_url = f"https://wa.me/{phone}?text={encoded_message}"
                    
                    return jsonify({
                        'success': True,
                        'data': {
                            'reminderType': reminder_type,
                            'whatsappUrl': whatsapp_url,
                            'phone': phone,
                            'message': message
                        },
                        'message': 'WhatsApp reminder link generated successfully'
                    })
                
                # For SMS, return success (actual SMS sending would require SMS service integration)
                return jsonify({
                    'success': True,
                    'data': {
                        'reminderType': reminder_type,
                        'phone': phone,
                        'message': message
                    },
                    'message': 'SMS reminder queued successfully'
                })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to process reminder',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== DOCUMENT GENERATION ENDPOINTS ====================

    @debtors_bp.route('/generate_iou/<debtor_id>', methods=['GET'])
    @token_required
    def generate_iou_pdf(current_user, debtor_id):
        """Generate PDF IOU document"""
        try:
            # Check subscription status
            if not check_subscription_status(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Active subscription required for PDF generation',
                    'errors': {'subscription': ['Active subscription required']}
                }), 403
            
            if not ObjectId.is_valid(debtor_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid debtor ID'
                }), 400
            
            # Get debtor
            debtor = mongo.db.debtors.find_one({
                '_id': ObjectId(debtor_id),
                'userId': current_user['_id']
            })
            
            if not debtor:
                return jsonify({
                    'success': False,
                    'message': 'Debtor not found'
                }), 404
            
            # Create PDF in memory
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []
            
            # Custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                spaceAfter=30,
                alignment=TA_CENTER,
                textColor=colors.darkblue
            )
            
            header_style = ParagraphStyle(
                'CustomHeader',
                parent=styles['Heading2'],
                fontSize=16,
                spaceAfter=12,
                textColor=colors.darkblue
            )
            
            # Header with branding
            story.append(Paragraph("FiCore Africa", title_style))
            story.append(Paragraph("IOU Document", header_style))
            story.append(Spacer(1, 20))
            
            # Debtor information
            debtor_info = [
                ['Customer Name:', debtor.get('customerName', 'N/A')],
                ['Customer Email:', debtor.get('customerEmail', 'N/A')],
                ['Customer Phone:', debtor.get('customerPhone', 'N/A')],
                ['Outstanding Amount:', f"₦{debtor.get('remainingDebt', 0):,.2f}"],
                ['Total Debt:', f"₦{debtor.get('totalDebt', 0):,.2f}"],
                ['Amount Paid:', f"₦{debtor.get('paidAmount', 0):,.2f}"],
                ['Status:', debtor.get('status', 'N/A').title()],
                ['Created Date:', debtor.get('createdAt', datetime.utcnow()).strftime('%B %d, %Y')],
                ['Last Updated:', debtor.get('updatedAt', datetime.utcnow()).strftime('%B %d, %Y')],
            ]
            
            if debtor.get('nextPaymentDue'):
                debtor_info.append(['Next Payment Due:', debtor['nextPaymentDue'].strftime('%B %d, %Y')])
            
            if debtor.get('notes'):
                debtor_info.append(['Description:', debtor['notes']])
            
            # Create table
            table = Table(debtor_info, colWidths=[2*inch, 4*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(table)
            story.append(Spacer(1, 30))
            
            # Footer
            footer_text = f"Generated on {datetime.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')}"
            story.append(Paragraph(footer_text, styles['Normal']))
            story.append(Spacer(1, 20))
            story.append(Paragraph("Powered by FiCore Africa - Financial Management Solutions", styles['Normal']))
            
            # Build PDF
            doc.build(story)
            buffer.seek(0)
            
            # Return PDF as base64 for mobile app
            import base64
            pdf_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            return jsonify({
                'success': True,
                'data': {
                    'pdfData': pdf_data,
                    'filename': f"IOU_{debtor.get('customerName', 'Customer')}_{datetime.utcnow().strftime('%Y%m%d')}.pdf",
                    'debtorName': debtor.get('customerName'),
                    'amount': debtor.get('remainingDebt', 0)
                },
                'message': 'PDF IOU generated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to generate PDF IOU',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/generate_iou_csv/<debtor_id>', methods=['GET'])
    @token_required
    def generate_iou_csv(current_user, debtor_id):
        """Generate CSV IOU file"""
        try:
            # Check subscription status
            if not check_subscription_status(current_user['_id']):
                return jsonify({
                    'success': False,
                    'message': 'Active subscription required for CSV generation',
                    'errors': {'subscription': ['Active subscription required']}
                }), 403
            
            if not ObjectId.is_valid(debtor_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid debtor ID'
                }), 400
            
            # Get debtor
            debtor = mongo.db.debtors.find_one({
                '_id': ObjectId(debtor_id),
                'userId': current_user['_id']
            })
            
            if not debtor:
                return jsonify({
                    'success': False,
                    'message': 'Debtor not found'
                }), 404
            
            # Get transactions
            transactions = list(mongo.db.debtor_transactions.find({
                'debtorId': ObjectId(debtor_id),
                'userId': current_user['_id']
            }).sort('transactionDate', -1))
            
            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['FiCore Africa - IOU Report'])
            writer.writerow(['Generated on:', datetime.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')])
            writer.writerow([])  # Empty row
            
            # Debtor information
            writer.writerow(['DEBTOR INFORMATION'])
            writer.writerow(['Customer Name:', debtor.get('customerName', 'N/A')])
            writer.writerow(['Customer Email:', debtor.get('customerEmail', 'N/A')])
            writer.writerow(['Customer Phone:', debtor.get('customerPhone', 'N/A')])
            writer.writerow(['Outstanding Amount:', f"₦{debtor.get('remainingDebt', 0):,.2f}"])
            writer.writerow(['Total Debt:', f"₦{debtor.get('totalDebt', 0):,.2f}"])
            writer.writerow(['Amount Paid:', f"₦{debtor.get('paidAmount', 0):,.2f}"])
            writer.writerow(['Status:', debtor.get('status', 'N/A').title()])
            writer.writerow(['Created Date:', debtor.get('createdAt', datetime.utcnow()).strftime('%B %d, %Y')])
            
            if debtor.get('nextPaymentDue'):
                writer.writerow(['Next Payment Due:', debtor['nextPaymentDue'].strftime('%B %d, %Y')])
            
            if debtor.get('notes'):
                writer.writerow(['Description:', debtor['notes']])
            
            writer.writerow([])  # Empty row
            
            # Transaction history
            if transactions:
                writer.writerow(['TRANSACTION HISTORY'])
                writer.writerow(['Date', 'Type', 'Amount', 'Description', 'Balance After'])
                
                for transaction in transactions:
                    writer.writerow([
                        transaction.get('transactionDate', datetime.utcnow()).strftime('%Y-%m-%d'),
                        transaction.get('type', 'N/A').title(),
                        f"₦{transaction.get('amount', 0):,.2f}",
                        transaction.get('description', 'N/A'),
                        f"₦{transaction.get('balanceAfter', 0):,.2f}"
                    ])
            
            # Get CSV content
            csv_content = output.getvalue()
            output.close()
            
            # Return CSV as base64 for mobile app
            import base64
            csv_data = base64.b64encode(csv_content.encode('utf-8')).decode('utf-8')
            
            return jsonify({
                'success': True,
                'data': {
                    'csvData': csv_data,
                    'filename': f"IOU_{debtor.get('customerName', 'Customer')}_{datetime.utcnow().strftime('%Y%m%d')}.csv",
                    'debtorName': debtor.get('customerName'),
                    'amount': debtor.get('remainingDebt', 0)
                },
                'message': 'CSV IOU generated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to generate CSV IOU',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== NOTIFICATION ENDPOINTS ====================

    @debtors_bp.route('/notifications/count', methods=['GET'])
    @token_required
    def get_notification_count(current_user):
        """Get count of unread notifications"""
        try:
            unread_count = mongo.db.debtor_notifications.count_documents({
                'userId': current_user['_id'],
                'isRead': False
            })
            
            return jsonify({
                'success': True,
                'data': {'unreadCount': unread_count},
                'message': 'Notification count retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve notification count',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/notifications', methods=['GET'])
    @token_required
    def get_notifications(current_user):
        """Get recent notifications (up to 10)"""
        try:
            notifications = list(mongo.db.debtor_notifications.find({
                'userId': current_user['_id']
            }).sort('createdAt', -1).limit(10))
            
            # Serialize notifications
            notification_list = []
            for notification in notifications:
                notif_data = serialize_doc(notification.copy())
                notif_data['createdAt'] = notif_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                
                # Get debtor name if available
                if notification.get('debtorId'):
                    debtor = mongo.db.debtors.find_one({'_id': notification['debtorId']})
                    notif_data['debtorName'] = debtor.get('customerName') if debtor else 'Unknown Customer'
                
                notification_list.append(notif_data)
            
            return jsonify({
                'success': True,
                'data': notification_list,
                'message': 'Notifications retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve notifications',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/notifications/<notification_id>/read', methods=['POST'])
    @token_required
    def mark_notification_read(current_user, notification_id):
        """Mark notification as read"""
        try:
            if not ObjectId.is_valid(notification_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid notification ID'
                }), 400
            
            # Update notification
            result = mongo.db.debtor_notifications.update_one(
                {
                    '_id': ObjectId(notification_id),
                    'userId': current_user['_id']
                },
                {
                    '$set': {
                        'isRead': True,
                        'readAt': datetime.utcnow()
                    }
                }
            )
            
            if result.matched_count == 0:
                return jsonify({
                    'success': False,
                    'message': 'Notification not found'
                }), 404
            
            return jsonify({
                'success': True,
                'message': 'Notification marked as read'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to mark notification as read',
                'errors': {'general': [str(e)]}
            }), 500

    @debtors_bp.route('/statistics', methods=['GET'])
    @token_required
    def get_debtors_statistics(current_user):
        """Get comprehensive debtors statistics using aggregation"""
        try:
            # Get date range parameters
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            
            # Default to current month if no dates provided
            now = datetime.utcnow()
            if start_date_str:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', ''))
            else:
                start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            if end_date_str:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', ''))
            else:
                end_date = now
            
            # Get comprehensive debtors statistics using aggregation
            statistics_pipeline = [
                {
                    '$match': {
                        'userId': current_user['_id']
                    }
                },
                {
                    '$group': {
                        '_id': None,
                        'totalCustomers': {'$sum': 1},
                        'totalDebt': {'$sum': '$totalDebt'},
                        'totalPaid': {'$sum': '$paidAmount'},
                        'totalOutstanding': {'$sum': '$remainingDebt'},
                        'activeCustomers': {
                            '$sum': {'$cond': [{'$eq': ['$status', 'active']}, 1, 0]}
                        },
                        'overdueCustomers': {
                            '$sum': {'$cond': [{'$eq': ['$status', 'overdue']}, 1, 0]}
                        },
                        'paidCustomers': {
                            '$sum': {'$cond': [{'$eq': ['$status', 'paid']}, 1, 0]}
                        },
                        'overdueAmount': {
                            '$sum': {'$cond': [
                                {'$eq': ['$status', 'overdue']}, 
                                '$remainingDebt', 
                                0
                            ]}
                        },
                        'averageDebt': {'$avg': '$totalDebt'},
                        'maxDebt': {'$max': '$totalDebt'},
                        'minDebt': {'$min': '$totalDebt'}
                    }
                }
            ]
            
            stats_result = list(mongo.db.debtors.aggregate(statistics_pipeline))
            
            if stats_result:
                stats = stats_result[0]
                
                # Calculate additional metrics - handle None values
                total_debt = float(stats.get('totalDebt') or 0)
                total_paid = float(stats.get('totalPaid') or 0)
                collection_rate = (total_paid / total_debt * 100) if total_debt > 0 else 0
                
                statistics_data = {
                    'totalCustomers': int(stats.get('totalCustomers', 0)),
                    'activeCustomers': int(stats.get('activeCustomers', 0)),
                    'overdueCustomers': int(stats.get('overdueCustomers', 0)),
                    'paidCustomers': int(stats.get('paidCustomers', 0)),
                    'totalDebt': total_debt,
                    'totalPaid': total_paid,
                    'totalOutstanding': float(stats.get('totalOutstanding') or 0),
                    'overdueAmount': float(stats.get('overdueAmount') or 0),
                    'averageDebt': float(stats.get('averageDebt') or 0),
                    'maxDebt': float(stats.get('maxDebt') or 0),
                    'minDebt': float(stats.get('minDebt') or 0),
                    'collectionRate': round(collection_rate, 2),
                    'dateRange': {
                        'startDate': start_date.isoformat() + 'Z',
                        'endDate': end_date.isoformat() + 'Z'
                    }
                }
            else:
                statistics_data = {
                    'totalCustomers': 0,
                    'activeCustomers': 0,
                    'overdueCustomers': 0,
                    'paidCustomers': 0,
                    'totalDebt': 0.0,
                    'totalPaid': 0.0,
                    'totalOutstanding': 0.0,
                    'overdueAmount': 0.0,
                    'averageDebt': 0.0,
                    'maxDebt': 0.0,
                    'minDebt': 0.0,
                    'collectionRate': 0.0,
                    'dateRange': {
                        'startDate': start_date.isoformat() + 'Z',
                        'endDate': end_date.isoformat() + 'Z'
                    }
                }
            
            # DISABLED FOR VAS FOCUS
            # print(f"DEBUG DEBTORS STATISTICS: {statistics_data}")
            
            return jsonify({
                'success': True,
                'data': statistics_data,
                'message': 'Debtors statistics retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_debtors_statistics: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve debtors statistics',
                'errors': {'general': [str(e)]}
            }), 500

    return debtors_bp