# Analytics System - Action Items

## ✅ Completed (Backend)

All backend implementation is complete and production-ready:

- ✅ Database schema with `analytics_events` collection
- ✅ Analytics API endpoints (tracking + admin dashboard)
- ✅ Automatic tracking in 7 blueprints
- ✅ Server-side IP and device info capture
- ✅ Admin dashboard web interface
- ✅ User data management endpoints (view, delete, export)
- ✅ Comprehensive documentation
- ✅ Test script for verification
- ✅ Privacy and compliance guides

## 🔨 To Do (Mobile App)

### Priority 1: User Consent (Required for Launch)

**File**: `lib/services/analytics_consent_service.dart`

```dart
import 'package:shared_preferences/shared_preferences.dart';

class AnalyticsConsentService {
  static const String _consentKey = 'analytics_consent';
  static const String _consentDateKey = 'analytics_consent_date';
  
  Future<bool> hasConsent() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_consentKey) ?? false;
  }
  
  Future<void> setConsent(bool consent) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_consentKey, consent);
    await prefs.setString(_consentDateKey, DateTime.now().toIso8601String());
  }
  
  Future<bool> hasAskedForConsent() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.containsKey(_consentKey);
  }
}
```

**File**: `lib/widgets/analytics_consent_dialog.dart`

```dart
import 'package:flutter/material.dart';

class AnalyticsConsentDialog extends StatelessWidget {
  final Function(bool) onConsentChanged;
  
  const AnalyticsConsentDialog({required this.onConsentChanged});
  
  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Help Us Improve FiCore'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'We collect anonymous usage data to improve your experience.',
              style: TextStyle(fontSize: 16),
            ),
            SizedBox(height: 16),
            Text(
              'We collect:',
              style: TextStyle(fontWeight: FontWeight.bold),
            ),
            Text('• Feature usage patterns'),
            Text('• Technical information'),
            Text('• Error reports'),
            SizedBox(height: 16),
            Text(
              'We do NOT collect:',
              style: TextStyle(fontWeight: FontWeight.bold),
            ),
            Text('• Personal identification'),
            Text('• Financial details'),
            Text('• Location data'),
            SizedBox(height: 16),
            TextButton(
              onPressed: () {
                // TODO: Show full privacy policy
              },
              child: Text('Read Privacy Policy'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () {
            onConsentChanged(false);
            Navigator.pop(context);
          },
          child: Text('No Thanks'),
        ),
        ElevatedButton(
          onPressed: () {
            onConsentChanged(true);
            Navigator.pop(context);
          },
          child: Text('Accept'),
        ),
      ],
    );
  }
}
```

**Usage**: Show on first app launch in `main.dart` or splash screen.

### Priority 2: Analytics Service (Required for Tracking)

**File**: `lib/services/analytics_service.dart`

```dart
import 'dart:io';
import 'package:package_info_plus/package_info_plus.dart';
import 'analytics_consent_service.dart';
import 'api_service.dart';

class AnalyticsService {
  final ApiService _apiService;
  final AnalyticsConsentService _consentService;
  
  AnalyticsService(this._apiService, this._consentService);
  
  // Track generic event
  Future<void> trackEvent(
    String eventType, {
    Map<String, dynamic>? eventDetails,
  }) async {
    // Check consent first
    if (!await _consentService.hasConsent()) {
      print('Analytics tracking skipped - no user consent');
      return;
    }
    
    try {
      // Get app version for headers
      final packageInfo = await PackageInfo.fromPlatform();
      
      // Set custom headers (server will capture IP and user agent)
      final headers = {
        'X-Platform': Platform.operatingSystem,
        'X-App-Version': packageInfo.version,
      };
      
      await _apiService.post(
        '/api/analytics/track',
        {
          'eventType': eventType,
          'eventDetails': eventDetails,
        },
        headers: headers,
      );
    } catch (e) {
      // Fail silently - don't disrupt user experience
      print('Analytics tracking failed: $e');
    }
  }
  
  // Convenience methods for common UI events
  Future<void> trackScreenView(String screenName) {
    return trackEvent('screen_viewed', eventDetails: {'screen': screenName});
  }
  
  Future<void> trackButtonClick(String buttonName) {
    return trackEvent('button_clicked', eventDetails: {'button': buttonName});
  }
  
  Future<void> trackSearch(String query) {
    return trackEvent('search_performed', eventDetails: {'query': query});
  }
  
  Future<void> trackFeatureDiscovered(String featureName) {
    return trackEvent('feature_discovered', eventDetails: {'feature': featureName});
  }
}
```

**Usage**: Inject into widgets that need tracking.

### Priority 3: Settings Integration

**File**: `lib/screens/settings/privacy_settings_screen.dart`

Add to your settings screen:

```dart
class PrivacySettingsScreen extends StatefulWidget {
  @override
  _PrivacySettingsScreenState createState() => _PrivacySettingsScreenState();
}

class _PrivacySettingsScreenState extends State<PrivacySettingsScreen> {
  final AnalyticsConsentService _consentService = AnalyticsConsentService();
  bool _analyticsEnabled = false;
  
  @override
  void initState() {
    super.initState();
    _loadConsent();
  }
  
  Future<void> _loadConsent() async {
    final consent = await _consentService.hasConsent();
    setState(() {
      _analyticsEnabled = consent;
    });
  }
  
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Privacy Settings')),
      body: ListView(
        children: [
          SwitchListTile(
            title: Text('Share Usage Data'),
            subtitle: Text('Help us improve by sharing anonymous usage data'),
            value: _analyticsEnabled,
            onChanged: (bool value) async {
              await _consentService.setConsent(value);
              setState(() {
                _analyticsEnabled = value;
              });
              
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(
                    value 
                      ? 'Analytics enabled. Thank you!' 
                      : 'Analytics disabled.'
                  ),
                ),
              );
            },
          ),
          ListTile(
            title: Text('View My Data'),
            subtitle: Text('See what analytics data we have collected'),
            trailing: Icon(Icons.arrow_forward_ios),
            onTap: () {
              // TODO: Navigate to data viewer screen
              // Call GET /api/analytics/my-data
            },
          ),
          ListTile(
            title: Text('Delete My Data'),
            subtitle: Text('Permanently delete all your analytics data'),
            trailing: Icon(Icons.delete_outline),
            onTap: () {
              _showDeleteConfirmation();
            },
          ),
          ListTile(
            title: Text('Export My Data'),
            subtitle: Text('Download your analytics data as CSV'),
            trailing: Icon(Icons.download),
            onTap: () {
              // TODO: Call GET /api/analytics/my-data/export
            },
          ),
          Divider(),
          ListTile(
            title: Text('Privacy Policy'),
            trailing: Icon(Icons.arrow_forward_ios),
            onTap: () {
              // TODO: Show privacy policy
            },
          ),
        ],
      ),
    );
  }
  
  void _showDeleteConfirmation() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete Analytics Data?'),
        content: Text(
          'This will permanently delete all analytics data we have collected about your usage. This action cannot be undone.'
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () async {
              // TODO: Call DELETE /api/analytics/my-data
              Navigator.pop(context);
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text('Analytics data deleted')),
              );
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: Text('Delete'),
          ),
        ],
      ),
    );
  }
}
```

### Priority 4: Track Screen Views

Add to your screens:

```dart
class DashboardScreen extends StatefulWidget {
  @override
  _DashboardScreenState createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final AnalyticsService _analytics = AnalyticsService(/* inject dependencies */);
  
  @override
  void initState() {
    super.initState();
    // Track screen view
    _analytics.trackScreenView('Dashboard');
  }
  
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Dashboard')),
      body: Column(
        children: [
          ElevatedButton(
            onPressed: () {
              // Track button click
              _analytics.trackButtonClick('Export Report');
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

## 📋 To Do (Legal/Compliance)

### Priority 1: Update Privacy Policy

**Location**: Your website, app store listings, in-app privacy policy

**Add this section**:

```markdown
## Analytics and Usage Tracking

We collect anonymous usage data to improve FiCore and provide better service.

### Data Collected
- User activity (logins, entries created, features used)
- Technical information (IP address, device type, app version)
- Usage patterns and timestamps

### Data NOT Collected
- Passwords or authentication credentials
- Personal identification numbers (SSN, TIN)
- Payment card information
- Detailed transaction descriptions
- Precise location data (GPS)
- Device identifiers (IMEI, MAC address)

### Purpose
- Understand how users interact with FiCore
- Improve features and user experience
- Identify and fix technical issues
- Measure feature adoption

### Retention
- Analytics data is retained for 12 months
- Automatically deleted after retention period
- You can request deletion anytime

### Your Rights
- View your analytics data
- Request deletion of your data
- Opt-out of analytics tracking
- Export your data in CSV format

### Contact
team@ficoreafrica.com

### Security
- All data encrypted in transit (HTTPS)
- Stored in encrypted databases
- Access restricted to authorized personnel
- We never sell your data to third parties
```

### Priority 2: Set Up Privacy Request Handling

**Create**: team@ficoreafrica.com email address

**Process**:
1. User sends privacy request to team@ficoreafrica.com
2. Verify user identity
3. Process request within 30 days (GDPR) or 45 days (CCPA)
4. Send confirmation email

**Templates**: See `ANALYTICS_PRIVACY_AND_CONSENT.md` for email templates

### Priority 3: Schedule Data Cleanup

**Add to backend** (if not using APScheduler):

Create a cron job to run daily:

```bash
# crontab -e
0 2 * * * cd /path/to/ficore_mobile_backend && python -c "from app import mongo; from datetime import datetime, timedelta; mongo.db.analytics_events.delete_many({'timestamp': {'$lt': datetime.utcnow() - timedelta(days=365)}})"
```

Or use the provided scheduler in the documentation.

## 📊 To Do (Monitoring)

### Set Up Dashboard Access

1. **Get admin token**:
   ```bash
   curl -X POST http://your-backend/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"admin@ficore.com","password":"admin123"}'
   ```

2. **Bookmark dashboard**:
   `http://your-backend/admin/analytics_dashboard.html`

3. **Check daily** for:
   - User growth trends
   - Feature adoption
   - Error patterns
   - Engagement metrics

### Set Up Alerts (Optional)

Monitor for:
- Sudden drop in DAU/MAU
- Spike in error events
- Unusual activity patterns

## 🧪 Testing Checklist

### Backend Testing
- [x] Run `python test_analytics_system.py`
- [x] Verify events are stored in MongoDB
- [x] Check dashboard loads correctly
- [x] Test admin API endpoints

### Mobile App Testing
- [ ] Test consent dialog appears on first launch
- [ ] Test consent is saved correctly
- [ ] Test analytics respects consent choice
- [ ] Test screen view tracking
- [ ] Test "View My Data" in settings
- [ ] Test "Delete My Data" in settings
- [ ] Test "Export My Data" in settings
- [ ] Verify no tracking when consent is denied

### Integration Testing
- [ ] Login → Check `user_logged_in` event in dashboard
- [ ] Create income → Check `income_entry_created` event
- [ ] Create expense → Check `expense_entry_created` event
- [ ] Update profile → Check `profile_updated` event
- [ ] View dashboard → Check `dashboard_viewed` event

## 📚 Documentation Reference

| Document | Purpose |
|----------|---------|
| `ANALYTICS_SYSTEM_README.md` | Complete API documentation |
| `ANALYTICS_QUICK_START.md` | 5-minute setup guide |
| `ANALYTICS_TRACKING_ARCHITECTURE.md` | ⭐ How tracking works |
| `ANALYTICS_PRIVACY_AND_CONSENT.md` | ⭐ Privacy compliance |
| `ANALYTICS_PRIVACY_IMPLEMENTATION_SUMMARY.md` | ⭐ Issues addressed |
| `ANALYTICS_IMPLEMENTATION_COMPLETE.md` | What's been done |
| `ANALYTICS_CHEAT_SHEET.md` | Quick reference |
| `ANALYTICS_ACTION_ITEMS.md` | This file |

## 🚀 Launch Checklist

Before going to production:

### Backend
- [x] Analytics system deployed
- [x] Database indexes created
- [ ] Data cleanup scheduled
- [ ] Admin dashboard accessible
- [ ] Privacy endpoints tested

### Mobile App
- [ ] Consent dialog implemented
- [ ] Analytics service integrated
- [ ] Settings page updated
- [ ] Screen tracking added
- [ ] Tested with real users

### Legal
- [ ] Privacy policy updated
- [ ] App store privacy disclosures updated
- [ ] Privacy request process established
- [ ] Team trained on privacy requirements
- [ ] Legal review completed

### Monitoring
- [ ] Dashboard bookmarked
- [ ] Team has admin access
- [ ] Monitoring schedule established
- [ ] Alert thresholds defined

## ⏱️ Estimated Time

- **Mobile App Implementation**: 4-6 hours
- **Privacy Policy Update**: 1-2 hours
- **Testing**: 2-3 hours
- **Legal Review**: Varies by organization
- **Total**: ~1-2 days

## 🆘 Need Help?

- **Architecture questions**: See `ANALYTICS_TRACKING_ARCHITECTURE.md`
- **Privacy questions**: See `ANALYTICS_PRIVACY_AND_CONSENT.md`
- **API questions**: See `ANALYTICS_SYSTEM_README.md`
- **Quick reference**: See `ANALYTICS_CHEAT_SHEET.md`

---

**Ready to launch!** Backend is complete. Focus on mobile app consent and privacy policy updates. 🎉
