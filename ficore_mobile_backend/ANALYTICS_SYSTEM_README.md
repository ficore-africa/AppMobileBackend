# FiCore Analytics & Usage Tracking System

## Overview

This custom analytics system tracks user activity and provides an admin dashboard for monitoring key metrics. All data is stored in your own MongoDB database, giving you full control without relying on third-party services.

## Features

### 📊 Metrics Tracked

- **Active Users**: Daily (DAU), Weekly (WAU), Monthly (MAU)
- **User Growth**: New registrations over time
- **Entry Counts**: Income and expense entries
- **Event Tracking**: All user actions (logins, entries created, profile updates, etc.)
- **Top Users**: Most active users by event count
- **Recent Activity**: Real-time activity feed

### 🎯 Event Types

The system tracks the following events:

- `user_logged_in` - User authentication
- `user_registered` - New user signup
- `income_entry_created` - Income entry added
- `income_entry_updated` - Income entry modified
- `income_entry_deleted` - Income entry removed
- `expense_entry_created` - Expense entry added
- `expense_entry_updated` - Expense entry modified
- `expense_entry_deleted` - Expense entry removed
- `profile_updated` - User profile changes
- `subscription_started` - Subscription activated
- `subscription_cancelled` - Subscription cancelled
- `tax_calculation_performed` - Tax calculation run
- `tax_module_completed` - Tax education module finished
- `debtor_created` - New debtor added
- `creditor_created` - New creditor added
- `inventory_item_created` - New inventory item
- `asset_created` - New asset registered
- `dashboard_viewed` - Dashboard accessed
- `report_generated` - Report created

## Architecture

### Database Schema

**Collection**: `analytics_events`

```javascript
{
  _id: ObjectId,
  userId: ObjectId,              // Reference to users._id
  eventType: String,             // Event type (see list above)
  timestamp: DateTime,           // When event occurred
  eventDetails: Object,          // Optional event-specific data
  deviceInfo: Object,            // Optional device information
  sessionId: String,             // Optional session identifier
  createdAt: DateTime            // Record creation timestamp
}
```

**Indexes**:
- `userId + timestamp` (descending)
- `eventType + timestamp` (descending)
- `timestamp` (descending)
- `userId + eventType`

## API Endpoints

### 1. Track Event (Client-Side)

**POST** `/api/analytics/track`

Track a user activity event from your mobile app.

**Headers**:
```
Authorization: Bearer <user_token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "eventType": "income_entry_created",
  "eventDetails": {
    "amount": 1500.00,
    "category": "Salary",
    "source": "Main Job"
  },
  "deviceInfo": {
    "platform": "Android",
    "version": "1.0.0",
    "osVersion": "13"
  },
  "sessionId": "optional-session-id"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Event tracked successfully",
  "data": {
    "eventId": "507f1f77bcf86cd799439011"
  }
}
```

### 2. Dashboard Overview (Admin Only)

**GET** `/api/analytics/dashboard/overview`

Get high-level dashboard metrics.

**Headers**:
```
Authorization: Bearer <admin_token>
```

**Response**:
```json
{
  "success": true,
  "data": {
    "users": {
      "total": 1250,
      "dailyActive": 45,
      "weeklyActive": 320,
      "monthlyActive": 890
    },
    "entries": {
      "totalIncome": 5420,
      "totalExpense": 8930,
      "incomeThisMonth": 450,
      "expenseThisMonth": 720
    },
    "recentActivity": [
      {
        "eventType": "user_logged_in",
        "timestamp": "2025-12-02T10:30:00Z",
        "userEmail": "user@example.com",
        "userName": "John Doe"
      }
    ]
  }
}
```

### 3. Event Counts (Admin Only)

**GET** `/api/analytics/dashboard/event-counts?period=month`

Get event counts by type for a given period.

**Query Parameters**:
- `period`: `today`, `week`, `month`, `all` (default: `month`)

**Response**:
```json
{
  "success": true,
  "data": {
    "period": "month",
    "eventCounts": {
      "user_logged_in": 2340,
      "income_entry_created": 450,
      "expense_entry_created": 720,
      "dashboard_viewed": 1890
    }
  }
}
```

### 4. User Growth (Admin Only)

**GET** `/api/analytics/dashboard/user-growth`

Get user registration growth over the last 30 days.

**Response**:
```json
{
  "success": true,
  "data": {
    "growthData": [
      {
        "date": "2025-11-02",
        "newUsers": 12
      },
      {
        "date": "2025-11-03",
        "newUsers": 8
      }
    ]
  }
}
```

### 5. MAU Trend (Admin Only)

**GET** `/api/analytics/dashboard/mau-trend`

Get Monthly Active Users trend for the last 12 months.

**Response**:
```json
{
  "success": true,
  "data": {
    "mauTrend": [
      {
        "month": "2025-01",
        "mau": 450
      },
      {
        "month": "2025-02",
        "mau": 520
      }
    ]
  }
}
```

### 6. Top Users (Admin Only)

**GET** `/api/analytics/dashboard/top-users?limit=10&period=month`

Get most active users based on event count.

**Query Parameters**:
- `limit`: Number of users to return (default: 10)
- `period`: `week`, `month`, `all` (default: `month`)

**Response**:
```json
{
  "success": true,
  "data": {
    "topUsers": [
      {
        "userId": "507f1f77bcf86cd799439011",
        "email": "user@example.com",
        "name": "John Doe",
        "eventCount": 245
      }
    ]
  }
}
```

## Implementation Guide

### Backend Integration

#### Option 1: Using the Analytics Tracker Utility

```python
from utils.analytics_tracker import create_tracker

# In your blueprint initialization
tracker = create_tracker(mongo.db)

# Track events
@income_bp.route('/income', methods=['POST'])
@token_required
def create_income(current_user):
    # ... create income logic ...
    
    # Track the event
    tracker.track_income_created(
        user_id=current_user['_id'],
        amount=income_data['amount'],
        category=income_data.get('category'),
        source=income_data.get('source')
    )
    
    return jsonify(response)
```

#### Option 2: Direct Event Tracking

```python
from datetime import datetime

@auth_bp.route('/login', methods=['POST'])
def login():
    # ... authentication logic ...
    
    # Track login event
    mongo.db.analytics_events.insert_one({
        'userId': user['_id'],
        'eventType': 'user_logged_in',
        'timestamp': datetime.utcnow(),
        'eventDetails': None,
        'deviceInfo': request.headers.get('User-Agent'),
        'sessionId': None,
        'createdAt': datetime.utcnow()
    })
    
    return jsonify(response)
```

### Mobile App Integration (Flutter/Dart)

Create an analytics service in your Flutter app:

```dart
class AnalyticsService {
  final ApiService _apiService;
  
  AnalyticsService(this._apiService);
  
  Future<void> trackEvent({
    required String eventType,
    Map<String, dynamic>? eventDetails,
    Map<String, String>? deviceInfo,
  }) async {
    try {
      await _apiService.post('/api/analytics/track', {
        'eventType': eventType,
        'eventDetails': eventDetails,
        'deviceInfo': deviceInfo ?? await _getDeviceInfo(),
      });
    } catch (e) {
      // Fail silently - don't disrupt user experience
      print('Analytics tracking failed: $e');
    }
  }
  
  Future<Map<String, String>> _getDeviceInfo() async {
    final deviceInfo = DeviceInfoPlugin();
    // Get platform-specific info
    return {
      'platform': Platform.operatingSystem,
      'version': '1.0.0', // Your app version
    };
  }
  
  // Convenience methods
  Future<void> trackLogin() => trackEvent(eventType: 'user_logged_in');
  
  Future<void> trackIncomeCreated(double amount, String category) {
    return trackEvent(
      eventType: 'income_entry_created',
      eventDetails: {'amount': amount, 'category': category},
    );
  }
  
  Future<void> trackExpenseCreated(double amount, String category) {
    return trackEvent(
      eventType: 'expense_entry_created',
      eventDetails: {'amount': amount, 'category': category},
    );
  }
}
```

Usage in your app:

```dart
// After successful login
await analyticsService.trackLogin();

// After creating income
await analyticsService.trackIncomeCreated(1500.0, 'Salary');

// After creating expense
await analyticsService.trackExpenseCreated(500.0, 'Groceries');
```

## Admin Dashboard

### Accessing the Dashboard

1. **URL**: `http://your-backend-url/admin/analytics_dashboard.html`

2. **Authentication**: You'll need an admin JWT token
   - Login as admin via `/api/auth/login`
   - Copy the token from the response
   - Paste it when prompted by the dashboard

3. **Features**:
   - Real-time metrics display
   - Auto-refresh every 30 seconds
   - Manual refresh button
   - Event counts breakdown
   - Top users table
   - Recent activity feed

### Dashboard Metrics

The dashboard displays:

1. **User Metrics**
   - Total registered users
   - Daily active users (DAU)
   - Weekly active users (WAU)
   - Monthly active users (MAU)

2. **Entry Metrics**
   - Total income entries (all time)
   - Total expense entries (all time)
   - Income entries this month
   - Expense entries this month

3. **Event Breakdown**
   - Count of each event type for the selected period

4. **Top Users**
   - Most active users ranked by event count

5. **Recent Activity**
   - Last 10 user actions with timestamps

## Best Practices

### 1. Track Strategically

Don't track every single action. Focus on:
- Key user actions (login, registration)
- Core feature usage (entries created)
- Business-critical events (subscriptions, payments)

### 2. Fail Silently

Analytics tracking should never disrupt the user experience:

```python
try:
    tracker.track_event(...)
except Exception as e:
    print(f"Analytics error: {e}")
    # Continue with normal flow
```

### 3. Batch Tracking (Optional)

For high-volume events, consider batching:

```python
# Collect events in memory
events_batch = []

# Add to batch
events_batch.append(event_data)

# Insert in batches
if len(events_batch) >= 100:
    mongo.db.analytics_events.insert_many(events_batch)
    events_batch.clear()
```

### 4. Data Retention

Consider implementing data retention policies:

```python
# Delete events older than 1 year
from datetime import datetime, timedelta

one_year_ago = datetime.utcnow() - timedelta(days=365)
mongo.db.analytics_events.delete_many({
    'timestamp': {'$lt': one_year_ago}
})
```

### 5. Privacy Considerations

- Don't track sensitive personal information in `eventDetails`
- Anonymize user data when possible
- Comply with GDPR/privacy regulations
- Provide users with opt-out options

## Performance Optimization

### Indexes

The system creates optimized indexes automatically:
- Fast queries by user and time range
- Efficient event type filtering
- Quick recent activity lookups

### Query Optimization

Use MongoDB aggregation pipelines for complex queries:

```python
# Example: Get event counts by hour
pipeline = [
    {'$match': {'timestamp': {'$gte': start_date}}},
    {'$group': {
        '_id': {
            '$dateToString': {
                'format': '%Y-%m-%d %H:00',
                'date': '$timestamp'
            }
        },
        'count': {'$sum': 1}
    }},
    {'$sort': {'_id': 1}}
]

results = mongo.db.analytics_events.aggregate(pipeline)
```

## Troubleshooting

### Events Not Appearing

1. Check if the `analytics_events` collection exists
2. Verify user authentication token is valid
3. Check server logs for errors
4. Ensure event type is in the valid list

### Dashboard Not Loading

1. Verify admin token is correct
2. Check browser console for errors
3. Ensure backend is running and accessible
4. Verify CORS settings allow dashboard access

### Slow Dashboard Performance

1. Check database indexes are created
2. Consider adding data retention policies
3. Implement caching for frequently accessed metrics
4. Use aggregation pipelines instead of multiple queries

## Future Enhancements

Potential additions to the system:

1. **Cohort Analysis**: Track user retention over time
2. **Funnel Analysis**: Monitor conversion funnels
3. **A/B Testing**: Track feature experiments
4. **Custom Dashboards**: User-specific analytics views
5. **Export Functionality**: Download reports as CSV/PDF
6. **Alerts**: Notify admins of unusual activity
7. **Real-time Updates**: WebSocket-based live dashboard
8. **Advanced Visualizations**: Charts and graphs using Chart.js

## Privacy & Compliance

**IMPORTANT**: Before deploying analytics to production, review:

📋 **[ANALYTICS_PRIVACY_AND_CONSENT.md](ANALYTICS_PRIVACY_AND_CONSENT.md)**
- GDPR, CCPA, and privacy law compliance
- User consent implementation
- Data retention policies
- User data management endpoints

🏗️ **[ANALYTICS_TRACKING_ARCHITECTURE.md](ANALYTICS_TRACKING_ARCHITECTURE.md)**
- Automatic vs. client-side tracking
- Server-side data capture (IP, device info)
- Privacy-safe tracking practices
- Complete implementation guide

### Key Privacy Points

1. **User Consent Required**: Implement opt-in/opt-out mechanism
2. **IP Addresses**: Captured server-side, never sent from client
3. **Data Retention**: Implement 12-month retention policy
4. **User Rights**: Provide data access, deletion, and export
5. **No Sensitive Data**: Never track passwords, PII, or payment info

## Support

For questions or issues:
1. **Privacy/Compliance**: See `ANALYTICS_PRIVACY_AND_CONSENT.md`
2. **Architecture**: See `ANALYTICS_TRACKING_ARCHITECTURE.md`
3. **Quick Start**: See `ANALYTICS_QUICK_START.md`
4. **API Documentation**: This file
5. **Server Logs**: Check for tracking errors
6. **Testing**: Run `python test_analytics_system.py`

## License

This analytics system is part of the FiCore Mobile Backend and follows the same license terms.
