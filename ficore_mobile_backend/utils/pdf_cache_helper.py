"""
PDF Cache Helper for FiCore Mobile
Simple file-system based caching for generated PDFs to avoid regenerating identical reports
"""
import os
import hashlib
import json
from datetime import datetime, timedelta
import io


class PDFCache:
    """
    Simple file-system based PDF cache.
    
    Caches generated PDFs to avoid regenerating identical reports.
    Uses hash of (userId + reportType + dateRange + filters) as cache key.
    
    Benefits:
    - Instant delivery for duplicate requests
    - Reduces server load
    - Better user experience
    
    Safety:
    - Only caches for 24 hours (configurable)
    - Automatic cleanup of old files
    - No sensitive data in cache keys
    """
    
    def __init__(self, cache_dir='pdf_cache', ttl_hours=24, max_cache_size_mb=500):
        """
        Initialize PDF cache.
        
        Args:
            cache_dir: Directory to store cached PDFs (default: 'pdf_cache')
            ttl_hours: Time-to-live for cached PDFs in hours (default: 24)
            max_cache_size_mb: Maximum cache size in MB (default: 500)
        """
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_hours * 3600
        self.max_cache_size_bytes = max_cache_size_mb * 1024 * 1024
        
        # Create cache directory if it doesn't exist
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
            print(f"📁 Created PDF cache directory: {self.cache_dir}")
    
    def _generate_cache_key(self, user_id, report_type, params):
        """
        Generate a unique cache key based on request parameters.
        
        CACHE INVALIDATION: Includes last_updated timestamp to ensure cache
        is automatically invalidated when user adds/edits transactions.
        
        Args:
            user_id: User ID
            report_type: Type of report (e.g., 'income_pdf', 'tax_summary_pdf')
            params: Dict of parameters (date_range, filters, last_updated, etc.)
        
        Returns:
            Hash string to use as cache key
        """
        # Create a deterministic string from parameters
        cache_data = {
            'user_id': str(user_id),
            'report_type': report_type,
            'params': params
        }
        
        # Sort keys for deterministic hashing
        cache_string = json.dumps(cache_data, sort_keys=True)
        
        # Generate SHA256 hash
        cache_hash = hashlib.sha256(cache_string.encode()).hexdigest()
        
        return cache_hash
    
    def _get_cache_path(self, cache_key):
        """Get full path to cached PDF file."""
        return os.path.join(self.cache_dir, f"{cache_key}.pdf")
    
    def _get_metadata_path(self, cache_key):
        """Get full path to cache metadata file."""
        return os.path.join(self.cache_dir, f"{cache_key}.meta")
    
    def get(self, user_id, report_type, params):
        """
        Retrieve cached PDF if it exists and is still valid.
        
        Args:
            user_id: User ID
            report_type: Type of report
            params: Request parameters
        
        Returns:
            BytesIO buffer with PDF content if cached, None otherwise
        """
        cache_key = self._generate_cache_key(user_id, report_type, params)
        cache_path = self._get_cache_path(cache_key)
        meta_path = self._get_metadata_path(cache_key)
        
        # Check if cache file exists
        if not os.path.exists(cache_path) or not os.path.exists(meta_path):
            return None
        
        # Check if cache is still valid (not expired)
        try:
            with open(meta_path, 'r') as f:
                metadata = json.load(f)
            
            created_at = datetime.fromisoformat(metadata['created_at'])
            age_seconds = (datetime.now() - created_at).total_seconds()
            
            if age_seconds > self.ttl_seconds:
                # Cache expired, delete it
                self._delete_cache_entry(cache_key)
                return None
            
            # Cache is valid, read and return PDF
            with open(cache_path, 'rb') as f:
                pdf_content = f.read()
            
            # Return as BytesIO buffer (same format as pdf_generator)
            buffer = io.BytesIO(pdf_content)
            buffer.seek(0)
            
            print(f"✅ PDF cache HIT for {report_type} (age: {age_seconds:.0f}s)")
            return buffer
            
        except Exception as e:
            print(f"⚠️ Error reading cache: {e}")
            self._delete_cache_entry(cache_key)
            return None
    
    def set(self, user_id, report_type, params, pdf_buffer):
        """
        Store generated PDF in cache.
        
        Args:
            user_id: User ID
            report_type: Type of report
            params: Request parameters
            pdf_buffer: BytesIO buffer with PDF content
        
        Returns:
            True if cached successfully, False otherwise
        """
        try:
            cache_key = self._generate_cache_key(user_id, report_type, params)
            cache_path = self._get_cache_path(cache_key)
            meta_path = self._get_metadata_path(cache_key)
            
            # Save PDF content
            pdf_buffer.seek(0)
            with open(cache_path, 'wb') as f:
                f.write(pdf_buffer.read())
            
            # Save metadata
            metadata = {
                'user_id': str(user_id),
                'report_type': report_type,
                'created_at': datetime.now().isoformat(),
                'size_bytes': os.path.getsize(cache_path)
            }
            
            with open(meta_path, 'w') as f:
                json.dump(metadata, f)
            
            # Reset buffer position for caller
            pdf_buffer.seek(0)
            
            print(f"💾 PDF cached for {report_type} (size: {metadata['size_bytes']} bytes)")
            
            # Cleanup old cache entries if needed
            self._cleanup_if_needed()
            
            return True
            
        except Exception as e:
            print(f"⚠️ Error caching PDF: {e}")
            return False
    
    def _delete_cache_entry(self, cache_key):
        """Delete a cache entry (PDF + metadata)."""
        cache_path = self._get_cache_path(cache_key)
        meta_path = self._get_metadata_path(cache_key)
        
        try:
            if os.path.exists(cache_path):
                os.remove(cache_path)
            if os.path.exists(meta_path):
                os.remove(meta_path)
        except Exception as e:
            print(f"⚠️ Error deleting cache entry: {e}")
    
    def _cleanup_if_needed(self):
        """
        Cleanup old cache entries if cache size exceeds limit OR files are expired.
        Removes oldest entries first.
        
        This runs automatically after each cache write, so no external cron job needed!
        """
        try:
            # Get all cache files with their metadata
            cache_entries = []
            now = datetime.now()
            
            for filename in os.listdir(self.cache_dir):
                if filename.endswith('.meta'):
                    meta_path = os.path.join(self.cache_dir, filename)
                    try:
                        with open(meta_path, 'r') as f:
                            metadata = json.load(f)
                        
                        cache_key = filename.replace('.meta', '')
                        cache_path = self._get_cache_path(cache_key)
                        
                        if os.path.exists(cache_path):
                            created_at = datetime.fromisoformat(metadata['created_at'])
                            age_seconds = (now - created_at).total_seconds()
                            
                            # Delete expired entries immediately
                            if age_seconds > self.ttl_seconds:
                                self._delete_cache_entry(cache_key)
                                print(f"🗑️ Auto-deleted expired cache entry (age: {age_seconds/3600:.1f}h)")
                                continue
                            
                            cache_entries.append({
                                'key': cache_key,
                                'created_at': created_at,
                                'size': os.path.getsize(cache_path)
                            })
                    except:
                        pass
            
            # Calculate total cache size
            total_size = sum(entry['size'] for entry in cache_entries)
            
            # If cache is too large, remove oldest entries
            if total_size > self.max_cache_size_bytes:
                # Sort by creation time (oldest first)
                cache_entries.sort(key=lambda x: x['created_at'])
                
                # Remove entries until we're under the limit
                for entry in cache_entries:
                    if total_size <= self.max_cache_size_bytes * 0.8:  # Leave 20% buffer
                        break
                    
                    self._delete_cache_entry(entry['key'])
                    total_size -= entry['size']
                    print(f"🗑️ Removed old cache entry (freed {entry['size']} bytes)")
        
        except Exception as e:
            print(f"⚠️ Error during cache cleanup: {e}")
    
    def clear_all(self):
        """Clear all cached PDFs (useful for testing or maintenance)."""
        try:
            for filename in os.listdir(self.cache_dir):
                file_path = os.path.join(self.cache_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            print(f"🗑️ Cleared all PDF cache entries")
            return True
        except Exception as e:
            print(f"⚠️ Error clearing cache: {e}")
            return False
    
    def get_stats(self):
        """
        Get cache statistics.
        
        Returns:
            Dict with cache stats (size, count, oldest, newest)
        """
        try:
            cache_entries = []
            total_size = 0
            
            for filename in os.listdir(self.cache_dir):
                if filename.endswith('.pdf'):
                    file_path = os.path.join(self.cache_dir, filename)
                    size = os.path.getsize(file_path)
                    mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    
                    cache_entries.append({
                        'size': size,
                        'modified': mtime
                    })
                    total_size += size
            
            if not cache_entries:
                return {
                    'count': 0,
                    'total_size_mb': 0,
                    'oldest': None,
                    'newest': None
                }
            
            cache_entries.sort(key=lambda x: x['modified'])
            
            return {
                'count': len(cache_entries),
                'total_size_mb': total_size / (1024 * 1024),
                'oldest': cache_entries[0]['modified'].isoformat(),
                'newest': cache_entries[-1]['modified'].isoformat()
            }
        
        except Exception as e:
            print(f"⚠️ Error getting cache stats: {e}")
            return {'error': str(e)}


# Global cache instance (singleton pattern)
_pdf_cache_instance = None


def get_pdf_cache():
    """
    Get the global PDF cache instance (singleton).
    
    Returns:
        PDFCache instance
    """
    global _pdf_cache_instance
    
    if _pdf_cache_instance is None:
        # Initialize cache with default settings
        _pdf_cache_instance = PDFCache(
            cache_dir='pdf_cache',
            ttl_hours=24,  # Cache for 24 hours
            max_cache_size_mb=500  # Max 500 MB cache
        )
    
    return _pdf_cache_instance
