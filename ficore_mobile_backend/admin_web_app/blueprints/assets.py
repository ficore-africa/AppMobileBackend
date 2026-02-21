"""
Asset Register Blueprint
Handles fixed asset tracking for 0% tax qualification (≤₦250M threshold)
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId


def init_assets_blueprint(mongo, token_required, serialize_doc):
    """Initialize the assets blueprint with database and auth decorator"""
    assets_bp = Blueprint('assets', __name__, url_prefix='/assets')
    
    def calculate_asset_book_value(asset):
        """
        OPTION A + C HYBRID: Calculate current book value for an asset
        Returns manual adjustment if exists, otherwise calculates on-the-fly
        """
        # Check for manual adjustment first (Option C layer)
        manual_adjustment = asset.get('manualValueAdjustment')
        if manual_adjustment is not None:
            return float(manual_adjustment)
        
        # Calculate on-the-fly (Option A core)
        purchase_price = asset.get('purchasePrice', 0)
        purchase_date = asset.get('purchaseDate', datetime.utcnow())
        depreciation_method = asset.get('depreciationMethod', 'straight_line')
        depreciation_rate = asset.get('depreciationRate', 0)
        useful_life = asset.get('usefulLifeYears', 5)
        
        # No depreciation
        if depreciation_method == 'none' or depreciation_rate == 0:
            return purchase_price
        
        # Calculate years owned
        now = datetime.utcnow()
        years_owned = (now - purchase_date).days / 365.25
        
        if years_owned <= 0:
            return purchase_price
        
        # Straight-line depreciation
        if depreciation_method == 'straight_line':
            annual_depreciation = purchase_price * (depreciation_rate / 100) if depreciation_rate > 0 else (purchase_price / useful_life if useful_life > 0 else 0)
            total_depreciation = annual_depreciation * years_owned
            return max(purchase_price - total_depreciation, 0)
        
        # Reducing balance depreciation
        elif depreciation_method == 'reducing_balance':
            book_value = purchase_price
            full_years = int(years_owned)
            partial_year = years_owned - full_years
            
            # Apply full years
            for _ in range(full_years):
                book_value = book_value * (1 - (depreciation_rate / 100))
            
            # Apply partial year
            if partial_year > 0:
                book_value = book_value * (1 - (depreciation_rate / 100 * partial_year))
            
            return max(book_value, 0)
        
        # Fallback
        return purchase_price

    @assets_bp.route('', methods=['GET'])
    @token_required
    def get_assets(current_user):
        """Get all assets for the authenticated user with optional filters"""
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
            valid_fields = ['createdAt', 'purchaseDate', 'assetName', 'currentValue', 'purchasePrice']
            sort_field = sort_by if sort_by in valid_fields else 'createdAt'

            # Get assets with pagination
            assets = list(mongo.db.assets.find(query)
                         .sort(sort_field, sort_direction)
                         .skip(offset)
                         .limit(limit))
            total = mongo.db.assets.count_documents(query)

            # Serialize assets
            asset_list = []
            for asset in assets:
                asset_data = serialize_doc(asset.copy())
                # Ensure dates are ISO format with Z
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

    @assets_bp.route('/<asset_id>', methods=['GET'])
    @token_required
    def get_asset(current_user, asset_id):
        """Get a single asset by ID"""
        try:
            if not ObjectId.is_valid(asset_id):
                return jsonify({'success': False, 'message': 'Invalid asset ID'}), 400

            asset = mongo.db.assets.find_one({
                '_id': ObjectId(asset_id),
                'userId': current_user['_id']
            })

            if not asset:
                return jsonify({
                    'success': False,
                    'message': 'Asset not found'
                }), 404

            asset_data = serialize_doc(asset.copy())
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

    @assets_bp.route('', methods=['POST'])
    @token_required
    def create_asset(current_user):
        """Create a new asset (costs 2 FCs for non-premium users)"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': 'No data provided'}), 400

            # Validation
            errors = {}
            if not data.get('assetName'):
                errors['assetName'] = ['Asset name is required']
            if not data.get('category'):
                errors['category'] = ['Category is required']
            if not data.get('purchasePrice') or float(data.get('purchasePrice', 0)) <= 0:
                errors['purchasePrice'] = ['Valid purchase price is required']
            if 'currentValue' not in data or float(data.get('currentValue', -1)) < 0:
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

            # Check if user is premium subscriber or admin (they get unlimited access)
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            is_admin = user.get('isAdmin', False)
            
            # ✅ CRITICAL FIX: Validate subscription end date, not just flag
            is_subscribed = user.get('isSubscribed', False)
            subscription_end = user.get('subscriptionEndDate')
            is_premium = is_admin or (is_subscribed and subscription_end and subscription_end > datetime.utcnow())
            
            # FC Cost: 2 FCs for creating an asset (premium users bypass this)
            if not is_premium:
                fc_cost = 2.0
                current_balance = user.get('ficoreCreditBalance', 0.0)
                
                if current_balance < fc_cost:
                    return jsonify({
                        'success': False,
                        'message': f'Insufficient credits. Need {fc_cost} FCs, have {current_balance} FCs',
                        'errors': {
                            'credits': [f'This operation requires {fc_cost} FCs. Please purchase credits or upgrade to premium.']
                        },
                        'data': {
                            'requiredCredits': fc_cost,
                            'currentBalance': current_balance,
                            'shortfall': fc_cost - current_balance
                        }
                    }), 402  # Payment Required
                
                # Deduct credits
                new_balance = current_balance - fc_cost
                mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'ficoreCreditBalance': new_balance}}
                )
                
                # Record credit transaction
                credit_transaction = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'type': 'debit',
                    'amount': fc_cost,
                    'description': f'Asset creation - {data.get("assetName", "New Asset")}',
                    'operation': 'create_asset',
                    'balanceBefore': current_balance,
                    'balanceAfter': new_balance,
                    'status': 'completed',
                    'createdAt': datetime.utcnow(),
                    'metadata': {
                        'operation': 'create_asset',
                        'deductionType': 'app_usage',
                        'assetName': data.get('assetName', 'Unknown')
                    }
                }
                mongo.db.credit_transactions.insert_one(credit_transaction)

            # Parse dates
            try:
                purchase_date = datetime.fromisoformat(data['purchaseDate'].replace('Z', '+00:00').replace('+00:00', ''))
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid purchase date format',
                    'errors': {'purchaseDate': ['Use ISO format (e.g., 2025-01-01T00:00:00Z)']}
                }), 400

            disposal_date = None
            if data.get('disposalDate'):
                try:
                    disposal_date = datetime.fromisoformat(data['disposalDate'].replace('Z', '+00:00').replace('+00:00', ''))
                except:
                    pass  # ignore invalid disposal date

            now = datetime.utcnow()
            asset_doc = {
                'userId': current_user['_id'],
                'assetName': data['assetName'].strip(),
                'assetCode': data.get('assetCode').strip() if data.get('assetCode') else None,
                'description': data.get('description').strip() if data.get('description') else None,
                'category': data['category'],
                'purchasePrice': float(data['purchasePrice']),
                'currentValue': float(data['currentValue']),
                'purchaseDate': purchase_date,
                'supplier': data.get('supplier').strip() if data.get('supplier') else None,
                'location': data.get('location').strip() if data.get('location') else None,
                'status': data['status'],
                'depreciationRate': float(data['depreciationRate']) if data.get('depreciationRate') else None,
                'depreciationMethod': data['depreciationMethod'],
                'usefulLifeYears': int(data['usefulLifeYears']) if data.get('usefulLifeYears') else None,
                'attachments': data.get('attachments', []),
                'notes': data.get('notes').strip() if data.get('notes') else None,
                'disposalDate': disposal_date,
                'disposalValue': float(data['disposalValue']) if data.get('disposalValue') else None,
                'createdAt': now,
                'updatedAt': now,
                # NEW: Manual adjustment fields (Option C layer)
                'manualValueAdjustment': float(data['manualValueAdjustment']) if data.get('manualValueAdjustment') else None,
                'lastValueUpdate': now if data.get('manualValueAdjustment') else None,
                'valueAdjustmentReason': data.get('valueAdjustmentReason').strip() if data.get('valueAdjustmentReason') else None,
            }

            result = mongo.db.assets.insert_one(asset_doc)
            asset_doc['_id'] = result.inserted_id

            asset_data = serialize_doc(asset_doc)
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

    @assets_bp.route('/<asset_id>', methods=['PUT'])
    @token_required
    def update_asset(current_user, asset_id):
        """Update an existing asset"""
        try:
            if not ObjectId.is_valid(asset_id):
                return jsonify({'success': False, 'message': 'Invalid asset ID'}), 400

            existing = mongo.db.assets.find_one({
                '_id': ObjectId(asset_id),
                'userId': current_user['_id']
            })
            if not existing:
                return jsonify({'success': False, 'message': 'Asset not found'}), 404

            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': 'No data provided'}), 400

            update_data = {'updatedAt': datetime.utcnow()}

            if 'assetName' in data:
                update_data['assetName'] = data['assetName'].strip() if data['assetName'] else None
            if 'assetCode' in data:
                update_data['assetCode'] = data['assetCode'].strip() if data['assetCode'] else None
            if 'description' in data:
                update_data['description'] = data['description'].strip() if data['description'] else None
            if 'category' in data:
                update_data['category'] = data['category']
            if 'purchasePrice' in data:
                update_data['purchasePrice'] = float(data['purchasePrice'])
            if 'currentValue' in data:
                update_data['currentValue'] = float(data['currentValue'])
            if 'purchaseDate' in data:
                try:
                    update_data['purchaseDate'] = datetime.fromisoformat(data['purchaseDate'].replace('Z', '+00:00').replace('+00:00', ''))
                except:
                    pass
            if 'supplier' in data:
                update_data['supplier'] = data['supplier'].strip() if data['supplier'] else None
            if 'location' in data:
                update_data['location'] = data['location'].strip() if data['location'] else None
            if 'status' in data:
                update_data['status'] = data['status']
            if 'depreciationRate' in data:
                update_data['depreciationRate'] = float(v) if (v := data.get('depreciationRate')) else None
            if 'depreciationMethod' in data:
                update_data['depreciationMethod'] = data['depreciationMethod']
            if 'usefulLifeYears' in data:
                update_data['usefulLifeYears'] = int(v) if (v := data.get('usefulLifeYears')) else None
            if 'attachments' in data:
                update_data['attachments'] = data['attachments']
            if 'notes' in data:
                update_data['notes'] = data['notes'].strip() if data['notes'] else None
            if 'disposalDate' in data:
                if data['disposalDate']:
                    try:
                        update_data['disposalDate'] = datetime.fromisoformat(data['disposalDate'].replace('Z', '+00:00').replace('+00:00', ''))
                    except:
                        pass
                else:
                    update_data['disposalDate'] = None
            if 'disposalValue' in data:
                update_data['disposalValue'] = float(v) if (v := data.get('disposalValue')) else None
            
            # NEW: Handle manual value adjustments (Option C layer)
            if 'manualValueAdjustment' in data:
                if data['manualValueAdjustment'] is not None:
                    update_data['manualValueAdjustment'] = float(data['manualValueAdjustment'])
                    update_data['lastValueUpdate'] = datetime.utcnow()
                else:
                    # Clear manual adjustment
                    update_data['manualValueAdjustment'] = None
                    update_data['lastValueUpdate'] = None
            
            if 'valueAdjustmentReason' in data:
                update_data['valueAdjustmentReason'] = data['valueAdjustmentReason'].strip() if data['valueAdjustmentReason'] else None

            mongo.db.assets.update_one(
                {'_id': ObjectId(asset_id), 'userId': current_user['_id']},
                {'$set': update_data}
            )

            updated = mongo.db.assets.find_one({'_id': ObjectId(asset_id)})
            asset_data = serialize_doc(updated)
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

    @assets_bp.route('/<asset_id>', methods=['DELETE'])
    @token_required
    def delete_asset(current_user, asset_id):
        """Delete an asset (costs 2 FCs for non-premium users)"""
        try:
            if not ObjectId.is_valid(asset_id):
                return jsonify({'success': False, 'message': 'Invalid asset ID'}), 400

            # Check if asset exists and belongs to user
            asset = mongo.db.assets.find_one({
                '_id': ObjectId(asset_id),
                'userId': current_user['_id']
            })
            
            if not asset:
                return jsonify({'success': False, 'message': 'Asset not found'}), 404

            # Check if user is premium subscriber or admin (they get unlimited access)
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            is_admin = user.get('isAdmin', False)
            
            # ✅ CRITICAL FIX: Validate subscription end date, not just flag
            is_subscribed = user.get('isSubscribed', False)
            subscription_end = user.get('subscriptionEndDate')
            is_premium = is_admin or (is_subscribed and subscription_end and subscription_end > datetime.utcnow())
            
            # FC Cost: 2 FCs for deleting an asset (premium users bypass this)
            if not is_premium:
                fc_cost = 2.0
                current_balance = user.get('ficoreCreditBalance', 0.0)
                
                if current_balance < fc_cost:
                    return jsonify({
                        'success': False,
                        'message': f'Insufficient credits. Need {fc_cost} FCs, have {current_balance} FCs',
                        'errors': {
                            'credits': [f'This operation requires {fc_cost} FCs. Please purchase credits or upgrade to premium.']
                        },
                        'data': {
                            'requiredCredits': fc_cost,
                            'currentBalance': current_balance,
                            'shortfall': fc_cost - current_balance
                        }
                    }), 402  # Payment Required
                
                # Deduct credits
                new_balance = current_balance - fc_cost
                mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'ficoreCreditBalance': new_balance}}
                )
                
                # Record credit transaction
                credit_transaction = {
                    '_id': ObjectId(),
                    'userId': current_user['_id'],
                    'type': 'debit',
                    'amount': fc_cost,
                    'description': f'Asset deletion - {asset.get("assetName", "Asset")}',
                    'operation': 'delete_asset',
                    'balanceBefore': current_balance,
                    'balanceAfter': new_balance,
                    'status': 'completed',
                    'createdAt': datetime.utcnow(),
                    'metadata': {
                        'operation': 'delete_asset',
                        'deductionType': 'app_usage',
                        'assetName': asset.get('assetName', 'Unknown'),
                        'assetId': str(asset_id)
                    }
                }
                mongo.db.credit_transactions.insert_one(credit_transaction)

            # Delete the asset
            result = mongo.db.assets.delete_one({
                '_id': ObjectId(asset_id),
                'userId': current_user['_id']
            })

            if result.deleted_count == 0:
                return jsonify({'success': False, 'message': 'Asset not found'}), 404

            return jsonify({
                'success': True,
                'message': 'Asset deleted successfully'
            })

        except Exception as e:
            print(f"Error in delete_asset: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to delete asset',
                'errors': {'general': [str(e)]}
            }), 500

    @assets_bp.route('/summary', methods=['GET'])
    @token_required
    def get_asset_summary(current_user):
        """
        Get asset summary statistics for the authenticated user
        OPTION A + C HYBRID: Calculates book values on-the-fly
        """
        try:
            # Get all assets for the user
            all_assets = list(mongo.db.assets.find({'userId': current_user['_id']}))
            
            # Initialize counters
            total_assets = len(all_assets)
            active_assets = 0
            disposed_assets = 0
            total_purchase_value = 0.0
            total_current_value = 0.0
            category_breakdown = {}
            
            # Calculate values on-the-fly for each asset
            for asset in all_assets:
                status = asset.get('status', 'active')
                
                if status == 'active':
                    active_assets += 1
                    purchase_price = asset.get('purchasePrice', 0)
                    book_value = calculate_asset_book_value(asset)
                    
                    total_purchase_value += purchase_price
                    total_current_value += book_value
                    
                    # Category breakdown
                    category = asset.get('category', 'Other')
                    category_breakdown[category] = category_breakdown.get(category, 0) + book_value
                    
                elif status == 'disposed':
                    disposed_assets += 1
            
            total_depreciation = total_purchase_value - total_current_value

            threshold = 250_000_000.0  # ₦250M
            qualifies_for_zero_tax = total_current_value <= threshold
            remaining_threshold = max(threshold - total_current_value, 0)

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
                'message': 'Asset summary retrieved successfully (calculated on-the-fly)'
            })

        except Exception as e:
            print(f"Error in get_asset_summary: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve asset summary',
                'errors': {'general': [str(e)]}
            }), 500

    @assets_bp.route('/search', methods=['GET'])
    @token_required
    def search_assets(current_user):
        """Search assets by name, code, description, etc."""
        try:
            query_text = request.args.get('q', '').strip()
            if not query_text:
                return jsonify({
                    'success': True,
                    'data': [],
                    'message': 'No search query provided'
                })

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

            assets = list(mongo.db.assets.find(search_query)
                         .sort('createdAt', -1)
                         .limit(50))

            asset_list = []
            for asset in assets:
                data = serialize_doc(asset.copy())
                data['purchaseDate'] = data['purchaseDate'].isoformat() + 'Z'
                data['createdAt'] = data['createdAt'].isoformat() + 'Z'
                data['updatedAt'] = data['updatedAt'].isoformat() + 'Z'
                if data.get('disposalDate'):
                    data['disposalDate'] = data['disposalDate'].isoformat() + 'Z'
                asset_list.append(data)

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

    return assets_bp
