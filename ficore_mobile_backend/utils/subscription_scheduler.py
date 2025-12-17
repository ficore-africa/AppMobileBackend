"""
Subscription Scheduler
Handles scheduled tasks for subscription management using APScheduler
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class SubscriptionScheduler:
    """
    Manages scheduled tasks for subscription lifecycle management.
    """
    
    def __init__(self, mongo_db):
        self.db = mongo_db
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        
    def start(self):
        """Start the scheduler with all subscription-related jobs"""
        if self.is_running:
            logger.warning("Scheduler already running")
            return
        
        try:
            # Import here to avoid circular dependencies
            from utils.subscription_expiration_manager import SubscriptionExpirationManager
            from utils.subscription_notification_manager import SubscriptionNotificationManager
            
            expiration_manager = SubscriptionExpirationManager(self.db)
            notification_manager = SubscriptionNotificationManager(self.db)
            
            # Job 1: Process expired subscriptions (Daily at 2 AM UTC)
            self.scheduler.add_job(
                func=expiration_manager.process_expired_subscriptions,
                trigger=CronTrigger(hour=2, minute=0),
                id='process_expired_subscriptions',
                name='Process Expired Subscriptions',
                replace_existing=True
            )
            
            # Job 2: Send expiry warnings (Daily at 10 AM UTC)
            self.scheduler.add_job(
                func=notification_manager.send_expiry_warnings,
                trigger=CronTrigger(hour=10, minute=0),
                id='send_expiry_warnings',
                name='Send Expiry Warnings',
                replace_existing=True
            )
            
            # Job 3: Send renewal reminders (Daily at 9 AM UTC)
            self.scheduler.add_job(
                func=notification_manager.send_renewal_reminders,
                trigger=CronTrigger(hour=9, minute=0),
                id='send_renewal_reminders',
                name='Send Renewal Reminders',
                replace_existing=True
            )
            
            # Job 4: Send re-engagement messages (Daily at 11 AM UTC)
            self.scheduler.add_job(
                func=notification_manager.send_reengagement_messages,
                trigger=CronTrigger(hour=11, minute=0),
                id='send_reengagement_messages',
                name='Send Re-engagement Messages',
                replace_existing=True
            )
            
            # Job 5: Process auto-renewals (Daily at 1 AM UTC)
            self.scheduler.add_job(
                func=self._process_auto_renewals,
                trigger=CronTrigger(hour=1, minute=0),
                id='process_auto_renewals',
                name='Process Auto-Renewals',
                replace_existing=True
            )
            
            self.scheduler.start()
            self.is_running = True
            logger.info("Subscription scheduler started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start subscription scheduler: {str(e)}")
            raise
    
    def stop(self):
        """Stop the scheduler"""
        if not self.is_running:
            return
        
        try:
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("Subscription scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {str(e)}")
    
    def _process_auto_renewals(self):
        """Process subscriptions set for auto-renewal"""
        logger.info("Processing auto-renewals...")
        # Implementation will depend on payment gateway integration
        # For now, just log
        logger.info("Auto-renewal processing complete")
    
    def get_scheduler_status(self):
        """Get current scheduler status"""
        jobs = []
        if self.is_running:
            for job in self.scheduler.get_jobs():
                jobs.append({
                    'id': job.id,
                    'name': job.name,
                    'next_run': job.next_run_time.isoformat() if job.next_run_time else None
                })
        
        return {
            'is_running': self.is_running,
            'jobs': jobs,
            'timestamp': datetime.utcnow().isoformat()
        }
