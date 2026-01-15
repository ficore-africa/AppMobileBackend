"""
Email Service for FiCore Africa
Professional Gmail SMTP service for OTP delivery and notifications
Zero-cost communication strategy implementation
"""
import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class EmailService:
    """Professional email service for OTP and notifications"""
    
    def __init__(self):
        self.sender_email = os.getenv('GMAIL_SENDER', 'ficore.africa@gmail.com')
        self.sender_password = os.getenv('GMAIL_APP_PASSWORD')
        self.sender_name = "FiCore Africa"
        
        if not self.sender_password:
            logger.warning("Gmail App Password not configured. Email service will be disabled.")
            self.enabled = False
        else:
            self.enabled = True
            logger.info("Email service initialized successfully")
    
    def send_otp(self, to_email: str, otp_code: str, user_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Send OTP verification code via email
        
        Args:
            to_email: Recipient email address
            otp_code: 6-digit verification code
            user_name: Optional user name for personalization
            
        Returns:
            Dict with success status and details
        """
        if not self.enabled:
            return {
                'success': False,
                'error': 'Email service not configured',
                'method': 'disabled'
            }
        
        try:
            subject = f"{otp_code} is your FiCore verification code"
            
            # Professional HTML template
            html_body = self._create_otp_template(otp_code, user_name)
            
            result = self._send_email(to_email, subject, html_body)
            
            if result['success']:
                logger.info(f"OTP email sent successfully to {to_email}")
                return {
                    'success': True,
                    'method': 'gmail_smtp',
                    'to': to_email,
                    'sent_at': datetime.utcnow().isoformat(),
                    'message': 'OTP sent successfully'
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"OTP email send failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'method': 'failed'
            }
    
    def send_password_reset(self, to_email: str, reset_token: str, user_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Send password reset link via email
        
        Args:
            to_email: Recipient email address
            reset_token: Password reset token
            user_name: Optional user name for personalization
            
        Returns:
            Dict with success status and details
        """
        if not self.enabled:
            return {
                'success': False,
                'error': 'Email service not configured',
                'method': 'disabled'
            }
        
        try:
            subject = "Reset your FiCore password"
            
            # Professional HTML template for password reset
            html_body = self._create_password_reset_template(reset_token, user_name)
            
            result = self._send_email(to_email, subject, html_body)
            
            if result['success']:
                logger.info(f"Password reset email sent successfully to {to_email}")
                return {
                    'success': True,
                    'method': 'gmail_smtp',
                    'to': to_email,
                    'sent_at': datetime.utcnow().isoformat(),
                    'message': 'Password reset email sent successfully'
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"Password reset email send failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'method': 'failed'
            }
    
    def send_transaction_receipt(self, to_email: str, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send transaction receipt via email
        
        Args:
            to_email: Recipient email address
            transaction_data: Transaction details
            
        Returns:
            Dict with success status and details
        """
        if not self.enabled:
            return {
                'success': False,
                'error': 'Email service not configured',
                'method': 'disabled'
            }
        
        try:
            subject = f"FiCore Transaction Receipt - ₦{transaction_data.get('amount', '0')}"
            
            # Professional HTML template for transaction receipt
            html_body = self._create_transaction_receipt_template(transaction_data)
            
            result = self._send_email(to_email, subject, html_body)
            
            if result['success']:
                logger.info(f"Transaction receipt sent successfully to {to_email}")
                return {
                    'success': True,
                    'method': 'gmail_smtp',
                    'to': to_email,
                    'sent_at': datetime.utcnow().isoformat(),
                    'message': 'Transaction receipt sent successfully'
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"Transaction receipt email send failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'method': 'failed'
            }
    
    def _send_email(self, to_email: str, subject: str, html_body: str) -> Dict[str, Any]:
        """
        Internal method to send email via Gmail SMTP
        
        Args:
            to_email: Recipient email
            subject: Email subject
            html_body: HTML email content
            
        Returns:
            Dict with success status
        """
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['From'] = f"{self.sender_name} <{self.sender_email}>"
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Attach HTML content
            html_part = MIMEText(html_body, 'html', 'utf-8')
            msg.attach(html_part)
            
            # Send via Gmail SMTP
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            
            return {
                'success': True,
                'message': 'Email sent successfully'
            }
            
        except smtplib.SMTPAuthenticationError:
            logger.error("Gmail authentication failed - check app password")
            return {
                'success': False,
                'error': 'Email authentication failed',
                'method': 'smtp_auth_error'
            }
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {str(e)}")
            return {
                'success': False,
                'error': f'SMTP error: {str(e)}',
                'method': 'smtp_error'
            }
        except Exception as e:
            logger.error(f"Email send error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'method': 'general_error'
            }
    
    def _create_otp_template(self, otp_code: str, user_name: Optional[str] = None) -> str:
        """Create professional OTP email template with FiCore brand colors"""
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>FiCore Verification Code</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #2E2E2E; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #FFF8F0;">
            <div style="background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px; font-weight: bold;">FiCore Africa</h1>
                <p style="color: #E8F0FE; margin: 5px 0 0 0; font-size: 16px;">Empowering Financial Freedom</p>
            </div>
            
            <div style="background: white; padding: 40px; border: 1px solid #E5E7EB; border-top: none; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; margin-bottom: 20px; color: #2E2E2E;">{greeting}</p>
                
                <p style="font-size: 16px; margin-bottom: 30px; color: #2E2E2E;">
                    Your verification code is:
                </p>
                
                <div style="background: #F4F1EC; border: 2px solid #1E3A8A; border-radius: 8px; padding: 20px; text-align: center; margin: 30px 0;">
                    <h2 style="font-size: 32px; letter-spacing: 8px; color: #1E3A8A; margin: 0; font-weight: bold;">{otp_code}</h2>
                </div>
                
                <p style="font-size: 14px; color: #6B7280; margin-bottom: 20px;">
                    This code expires in <strong>10 minutes</strong>. If you didn't request this verification, please ignore this email.
                </p>
                
                <div style="background: #F4F1EC; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="font-size: 14px; color: #B88A44; margin: 0; text-align: center;">
                        <strong>💡 Pro Tip:</strong> Save time by enabling biometric login in your FiCore app settings!
                    </p>
                </div>
                
                <div style="border-top: 1px solid #E5E7EB; padding-top: 20px; margin-top: 30px;">
                    <p style="font-size: 12px; color: #6B7280; text-align: center; margin: 0;">
                        <strong>FiCore Africa</strong> - Your trusted financial partner<br>
                        This is an automated message, please do not reply.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _create_password_reset_template(self, reset_token: str, user_name: Optional[str] = None) -> str:
        """Create professional password reset email template with FiCore brand colors"""
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        reset_url = f"https://app.ficore.africa/reset-password?token={reset_token}"
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Reset Your FiCore Password</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #2E2E2E; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #FFF8F0;">
            <div style="background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px; font-weight: bold;">FiCore Africa</h1>
                <p style="color: #E8F0FE; margin: 5px 0 0 0; font-size: 16px;">Password Reset Request</p>
            </div>
            
            <div style="background: white; padding: 40px; border: 1px solid #E5E7EB; border-top: none; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; margin-bottom: 20px; color: #2E2E2E;">{greeting}</p>
                
                <p style="font-size: 16px; margin-bottom: 30px; color: #2E2E2E;">
                    We received a request to reset your FiCore password. Click the button below to create a new password:
                </p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%); color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-size: 16px; font-weight: bold; display: inline-block; box-shadow: 0 4px 6px rgba(30, 58, 138, 0.2);">
                        Reset Password
                    </a>
                </div>
                
                <div style="background: #F4F1EC; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #B88A44;">
                    <p style="font-size: 14px; color: #B88A44; margin: 0;">
                        <strong>🔒 Security Tip:</strong> This link expires in 1 hour for your protection.
                    </p>
                </div>
                
                <p style="font-size: 14px; color: #6B7280; margin-bottom: 20px;">
                    If you didn't request this reset, please ignore this email and your password will remain unchanged.
                </p>
                
                <p style="font-size: 12px; color: #6B7280; margin-bottom: 20px; background: #F4F1EC; padding: 10px; border-radius: 4px;">
                    If the button doesn't work, copy and paste this link into your browser:<br>
                    <span style="word-break: break-all; font-family: monospace;">{reset_url}</span>
                </p>
                
                <div style="border-top: 1px solid #E5E7EB; padding-top: 20px; margin-top: 30px;">
                    <p style="font-size: 12px; color: #6B7280; text-align: center; margin: 0;">
                        <strong>FiCore Africa</strong> - Your trusted financial partner<br>
                        This is an automated message, please do not reply.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _create_transaction_receipt_template(self, transaction_data: Dict[str, Any]) -> str:
        """Create professional transaction receipt email template with FiCore brand colors"""
        
        # Extract transaction details
        transaction_type = transaction_data.get('type', 'Transaction')
        amount = transaction_data.get('amount', '0')
        fee = transaction_data.get('fee', '0')
        total_paid = transaction_data.get('total_paid', amount)
        new_balance = transaction_data.get('new_balance', 'N/A')
        is_premium = transaction_data.get('is_premium', False)
        
        # Create fee display
        fee_display = ""
        if fee and fee != "0" and fee != "₦0 (Premium)":
            fee_display = f"""
                        <tr>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; font-weight: bold; color: #1E3A8A;">Transaction Fee:</td>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; text-align: right; color: #F97316;">₦{fee}</td>
                        </tr>"""
        
        # Create balance display for wallet transactions
        balance_display = ""
        if new_balance and new_balance != 'N/A':
            balance_display = f"""
                        <tr>
                            <td style="padding: 12px 0; font-weight: bold; color: #1E3A8A;">New Wallet Balance:</td>
                            <td style="padding: 12px 0; text-align: right; font-size: 18px; font-weight: bold; color: #16A34A;">₦{new_balance}</td>
                        </tr>"""
        
        # Premium user badge
        premium_badge = ""
        if is_premium:
            premium_badge = """
                <div style="background: linear-gradient(135deg, #B88A44 0%, #D4AF37 100%); color: white; padding: 8px 16px; border-radius: 20px; display: inline-block; font-size: 12px; font-weight: bold; margin-bottom: 20px;">
                    ⭐ PREMIUM USER - NO FEES
                </div>"""
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>FiCore Transaction Receipt</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #2E2E2E; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #FFF8F0;">
            <div style="background: linear-gradient(135deg, #16A34A 0%, #4ADE80 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px; font-weight: bold;">FiCore Africa</h1>
                <p style="color: #E8F0FE; margin: 5px 0 0 0; font-size: 16px;">Transaction Receipt</p>
            </div>
            
            <div style="background: white; padding: 40px; border: 1px solid #E5E7EB; border-top: none; border-radius: 0 0 10px 10px;">
                <div style="text-align: center; margin-bottom: 30px;">
                    {premium_badge}
                    <div style="background: #16A34A; color: white; padding: 10px 20px; border-radius: 20px; display: inline-block; font-size: 14px; font-weight: bold;">
                        ✅ Transaction Successful
                    </div>
                </div>
                
                <div style="background: #F4F1EC; padding: 25px; border-radius: 8px; margin-bottom: 30px; border-left: 4px solid #B88A44;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; font-weight: bold; color: #1E3A8A;">Transaction Type:</td>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; text-align: right; color: #2E2E2E;">{transaction_type}</td>
                        </tr>
                        <tr>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; font-weight: bold; color: #1E3A8A;">Amount Credited:</td>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; text-align: right; font-size: 18px; font-weight: bold; color: #16A34A;">₦{amount}</td>
                        </tr>{fee_display}
                        <tr>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; font-weight: bold; color: #1E3A8A;">Total Paid:</td>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; text-align: right; font-weight: bold; color: #2E2E2E;">₦{total_paid}</td>
                        </tr>
                        <tr>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; font-weight: bold; color: #1E3A8A;">Date & Time:</td>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; text-align: right; color: #2E2E2E;">{transaction_data.get('date', datetime.now().strftime('%Y-%m-%d %H:%M'))}</td>
                        </tr>
                        <tr>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; font-weight: bold; color: #1E3A8A;">Reference:</td>
                            <td style="padding: 12px 0; border-bottom: 1px solid #E5E7EB; text-align: right; font-family: monospace; color: #6B7280; font-size: 12px;">{transaction_data.get('reference', 'N/A')}</td>
                        </tr>{balance_display}
                    </table>
                </div>
                
                <div style="background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%); padding: 20px; border-radius: 8px; text-align: center; margin: 20px 0;">
                    <p style="color: white; margin: 0; font-size: 16px;">
                        <strong>💰 Your financial journey continues with FiCore!</strong>
                    </p>
                    <p style="color: #E8F0FE; margin: 10px 0 0 0; font-size: 14px;">
                        Track expenses • Build wealth • Achieve your goals
                    </p>
                </div>
                
                <p style="font-size: 14px; color: #6B7280; text-align: center; margin: 20px 0;">
                    Thank you for choosing FiCore Africa as your financial partner.
                </p>
                
                <div style="border-top: 1px solid #E5E7EB; padding-top: 20px; margin-top: 30px;">
                    <p style="font-size: 12px; color: #6B7280; text-align: center; margin: 0;">
                        <strong>FiCore Africa</strong> - Your trusted financial partner<br>
                        This is an automated message, please do not reply.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get email service status"""
        return {
            'enabled': self.enabled,
            'sender_email': self.sender_email if self.enabled else None,
            'mode': 'production' if self.enabled else 'disabled'
        }


# Singleton instance
_email_service = None

def get_email_service() -> EmailService:
    """Get or create email service singleton"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service