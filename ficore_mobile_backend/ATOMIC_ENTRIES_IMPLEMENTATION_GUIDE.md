# Atomic Entry Creation Implementation Guide

## Overview

This document provides step-by-step instructions for implementing and deploying the new atomic entry creation endpoints that solve the critical FC charging bug.

## Problem Statement

**Current Issue**: FREE users over their monthly limit can get entries without being charged FCs because:
1. Entry is saved to database first
2. FC deduction happens separately with `unawaited()` (fire and forget)
3. If FC deduction fails, entry stays saved (free entry for user)

**Solution**: Atomic transaction that ensures entry creation and FC deduction happen together or not at all.

---

## Implementation Steps

### Step 1: Register the New Blueprint

**File**: `ficore_mobile_backend/app.py`

Add the atomic entries blueprint registration:

```python
# Import the new blueprint
from blueprints.atomic_entries import init_atomic_entries_blueprint

# Register blueprint (add after other blueprint registrations)
atomic_entries_bp = init_atomic_entries_blueprint(mongo, token_required, serialize_doc)
app.register_blueprint(atomic_entries_bp)

print("✓ Atomic entries blueprint registered")
```

### Step 2: Test the Endpoints Locally

**Start the development server**:
```bash
cd ficore_mobile_backend
python start_server.py
```

**Test with curl or Postman**:

```bash
# Test expense creation (free user within limit)
curl -X POST http://localhost:5000/atomic/expenses/create-with-payment \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 500.0,
    "description": "Test expense",
    "category": "Food",
    "date": "2024-01-15T10:00:00Z"
  }'

# Test income creation
curl -X POST http://localhost:5000/atomic/income/create-with-payment \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 1000.0,
    "source": "Salary",
    "category": "salary",
    "dateReceived": "2024-01-15T10:00:00Z"
  }'
```

### Step 3: Run Unit Tests

```bash
cd ficore_mobile_backend
python -m pytest tests/test_atomic_entries.py -v
```

**Expected output**:
```
test_free_user_within_limit_no_charge PASSED
test_free_user_over_limit_with_sufficient_fcs PASSED
test_free_user_over_limit_insufficient_fcs PASSED
test_premium_user_unlimited_no_charge PASSED
test_admin_user_unlimited_no_charge PASSED
test_concurrent_requests_race_condition PASSED
test_rollback_on_fc_deduction_failure PASSED
test_validation_errors PASSED
```

### Step 4: Deploy to Staging

```bash
# Deploy to staging environment
git add .
git commit -m "feat: Add atomic entry creation endpoints with FC deduction"
git push origin staging

# Or use deployment script
./deploy.sh staging
```

**Verify staging deployment**:
```bash
curl https://staging-api.ficore.africa/atomic/expenses/create-with-payment \
  -H "Authorization: Bearer STAGING_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount": 100, "description": "Test", "category": "Food"}'
```

### Step 5: Monitor Staging

**Check logs for**:
- ✓ Successful entry creations
- ✓ Successful FC deductions
- ✓ Proper rollbacks on failures
- ✗ Any unexpected errors

**Staging monitoring checklist**:
- [ ] Free user within limit: Entry created, no charge
- [ ] Free user over limit with FCs: Entry created, FC charged
- [ ] Free user over limit without FCs: Entry rejected
- [ ] Premium user: Entry created, no charge
- [ ] Concurrent requests: Only one succeeds
- [ ] Network errors: Proper rollback

### Step 6: Deploy to Production

```bash
# Deploy to production
git checkout main
git merge staging
git push origin main

# Or use deployment script
./deploy.sh production
```

### Step 7: Update Frontend (Phase 2)

After backend is deployed and verified, update frontend to use new endpoints.

**See**: `FREE_USER_FC_CHARGING_ANALYSIS.md` - Phase 2 section

---

## API Documentation

### POST /atomic/expenses/create-with-payment

Creates an expense with atomic FC deduction.

**Request**:
```json
{
  "amount": 500.0,
  "description": "Grocery shopping",
  "category": "Food",
  "date": "2024-01-15T10:00:00Z",
  "budgetId": "optional_budget_id",
  "tags": ["groceries", "weekly"],
  "paymentMethod": "cash",
  "location": "Shoprite",
  "notes": "Weekly shopping"
}
```

**Response (Success - Free entry)**:
```json
{
  "success": true,
  "data": {
    "expense": {
      "id": "65a1b2c3d4e5f6g7h8i9j0k1",
      "amount": 500.0,
      "description": "Grocery shopping",
      "category": "Food",
      "date": "2024-01-15T10:00:00Z",
      "createdAt": "2024-01-15T10:05:00Z",
      "updatedAt": "2024-01-15T10:05:00Z"
    },
    "fc_charge_amount": 0.0,
    "fc_balance": 5.0,
    "monthly_entries": {
      "count": 16,
      "limit": 20,
      "remaining": 4
    }
  },
  "message": "Expense created successfully. 4 free entries remaining this month."
}
```

**Response (Success - FC charged)**:
```json
{
  "success": true,
  "data": {
    "expense": { ... },
    "fc_charge_amount": 1.0,
    "fc_balance": 4.0,
    "monthly_entries": {
      "count": 22,
      "limit": 20,
      "remaining": 0
    }
  },
  "message": "Expense created successfully. 1.0 FC charged. New balance: 4.0 FC."
}
```

**Response (Error - Insufficient FCs)**:
```json
{
  "success": false,
  "message": "Insufficient FiCore Credits. Need 1.0 FC, have 0.5 FC.",
  "error_type": "insufficient_credits",
  "data": {
    "fc_required": 1.0,
    "fc_balance": 0.5,
    "monthly_entries": {
      "count": 21,
      "limit": 20,
      "remaining": 0
    }
  }
}
```

### POST /atomic/income/create-with-payment

Creates an income entry with atomic FC deduction.

**Request**:
```json
{
  "amount": 1000.0,
  "source": "Salary",
  "description": "Monthly salary",
  "category": "salary",
  "dateReceived": "2024-01-15T10:00:00Z",
  "frequency": "monthly",
  "isRecurring": true,
  "nextRecurringDate": "2024-02-15T10:00:00Z",
  "metadata": {
    "sales_type": "cash"
  }
}
```

**Response**: Same structure as expense endpoint

---

## Error Codes

| Status Code | Error Type | Description |
|-------------|------------|-------------|
| 201 | - | Success - Entry created |
| 400 | validation_error | Invalid request data |
| 401 | unauthorized | Invalid or missing token |
| 402 | insufficient_credits | User doesn't have enough FCs |
| 404 | user_not_found | User doesn't exist |
| 500 | fc_deduction_failed | FC deduction failed (entry rolled back) |
| 500 | server_error | Unexpected server error |

---

## Monitoring & Alerts

### Key Metrics to Track

1. **Success Rate**: % of successful entry creations
2. **FC Deduction Rate**: % of entries that required FC charge
3. **Rollback Rate**: % of entries that were rolled back
4. **Error Rate**: % of failed requests by error type

### Logging

All operations are logged with the following format:

```
✓ Expense created: 65a1b2c3d4e5f6g7h8i9j0k1
✓ FC deducted: 1.0 FC (Balance: 5.0 → 4.0)
✓ FC transaction recorded: 65a1b2c3d4e5f6g7h8i9j0k2
```

Or on failure:

```
✗ FC deduction failed: Insufficient credits
✗ Rolling back expense: 65a1b2c3d4e5f6g7h8i9j0k1
✓ Rolled back expense: 65a1b2c3d4e5f6g7h8i9j0k1
```

### Alerts to Set Up

1. **High Rollback Rate**: Alert if rollback rate > 5%
2. **FC Deduction Failures**: Alert on any FC deduction failure
3. **Orphaned Entries**: Alert if entries exist with `fcChargeRequired=true` and `fcChargeCompleted=false` for > 1 hour

---

## Rollback Plan

If issues arise after deployment:

### Immediate Rollback (< 5 minutes)

```bash
# Revert to previous version
git revert HEAD
git push origin main

# Or rollback deployment
./deploy.sh production --rollback
```

### Partial Rollback

Keep atomic endpoints but disable for certain users:

```python
# Add feature flag
ATOMIC_ENTRIES_ENABLED = os.getenv('ATOMIC_ENTRIES_ENABLED', 'false')

@atomic_entries_bp.before_request
def check_feature_flag():
    if ATOMIC_ENTRIES_ENABLED != 'true':
        return jsonify({
            'success': False,
            'message': 'Feature temporarily disabled'
        }), 503
```

---

## Troubleshooting

### Issue: Entries created but FC not deducted

**Diagnosis**:
```sql
-- Find entries with incomplete FC charges
db.expenses.find({
  fcChargeRequired: true,
  fcChargeCompleted: false,
  fcChargeAttemptedAt: { $lt: new Date(Date.now() - 3600000) }
})
```

**Fix**: Run cleanup script (see `scripts/cleanup_orphaned_entries.py`)

### Issue: FC deducted but entry not created

**Diagnosis**:
```sql
-- Find FC transactions without corresponding entries
db.credit_transactions.find({
  operation: 'create_expense_atomic',
  status: 'completed'
}).forEach(tx => {
  const expense = db.expenses.findOne({ _id: ObjectId(tx.metadata.expense_id) });
  if (!expense) {
    print(`Orphaned transaction: ${tx._id}`);
  }
});
```

**Fix**: Refund FC to user

### Issue: High rollback rate

**Possible causes**:
1. Network issues between app and database
2. Concurrent request race conditions
3. Database performance issues

**Investigation**:
- Check database connection pool
- Review concurrent request patterns
- Check database query performance

---

## Success Criteria

✅ **Technical**:
- 0% free entries for users over monthly limit
- 100% atomic transactions (no orphaned entries)
- <1% failed FC deductions due to system errors
- <300ms average response time

✅ **Business**:
- 100% revenue capture for over-limit entries
- $0 revenue leakage
- Reduced support tickets related to FC charges

✅ **User Experience**:
- <100ms perceived delay (optimistic UI)
- Clear error messages
- Smooth entry creation flow

---

## Next Steps

After successful backend deployment:

1. ✅ Update frontend to use new endpoints (Phase 2)
2. ✅ Add FC balance display in entry screens (Phase 3)
3. ✅ Implement enhanced error handling (Phase 3)
4. ✅ Add monitoring dashboard (Phase 4)
5. ✅ Implement orphaned entry cleanup job (Phase 4)

---

## Support

For issues or questions:
- Check logs: `/var/log/ficore/app.log`
- Review monitoring dashboard
- Contact: dev@ficore.africa
