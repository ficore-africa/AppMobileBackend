"""
Email Service for FiCore Africa
Uses Resend API for transactional and marketing emails
"""

import os
import resend
from datetime import datetime
from flask import current_app
from extensions import mongo
from bson import ObjectId


class EmailService:
    """
    Centralized email service using Resend
    """
    
    def __init__(self):
        """Initialize Resend with API key from environment"""
        self.api_key = os.getenv('RESEND_API_KEY')
        if not self.api_key:
            raise ValueError('RESEND_API_KEY environment variable not set')
        
        resend.api_key = self.api_key
        self.from_email = "FiCore <team@ficoreafrica.com>"
    
    def _log_email(self, to_email, subject, email_type, status, email_id=None, error=None, user_id=None):
        """
        Log email to database for tracking and debugging
        """
        try:
            log_entry = {
                'toEmail': to_email,
                'subject': subject,
                'emailType': email_type,
                'status': status,  # 'sent', 'failed', 'queued'
                'emailId': email_id,  # Resend email ID
                'error': error,
                'sentAt': datetime.utcnow(),
                'userId': ObjectId(user_id) if user_id else None
            }
            mongo.db.email_logs.insert_one(log_entry)
        except Exception as e:
            print(f'Error logging email: {e}')
    
    def _send_email(self, to_email, subject, html_content, email_type, user_id=None):
        """
        Internal method to send email via Resend
        """
        try:
            params = {
                "from": self.from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_content
            }
            
            # Send email
            response = resend.Emails.send(params)
            
            # Log success
            self._log_email(
                to_email=to_email,
                subject=subject,
                email_type=email_type,
                status='sent',
                email_id=response.get('id'),
                user_id=user_id
            )
            
            print(f'✅ Email sent: {email_type} to {to_email}')
            return {'success': True, 'email_id': response.get('id')}
            
        except Exception as e:
            # Log failure
            self._log_email(
                to_email=to_email,
                subject=subject,
                email_type=email_type,
                status='failed',
                error=str(e),
                user_id=user_id
            )
            
            print(f'❌ Email failed: {email_type} to {to_email} - {e}')
            return {'success': False, 'error': str(e)}
    
    # ==================== TRANSACTIONAL EMAILS ====================
    
    def send_welcome_email(self, to_email, user_name, user_id=None):
        """
        Send welcome email after user signup
        """
        subject = "Welcome to FiCore Africa! 🎉"
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
                <h1 style="color: #FFFFFF; margin: 0; font-size: 28px; font-weight: 700;">Welcome to FiCore! 🎉</h1>
                <p style="color: #FFF8F0; margin: 10px 0 0 0; font-size: 14px;">Your Digital CFO for Business Success</p>
            </div>
            
            <!-- Main Content -->
            <div style="background: #FFFFFF; padding: 40px 30px;">
                <p style="font-size: 16px; color: #2E2E2E; margin-top: 0;">Hi {user_name},</p>
                
                <p style="color: #2E2E2E;">Welcome to FiCore Africa - your Digital CFO for business success!</p>
                
                <p style="color: #2E2E2E;">You've just joined thousands of Nigerian SMEs who are transforming their bookkeeping from a chore into a competitive advantage.</p>
                
                <h3 style="color: #1E3A8A; font-size: 18px; margin-top: 30px; margin-bottom: 15px;">What's Next?</h3>
                <ul style="line-height: 2; color: #2E2E2E; padding-left: 20px;">
                    <li>📱 <strong>Record your first transaction</strong> (voice entry in 10 seconds)</li>
                    <li>💰 <strong>Add cash to your wallet</strong> (buy airtime, data, pay bills)</li>
                    <li>📊 <strong>View your dashboard</strong> (see your profit/loss instantly)</li>
                    <li>🎁 <strong>Your welcome bonus</strong> (10 FC Credits already added!)</li>
                </ul>
                
                <!-- CTA Button with FiCore Golden -->
                <div style="text-align: center; margin: 40px 0;">
                    <p style="color: #2E2E2E; margin-bottom: 15px;">Open the FiCore mobile app to get started!</p>
                </div>
                
                <!-- Support Info -->
                <div style="background: #FFF8F0; border-left: 4px solid #B88A44; padding: 15px 20px; margin: 30px 0; border-radius: 4px;">
                    <p style="color: #2E2E2E; margin: 0; font-size: 14px;">
                        <strong>Need help?</strong> Reply to this email or WhatsApp us at <a href="https://wa.me/2348012345678" style="color: #25D366; text-decoration: none; font-weight: 600;">+234 801 234 5678</a>
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
                <p style="margin: 0 0 15px 0;">RC 8799482 | Lagos, Nigeria</p>
                <p style="margin: 0;">
                    <a href="https://business.ficoreafrica.com/privacy" style="color: #1E3A8A; text-decoration: none; margin: 0 10px;">Privacy Policy</a> | 
                    <a href="https://business.ficoreafrica.com/terms" style="color: #1E3A8A; text-decoration: none; margin: 0 10px;">Terms of Service</a>
                </p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(to_email, subject, html_content, 'welcome', user_id)
    
    def send_password_reset_email(self, to_email, reset_token, user_name, user_id=None):
        """
        Send password reset email with reset code
        Note: Mobile app handles password reset in-app using the reset code
        """
        subject = "Reset Your FiCore Password"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #2E2E2E; max-width: 600px; margin: 0 auto; padding: 0; background-color: #FFF8F0;">
            <!-- Header -->
            <div style="background: #1E3A8A; padding: 40px 30px; text-align: center;">
                <h1 style="color: #FFFFFF; margin: 0; font-size: 24px; font-weight: 700;">Password Reset Request</h1>
            </div>
            
            <!-- Main Content -->
            <div style="background: #FFFFFF; padding: 40px 30px;">
                <p style="font-size: 16px; color: #2E2E2E; margin-top: 0;">Hi {user_name},</p>
                
                <p style="color: #2E2E2E;">We received a request to reset your FiCore password.</p>
                
                <p style="color: #2E2E2E;">Use the reset code below in the FiCore mobile app:</p>
                
                <!-- Reset Code Display -->
                <div style="background: #F4F1EC; border: 2px dashed #1E3A8A; border-radius: 8px; padding: 30px; margin: 30px 0; text-align: center;">
                    <p style="margin: 0; color: #6B7280; font-size: 14px;">Your Reset Code:</p>
                    <h2 style="margin: 10px 0; color: #1E3A8A; font-size: 36px; font-weight: 700; letter-spacing: 4px; font-family: 'Courier New', monospace;">{reset_token[:8]}</h2>
                    <p style="margin: 10px 0 0 0; color: #6B7280; font-size: 12px;">Enter this code in the FiCore app</p>
                </div>
                
                <!-- Security Warning -->
                <div style="background: #FFF8F0; border-left: 4px solid #F97316; padding: 15px 20px; margin: 30px 0; border-radius: 4px;">
                    <p style="color: #2E2E2E; margin: 0; font-size: 14px;">
                        ⚠️ <strong>Security Notice:</strong> This code expires in 1 hour. If you didn't request this reset, please ignore this email and your password will remain unchanged.
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
                <p style="margin: 0 0 15px 0;">RC 8799482 | Lagos, Nigeria</p>
                <p style="margin: 0;">
                    <a href="https://business.ficoreafrica.com/privacy" style="color: #1E3A8A; text-decoration: none; margin: 0 10px;">Privacy Policy</a> | 
                    <a href="https://business.ficoreafrica.com/terms" style="color: #1E3A8A; text-decoration: none; margin: 0 10px;">Terms</a>
                </p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(to_email, subject, html_content, 'password_reset', user_id)
    
    # ==================== SUBSCRIPTION EMAILS ====================
    
    def send_subscription_expiring_email(self, to_email, user_name, days_remaining, expiry_date, user_id=None):
        """
        Send reminder email before subscription expires
        """
        subject = f"Your FiCore Subscription Expires in {days_remaining} Days"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #2E2E2E; max-width: 600px; margin: 0 auto; padding: 0; background-color: #FFF8F0;">
            <!-- Header with Warning Orange -->
            <div style="background: #F97316; padding: 40px 30px; text-align: center;">
                <h1 style="color: #FFFFFF; margin: 0; font-size: 24px; font-weight: 700;">⏰ Subscription Expiring Soon</h1>
            </div>
            
            <!-- Main Content -->
            <div style="background: #FFFFFF; padding: 40px 30px;">
                <p style="font-size: 16px; color: #2E2E2E; margin-top: 0;">Hi {user_name},</p>
                
                <p style="color: #2E2E2E;">Your FiCore Premium subscription will expire in <strong style="color: #F97316;">{days_remaining} days</strong> on {expiry_date.strftime('%B %d, %Y')}.</p>
                
                <h3 style="color: #1E3A8A; font-size: 18px; margin-top: 30px; margin-bottom: 15px;">Don't lose access to:</h3>
                <ul style="line-height: 2; color: #2E2E2E; padding-left: 20px;">
                    <li>✅ Unlimited transactions</li>
                    <li>✅ Advanced reports</li>
                    <li>✅ Priority support</li>
                    <li>✅ E-invoicing features</li>
                </ul>
                
                <!-- CTA Button -->
                <div style="text-align: center; margin: 40px 0;">
                    <a href="https://business.ficoreafrica.com/subscription" style="background: #B88A44; color: #FFFFFF; padding: 16px 40px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: 600; font-size: 16px; box-shadow: 0 4px 6px rgba(184, 138, 68, 0.3);">Renew Now</a>
                </div>
                
                <!-- Support Info -->
                <div style="background: #FFF8F0; border-left: 4px solid #B88A44; padding: 15px 20px; margin: 30px 0; border-radius: 4px;">
                    <p style="color: #2E2E2E; margin: 0; font-size: 14px;">
                        Questions? Reply to this email or contact support.
                    </p>
                </div>
                
                <p style="color: #6B7280; font-size: 14px; margin-top: 30px;">
                    Best regards,<br>
                    <strong style="color: #1E3A8A;">The FiCore Team</strong>
                </p>
            </div>
            
            <!-- Footer -->
            <div style="background: #F4F1EC; text-align: center; padding: 30px 20px; color: #6B7280; font-size: 12px;">
                <p style="margin: 0;"><strong style="color: #1E3A8A;">FiCore Labs Limited</strong> | RC 8799482 | Lagos, Nigeria</p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(to_email, subject, html_content, 'subscription_expiring', user_id)
    
    def send_subscription_expired_email(self, to_email, user_name, user_id=None):
        """
        Send notification email after subscription expires
        """
        subject = "Your FiCore Subscription Has Expired"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: #e74c3c; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0;">Subscription Expired</h1>
            </div>
            
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px;">Hi {user_name},</p>
                
                <p>Your FiCore Premium subscription has expired. You've been moved to the Free tier.</p>
                
                <p><strong>What you still have:</strong></p>
                <ul style="line-height: 2;">
                    <li>✅ Your FC Credits (preserved)</li>
                    <li>✅ Your transaction history</li>
                    <li>✅ Basic features</li>
                </ul>
                
                <p><strong>What you're missing:</strong></p>
                <ul style="line-height: 2;">
                    <li>❌ Unlimited transactions</li>
                    <li>❌ Advanced reports</li>
                    <li>❌ Priority support</li>
                    <li>❌ E-invoicing features</li>
                </ul>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://business.ficoreafrica.com/subscription" style="background: #667eea; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">Reactivate Premium</a>
                </div>
                
                <p style="color: #666; font-size: 14px; margin-top: 30px;">
                    Best regards,<br>
                    <strong>The FiCore Team</strong>
                </p>
            </div>
            
            <div style="text-align: center; padding: 20px; color: #999; font-size: 12px;">
                <p>FiCore Labs Limited | RC 8799482 | Lagos, Nigeria</p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(to_email, subject, html_content, 'subscription_expired', user_id)
    
    # ==================== CREDIT EMAILS ====================
    
    def send_credit_approved_email(self, to_email, user_name, amount, new_balance, user_id=None):
        """
        Send notification when credit request is approved
        """
        subject = f"✅ Your ₦{amount:,.0f} Credit Request Approved!"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #2E2E2E; max-width: 600px; margin: 0 auto; padding: 0; background-color: #FFF8F0;">
            <!-- Header with Success Green -->
            <div style="background: #16A34A; padding: 40px 30px; text-align: center;">
                <h1 style="color: #FFFFFF; margin: 0; font-size: 24px; font-weight: 700;">✅ Credit Approved!</h1>
            </div>
            
            <!-- Main Content -->
            <div style="background: #FFFFFF; padding: 40px 30px;">
                <p style="font-size: 16px; color: #2E2E2E; margin-top: 0;">Hi {user_name},</p>
                
                <p style="color: #2E2E2E;">Great news! Your credit request has been approved.</p>
                
                <!-- Amount Card -->
                <div style="background: #FFF8F0; border: 2px solid #B88A44; border-radius: 8px; padding: 30px; margin: 30px 0; text-align: center;">
                    <p style="margin: 0; color: #6B7280; font-size: 14px;">Amount Approved:</p>
                    <h2 style="margin: 10px 0; color: #16A34A; font-size: 32px; font-weight: 700;">₦{amount:,.0f}</h2>
                    <p style="margin: 15px 0 0 0; color: #6B7280; font-size: 14px;">New FC Credits Balance:</p>
                    <h3 style="margin: 10px 0 0 0; color: #B88A44; font-size: 24px; font-weight: 600;">{new_balance:,.0f} FCs</h3>
                </div>
                
                <p style="color: #2E2E2E;">Your FC Credits have been added to your account and are ready to use!</p>
                
                <!-- CTA Button -->
                <div style="text-align: center; margin: 40px 0;">
                    <a href="https://business.ficoreafrica.com" style="background: #1E3A8A; color: #FFFFFF; padding: 16px 40px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: 600; font-size: 16px; box-shadow: 0 4px 6px rgba(30, 58, 138, 0.3);">Open FiCore App</a>
                </div>
                
                <p style="color: #6B7280; font-size: 14px; margin-top: 30px;">
                    Best regards,<br>
                    <strong style="color: #1E3A8A;">The FiCore Team</strong>
                </p>
            </div>
            
            <!-- Footer -->
            <div style="background: #F4F1EC; text-align: center; padding: 30px 20px; color: #6B7280; font-size: 12px;">
                <p style="margin: 0;"><strong style="color: #1E3A8A;">FiCore Labs Limited</strong> | RC 8799482 | Lagos, Nigeria</p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(to_email, subject, html_content, 'credit_approved', user_id)
    
    # ==================== AUTOMATION EMAILS ====================
    
    def send_inactive_user_email(self, to_email, user_name, days_inactive, user_id=None):
        """
        Send re-engagement email to inactive users
        """
        subject = f"We Miss You at FiCore! 👋"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: #667eea; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0;">We Miss You! 👋</h1>
            </div>
            
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px;">Hi {user_name},</p>
                
                <p>It's been {days_inactive} days since we last saw you in FiCore. We hope everything is going well!</p>
                
                <p>Your business data is waiting for you:</p>
                <ul style="line-height: 2;">
                    <li>📊 View your financial dashboard</li>
                    <li>💰 Check your wallet balance</li>
                    <li>📱 Buy airtime/data instantly</li>
                    <li>📈 Generate tax reports</li>
                </ul>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://business.ficoreafrica.com" style="background: #667eea; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">Welcome Back</a>
                </div>
                
                <p style="color: #666; font-size: 14px;">
                    Need help getting started again? Reply to this email and we'll assist you.
                </p>
                
                <p style="color: #666; font-size: 14px; margin-top: 30px;">
                    Best regards,<br>
                    <strong>The FiCore Team</strong>
                </p>
            </div>
            
            <div style="text-align: center; padding: 20px; color: #999; font-size: 12px;">
                <p>FiCore Labs Limited | RC 8799482 | Lagos, Nigeria</p>
                <p>
                    <a href="https://business.ficoreafrica.com/unsubscribe?email={to_email}" style="color: #999; text-decoration: none;">Unsubscribe</a>
                </p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(to_email, subject, html_content, 'inactive_user', user_id)
    
    # ==================== TEST EMAIL ====================
    
    def send_test_email(self, to_email):
        """
        Send test email to verify Resend integration
        """
        subject = "🧪 FiCore Email Service Test"
        
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #2E2E2E; max-width: 600px; margin: 0 auto; padding: 0; background-color: #FFF8F0;">
            <!-- Header with FiCore Brand Colors -->
            <div style="background: linear-gradient(135deg, #1E3A8A 0%, #B88A44 100%); padding: 40px 30px; text-align: center;">
                <h1 style="color: #FFFFFF; margin: 0; font-size: 28px; font-weight: 700;">✅ Email Service Working!</h1>
            </div>
            
            <!-- Main Content -->
            <div style="background: #FFFFFF; padding: 40px 30px;">
                <p style="font-size: 16px; color: #2E2E2E; margin-top: 0;">Congratulations!</p>
                
                <p style="color: #2E2E2E;">Your FiCore email service is configured correctly and working perfectly.</p>
                
                <h3 style="color: #1E3A8A; font-size: 18px; margin-top: 30px; margin-bottom: 15px;">What's working:</h3>
                <ul style="line-height: 2; color: #2E2E2E; padding-left: 20px;">
                    <li>✅ Resend API integration</li>
                    <li>✅ Domain verification (ficoreafrica.com)</li>
                    <li>✅ Email delivery</li>
                    <li>✅ HTML rendering</li>
                    <li>✅ FiCore brand colors</li>
                </ul>
                
                <!-- Success Box -->
                <div style="background: #FFF8F0; border-left: 4px solid #16A34A; padding: 20px; margin: 30px 0; border-radius: 4px;">
                    <p style="color: #2E2E2E; margin: 0; font-size: 15px;">
                        ✅ <strong style="color: #16A34A;">Success!</strong> You can now send transactional and marketing emails to your users.
                    </p>
                </div>
                
                <!-- Brand Colors Reference -->
                <div style="margin: 30px 0;">
                    <h4 style="color: #1E3A8A; font-size: 16px; margin-bottom: 15px;">FiCore Brand Colors:</h4>
                    <div style="display: flex; flex-wrap: wrap; gap: 10px;">
                        <div style="background: #1E3A8A; color: #FFFFFF; padding: 10px 15px; border-radius: 4px; font-size: 12px; display: inline-block; margin: 5px;">Primary Blue #1E3A8A</div>
                        <div style="background: #B88A44; color: #FFFFFF; padding: 10px 15px; border-radius: 4px; font-size: 12px; display: inline-block; margin: 5px;">Golden #B88A44</div>
                        <div style="background: #F97316; color: #FFFFFF; padding: 10px 15px; border-radius: 4px; font-size: 12px; display: inline-block; margin: 5px;">Orange #F97316</div>
                        <div style="background: #16A34A; color: #FFFFFF; padding: 10px 15px; border-radius: 4px; font-size: 12px; display: inline-block; margin: 5px;">Success #16A34A</div>
                    </div>
                </div>
                
                <p style="color: #6B7280; font-size: 14px; margin-top: 30px;">
                    This is a test email from FiCore Africa.<br>
                    <strong style="color: #1E3A8A;">Sent via Resend</strong>
                </p>
            </div>
            
            <!-- Footer -->
            <div style="background: #F4F1EC; text-align: center; padding: 30px 20px; color: #6B7280; font-size: 12px;">
                <p style="margin: 0;"><strong style="color: #1E3A8A;">FiCore Labs Limited</strong> | RC 8799482 | Lagos, Nigeria</p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(to_email, subject, html_content, 'test')


# Convenience function for quick access
def get_email_service():
    """Get EmailService instance"""
    return EmailService()
