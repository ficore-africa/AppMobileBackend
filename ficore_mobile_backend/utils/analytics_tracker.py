"""
Analytics Tracker Utility
Helper functions to track user events across the application.
"""

from datetime import datetime
from bson import ObjectId
from typing import Dict, Any, Optional


class AnalyticsTracker:
    """
    Utility class for tracking user events.
    """
    
    def __init__(self, mongo_db):
        """
        Initialize tracker with MongoDB database instance.
        
        Args:
            mongo_db: PyMongo database instance
        """
        self.db = mongo_db
    
    def track_event(
        self,
        user_id: ObjectId,
        event_type: str,
        event_details: Optional[Dict[str, Any]] = None,
        device_info: Optional[Dict[str, str]] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Track a user event.
        
        Args:
            user_id: User's ObjectId
            event_type: Type of event (e.g., 'user_logged_in')
            event_details: Optional event-specific data
            device_info: Optional device information
            session_id: Optional session identifier
            
        Returns:
            bool: True if event was tracked successfully, False otherwise
        """
        try:
            event = {
                'userId': user_id,
                'eventType': event_type,
                'timestamp': datetime.utcnow(),
                'eventDetails': event_details,
                'deviceInfo': device_info,
                'sessionId': session_id,
                'createdAt': datetime.utcnow()
            }
            
            self.db.analytics_events.insert_one(event)
            return True
            
        except Exception as e:
            print(f"Error tracking event '{event_type}' for user {user_id}: {str(e)}")
            return False
    
    def track_login(self, user_id: ObjectId, device_info: Optional[Dict[str, str]] = None) -> bool:
        """Track user login event."""
        return self.track_event(user_id, 'user_logged_in', device_info=device_info)
    
    def track_registration(self, user_id: ObjectId, device_info: Optional[Dict[str, str]] = None) -> bool:
        """Track user registration event."""
        return self.track_event(user_id, 'user_registered', device_info=device_info)
    
    def track_income_created(
        self,
        user_id: ObjectId,
        amount: float,
        category: Optional[str] = None,
        source: Optional[str] = None
    ) -> bool:
        """Track income entry creation."""
        event_details = {
            'amount': amount,
            'category': category,
            'source': source
        }
        return self.track_event(user_id, 'income_entry_created', event_details=event_details)
    
    def track_expense_created(
        self,
        user_id: ObjectId,
        amount: float,
        category: Optional[str] = None
    ) -> bool:
        """Track expense entry creation."""
        event_details = {
            'amount': amount,
            'category': category
        }
        return self.track_event(user_id, 'expense_entry_created', event_details=event_details)
    
    def track_profile_updated(self, user_id: ObjectId, fields_updated: Optional[list] = None) -> bool:
        """Track profile update event."""
        event_details = {
            'fields_updated': fields_updated
        } if fields_updated else None
        return self.track_event(user_id, 'profile_updated', event_details=event_details)
    
    def track_subscription_started(
        self,
        user_id: ObjectId,
        subscription_type: str,
        amount: Optional[float] = None
    ) -> bool:
        """Track subscription start event."""
        event_details = {
            'subscription_type': subscription_type,
            'amount': amount
        }
        return self.track_event(user_id, 'subscription_started', event_details=event_details)
    
    def track_tax_calculation(self, user_id: ObjectId, tax_year: Optional[int] = None) -> bool:
        """Track tax calculation event."""
        event_details = {
            'tax_year': tax_year
        } if tax_year else None
        return self.track_event(user_id, 'tax_calculation_performed', event_details=event_details)
    
    def track_dashboard_view(self, user_id: ObjectId) -> bool:
        """Track dashboard view event."""
        return self.track_event(user_id, 'dashboard_viewed')
    
    def track_report_generated(
        self,
        user_id: ObjectId,
        report_type: Optional[str] = None
    ) -> bool:
        """Track report generation event."""
        event_details = {
            'report_type': report_type
        } if report_type else None
        return self.track_event(user_id, 'report_generated', event_details=event_details)


def create_tracker(mongo_db):
    """
    Factory function to create an AnalyticsTracker instance.
    
    Args:
        mongo_db: PyMongo database instance
        
    Returns:
        AnalyticsTracker: Configured tracker instance
    """
    return AnalyticsTracker(mongo_db)
