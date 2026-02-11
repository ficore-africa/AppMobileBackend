from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from datetime import datetime, timedelta
import hashlib
import json
import re


def init_voice_reporting_blueprint(mongo, token_required, serialize_doc):
    bp = Blueprint('voice_reporting', __name__, url_prefix='/api/voice')

    # ==================== EXTRACTION LOGIC (Backend heuristic parser) ====================

    @staticmethod
    def extract_amount_from_text(text):
        """
        Extract monetary amount from Nigerian Naira transcription.
        Handles: "5k" → 5000, "50h" → 5000, "five thousand", "₦5000", "5,000", etc.
        Returns (amount: float, confidence: float)
        """
        if not text or not isinstance(text, str):
            return 0.0, 0.0

        text_lower = text.lower().strip()

        # Pattern 1: Standard numbers with optional comma separator
        # "5000" or "5,000"
        match = re.search(r'₦?\s*(\d+(?:,\d{3})*(?:\.\d+)?)', text_lower)
        if match:
            num_str = match.group(1).replace(',', '')
            try:
                return float(num_str), 0.95
            except ValueError:
                pass

        # Pattern 2: "5k" or "5K" → 5000
        match = re.search(r'(\d+(?:\.\d+)?)\s*k(?:ay|aira)?(?:\s|$)', text_lower)
        if match:
            try:
                base = float(match.group(1))
                return base * 1000, 0.90
            except ValueError:
                pass

        # Pattern 3: "50h" or "50H" → 50 * 100 = 5000
        match = re.search(r'(\d+(?:\.\d+)?)\s*h(?:undred)?(?:\s|$)', text_lower)
        if match:
            try:
                base = float(match.group(1))
                return base * 100, 0.85
            except ValueError:
                pass

        # Pattern 4: Words like "thousand", "hundred"
        match = re.search(r'(\d+(?:\.\d+)?)\s+thousand', text_lower)
        if match:
            try:
                base = float(match.group(1))
                return base * 1000, 0.85
            except ValueError:
                pass

        match = re.search(r'(\d+(?:\.\d+)?)\s+hundred', text_lower)
        if match:
            try:
                base = float(match.group(1))
                return base * 100, 0.80
            except ValueError:
                pass

        return 0.0, 0.0

    @staticmethod
    def classify_category_and_type(transcription):
        """
        Classify transaction category and type from transcription.
        Returns (category: str, type: str)
        """
        text_lower = transcription.lower()

        # Income keywords
        income_keywords = ['salary', 'payment', 'earned', 'received', 'income', 'sold', 'sold for', 'revenue', 'commission']
        if any(kw in text_lower for kw in income_keywords):
            if 'salary' in text_lower:
                return 'income', 'salary'
            elif 'commission' in text_lower:
                return 'income', 'commission'
            elif 'sold' in text_lower:
                return 'income', 'sales'
            else:
                return 'income', 'other_income'

        # Expense keywords
        expense_keywords = ['spent', 'paid', 'cost', 'bought', 'expense', 'purchase', 'fee', 'charge']
        if any(kw in text_lower for kw in expense_keywords):
            if 'food' in text_lower or 'meal' in text_lower or 'eat' in text_lower:
                return 'expense', 'food'
            elif 'transport' in text_lower or 'fuel' in text_lower or 'bus' in text_lower:
                return 'expense', 'transportation'
            elif 'office' in text_lower or 'business' in text_lower or 'supply' in text_lower:
                return 'expense', 'office_supplies'
            else:
                return 'expense', 'miscellaneous'

        # Debt/Debtor keywords
        if 'owe' in text_lower or 'loan' in text_lower or 'borrowed' in text_lower:
            return 'debt', 'debt'

        # Default to expense
        return 'expense', 'miscellaneous'

    # ==================== TRANSACTION MANAGER (Atomic creation) ====================

    @staticmethod
    def create_voice_report_with_activity(mongo, user_id, voice_doc):
        """
        Atomically create a VoiceReport and corresponding Activity (Income/Expense).
        
        Returns:
            (success: bool, message: str, voice_id: str|None, activity_id: str|None, error_detail: str|None)
        """
        voice_report_id = None

        try:
            client = mongo.cx
            session = None
            
            # Try to use a transactional session
            try:
                session = client.start_session()
            except Exception as e:
                current_app.logger.warning(f"Session creation failed, proceeding without transaction: {str(e)}")
                session = None

            # Determine what activity to create based on category
            category = voice_doc.get('category', 'expense')
            amount = voice_doc.get('extractedAmount', 0.0)

            if amount <= 0:
                return False, 'Extracted amount must be > 0', None, None, 'Invalid amount extraction'

            # Build activity document based on category
            now = datetime.utcnow()
            activity_doc = None
            activity_collection = None

            if category == 'income':
                activity_collection = 'incomes'  # CORRECT: Plural form
                activity_doc = {
                    '_id': ObjectId(),  # NEW: Explicit ID for reference
                    'userId': user_id,
                    'amount': amount,
                    'source': voice_doc.get('transactionType', 'voice_entry'),
                    'description': voice_doc.get('description', voice_doc.get('transcription', '')),
                    'category': voice_doc.get('transactionType', 'other_income'),
                    'frequency': 'one_time',
                    'salesType': None,
                    'dateReceived': now,
                    'isRecurring': False,
                    'nextRecurringDate': None,
                    # CRITICAL: Missing fields from comparison
                    'entryType': 'personal',
                    'exportHistory': [],
                    'fcChargeAmount': 0.0,
                    'fcChargeAttemptedAt': None,
                    'fcChargeCompleted': False,
                    'fcChargeRequired': False,
                    'isDeleted': False,
                    'status': 'active',
                    'taggedAt': now,
                    'taggedBy': 'voice_system',
                    'metadata': {
                        'source': 'voice_report',
                        'voiceReportId': None,  # Will set after voice doc creation
                        'transcription': voice_doc.get('transcription', ''),
                    },
                    'createdAt': now,
                    'updatedAt': now,
                }

            elif category == 'expense':
                activity_collection = 'expenses'
                activity_doc = {
                    '_id': ObjectId(),  # NEW: Explicit ID for reference
                    'userId': user_id,
                    'amount': amount,
                    'title': voice_doc.get('transactionType', 'voice_entry').replace('_', ' ').title(),
                    'description': voice_doc.get('description', voice_doc.get('transcription', '')),
                    'category': voice_doc.get('transactionType', 'miscellaneous'),
                    'date': now,
                    'tags': ['voice_entry'],
                    'paymentMethod': 'cash',  # Default for voice entries
                    'location': None,
                    'notes': f"From voice: {voice_doc.get('transcription', '')}",
                    # NEW: Version control fields (CRITICAL for deduplication)
                    'version': 1,
                    'supersededBy': None,
                    'superseded': False,
                    'originalEntryId': None,
                    # NEW: Immutable ledger fields
                    'status': 'active',
                    'isDeleted': False,
                    'deletedAt': None,
                    'deletedBy': None,
                    'reversalEntryId': None,
                    # NEW: Audit trail
                    'auditLog': [],
                    'exportHistory': [],
                    'metadata': None,
                    'createdAt': now,
                    'updatedAt': now,
                }

            else:
                return False, f'Unsupported category: {category}', None, None, 'Category not income or expense'

            # Execute atomic transaction if session available
            if session and activity_doc:
                try:
                    with session.start_transaction():
                        # 1. Insert VoiceReport
                        voice_res = mongo.db.voice_reports.insert_one(voice_doc, session=session)
                        voice_report_id = voice_res.inserted_id

                        # 2. Update activity doc with voice report reference
                        activity_doc['metadata']['voiceReportId'] = str(voice_report_id)

                        # 3. Insert Activity
                        activity_res = mongo.db[activity_collection].insert_one(activity_doc, session=session)
                        activity_id = activity_res.inserted_id

                        # 4. Update VoiceReport with activity reference
                        mongo.db.voice_reports.update_one(
                            {'_id': voice_report_id},
                            {
                                '$set': {
                                    'linkedTransactionId': activity_id,
                                    'linkedTransactionType': 'income' if category == 'income' else 'expense',
                                    'syncStatus': 'synced',
                                    'syncedAt': now,
                                    'updatedAt': now,
                                }
                            },
                            session=session
                        )

                        return True, 'Voice report and activity created successfully', str(voice_report_id), str(activity_id), None

                except Exception as tx_error:
                    # Transaction rolled back automatically by MongoDB
                    current_app.logger.exception(f'Atomic transaction failed: {str(tx_error)}')
                    return False, f'Transaction failed: {str(tx_error)}', None, None, str(tx_error)

            else:
                # Fallback: No session, manual cleanup on error
                try:
                    # 1. Insert VoiceReport
                    voice_res = mongo.db.voice_reports.insert_one(voice_doc)
                    voice_report_id = voice_res.inserted_id

                    # 2. Update activity doc with voice report reference
                    if activity_doc:
                        activity_doc['metadata']['voiceReportId'] = str(voice_report_id)

                        # 3. Insert Activity
                        try:
                            activity_res = mongo.db[activity_collection].insert_one(activity_doc)
                            activity_id = activity_res.inserted_id

                            # 4. Update VoiceReport with activity reference
                            mongo.db.voice_reports.update_one(
                                {'_id': voice_report_id},
                                {
                                    '$set': {
                                        'linkedTransactionId': activity_id,
                                        'linkedTransactionType': 'income' if category == 'income' else 'expense',
                                        'syncStatus': 'synced',
                                        'syncedAt': now,
                                        'updatedAt': now,
                                    }
                                }
                            )

                            return True, 'Voice report and activity created successfully', str(voice_report_id), str(activity_id), None

                        except Exception as activity_error:
                            # Activity creation failed, cleanup voice report
                            mongo.db.voice_reports.delete_one({'_id': voice_report_id})
                            current_app.logger.exception(f'Activity creation failed, rolled back VoiceReport: {str(activity_error)}')
                            return False, f'Activity creation failed: {str(activity_error)}', None, None, str(activity_error)

                except Exception as voice_error:
                    current_app.logger.exception(f'VoiceReport creation failed: {str(voice_error)}')
                    return False, f'VoiceReport creation failed: {str(voice_error)}', None, None, str(voice_error)

        except Exception as e:
            current_app.logger.exception(f'Unexpected error in atomic transaction: {str(e)}')
            return False, f'Unexpected error: {str(e)}', None, None, str(e)

    # ==================== ENDPOINT: Create Voice Report ====================

    @bp.route('/create', methods=['POST'])
    @token_required
    def create_voice_report(current_user):
        """
        Create a voice report with automatic extraction and atomic Activity creation.
        
        Expected body (JSON):
        {
            "idempotency_key": "uuid-v4",
            "transcription": "I earned five thousand naira today",
            "audioUrl": "gs://bucket/file.m4a",
            "audioFileName": "voice_123.m4a",
            "audioFileSize": 125000,
            "currencyCode": "NGN",
            "recordedAt": "2025-01-01T12:00:00Z"
        }
        """
        user_id = current_user['_id']

        # Accept both JSON and form-data
        if request.content_type and 'application/json' in request.content_type:
            body = request.get_json(force=True)
        else:
            body = {}
            body.update(request.form.to_dict())

        idempotency_key = body.get('idempotency_key') or body.get('idempotencyKey')
        if not idempotency_key:
            return jsonify({'success': False, 'message': 'Missing idempotency_key'}), 400

        transcription = body.get('transcription', '')
        if not transcription:
            return jsonify({'success': False, 'message': 'Missing transcription'}), 400

        # Build request hash for idempotency
        try:
            request_copy = body.copy()
            request_copy.pop('audio', None)
            request_copy.pop('file', None)
            request_str = json.dumps(request_copy, sort_keys=True, default=str)
            request_hash = hashlib.sha256(request_str.encode('utf-8')).hexdigest()
        except Exception:
            request_hash = hashlib.sha256(str(datetime.utcnow().timestamp()).encode('utf-8')).hexdigest()

        # Check idempotency cache FIRST
        cached = mongo.db.idempotency_keys.find_one({'idempotencyKey': idempotency_key, 'userId': user_id})
        if cached:
            if cached.get('requestHash') == request_hash:
                resp_status = cached.get('responseStatus', 200)
                resp_body = cached.get('responseBody', {})
                return jsonify(resp_body), resp_status
            else:
                return jsonify({'success': False, 'message': 'Idempotency key used with different payload'}), 409

        # ===== EXTRACTION PHASE (Backend heuristics) =====
        extracted_amount, confidence = extract_amount_from_text(transcription)
        category, transaction_type = classify_category_and_type(transcription)

        now = datetime.utcnow()
        voice_doc = {
            'userId': user_id,
            'idempotencyKey': idempotency_key,
            'transcription': transcription,
            'audioUrl': body.get('audioUrl') or None,
            'audioFileName': body.get('audioFileName') or None,
            'audioFileSize': int(body.get('audioFileSize')) if body.get('audioFileSize') else None,
            'extractedAmount': extracted_amount,
            'currencyCode': body.get('currencyCode', 'NGN'),
            'category': category,
            'transactionType': transaction_type,
            'description': transcription[:200],  # First 200 chars as description
            'confidence': confidence,
            'status': 'pending',
            'transcriptionStatus': 'completed',
            'syncStatus': 'pending',
            'processingError': None,
            'linkedTransactionId': None,
            'linkedTransactionType': None,
            'notificationSent': False,
            'userNotified': False,
            'recordedAt': datetime.fromisoformat(body.get('recordedAt', now.isoformat())),
            'uploadedAt': now,
            'transcribedAt': now,
            'processedAt': now,
            'syncedAt': None,
            'createdAt': now,
            'updatedAt': now,
        }

        # ===== ATOMIC TRANSACTION PHASE =====
        success, message, voice_id, activity_id, error_detail = create_voice_report_with_activity(mongo, user_id, voice_doc)

        if success:
            # Save idempotency cache ONLY after successful atomic transaction
            response_doc = {
                'success': True,
                'message': message,
                'voiceReportId': voice_id,
                'activityId': activity_id,
                'extractedAmount': extracted_amount,
                'category': category,
                'transactionType': transaction_type,
                'confidence': confidence,
            }

            try:
                mongo.db.idempotency_keys.insert_one({
                    'idempotencyKey': idempotency_key,
                    'userId': user_id,
                    'endpoint': '/api/voice/create',
                    'requestHash': request_hash,
                    'responseStatus': 201,
                    'responseBody': response_doc,
                    'responseHeaders': None,
                    'createdAt': now,
                    'expiresAt': now + timedelta(hours=24),
                })
            except Exception as cache_error:
                current_app.logger.warning(f'Idempotency cache save failed (non-fatal): {str(cache_error)}')

            return jsonify(response_doc), 201

        else:
            # Failed transaction - do NOT cache idempotency key
            # This allows client to retry on network error without getting stale response
            response_doc = {
                'success': False,
                'message': message,
                'errorDetail': error_detail,
            }
            return jsonify(response_doc), 500

    return bp
