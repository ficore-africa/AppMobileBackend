"""
Email Alert Utility for Provider Health Monitoring
Sends critical alerts to admin when provider balances are low
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from datetime import datetime

def send_provider_alert_email(provider_name, balance, failed_count, alert_type='critical'):
    """
    Send email alert to admin when provider balance is critically low
    
    Args:
        provider_name: Name of the provider (e.g., 'Peyflex', 'Monnify')
        balance: Current balance amount
        failed_count: Number of recent failed transactions
        alert_type: 'critical' or 'warning'
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Admin email addresses
        admin_emails = [
            'hassanahmadabdullahi@gmail.com',
            'hassanahmad@ficoreafrica.com'
        ]
        
        # Email configuration from environment
        smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.environ.get('SMTP_PORT', 587))
        smtp_username = os.environ.get('SMTP_USERNAME', '')
        smtp_password = os.environ.get('SMTP_PASSWORD', '')
        sender_email = os.environ.get('SENDER_EMAIL', smtp_username)
        
        # Check if email is configured
        if not smtp_username or not smtp_password:
            print(f'⚠️ WARNING: Email not configured. Cannot send alert for {provider_name}')
            return False
        
        # Determine severity
        severity_emoji = '🚨' if alert_type == 'critical' else '⚠️'
        severity_text = 'CRITICAL' if alert_type == 'critical' else 'WARNING'
        
        # Create email subject
        subject = f'{severity_emoji} {severity_text}: {provider_name} Balance Low - ₦{balance:,.2f}'
        
        # Create email body
        body = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 2px solid {'#e74c3c' if alert_type == 'critical' else '#f39c12'}; border-radius: 10px;">
        <h2 style="color: {'#e74c3c' if alert_type == 'critical' else '#f39c12'};">
            {severity_emoji} {severity_text}: {provider_name} Balance Alert
        </h2>
        
        <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <h3 style="margin-top: 0;">Current Status:</h3>
            <ul style="list-style: none; padding: 0;">
                <li style="padding: 8px 0; border-bottom: 1px solid #ddd;">
                    <strong>Provider:</strong> {provider_name}
                </li>
                <li style="padding: 8px 0; border-bottom: 1px solid #ddd;">
                    <strong>Current Balance:</strong> <span style="color: {'#e74c3c' if alert_type == 'critical' else '#f39c12'}; font-size: 1.2em;">₦{balance:,.2f}</span>
                </li>
                <li style="padding: 8px 0; border-bottom: 1px solid #ddd;">
                    <strong>Failed Transactions (Last Hour):</strong> {failed_count}
                </li>
                <li style="padding: 8px 0;">
                    <strong>Alert Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
                </li>
            </ul>
        </div>
        
        <div style="background: {'#ffebee' if alert_type == 'critical' else '#fff3e0'}; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <h3 style="margin-top: 0; color: {'#c0392b' if alert_type == 'critical' else '#e67e22'};">
                {'⚡ IMMEDIATE ACTION REQUIRED' if alert_type == 'critical' else '⏰ Action Recommended'}
            </h3>
            <p style="margin: 10px 0;">
                {'Users are currently being affected by failed transactions. Fund the provider wallet immediately to restore service.' if alert_type == 'critical' else 'Consider funding the provider wallet soon to prevent service disruption.'}
            </p>
        </div>
        
        <div style="margin-top: 20px; padding: 15px; background: #e3f2fd; border-radius: 5px;">
            <h4 style="margin-top: 0;">Quick Actions:</h4>
            <ol>
                <li>Log in to {provider_name} dashboard</li>
                <li>Fund the wallet with sufficient balance</li>
                <li>Update balance in FiCore Provider Health Dashboard</li>
                <li>Monitor for successful transactions</li>
            </ol>
        </div>
        
        <div style="margin-top: 20px; padding: 10px; background: #f1f1f1; border-radius: 5px; font-size: 0.9em; color: #666;">
            <p style="margin: 5px 0;">
                <strong>Dashboard:</strong> <a href="https://mobilebackend.ficoreafrica.com/admin_web_app/provider_health_dashboard.html">Provider Health Monitor</a>
            </p>
            <p style="margin: 5px 0;">
                This is an automated alert from FiCore Provider Health Monitoring System.
            </p>
        </div>
    </div>
</body>
</html>
"""
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f'FiCore Alerts <{sender_email}>'
        msg['To'] = ', '.join(admin_emails)
        
        # Attach HTML body
        html_part = MIMEText(body, 'html')
        msg.attach(html_part)
        
        # Send email
        print(f'📧 Sending {severity_text} alert email for {provider_name}...')
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        print(f'✅ Alert email sent successfully to {", ".join(admin_emails)}')
        return True
        
    except Exception as e:
        print(f'❌ Error sending alert email: {str(e)}')
        return False


def send_test_alert():
    """Send a test alert email to verify configuration"""
    return send_provider_alert_email(
        provider_name='Test Provider',
        balance=4500.00,
        failed_count=5,
        alert_type='critical'
    )


if __name__ == '__main__':
    # Test the email function
    print('Testing email alert system...')
    success = send_test_alert()
    if success:
        print('✅ Test email sent successfully!')
    else:
        print('❌ Test email failed. Check configuration.')
