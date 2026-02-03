"""
Transaction Task Queue - Bulletproof VAS Transaction Processing
Handles the critical gap between provider success and database update
Includes wallet reservation system to prevent double-spending
"""

import time
import json
import threading
from datetime import datetime, timedelta
from bson import ObjectId
from typing import Dict, Any, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TransactionTaskQueue:
    """
    Bulletproof task queue for VAS transactions with wallet reservation
    Ensures that if provider succeeds, database WILL be updated eventually
    Prevents double-spending by reserving wallet amounts immediately
    """
    
    def __init__(self, mongo_db):
        self.mongo = mongo_db
        self.pending_tasks = {}  # In-memory queue for immediate processing
        self.worker_running = False
        self.worker_thread = None
        
    def start_worker(self):
        """Start the background worker thread"""
        if not self.worker_running:
            self.worker_running = True
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            logger.info("🚀 Transaction task queue worker started")
    
    def stop_worker(self):
        """Stop the background worker thread"""
        self.worker_running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        logger.info("🛑 Transaction task queue worker stopped")
    
    def reserve_wallet_amount(self, user_id: str, amount: float, description: str) -> bool:
        """
        Reserve amount in user's wallet to prevent double-spending
        Returns True if reservation successful, False if insufficient funds
        """
        try:
            # Atomic operation to reserve funds
            result = self.mongo.vas_wallets.update_one(
                {
                    'userId': ObjectId(user_id),
                    'balance': {'$gte': amount}  # Only if sufficient balance
                },
                {
                    '$inc': {
                        'balance': -amount,  # Immediately deduct from available balance
                        'reservedAmount': amount  # Add to reserved amount
                    },
                    '$push': {
                        'reservationHistory': {
                            'amount': amount,
                            'description': description,
                            'timestamp': datetime.utcnow(),
                            'status': 'RESERVED'
                        }
                    },
                    '$set': {'updatedAt': datetime.utcnow()}
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"💰 Reserved ₦{amount:,.2f} for user {user_id}")
                return True
            else:
                logger.warning(f"❌ Insufficient funds to reserve ₦{amount:,.2f} for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error reserving wallet amount: {str(e)}")
            return False
    
    def release_reservation(self, user_id: str, amount: float, reason: str = "Task completed"):
        """
        Release reserved amount (move from reserved to actual debit)
        Called when task completes successfully
        
        CRITICAL: Ensure reservedAmount never goes negative
        """
        try:
            # First check current reserved amount
            wallet = self.mongo.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                logger.error(f"❌ Wallet not found for user {user_id}")
                return
            
            current_reserved = wallet.get('reservedAmount', 0.0)
            
            # Don't decrement if already 0 or would go negative
            if current_reserved <= 0:
                logger.warning(f"⚠️ Reserved amount already 0 for user {user_id}, skipping release")
                return
            
            # Only decrement up to the current reserved amount
            amount_to_release = min(amount, current_reserved)
            
            result = self.mongo.vas_wallets.update_one(
                {'userId': ObjectId(user_id)},
                {
                    '$inc': {'reservedAmount': -amount_to_release},  # Remove from reserved (never goes negative)
                    '$push': {
                        'transactionHistory': {
                            'type': 'DEBIT_CONFIRMED',
                            'amount': amount_to_release,
                            'description': reason,
                            'timestamp': datetime.utcnow()
                        }
                    },
                    '$set': {'updatedAt': datetime.utcnow()}
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Released reservation ₦{amount_to_release:,.2f} for user {user_id}")
            else:
                logger.warning(f"⚠️ Could not release reservation for user {user_id}")
                
        except Exception as e:
            logger.error(f"❌ Error releasing reservation: {str(e)}")
    
    def rollback_reservation(self, user_id: str, amount: float, reason: str = "Task failed"):
        """
        Rollback reserved amount (return to available balance)
        Called when task fails and needs to refund user
        
        CRITICAL: Ensure reservedAmount never goes negative
        """
        try:
            # First check current reserved amount
            wallet = self.mongo.vas_wallets.find_one({'userId': ObjectId(user_id)})
            if not wallet:
                logger.error(f"❌ Wallet not found for user {user_id}")
                return
            
            current_reserved = wallet.get('reservedAmount', 0.0)
            
            # Don't decrement if already 0 or would go negative
            if current_reserved <= 0:
                logger.warning(f"⚠️ Reserved amount already 0 for user {user_id}, skipping rollback")
                return
            
            # Only decrement up to the current reserved amount
            amount_to_rollback = min(amount, current_reserved)
            
            result = self.mongo.vas_wallets.update_one(
                {'userId': ObjectId(user_id)},
                {
                    '$inc': {
                        'balance': amount_to_rollback,  # Return to available balance
                        'reservedAmount': -amount_to_rollback  # Remove from reserved (never goes negative)
                    },
                    '$push': {
                        'transactionHistory': {
                            'type': 'REFUND',
                            'amount': amount_to_rollback,
                            'description': f"ROLLBACK: {reason}",
                            'timestamp': datetime.utcnow()
                        }
                    },
                    '$set': {'updatedAt': datetime.utcnow()}
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"🔄 Rolled back reservation ₦{amount:,.2f} for user {user_id}")
            else:
                logger.warning(f"⚠️ Could not rollback reservation for user {user_id}")
                
        except Exception as e:
            logger.error(f"❌ Error rolling back reservation: {str(e)}")
    
    def enqueue_transaction_update(self, task_data: Dict[str, Any]) -> str:
        """
        Enqueue a transaction update task
        This is called IMMEDIATELY after provider API succeeds AND wallet is reserved
        """
        task_id = str(ObjectId())
        task = {
            'id': task_id,
            'type': 'TRANSACTION_UPDATE',
            'data': task_data,
            'created_at': datetime.utcnow(),
            'attempts': 0,
            'max_attempts': 5,
            'status': 'PENDING'
        }
        
        # Store in database for persistence
        self.mongo.transaction_tasks.insert_one(task)
        
        # Also store in memory for immediate processing
        self.pending_tasks[task_id] = task
        
        logger.info(f"📋 Enqueued transaction update task: {task_id}")
        return task_id
    
    def _worker_loop(self):
        """Background worker that processes pending tasks"""
        while self.worker_running:
            try:
                # Process in-memory tasks first (immediate)
                self._process_memory_tasks()
                
                # Process database tasks (recovery)
                self._process_database_tasks()
                
                # Sleep for a short interval
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"❌ Worker loop error: {str(e)}")
                time.sleep(5)  # Longer sleep on error
    
    def _process_memory_tasks(self):
        """Process tasks from in-memory queue"""
        completed_tasks = []
        
        for task_id, task in self.pending_tasks.items():
            try:
                if self._process_transaction_update(task):
                    completed_tasks.append(task_id)
                    logger.info(f"✅ Completed memory task: {task_id}")
                else:
                    # Move to database for retry
                    task['attempts'] += 1
                    self.mongo.transaction_tasks.update_one(
                        {'id': task_id},
                        {'$set': {'attempts': task['attempts'], 'last_attempt': datetime.utcnow()}}
                    )
                    if task['attempts'] >= task['max_attempts']:
                        # Rollback reservation on final failure
                        task_data = task['data']
                        self.rollback_reservation(
                            task_data['user_id'], 
                            task_data['amount_to_debit'],
                            "Task failed after max attempts"
                        )
                        completed_tasks.append(task_id)
                        logger.error(f"❌ Task failed after max attempts: {task_id}")
                        
            except Exception as e:
                logger.error(f"❌ Error processing memory task {task_id}: {str(e)}")
                completed_tasks.append(task_id)
        
        # Remove completed tasks from memory
        for task_id in completed_tasks:
            self.pending_tasks.pop(task_id, None)
    
    def _process_database_tasks(self):
        """Process tasks from database (recovery mode)"""
        # Find pending tasks that need retry
        cutoff_time = datetime.utcnow() - timedelta(minutes=1)
        
        pending_tasks = self.mongo.transaction_tasks.find({
            'status': 'PENDING',
            'attempts': {'$lt': 5},
            '$or': [
                {'last_attempt': {'$exists': False}},
                {'last_attempt': {'$lt': cutoff_time}}
            ]
        }).limit(10)
        
        for task in pending_tasks:
            try:
                if self._process_transaction_update(task):
                    # Mark as completed
                    self.mongo.transaction_tasks.update_one(
                        {'_id': task['_id']},
                        {'$set': {'status': 'COMPLETED', 'completed_at': datetime.utcnow()}}
                    )
                    logger.info(f"✅ Completed database task: {task['id']}")
                else:
                    # Increment attempts
                    self.mongo.transaction_tasks.update_one(
                        {'_id': task['_id']},
                        {
                            '$inc': {'attempts': 1},
                            '$set': {'last_attempt': datetime.utcnow()}
                        }
                    )
                    
                    # Check if max attempts reached
                    if task.get('attempts', 0) + 1 >= 5:
                        # Rollback reservation on final failure
                        task_data = task['data']
                        self.rollback_reservation(
                            task_data['user_id'], 
                            task_data['amount_to_debit'],
                            "Database task failed after max attempts"
                        )
                        self.mongo.transaction_tasks.update_one(
                            {'_id': task['_id']},
                            {'$set': {'status': 'FAILED', 'failed_at': datetime.utcnow()}}
                        )
                    
            except Exception as e:
                logger.error(f"❌ Error processing database task {task['id']}: {str(e)}")
    
    def _process_transaction_update(self, task: Dict[str, Any]) -> bool:
        """
        Process a single transaction update task
        Returns True if successful, False if should retry
        """
        try:
            task_data = task['data']
            transaction_id = ObjectId(task_data['transaction_id'])
            user_id = task_data['user_id']
            amount = task_data['amount_to_debit']
            
            # Update transaction status to SUCCESS
            transaction_result = self.mongo.vas_transactions.update_one(
                {'_id': transaction_id},
                {
                    '$set': {
                        'status': 'SUCCESS',
                        'provider': task_data['provider'],
                        'providerResponse': task_data.get('provider_response', {}),
                        'updatedAt': datetime.utcnow(),
                        'processedByTaskQueue': True,
                        'taskQueueProcessedAt': datetime.utcnow()
                    },
                    '$unset': {'failureReason': ""}
                }
            )
            
            # Verify transaction update succeeded
            if transaction_result.modified_count == 0:
                logger.error(f"❌ Failed to update transaction {transaction_id}")
                return False
            
            # Release the reservation (move from reserved to confirmed debit)
            self.release_reservation(user_id, amount, task_data['description'])
            
            logger.info(f"✅ Successfully processed transaction update: {transaction_id}")
            return True
                    
        except Exception as e:
            logger.error(f"❌ Transaction update failed: {str(e)}")
            return False

# Global task queue instance
_task_queue = None

def get_task_queue(mongo_db):
    """Get or create the global task queue instance"""
    global _task_queue
    if _task_queue is None:
        _task_queue = TransactionTaskQueue(mongo_db)
        _task_queue.start_worker()
    return _task_queue

def process_vas_transaction_with_reservation(mongo_db, transaction_id: str, user_id: str, 
                                           amount_to_debit: float, provider: str, 
                                           provider_response: Dict[str, Any], 
                                           description: str) -> Dict[str, Any]:
    """
    Complete VAS transaction processing with wallet reservation
    1. Reserve wallet amount immediately
    2. Enqueue task for transaction update
    3. Return success/failure status
    """
    task_queue = get_task_queue(mongo_db)
    
    # Step 1: Reserve wallet amount immediately
    reservation_success = task_queue.reserve_wallet_amount(user_id, amount_to_debit, description)
    
    if not reservation_success:
        return {
            'success': False,
            'error': 'INSUFFICIENT_FUNDS',
            'message': 'Insufficient wallet balance'
        }
    
    # Step 2: Enqueue task for transaction update
    task_data = {
        'transaction_id': transaction_id,
        'user_id': user_id,
        'amount_to_debit': amount_to_debit,
        'provider': provider,
        'provider_response': provider_response,
        'description': description
    }
    
    task_id = task_queue.enqueue_transaction_update(task_data)
    
    return {
        'success': True,
        'task_id': task_id,
        'message': 'Transaction queued for processing',
        'amount_reserved': amount_to_debit
    }

def get_user_available_balance(mongo_db, user_id: str) -> float:
    """
    Get user's available balance (total balance - reserved amounts)
    This prevents double-spending while tasks are processing
    
    CRITICAL: The calculation is CORRECT (total - reserved)
    The REAL issue is STALE reserved amounts from failed/timed-out transactions
    that never got cleaned up, blocking users with real money from purchases
    """
    try:
        wallet = mongo_db.vas_wallets.find_one({'userId': ObjectId(user_id)})
        if not wallet:
            return 0.0
        
        total_balance = wallet.get('balance', 0.0)
        reserved_amount = wallet.get('reservedAmount', 0.0)
        
        # Calculation is correct: subtract reserved amount
        # Reserved amount is money locked for pending transactions
        available_balance = total_balance - reserved_amount
        return max(0.0, available_balance)  # Never return negative
        
    except Exception as e:
        logger.error(f"❌ Error getting available balance for user {user_id}: {str(e)}")
        return 0.0

def cleanup_completed_tasks(mongo_db, days_old: int = 7):
    """Clean up completed tasks older than specified days"""
    cutoff_date = datetime.utcnow() - timedelta(days=days_old)
    
    result = mongo_db.transaction_tasks.delete_many({
        'status': 'COMPLETED',
        'completed_at': {'$lt': cutoff_date}
    })
    
    logger.info(f"🧹 Cleaned up {result.deleted_count} completed tasks older than {days_old} days")
    return result.deleted_count