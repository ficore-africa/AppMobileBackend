"""
Asset Register Blueprint
Handles fixed asset tracking for 0% tax qualification (≤₦250M threshold)
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId

assets_bp = Blueprint('assets', __name__, url_prefix='/assets')

def init_assets_blueprint(mongo, token_required, serialize_doc):
    """Initialize the assets blueprint with database and auth decorator"""
    assets_bp.mongo = mongo
    assets_bp.token_required = token_required
    assets_bp.serialize_doc = serialize_doc
    return assets_bp


@assets_bp.route('', methods=['GET'])
def get_assets():
    """Get all assets for the authenticated user with optional filters"""
    @assets_bp.token_required
    def _get_assets(current_user):
        try:
            # Get query parameters
            limit = min(int(request.args.get('limit', 100)), 200)
            offset = max(int(request.args.get('offset', 0)), 0)
            category = request.args.get('category')
            status = request.args.get('status')
            sort_by = request.args.get('sort_by', 'createdAt')
            sort_order = request.args.get('sort_order', 'desc')
            
            # Build query
            query = {'userId': current_user['_id']}
            
            if category:
                query['category'] = category
            if status:
                query['status'] = status
            
            # Sorting
            sort_direction = -1 if sort_order == 'desc' else 1
            sort_field = sort_by if sort_by in ['createdAt', 'purchaseDate', 'assetName', 'currentValue'] else 'createdAt'
            
            # Get assets with pagination
            assets = list(assets_bp.mongo.db.assets.find(query)
                         .sort(sort_field, sort_direction)
                         .skip(offset)
                         .limit(limit))
            total = assets_bp.mongo.db.assets.count_documents(query)
            
            # Serialize assets
            asset_list = []
            for asset in assets:
                asset_data = assets_bp.serialize_doc(asset.copy())
                # Ensure dates are ISO format
                asset_data['purchaseDate'] = asset_data.get('purchaseDate', datetime.utcnow()).isoformat() + 'Z'
                asset_data['createdAt'] = asset_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                asset_data['updatedAt'] = asset_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                if asset_data.get('disposalDate'):
                    asset_data['disposalDate'] = asset_data['disposalDate'].isoformat() + 'Z'
                asset_list.append(asset_data)
            
            has_more = offset + limit < total
            
            return jsonify({
                'success': True,
                'data': asset_list,
                'pagination': {
                    'total': total,
                    'limit': limit,
                    'offset': offset,
                    'hasMore': has_more,
                    'page': (offset // limit) + 1,
                    'pages': (total + limit - 1) // limit
                },
                'message': 'Assets retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_assets: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve assets',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_assets()


@assets_bp.route('/<asset_id>', methods=['GET'])
def get_asset(asset_id):
    """Get a single asset by ID"""
    @assets_bp.token_required
    def _get_asset(current_user):
        try:
            asset = assets_bp.mongo.db.assets.find_one({
                '_id': ObjectId(asset_id),
                'userId': current_user['_id']
            })
            
            if not asset:
                return jsonify({
                    'success': False,
                    'message': 'Asset not found'
                }), 404
            
            asset_data = assets_bp.serialize_doc(asset.copy())
            # Ensure dates are ISO format
            asset_data['purchaseDate'] = asset_data.get('purchaseDate', datetime.utcnow()).isoformat() + 'Z'
            asset_data['createdAt'] = asset_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            asset_data['updatedAt'] = asset_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            if asset_data.get('disposalDate'):
                asset_data['disposalDate'] = asset_data['disposalDate'].isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': asset_data,
                'message': 'Asset retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_asset: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve asset',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_asset()


@assets_bp.route('', methods=['POST'])
def create_asset():
    """Create a new asset"""
    @assets_bp.token_required
    def _create_asset(current_user):
        try:
            data = request.get_json()
            
            # Validation
            errors = {}
            if not data.get('assetName'):
                errors['assetName'] = ['Asset name is required']
            if not data.get('category'):
                errors['category'] = ['Category is required']
            if not data.get('purchasePrice') or data.get('purchasePrice', 0) <= 0:
                errors['purchasePrice'] = ['Valid purchase price is required']
            if not data.get('currentValue') or data.get('currentValue', 0) < 0:
                errors['currentValue'] = ['Valid current value is required']
            if not data.get('purchaseDate'):
                errors['purchaseDate'] = ['Purchase date is required']
            if not data.get('status'):
                errors['status'] = ['Status is required']
            if not data.get('depreciationMethod'):
                errors['depreciationMethod'] = ['Depreciation method is required']
            
            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400
            
            # Parse purchase date
            try:
                purchase_date = datetime.fromisoformat(data['purchaseDate'].replace('Z', ''))
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid purchase date format',
                    'errors': {'purchaseDate': ['Invalid date format']}
                }), 400
            
            # Parse disposal date if provided
            disposal_date = None
            if data.get('disposalDate'):
                try:
                    disposal_date = datetime.fromisoformat(data['disposalDate'].replace('Z', ''))
                except:
                    pass
            
            # Create asset document
            now = datetime.utcnow()
            asset_doc = {
                'userId': current_user['_id'],
                'assetName': data['assetName'].strip(),
                'assetCode': data.get('assetCode', '').strip() or None,
                'description': data.get('description', '').strip() or None,
                'category': data['category'],
                'purchasePrice': float(data['purchasePrice']),
                'currentValue': float(data['currentValue']),
                'purchaseDate': purchase_date,
                'supplier': data.get('supplier', '').strip() or None,
                'location': data.get('location', '').strip() or None,
                'status': data['status'],
                'depreciationRate': float(data['depreciationRate']) if data.get('depreciationRate') else None,
                'depreciationMethod': data['depreciationMethod'],
                'usefulLifeYears': int(data['usefulLifeYears']) if data.get('usefulLifeYears') else None,
                'attachments': data.get('attachments', []),
                'notes': data.get('notes', '').strip() or None,
                'disposalDate': disposal_date,
                'disposalValue': float(data['disposalValue']) if data.get('disposalValue') else None,
                'createdAt': now,
                'updatedAt': now
            }
            
            # Insert into database
            result = assets_bp.mongo.db.assets.insert_one(asset_doc)
            asset_doc['_id'] = result.inserted_id
            
            # Serialize and return
            asset_data = assets_bp.serialize_doc(asset_doc)
            asset_data['purchaseDate'] = asset_data['purchaseDate'].isoformat() + 'Z'
            asset_data['createdAt'] = asset_data['createdAt'].isoformat() + 'Z'
            asset_data['updatedAt'] = asset_data['updatedAt'].isoformat() + 'Z'
            if asset_data.get('disposalDate'):
                asset_data['disposalDate'] = asset_data['disposalDate'].isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': asset_data,
                'message': 'Asset created successfully'
            }), 201
            
        except Exception as e:
            print(f"Error in create_asset: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to create asset',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _create_asset()


@assets_bp.route('/<asset_id>', methods=['PUT'])
def update_asset(asset_id):
    """Update an existing asset"""
    @assets_bp.token_required
    def _update_asset(current_user):
        try:
            # Check if asset exists and belongs to user
            existing_asset = assets_bp.mongo.db.assets.find_one({
                '_id': ObjectId(asset_id),
                'userId': current_user['_id']
            })
            
            if not existing_asset:
                return jsonify({
                    'success': False,
                    'message': 'Asset not found'
                }), 404
            
            data = request.get_json()
            
            # Build update document
            update_data = {'updatedAt': datetime.utcnow()}
            
            # Update fields if provided
            if 'assetName' in data:
                update_data['assetName'] = data['assetName'].strip()
            if 'assetCode' in data:
                update_data['assetCode'] = data['assetCode'].strip() or None
            if 'description' in data:
                update_data['description'] = data['description'].strip() or None
            if 'category' in data:
                update_data['category'] = data['category']
            if 'purchasePrice' in data:
                update_data['purchasePrice'] = float(data['purchasePrice'])
            if 'currentValue' in data:
                update_data['currentValue'] = float(data['currentValue'])
            if 'purchaseDate' in data:
                try:
                    update_data['purchaseDate'] = datetime.fromisoformat(data['purchaseDate'].replace('Z', ''))
                except:
                    pass
            if 'supplier' in data:
                update_data['supplier'] = data['supplier'].strip() or None
            if 'location' in data:
                update_data['location'] = data['location'].strip() or None
            if 'status' in data:
                update_data['status'] = data['status']
            if 'depreciationRate' in data:
                update_data['depreciationRate'] = float(data['depreciationRate']) if data['depreciationRate'] else None
            if 'depreciationMethod' in data:
                update_data['depreciationMethod'] = data['depreciationMethod']
            if 'usefulLifeYears' in data:
                update_data['usefulLifeYears'] = int(data['usefulLifeYears']) if data['usefulLifeYears'] else None
            if 'attachments' in data:
                update_data['attachments'] = data['attachments']
            if 'notes' in data:
                update_data['notes'] = data['notes'].strip() or None
            if 'disposalDate' in data:
                try:
                    update_data['disposalDate'] = datetime.fromisoformat(data['disposalDate'].replace('Z', '')) if data['disposalDate'] else None
                except:
                    pass
            if 'disposalValue' in data:
                update_data['disposalValue'] = float(data['disposalValue']) if data['disposalValue'] else None
            
            # Update asset
            assets_bp.mongo.db.assets.update_one(
                {'_id': ObjectId(asset_id)},
                {'$set': update_data}
            )
            
            # Fetch updated asset
            updated_asset = assets_bp.mongo.db.assets.find_one({'_id': ObjectId(asset_id)})
            asset_data = assets_bp.serialize_doc(updated_asset)
            asset_data['purchaseDate'] = asset_data['purchaseDate'].isoformat() + 'Z'
            asset_data['createdAt'] = asset_data['createdAt'].isoformat() + 'Z'
            asset_data['updatedAt'] = asset_data['updatedAt'].isoformat() + 'Z'
            if asset_data.get('disposalDate'):
                asset_data['disposalDate'] = asset_data['disposalDate'].isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': asset_data,
                'message': 'Asset updated successfully'
            })
            
        except Exception as e:
            print(f"Error in update_asset: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to update asset',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _update_asset()


@assets_bp.route('/<asset_id>', methods=['DELETE'])
def delete_asset(asset_id):
    """Delete an asset"""
    @assets_bp.token_required
    def _delete_asset(current_user):
        try:
            # Check if asset exists and belongs to user
            asset = assets_bp.mongo.db.assets.find_one({
                '_id': ObjectId(asset_id),
                'userId': current_user['_id']
            })
            
            if not asset:
                return jsonify({
                    'success': False,
                    'message': 'Asset not found'
                }), 404
            
            # Delete asset
            assets_bp.mongo.db.assets.delete_one({'_id': ObjectId(asset_id)})
            
            return jsonify({
                'success': True,
                'message': 'Asset deleted successfully'
            }), 200
            
        except Exception as e:
            print(f"Error in delete_asset: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to delete asset',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _delete_asset()


@assets_bp.route('/summary', methods=['GET'])
def get_asset_summary():
    """Get asset summary statistics for the authenticated user"""
    @assets_bp.token_required
    def _get_asset_summary(current_user):
        try:
            # Use MongoDB aggregation for efficient calculation
            pipeline = [
                {'$match': {'userId': current_user['_id']}},
                {'$facet': {
                    'totals': [
                        {'$group': {
                            '_id': None,
                            'totalAssets': {'$sum': 1},
                            'activeAssets': {
                                '$sum': {'$cond': [{'$eq': ['$status', 'active']}, 1, 0]}
                            },
                            'disposedAssets': {
                                '$sum': {'$cond': [{'$eq': ['$status', 'disposed']}, 1, 0]}
                            }
                        }}
                    ],
                    'activeValues': [
                        {'$match': {'status': 'active'}},
                        {'$group': {
                            '_id': None,
                            'totalPurchaseValue': {'$sum': '$purchasePrice'},
                            'totalCurrentValue': {'$sum': '$currentValue'}
                        }}
                    ],
                    'categoryBreakdown': [
                        {'$match': {'status': 'active'}},
                        {'$group': {
                            '_id': '$category',
                            'value': {'$sum': '$currentValue'}
                        }}
                    ]
                }}
            ]
            
            result = list(assets_bp.mongo.db.assets.aggregate(pipeline))
            
            if not result:
                # No assets found
                summary = {
                    'totalAssets': 0,
                    'activeAssets': 0,
                    'disposedAssets': 0,
                    'totalPurchaseValue': 0.0,
                    'totalCurrentValue': 0.0,
                    'totalDepreciation': 0.0,
                    'categoryBreakdown': {},
                    'qualifiesForZeroTax': True,
                    'remainingThreshold': 250000000.0
                }
            else:
                data = result[0]
                
                # Extract totals
                totals = data['totals'][0] if data['totals'] else {}
                total_assets = totals.get('totalAssets', 0)
                active_assets = totals.get('activeAssets', 0)
                disposed_assets = totals.get('disposedAssets', 0)
                
                # Extract active values
                active_values = data['activeValues'][0] if data['activeValues'] else {}
                total_purchase_value = active_values.get('totalPurchaseValue', 0.0)
                total_current_value = active_values.get('totalCurrentValue', 0.0)
                total_depreciation = total_purchase_value - total_current_value
                
                # Extract category breakdown
                category_breakdown = {}
                for item in data['categoryBreakdown']:
                    category_breakdown[item['_id']] = item['value']
                
                # Check 0% tax qualification (≤₦250M threshold)
                threshold = 250000000.0  # ₦250M
                qualifies_for_zero_tax = total_current_value <= threshold
                remaining_threshold = threshold - total_current_value if qualifies_for_zero_tax else 0
                
                summary = {
                    'totalAssets': total_assets,
                    'activeAssets': active_assets,
                    'disposedAssets': disposed_assets,
                    'totalPurchaseValue': total_purchase_value,
                    'totalCurrentValue': total_current_value,
                    'totalDepreciation': total_depreciation,
                    'categoryBreakdown': category_breakdown,
                    'qualifiesForZeroTax': qualifies_for_zero_tax,
                    'remainingThreshold': remaining_threshold
                }
            
            return jsonify({
                'success': True,
                'data': summary,
                'message': 'Asset summary retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error in get_asset_summary: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve asset summary',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _get_asset_summary()


@assets_bp.route('/search', methods=['GET'])
def search_assets():
    """Search assets by name, code, or description"""
    @assets_bp.token_required
    def _search_assets(current_user):
        try:
            query_text = request.args.get('q', '').strip()
            
            if not query_text:
                return jsonify({
                    'success': True,
                    'data': [],
                    'message': 'No search query provided'
                })
            
            # Build search query with text search
            search_query = {
                'userId': current_user['_id'],
                '$or': [
                    {'assetName': {'$regex': query_text, '$options': 'i'}},
                    {'assetCode': {'$regex': query_text, '$options': 'i'}},
                    {'description': {'$regex': query_text, '$options': 'i'}},
                    {'category': {'$regex': query_text, '$options': 'i'}},
                    {'supplier': {'$regex': query_text, '$options': 'i'}}
                ]
            }
            
            # Fetch matching assets (limit to 50 results)
            assets = list(assets_bp.mongo.db.assets.find(search_query)
                         .sort('createdAt', -1)
                         .limit(50))
            
            # Serialize assets
            asset_list = []
            for asset in assets:
                asset_data = assets_bp.serialize_doc(asset.copy())
                asset_data['purchaseDate'] = asset_data['purchaseDate'].isoformat() + 'Z'
                asset_data['createdAt'] = asset_data['createdAt'].isoformat() + 'Z'
                asset_data['updatedAt'] = asset_data['updatedAt'].isoformat() + 'Z'
                if asset_data.get('disposalDate'):
                    asset_data['disposalDate'] = asset_data['disposalDate'].isoformat() + 'Z'
                asset_list.append(asset_data)
            
            return jsonify({
                'success': True,
                'data': asset_list,
                'message': f'Found {len(asset_list)} matching assets'
            })
            
        except Exception as e:
            print(f"Error in search_assets: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to search assets',
                'errors': {'general': [str(e)]}
            }), 500
    
    return _search_assets()
