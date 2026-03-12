from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
import traceback

def init_subscription_discounts_blueprint(mongo, token_required, serialize_doc, limiter=None):
    subscription_discounts_bp = Blueprint('subscription_discounts', __name__, url_prefix='/subscription')
    
    @subscription_discounts_bp.route('/discounts', methods=['GET'])
    @token_required
    def get_available_discounts(current_user):
        """Get available subscription discounts for the user"""
        try:
            # Validate user exists
            if not current_user or '_id' not in current_user:
                return jsonify({
                    'success': False,
                    'message': 'Invalid user session'
                }), 401

            # Get user's available discount IDs
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            if not user:
                return jsonify({
                    'success': False,
                    'message': 'User not found'
                }), 404

            discount_ids = user.get('available_subscription_discounts', [])
            
            if not discount_ids:
                return jsonify({
                    'success': True,
                    'data': [],
                    'message': 'No discounts available'
                })

            # Get discount details
            discounts = []
            for discount_id in discount_ids:
                try:
                    discount = mongo.db.subscription_discounts.find_one({
                        '_id': ObjectId(discount_id),
                        'user_id': current_user['_id'],
                        'used': False,
                        'expires_at': {'$gt': datetime.utcnow()}
                    })
                    
                    if discount:
                        discounts.append({
                            'id': str(discount['_id']),
                            'discount_percentage': discount['discount_percentage'],
                            'description': discount.get('description', ''),
                            'created_at': discount['created_at'].isoformat() + 'Z',
                            'expires_at': discount['expires_at'].isoformat() + 'Z',
                            'milestone_type': discount.get('milestone_type'),
                            'milestone_value': discount.get('milestone_value')
                        })
                except Exception as e:
                    print(f"Error processing discount {discount_id}: {str(e)}")
                    continue

            return jsonify({
                'success': True,
                'data': discounts,
                'message': f'Found {len(discounts)} available discounts'
            })

        except Exception as e:
            print(f"Error in get_available_discounts: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve discounts',
                'errors': {'general': [str(e)]}
            }), 500

    @subscription_discounts_bp.route('/validate-discount', methods=['POST'])
    @token_required
    def validate_discount(current_user):
        """Validate a discount before applying"""
        try:
            data = request.get_json()
            
            if 'discount_id' not in data:
                return jsonify({
                    'success': False,
                    'message': 'Missing required field: discount_id'
                }), 400

            discount_id = data['discount_id']
            
            # Get discount record
            discount = mongo.db.subscription_discounts.find_one({
                '_id': ObjectId(discount_id),
                'user_id': current_user['_id']
            })
            
            if not discount:
                return jsonify({
                    'success': False,
                    'message': 'Discount not found'
                }), 404

            # Check if already used
            if discount.get('used', False):
                return jsonify({
                    'success': False,
                    'message': 'Discount has already been used'
                }), 400

            # Check if expired
            if discount['expires_at'] <= datetime.utcnow():
                return jsonify({
                    'success': False,
                    'message': 'Discount has expired'
                }), 400

            return jsonify({
                'success': True,
                'data': {
                    'id': str(discount['_id']),
                    'discount_percentage': discount['discount_percentage'],
                    'description': discount.get('description', ''),
                    'expires_at': discount['expires_at'].isoformat() + 'Z',
                    'valid': True
                },
                'message': 'Discount is valid'
            })

        except Exception as e:
            print(f"Error in validate_discount: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to validate discount',
                'errors': {'general': [str(e)]}
            }), 500

    @subscription_discounts_bp.route('/apply-discount', methods=['POST'])
    @token_required
    def apply_discount(current_user):
        """Apply a discount to a subscription purchase"""
        try:
            data = request.get_json()
            
            required_fields = ['discount_id', 'subscription_plan', 'original_amount']
            for field in required_fields:
                if field not in data:
                    return jsonify({
                        'success': False,
                        'message': f'Missing required field: {field}'
                    }), 400

            discount_id = data['discount_id']
            subscription_plan = data['subscription_plan']
            original_amount = float(data['original_amount'])
            
            # Validate discount first
            discount = mongo.db.subscription_discounts.find_one({
                '_id': ObjectId(discount_id),
                'user_id': current_user['_id'],
                'used': False,
                'expires_at': {'$gt': datetime.utcnow()}
            })
            
            if not discount:
                return jsonify({
                    'success': False,
                    'message': 'Invalid or expired discount'
                }), 400

            # Calculate discounted amount
            discount_percentage = discount['discount_percentage']
            discount_amount = original_amount * (discount_percentage / 100)
            final_amount = original_amount - discount_amount

            # Mark discount as used
            mongo.db.subscription_discounts.update_one(
                {'_id': ObjectId(discount_id)},
                {
                    '$set': {
                        'used': True,
                        'used_at': datetime.utcnow(),
                        'applied_to_plan': subscription_plan,
                        'original_amount': original_amount,
                        'discount_amount': discount_amount,
                        'final_amount': final_amount
                    }
                }
            )

            # Remove discount from user's available discounts
            user = mongo.db.users.find_one({'_id': current_user['_id']})
            available_discounts = user.get('available_subscription_discounts', [])
            if discount_id in available_discounts:
                available_discounts.remove(discount_id)
                mongo.db.users.update_one(
                    {'_id': current_user['_id']},
                    {'$set': {'available_subscription_discounts': available_discounts}}
                )

            # Create discount usage record
            usage_record = {
                '_id': ObjectId(),
                'user_id': current_user['_id'],
                'discount_id': ObjectId(discount_id),
                'subscription_plan': subscription_plan,
                'original_amount': original_amount,
                'discount_percentage': discount_percentage,
                'discount_amount': discount_amount,
                'final_amount': final_amount,
                'applied_at': datetime.utcnow(),
                'milestone_achievement': discount.get('milestone_achievement', False),
                'milestone_type': discount.get('milestone_type'),
                'milestone_value': discount.get('milestone_value')
            }
            mongo.db.discount_usage.insert_one(usage_record)

            return jsonify({
                'success': True,
                'data': {
                    'discount_id': discount_id,
                    'subscription_plan': subscription_plan,
                    'original_amount': original_amount,
                    'discount_percentage': discount_percentage,
                    'discount_amount': discount_amount,
                    'final_amount': final_amount,
                    'savings': discount_amount
                },
                'message': f'Discount applied successfully! You saved ₦{discount_amount:,.2f}'
            })

        except Exception as e:
            print(f"Error in apply_discount: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Failed to apply discount',
                'errors': {'general': [str(e)]}
            }), 500

    return subscription_discounts_bp