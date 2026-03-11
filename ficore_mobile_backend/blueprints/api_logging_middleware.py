"""
API Logging Middleware - Automatically log all API calls for rate limit monitoring
"""
from flask import request, g
from datetime import datetime
import time

def setup_api_logging(app, rate_limit_tracker):
    """Setup middleware to log all API calls"""
    
    @app.before_request
    def before_request():
        """Record request start time"""
        g.start_time = time.time()
    
    @app.after_request
    def after_request(response):
        """Log API call after request completes"""
        try:
            # Calculate response time
            if hasattr(g, 'start_time'):
                response_time_ms = (time.time() - g.start_time) * 1000
            else:
                response_time_ms = 0
            
            # Get user ID from request context (set by token_required decorator)
            user_id = getattr(g, 'current_user_id', None)
            
            # Only log API calls (not static files)
            endpoint = request.endpoint
            if endpoint and not endpoint.startswith('static'):
                # Get the actual route path
                path = request.path
                method = request.method
                status_code = response.status_code
                
                # Log the call
                if user_id:
                    rate_limit_tracker.log_api_call(
                        user_id=user_id,
                        endpoint=path,
                        method=method,
                        status_code=status_code,
                        response_time_ms=response_time_ms
                    )
            
        except Exception as e:
            # Don't fail the request if logging fails
            print(f"Error in API logging middleware: {e}")
        
        return response
    
    return app
