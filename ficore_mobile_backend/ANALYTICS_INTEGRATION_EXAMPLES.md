# Analytics Integration Examples

This document shows how to integrate analytics tracking into your existing endpoints.

## Quick Start

### 1. Import the Tracker

Add this to the top of your blueprint file:

```python
from utils.analytics_tracker import create_tracker
```

### 2. Initialize in Blueprint

```python
def init_your_blueprint(mongo, token_required, serialize_doc):
    your_bp = Blueprint('your_module', __name__, url_prefix='/api/your-module')
    
    # Create tracker instance
    tracker = create_tracker(mongo.db)
    
    # Your routes...
    return your_bp
```

### 3. Track Events in Routes

```python
@your_bp.route('/action', methods=['POST'])
@token_required
def your_action(current_user):
    try:
        # Your business logic here
        result = do_something()
        
        # Track the event (non-blocking)
        try:
            tracker.track_event(
                user_id=current_user['_id'],
                event_type='your_event_type',
                event_details={'key': 'value'}
            )
        except Exception as e:
            print(f"Analytics tracking failed: {e}")
            # Continue with normal flow
        
        return jsonify({'success': True, 'data': result})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
```

## Real-World Examples

### Example 1: Track Login (auth.py)

```python
# In blueprints/auth.py

from utils.analytics_tracker import create_tracker

def init_auth_blueprint(mongo, app_config):
    auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
    auth_bp.mongo = mongo
    auth_bp.config = app_config
    
    # Create tracker
    tracker = create_tracker(mongo.db)
    
    @auth_bp.route('/login', methods=['POST'])
    def login():
        try:
            # ... existing login logic ...
            
            # After successful authentication
            user = auth_bp.mongo.db.users.find_one({'email': email})
            
            # Track login event
            try:
                device_info = {
                    'user_agent': request.headers.get('User-Agent', 'Unknown'),
                    'ip_address': request.remote_addr
                }
                tracker.track_login(user['_id'], device_info=device_info)
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({
                'success': True,
                'data': {
                    'token': access_token,
                    'user': user_data
                }
            })
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @auth_bp.route('/signup', methods=['POST'])
    def signup():
        try:
            # ... existing signup logic ...
            
            # After successful registration
            result = auth_bp.mongo.db.users.insert_one(user_data)
            
            # Track registration event
            try:
                tracker.track_registration(result.inserted_id)
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({'success': True, 'data': response_data})
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    return auth_bp
```

### Example 2: Track Income Creation (income.py)

```python
# In blueprints/income.py

from utils.analytics_tracker import create_tracker

def init_income_blueprint(mongo, token_required, serialize_doc):
    income_bp = Blueprint('income', __name__, url_prefix='/api/income')
    
    # Create tracker
    tracker = create_tracker(mongo.db)
    
    @income_bp.route('/', methods=['POST'])
    @token_required
    def create_income(current_user):
        try:
            data = request.get_json()
            
            # ... existing income creation logic ...
            
            income_data = {
                'userId': current_user['_id'],
                'amount': data['amount'],
                'source': data['source'],
                'category': data.get('category', 'Other'),
                'dateReceived': datetime.utcnow(),
                'createdAt': datetime.utcnow()
            }
            
            result = mongo.db.incomes.insert_one(income_data)
            
            # Track income creation event
            try:
                tracker.track_income_created(
                    user_id=current_user['_id'],
                    amount=data['amount'],
                    category=data.get('category'),
                    source=data['source']
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({
                'success': True,
                'data': serialize_doc(income_data),
                'message': 'Income created successfully'
            }), 201
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @income_bp.route('/<income_id>', methods=['PUT'])
    @token_required
    def update_income(current_user, income_id):
        try:
            # ... existing update logic ...
            
            # Track update event
            try:
                tracker.track_event(
                    user_id=current_user['_id'],
                    event_type='income_entry_updated',
                    event_details={'income_id': income_id}
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({'success': True, 'message': 'Income updated'})
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @income_bp.route('/<income_id>', methods=['DELETE'])
    @token_required
    def delete_income(current_user, income_id):
        try:
            # ... existing delete logic ...
            
            # Track deletion event
            try:
                tracker.track_event(
                    user_id=current_user['_id'],
                    event_type='income_entry_deleted',
                    event_details={'income_id': income_id}
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({'success': True, 'message': 'Income deleted'})
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    return income_bp
```

### Example 3: Track Expense Creation (expenses.py)

```python
# In blueprints/expenses.py

from utils.analytics_tracker import create_tracker

def init_expenses_blueprint(mongo, token_required, serialize_doc):
    expenses_bp = Blueprint('expenses', __name__, url_prefix='/api/expenses')
    
    # Create tracker
    tracker = create_tracker(mongo.db)
    
    @expenses_bp.route('/', methods=['POST'])
    @token_required
    def create_expense(current_user):
        try:
            data = request.get_json()
            
            # ... existing expense creation logic ...
            
            expense_data = {
                'userId': current_user['_id'],
                'amount': data['amount'],
                'category': data['category'],
                'description': data.get('description', ''),
                'date': datetime.utcnow(),
                'createdAt': datetime.utcnow()
            }
            
            result = mongo.db.expenses.insert_one(expense_data)
            
            # Track expense creation event
            try:
                tracker.track_expense_created(
                    user_id=current_user['_id'],
                    amount=data['amount'],
                    category=data['category']
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({
                'success': True,
                'data': serialize_doc(expense_data),
                'message': 'Expense created successfully'
            }), 201
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    return expenses_bp
```

### Example 4: Track Profile Updates (users.py)

```python
# In blueprints/users.py

from utils.analytics_tracker import create_tracker

def init_users_blueprint(mongo, token_required):
    users_bp = Blueprint('users', __name__, url_prefix='/api/users')
    
    # Create tracker
    tracker = create_tracker(mongo.db)
    
    @users_bp.route('/profile', methods=['PUT'])
    @token_required
    def update_profile(current_user):
        try:
            data = request.get_json()
            
            # Track which fields were updated
            fields_updated = list(data.keys())
            
            # ... existing profile update logic ...
            
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': data}
            )
            
            # Track profile update event
            try:
                tracker.track_profile_updated(
                    user_id=current_user['_id'],
                    fields_updated=fields_updated
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({
                'success': True,
                'message': 'Profile updated successfully'
            })
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    return users_bp
```

### Example 5: Track Subscription Events (subscription.py)

```python
# In blueprints/subscription.py

from utils.analytics_tracker import create_tracker

def init_subscription_blueprint(mongo, token_required, serialize_doc):
    subscription_bp = Blueprint('subscription', __name__, url_prefix='/api/subscription')
    
    # Create tracker
    tracker = create_tracker(mongo.db)
    
    @subscription_bp.route('/subscribe', methods=['POST'])
    @token_required
    def subscribe(current_user):
        try:
            data = request.get_json()
            subscription_type = data.get('type', 'monthly')
            
            # ... existing subscription logic ...
            
            # Track subscription start event
            try:
                tracker.track_subscription_started(
                    user_id=current_user['_id'],
                    subscription_type=subscription_type,
                    amount=data.get('amount')
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({
                'success': True,
                'message': 'Subscription activated'
            })
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @subscription_bp.route('/cancel', methods=['POST'])
    @token_required
    def cancel_subscription(current_user):
        try:
            # ... existing cancellation logic ...
            
            # Track subscription cancellation
            try:
                tracker.track_event(
                    user_id=current_user['_id'],
                    event_type='subscription_cancelled'
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({
                'success': True,
                'message': 'Subscription cancelled'
            })
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    return subscription_bp
```

### Example 6: Track Dashboard Views (dashboard.py)

```python
# In blueprints/dashboard.py

from utils.analytics_tracker import create_tracker

def init_dashboard_blueprint(mongo, token_required, serialize_doc):
    dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')
    
    # Create tracker
    tracker = create_tracker(mongo.db)
    
    @dashboard_bp.route('/', methods=['GET'])
    @token_required
    def get_dashboard(current_user):
        try:
            # Track dashboard view
            try:
                tracker.track_dashboard_view(current_user['_id'])
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            # ... existing dashboard logic ...
            
            return jsonify({
                'success': True,
                'data': dashboard_data
            })
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    return dashboard_bp
```

### Example 7: Track Tax Calculations (tax.py)

```python
# In blueprints/tax.py

from utils.analytics_tracker import create_tracker

def init_tax_blueprint(mongo, token_required, serialize_doc):
    tax_bp = Blueprint('tax', __name__, url_prefix='/api/tax')
    
    # Create tracker
    tracker = create_tracker(mongo.db)
    
    @tax_bp.route('/calculate', methods=['POST'])
    @token_required
    def calculate_tax(current_user):
        try:
            data = request.get_json()
            tax_year = data.get('tax_year')
            
            # ... existing tax calculation logic ...
            
            # Track tax calculation event
            try:
                tracker.track_tax_calculation(
                    user_id=current_user['_id'],
                    tax_year=tax_year
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")
            
            return jsonify({
                'success': True,
                'data': calculation_result
            })
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    return tax_bp
```

## Best Practices

### 1. Always Use Try-Catch

Never let analytics tracking break your main functionality:

```python
try:
    tracker.track_event(...)
except Exception as e:
    print(f"Analytics tracking failed: {e}")
    # Continue with normal flow
```

### 2. Track After Success

Only track events after the main operation succeeds:

```python
# ✅ Good
result = mongo.db.collection.insert_one(data)
tracker.track_event(...)  # Track after success

# ❌ Bad
tracker.track_event(...)  # Don't track before operation
result = mongo.db.collection.insert_one(data)
```

### 3. Include Relevant Details

Add context to help with analysis:

```python
# ✅ Good - includes useful context
tracker.track_event(
    user_id=current_user['_id'],
    event_type='income_entry_created',
    event_details={
        'amount': 1500.0,
        'category': 'Salary',
        'source': 'Main Job',
        'frequency': 'monthly'
    }
)

# ❌ Bad - no context
tracker.track_event(
    user_id=current_user['_id'],
    event_type='income_entry_created'
)
```

### 4. Don't Track Sensitive Data

Never include passwords, tokens, or PII:

```python
# ❌ Bad - includes sensitive data
tracker.track_event(
    user_id=current_user['_id'],
    event_type='profile_updated',
    event_details={
        'password': 'secret123',  # Never do this!
        'ssn': '123-45-6789'      # Never do this!
    }
)

# ✅ Good - only tracks field names
tracker.track_event(
    user_id=current_user['_id'],
    event_type='profile_updated',
    event_details={
        'fields_updated': ['firstName', 'lastName', 'phone']
    }
)
```

### 5. Use Descriptive Event Types

Make event types clear and consistent:

```python
# ✅ Good - clear and consistent
'income_entry_created'
'expense_entry_updated'
'subscription_started'

# ❌ Bad - unclear or inconsistent
'income_add'
'expense_edit'
'sub_start'
```

## Testing Analytics

### Test Event Tracking

```python
# Test in Python shell or test file
from utils.analytics_tracker import create_tracker
from flask_pymongo import PyMongo
from bson import ObjectId

# Create tracker
tracker = create_tracker(mongo.db)

# Test tracking
user_id = ObjectId('507f1f77bcf86cd799439011')
result = tracker.track_login(user_id)
print(f"Tracking successful: {result}")

# Verify event was created
event = mongo.db.analytics_events.find_one({
    'userId': user_id,
    'eventType': 'user_logged_in'
})
print(f"Event found: {event}")
```

### Test API Endpoint

```bash
# Track an event via API
curl -X POST http://localhost:5000/api/analytics/track \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "eventType": "income_entry_created",
    "eventDetails": {
      "amount": 1500.0,
      "category": "Salary"
    }
  }'
```

## Rollout Strategy

### Phase 1: Core Events (Week 1)
- User login/registration
- Income/expense creation

### Phase 2: Feature Events (Week 2)
- Profile updates
- Dashboard views
- Report generation

### Phase 3: Business Events (Week 3)
- Subscription events
- Tax calculations
- Business suite features

### Phase 4: Optimization (Week 4)
- Review tracked data
- Add missing events
- Optimize event details
- Implement data retention

## Monitoring

Check analytics health regularly:

```python
# Count events by type
pipeline = [
    {'$group': {
        '_id': '$eventType',
        'count': {'$sum': 1}
    }},
    {'$sort': {'count': -1}}
]

results = mongo.db.analytics_events.aggregate(pipeline)
for result in results:
    print(f"{result['_id']}: {result['count']}")
```

## Support

If you encounter issues:
1. Check server logs for tracking errors
2. Verify the `analytics_events` collection exists
3. Ensure indexes are created
4. Test with a simple event first
5. Review the main README for troubleshooting
