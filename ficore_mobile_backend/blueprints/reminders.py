from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from datetime import datetime, timedelta

def init_reminders_blueprint(mongo, token_required, serialize_doc=None):
    """Initialize the reminders blueprint.

    Endpoints added:
    - POST /reminders/interactions
    - GET  /reminders/personalized
    - POST /users/<id>/preferences
    - POST /users/<id>/optout
    """
    bp = Blueprint('reminders', __name__)

    # Ensure indexes for fast queries and aggregation
    try:
        mongo.db.reminder_interactions.create_index([('userId', 1), ('ts', -1)])
        mongo.db.reminder_interactions.create_index([('reminderId', 1)])
        mongo.db.reminder_interactions.create_index([('event', 1), ('ts', -1)])
    except Exception as e:
        current_app.logger.warning(f"Failed creating reminder_interactions indexes: {e}")

    @bp.route('/reminders/interactions', methods=['POST'])
    @token_required
    def record_interaction(current_user):
        """Record a reminder interaction from the mobile client.

        Expected JSON body: { reminderId, event: 'shown|clicked|dismissed|snoozed|whatsapp', ts? }
        """
        payload = request.get_json(force=True, silent=True) or {}
        allowed_events = {'shown', 'clicked', 'dismissed', 'snoozed', 'whatsapp'}

        reminder_id = payload.get('reminderId')
        event = payload.get('event')
        ts = payload.get('ts')

        if not reminder_id or not event or event not in allowed_events:
            return jsonify({'success': False, 'message': 'Invalid payload'}), 400

        # Parse timestamp if provided, else use now
        try:
            if ts:
                event_ts = datetime.fromisoformat(ts)
            else:
                event_ts = datetime.utcnow()
        except Exception:
            event_ts = datetime.utcnow()

        user_obj_id = current_user.get('_id')
        if isinstance(user_obj_id, str):
            try:
                user_obj_id = ObjectId(user_obj_id)
            except Exception:
                pass

        # Simple dedupe: if same event for same reminder by this user within 30s -> treat as duplicate
        try:
            last = mongo.db.reminder_interactions.find_one(
                {'userId': user_obj_id, 'reminderId': reminder_id, 'event': event},
                sort=[('ts', -1)]
            )
            if last and 'ts' in last:
                last_ts = last['ts'] if isinstance(last['ts'], datetime) else datetime.utcnow()
                if (event_ts - last_ts) < timedelta(seconds=30):
                    return jsonify({'success': True, 'duplicate': True, 'message': 'Duplicate interaction'}), 200

            # Simple rate limiting per user: avoid > 60 interactions in last minute
            window_start = datetime.utcnow() - timedelta(seconds=60)
            recent_count = mongo.db.reminder_interactions.count_documents({'userId': user_obj_id, 'ts': {'$gte': window_start}})
            if recent_count > 60:
                return jsonify({'success': False, 'message': 'Too many interactions, slow down'}), 429

            doc = {
                'userId': user_obj_id,
                'reminderId': reminder_id,
                'event': event,
                'ts': event_ts,
                'meta': payload.get('meta', {}),
                'createdAt': datetime.utcnow()
            }

            result = mongo.db.reminder_interactions.insert_one(doc)
            return jsonify({'success': True, 'insertedId': str(result.inserted_id)}), 201

        except Exception as e:
            current_app.logger.exception('Failed recording interaction')
            return jsonify({'success': False, 'message': str(e)}), 500

    @bp.route('/reminders/personalized', methods=['GET'])
    @token_required
    def get_personalized(current_user):
        """Return a small list of personalized reminder messages for the user.

        Currently returns a simple, score-annotated list computed from recent interactions.
        """
        try:
            user_obj_id = current_user.get('_id')
            # Aggregate interactions in the last 30 days to compute a simple score
            since = datetime.utcnow() - timedelta(days=30)
            pipeline = [
                {'$match': {'userId': user_obj_id, 'ts': {'$gte': since}}},
                {'$group': {'_id': '$reminderId', 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}},
                {'$limit': 20}
            ]
            agg = list(mongo.db.reminder_interactions.aggregate(pipeline))

            # Fallback default messages (small sample)
            defaults = [
                {'id': 'd1', 'title': 'Log today’s income', 'body': 'Quickly add today’s income to keep your balance accurate.'},
                {'id': 'd2', 'title': 'Record that expense', 'body': 'Logging small expenses keeps your budget honest.'},
                {'id': 'd3', 'title': 'Check your creditors', 'body': 'A 1-minute check keeps your records tidy.'}
            ]

            personalized = []
            for item in agg:
                personalized.append({
                    'id': item['_id'],
                    'title': f'Reminder {item["_id"]}',
                    'body': 'A personalized nudge based on your activity.',
                    'score': int(item['count'])
                })

            # If no aggregated data, return defaults
            if not personalized:
                personalized = defaults

            return jsonify({'success': True, 'data': personalized}), 200
        except Exception as e:
            current_app.logger.exception('Failed to compute personalized reminders')
            return jsonify({'success': False, 'message': str(e)}), 500

    @bp.route('/users/<user_id>/preferences', methods=['POST'])
    @token_required
    def set_preferences(current_user, user_id):
        """Upsert user preferences such as WhatsApp opt-in and nudges_enabled.

        Body example: { whatsapp_opt_in: true, whatsapp_phone: '+234...' , nudges_enabled: true }
        """
        payload = request.get_json(force=True, silent=True) or {}
        try:
            # Allow users to update only their own prefs unless admin
            if str(current_user.get('_id')) != user_id and current_user.get('role') != 'admin':
                return jsonify({'success': False, 'message': 'Forbidden'}), 403

            update = {}
            prefs = {}
            if 'whatsapp_opt_in' in payload:
                prefs['whatsapp_opt_in'] = bool(payload.get('whatsapp_opt_in'))
            if 'whatsapp_phone' in payload:
                prefs['whatsapp_phone'] = payload.get('whatsapp_phone')
            if 'nudges_enabled' in payload:
                prefs['nudges_enabled'] = bool(payload.get('nudges_enabled'))

            if prefs:
                update['settings.preferences'] = prefs
                update['updatedAt'] = datetime.utcnow()
                mongo.db.users.update_one({'_id': ObjectId(user_id)}, {'$set': update}, upsert=True)

            return jsonify({'success': True, 'message': 'Preferences saved'}), 200
        except Exception as e:
            current_app.logger.exception('Failed saving preferences')
            return jsonify({'success': False, 'message': str(e)}), 500

    @bp.route('/users/<user_id>/optout', methods=['POST'])
    @token_required
    def optout(current_user, user_id):
        """User opt-out endpoint for nudges/telemetry."""
        try:
            if str(current_user.get('_id')) != user_id and current_user.get('role') != 'admin':
                return jsonify({'success': False, 'message': 'Forbidden'}), 403

            mongo.db.users.update_one({'_id': ObjectId(user_id)}, {'$set': {'settings.privacy.optOutNudges': True, 'updatedAt': datetime.utcnow()}}, upsert=True)
            return jsonify({'success': True, 'message': 'Opt-out recorded'}), 200
        except Exception as e:
            current_app.logger.exception('Failed opt-out')
            return jsonify({'success': False, 'message': str(e)}), 500

    return bp
