# Analytics System - Privacy & Consent Guide

## Overview

This document outlines the privacy considerations and user consent requirements for the FiCore analytics system, ensuring compliance with data protection regulations like GDPR, CCPA, and similar laws.

## Data Collection Summary

### What Data is Collected

The analytics system collects the following data:

#### 1. User Identifiers
- **User ID** (MongoDB ObjectId) - Links events to specific users
- **Session ID** (optional) - Groups events within a user session

#### 2. Event Data
- **Event Type** - The action performed (e.g., "user_logged_in", "income_entry_created")
- **Timestamp** - When the event occurred (UTC)
- **Event Details** - Context-specific data:
  - For income/expense: amount, category (NO sensitive descriptions)
  - For profile updates: field names updated (NO actual values)
  - For subscriptions: subscription type, amount

#### 3. Technical Data (Automatically Collected Server-Side)
- **IP Address** - User's IP address from request headers
- **User Agent** - Browser/app information
- **Platform** - Operating system (iOS, Android, Web)
- **App Version** - Application version number

#### 4. What is NOT Collected
- ❌ Passwords or authentication tokens
- ❌ Personal identification numbers (SSN, TIN, etc.)
- ❌ Full names or email addresses in event details
- ❌ Detailed transaction descriptions
- ❌ Payment card information
- ❌ Location data (GPS coordinates)
- ❌ Device identifiers (IMEI, MAC address)

## Legal Requirements

### GDPR (European Union)

If you have users in the EU, you must:

1. **Obtain Explicit Consent**
   - Users must opt-in to analytics tracking
   - Consent must be freely given, specific, informed, and unambiguous
   - Pre-checked boxes are NOT valid consent

2. **Provide Clear Information**
   - What data is collected
   - Why it's collected
   - How long it's retained
   - Who has access to it

3. **Enable User Rights**
   - Right to access their data
   - Right to delete their data
   - Right to data portability
   - Right to object to processing

### CCPA (California, USA)

If you have users in California:

1. **Disclose Data Collection**
   - List categories of data collected
   - Purpose of collection
   - Third parties with access

2. **Provide Opt-Out**
   - "Do Not Sell My Personal Information" option
   - Easy opt-out mechanism

3. **Honor Deletion Requests**
   - Delete user data upon request
   - Confirm deletion within 45 days

### Other Jurisdictions

Check local laws for:
- Brazil (LGPD)
- Canada (PIPEDA)
- Australia (Privacy Act)
- Your specific country/region

## Implementation Guide

### Step 1: Update Privacy Policy

Add this section to your privacy policy:

```markdown
## Analytics and Usage Data

### What We Collect
We collect analytics data to improve our service, including:
- User activity events (logins, entries created, features used)
- Technical information (IP address, device type, app version)
- Usage patterns and feature engagement
- Timestamps of actions

### Why We Collect It
- To understand how users interact with our app
- To improve features and user experience
- To identify and fix technical issues
- To measure feature adoption and engagement

### What We Don't Collect
We do NOT collect:
- Your passwords or authentication credentials
- Personal identification numbers (SSN, TIN)
- Detailed transaction descriptions
- Payment card information
- Precise location data
- Device identifiers (IMEI, MAC address)

### Data Retention
- Analytics data is retained for 12 months
- After 12 months, data is automatically deleted
- You can request deletion at any time

### Your Rights
You have the right to:
- Access your analytics data
- Request deletion of your data
- Opt-out of analytics tracking
- Export your data

To exercise these rights, contact us at team@ficoreafrica.com

### Data Security
- All data is encrypted in transit (HTTPS)
- Data is stored securely in encrypted databases
- Access is restricted to authorized personnel only
- We never sell your data to third parties
```

### Step 2: Implement Consent Mechanism

#### Option A: Opt-In (Recommended for GDPR)

Add consent prompt on first app launch:

```dart
// Flutter example
class AnalyticsConsentDialog extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Help Us Improve'),
      content: Column(
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
              // Show full privacy policy
            },
            child: Text('Read Privacy Policy'),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () {
            // User declined
            _setAnalyticsConsent(false);
            Navigator.pop(context);
          },
          child: Text('No Thanks'),
        ),
        ElevatedButton(
          onPressed: () {
            // User accepted
            _setAnalyticsConsent(true);
            Navigator.pop(context);
          },
          child: Text('Accept'),
        ),
      ],
    );
  }
  
  void _setAnalyticsConsent(bool consent) async {
    await SharedPreferences.getInstance().then((prefs) {
      prefs.setBool('analytics_consent', consent);
      prefs.setString('analytics_consent_date', DateTime.now().toIso8601String());
    });
  }
}
```

#### Option B: Opt-Out (For Less Strict Jurisdictions)

Enable analytics by default with easy opt-out in settings:

```dart
// Settings screen
class AnalyticsSettings extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return SwitchListTile(
      title: Text('Share Usage Data'),
      subtitle: Text('Help us improve by sharing anonymous usage data'),
      value: _analyticsEnabled,
      onChanged: (bool value) {
        setState(() {
          _analyticsEnabled = value;
          _saveAnalyticsPreference(value);
        });
      },
    );
  }
}
```

### Step 3: Respect User Consent

Update your analytics service to check consent:

```dart
class AnalyticsService {
  final ApiService _apiService;
  
  Future<bool> _hasConsent() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool('analytics_consent') ?? false;
  }
  
  Future<void> trackEvent({
    required String eventType,
    Map<String, dynamic>? eventDetails,
  }) async {
    // Check consent first
    if (!await _hasConsent()) {
      print('Analytics tracking skipped - no user consent');
      return;
    }
    
    try {
      await _apiService.post('/api/analytics/track', {
        'eventType': eventType,
        'eventDetails': eventDetails,
      });
    } catch (e) {
      print('Analytics tracking failed: $e');
    }
  }
}
```

### Step 4: Add User Data Management Endpoints

Add these endpoints to allow users to manage their data:

```python
# In blueprints/analytics.py or users.py

@analytics_bp.route('/my-data', methods=['GET'])
@token_required
def get_my_analytics_data(current_user):
    """
    Allow users to view their analytics data (GDPR Article 15)
    """
    try:
        events = list(mongo.db.analytics_events.find({
            'userId': current_user['_id']
        }).sort('timestamp', -1).limit(1000))
        
        # Serialize events
        events_data = []
        for event in events:
            events_data.append({
                'eventType': event['eventType'],
                'timestamp': event['timestamp'].isoformat() + 'Z',
                'eventDetails': event.get('eventDetails'),
            })
        
        return jsonify({
            'success': True,
            'data': {
                'events': events_data,
                'total': len(events_data)
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to retrieve analytics data',
            'error': str(e)
        }), 500

@analytics_bp.route('/my-data', methods=['DELETE'])
@token_required
def delete_my_analytics_data(current_user):
    """
    Allow users to delete their analytics data (GDPR Article 17)
    """
    try:
        result = mongo.db.analytics_events.delete_many({
            'userId': current_user['_id']
        })
        
        return jsonify({
            'success': True,
            'message': f'Deleted {result.deleted_count} analytics events',
            'data': {
                'deleted_count': result.deleted_count
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to delete analytics data',
            'error': str(e)
        }), 500

@analytics_bp.route('/my-data/export', methods=['GET'])
@token_required
def export_my_analytics_data(current_user):
    """
    Allow users to export their analytics data (GDPR Article 20)
    """
    try:
        events = list(mongo.db.analytics_events.find({
            'userId': current_user['_id']
        }).sort('timestamp', -1))
        
        # Create CSV export
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Timestamp', 'Event Type', 'Event Details'])
        
        # Write data
        for event in events:
            writer.writerow([
                event['timestamp'].isoformat(),
                event['eventType'],
                str(event.get('eventDetails', {}))
            ])
        
        # Create response
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': 'attachment; filename=my_analytics_data.csv'
            }
        )
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Failed to export analytics data',
            'error': str(e)
        }), 500
```

### Step 5: Implement Data Retention Policy

Add automatic data deletion:

```python
# Create a scheduled task (e.g., using APScheduler or cron)

from datetime import datetime, timedelta

def cleanup_old_analytics_data():
    """
    Delete analytics data older than 12 months
    Run this daily via cron or scheduler
    """
    try:
        retention_period = timedelta(days=365)  # 12 months
        cutoff_date = datetime.utcnow() - retention_period
        
        result = mongo.db.analytics_events.delete_many({
            'timestamp': {'$lt': cutoff_date}
        })
        
        print(f"Deleted {result.deleted_count} old analytics events")
        return result.deleted_count
        
    except Exception as e:
        print(f"Error cleaning up analytics data: {e}")
        return 0

# Schedule this to run daily
# Example with APScheduler:
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(
    cleanup_old_analytics_data,
    'cron',
    hour=2,  # Run at 2 AM daily
    minute=0
)
scheduler.start()
```

## Best Practices

### 1. Minimize Data Collection
- Only collect what you actually need
- Don't collect sensitive personal information
- Aggregate data when possible

### 2. Anonymize When Possible
- Use user IDs instead of emails in analytics
- Hash IP addresses if full IP not needed
- Remove identifying information from event details

### 3. Secure Data Storage
- Encrypt data at rest
- Use HTTPS for all API calls
- Restrict database access
- Regular security audits

### 4. Be Transparent
- Clear privacy policy
- Easy-to-understand consent forms
- Visible opt-out options
- Regular privacy updates

### 5. Honor User Requests Promptly
- Respond to data requests within 30 days
- Provide data in readable format
- Confirm deletions
- Keep records of requests

## Consent Flow Examples

### First Launch Flow

```
1. User opens app for first time
2. Show welcome screen
3. Show analytics consent dialog
   - Clear explanation of what's collected
   - Link to full privacy policy
   - "Accept" and "No Thanks" buttons
4. Store user's choice
5. Only track if user accepted
```

### Settings Flow

```
1. User goes to Settings > Privacy
2. Show "Share Usage Data" toggle
3. Show explanation below toggle
4. Link to "View My Data" and "Delete My Data"
5. Update tracking based on toggle state
```

## Compliance Checklist

- [ ] Privacy policy updated with analytics section
- [ ] Consent mechanism implemented (opt-in or opt-out)
- [ ] User data access endpoint created
- [ ] User data deletion endpoint created
- [ ] User data export endpoint created
- [ ] Data retention policy implemented
- [ ] Automatic data cleanup scheduled
- [ ] Analytics respects user consent
- [ ] No sensitive data in event details
- [ ] IP addresses handled appropriately
- [ ] Security measures in place
- [ ] Team trained on privacy requirements
- [ ] Privacy policy easily accessible in app
- [ ] Contact email for privacy requests

## Sample Privacy Request Responses

### Data Access Request

```
Subject: Your Analytics Data Request

Dear [User],

Thank you for your data access request. Attached is a CSV file containing
all analytics events we have recorded for your account.

This includes:
- Event types and timestamps
- Usage patterns
- Technical information

If you have any questions, please reply to this email.

Best regards,
FiCore Privacy Team
```

### Data Deletion Request

```
Subject: Your Data Deletion Request - Completed

Dear [User],

We have successfully deleted all analytics data associated with your account.

Deleted:
- 1,234 analytics events
- All associated metadata

Your account remains active, but we will no longer track analytics data
unless you opt back in.

If you have any questions, please reply to this email.

Best regards,
FiCore Privacy Team
```

## Resources

- [GDPR Official Text](https://gdpr-info.eu/)
- [CCPA Official Text](https://oag.ca.gov/privacy/ccpa)
- [Privacy Policy Generator](https://www.privacypolicies.com/)
- [GDPR Checklist](https://gdpr.eu/checklist/)

## Support

For privacy-related questions:
- Email: team@ficoreafrica.com
- Review: `ANALYTICS_SYSTEM_README.md`
- Legal: Consult with a privacy attorney for your jurisdiction

---

**Remember**: Privacy is not just about compliance—it's about respecting your users and building trust. Be transparent, be fair, and always put user privacy first.
