"""
COGS Separation - Purchase and Sell Endpoints
Phase 2.1: Inventory purchases create Assets, sales create COGS expenses
"""

from flask import request, jsonify
from datetime import datetime
from bson import ObjectId

def add_cogs_routes(inventory_bp, mongo, token_required):
    """Add COGS purchase and sell routes to existing inventory blueprint"""
    
    @inventory_bp.route('/purchase', methods=['POST'])
    @token_required
    def purchase_inventory(current_user):
        """
        Purchase inventory - Creates Asset (not Expense)
        This is the key COGS separation: buying stock is an asset conversion, not an expense
        """
        try:
            data = request.get_json()
            
            # Validate required fields
            required = ['itemId', 'quantity', 'unitCost']
            for field in required:
                if not data.get(field):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            item_id = ObjectId(data['itemId'])
            quantity = int(data['quantity'])
            unit_cost = float(data['unitCost'])
            
            # Validate item exists
            item = mongo.db.inventory_items.find_one({
                '_id': item_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found'
                }), 404
            
            # Calculate total cost
            total_cost = quantity * unit_cost
            
            # Update item stock and cost price
            new_stock = item.get('currentStock', 0) + quantity
            mongo.db.inventory_items.update_one(
                {'_id': item_id},
                {
                    '$set': {
                        'currentStock': new_stock,
                        'costPrice': unit_cost,  # Update to latest purchase price
                        'lastRestocked': datetime.utcnow(),
                        'status': 'active',
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # Create inventory movement record
            movement = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'itemId': item_id,
                'movementType': 'in',
                'quantity': quantity,
                'unitCost': unit_cost,
                'totalCost': total_cost,
                'reason': 'purchase',
                'reference': data.get('reference', 'Purchase'),
                'stockBefore': item.get('currentStock', 0),
                'stockAfter': new_stock,
                'movementDate': datetime.utcnow(),
                'notes': data.get('notes', f'Purchased {quantity} units at ₦{unit_cost} each'),
                'createdAt': datetime.utcnow()
            }
            mongo.db.inventory_movements.insert_one(movement)
            
            # CRITICAL: NO EXPENSE CREATED
            # This is the key difference - inventory purchase is an asset conversion
            # Cash → Inventory (both are assets)
            
            return jsonify({
                'success': True,
                'message': f'Purchased {quantity} units of {item["itemName"]}',
                'data': {
                    'itemId': str(item_id),
                    'itemName': item['itemName'],
                    'quantity': quantity,
                    'unitCost': unit_cost,
                    'totalCost': total_cost,
                    'newStock': new_stock
                }
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to purchase inventory',
                'error': str(e)
            }), 500
    
    @inventory_bp.route('/sell', methods=['POST'])
    @token_required
    def sell_inventory(current_user):
        """
        Sell inventory - Creates Income (revenue) + COGS Expense
        This separates COGS from Operating Expenses
        """
        try:
            data = request.get_json()
            
            # Validate required fields
            required = ['itemId', 'quantity', 'sellingPrice']
            for field in required:
                if not data.get(field):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            item_id = ObjectId(data['itemId'])
            quantity = int(data['quantity'])
            selling_price = float(data['sellingPrice'])
            
            # Validate item exists
            item = mongo.db.inventory_items.find_one({
                '_id': item_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found'
                }), 404
            
            # Check sufficient stock
            current_stock = item.get('currentStock', 0)
            if current_stock < quantity:
                return jsonify({
                    'success': False,
                    'message': f'Insufficient stock. Available: {current_stock}, Requested: {quantity}'
                }), 400
            
            # Calculate amounts
            revenue = quantity * selling_price
            cogs = quantity * item['costPrice']
            gross_profit = revenue - cogs
            
            # Update item stock
            new_stock = current_stock - quantity
            status = 'active' if new_stock > 0 else 'out_of_stock'
            
            mongo.db.inventory_items.update_one(
                {'_id': item_id},
                {
                    '$set': {
                        'currentStock': new_stock,
                        'status': status,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # Create inventory movement
            movement = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'itemId': item_id,
                'movementType': 'out',
                'quantity': quantity,
                'unitCost': item['costPrice'],
                'totalCost': cogs,
                'reason': 'sale',
                'reference': data.get('reference', 'Sale'),
                'stockBefore': current_stock,
                'stockAfter': new_stock,
                'movementDate': datetime.utcnow(),
                'notes': data.get('notes', f'Sold {quantity} units at ₦{selling_price} each'),
                'createdAt': datetime.utcnow()
            }
            mongo.db.inventory_movements.insert_one(movement)
            
            # 1. Create INCOME entry (Revenue)
            income_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'amount': revenue,
                'source': f'Sale of {item["itemName"]}',
                'description': f'Sold {quantity} units at ₦{selling_price} each',
                'category': 'business',
                'frequency': 'one_time',
                'dateReceived': datetime.utcnow(),
                'isRecurring': False,
                'status': 'active',
                'isDeleted': False,
                'sourceType': 'manual',  # SOURCE TRACKING
                'metadata': {
                    'inventorySale': True,
                    'itemId': str(item_id),
                    'quantity': quantity,
                    'sellingPrice': selling_price
                },
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            mongo.db.incomes.insert_one(income_data)
            
            # 2. Create COGS EXPENSE (separate from Operating Expenses)
            cogs_expense = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'amount': cogs,
                'description': f'COGS - {item["itemName"]}',
                'category': 'Cost of Goods Sold',  # CRITICAL: Separate category
                'date': datetime.utcnow(),
                'tags': ['COGS', 'Inventory', 'Auto-generated'],
                'paymentMethod': 'inventory',
                'status': 'active',
                'isDeleted': False,
                'sourceType': 'manual',  # SOURCE TRACKING
                'metadata': {
                    'inventorySale': True,
                    'itemId': str(item_id),
                    'quantity': quantity,
                    'unitCost': item['costPrice']
                },
                'notes': f'Cost of {quantity} units at ₦{item["costPrice"]} each',
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            mongo.db.expenses.insert_one(cogs_expense)
            
            return jsonify({
                'success': True,
                'message': f'Sold {quantity} units of {item["itemName"]}',
                'data': {
                    'itemId': str(item_id),
                    'itemName': item['itemName'],
                    'quantity': quantity,
                    'sellingPrice': selling_price,
                    'revenue': revenue,
                    'cogs': cogs,
                    'grossProfit': gross_profit,
                    'profitMargin': round((gross_profit / revenue * 100), 2) if revenue > 0 else 0,
                    'newStock': new_stock
                }
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to sell inventory',
                'error': str(e)
            }), 500
