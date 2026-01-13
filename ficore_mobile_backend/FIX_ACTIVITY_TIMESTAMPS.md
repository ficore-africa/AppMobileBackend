# Backend Fix: Activity Timestamps

## Problem
Activities are showing "21h ago" for entries created 2 minutes ago because the backend is using `date`/`dateReceived` fields (user-selected transaction date at 12:00am) instead of `createdAt` (actual creation timestamp).

## Root Cause
Multiple endpoints are constructing activity objects with the wrong timestamp field:

### File: `blueprints/summaries.py`
**Line 52** (Expenses):
```python
'date': expense.get('date', expense.get('createdAt', datetime.utcnow())).isoformat() + 'Z',
```

**Line 86** (Incomes):
```python
'date': income.get('dateReceived', income.get('createdAt', datetime.utcnow())).isoformat() + 'Z',
```

### File: `blueprints/admin.py`
**Line 1154** (Expenses):
```python
'timestamp': expense.get('date', datetime.utcnow()).isoformat() + 'Z',
```

**Line 1166** (Incomes):
```python
'timestamp': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z',
```

### File: `blueprints/dashboard.py`
Similar issues in activity construction.

---

## Solution

### Change 1: `blueprints/summaries.py` (Line 52)
```python
# BEFORE (WRONG)
'date': expense.get('date', expense.get('createdAt', datetime.utcnow())).isoformat() + 'Z',

# AFTER (CORRECT)
'date': expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
'transactionDate': expense.get('date', datetime.utcnow()).isoformat() + 'Z',  # Keep for reference
```

### Change 2: `blueprints/summaries.py` (Line 86)
```python
# BEFORE (WRONG)
'date': income.get('dateReceived', income.get('createdAt', datetime.utcnow())).isoformat() + 'Z',

# AFTER (CORRECT)
'date': income.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
'transactionDate': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z',  # Keep for reference
```

### Change 3: `blueprints/admin.py` (Line 1154)
```python
# BEFORE (WRONG)
'timestamp': expense.get('date', datetime.utcnow()).isoformat() + 'Z',

# AFTER (CORRECT)
'timestamp': expense.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
```

### Change 4: `blueprints/admin.py` (Line 1166)
```python
# BEFORE (WRONG)
'timestamp': income.get('dateReceived', datetime.utcnow()).isoformat() + 'Z',

# AFTER (CORRECT)
'timestamp': income.get('createdAt', datetime.utcnow()).isoformat() + 'Z',
```

---

## Why This Matters

### User-Selected Date vs Creation Time
- **`date`/`dateReceived`**: User-selected transaction date (e.g., "January 9, 2026" → "2026-01-09T00:00:00Z")
- **`createdAt`**: Actual creation timestamp (e.g., "2026-01-10T10:28:35Z")

### Example Scenario
1. User creates income entry on Jan 10 at 10:28 AM
2. User selects transaction date as Jan 9 (yesterday)
3. Backend stores:
   - `dateReceived`: "2026-01-09T00:00:00Z" (midnight yesterday)
   - `createdAt`: "2026-01-10T10:28:35Z" (actual creation time)
4. Activity endpoint returns `date` field with midnight timestamp
5. Frontend calculates: "21 hours ago" (from midnight yesterday to 10:28 AM today)

### Correct Behavior
- Activity timestamp should use `createdAt` (when entry was created)
- Transaction date should be separate field for filtering/reporting
- Frontend shows: "Just now" → "2m ago" → "5m ago"

---

## Impact

### Before Fix
- ❌ Activities show "21h ago" for entries created minutes ago
- ❌ Confusing UX - users think system is broken
- ❌ Timestamp doesn't reflect actual activity time

### After Fix
- ✅ Activities show accurate timestamps ("Just now", "2m ago")
- ✅ Clear UX - users see real-time updates
- ✅ Timestamp reflects actual creation time
- ✅ Transaction date still available for filtering/reporting

---

## Testing

### Test Case 1: Create Entry with Past Date
1. Create income entry with amount ₦100,000
2. Select transaction date as yesterday (Jan 9)
3. Save entry
4. Check Recent Activity
5. **Expected**: Shows "Just now" (not "21h ago")

### Test Case 2: Create Entry with Future Date
1. Create expense entry with amount ₦50,000
2. Select transaction date as tomorrow (Jan 11)
3. Save entry
4. Check Recent Activity
5. **Expected**: Shows "Just now" (not "in 14h")

### Test Case 3: Wait and Verify
1. Create entry
2. Wait 2 minutes
3. Check Recent Activity
4. **Expected**: Shows "2m ago" (accurate)

---

## Files to Modify

1. `ficore_mobile_backend/blueprints/summaries.py` (lines 52, 86)
2. `ficore_mobile_backend/blueprints/admin.py` (lines 1154, 1166)
3. `ficore_mobile_backend/blueprints/dashboard.py` (check for similar patterns)

---

## Deployment Notes

- This is a **non-breaking change** (adds new field, doesn't remove old one)
- Frontend already has fallback logic to handle both fields
- Can be deployed independently of frontend changes
- Recommend deploying backend fix first, then frontend fix

---

## Related Frontend Fix

The frontend fix in `lib/providers/activities_provider.dart` prioritizes `timestamp` over `date`:

```dart
timestamp: DateTime.tryParse(activityJson['timestamp']?.toString() ?? '') ?? 
          DateTime.tryParse(activityJson['created_at']?.toString() ?? '') ??
          DateTime.tryParse(activityJson['createdAt']?.toString() ?? '') ??
          DateTime.now(),
```

This provides defense-in-depth: even if backend sends wrong field, frontend won't use it.

