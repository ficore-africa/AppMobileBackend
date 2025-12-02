# Analytics System - Quick Start Guide

Get your custom analytics dashboard up and running in 5 minutes!

## Step 1: Initialize the Database (1 minute)

The analytics system will automatically create the `analytics_events` collection when you start your backend.

```bash
# Start your backend server
cd ficore_mobile_backend
python app.py
```

Look for this in the logs:
```
✅ Created collection 'analytics_events'
✅ Created index 'user_timestamp_desc' on 'analytics_events'
```

## Step 2: Test the System (2 minutes)

Run the test script to verify everything works:

```bash
python test_analytics_system.py
```

You should see:
```
✅ All tests passed!
✅ 4 events tracked successfully
✅ 4 indexes verified
```

## Step 3: Access the Dashboard (1 minute)

1. **Get your admin token**:
   ```bash
   # Login as admin
   curl -X POST http://localhost:5000/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"admin@ficore.com","password":"admin123"}'
   ```

2. **Open the dashboard**:
   - Navigate to: `http://localhost:5000/admin/analytics_dashboard.html`
   - Paste your admin token when prompted
   - View your metrics!

## Step 4: Start Tracking Events (1 minute)

### From Your Mobile App (Flutter)

```dart
// Track login
await apiService.post('/api/analytics/track', {
  'eventType': 'user_logged_in',
  'deviceInfo': {
    'platform': Platform.operatingSystem,
    'version': '1.0.0'
  }
});

// Track income creation
await apiService.post('/api/analytics/track', {
  'eventType': 'income_entry_created',
  'eventDetails': {
    'amount': 1500.0,
    'category': 'Salary'
  }
});
```

### From Your Backend (Python)

```python
from utils.analytics_tracker import create_tracker

# In your blueprint
tracker = create_tracker(mongo.db)

# Track events
tracker.track_login(user_id)
tracker.track_income_created(user_id, amount=1500.0, category='Salary')
tracker.track_expense_created(user_id, amount=500.0, category='Groceries')
```

## What You Get

### Dashboard Metrics
- **Total Users**: All registered users
- **DAU/WAU/MAU**: Daily/Weekly/Monthly active users
- **Entry Counts**: Income and expense entries
- **Event Breakdown**: Counts by event type
- **Top Users**: Most active users
- **Recent Activity**: Real-time activity feed

### API Endpoints (Admin Only)
- `GET /api/analytics/dashboard/overview` - High-level metrics
- `GET /api/analytics/dashboard/event-counts` - Event counts by type
- `GET /api/analytics/dashboard/user-growth` - Registration trend
- `GET /api/analytics/dashboard/mau-trend` - MAU over 12 months
- `GET /api/analytics/dashboard/top-users` - Most active users

### Client Endpoint (All Users)
- `POST /api/analytics/track` - Track user events

## Common Use Cases

### 1. Track User Login
```python
# After successful authentication
tracker.track_login(user['_id'], device_info={'platform': 'Android'})
```

### 2. Track Entry Creation
```python
# After creating income
tracker.track_income_created(user_id, amount=1500.0, category='Salary')

# After creating expense
tracker.track_expense_created(user_id, amount=500.0, category='Groceries')
```

### 3. Track Feature Usage
```python
# Dashboard view
tracker.track_dashboard_view(user_id)

# Report generation
tracker.track_report_generated(user_id, report_type='monthly_summary')

# Tax calculation
tracker.track_tax_calculation(user_id, tax_year=2025)
```

### 4. Track Business Events
```python
# Subscription started
tracker.track_subscription_started(user_id, 'monthly', amount=9.99)

# Profile updated
tracker.track_profile_updated(user_id, fields_updated=['firstName', 'phone'])
```

## Troubleshooting

### Dashboard Not Loading?
1. Check if backend is running: `http://localhost:5000/health`
2. Verify admin token is valid
3. Check browser console for errors

### Events Not Appearing?
1. Verify `analytics_events` collection exists
2. Check server logs for tracking errors
3. Test with the test script: `python test_analytics_system.py`

### Slow Performance?
1. Ensure indexes are created (check test script output)
2. Consider data retention policies for old events
3. Use aggregation pipelines for complex queries

## Next Steps

1. **Read the full documentation**: `ANALYTICS_SYSTEM_README.md`
2. **See integration examples**: `ANALYTICS_INTEGRATION_EXAMPLES.md`
3. **Customize the dashboard**: Edit `admin_web_app/analytics_dashboard.html`
4. **Add more events**: Extend the tracker utility as needed

## Support

- Check logs: Look for "Analytics tracking failed" messages
- Test endpoints: Use Postman or curl to test API calls
- Verify database: Check MongoDB for `analytics_events` collection
- Review code: See `blueprints/analytics.py` for implementation

## Production Checklist

Before deploying to production:

- [ ] Test all tracking endpoints
- [ ] Verify dashboard loads correctly
- [ ] Set up proper admin authentication
- [ ] Configure CORS for dashboard access
- [ ] Implement data retention policies
- [ ] Add monitoring/alerting for tracking failures
- [ ] Review privacy compliance (GDPR, etc.)
- [ ] Document tracked events for your team

---

**That's it!** You now have a fully functional analytics system tracking user activity and providing insights through a custom admin dashboard. 🎉
