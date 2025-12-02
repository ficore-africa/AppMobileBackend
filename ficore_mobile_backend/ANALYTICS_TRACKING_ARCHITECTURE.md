# Analytics Tracking Architecture

## Overview

This document clarifies how analytics tracking works in the FiCore system, distinguishing between automatic backend tracking and client-side event submission.

## Two Tracking Approaches

### Approach 1: Automatic Backend Tracking (Recommended)

**When to use**: For events that occur during API calls (login, create income, etc.)

**How it works**:
1. User performs action in mobile app
2. App calls backend API endpoint (e.g., `POST /income`)
3. Backend processes the request
4. Backend automatically tracks the event using `tracker.track_event()`
5. Event is stored in database

**Advantages**:
- ✅ No extra API call from mobile app
- ✅ Server-side IP and device info capture
- ✅ Guaranteed tracking (can't be blocked by client)
- ✅ Consistent data format
- ✅ Less mobile app code

**Example**:
```python
# In blueprints/income.py
@income_bp.route('', methods=['POST'])
@token_required
def create_income(current_user):
    # ... create income logic ...
    result = mongo.db.incomes.insert_one(income_data)
    
    # Automatic tracking - no client action needed
    tracker.track_income_created(
        user_id=current_user['_id'],
        amount=data['amount'],
        category=data['category']
    )
    
    return jsonify({'success': True, 'data': income_data})
```

**Mobile app code**:
```dart
// App just calls the normal API - tracking happens automatically
await apiService.post('/income', {
  'amount': 1500.0,
  'category': 'Salary',
  'source': 'Main Job'
});
// That's it! Event is tracked server-side
```

### Approach 2: Client-Side Event Submission

**When to use**: For events that DON'T involve API calls (UI interactions, screen views, etc.)

**How it works**:
1. User performs action in mobile app (e.g., views a screen)
2. App explicitly calls `POST /api/analytics/track`
3. Backend captures IP and device info from request headers
4. Event is stored in database

**Advantages**:
- ✅ Can track UI-only events
- ✅ Can track client-side interactions
- ✅ Flexible for custom events

**Example**:
```dart
// In mobile app - for UI events only
class AnalyticsService {
  Future<void> trackScreenView(String screenName) async {
    // Check user consent first
    if (!await _hasConsent()) return;
    
    try {
      await apiService.post('/api/analytics/track', {
        'eventType': 'screen_viewed',
        'eventDetails': {'screen': screenName}
      });
      // Note: NO deviceInfo or IP in payload - server captures it
    } catch (e) {
      print('Analytics failed: $e');
    }
  }
}
```

## Important Rules

### ❌ DON'T: Send IP Address or Device Info from Client

**Wrong**:
```dart
// ❌ BAD - Don't do this!
await apiService.post('/api/analytics/track', {
  'eventType': 'user_logged_in',
  'deviceInfo': {
    'ip_address': '192.168.1.1',  // ❌ Never send IP from client
    'device_id': 'ABC123',         // ❌ Privacy concern
    'imei': '123456789'            // ❌ Privacy violation
  }
});
```

**Right**:
```dart
// ✅ GOOD - Let server capture this
await apiService.post('/api/analytics/track', {
  'eventType': 'screen_viewed',
  'eventDetails': {'screen': 'Dashboard'}
  // No deviceInfo - server will add it
});
```

### ✅ DO: Let Server Extract Technical Data

The backend automatically captures:
- IP address from `request.remote_addr` or `X-Forwarded-For` header
- User agent from `User-Agent` header
- Platform from `X-Platform` header (if app sets it)
- App version from `X-App-Version` header (if app sets it)

**Mobile app can optionally set headers**:
```dart
// Optional: Set custom headers for better tracking
final headers = {
  'Authorization': 'Bearer $token',
  'X-Platform': Platform.operatingSystem,  // 'android' or 'ios'
  'X-App-Version': '1.0.0',
  // Don't set X-Forwarded-For or try to send IP
};

await apiService.post('/api/analytics/track', 
  {'eventType': 'screen_viewed'},
  headers: headers
);
```

## Event Tracking Decision Tree

```
Is this event triggered by an API call?
│
├─ YES → Use Automatic Backend Tracking
│         (Event is tracked in the API endpoint)
│         Mobile app: Just call the API normally
│         Example: Login, Create Income, Update Profile
│
└─ NO → Use Client-Side Event Submission
          (Event is tracked via /api/analytics/track)
          Mobile app: Explicitly call tracking endpoint
          Example: Screen views, Button clicks, UI interactions
```

## Complete Event Mapping

### Events with Automatic Backend Tracking

These events are tracked automatically when you call the corresponding API:

| Event | API Endpoint | Mobile App Action |
|-------|-------------|-------------------|
| `user_logged_in` | `POST /auth/login` | Just login normally |
| `user_registered` | `POST /auth/signup` | Just signup normally |
| `income_entry_created` | `POST /income` | Just create income normally |
| `expense_entry_created` | `POST /expenses` | Just create expense normally |
| `profile_updated` | `PUT /users/profile` | Just update profile normally |
| `subscription_started` | `POST /subscription/verify` | Just verify payment normally |
| `dashboard_viewed` | `GET /dashboard/overview` | Just fetch dashboard normally |
| `tax_calculation_performed` | `POST /tax/calculate` | Just calculate tax normally |

**Mobile app code for these events**:
```dart
// No special tracking code needed!
// Just call the API - tracking happens automatically

// Login - tracked automatically
await apiService.post('/auth/login', {
  'email': email,
  'password': password
});

// Create income - tracked automatically
await apiService.post('/income', {
  'amount': 1500.0,
  'category': 'Salary'
});

// Update profile - tracked automatically
await apiService.put('/users/profile', {
  'firstName': 'John',
  'lastName': 'Doe'
});
```

### Events Requiring Client-Side Submission

These events must be explicitly tracked by the mobile app:

| Event | When to Track | Mobile App Code |
|-------|--------------|-----------------|
| `screen_viewed` | User navigates to screen | Call `/api/analytics/track` |
| `button_clicked` | User clicks button | Call `/api/analytics/track` |
| `feature_discovered` | User finds feature | Call `/api/analytics/track` |
| `tutorial_completed` | User finishes tutorial | Call `/api/analytics/track` |
| `search_performed` | User searches | Call `/api/analytics/track` |
| `filter_applied` | User filters data | Call `/api/analytics/track` |

**Mobile app code for these events**:
```dart
class AnalyticsService {
  final ApiService _apiService;
  
  // Check consent before tracking
  Future<bool> _hasConsent() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool('analytics_consent') ?? false;
  }
  
  // Generic tracking method
  Future<void> trackEvent(String eventType, [Map<String, dynamic>? details]) async {
    if (!await _hasConsent()) return;
    
    try {
      await _apiService.post('/api/analytics/track', {
        'eventType': eventType,
        'eventDetails': details,
      });
    } catch (e) {
      print('Analytics failed: $e');
    }
  }
  
  // Convenience methods for common UI events
  Future<void> trackScreenView(String screenName) {
    return trackEvent('screen_viewed', {'screen': screenName});
  }
  
  Future<void> trackButtonClick(String buttonName) {
    return trackEvent('button_clicked', {'button': buttonName});
  }
  
  Future<void> trackSearch(String query) {
    return trackEvent('search_performed', {'query': query});
  }
}

// Usage in app
class DashboardScreen extends StatefulWidget {
  @override
  void initState() {
    super.initState();
    // Track screen view
    analyticsService.trackScreenView('Dashboard');
  }
  
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          ElevatedButton(
            onPressed: () {
              // Track button click
              analyticsService.trackButtonClick('Export Report');
              // Then perform action
              _exportReport();
            },
            child: Text('Export Report'),
          ),
        ],
      ),
    );
  }
}
```

## Server-Side Implementation Details

### How Backend Captures Device Info

```python
# In blueprints/analytics.py

@analytics_bp.route('/track', methods=['POST'])
@token_required
def track_event(current_user):
    data = request.get_json()
    
    # IMPORTANT: Always capture device info server-side
    device_info = {
        'user_agent': request.headers.get('User-Agent', 'Unknown'),
        'ip_address': request.remote_addr or request.headers.get('X-Forwarded-For', 'Unknown'),
        'platform': request.headers.get('X-Platform', 'Unknown'),
        'app_version': request.headers.get('X-App-Version', 'Unknown')
    }
    
    # Create event with server-captured data
    event = {
        'userId': current_user['_id'],
        'eventType': data['eventType'],
        'timestamp': datetime.utcnow(),
        'eventDetails': data.get('eventDetails'),
        'deviceInfo': device_info,  # Server-side capture
        'sessionId': data.get('sessionId'),
        'createdAt': datetime.utcnow()
    }
    
    mongo.db.analytics_events.insert_one(event)
    return jsonify({'success': True})
```

### How Automatic Tracking Works

```python
# In blueprints/auth.py

@auth_bp.route('/login', methods=['POST'])
def login():
    # ... authentication logic ...
    
    # After successful login, track automatically
    try:
        device_info = {
            'user_agent': request.headers.get('User-Agent', 'Unknown'),
            'ip_address': request.remote_addr,
            'platform': request.headers.get('X-Platform', 'Unknown'),
            'app_version': request.headers.get('X-App-Version', 'Unknown')
        }
        auth_bp.tracker.track_login(user['_id'], device_info=device_info)
    except Exception as e:
        print(f"Analytics tracking failed: {e}")
        # Continue - don't fail login if tracking fails
    
    return jsonify({'success': True, 'data': user_data})
```

## Privacy Considerations

### What Gets Tracked

✅ **Safe to track**:
- User ID (ObjectId)
- Event type
- Timestamp
- Aggregated amounts (income/expense totals)
- Category names
- Feature usage counts
- IP address (for security/fraud detection)
- User agent (for compatibility)

❌ **Never track**:
- Passwords
- Authentication tokens
- Personal identification numbers
- Full names in event details
- Email addresses in event details
- Detailed transaction descriptions
- Payment card information
- Precise GPS coordinates
- Device IMEI/serial numbers

### IP Address Handling

**Why we collect IP addresses**:
- Security (detect suspicious logins)
- Fraud prevention
- Geographic analytics (country-level only)
- Debugging connection issues

**How to anonymize** (if needed):
```python
import hashlib

def anonymize_ip(ip_address):
    """Hash IP address for privacy"""
    return hashlib.sha256(ip_address.encode()).hexdigest()[:16]

# Use in tracking
device_info = {
    'ip_address': anonymize_ip(request.remote_addr),
    # ... other fields
}
```

## Testing

### Test Automatic Tracking

```bash
# Login - should auto-track
curl -X POST http://localhost:5000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password123"}'

# Check if event was created
# In MongoDB shell:
db.analytics_events.find({eventType: 'user_logged_in'}).sort({timestamp: -1}).limit(1)
```

### Test Client-Side Tracking

```bash
# Explicit tracking call
curl -X POST http://localhost:5000/api/analytics/track \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Platform: android" \
  -H "X-App-Version: 1.0.0" \
  -d '{"eventType":"screen_viewed","eventDetails":{"screen":"Dashboard"}}'

# Check if event was created with server-captured device info
db.analytics_events.find({eventType: 'screen_viewed'}).sort({timestamp: -1}).limit(1)
```

## Summary

### For Backend Developers

1. **Add automatic tracking** to API endpoints for core actions
2. **Always capture device info server-side** from request headers
3. **Never trust client-provided IP addresses**
4. **Make tracking fail-safe** (don't break main functionality)

### For Mobile App Developers

1. **Don't send IP addresses or device IDs** in tracking payloads
2. **Optionally set headers** (X-Platform, X-App-Version) for better tracking
3. **Only explicitly track UI events** that don't involve API calls
4. **Check user consent** before any tracking
5. **Let automatic tracking handle** API-related events

### Key Principle

**Server is the source of truth for technical data. Client provides context about user actions.**

---

This architecture ensures:
- ✅ Accurate data collection
- ✅ User privacy protection
- ✅ Consistent tracking
- ✅ Minimal client-side code
- ✅ Server-side control
