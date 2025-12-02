# Admin Dashboard Login Guide

## Quick Access

### 🔐 Admin Login Page
**URL**: `http://your-backend-url/admin/admin_login.html`

### 📊 Analytics Dashboard (After Login)
**URL**: `http://your-backend-url/admin/analytics_dashboard.html`

---

## Default Admin Credentials

### Initial Setup
When you first deploy FiCore, a default admin account is automatically created:

**Email**: `admin@ficore.com`  
**Password**: `admin123`

⚠️ **IMPORTANT**: Change this password immediately after first login!

---

## How to Login

### Step 1: Access Login Page

Navigate to: `http://your-backend-url/admin/admin_login.html`

**Local Development**:
```
http://localhost:5000/admin/admin_login.html
```

**Production**:
```
https://your-domain.com/admin/admin_login.html
```

### Step 2: Enter Credentials

1. Enter your admin email
2. Enter your password
3. Click "Login to Dashboard"

### Step 3: Access Dashboard

After successful login, you'll be automatically redirected to the analytics dashboard.

---

## Login Flow

```
1. User visits admin_login.html
   ↓
2. Enters email and password
   ↓
3. System calls POST /auth/login
   ↓
4. Verifies credentials
   ↓
5. Checks if user has admin role
   ↓
6. If admin: Store token and redirect to dashboard
   If not admin: Show "Access denied" error
   ↓
7. Dashboard loads with admin token
   ↓
8. Admin can access all analytics features
```

---

## Authentication Details

### Token Storage
- Admin token is stored in browser's `localStorage`
- Token is valid for 24 hours
- Token is automatically included in all API requests

### Session Management
- Login persists across browser sessions
- Token is validated on each API call
- Expired tokens trigger automatic logout

### Security Features
- Admin role verification
- Token expiration (24 hours)
- Automatic logout on token expiry
- Secure HTTPS communication (in production)

---

## Troubleshooting

### Issue: "Access denied. Admin role required"

**Cause**: Your account doesn't have admin role

**Solution**:
1. Check your role in MongoDB:
   ```javascript
   db.users.findOne({email: "your-email@example.com"})
   ```
2. If role is not 'admin', update it:
   ```javascript
   db.users.updateOne(
     {email: "your-email@example.com"},
     {$set: {role: "admin"}}
   )
   ```

### Issue: "Invalid credentials"

**Cause**: Wrong email or password

**Solution**:
1. Verify email is correct
2. Check password (case-sensitive)
3. Try default credentials: admin@ficore.com / admin123
4. Reset password if needed (see below)

### Issue: "Connection error"

**Cause**: Backend server not running or network issue

**Solution**:
1. Verify backend is running: `http://your-backend/health`
2. Check network connection
3. Verify URL is correct
4. Check browser console for errors

### Issue: "Session expired"

**Cause**: Token expired (24 hours)

**Solution**:
1. Click "Logout" button
2. Login again with credentials
3. New token will be issued

### Issue: Can't access dashboard directly

**Cause**: No valid token in localStorage

**Solution**:
- Dashboard automatically redirects to login page
- Login first, then you'll be redirected to dashboard
- Don't bookmark dashboard URL, bookmark login URL

---

## Password Management

### Changing Admin Password

**Method 1: Via API**
```bash
curl -X PUT http://your-backend/users/password \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "currentPassword": "admin123",
    "newPassword": "your-new-secure-password"
  }'
```

**Method 2: Via MongoDB**
```javascript
// Generate password hash first (use bcrypt)
const bcrypt = require('bcrypt');
const newPasswordHash = bcrypt.hashSync('your-new-password', 10);

// Update in database
db.users.updateOne(
  {email: "admin@ficore.com"},
  {$set: {password: newPasswordHash}}
)
```

### Creating Additional Admin Users

**Via MongoDB**:
```javascript
db.users.insertOne({
  email: "newadmin@ficore.com",
  password: "$2b$10$...", // bcrypt hash of password
  firstName: "New",
  lastName: "Admin",
  displayName: "New Admin",
  role: "admin",
  ficoreCreditBalance: 0,
  isActive: true,
  createdAt: new Date(),
  updatedAt: new Date(),
  settings: {
    notifications: {push: true, email: true},
    privacy: {profileVisibility: "private"},
    preferences: {currency: "NGN", language: "en", theme: "light"}
  }
})
```

---

## Security Best Practices

### 1. Change Default Password
```bash
# Immediately after first login
curl -X PUT http://your-backend/users/password \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "currentPassword": "admin123",
    "newPassword": "StrongP@ssw0rd123!"
  }'
```

### 2. Use Strong Passwords
- Minimum 12 characters
- Mix of uppercase, lowercase, numbers, symbols
- No common words or patterns
- Unique password (not used elsewhere)

### 3. Limit Admin Access
- Only create admin accounts for trusted personnel
- Review admin users regularly
- Remove admin access when no longer needed

### 4. Monitor Admin Activity
- Check server logs for admin logins
- Review admin actions in audit logs
- Set up alerts for suspicious activity

### 5. Use HTTPS in Production
- Always use HTTPS for admin access
- Never send credentials over HTTP
- Use SSL/TLS certificates

### 6. Regular Token Rotation
- Logout and login regularly
- Don't share admin tokens
- Clear browser cache when done

---

## Admin Dashboard Features

Once logged in, you have access to:

### Overview Metrics
- Total users, DAU, WAU, MAU
- Entry counts (income/expense)
- Event breakdown
- Top users
- Recent activity

### Admin Tools
- 📊 View All Users Data
- 📈 System Statistics
- 🔍 Search User Data
- ⚖️ NDPR Requests

### User Management
- View individual user analytics
- Delete user analytics data (NDPR)
- Export user data
- Monitor user activity

### System Monitoring
- Total events tracked
- Storage usage
- Event distribution
- Performance metrics

---

## API Endpoints Available to Admin

### Analytics Endpoints
```
GET  /api/analytics/dashboard/overview
GET  /api/analytics/dashboard/event-counts
GET  /api/analytics/dashboard/user-growth
GET  /api/analytics/dashboard/mau-trend
GET  /api/analytics/dashboard/top-users
```

### Admin-Only Endpoints
```
GET    /api/analytics/admin/all-users-data
GET    /api/analytics/admin/user/<user_id>/data
DELETE /api/analytics/admin/user/<user_id>/data
GET    /api/analytics/admin/stats
GET    /api/analytics/admin/ndpr-requests
```

### Health Check
```
GET /admin/health
```

---

## Logout

### How to Logout

1. Click the "🚪 Logout" button in the top-right corner
2. Confirm logout
3. You'll be redirected to login page
4. Token is cleared from localStorage

### Manual Logout (if needed)

Open browser console and run:
```javascript
localStorage.removeItem('admin_token');
localStorage.removeItem('admin_email');
localStorage.removeItem('admin_name');
window.location.href = 'admin_login.html';
```

---

## Multi-Admin Setup

### Creating Multiple Admin Accounts

For teams with multiple administrators:

1. **Create new admin user in database**:
   ```javascript
   db.users.insertOne({
     email: "admin2@ficore.com",
     password: bcrypt.hashSync("SecurePassword123!", 10),
     firstName: "Admin",
     lastName: "Two",
     displayName: "Admin Two",
     role: "admin",
     // ... other required fields
   })
   ```

2. **Each admin logs in with their own credentials**

3. **All admins have same access level**

### Admin Audit Trail

All admin actions are logged:
- Who accessed what data
- Who deleted what data
- When actions were performed
- IP addresses of admin access

Check server logs for audit trail:
```bash
grep "Admin" /var/log/ficore/app.log
```

---

## Production Deployment

### Environment Variables

Set these for production:

```bash
# Backend URL
BACKEND_URL=https://api.ficore.com

# Admin credentials (change these!)
ADMIN_EMAIL=admin@yourcompany.com
ADMIN_PASSWORD=YourSecurePassword123!

# JWT secret (use strong random string)
SECRET_KEY=your-very-long-random-secret-key
```

### HTTPS Configuration

Ensure admin pages are only accessible via HTTPS:

```nginx
# Nginx configuration
server {
    listen 443 ssl;
    server_name api.ficore.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location /admin/ {
        # Admin pages
        root /path/to/admin_web_app;
        index admin_login.html;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name api.ficore.com;
    return 301 https://$server_name$request_uri;
}
```

---

## Quick Reference

### URLs
- **Login**: `/admin/admin_login.html`
- **Dashboard**: `/admin/analytics_dashboard.html`

### Default Credentials
- **Email**: `admin@ficore.com`
- **Password**: `admin123`

### Token Expiry
- **Duration**: 24 hours
- **Storage**: localStorage
- **Auto-logout**: On expiry

### Support
- **Technical**: admin@ficore.com
- **Security**: team@ficoreafrica.com
- **Emergency**: +234-456-6899

---

## Checklist

### First-Time Setup
- [ ] Access login page
- [ ] Login with default credentials
- [ ] Change default password
- [ ] Verify dashboard access
- [ ] Test admin features
- [ ] Create additional admin users (if needed)
- [ ] Document new credentials securely
- [ ] Set up HTTPS (production)
- [ ] Configure monitoring/alerts

### Regular Maintenance
- [ ] Review admin users monthly
- [ ] Check audit logs weekly
- [ ] Update passwords quarterly
- [ ] Monitor for suspicious activity
- [ ] Backup admin credentials securely

---

**Last Updated**: December 2, 2025  
**Version**: 1.0  
**Contact**: admin@ficore.com
