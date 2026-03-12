"""
Analytics tracker for FiCore backend
"""
from datetime import datetime
from bson import ObjectId

class AnalyticsTracker:
    """Analytics tracker class with proper methods"""
    
    def __init__(self, mongo_db):
        self.mongo_db = mongo_db
    
    def track_event(self, user_id, event_type, event_details=None):
        """
        Track a generic event
        
        Args:
            user_id: User ObjectId
            event_type: Type of event to track
            event_details: Optional event metadata
        
        Returns:
            dict: Tracking result
        """
        try:
            print(f"📊 Analytics: {event_type} for user {user_id}")
            
            # Store in database if available
            if self.mongo_db is not None:
                event_log = {
                    'userId': ObjectId(user_id) if user_id else None,
                    'eventType': event_type,
                    'eventDetails': event_details or {},
                    'timestamp': datetime.utcnow()
                }
                self.mongo_db.analytics_events.insert_one(event_log)
            
            return {'success': True, 'event_id': 'tracked'}
        except Exception as e:
            print(f"Analytics tracking error: {e}")
            return {'success': False, 'error': str(e)}
    
    def track_login(self, user_id, device_info=None):
        """Track user login"""
        return self.track_event(user_id, 'user_login', {'device_info': device_info})
    
    def track_registration(self, user_id, device_info=None):
        """Track user registration"""
        return self.track_event(user_id, 'user_registration', {'device_info': device_info})
    
    def track_dashboard_view(self, user_id):
        """Track dashboard view"""
        return self.track_event(user_id, 'dashboard_view')
    
    def track_income_created(self, user_id, amount, category=None, source_type=None):
        """Track income creation"""
        return self.track_event(user_id, 'income_created', {
            'amount': amount,
            'category': category,
            'source_type': source_type
        })
    
    def track_expense_created(self, user_id, amount, category=None, source_type=None):
        """Track expense creation"""
        return self.track_event(user_id, 'expense_created', {
            'amount': amount,
            'category': category,
            'source_type': source_type
        })
    
    def track_profile_updated(self, user_id, fields_updated=None):
        """Track profile update"""
        return self.track_event(user_id, 'profile_updated', {
            'fields_updated': fields_updated or []
        })
    
    def track_tax_calculation(self, user_id, tax_year=None):
        """Track tax calculation"""
        return self.track_event(user_id, 'tax_calculation', {
            'tax_year': tax_year
        })
    
    def track_subscription_started(self, user_id, subscription_type=None, plan_details=None):
        """Track subscription started"""
        return self.track_event(user_id, 'subscription_started', {
            'subscription_type': subscription_type,
            'plan_details': plan_details
        })

def create_tracker(mongo_db):
    """
    Create an analytics tracker instance
    
    Args:
        mongo_db: MongoDB database connection
    
    Returns:
        AnalyticsTracker: Tracker instance with methods
    """
    return AnalyticsTracker(mongo_db)

def track_export(user_id, export_type, file_format, record_count=0):
    """
    Track export operations for analytics
    
    Args:
        user_id: User ObjectId
        export_type: Type of export (income, expense, report)
        file_format: Format (pdf, csv, excel)
        record_count: Number of records exported
        
    Returns:
        bool: True if tracked successfully
    """
    try:
        print(f"Export tracked: User {user_id} exported {record_count} {export_type} records as {file_format}")
        return True
        
    except Exception as e:
        print(f"Error tracking export: {str(e)}")
        return False
