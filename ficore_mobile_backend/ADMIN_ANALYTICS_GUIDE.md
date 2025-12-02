# Admin Analytics Management Guide

## Overview

As an admin, you have full access to all analytics data and NDPR compliance tools. This guide shows you how to manage user analytics data, handle NDPR requests, and monitor system health.

---

## 🔐 Admin Access

### Prerequisites
- Admin role in the system
- Valid admin JWT token
- Access to admin dashboard

### Getting Admin Token

```bash
curl -X POST http://your-backend/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@ficore.com","password":"admin123"}'
```

Save the `access_token` from the response.

---

## 📊 Admin Dashboard

### Accessing the Dashboard

**URL**: `http://your-backend/admin/analytics_dashboard.html`

**Features**:
1. **Overview Metrics**
   - Total users, DAU, WAU, MAU
   - Entry counts (income/expense)
   - Event breakdown
   - Top users
   - Recent activity

2. **Admin Tools** (New!)
   - 📊 View All Users Data
   - 📈 System Statistics
   - 🔍 Search User Data
   - ⚖️ NDPR Requests

---

## 🛠️ Admin API Endpoints

### 1. View All Users Analytics Data

**Endpoint**: `GET /api/analytics/admin/all-users-data`

**Purpose**: View analytics events from all users with filtering

**Query Parameters**:
- `user_id` - Filter by specific user (optional)
- `event_type` - Filter by event type (optional)
- `start_date` - Filter from date (optional)
- `end_date` - Filter to date (optional)
- `limit` - Number of events (default: 100, max: 1000)
- `offset` - Pagination offset (default: 0)

**Example**:
```bash
curl -X GET "http://your-backend/api/analytics/admin/all-users-data?limit=50" \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

**Response**:
```json
{
  "success": true,
  "data": {
    "events": [
      {
        "eventId": "...",
        "userId": "...",
        "userEmail": "user@example.com",
        "userName": "John Doe",
        "eventType": "user_logged_in",
        "timestamp": "2025-12-02T10:30:00Z",
        "eventDetails": {...},
        "deviceInfo": {...}
      }
    ],
    "pagination": {
      "total": 1234,
      "limit": 50,
      "offset": 0,
      "hasMore": true
    }
  }
}
```

**Use Cases**:
- Monitor user activity across the platform
- Identify unusual patterns
- Generate reports
- Audit user behavior

---

### 2. View Specific User's Analytics Data

**Endpoint**: `GET /api/analytics/admin/user/<user_id>/data`

**Purpose**: Get complete analytics profile for a specific user

**Example**:
```bash
curl -X GET "http://your-backend/api/analytics/admin/user/507f1f77bcf86cd799439011/data" \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

**Response**:
```json
{
  "success": true,
  "data": {
    "user": {
      "userId": "507f1f77bcf86cd799439011",
      "email": "user@example.com",
      "name": "John Doe",
      "createdAt": "2025-01-15T10:00:00Z"
    },
    "analytics": {
      "totalEvents": 145,
      "eventTypes": {
        "user_logged_in": 45,
        "income_entry_created": 60,
        "expense_entry_created": 40
      },
      "firstActivity": "2025-01-15T10:30:00Z",
      "lastActivity": "2025-12-02T09:15:00Z",
      "events": [...]
    },
    "dataRetentionPeriod": "12 months"
  }
}
```

**Use Cases**:
- Respond to user data access requests (NDPR)
- Investigate user issues
- Understand user behavior
- Generate user-specific reports

---

### 3. Delete User's Analytics Data (NDPR Compliance)

**Endpoint**: `DELETE /api/analytics/admin/user/<user_id>/data`

**Purpose**: Permanently delete all analytics data for a user

**⚠️ Warning**: This action is irreversible and logged for audit purposes.

**Example**:
```bash
curl -X DELETE "http://your-backend/api/analytics/admin/user/507f1f77bcf86cd799439011/data" \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

**Response**:
```json
{
  "success": true,
  "data": {
    "userId": "507f1f77bcf86cd799439011",
    "userEmail": "user@example.com",
    "deletedEvents": 145,
    "deletedAt": "2025-12-02T10:30:00Z",
    "deletedBy": "admin@ficore.com"
  },
  "message": "Successfully deleted 145 analytics events for user"
}
```

**Use Cases**:
- NDPR Right to Erasure requests
- User account deletion
- Data cleanup
- Compliance requirements

**Audit Log**:
Every deletion is logged with:
- Admin who performed the action
- User whose data was deleted
- Number of events deleted
- Timestamp

---

### 4. System Analytics Statistics

**Endpoint**: `GET /api/analytics/admin/stats`

**Purpose**: Get comprehensive system-wide analytics metrics

**Example**:
```bash
curl -X GET "http://your-backend/api/analytics/admin/stats" \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

**Response**:
```json
{
  "success": true,
  "data": {
    "overview": {
      "totalEvents": 12450,
      "uniqueUsers": 350,
      "avgEventsPerUser": 35.57,
      "storageSizeMB": 12.5
    },
    "timeRanges": {
      "last24Hours": 450,
      "last7Days": 2340,
      "last30Days": 8920
    },
    "eventTypes": {
      "user_logged_in": 3450,
      "income_entry_created": 4200,
      "expense_entry_created": 4800
    },
    "dateRange": {
      "oldest": "2025-01-01T00:00:00Z",
      "newest": "2025-12-02T10:30:00Z"
    },
    "dataRetention": {
      "policy": "12 months",
      "autoCleanup": "Enabled"
    }
  }
}
```

**Use Cases**:
- Monitor system health
- Capacity planning
- Performance analysis
- Executive reporting

---

### 5. NDPR Requests Summary

**Endpoint**: `GET /api/analytics/admin/ndpr-requests`

**Purpose**: Get summary of NDPR-related activities

**Example**:
```bash
curl -X GET "http://your-backend/api/analytics/admin/ndpr-requests" \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

**Response**:
```json
{
  "success": true,
  "data": {
    "summary": {
      "totalUsers": 500,
      "usersWithAnalytics": 350,
      "usersWithoutAnalytics": 150
    }
  }
}
```

**Use Cases**:
- NDPR compliance reporting
- Data protection audits
- User privacy monitoring

---

## 🎯 Common Admin Tasks

### Task 1: Respond to User Data Access Request

**Scenario**: User emails team@ficoreafrica.com requesting their analytics data

**Steps**:
1. Verify user identity
2. Get user ID from email
3. Call admin endpoint to get user data:
   ```bash
   curl -X GET "http://your-backend/api/analytics/admin/user/USER_ID/data" \
     -H "Authorization: Bearer ADMIN_TOKEN"
   ```
4. Send data to user via secure email
5. Log the request for compliance

**Response Time**: Within 7 business days (NDPR requirement: 30 days)

---

### Task 2: Process Data Deletion Request

**Scenario**: User requests deletion of their analytics data

**Steps**:
1. Verify user identity
2. Confirm deletion request in writing
3. Delete user data:
   ```bash
   curl -X DELETE "http://your-backend/api/analytics/admin/user/USER_ID/data" \
     -H "Authorization: Bearer ADMIN_TOKEN"
   ```
4. Send confirmation email to user
5. Document the deletion for audit

**Response Time**: Within 30 days (NDPR requirement)

---

### Task 3: Investigate Unusual Activity

**Scenario**: Suspicious activity detected for a user

**Steps**:
1. Access admin dashboard
2. Click "Search User Data"
3. Enter user email
4. Review user's event history
5. Look for patterns:
   - Unusual login times
   - Excessive API calls
   - Suspicious device info
6. Take appropriate action

---

### Task 4: Generate Monthly Report

**Scenario**: Need monthly analytics report for management

**Steps**:
1. Access admin dashboard
2. Click "System Statistics"
3. Review metrics:
   - Total events
   - Active users
   - Event distribution
   - Storage usage
4. Export data (screenshot or API call)
5. Create report document

---

### Task 5: Monitor NDPR Compliance

**Scenario**: Regular compliance check

**Steps**:
1. Access admin dashboard
2. Click "NDPR Requests"
3. Review:
   - Users with/without analytics data
   - Data retention status
   - Recent deletions (check logs)
4. Ensure auto-cleanup is running
5. Document compliance status

---

## 🔍 Dashboard Features

### Overview Section
- **Total Users**: All registered users
- **DAU**: Users who logged in today
- **WAU**: Users who logged in this week
- **MAU**: Users who logged in this month
- **Entry Counts**: Income and expense entries

### Event Counts Section
- Breakdown by event type
- Filterable by time period
- Visual representation

### Top Users Section
- Most active users by event count
- Ranked list with activity metrics
- Quick access to user details

### Recent Activity Section
- Last 10 events across all users
- Real-time updates
- User identification

### Admin Tools Section (New!)
- **View All Users Data**: Browse all analytics events
- **System Statistics**: Comprehensive metrics
- **Search User Data**: Find specific user
- **NDPR Requests**: Compliance summary

---

## 🛡️ Security & Audit

### Access Control
- Only users with `role: 'admin'` can access admin endpoints
- All admin actions require valid JWT token
- Token expires after 24 hours

### Audit Logging
All admin actions are logged:
- User data access (who viewed what)
- Data deletions (who deleted what, when)
- System queries (who ran what query)

**Log Format**:
```
[2025-12-02 10:30:00] Admin admin@ficore.com deleted 145 analytics events for user user@example.com (ID: 507f...)
```

### Data Protection
- All API calls use HTTPS
- Data encrypted in transit and at rest
- Admin dashboard requires authentication
- No sensitive data in logs

---

## 📋 NDPR Compliance Checklist

### For Each User Request:

**Data Access Request**:
- [ ] Verify user identity
- [ ] Retrieve user data via admin API
- [ ] Send data in readable format (JSON)
- [ ] Respond within 7 business days
- [ ] Log the request

**Data Deletion Request**:
- [ ] Verify user identity
- [ ] Confirm deletion request in writing
- [ ] Delete data via admin API
- [ ] Send confirmation email
- [ ] Respond within 30 days
- [ ] Log the deletion

**Data Export Request**:
- [ ] Verify user identity
- [ ] Export data via admin API
- [ ] Provide in portable format (JSON)
- [ ] Respond within 7 business days
- [ ] Log the export

---

## 🚨 Troubleshooting

### Issue: Can't Access Admin Dashboard

**Solution**:
1. Verify you have admin role: Check `role: 'admin'` in database
2. Get fresh admin token: Login again
3. Check token expiration: Tokens expire after 24 hours
4. Verify URL: Should be `/admin/analytics_dashboard.html`

### Issue: "Unauthorized" Error

**Solution**:
1. Check token is valid
2. Verify admin role in database
3. Ensure token is in Authorization header
4. Try logging in again

### Issue: User Data Not Found

**Solution**:
1. Verify user ID is correct (ObjectId format)
2. Check if user has any analytics events
3. Confirm user exists in database
4. Try searching by email instead

### Issue: Deletion Not Working

**Solution**:
1. Verify you have admin role
2. Check user ID format
3. Ensure MongoDB connection is active
4. Check server logs for errors

---

## 📞 Support

### For Admin Issues
- **Technical Support**: admin@ficore.com
- **DPO**: team@ficoreafrica.com
- **Emergency**: +234-456-6899

### For User Requests
- **Privacy Requests**: team@ficoreafrica.com
- **Data Access**: team@ficoreafrica.com
- **General Support**: team@ficoreafrica.com

---

## 📚 Related Documentation

- **NDPR Compliance**: `NDPR_COMPLIANCE_DOCUMENTATION.md`
- **Privacy Policy**: `lib/screens/legal/privacy_policy_screen.dart`
- **Analytics System**: `ANALYTICS_SYSTEM_README.md`
- **Quick Reference**: `NDPR_QUICK_REFERENCE.md`

---

## ✅ Admin Capabilities Summary

As an admin, you can:

✅ **View**:
- All users' analytics data
- Individual user analytics profiles
- System-wide statistics
- Event breakdowns
- Activity trends

✅ **Manage**:
- Delete user analytics data
- Search for specific users
- Filter events by type/date
- Export data for users
- Monitor NDPR compliance

✅ **Monitor**:
- System health
- Storage usage
- Active users (DAU/WAU/MAU)
- Event distribution
- Data retention status

✅ **Comply**:
- NDPR data access requests
- NDPR deletion requests
- Data portability requests
- Audit logging
- Compliance reporting

---

**Last Updated**: December 2, 2025  
**Version**: 1.0  
**Contact**: admin@ficore.com
