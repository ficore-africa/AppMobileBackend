from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId

def init_inventory_blueprint(mongo, token_required, serialize_doc):
    """Initialize the inventory blueprint with database and auth decorator"""
    inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')

    def safe_date_format(date_value, default_to_now=False):
        """Safely format datetime to ISO string, handling None values"""
        if date_value is None:
            return datetime.utcnow().isoformat() + 'Z' if default_to_now else None
        try:
            return date_value.isoformat() + 'Z'
        except (AttributeError, TypeError):
            return datetime.utcnow().isoformat() + 'Z' if default_to_now else None

    def update_item_stock(item_id, user_id):
        """Update item stock based on movements"""
        try:
            # Get all movements for this item
            movements = list(mongo.db.inventory_movements.find({
                'itemId': item_id,
                'userId': user_id
            }).sort('movementDate', 1))
            
            current_stock = 0
            for movement in movements:
                if movement['movementType'] in ['in', 'adjustment']:
                    current_stock += movement['quantity']
                elif movement['movementType'] in ['out']:
                    current_stock -= abs(movement['quantity'])
            
            # Update item stock
            item = mongo.db.inventory_items.find_one({'_id': item_id})
            if not item:
                return False
            
            # Determine status based on stock level
            status = 'active'
            if current_stock <= 0:
                status = 'out_of_stock'
            elif current_stock <= item.get('minimumStock', 0):
                status = 'low_stock'
            
            mongo.db.inventory_items.update_one(
                {'_id': item_id},
                {
                    '$set': {
                        'currentStock': current_stock,
                        'status': status,
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            return True
            
        except Exception as e:
            print(f"Error updating item stock: {str(e)}")
            return False

    def create_cogs_expense(item_id, quantity_sold, user_id):
        """
        Create COGS expense when inventory is sold
        
        IMPORTANT (Phase 2.1 - COGS Separation):
        This should ONLY be called for actual SALES, not for:
        - Damage/spoilage
        - Theft/loss
        - Internal usage
        - Stock adjustments
        
        Only sales generate revenue, so only sales should generate COGS.
        """
        try:
            # Get item details
            item = mongo.db.inventory_items.find_one({'_id': item_id})
            if not item:
                return False
            
            # Calculate COGS
            cogs_amount = item['costPrice'] * quantity_sold
            
            # Create expense record for COGS
            expense_data = {
                '_id': ObjectId(),
                'userId': user_id,
                'amount': cogs_amount,
                'title': f"COGS - {item['itemName']}",
                'description': f"Cost of Goods Sold for {quantity_sold} units of {item['itemName']}",
                'category': 'Cost of Goods Sold',
                'date': datetime.utcnow(),
                'tags': ['COGS', 'Inventory', 'Auto-generated'],
                'paymentMethod': 'inventory',
                'notes': f"Auto-generated COGS expense for inventory sale. Item: {item['itemName']}, Quantity: {quantity_sold}, Unit Cost: {item['costPrice']}",
                'status': 'active',  # CRITICAL: Required for immutability system
                'isDeleted': False,  # CRITICAL: Required for immutability system
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            # Import and apply auto-population for proper title/description
            from ..utils.expense_utils import auto_populate_expense_fields
            expense_data = auto_populate_expense_fields(expense_data)
            
            mongo.db.expenses.insert_one(expense_data)
            return True
            
        except Exception as e:
            print(f"Error creating COGS expense: {str(e)}")
            return False

    # ==================== MAIN INVENTORY ENDPOINT ====================

    @inventory_bp.route('/', methods=['GET'])
    @token_required
    def get_inventory_overview(current_user):
        """Get inventory overview - main endpoint for /inventory route"""
        try:
            user_id = current_user['_id']
            
            # Get all inventory items
            items = list(mongo.db.inventory_items.find({'userId': user_id}))
            
            # Calculate overview statistics
            total_items = len(items)
            total_stock = sum(item.get('currentStock', 0) for item in items)
            total_value = sum(item.get('currentStock', 0) * item.get('unitPrice', 0) for item in items)
            
            # Get low stock items (where current stock <= minimum stock level)
            low_stock_items = [
                item for item in items 
                if item.get('currentStock', 0) <= item.get('minimumStockLevel', 0)
            ]
            low_stock_count = len(low_stock_items)
            
            # Get out of stock items
            out_of_stock_items = [item for item in items if item.get('currentStock', 0) == 0]
            out_of_stock_count = len(out_of_stock_items)
            
            # Get active items
            active_items = [item for item in items if item.get('status') == 'active']
            active_count = len(active_items)
            
            # Get recent movements
            recent_movements = list(mongo.db.inventory_movements.find({
                'userId': user_id
            }).sort('createdAt', -1).limit(5))
            
            # Serialize movements
            for movement in recent_movements:
                movement = serialize_doc(movement)
            
            overview_data = {
                'totalItems': total_items,
                'totalStock': total_stock,
                'totalValue': round(total_value, 2),
                'activeItems': active_count,
                'lowStockItems': low_stock_count,
                'outOfStockItems': out_of_stock_count,
                'recentMovements': recent_movements,
                'summary': {
                    'averageValue': round(total_value / total_items, 2) if total_items > 0 else 0,
                    'stockTurnover': 'N/A',  # Would need historical data to calculate
                    'topItems': []  # Could add top items by value or movement
                }
            }
            
            return jsonify({
                'success': True,
                'data': overview_data,
                'message': 'Inventory overview retrieved successfully'
            }), 200
            
        except Exception as e:
            print(f"Error getting inventory overview: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve inventory overview',
                'error': str(e)
            }), 500

    # ==================== ITEM MANAGEMENT ENDPOINTS ====================

    @inventory_bp.route('/items', methods=['POST'])
    @token_required
    def add_item(current_user):
        """Add a new inventory item"""
        try:
            data = request.get_json()
            
            # Validate required fields with proper null/empty checks
            required_fields = ['itemName', 'category', 'costPrice', 'sellingPrice', 'unit']
            for field in required_fields:
                value = data.get(field)
                if value is None or (isinstance(value, str) and value.strip() == ''):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            # Check if item already exists
            existing_item = mongo.db.inventory_items.find_one({
                'userId': current_user['_id'],
                'itemName': data['itemName']
            })
            
            if existing_item:
                return jsonify({
                    'success': False,
                    'message': 'Item with this name already exists',
                    'errors': {'itemName': ['Item already exists']}
                }), 400
            
            # Validate numeric fields with proper error handling
            try:
                cost_price = float(data.get('costPrice', 0))
                selling_price = float(data.get('sellingPrice', 0))
                if cost_price < 0 or selling_price < 0:
                    return jsonify({
                        'success': False,
                        'message': 'Prices must be non-negative',
                        'errors': {'price': ['Prices must be non-negative']}
                    }), 400
            except (ValueError, TypeError) as e:
                return jsonify({
                    'success': False,
                    'message': 'Invalid price format',
                    'errors': {'price': ['Prices must be valid numbers']}
                }), 400
            
            # Validate stock levels with proper defaults
            try:
                current_stock = int(data.get('currentStock', 0))
                minimum_stock = int(data.get('minimumStock', 0))
                maximum_stock = int(data.get('maximumStock')) if data.get('maximumStock') is not None else None
                
                if current_stock < 0 or minimum_stock < 0:
                    return jsonify({
                        'success': False,
                        'message': 'Stock levels must be non-negative',
                        'errors': {'stock': ['Stock levels must be non-negative']}
                    }), 400
            except (ValueError, TypeError) as e:
                return jsonify({
                    'success': False,
                    'message': 'Invalid stock level format',
                    'errors': {'stock': ['Stock levels must be valid numbers']}
                }), 400
            
            # Determine initial status
            status = 'active'
            if current_stock <= 0:
                status = 'out_of_stock'
            elif current_stock <= minimum_stock:
                status = 'low_stock'
            
            # Create item record
            item_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'itemName': data['itemName'].strip(),
                'itemCode': data.get('itemCode', '').strip() or None,
                'description': data.get('description', '').strip() or None,
                'category': data['category'].strip(),
                'costPrice': cost_price,
                'sellingPrice': selling_price,
                'currentStock': current_stock,
                'minimumStock': minimum_stock,
                'maximumStock': maximum_stock,
                'unit': data['unit'].strip(),
                'supplier': data.get('supplier', '').strip() or None,
                'location': data.get('location', '').strip() or None,
                'status': status,
                'lastRestocked': datetime.utcnow() if current_stock > 0 else None,
                'expiryDate': None,
                'tags': data.get('tags', []) if isinstance(data.get('tags'), list) else [],
                'images': data.get('images', []) if isinstance(data.get('images'), list) else [],
                'notes': data.get('notes', '').strip() or None,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            result = mongo.db.inventory_items.insert_one(item_data)
            
            # Create initial stock movement if stock > 0
            if current_stock > 0:
                movement_data = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'itemId': result.inserted_id,
                    'movementType': 'in',
                    'quantity': current_stock,
                    'unitCost': cost_price,
                    'totalCost': cost_price * current_stock,
                    'reason': 'initial_stock',
                    'reference': 'Initial Stock Entry',
                    'stockBefore': 0,
                    'stockAfter': current_stock,
                    'movementDate': datetime.utcnow(),
                    'notes': 'Initial stock entry when item was created',
                    'createdAt': datetime.utcnow()
                }
                mongo.db.inventory_movements.insert_one(movement_data)
            
            # Return created item
            created_item = mongo.db.inventory_items.find_one({'_id': result.inserted_id})
            item_response = serialize_doc(created_item.copy())
            
            # Format dates - Fix date serialization bug
            item_response['createdAt'] = safe_date_format(item_response.get('createdAt'), default_to_now=True)
            item_response['updatedAt'] = safe_date_format(item_response.get('updatedAt'), default_to_now=True)
            item_response['lastRestocked'] = safe_date_format(item_response.get('lastRestocked'))
            
            return jsonify({
                'success': True,
                'data': item_response,
                'message': 'Item added successfully'
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to add item',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/items', methods=['GET'])
    @token_required
    def get_items(current_user):
        """Get all inventory items with pagination and filtering"""
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 10))
            category = request.args.get('category')
            status = request.args.get('status')
            search = request.args.get('search')
            low_stock_only = request.args.get('lowStockOnly', '').lower() == 'true'
            
            # Build query
            query = {'userId': current_user['_id']}
            
            if category:
                query['category'] = category
            
            if status:
                query['status'] = status
            
            if low_stock_only:
                query['$expr'] = {'$lte': ['$currentStock', '$minimumStock']}
            
            if search:
                query['$or'] = [
                    {'itemName': {'$regex': search, '$options': 'i'}},
                    {'itemCode': {'$regex': search, '$options': 'i'}},
                    {'description': {'$regex': search, '$options': 'i'}},
                    {'supplier': {'$regex': search, '$options': 'i'}}
                ]
            
            # Get items with pagination
            skip = (page - 1) * limit
            items = list(mongo.db.inventory_items.find(query).sort('itemName', 1).skip(skip).limit(limit))
            total = mongo.db.inventory_items.count_documents(query)
            
            # Serialize items
            item_list = []
            for item in items:
                item_data = serialize_doc(item.copy())
                item_data['createdAt'] = safe_date_format(item_data.get('createdAt'), default_to_now=True)
                item_data['updatedAt'] = safe_date_format(item_data.get('updatedAt'), default_to_now=True)
                item_data['lastRestocked'] = safe_date_format(item_data.get('lastRestocked'))
                
                # Calculate profit margin
                if item['sellingPrice'] > 0:
                    profit_margin = ((item['sellingPrice'] - item['costPrice']) / item['sellingPrice']) * 100
                    item_data['profitMargin'] = round(profit_margin, 2)
                else:
                    item_data['profitMargin'] = 0
                
                # Check if item is low stock
                item_data['isLowStock'] = item['currentStock'] <= item['minimumStock']
                
                item_list.append(item_data)
            
            return jsonify({
                'success': True,
                'data': item_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                },
                'message': 'Items retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve items',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/statistics', methods=['GET'])
    @token_required
    def get_inventory_statistics(current_user):
        """Enhanced statistics endpoint with comprehensive metrics"""
        try:
            user_id = current_user['_id']
            
            # MongoDB aggregation pipeline for comprehensive stats
            pipeline = [
                {"$match": {"userId": user_id}},
                {"$group": {
                    "_id": None,
                    "totalCount": {"$sum": 1},
                    "totalItems": {"$sum": 1},  # Alias for consistency
                    "totalValue": {"$sum": {"$multiply": ["$currentStock", "$costPrice"]}},
                    "totalStock": {"$sum": "$currentStock"},
                    "averageValue": {"$avg": {"$multiply": ["$currentStock", "$costPrice"]}},
                    "maxValue": {"$max": {"$multiply": ["$currentStock", "$costPrice"]}},
                    "minValue": {"$min": {"$multiply": ["$currentStock", "$costPrice"]}},
                    "activeItems": {
                        "$sum": {"$cond": [{"$eq": ["$status", "active"]}, 1, 0]}
                    },
                    "lowStockItems": {
                        "$sum": {"$cond": [{"$lte": ["$currentStock", "$minimumStock"]}, 1, 0]}
                    },
                    "outOfStockItems": {
                        "$sum": {"$cond": [{"$lte": ["$currentStock", 0]}, 1, 0]}
                    },
                    "totalCostValue": {"$sum": {"$multiply": ["$currentStock", "$costPrice"]}},
                    "totalSellingValue": {"$sum": {"$multiply": ["$currentStock", "$sellingPrice"]}},
                }}
            ]
            
            result = mongo.db.inventory_items.aggregate(pipeline)
            statistics = next(result, {})
            
            # Calculate additional metrics
            total_cost_value = float(statistics.get('totalCostValue', 0))
            total_selling_value = float(statistics.get('totalSellingValue', 0))
            potential_profit = total_selling_value - total_cost_value
            profit_margin = (potential_profit / total_selling_value * 100) if total_selling_value > 0 else 0
            
            enhanced_stats = {
                'totalCount': statistics.get('totalCount', 0),
                'totalItems': statistics.get('totalItems', 0),  # Alias for consistency
                'totalValue': float(statistics.get('totalValue', 0)),
                'totalStock': statistics.get('totalStock', 0),
                'averageValue': float(statistics.get('averageValue', 0)),
                'maxValue': float(statistics.get('maxValue', 0)),
                'minValue': float(statistics.get('minValue', 0)),
                'activeItems': statistics.get('activeItems', 0),
                'lowStockItems': statistics.get('lowStockItems', 0),
                'outOfStockItems': statistics.get('outOfStockItems', 0),
                'totalCostValue': total_cost_value,
                'totalSellingValue': total_selling_value,
                'potentialProfit': potential_profit,
                'profitMargin': round(profit_margin, 2),
                'dateRange': {
                    'startDate': datetime.utcnow().replace(day=1).isoformat() + 'Z',
                    'endDate': datetime.utcnow().isoformat() + 'Z'
                }
            }
            
            return jsonify({
                'success': True,
                'data': enhanced_stats,
                'message': 'Inventory statistics retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve inventory statistics',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/summary', methods=['GET'])
    @token_required
    def get_summary(current_user):
        """Get inventory summary statistics"""
        try:
            # Get all items
            items = list(mongo.db.inventory_items.find({'userId': current_user['_id']}))
            
            # Calculate summary statistics
            total_items = len(items)
            total_value = sum(item['currentStock'] * item['costPrice'] for item in items)
            low_stock_items = len([item for item in items if item['currentStock'] <= item['minimumStock']])
            out_of_stock_items = len([item for item in items if item['currentStock'] <= 0])
            
            # Count by status
            active_items = len([item for item in items if item.get('status') == 'active'])
            
            # Calculate total stock quantity
            total_stock = sum(item['currentStock'] for item in items)
            
            summary_data = {
                'totalItems': total_items,
                'activeItems': active_items,
                'lowStockItems': low_stock_items,
                'outOfStockItems': out_of_stock_items,
                'totalValue': total_value,
                'totalStock': total_stock
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

    # ==================== INDIVIDUAL ITEM CRUD OPERATIONS ====================

    @inventory_bp.route('/items/<item_id>', methods=['GET'])
    @token_required
    def get_item(current_user, item_id):
        """Get specific item details"""
        try:
            # Validate ObjectId
            try:
                item_object_id = ObjectId(item_id)
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid item ID format',
                    'errors': {'itemId': ['Invalid item ID format']}
                }), 400
            
            # Find item
            item = mongo.db.inventory_items.find_one({
                '_id': item_object_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found',
                    'errors': {'itemId': ['Item not found']}
                }), 404
            
            # Serialize item
            item_data = serialize_doc(item.copy())
            item_data['createdAt'] = safe_date_format(item_data.get('createdAt'), default_to_now=True)
            item_data['updatedAt'] = safe_date_format(item_data.get('updatedAt'), default_to_now=True)
            item_data['lastRestocked'] = safe_date_format(item_data.get('lastRestocked'))
            
            # Calculate profit margin
            if item['sellingPrice'] > 0:
                profit_margin = ((item['sellingPrice'] - item['costPrice']) / item['sellingPrice']) * 100
                item_data['profitMargin'] = round(profit_margin, 2)
            else:
                item_data['profitMargin'] = 0
            
            # Check if item is low stock
            item_data['isLowStock'] = item['currentStock'] <= item['minimumStock']
            
            # Get recent movements for this item
            recent_movements = list(mongo.db.inventory_movements.find({
                'itemId': item_object_id,
                'userId': current_user['_id']
            }).sort('movementDate', -1).limit(5))
            
            movements_data = []
            for movement in recent_movements:
                movement_data = serialize_doc(movement.copy())
                movement_data['movementDate'] = safe_date_format(movement_data.get('movementDate'), default_to_now=True)
                movement_data['createdAt'] = safe_date_format(movement_data.get('createdAt'), default_to_now=True)
                movements_data.append(movement_data)
            
            item_data['recentMovements'] = movements_data
            
            return jsonify({
                'success': True,
                'data': item_data,
                'message': 'Item retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve item',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/items/<item_id>', methods=['PUT'])
    @token_required
    def update_item(current_user, item_id):
        """Update specific item"""
        try:
            # Validate ObjectId
            try:
                item_object_id = ObjectId(item_id)
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid item ID format',
                    'errors': {'itemId': ['Invalid item ID format']}
                }), 400
            
            # Check if item exists
            existing_item = mongo.db.inventory_items.find_one({
                '_id': item_object_id,
                'userId': current_user['_id']
            })
            
            if not existing_item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found',
                    'errors': {'itemId': ['Item not found']}
                }), 404
            
            data = request.get_json()
            
            # Validate required fields if provided
            if 'itemName' in data and not data['itemName']:
                return jsonify({
                    'success': False,
                    'message': 'Item name cannot be empty',
                    'errors': {'itemName': ['Item name is required']}
                }), 400
            
            # Check for duplicate name if name is being changed
            if 'itemName' in data and data['itemName'] != existing_item['itemName']:
                duplicate_item = mongo.db.inventory_items.find_one({
                    'userId': current_user['_id'],
                    'itemName': data['itemName'],
                    '_id': {'$ne': item_object_id}
                })
                
                if duplicate_item:
                    return jsonify({
                        'success': False,
                        'message': 'Item with this name already exists',
                        'errors': {'itemName': ['Item name already exists']}
                    }), 400
            
            # Validate numeric fields
            update_data = {}
            
            if 'costPrice' in data:
                try:
                    cost_price = float(data['costPrice'])
                    if cost_price < 0:
                        return jsonify({
                            'success': False,
                            'message': 'Cost price must be non-negative',
                            'errors': {'costPrice': ['Cost price must be non-negative']}
                        }), 400
                    update_data['costPrice'] = cost_price
                except (ValueError, TypeError):
                    return jsonify({
                        'success': False,
                        'message': 'Invalid cost price format',
                        'errors': {'costPrice': ['Cost price must be a valid number']}
                    }), 400
            
            if 'sellingPrice' in data:
                try:
                    selling_price = float(data['sellingPrice'])
                    if selling_price < 0:
                        return jsonify({
                            'success': False,
                            'message': 'Selling price must be non-negative',
                            'errors': {'sellingPrice': ['Selling price must be non-negative']}
                        }), 400
                    update_data['sellingPrice'] = selling_price
                except (ValueError, TypeError):
                    return jsonify({
                        'success': False,
                        'message': 'Invalid selling price format',
                        'errors': {'sellingPrice': ['Selling price must be a valid number']}
                    }), 400
            
            # Validate stock levels
            if 'minimumStock' in data:
                try:
                    minimum_stock = int(data['minimumStock'])
                    if minimum_stock < 0:
                        return jsonify({
                            'success': False,
                            'message': 'Minimum stock must be non-negative',
                            'errors': {'minimumStock': ['Minimum stock must be non-negative']}
                        }), 400
                    update_data['minimumStock'] = minimum_stock
                except (ValueError, TypeError):
                    return jsonify({
                        'success': False,
                        'message': 'Invalid minimum stock format',
                        'errors': {'minimumStock': ['Minimum stock must be a valid number']}
                    }), 400
            
            if 'maximumStock' in data:
                if data['maximumStock'] is not None:
                    try:
                        maximum_stock = int(data['maximumStock'])
                        if maximum_stock < 0:
                            return jsonify({
                                'success': False,
                                'message': 'Maximum stock must be non-negative',
                                'errors': {'maximumStock': ['Maximum stock must be non-negative']}
                            }), 400
                        update_data['maximumStock'] = maximum_stock
                    except (ValueError, TypeError):
                        return jsonify({
                            'success': False,
                            'message': 'Invalid maximum stock format',
                            'errors': {'maximumStock': ['Maximum stock must be a valid number']}
                        }), 400
                else:
                    update_data['maximumStock'] = None
            
            # Update other fields
            updatable_fields = ['itemName', 'itemCode', 'description', 'category', 'unit', 'supplier', 'location', 'tags', 'images', 'notes']
            for field in updatable_fields:
                if field in data:
                    if field in ['itemName', 'itemCode', 'description', 'category', 'unit', 'supplier', 'location', 'notes']:
                        update_data[field] = data[field].strip() if data[field] else None
                    else:
                        update_data[field] = data[field] if isinstance(data[field], list) else []
            
            # Update timestamp
            update_data['updatedAt'] = datetime.utcnow()
            
            # Update item
            mongo.db.inventory_items.update_one(
                {'_id': item_object_id},
                {'$set': update_data}
            )
            
            # Recalculate status if minimum stock changed
            if 'minimumStock' in update_data:
                update_item_stock(item_object_id, current_user['_id'])
            
            # Get updated item
            updated_item = mongo.db.inventory_items.find_one({'_id': item_object_id})
            item_response = serialize_doc(updated_item.copy())
            
            # Format dates - Fix date serialization bug
            item_response['createdAt'] = safe_date_format(item_response.get('createdAt'), default_to_now=True)
            item_response['updatedAt'] = safe_date_format(item_response.get('updatedAt'), default_to_now=True)
            item_response['lastRestocked'] = safe_date_format(item_response.get('lastRestocked'))
            
            return jsonify({
                'success': True,
                'data': item_response,
                'message': 'Item updated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update item',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/items/<item_id>', methods=['DELETE'])
    @token_required
    def delete_item(current_user, item_id):
        """Delete specific item with safety checks"""
        try:
            # Validate ObjectId
            try:
                item_object_id = ObjectId(item_id)
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid item ID format',
                    'errors': {'itemId': ['Invalid item ID format']}
                }), 400
            
            # Check if item exists
            item = mongo.db.inventory_items.find_one({
                '_id': item_object_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found',
                    'errors': {'itemId': ['Item not found']}
                }), 404
            
            # Check if item has movements (safety check)
            movements_count = mongo.db.inventory_movements.count_documents({
                'itemId': item_object_id,
                'userId': current_user['_id']
            })
            
            force_delete = request.args.get('force', '').lower() == 'true'
            
            if movements_count > 0 and not force_delete:
                return jsonify({
                    'success': False,
                    'message': 'Cannot delete item with existing movements. Use force=true to override.',
                    'errors': {'movements': ['Item has existing movements']},
                    'data': {'movementsCount': movements_count}
                }), 400
            
            # Delete movements if force delete
            if force_delete and movements_count > 0:
                mongo.db.inventory_movements.delete_many({
                    'itemId': item_object_id,
                    'userId': current_user['_id']
                })
            
            # Delete item
            mongo.db.inventory_items.delete_one({'_id': item_object_id})
            
            return jsonify({
                'success': True,
                'message': 'Item deleted successfully',
                'data': {'deletedMovements': movements_count if force_delete else 0}
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to delete item',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== STOCK MOVEMENT MANAGEMENT ====================

    @inventory_bp.route('/movements', methods=['POST'])
    @token_required
    def record_movement(current_user):
        """Record stock movement (in/out/adjustment)"""
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['itemId', 'movementType', 'quantity']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            # Validate ObjectId
            try:
                item_object_id = ObjectId(data['itemId'])
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid item ID format',
                    'errors': {'itemId': ['Invalid item ID format']}
                }), 400
            
            # Check if item exists
            item = mongo.db.inventory_items.find_one({
                '_id': item_object_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found',
                    'errors': {'itemId': ['Item not found']}
                }), 404
            
            # Validate movement type
            valid_types = ['in', 'out', 'adjustment']
            movement_type = data['movementType'].lower()
            if movement_type not in valid_types:
                return jsonify({
                    'success': False,
                    'message': 'Invalid movement type',
                    'errors': {'movementType': ['Movement type must be in, out, or adjustment']}
                }), 400
            
            # Validate quantity
            try:
                quantity = int(data['quantity'])
                if quantity <= 0 and movement_type != 'adjustment':
                    return jsonify({
                        'success': False,
                        'message': 'Quantity must be positive for in/out movements',
                        'errors': {'quantity': ['Quantity must be positive']}
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False,
                    'message': 'Invalid quantity format',
                    'errors': {'quantity': ['Quantity must be a valid number']}
                }), 400
            
            # Get current stock
            current_stock = item['currentStock']
            
            # Calculate stock after movement
            if movement_type == 'in':
                stock_after = current_stock + abs(quantity)
            elif movement_type == 'out':
                stock_after = current_stock - abs(quantity)
                # Check if stock would go negative
                if stock_after < 0:
                    return jsonify({
                        'success': False,
                        'message': 'Insufficient stock for this operation',
                        'errors': {'quantity': ['Insufficient stock available']},
                        'data': {'currentStock': current_stock, 'requestedQuantity': quantity}
                    }), 400
            else:  # adjustment
                stock_after = quantity  # For adjustments, quantity is the new stock level
            
            # Validate unit cost for in movements
            unit_cost = 0
            total_cost = 0
            if movement_type == 'in':
                if 'unitCost' in data:
                    try:
                        unit_cost = float(data['unitCost'])
                        if unit_cost < 0:
                            return jsonify({
                                'success': False,
                                'message': 'Unit cost must be non-negative',
                                'errors': {'unitCost': ['Unit cost must be non-negative']}
                            }), 400
                    except (ValueError, TypeError):
                        return jsonify({
                            'success': False,
                            'message': 'Invalid unit cost format',
                            'errors': {'unitCost': ['Unit cost must be a valid number']}
                        }), 400
                else:
                    unit_cost = item['costPrice']  # Use item's cost price as default
                
                total_cost = unit_cost * abs(quantity)
            
            # Create movement record
            movement_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'itemId': item_object_id,
                'movementType': movement_type,
                'quantity': quantity,
                'unitCost': unit_cost,
                'totalCost': total_cost,
                'reason': data.get('reason', '').strip() or None,
                'reference': data.get('reference', '').strip() or None,
                'stockBefore': current_stock,
                'stockAfter': stock_after,
                'movementDate': datetime.utcnow(),
                'notes': data.get('notes', '').strip() or None,
                'createdAt': datetime.utcnow()
            }
            
            # Insert movement
            result = mongo.db.inventory_movements.insert_one(movement_data)
            
            # Update item stock
            update_item_stock(item_object_id, current_user['_id'])
            
            # COGS FIX (Phase 2.1): Only create COGS expense for SALES, not all out movements
            # Other out movements (damage, theft, adjustment) should NOT create COGS
            if movement_type == 'out' and data.get('reason') == 'sale':
                create_cogs_expense(item_object_id, abs(quantity), current_user['_id'])
            
            # Get created movement
            created_movement = mongo.db.inventory_movements.find_one({'_id': result.inserted_id})
            movement_response = serialize_doc(created_movement.copy())
            
            # Format dates
            movement_response['movementDate'] = safe_date_format(movement_response.get('movementDate'), default_to_now=True)
            movement_response['createdAt'] = safe_date_format(movement_response.get('createdAt'), default_to_now=True)
            
            return jsonify({
                'success': True,
                'data': movement_response,
                'message': 'Movement recorded successfully'
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to record movement',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/movements', methods=['GET'])
    @token_required
    def get_movements(current_user):
        """Get stock movement history with filtering"""
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            item_id = request.args.get('itemId')
            movement_type = request.args.get('movementType')
            start_date = request.args.get('startDate')
            end_date = request.args.get('endDate')
            
            # Build query
            query = {'userId': current_user['_id']}
            
            if item_id:
                try:
                    query['itemId'] = ObjectId(item_id)
                except:
                    return jsonify({
                        'success': False,
                        'message': 'Invalid item ID format',
                        'errors': {'itemId': ['Invalid item ID format']}
                    }), 400
            
            if movement_type:
                query['movementType'] = movement_type.lower()
            
            # Date filtering
            if start_date or end_date:
                date_query = {}
                if start_date:
                    try:
                        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                        date_query['$gte'] = start_dt
                    except:
                        return jsonify({
                            'success': False,
                            'message': 'Invalid start date format',
                            'errors': {'startDate': ['Invalid date format']}
                        }), 400
                
                if end_date:
                    try:
                        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                        date_query['$lte'] = end_dt
                    except:
                        return jsonify({
                            'success': False,
                            'message': 'Invalid end date format',
                            'errors': {'endDate': ['Invalid date format']}
                        }), 400
                
                query['movementDate'] = date_query
            
            # Get movements with pagination
            skip = (page - 1) * limit
            movements = list(mongo.db.inventory_movements.find(query).sort('movementDate', -1).skip(skip).limit(limit))
            total = mongo.db.inventory_movements.count_documents(query)
            
            # Get item details for each movement
            movement_list = []
            for movement in movements:
                movement_data = serialize_doc(movement.copy())
                movement_data['movementDate'] = safe_date_format(movement_data.get('movementDate'), default_to_now=True)
                movement_data['createdAt'] = safe_date_format(movement_data.get('createdAt'), default_to_now=True)
                
                # Get item details
                item = mongo.db.inventory_items.find_one({'_id': movement['itemId']})
                if item:
                    movement_data['itemName'] = item['itemName']
                    movement_data['itemCode'] = item.get('itemCode')
                    movement_data['unit'] = item['unit']
                
                movement_list.append(movement_data)
            
            return jsonify({
                'success': True,
                'data': movement_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                },
                'message': 'Movements retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve movements',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/items/<item_id>/movements', methods=['GET'])
    @token_required
    def get_item_movements(current_user, item_id):
        """Get movements for specific item"""
        try:
            # Validate ObjectId
            try:
                item_object_id = ObjectId(item_id)
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid item ID format',
                    'errors': {'itemId': ['Invalid item ID format']}
                }), 400
            
            # Check if item exists
            item = mongo.db.inventory_items.find_one({
                '_id': item_object_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found',
                    'errors': {'itemId': ['Item not found']}
                }), 404
            
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            
            # Get movements for this item
            skip = (page - 1) * limit
            movements = list(mongo.db.inventory_movements.find({
                'itemId': item_object_id,
                'userId': current_user['_id']
            }).sort('movementDate', -1).skip(skip).limit(limit))
            
            total = mongo.db.inventory_movements.count_documents({
                'itemId': item_object_id,
                'userId': current_user['_id']
            })
            
            # Serialize movements
            movement_list = []
            for movement in movements:
                movement_data = serialize_doc(movement.copy())
                movement_data['movementDate'] = safe_date_format(movement_data.get('movementDate'), default_to_now=True)
                movement_data['createdAt'] = safe_date_format(movement_data.get('createdAt'), default_to_now=True)
                movement_data['itemName'] = item['itemName']
                movement_data['itemCode'] = item.get('itemCode')
                movement_data['unit'] = item['unit']
                movement_list.append(movement_data)
            
            return jsonify({
                'success': True,
                'data': movement_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                },
                'itemInfo': {
                    'itemName': item['itemName'],
                    'itemCode': item.get('itemCode'),
                    'currentStock': item['currentStock'],
                    'unit': item['unit']
                },
                'message': 'Item movements retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve item movements',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== STOCK OPERATIONS ====================

    @inventory_bp.route('/stock-in', methods=['POST'])
    @token_required
    def stock_in_operation(current_user):
        """Stock in operation (purchase/restock)"""
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['itemId', 'quantity']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            # Validate ObjectId
            try:
                item_object_id = ObjectId(data['itemId'])
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid item ID format',
                    'errors': {'itemId': ['Invalid item ID format']}
                }), 400
            
            # Check if item exists
            item = mongo.db.inventory_items.find_one({
                '_id': item_object_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found',
                    'errors': {'itemId': ['Item not found']}
                }), 404
            
            # Validate quantity
            try:
                quantity = int(data['quantity'])
                if quantity <= 0:
                    return jsonify({
                        'success': False,
                        'message': 'Quantity must be positive',
                        'errors': {'quantity': ['Quantity must be positive']}
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False,
                    'message': 'Invalid quantity format',
                    'errors': {'quantity': ['Quantity must be a valid number']}
                }), 400
            
            # Validate unit cost
            unit_cost = item['costPrice']  # Default to item's cost price
            if 'unitCost' in data:
                try:
                    unit_cost = float(data['unitCost'])
                    if unit_cost < 0:
                        return jsonify({
                            'success': False,
                            'message': 'Unit cost must be non-negative',
                            'errors': {'unitCost': ['Unit cost must be non-negative']}
                        }), 400
                except (ValueError, TypeError):
                    return jsonify({
                        'success': False,
                        'message': 'Invalid unit cost format',
                        'errors': {'unitCost': ['Unit cost must be a valid number']}
                    }), 400
            
            # Calculate total cost
            total_cost = unit_cost * quantity
            
            # Get current stock
            current_stock = item['currentStock']
            stock_after = current_stock + quantity
            
            # Create movement record
            movement_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'itemId': item_object_id,
                'movementType': 'in',
                'quantity': quantity,
                'unitCost': unit_cost,
                'totalCost': total_cost,
                'reason': 'stock_in',
                'reference': data.get('reference', '').strip() or f"Stock In - {datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                'stockBefore': current_stock,
                'stockAfter': stock_after,
                'movementDate': datetime.utcnow(),
                'notes': data.get('notes', '').strip() or None,
                'supplier': data.get('supplier', '').strip() or None,
                'purchaseOrder': data.get('purchaseOrder', '').strip() or None,
                'createdAt': datetime.utcnow()
            }
            
            # Insert movement
            result = mongo.db.inventory_movements.insert_one(movement_data)
            
            # Update item stock and last restocked date
            mongo.db.inventory_items.update_one(
                {'_id': item_object_id},
                {
                    '$set': {
                        'lastRestocked': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }
                }
            )
            
            # Update item stock using helper function
            update_item_stock(item_object_id, current_user['_id'])
            
            # Get created movement
            created_movement = mongo.db.inventory_movements.find_one({'_id': result.inserted_id})
            movement_response = serialize_doc(created_movement.copy())
            
            # Format dates
            movement_response['movementDate'] = safe_date_format(movement_response.get('movementDate'), default_to_now=True)
            movement_response['createdAt'] = safe_date_format(movement_response.get('createdAt'), default_to_now=True)
            
            # Add item info
            movement_response['itemName'] = item['itemName']
            movement_response['itemCode'] = item.get('itemCode')
            movement_response['unit'] = item['unit']
            
            return jsonify({
                'success': True,
                'data': movement_response,
                'message': 'Stock in operation completed successfully'
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to complete stock in operation',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/stock-out', methods=['POST'])
    @token_required
    def stock_out_operation(current_user):
        """Stock out operation (sale/usage)"""
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['itemId', 'quantity']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            # Validate ObjectId
            try:
                item_object_id = ObjectId(data['itemId'])
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid item ID format',
                    'errors': {'itemId': ['Invalid item ID format']}
                }), 400
            
            # Check if item exists
            item = mongo.db.inventory_items.find_one({
                '_id': item_object_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found',
                    'errors': {'itemId': ['Item not found']}
                }), 404
            
            # Validate quantity
            try:
                quantity = int(data['quantity'])
                if quantity <= 0:
                    return jsonify({
                        'success': False,
                        'message': 'Quantity must be positive',
                        'errors': {'quantity': ['Quantity must be positive']}
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False,
                    'message': 'Invalid quantity format',
                    'errors': {'quantity': ['Quantity must be a valid number']}
                }), 400
            
            # Check stock availability
            current_stock = item['currentStock']
            if current_stock < quantity:
                return jsonify({
                    'success': False,
                    'message': 'Insufficient stock for this operation',
                    'errors': {'quantity': ['Insufficient stock available']},
                    'data': {'currentStock': current_stock, 'requestedQuantity': quantity}
                }), 400
            
            stock_after = current_stock - quantity
            
            # Create movement record
            movement_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'itemId': item_object_id,
                'movementType': 'out',
                'quantity': quantity,
                'unitCost': item['costPrice'],
                'totalCost': item['costPrice'] * quantity,
                'reason': 'stock_out',
                'reference': data.get('reference', '').strip() or f"Stock Out - {datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                'stockBefore': current_stock,
                'stockAfter': stock_after,
                'movementDate': datetime.utcnow(),
                'notes': data.get('notes', '').strip() or None,
                'customer': data.get('customer', '').strip() or None,
                'salesOrder': data.get('salesOrder', '').strip() or None,
                'sellingPrice': data.get('sellingPrice'),
                'createdAt': datetime.utcnow()
            }
            
            # Insert movement
            result = mongo.db.inventory_movements.insert_one(movement_data)
            
            # Update item stock using helper function
            update_item_stock(item_object_id, current_user['_id'])
            
            # COGS FIX (Phase 2.1): Only create COGS expense if this is a SALE
            # Check if sellingPrice is provided (indicates a sale)
            # Otherwise, this might be usage/damage/waste which should NOT create COGS
            if data.get('sellingPrice') is not None:
                create_cogs_expense(item_object_id, quantity, current_user['_id'])
            
            # Get created movement
            created_movement = mongo.db.inventory_movements.find_one({'_id': result.inserted_id})
            movement_response = serialize_doc(created_movement.copy())
            
            # Format dates
            movement_response['movementDate'] = safe_date_format(movement_response.get('movementDate'), default_to_now=True)
            movement_response['createdAt'] = safe_date_format(movement_response.get('createdAt'), default_to_now=True)
            
            # Add item info
            movement_response['itemName'] = item['itemName']
            movement_response['itemCode'] = item.get('itemCode')
            movement_response['unit'] = item['unit']
            
            return jsonify({
                'success': True,
                'data': movement_response,
                'message': 'Stock out operation completed successfully'
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to complete stock out operation',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/stock-adjustment', methods=['POST'])
    @token_required
    def stock_adjustment_operation(current_user):
        """Stock adjustment operation"""
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['itemId', 'newStockLevel', 'reason']
            for field in required_fields:
                if field == 'newStockLevel' and data.get(field) is None:
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
                elif field != 'newStockLevel' and not data.get(field):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            # Validate ObjectId
            try:
                item_object_id = ObjectId(data['itemId'])
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid item ID format',
                    'errors': {'itemId': ['Invalid item ID format']}
                }), 400
            
            # Check if item exists
            item = mongo.db.inventory_items.find_one({
                '_id': item_object_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found',
                    'errors': {'itemId': ['Item not found']}
                }), 404
            
            # Validate new stock level
            try:
                new_stock_level = int(data['newStockLevel'])
                if new_stock_level < 0:
                    return jsonify({
                        'success': False,
                        'message': 'New stock level must be non-negative',
                        'errors': {'newStockLevel': ['New stock level must be non-negative']}
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False,
                    'message': 'Invalid new stock level format',
                    'errors': {'newStockLevel': ['New stock level must be a valid number']}
                }), 400
            
            # Get current stock
            current_stock = item['currentStock']
            
            # Calculate adjustment quantity
            adjustment_quantity = new_stock_level - current_stock
            
            if adjustment_quantity == 0:
                return jsonify({
                    'success': False,
                    'message': 'No adjustment needed - stock level is already at target',
                    'errors': {'newStockLevel': ['Stock level is already at target value']},
                    'data': {'currentStock': current_stock}
                }), 400
            
            # Create movement record
            movement_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'itemId': item_object_id,
                'movementType': 'adjustment',
                'quantity': new_stock_level,  # For adjustments, quantity is the new stock level
                'adjustmentQuantity': adjustment_quantity,  # Track the actual adjustment
                'unitCost': 0,  # No cost for adjustments
                'totalCost': 0,
                'reason': data['reason'].strip(),
                'reference': data.get('reference', '').strip() or f"Stock Adjustment - {datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                'stockBefore': current_stock,
                'stockAfter': new_stock_level,
                'movementDate': datetime.utcnow(),
                'notes': data.get('notes', '').strip() or None,
                'adjustedBy': current_user.get('email', 'Unknown'),
                'createdAt': datetime.utcnow()
            }
            
            # Insert movement
            result = mongo.db.inventory_movements.insert_one(movement_data)
            
            # Update item stock using helper function
            update_item_stock(item_object_id, current_user['_id'])
            
            # Get created movement
            created_movement = mongo.db.inventory_movements.find_one({'_id': result.inserted_id})
            movement_response = serialize_doc(created_movement.copy())
            
            # Format dates
            movement_response['movementDate'] = safe_date_format(movement_response.get('movementDate'), default_to_now=True)
            movement_response['createdAt'] = safe_date_format(movement_response.get('createdAt'), default_to_now=True)
            
            # Add item info
            movement_response['itemName'] = item['itemName']
            movement_response['itemCode'] = item.get('itemCode')
            movement_response['unit'] = item['unit']
            
            return jsonify({
                'success': True,
                'data': movement_response,
                'message': f'Stock adjustment completed successfully. Stock changed by {adjustment_quantity:+d} units.'
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to complete stock adjustment',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== REPORTING & ANALYTICS ====================

    @inventory_bp.route('/low-stock', methods=['GET'])
    @token_required
    def get_low_stock_items(current_user):
        """Get low stock items"""
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            category = request.args.get('category')
            
            # Build query for low stock items
            query = {
                'userId': current_user['_id'],
                '$expr': {'$lte': ['$currentStock', '$minimumStock']}
            }
            
            if category:
                query['category'] = category
            
            # Get low stock items with pagination
            skip = (page - 1) * limit
            items = list(mongo.db.inventory_items.find(query).sort('currentStock', 1).skip(skip).limit(limit))
            total = mongo.db.inventory_items.count_documents(query)
            
            # Serialize items with additional low stock info
            item_list = []
            for item in items:
                item_data = serialize_doc(item.copy())
                item_data['createdAt'] = safe_date_format(item_data.get('createdAt'), default_to_now=True)
                item_data['updatedAt'] = safe_date_format(item_data.get('updatedAt'), default_to_now=True)
                item_data['lastRestocked'] = safe_date_format(item_data.get('lastRestocked'))
                
                # Calculate stock deficit
                stock_deficit = item['minimumStock'] - item['currentStock']
                item_data['stockDeficit'] = max(0, stock_deficit)
                
                # Calculate suggested reorder quantity (minimum stock + 50% buffer)
                suggested_reorder = int(item['minimumStock'] * 1.5) - item['currentStock']
                item_data['suggestedReorderQuantity'] = max(0, suggested_reorder)
                
                # Calculate days since last restock
                if item.get('lastRestocked'):
                    days_since_restock = (datetime.utcnow() - item['lastRestocked']).days
                    item_data['daysSinceLastRestock'] = days_since_restock
                else:
                    item_data['daysSinceLastRestock'] = None
                
                # Priority level based on stock level
                if item['currentStock'] <= 0:
                    item_data['priority'] = 'critical'
                elif item['currentStock'] <= item['minimumStock'] * 0.5:
                    item_data['priority'] = 'high'
                else:
                    item_data['priority'] = 'medium'
                
                item_list.append(item_data)
            
            # Calculate summary statistics
            critical_items = len([item for item in item_list if item['priority'] == 'critical'])
            high_priority_items = len([item for item in item_list if item['priority'] == 'high'])
            
            return jsonify({
                'success': True,
                'data': item_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                },
                'summary': {
                    'totalLowStockItems': total,
                    'criticalItems': critical_items,
                    'highPriorityItems': high_priority_items
                },
                'message': 'Low stock items retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve low stock items',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/valuation', methods=['GET'])
    @token_required
    def get_inventory_valuation(current_user):
        """Get inventory valuation report"""
        try:
            method = request.args.get('method', 'current').lower()  # current, fifo, lifo, average
            category = request.args.get('category')
            
            # Build query
            query = {'userId': current_user['_id']}
            if category:
                query['category'] = category
            
            # Get all items
            items = list(mongo.db.inventory_items.find(query))
            
            valuation_data = []
            total_value = 0
            total_quantity = 0
            
            for item in items:
                item_valuation = {
                    'itemId': str(item['_id']),
                    'itemName': item['itemName'],
                    'itemCode': item.get('itemCode'),
                    'category': item['category'],
                    'currentStock': item['currentStock'],
                    'unit': item['unit']
                }
                
                if method == 'current':
                    # Use current cost price
                    unit_value = item['costPrice']
                    item_value = item['currentStock'] * unit_value
                    item_valuation['unitValue'] = unit_value
                    item_valuation['totalValue'] = item_value
                    item_valuation['method'] = 'Current Cost Price'
                
                elif method == 'fifo':
                    # FIFO - First In, First Out
                    movements = list(mongo.db.inventory_movements.find({
                        'itemId': item['_id'],
                        'userId': current_user['_id'],
                        'movementType': 'in'
                    }).sort('movementDate', 1))
                    
                    remaining_stock = item['currentStock']
                    fifo_value = 0
                    
                    for movement in movements:
                        if remaining_stock <= 0:
                            break
                        
                        movement_qty = min(movement['quantity'], remaining_stock)
                        fifo_value += movement_qty * movement['unitCost']
                        remaining_stock -= movement_qty
                    
                    item_valuation['totalValue'] = fifo_value
                    item_valuation['unitValue'] = fifo_value / item['currentStock'] if item['currentStock'] > 0 else 0
                    item_valuation['method'] = 'FIFO'
                
                elif method == 'lifo':
                    # LIFO - Last In, First Out
                    movements = list(mongo.db.inventory_movements.find({
                        'itemId': item['_id'],
                        'userId': current_user['_id'],
                        'movementType': 'in'
                    }).sort('movementDate', -1))
                    
                    remaining_stock = item['currentStock']
                    lifo_value = 0
                    
                    for movement in movements:
                        if remaining_stock <= 0:
                            break
                        
                        movement_qty = min(movement['quantity'], remaining_stock)
                        lifo_value += movement_qty * movement['unitCost']
                        remaining_stock -= movement_qty
                    
                    item_valuation['totalValue'] = lifo_value
                    item_valuation['unitValue'] = lifo_value / item['currentStock'] if item['currentStock'] > 0 else 0
                    item_valuation['method'] = 'LIFO'
                
                elif method == 'average':
                    # Weighted Average Cost
                    movements = list(mongo.db.inventory_movements.find({
                        'itemId': item['_id'],
                        'userId': current_user['_id'],
                        'movementType': 'in'
                    }))
                    
                    total_cost = sum(movement['totalCost'] for movement in movements)
                    total_qty = sum(movement['quantity'] for movement in movements)
                    
                    if total_qty > 0:
                        avg_unit_cost = total_cost / total_qty
                        item_value = item['currentStock'] * avg_unit_cost
                    else:
                        avg_unit_cost = item['costPrice']
                        item_value = item['currentStock'] * avg_unit_cost
                    
                    item_valuation['unitValue'] = avg_unit_cost
                    item_valuation['totalValue'] = item_value
                    item_valuation['method'] = 'Weighted Average'
                
                # Add profit potential
                potential_revenue = item['currentStock'] * item['sellingPrice']
                potential_profit = potential_revenue - item_valuation['totalValue']
                item_valuation['potentialRevenue'] = potential_revenue
                item_valuation['potentialProfit'] = potential_profit
                
                valuation_data.append(item_valuation)
                total_value += item_valuation['totalValue']
                total_quantity += item['currentStock']
            
            # Calculate summary
            total_potential_revenue = sum(item['potentialRevenue'] for item in valuation_data)
            total_potential_profit = sum(item['potentialProfit'] for item in valuation_data)
            
            # Group by category
            category_summary = {}
            for item in valuation_data:
                cat = item['category']
                if cat not in category_summary:
                    category_summary[cat] = {
                        'totalValue': 0,
                        'totalQuantity': 0,
                        'itemCount': 0,
                        'potentialRevenue': 0,
                        'potentialProfit': 0
                    }
                
                category_summary[cat]['totalValue'] += item['totalValue']
                category_summary[cat]['totalQuantity'] += item['currentStock']
                category_summary[cat]['itemCount'] += 1
                category_summary[cat]['potentialRevenue'] += item['potentialRevenue']
                category_summary[cat]['potentialProfit'] += item['potentialProfit']
            
            return jsonify({
                'success': True,
                'data': {
                    'items': valuation_data,
                    'summary': {
                        'totalValue': total_value,
                        'totalQuantity': total_quantity,
                        'totalItems': len(valuation_data),
                        'potentialRevenue': total_potential_revenue,
                        'potentialProfit': total_potential_profit,
                        'profitMargin': (total_potential_profit / total_potential_revenue * 100) if total_potential_revenue > 0 else 0
                    },
                    'categoryBreakdown': category_summary,
                    'valuationMethod': method.upper(),
                    'generatedAt': safe_date_format(datetime.utcnow(), default_to_now=True)
                },
                'message': 'Inventory valuation report generated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to generate valuation report',
                'errors': {'general': [str(e)]}
            }), 500

    @inventory_bp.route('/movement-history', methods=['GET'])
    @token_required
    def get_movement_history_report(current_user):
        """Get comprehensive movement history with analytics"""
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
            start_date = request.args.get('startDate')
            end_date = request.args.get('endDate')
            category = request.args.get('category')
            movement_type = request.args.get('movementType')
            
            # Build query
            query = {'userId': current_user['_id']}
            
            # Date filtering
            if start_date or end_date:
                date_query = {}
                if start_date:
                    try:
                        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                        date_query['$gte'] = start_dt
                    except:
                        return jsonify({
                            'success': False,
                            'message': 'Invalid start date format',
                            'errors': {'startDate': ['Invalid date format']}
                        }), 400
                
                if end_date:
                    try:
                        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                        date_query['$lte'] = end_dt
                    except:
                        return jsonify({
                            'success': False,
                            'message': 'Invalid end date format',
                            'errors': {'endDate': ['Invalid date format']}
                        }), 400
                
                query['movementDate'] = date_query
            
            if movement_type:
                query['movementType'] = movement_type.lower()
            
            # Get movements with item details
            pipeline = [
                {'$match': query},
                {
                    '$lookup': {
                        'from': 'inventory_items',
                        'localField': 'itemId',
                        'foreignField': '_id',
                        'as': 'item'
                    }
                },
                {'$unwind': '$item'},
                {'$sort': {'movementDate': -1}}
            ]
            
            if category:
                pipeline.insert(-1, {'$match': {'item.category': category}})
            
            # Add pagination
            pipeline.extend([
                {'$skip': (page - 1) * limit},
                {'$limit': limit}
            ])
            
            movements = list(mongo.db.inventory_movements.aggregate(pipeline))
            
            # Get total count for pagination
            count_pipeline = pipeline[:-2]  # Remove skip and limit
            count_pipeline.append({'$count': 'total'})
            count_result = list(mongo.db.inventory_movements.aggregate(count_pipeline))
            total = count_result[0]['total'] if count_result else 0
            
            # Process movements
            movement_list = []
            for movement in movements:
                movement_data = {
                    'movementId': str(movement['_id']),
                    'itemId': str(movement['itemId']),
                    'itemName': movement['item']['itemName'],
                    'itemCode': movement['item'].get('itemCode'),
                    'category': movement['item']['category'],
                    'unit': movement['item']['unit'],
                    'movementType': movement['movementType'],
                    'quantity': movement['quantity'],
                    'unitCost': movement.get('unitCost', 0),
                    'totalCost': movement.get('totalCost', 0),
                    'reason': movement.get('reason'),
                    'reference': movement.get('reference'),
                    'stockBefore': movement.get('stockBefore', 0),
                    'stockAfter': movement.get('stockAfter', 0),
                    'movementDate': safe_date_format(movement.get('movementDate'), default_to_now=True),
                    'notes': movement.get('notes'),
                    'createdAt': safe_date_format(movement.get('createdAt'), default_to_now=True)
                }
                
                # Add type-specific fields
                if movement['movementType'] == 'in':
                    movement_data['supplier'] = movement.get('supplier')
                    movement_data['purchaseOrder'] = movement.get('purchaseOrder')
                elif movement['movementType'] == 'out':
                    movement_data['customer'] = movement.get('customer')
                    movement_data['salesOrder'] = movement.get('salesOrder')
                    movement_data['sellingPrice'] = movement.get('sellingPrice')
                elif movement['movementType'] == 'adjustment':
                    movement_data['adjustmentQuantity'] = movement.get('adjustmentQuantity')
                    movement_data['adjustedBy'] = movement.get('adjustedBy')
                
                movement_list.append(movement_data)
            
            # Calculate analytics
            analytics = {
                'totalMovements': total,
                'movementsByType': {},
                'totalValueIn': 0,
                'totalValueOut': 0,
                'totalQuantityIn': 0,
                'totalQuantityOut': 0,
                'categoriesAffected': set(),
                'itemsAffected': set()
            }
            
            for movement in movement_list:
                mov_type = movement['movementType']
                analytics['movementsByType'][mov_type] = analytics['movementsByType'].get(mov_type, 0) + 1
                analytics['categoriesAffected'].add(movement['category'])
                analytics['itemsAffected'].add(movement['itemId'])
                
                if mov_type == 'in':
                    analytics['totalValueIn'] += movement['totalCost']
                    analytics['totalQuantityIn'] += movement['quantity']
                elif mov_type == 'out':
                    analytics['totalValueOut'] += movement['totalCost']
                    analytics['totalQuantityOut'] += movement['quantity']
            
            analytics['categoriesAffected'] = len(analytics['categoriesAffected'])
            analytics['itemsAffected'] = len(analytics['itemsAffected'])
            
            return jsonify({
                'success': True,
                'data': movement_list,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                },
                'analytics': analytics,
                'message': 'Movement history report generated successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to generate movement history report',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== SHRINKAGE MANAGEMENT (Light Approach) ====================
    
    @inventory_bp.route('/mark-shrinkage', methods=['POST'])
    @token_required
    def mark_shrinkage(current_user):
        """
        Mark inventory items as damaged/lost/stolen (Shrinkage)
        
        The "Light" Approach:
        1. Reduce Inventory Asset value
        2. Create Shrinkage Expense (Operating Expense)
        3. Balance Sheet stays balanced
        4. Profit & Loss accurately reflects the loss
        
        This is NOT a sale, so NO COGS is created.
        """
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['itemId', 'quantity', 'reason']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({
                        'success': False,
                        'message': f'{field} is required',
                        'errors': {field: [f'{field} is required']}
                    }), 400
            
            # Validate item ID
            if not ObjectId.is_valid(data['itemId']):
                return jsonify({
                    'success': False,
                    'message': 'Invalid item ID'
                }), 400
            
            item_object_id = ObjectId(data['itemId'])
            
            # Check if item exists
            item = mongo.db.inventory_items.find_one({
                '_id': item_object_id,
                'userId': current_user['_id']
            })
            
            if not item:
                return jsonify({
                    'success': False,
                    'message': 'Item not found'
                }), 404
            
            # Validate quantity
            try:
                quantity = int(data['quantity'])
                if quantity <= 0:
                    return jsonify({
                        'success': False,
                        'message': 'Quantity must be greater than 0',
                        'errors': {'quantity': ['Quantity must be greater than 0']}
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    'success': False,
                    'message': 'Invalid quantity format',
                    'errors': {'quantity': ['Quantity must be a valid number']}
                }), 400
            
            # Check if sufficient stock
            current_stock = item['currentStock']
            if quantity > current_stock:
                return jsonify({
                    'success': False,
                    'message': 'Insufficient stock',
                    'errors': {'quantity': [f'Cannot mark {quantity} units as shrinkage. Only {current_stock} units available.']},
                    'data': {'currentStock': current_stock, 'requestedQuantity': quantity}
                }), 400
            
            # Validate reason
            valid_reasons = ['damaged', 'lost', 'stolen', 'expired', 'spoiled', 'other']
            reason = data['reason'].lower()
            if reason not in valid_reasons:
                return jsonify({
                    'success': False,
                    'message': 'Invalid shrinkage reason',
                    'errors': {'reason': [f'Reason must be one of: {", ".join(valid_reasons)}']}
                }), 400
            
            # Calculate shrinkage value
            shrinkage_value = item['costPrice'] * quantity
            
            # Create inventory movement record (out movement for shrinkage)
            movement_data = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'itemId': item_object_id,
                'movementType': 'out',
                'quantity': quantity,
                'unitCost': item['costPrice'],
                'totalCost': shrinkage_value,
                'reason': f'shrinkage_{reason}',
                'reference': data.get('reference', '').strip() or f"SHRINKAGE-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                'stockBefore': current_stock,
                'stockAfter': current_stock - quantity,
                'movementDate': datetime.utcnow(),
                'notes': data.get('notes', '').strip() or f"Inventory shrinkage: {reason}",
                'shrinkageType': reason,  # Track shrinkage type
                'createdAt': datetime.utcnow()
            }
            
            # Insert movement
            movement_result = mongo.db.inventory_movements.insert_one(movement_data)
            
            # Update item stock using helper function
            update_item_stock(item_object_id, current_user['_id'])
            
            # 💰 SHRINKAGE EXPENSE: Create Operating Expense (NOT COGS)
            # This reduces Inventory Asset and increases Shrinkage Expense
            # Balance Sheet stays balanced, P&L shows the loss
            shrinkage_expense = {
                '_id': ObjectId(),
                'userId': current_user['_id'],
                'amount': shrinkage_value,
                'title': f"Inventory Shrinkage - {item['itemName']}",
                'description': f"Shrinkage ({reason}): {quantity} units of {item['itemName']}",
                'category': 'Shrinkage',  # Operating Expense category
                'date': datetime.utcnow(),
                'tags': ['Shrinkage', 'Inventory', 'Operating Expense', 'Auto-generated'],
                'paymentMethod': 'inventory',
                'notes': f"Auto-generated shrinkage expense. Item: {item['itemName']}, Quantity: {quantity}, Unit Cost: ₦{item['costPrice']:,.2f}, Reason: {reason}",
                'status': 'active',
                'isDeleted': False,
                'metadata': {
                    'source': 'inventory_shrinkage',
                    'itemId': str(item_object_id),
                    'itemName': item['itemName'],
                    'movementId': str(movement_result.inserted_id),
                    'shrinkageType': reason,
                    'quantity': quantity,
                    'unitCost': item['costPrice'],
                    'automated': True
                },
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            expense_result = mongo.db.expenses.insert_one(shrinkage_expense)
            
            print(f"✅ SHRINKAGE RECORDED:")
            print(f"   Item: {item['itemName']}")
            print(f"   Quantity: {quantity} units")
            print(f"   Value: ₦{shrinkage_value:,.2f}")
            print(f"   Reason: {reason}")
            print(f"   Inventory Asset: -₦{shrinkage_value:,.2f}")
            print(f"   Shrinkage Expense: +₦{shrinkage_value:,.2f}")
            print(f"   Balance Sheet: Balanced ✅")
            
            # Get created movement for response
            created_movement = mongo.db.inventory_movements.find_one({'_id': movement_result.inserted_id})
            movement_response = serialize_doc(created_movement.copy())
            
            # Format dates
            movement_response['movementDate'] = safe_date_format(movement_response.get('movementDate'), default_to_now=True)
            movement_response['createdAt'] = safe_date_format(movement_response.get('createdAt'), default_to_now=True)
            
            # Add item info
            movement_response['itemName'] = item['itemName']
            movement_response['itemCode'] = item.get('itemCode')
            movement_response['unit'] = item['unit']
            movement_response['shrinkageValue'] = shrinkage_value
            movement_response['expenseId'] = str(expense_result.inserted_id)
            
            return jsonify({
                'success': True,
                'data': movement_response,
                'message': f'Shrinkage recorded successfully. {quantity} units of {item["itemName"]} marked as {reason}.',
                'accounting': {
                    'inventoryReduction': shrinkage_value,
                    'shrinkageExpense': shrinkage_value,
                    'balanceSheetImpact': 'Balanced',
                    'profitLossImpact': f'-₦{shrinkage_value:,.2f}'
                }
            }), 201
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to record shrinkage',
                'errors': {'general': [str(e)]}
            }), 500

    # ==================== COGS SEPARATION (Phase 2.1) ====================
    # Import and add purchase/sell endpoints for COGS separation
    from .inventory_cogs import add_cogs_routes
    add_cogs_routes(inventory_bp, mongo, token_required)

    return inventory_bp
