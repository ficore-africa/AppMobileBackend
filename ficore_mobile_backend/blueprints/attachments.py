from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
import os
import uuid
from google.cloud import storage
from werkzeug.utils import secure_filename

def init_attachments_blueprint(mongo, token_required, serialize_doc):
    """Initialize the attachments blueprint with database and auth decorator"""
    attachments_bp = Blueprint('attachments', __name__, url_prefix='/attachments')
    
    # Initialize Google Cloud Storage client
    storage_client = storage.Client()
    bucket_name = os.environ.get('GCS_BUCKET_NAME', 'ficore-attachments')
    
    # Allowed file extensions and max size
    ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx', 'xls', 'xlsx'}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    
    def allowed_file(filename):
        """Check if file extension is allowed"""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    
    def get_file_extension(filename):
        """Get file extension"""
        return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    @attachments_bp.route('/upload', methods=['POST'])
    @token_required
    def upload_attachment(current_user):
        """Upload an attachment for income or expense"""
        try:
            # Check if file is in request
            if 'file' not in request.files:
                return jsonify({
                    'success': False,
                    'message': 'No file provided'
                }), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({
                    'success': False,
                    'message': 'No file selected'
                }), 400
            
            # Validate file
            if not allowed_file(file.filename):
                return jsonify({
                    'success': False,
                    'message': f'File type not allowed. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
                }), 400
            
            # Get additional fields
            entity_type = request.form.get('entity_type')  # 'income' or 'expense'
            entity_id = request.form.get('entity_id')
            description = request.form.get('description', '')
            
            # Validation
            if not entity_type or entity_type not in ['income', 'expense']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid entity_type. Must be "income" or "expense"'
                }), 400
            
            if not entity_id or not ObjectId.is_valid(entity_id):
                return jsonify({
                    'success': False,
                    'message': 'Valid entity_id is required'
                }), 400
            
            # Verify entity exists and belongs to user
            collection = mongo.db.incomes if entity_type == 'income' else mongo.db.expenses
            entity = collection.find_one({
                '_id': ObjectId(entity_id),
                'userId': current_user['_id']
            })
            
            if not entity:
                return jsonify({
                    'success': False,
                    'message': f'{entity_type.capitalize()} not found'
                }), 404
            
            # Generate unique filename
            original_filename = secure_filename(file.filename)
            file_extension = get_file_extension(original_filename)
            unique_filename = f"{current_user['_id']}/{entity_type}/{entity_id}/{uuid.uuid4()}.{file_extension}"
            
            # Upload to Google Cloud Storage
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(unique_filename)
            
            # Set content type
            content_type = file.content_type or 'application/octet-stream'
            blob.upload_from_file(file, content_type=content_type)
            
            # Make blob publicly readable (or use signed URLs for private access)
            # For now, we'll use signed URLs for security
            
            # Create attachment metadata in database
            attachment_data = {
                'userId': current_user['_id'],
                'entityType': entity_type,
                'entityId': ObjectId(entity_id),
                'originalFilename': original_filename,
                'storagePath': unique_filename,
                'fileSize': file.content_length or 0,
                'mimeType': content_type,
                'description': description,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }
            
            result = mongo.db.attachments.insert_one(attachment_data)
            attachment_id = str(result.inserted_id)
            
            # Generate signed URL for viewing (valid for 1 hour)
            signed_url = blob.generate_signed_url(
                version='v4',
                expiration=timedelta(hours=1),
                method='GET'
            )
            
            # Return attachment data
            attachment_response = serialize_doc(attachment_data.copy())
            attachment_response['id'] = attachment_id
            attachment_response['url'] = signed_url
            attachment_response['createdAt'] = attachment_response.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
            attachment_response['updatedAt'] = attachment_response.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
            
            return jsonify({
                'success': True,
                'data': attachment_response,
                'message': 'Attachment uploaded successfully'
            })
            
        except Exception as e:
            print(f"Error uploading attachment: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to upload attachment',
                'errors': {'general': [str(e)]}
            }), 500
    
    @attachments_bp.route('/<entity_type>/<entity_id>', methods=['GET'])
    @token_required
    def get_attachments(current_user, entity_type, entity_id):
        """Get all attachments for an income or expense"""
        try:
            # Validation
            if entity_type not in ['income', 'expense']:
                return jsonify({
                    'success': False,
                    'message': 'Invalid entity_type. Must be "income" or "expense"'
                }), 400
            
            if not ObjectId.is_valid(entity_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid entity_id'
                }), 400
            
            # Get attachments
            attachments = list(mongo.db.attachments.find({
                'userId': current_user['_id'],
                'entityType': entity_type,
                'entityId': ObjectId(entity_id)
            }).sort('createdAt', -1))
            
            # Generate signed URLs for each attachment
            bucket = storage_client.bucket(bucket_name)
            attachment_list = []
            
            for attachment in attachments:
                attachment_data = serialize_doc(attachment.copy())
                
                # Generate signed URL (valid for 1 hour)
                blob = bucket.blob(attachment['storagePath'])
                signed_url = blob.generate_signed_url(
                    version='v4',
                    expiration=timedelta(hours=1),
                    method='GET'
                )
                
                attachment_data['url'] = signed_url
                attachment_data['createdAt'] = attachment_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                attachment_data['updatedAt'] = attachment_data.get('updatedAt', datetime.utcnow()).isoformat() + 'Z'
                attachment_list.append(attachment_data)
            
            return jsonify({
                'success': True,
                'data': {
                    'attachments': attachment_list,
                    'count': len(attachment_list)
                },
                'message': 'Attachments retrieved successfully'
            })
            
        except Exception as e:
            print(f"Error retrieving attachments: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve attachments',
                'errors': {'general': [str(e)]}
            }), 500
    
    @attachments_bp.route('/<attachment_id>', methods=['DELETE'])
    @token_required
    def delete_attachment(current_user, attachment_id):
        """Delete an attachment"""
        try:
            # Validate attachment_id
            if not ObjectId.is_valid(attachment_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid attachment ID'
                }), 400
            
            # Find attachment
            attachment = mongo.db.attachments.find_one({
                '_id': ObjectId(attachment_id),
                'userId': current_user['_id']
            })
            
            if not attachment:
                return jsonify({
                    'success': False,
                    'message': 'Attachment not found'
                }), 404
            
            # Delete from Google Cloud Storage
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(attachment['storagePath'])
            
            try:
                blob.delete()
            except Exception as gcs_error:
                print(f"Warning: Failed to delete from GCS: {gcs_error}")
                # Continue with database deletion even if GCS deletion fails
            
            # Delete from database
            result = mongo.db.attachments.delete_one({
                '_id': ObjectId(attachment_id),
                'userId': current_user['_id']
            })
            
            if result.deleted_count == 0:
                return jsonify({
                    'success': False,
                    'message': 'Attachment not found'
                }), 404
            
            return jsonify({
                'success': True,
                'message': 'Attachment deleted successfully'
            })
            
        except Exception as e:
            print(f"Error deleting attachment: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to delete attachment',
                'errors': {'general': [str(e)]}
            }), 500
    
    @attachments_bp.route('/<attachment_id>/url', methods=['GET'])
    @token_required
    def get_attachment_url(current_user, attachment_id):
        """Get a fresh signed URL for viewing an attachment"""
        try:
            # Validate attachment_id
            if not ObjectId.is_valid(attachment_id):
                return jsonify({
                    'success': False,
                    'message': 'Invalid attachment ID'
                }), 400
            
            # Find attachment
            attachment = mongo.db.attachments.find_one({
                '_id': ObjectId(attachment_id),
                'userId': current_user['_id']
            })
            
            if not attachment:
                return jsonify({
                    'success': False,
                    'message': 'Attachment not found'
                }), 404
            
            # Generate signed URL (valid for 1 hour)
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(attachment['storagePath'])
            signed_url = blob.generate_signed_url(
                version='v4',
                expiration=timedelta(hours=1),
                method='GET'
            )
            
            return jsonify({
                'success': True,
                'data': {
                    'url': signed_url,
                    'expiresIn': 3600  # 1 hour in seconds
                },
                'message': 'Signed URL generated successfully'
            })
            
        except Exception as e:
            print(f"Error generating signed URL: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to generate signed URL',
                'errors': {'general': [str(e)]}
            }), 500
    
    return attachments_bp
