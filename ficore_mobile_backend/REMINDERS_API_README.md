# Reminders API (FiCore Mobile Backend)

This folder contains a small reminders blueprint and a simple personalization worker.

Environment
- MONGO_URI - MongoDB connection string (default: `mongodb://localhost:27017/ficore_mobile`)

Endpoints (blueprint: `/` root paths below are relative to the main API host)

- POST /reminders/interactions
  - Payload: { reminderId, event: 'shown|clicked|dismissed|snoozed|whatsapp', ts?: ISO8601, meta?: {} }
  - Auth: Bearer token required
  - Notes: Lightweight dedupe (30s) and rate-limit protection.

- GET /reminders/personalized
  - Query: (none) uses authenticated user
  - Returns: array of personalized reminders (id,title,body,score)

- POST /users/<id>/preferences
  - Payload: { whatsapp_opt_in?: bool, whatsapp_phone?: string, nudges_enabled?: bool }
  - Auth: Bearer token required (user must be same as <id> or admin)

- POST /users/<id>/optout
  - Marks `settings.privacy.optOutNudges` = true for the user

Worker
- `scripts/personalization_worker.py` aggregates recent interactions and writes summaries to `personalization` collection.

Run locally (example)

```powershell
$env:MONGO_URI = 'mongodb://localhost:27017/ficore_mobile'
python -m flask run --host=0.0.0.0 --port=5000
# or run the worker
python scripts/personalization_worker.py
```

Notes
- The endpoints are intentionally conservative — they perform light validation and protect against spam. They should be extended with schema validation when moving to production.
- Indexes for `reminder_interactions` are created at blueprint init to help queries for aggregation. If you modify collection names, update the index creation.
