"""
Announcement Service for FiCore Africa
Handles bulk announcements to users via Resend Broadcasts
"""

import os
import resend
import time
from datetime import datetime
from bson import ObjectId


class AnnouncementService:
    """
    Service for sending announcements to FiCore users
    Uses Resend Broadcasts API for bulk sending
    """
    
    def __init__(self, mongo_db=None):
        """Initialize Resend with API key from environment"""
        self.api_key = os.getenv('RESEND_API_KEY')
        if not self.api_key:
            raise ValueError('RESEND_API_KEY environment variable not set')
        
        resend.api_key = self.api_key
        self.from_email = "FiCore Africa <team@ficoreafrica.com>"
        self.mongo_db = mongo_db
        
        # Resend Audience ID - MUST be set in environment variables
        self.audience_id = os.getenv('RESEND_AUDIENCE_ID')
        if not self.audience_id or self.audience_id == 'default_audience_id':
            print('⚠️ WARNING: RESEND_AUDIENCE_ID not set or invalid!')
            print('   Please set RESEND_AUDIENCE_ID in Render environment variables')
            print('   Get your Audience ID from: https://resend.com/audiences')
    
    def _log_announcement(self, subject, announcement_type, status, recipient_count=0, error=None, admin_id=None):
        """
        Log announcement to database for tracking
        """
        if self.mongo_db is None:
            print(f'⚠️ MongoDB not available for announcement logging')
            return
            
        try:
            log_entry = {
                'subject': subject,
                'announcementType': announcement_type,
                'status': status,  # 'sent', 'failed', 'test'
                'recipientCount': recipient_count,
                'error': error,
                'sentAt': datetime.utcnow(),
                'sentBy': ObjectId(admin_id) if admin_id else None
            }
            self.mongo_db.announcement_logs.insert_one(log_entry)
        except Exception as e:
            print(f'Error logging announcement: {e}')
    
    def sync_user_to_audience(self, email, first_name, last_name, user_id=None):
        """
        Add a user to Resend Audience
        Called automatically after signup
        
        Args:
            email: User's email address
            first_name: User's first name
            last_name: User's last name
            user_id: MongoDB user ID (optional)
        
        Returns:
            dict: {'success': bool, 'contact_id': str or None, 'error': str or None}
        """
        try:
            # Check if audience_id is valid
            if not self.audience_id or self.audience_id == 'default_audience_id':
                error_msg = 'RESEND_AUDIENCE_ID not configured. Please set it in Render environment variables. Get your Audience ID from https://resend.com/audiences'
                print(f'🔑 CONFIG ERROR: {error_msg}')
                return {
                    'success': False,
                    'contact_id': None,
                    'error': error_msg
                }
            
            # Resend Contacts API - try both formats (camelCase and snake_case)
            # JavaScript SDK uses camelCase, Python SDK might use snake_case
            # Based on blog: audienceId (camelCase) is used in JavaScript
            # Let's try snake_case first (Python convention), then camelCase if it fails
            try:
                # Try snake_case (Python convention)
                contact = resend.Contacts.create({
                    'audience_id': self.audience_id,
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name
                })
            except Exception as snake_error:
                # If snake_case fails, try camelCase (JavaScript convention)
                print(f'⚠️ snake_case failed, trying camelCase: {snake_error}')
                contact = resend.Contacts.create({
                    'audienceId': self.audience_id,
                    'email': email,
                    'firstName': first_name,
                    'lastName': last_name
                })
            
            print(f'✅ User synced to Resend: {email}')
            
            # Log sync to MongoDB
            if self.mongo_db is not None and user_id:
                try:
                    self.mongo_db.users.update_one(
                        {'_id': ObjectId(user_id)},
                        {
                            '$set': {
                                'resendContactId': contact.get('id'),
                                'resendSyncedAt': datetime.utcnow()
                            }
                        }
                    )
                except Exception as e:
                    print(f'⚠️ Failed to update user with Resend contact ID: {e}')
            
            return {
                'success': True,
                'contact_id': contact.get('id'),
                'error': None
            }
            
        except Exception as e:
            error_msg = str(e)
            
            # Check for common errors
            if 'restricted to only send emails' in error_msg:
                error_msg = 'API key lacks permissions. Please create a new Resend API key with "Full Access" (not just "Sending Access") in your Resend dashboard.'
                print(f'🔑 PERMISSION ERROR: {error_msg}')
            elif 'must be a valid UUID' in error_msg:
                error_msg = 'Invalid RESEND_AUDIENCE_ID. Please set the correct Audience ID from https://resend.com/audiences in Render environment variables.'
                print(f'🔑 CONFIG ERROR: {error_msg}')
            elif 'Too many requests' in error_msg:
                error_msg = 'Rate limit exceeded (2 requests/second). Please wait and try again.'
                print(f'⏱️ RATE LIMIT: {error_msg}')
            
            print(f'❌ Failed to sync user to Resend: {error_msg}')
            return {
                'success': False,
                'contact_id': None,
                'error': error_msg
            }
    
    def create_announcement_template(self, title, body, cta_text=None, cta_link=None, image_url=None):
        """
        Create announcement email HTML from template
        
        Args:
            title: Announcement headline
            body: Main message content
            cta_text: Call-to-action button text (optional)
            cta_link: Call-to-action button link (optional)
            image_url: Hero image URL (optional)
        
        Returns:
            str: HTML email content
        """
        
        # Build CTA button HTML if provided
        cta_html = ""
        if cta_text and cta_link:
            cta_html = f"""
            <div style="text-align: center; margin: 40px 0;">
                <a href="{cta_link}" style="display: inline-block; background: #B88A44; color: #FFFFFF; padding: 16px 40px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px; box-shadow: 0 4px 6px rgba(184, 138, 68, 0.3);">
                    {cta_text}
                </a>
            </div>
            """
        
        # Build hero image HTML if provided
        hero_image_html = ""
        if image_url:
            hero_image_html = f"""
            <div style="margin: 30px 0; text-align: center;">
                <img src="{image_url}" alt="Announcement" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
            </div>
            """
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #2E2E2E; max-width: 600px; margin: 0 auto; padding: 0; background-color: #FFF8F0;">
            <!-- Header with FiCore Brand Colors -->
            <div style="background: linear-gradient(135deg, #1E3A8A 0%, #1E40AF 100%); padding: 40px 30px; text-align: center; border-radius: 0;">
                <h1 style="color: #FFFFFF; margin: 0; font-size: 28px; font-weight: 700;">📢 FiCore News</h1>
                <p style="color: #FFF8F0; margin: 10px 0 0 0; font-size: 14px;">Your Digital CFO for Business Success</p>
            </div>
            
            <!-- Main Content -->
            <div style="background: #FFFFFF; padding: 40px 30px;">
                <!-- Announcement Title -->
                <h2 style="color: #1E3A8A; font-size: 24px; margin-top: 0; margin-bottom: 20px; text-align: center;">{title}</h2>
                
                <!-- Hero Image (if provided) -->
                {hero_image_html}
                
                <!-- Announcement Body -->
                <div style="color: #2E2E2E; font-size: 16px; line-height: 1.8;">
                    {body}
                </div>
                
                <!-- CTA Button (if provided) -->
                {cta_html}
                
                <!-- Support Info -->
                <div style="background: #FFF8F0; border-left: 4px solid #B88A44; padding: 15px 20px; margin: 30px 0; border-radius: 4px;">
                    <p style="color: #2E2E2E; margin: 0; font-size: 14px;">
                        <strong>Need help?</strong> Reply to this email or WhatsApp us at <a href="https://wa.me/2348130549754" style="color: #25D366; text-decoration: none; font-weight: 600;">+234 813 054 9754</a>
                    </p>
                </div>
                
                <p style="color: #6B7280; font-size: 14px; margin-top: 30px;">
                    Best regards,<br>
                    <strong style="color: #1E3A8A;">The FiCore Team</strong>
                </p>
            </div>
            
            <!-- Footer -->
            <div style="background: #F4F1EC; text-align: center; padding: 30px 20px; color: #6B7280; font-size: 12px;">
                <p style="margin: 0 0 10px 0;"><strong style="color: #1E3A8A;">FiCore Labs Limited</strong></p>
                <p style="margin: 0 0 15px 0;">RC 8799482 | Nigeria</p>
                <p style="margin: 0 0 15px 0;">
                    <a href="https://business.ficoreafrica.com/general/privacy" style="color: #1E3A8A; text-decoration: none; margin: 0 8px;">Privacy Policy</a> | 
                    <a href="https://business.ficoreafrica.com/general/terms" style="color: #1E3A8A; text-decoration: none; margin: 0 8px;">Terms of Service</a> | 
                    <a href="https://business.ficoreafrica.com/general/landing" style="color: #1E3A8A; text-decoration: none; margin: 0 8px;">Website</a>
                </p>
                <!-- Unsubscribe Link (MANDATORY for announcements) -->
                <p style="margin: 15px 0 0 0;">
                    <a href="{{RESEND_UNSUBSCRIBE_URL}}" style="color: #6B7280; text-decoration: underline; font-size: 11px;">Unsubscribe from announcements</a>
                </p>
            </div>
        </body>
        </html>
        """
        
        return html_content
    
    def send_announcement(self, subject, title, body, cta_text=None, cta_link=None, image_url=None, 
                         test_mode=False, test_email=None, announcement_type='general', admin_id=None):
        """
        Send announcement to users
        
        Args:
            subject: Email subject line
            title: Announcement headline
            body: Main message content
            cta_text: Call-to-action button text (optional)
            cta_link: Call-to-action button link (optional)
            image_url: Hero image URL (optional)
            test_mode: If True, send only to test_email
            test_email: Email address for test mode
            announcement_type: Type of announcement (general, feature, update, promotional, educational)
            admin_id: ID of admin sending the announcement
        
        Returns:
            dict: {'success': bool, 'message': str, 'broadcast_id': str or None, 'error': str or None}
        """
        try:
            # Create HTML content from template
            html_content = self.create_announcement_template(
                title=title,
                body=body,
                cta_text=cta_text,
                cta_link=cta_link,
                image_url=image_url
            )
            
            if test_mode:
                # Test mode: Send to single email
                if not test_email:
                    return {
                        'success': False,
                        'message': 'Test email address required for test mode',
                        'broadcast_id': None,
                        'error': 'Missing test_email'
                    }
                
                # Send test email using regular email API
                params = {
                    "from": self.from_email,
                    "to": [test_email],
                    "subject": f"[TEST] {subject}",
                    "html": html_content
                }
                
                response = resend.Emails.send(params)
                
                # Log test announcement
                self._log_announcement(
                    subject=subject,
                    announcement_type=announcement_type,
                    status='test',
                    recipient_count=1,
                    admin_id=admin_id
                )
                
                return {
                    'success': True,
                    'message': f'Test announcement sent to {test_email}',
                    'broadcast_id': response.get('id'),
                    'error': None
                }
            
            else:
                # Live mode: Send to all users via Broadcasts
                # Resend Broadcasts automatically handle unsubscribe links
                
                if self.mongo_db is None:
                    return {
                        'success': False,
                        'message': 'Database connection required for live announcements',
                        'broadcast_id': None,
                        'error': 'No MongoDB connection'
                    }
                
                # Get all users with resendContactId (synced users)
                users = list(self.mongo_db.users.find(
                    {'resendContactId': {'$exists': True}},
                    {'email': 1, '_id': 0}
                ))
                
                if not users:
                    return {
                        'success': False,
                        'message': 'No users found in audience. Please sync users first.',
                        'broadcast_id': None,
                        'error': 'Empty audience'
                    }
                
                # Send to all users using Broadcasts API
                # Note: Resend Broadcasts API handles unsubscribe automatically
                recipient_emails = [user['email'] for user in users]
                
                try:
                    # Use Broadcasts API (handles unsubscribe automatically)
                    # Note: Free tier has 100 emails/day limit
                    # For 111 users, we'll use batch sending with proper headers
                    
                    print(f'📧 Sending to {len(recipient_emails)} users...')
                    
                    # Check if we're within free tier limits
                    if len(recipient_emails) > 100:
                        print(f'⚠️ Warning: {len(recipient_emails)} users exceeds free tier daily limit (100)')
                        print(f'   Using batch sending with List-Unsubscribe header')
                    
                    # Use batch sending with proper unsubscribe headers
                    # This is more reliable than Broadcasts API for free tier
                    batch_size = 50  # Smaller batches to avoid rate limits
                    total_sent = 0
                    
                    for i in range(0, len(recipient_emails), batch_size):
                        batch = recipient_emails[i:i + batch_size]
                        
                        params = {
                            "from": self.from_email,
                            "to": batch,
                            "subject": subject,
                            "html": html_content,
                            "headers": {
                                "List-Unsubscribe": f"<mailto:unsubscribe@ficoreafrica.com?subject=unsubscribe>",
                                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"
                            }
                        }
                        
                        response = resend.Emails.send(params)
                        total_sent += len(batch)
                        
                        print(f'✅ Sent announcement to {len(batch)} users (batch {i//batch_size + 1}/{(len(recipient_emails) + batch_size - 1)//batch_size})')
                    
                    # Log announcement
                    self._log_announcement(
                        subject=subject,
                        announcement_type=announcement_type,
                        status='sent',
                        recipient_count=total_sent,
                        admin_id=admin_id
                    )
                    
                    return {
                        'success': True,
                        'message': f'Announcement sent to {total_sent} users',
                        'broadcast_id': None,
                        'recipient_count': total_sent,
                        'error': None
                    }
                    
                except Exception as send_error:
                    print(f'❌ Failed to send announcement: {send_error}')
                    
                    # Log failure
                    self._log_announcement(
                        subject=subject,
                        announcement_type=announcement_type,
                        status='failed',
                        error=str(send_error),
                        admin_id=admin_id
                    )
                    
                    return {
                        'success': False,
                        'message': f'Failed to send announcement: {str(send_error)}',
                        'broadcast_id': None,
                        'error': str(send_error)
                    }
            
        except Exception as e:
            # Log failure
            self._log_announcement(
                subject=subject,
                announcement_type=announcement_type,
                status='failed',
                error=str(e),
                admin_id=admin_id
            )
            
            print(f'❌ Announcement failed: {e}')
            return {
                'success': False,
                'message': 'Failed to send announcement',
                'broadcast_id': None,
                'error': str(e)
            }
    
    def get_announcement_stats(self, days=30):
        """
        Get announcement statistics for the last N days
        
        Args:
            days: Number of days to look back
        
        Returns:
            dict: Statistics about announcements
        """
        if self.mongo_db is None:
            return {'error': 'Database connection required'}
        
        try:
            from datetime import timedelta
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Get announcement logs
            logs = list(self.mongo_db.announcement_logs.find(
                {'sentAt': {'$gte': cutoff_date}}
            ).sort('sentAt', -1))
            
            # Calculate stats
            total_sent = sum(log.get('recipientCount', 0) for log in logs if log.get('status') == 'sent')
            total_failed = len([log for log in logs if log.get('status') == 'failed'])
            total_tests = len([log for log in logs if log.get('status') == 'test'])
            
            return {
                'total_announcements': len(logs),
                'total_recipients': total_sent,
                'total_failed': total_failed,
                'total_tests': total_tests,
                'recent_announcements': logs[:10]  # Last 10 announcements
            }
            
        except Exception as e:
            return {'error': str(e)}


# Convenience function for quick access
def get_announcement_service(mongo_db=None):
    """
    Get AnnouncementService instance
    
    Args:
        mongo_db: Optional MongoDB database connection
    
    Returns:
        AnnouncementService instance
    """
    return AnnouncementService(mongo_db=mongo_db)
