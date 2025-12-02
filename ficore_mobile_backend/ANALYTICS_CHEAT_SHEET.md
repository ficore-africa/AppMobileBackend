# Analytics System - Quick Reference

## 🚀 Quick Start

```bash
# 1. Start backend (analytics auto-initializes)
python app.py

# 2. Test the system
python test_analytics_system.py

# 3. Access dashboard
# http://localhost:5000/admin/analytics_dashboard.html
```

## 📊 Dashboard Access

```bash
# Get admin token
curl -X POST http://localhost:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@ficore.com","password":"admin123"}'

# Open: http://localhost:5000/admin/analytics_dashboard.html
# Paste token when prompted
```

## 🎯 Events Being Tracked

| Event | When | Details Captured |
|-------|------|------------------|
| `user_logged_in` | User logs in | Device info, IP |
| `user_registered` | New signup | Device info, IP |
| `income_entry_created` | Income added | Amount, category, source |
| `expense_entry_created` | Expense added | Amount, category |
| `profile_updated` | Profile changed | Fields updated |
| `subscription_started` | Subscription activated | Type, amount |
| `dashboard_viewed` | Dashboard accessed | - |
| `tax_calculation_performed` | Tax calculated | Tax year |

## 🔌 API Endpoints

### Client Tracking
```bash
POST /api/analytics/track
Authorization: Bearer USER_TOKEN

{
  "eventType": "income_entry_created",
  "eventDetails": {"amount": 1500, "category": "Salary"}
}
```

### Admin Dashboard
```bash
# Overview
GET /api/analytics/dashboard/overview
Authorization: Bearer ADMIN_TOKEN

# Event counts
GET /api/analytics/dashboard/event-counts?period=month
Authorization: Bearer ADMIN_TOKEN

# User growth
GET /api/analytics/dashboard/user-growth
Authorization: Bearer ADMIN_TOKEN

# MAU trend
GET /api/analytics/dashboard/mau-trend
Authorization: Bearer ADMIN_TOKEN

# Top users
GET /api/analytics/dashboard/top-users?limit=10&period=month
Authorization: Bearer ADMIN_TOKEN
```

## 💻 Code Examples

### Backend Tracking
```python
from utils.analytics_tracker import create_tracker

# Initialize
tracker = create_tracker(mongo.db)

# Track events
tracker.track_login(user_id)
tracker.track_income_created(user_id, amount=1500, category='Salary')
tracker.track_expense_created(user_id, amount=500, category='Groceries')
tracker.track_profile_updated(user_id, fields_updated=['firstName'])
tracker.track_subscription_started(user_id, 'monthly', amount=2500)
tracker.track_dashboard_view(user_id)
tracker.track_tax_calculation(user_id, tax_year=2025)

# Custom event
tracker.track_event(
    user_id=user_id,
    event_type='custom_event',
    event_details={'key': 'value'}
)
```

### Flutter/Dart Tracking
```dart
class AnalyticsService {
  final ApiService _apiService;
  
  Future<void> trackEvent(String eventType, [Map<String, dynamic>? details]) async {
    try {
      await _apiService.post('/api/analytics/track', {
        'eventType': eventType,
        'eventDetails': details,
      });
    } catch (e) {
      print('Analytics failed: $e');
    }
  }
  
  // Convenience methods
  Future<void> trackLogin() => trackEvent('user_logged_in');
  Future<void> trackIncomeCreated(double amount, String category) {
    return trackEvent('income_entry_created', {
      'amount': amount,
      'category': category
    });
  }
}
```

## 📈 Dashboard Metrics

| Metric | Description |
|--------|-------------|
| Total Users | All registered users |
| DAU | Daily Active Users (logged in today) |
| WAU | Weekly Active Users (logged in this week) |
| MAU | Monthly Active Users (logged in this month) |
| Total Income Entries | All-time income entries |
| Total Expense Entries | All-time expense entries |
| Income This Month | Income entries this month |
| Expense This Month | Expense entries this month |

## 🔍 Query Examples

### MongoDB Shell
```javascript
// Count total events
db.analytics_events.countDocuments({})

// Events by type
db.analytics_events.aggregate([
  {$group: {_id: '$eventType', count: {$sum: 1}}},
  {$sort: {count: -1}}
])

// Recent events
db.analytics_events.find().sort({timestamp: -1}).limit(10)

// User's events
db.analytics_events.find({userId: ObjectId('...')})

// Events today
db.analytics_events.find({
  timestamp: {$gte: new Date(new Date().setHours(0,0,0,0))}
})
```

### Python
```python
from flask_pymongo import PyMongo
from datetime import datetime, timedelta

# Total events
total = mongo.db.analytics_events.count_documents({})

# Events by type
pipeline = [
    {'$group': {'_id': '$eventType', 'count': {'$sum': 1}}},
    {'$sort': {'count': -1}}
]
results = list(mongo.db.analytics_events.aggregate(pipeline))

# MAU
month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
mau = mongo.db.analytics_events.distinct('userId', {
    'eventType': 'user_logged_in',
    'timestamp': {'$gte': month_start}
})
print(f"MAU: {len(mau)}")
```

## 🛠️ Maintenance

### Check System Health
```bash
python test_analytics_system.py
```

### View Recent Events
```python
events = mongo.db.analytics_events.find().sort('timestamp', -1).limit(10)
for e in events:
    print(f"{e['timestamp']} - {e['eventType']}")
```

### Clean Old Data
```python
from datetime import datetime, timedelta

# Delete events older than 1 year
one_year_ago = datetime.utcnow() - timedelta(days=365)
mongo.db.analytics_events.delete_many({'timestamp': {'$lt': one_year_ago}})
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Events not appearing | Check server logs, verify collection exists |
| Dashboard not loading | Verify admin token, check browser console |
| Slow queries | Check indexes, implement data retention |
| Tracking errors | Check MongoDB connection, verify user_id |

## 📝 Files Reference

| File | Purpose |
|------|---------|
| `models.py` | Database schema with analytics_events |
| `blueprints/analytics.py` | Analytics API endpoints |
| `utils/analytics_tracker.py` | Tracking utility functions |
| `admin_web_app/analytics_dashboard.html` | Dashboard UI |
| `test_analytics_system.py` | System test script |
| `ANALYTICS_SYSTEM_README.md` | Full documentation |
| `ANALYTICS_QUICK_START.md` | Quick start guide |
| `ANALYTICS_IMPLEMENTATION_COMPLETE.md` | Implementation summary |

## 🎯 Integration Status

✅ Auth Blueprint - Login & Registration
✅ Income Blueprint - Income entries
✅ Expenses Blueprint - Expense entries
✅ Users Blueprint - Profile updates
✅ Subscription Blueprint - Subscriptions
✅ Dashboard Blueprint - Dashboard views
✅ Tax Blueprint - Tax calculations

## 🔐 Security

- Dashboard requires admin role
- User data is anonymized (ObjectIds)
- Tracking fails silently (non-blocking)
- No sensitive data in event details

## 📞 Support

- Full docs: `ANALYTICS_SYSTEM_README.md`
- Quick start: `ANALYTICS_QUICK_START.md`
- Test: `python test_analytics_system.py`
- Issues: Check server logs

---

**Quick Access URLs:**
- Dashboard: `/admin/analytics_dashboard.html`
- API Docs: `ANALYTICS_SYSTEM_README.md`
- Test Script: `python test_analytics_system.py`
