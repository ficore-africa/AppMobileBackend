"""
Engagement Reminder Service for ₦0 Communication Strategy
Sends weekly engagement emails to inactive users to boost retention
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from bson import ObjectId
from utils.email_service import get_email_service

logger = logging.getLogger(__name__)

class EngagementReminderService:
    """Service for sending weekly engagement reminders to inactive users"""
    
    def __init__(self, mongo):
        self.mongo = mongo
        self.email_service = get_email_service()
    
    def send_weekly_engagement_reminders(self) -> Dict[str, Any]:
        """
        Send weekly engagement reminders to users who haven't been active
        
        Returns:
            Dict with summary of emails sent
        """
        try:
            # Define inactivity thresholds
            one_week_ago = datetime.utcnow() - timedelta(days=7)
            two_weeks_ago = datetime.utcnow() - timedelta(days=14)
            one_month_ago = datetime.utcnow() - timedelta(days=30)
            
            results = {
                'total_processed': 0,
                'emails_sent': 0,
                'errors': 0,
                'categories': {
                    'week_inactive': 0,
                    'two_weeks_inactive': 0,
                    'month_inactive': 0
                }
            }
            
            # Get inactive users (haven't logged in recently)
            inactive_users = list(self.mongo.db.users.find({
                'isActive': True,
                'email': {'$exists': True, '$ne': ''},
                '$or': [
                    {'lastLogin': {'$lt': one_week_ago}},
                    {'lastLogin': {'$exists': False}}
                ]
            }))
            
            results['total_processed'] = len(inactive_users)
            
            for user in inactive_users:
                try:
                    # Determine inactivity level
                    last_login = user.get('lastLogin')
                    if not last_login or last_login < one_month_ago:
                        reminder_type = 'month_inactive'
                    elif last_login < two_weeks_ago:
                        reminder_type = 'two_weeks_inactive'
                    else:
                        reminder_type = 'week_inactive'
                    
                    # Send appropriate reminder
                    email_result = self._send_engagement_email(user, reminder_type)
                    
                    if email_result.get('success'):
                        results['emails_sent'] += 1
                        results['categories'][reminder_type] += 1
                        
                        # Log engagement reminder
                        self._log_engagement_reminder(user['_id'], reminder_type, email_result)
                    else:
                        results['errors'] += 1
                        
                except Exception as e:
                    logger.error(f"Failed to send engagement reminder to user {user.get('_id')}: {str(e)}")
                    results['errors'] += 1
            
            logger.info(f"Weekly engagement reminders completed: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Weekly engagement reminder process failed: {str(e)}")
            return {
                'total_processed': 0,
                'emails_sent': 0,
                'errors': 1,
                'error_message': str(e)
            }
    
    def _send_engagement_email(self, user: Dict[str, Any], reminder_type: str) -> Dict[str, Any]:
        """Send engagement email based on inactivity level"""
        
        user_name = user.get('displayName') or f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
        email = user.get('email')
        
        # Get user's financial data for personalization
        user_stats = self._get_user_stats(user['_id'])
        
        # Create personalized email content
        email_content = self._create_engagement_email_content(user_name, reminder_type, user_stats)
        
        return self.email_service._send_email(
            to_email=email,
            subject=email_content['subject'],
            html_body=email_content['html']
        )
    
    def _get_user_stats(self, user_id: ObjectId) -> Dict[str, Any]:
        """Get user's financial statistics for personalization"""
        try:
            # Get recent transactions count
            recent_transactions = self.mongo.db.income.count_documents({
                'userId': user_id,
                'createdAt': {'$gte': datetime.utcnow() - timedelta(days=30)}
            }) + self.mongo.db.expenses.count_documents({
                'userId': user_id,
                'createdAt': {'$gte': datetime.utcnow() - timedelta(days=30)}
            })
            
            # Get wallet balance if exists
            wallet = self.mongo.db.vas_wallets.find_one({'userId': user_id})
            wallet_balance = wallet.get('balance', 0.0) if wallet else 0.0
            
            # Get FiCore Credits balance
            user = self.mongo.db.users.find_one({'_id': user_id})
            fc_balance = user.get('ficoreCreditBalance', 0.0) if user else 0.0
            
            return {
                'recent_transactions': recent_transactions,
                'wallet_balance': wallet_balance,
                'fc_balance': fc_balance,
                'has_wallet': wallet is not None
            }
            
        except Exception as e:
            logger.error(f"Failed to get user stats for {user_id}: {str(e)}")
            return {
                'recent_transactions': 0,
                'wallet_balance': 0.0,
                'fc_balance': 0.0,
                'has_wallet': False
            }
    
    def _create_engagement_email_content(self, user_name: str, reminder_type: str, stats: Dict[str, Any]) -> Dict[str, str]:
        """Create personalized engagement email content"""
        
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        
        # Customize content based on inactivity level
        if reminder_type == 'month_inactive':
            subject = "We miss you at FiCore! Your financial goals are waiting 💰"
            main_message = "It's been a while since we've seen you! Your financial journey doesn't have to pause."
            cta_text = "Resume Your Journey"
            urgency = "Don't let another month pass without progress on your financial goals."
        elif reminder_type == 'two_weeks_inactive':
            subject = "Your FiCore account is ready when you are 📊"
            main_message = "Two weeks can make a big difference in your financial tracking."
            cta_text = "Continue Tracking"
            urgency = "The sooner you start, the clearer your financial picture becomes."
        else:  # week_inactive
            subject = "Quick check-in: How are your finances this week? 📈"
            main_message = "A week of financial tracking can reveal powerful insights."
            cta_text = "Add This Week's Data"
            urgency = "Stay consistent with your financial tracking for better results."
        
        # Personalized stats section
        stats_section = ""
        if stats['fc_balance'] > 0:
            stats_section += f"""
                <div style="background: #F4F1EC; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #B88A44;">
                    <p style="margin: 0; color: #B88A44; font-weight: bold;">
                        💎 You have {stats['fc_balance']:.0f} FiCore Credits waiting to be used!
                    </p>
                </div>"""
        
        if stats['wallet_balance'] > 0:
            stats_section += f"""
                <div style="background: #F4F1EC; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #16A34A;">
                    <p style="margin: 0; color: #16A34A; font-weight: bold;">
                        💳 Your Liquid Wallet has ₦{stats['wallet_balance']:,.2f} ready for utilities!
                    </p>
                </div>"""
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{subject}</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #2E2E2E; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #FFF8F0;">
            <div style="background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px; font-weight: bold;">FiCore Africa</h1>
                <p style="color: #E8F0FE; margin: 5px 0 0 0; font-size: 16px;">Your Financial Journey Continues</p>
            </div>
            
            <div style="background: white; padding: 40px; border: 1px solid #E5E7EB; border-top: none; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; margin-bottom: 20px; color: #2E2E2E;">{greeting}</p>
                
                <p style="font-size: 16px; margin-bottom: 30px; color: #2E2E2E;">
                    {main_message}
                </p>
                
                {stats_section}
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://app.ficore.africa" style="background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%); color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-size: 16px; font-weight: bold; display: inline-block; box-shadow: 0 4px 6px rgba(30, 58, 138, 0.2);">
                        {cta_text}
                    </a>
                </div>
                
                <div style="background: #F4F1EC; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #1E3A8A; margin: 0 0 15px 0;">Quick Actions You Can Take:</h3>
                    <ul style="color: #2E2E2E; margin: 0; padding-left: 20px;">
                        <li>📊 Add your recent income and expenses</li>
                        <li>💳 Fund your Liquid Wallet for utilities</li>
                        <li>🎯 Review your financial goals progress</li>
                        <li>📈 Check your spending patterns</li>
                    </ul>
                </div>
                
                <p style="font-size: 14px; color: #6B7280; margin: 20px 0; text-align: center; font-style: italic;">
                    {urgency}
                </p>
                
                <div style="border-top: 1px solid #E5E7EB; padding-top: 20px; margin-top: 30px;">
                    <p style="font-size: 12px; color: #6B7280; text-align: center; margin: 0;">
                        <strong>FiCore Africa</strong> - Your trusted financial partner<br>
                        This is an automated reminder. Reply STOP to unsubscribe.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return {
            'subject': subject,
            'html': html_content
        }
    
    def _log_engagement_reminder(self, user_id: ObjectId, reminder_type: str, email_result: Dict[str, Any]):
        """Log engagement reminder for analytics"""
        try:
            log_entry = {
                '_id': ObjectId(),
                'userId': user_id,
                'type': 'engagement_reminder',
                'reminderType': reminder_type,
                'emailSent': email_result.get('success', False),
                'emailMethod': email_result.get('method', 'unknown'),
                'sentAt': datetime.utcnow(),
                'metadata': {
                    'email_result': email_result
                }
            }
            
            self.mongo.db.engagement_logs.insert_one(log_entry)
            
        except Exception as e:
            logger.error(f"Failed to log engagement reminder: {str(e)}")


def send_weekly_engagement_reminders(mongo):
    """Standalone function to send weekly engagement reminders"""
    service = EngagementReminderService(mongo)
    return service.send_weekly_engagement_reminders()