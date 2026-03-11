"""
Background Report Generator for FiCore Mobile
Generates PDFs in background threads and notifies users when ready

FREE SOLUTION - No Celery/RQ required!
Uses Python's built-in threading + MongoDB for job tracking
"""
import threading
import time
import traceback
from datetime import datetime, timedelta
from bson import ObjectId
import io


class ReportJobStatus:
    """Job status constants"""
    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'


class BackgroundReportGenerator:
    """
    Background report generator using threading.
    
    How it works:
    1. User requests export → Create job in MongoDB → Return job_id immediately
    2. Background thread generates PDF → Saves to GridFS → Updates job status
    3. User polls /api/reports/job-status/{job_id} → Gets download link when ready
    4. Frontend shows "Generating report... We'll notify you when ready"
    
    Benefits:
    - FREE (no external services)
    - User doesn't wait for PDF generation
    - Better UX for large reports
    - Automatic cleanup of old jobs (7 days)
    """
    
    def __init__(self, mongo_db):
        """
        Initialize background report generator.
        
        Args:
            mongo_db: MongoDB database instance
        """
        self.db = mongo_db
        self._ensure_collections()
    
    def _ensure_collections(self):
        """Ensure required collections and indexes exist"""
        try:
            # Create report_jobs collection if it doesn't exist
            if 'report_jobs' not in self.db.list_collection_names():
                self.db.create_collection('report_jobs')
            
            # Create indexes for efficient querying
            existing_indexes = self.db.report_jobs.index_information()
            
            if 'userId_createdAt_idx' not in existing_indexes:
                self.db.report_jobs.create_index(
                    [('userId', 1), ('createdAt', -1)],
                    name='userId_createdAt_idx'
                )
            
            if 'status_createdAt_idx' not in existing_indexes:
                self.db.report_jobs.create_index(
                    [('status', 1), ('createdAt', -1)],
                    name='status_createdAt_idx'
                )
            
            if 'jobId_idx' not in existing_indexes:
                self.db.report_jobs.create_index(
                    [('jobId', 1)],
                    name='jobId_idx',
                    unique=True
                )
            
            # TTL index to auto-delete jobs older than 7 days
            if 'ttl_idx' not in existing_indexes:
                self.db.report_jobs.create_index(
                    'createdAt',
                    name='ttl_idx',
                    expireAfterSeconds=604800  # 7 days
                )
            
        except Exception as e:
            print(f"⚠️ Warning: Could not create report_jobs indexes: {e}")
    
    def create_job(self, user_id, report_type, report_format, params):
        """
        Create a new report generation job.
        
        Args:
            user_id: User ObjectId
            report_type: Type of report (e.g., 'income', 'profit_loss')
            report_format: 'pdf' or 'csv'
            params: Dict of report parameters (date_range, filters, etc.)
        
        Returns:
            job_id: String job ID for tracking
        """
        job_id = str(ObjectId())
        
        job_doc = {
            'jobId': job_id,
            'userId': user_id,
            'reportType': report_type,
            'reportFormat': report_format,
            'params': params,
            'status': ReportJobStatus.PENDING,
            'progress': 0,
            'message': 'Report queued for generation',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'completedAt': None,
            'fileId': None,  # GridFS file ID when completed
            'fileName': None,
            'fileSize': None,
            'error': None
        }
        
        self.db.report_jobs.insert_one(job_doc)
        
        return job_id
    
    def start_generation(self, job_id, generation_function, *args, **kwargs):
        """
        Start PDF generation in background thread.
        
        Args:
            job_id: Job ID to track
            generation_function: Function that generates the PDF (returns BytesIO buffer)
            *args, **kwargs: Arguments to pass to generation_function
        """
        thread = threading.Thread(
            target=self._generate_report_worker,
            args=(job_id, generation_function, args, kwargs),
            daemon=True
        )
        thread.start()
    
    def _generate_report_worker(self, job_id, generation_function, args, kwargs):
        """
        Worker function that runs in background thread.
        
        This is where the actual PDF generation happens.
        """
        print(f"🔄 [WORKER START] Job {job_id} - Thread started")
        
        try:
            # Update status to processing
            print(f"📊 [WORKER] Job {job_id} - Updating status to PROCESSING")
            self._update_job(job_id, {
                'status': ReportJobStatus.PROCESSING,
                'progress': 10,
                'message': 'Fetching data from database...'
            })
            
            # Call the generation function (this is the slow part)
            print(f"📄 [WORKER] Job {job_id} - Calling generation function...")
            pdf_buffer = generation_function(*args, **kwargs)
            print(f"✅ [WORKER] Job {job_id} - PDF generated successfully ({pdf_buffer.getbuffer().nbytes} bytes)")
            
            # Update progress
            self._update_job(job_id, {
                'progress': 80,
                'message': 'Saving report file...'
            })
            
            # Save PDF to GridFS (MongoDB's file storage)
            print(f"💾 [WORKER] Job {job_id} - Saving to GridFS...")
            from gridfs import GridFS
            fs = GridFS(self.db)
            
            # Get job details for filename
            job = self.db.report_jobs.find_one({'jobId': job_id})
            report_type = job['reportType']
            report_format = job['reportFormat']
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            filename = f'ficore_{report_type}_report_{timestamp}.{report_format}'
            
            # Save file
            pdf_buffer.seek(0)
            file_id = fs.put(
                pdf_buffer,
                filename=filename,
                content_type='application/pdf' if report_format == 'pdf' else 'text/csv',
                metadata={
                    'userId': job['userId'],
                    'reportType': report_type,
                    'jobId': job_id,
                    'createdAt': datetime.utcnow()
                }
            )
            
            file_size = pdf_buffer.getbuffer().nbytes
            print(f"✅ [WORKER] Job {job_id} - Saved to GridFS with file_id: {file_id}")
            
            # Update job as completed
            print(f"🎉 [WORKER] Job {job_id} - Updating status to COMPLETED")
            self._update_job(job_id, {
                'status': ReportJobStatus.COMPLETED,
                'progress': 100,
                'message': 'Report ready for download',
                'completedAt': datetime.utcnow(),
                'fileId': str(file_id),
                'fileName': filename,
                'fileSize': file_size
            })
            
            print(f"✅ [WORKER COMPLETE] Job {job_id} completed successfully")
            
        except Exception as e:
            # Update job as failed
            error_msg = str(e)
            error_trace = traceback.format_exc()
            
            print(f"❌ [WORKER FAILED] Job {job_id} - Error: {error_msg}")
            print(f"📋 [WORKER FAILED] Job {job_id} - Stack trace:")
            print(error_trace)
            
            self._update_job(job_id, {
                'status': ReportJobStatus.FAILED,
                'progress': 0,
                'message': f'Report generation failed: {error_msg}',
                'error': error_trace
            })
            
            print(f"❌ Report job {job_id} failed: {error_msg}")
            print(error_trace)
    
    def _update_job(self, job_id, updates):
        """Update job status in database"""
        updates['updatedAt'] = datetime.utcnow()
        self.db.report_jobs.update_one(
            {'jobId': job_id},
            {'$set': updates}
        )
    
    def get_job_status(self, job_id):
        """
        Get current status of a report job.
        
        Returns:
            Dict with job status, progress, message, download_url (if completed)
        """
        job = self.db.report_jobs.find_one({'jobId': job_id})
        
        if not job:
            return {
                'found': False,
                'error': 'Job not found'
            }
        
        result = {
            'found': True,
            'jobId': job_id,
            'status': job['status'],
            'progress': job['progress'],
            'message': job['message'],
            'createdAt': job['createdAt'].isoformat() + 'Z',
            'updatedAt': job['updatedAt'].isoformat() + 'Z'
        }
        
        if job['status'] == ReportJobStatus.COMPLETED:
            result['completedAt'] = job['completedAt'].isoformat() + 'Z'
            result['fileName'] = job['fileName']
            result['fileSize'] = job['fileSize']
            result['downloadUrl'] = f'/api/reports/download/{job_id}'
        
        if job['status'] == ReportJobStatus.FAILED:
            result['error'] = job.get('error', 'Unknown error')
        
        return result
    
    def get_user_jobs(self, user_id, limit=10):
        """
        Get recent report jobs for a user.
        
        Args:
            user_id: User ObjectId
            limit: Maximum number of jobs to return
        
        Returns:
            List of job status dicts
        """
        jobs = list(self.db.report_jobs.find(
            {'userId': user_id}
        ).sort('createdAt', -1).limit(limit))
        
        return [self.get_job_status(job['jobId']) for job in jobs]
    
    def get_file(self, job_id):
        """
        Get the generated file for a completed job.
        
        Returns:
            Tuple of (file_buffer, filename, mimetype) or (None, None, None) if not found
        """
        job = self.db.report_jobs.find_one({'jobId': job_id})
        
        if not job or job['status'] != ReportJobStatus.COMPLETED:
            return None, None, None
        
        from gridfs import GridFS
        fs = GridFS(self.db)
        
        try:
            file_id = ObjectId(job['fileId'])
            grid_file = fs.get(file_id)
            
            # Read file into BytesIO buffer
            buffer = io.BytesIO(grid_file.read())
            buffer.seek(0)
            
            filename = job['fileName']
            mimetype = 'application/pdf' if job['reportFormat'] == 'pdf' else 'text/csv'
            
            return buffer, filename, mimetype
            
        except Exception as e:
            print(f"❌ Error retrieving file for job {job_id}: {e}")
            return None, None, None
    
    def cleanup_old_jobs(self, days=7):
        """
        Manually cleanup old jobs (in addition to TTL index).
        
        Args:
            days: Delete jobs older than this many days
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Find old jobs
        old_jobs = list(self.db.report_jobs.find({
            'createdAt': {'$lt': cutoff_date}
        }))
        
        if not old_jobs:
            print(f"✅ No jobs older than {days} days to cleanup")
            return
        
        # Delete associated files from GridFS
        from gridfs import GridFS
        fs = GridFS(self.db)
        
        deleted_count = 0
        for job in old_jobs:
            if job.get('fileId'):
                try:
                    fs.delete(ObjectId(job['fileId']))
                except Exception as e:
                    print(f"⚠️ Could not delete file {job['fileId']}: {e}")
            
            deleted_count += 1
        
        # Delete job records
        self.db.report_jobs.delete_many({
            'createdAt': {'$lt': cutoff_date}
        })
        
        print(f"✅ Cleaned up {deleted_count} old report jobs")


# Singleton instance
_background_generator = None

def get_background_generator(mongo_db):
    """Get or create singleton background generator instance"""
    global _background_generator
    if _background_generator is None:
        _background_generator = BackgroundReportGenerator(mongo_db)
    return _background_generator
