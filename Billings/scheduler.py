import logging
import sys
from django.core.management import call_command
from django_apscheduler.jobstores import DjangoJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.pool import ThreadPoolExecutor
import atexit

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler = None

def get_scheduler():
    """Get or create scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone='Africa/Lagos')
        _scheduler.add_jobstore(DjangoJobStore(), 'default')
        
        # Configure executor
        _scheduler.configure(
            executors={
                'default': ThreadPoolExecutor(1)
            },
            job_defaults={
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 3600
            }
        )
    
    return _scheduler

def start_scheduler():
    """Start the scheduler with a delayed initialization"""
    try:
        # Don't start scheduler during migrations or shell
        if 'migrate' in sys.argv or 'makemigrations' in sys.argv or 'shell' in sys.argv:
            logger.info("Skipping scheduler start during migrations/shell")
            return
        
        # Check if tables exist before starting
        from django.db import connection
        from django_apscheduler.models import DjangoJob
        
        cursor = connection.cursor()
        cursor.execute("SHOW TABLES LIKE 'django_apscheduler_djangojob'")
        if not cursor.fetchone():
            logger.warning("APScheduler tables not found. Run 'python manage.py migrate django_apscheduler'")
            return
            
    except Exception as e:
        logger.warning(f"Could not check APScheduler tables: {e}")
        return
    
    scheduler = get_scheduler()
    
    # Add job only if not already scheduled
    try:
        existing_job = scheduler.get_job('send_daily_day_book')
        if not existing_job:
            scheduler.add_job(
                send_daily_day_book_job,
                trigger=CronTrigger(hour=23, minute=0, timezone='Africa/Lagos'),
                id='send_daily_day_book',
                replace_existing=True,
                name='Send Daily Day Book Report to CMD'
            )
            logger.info("Daily day book job added to scheduler")
    except Exception as e:
        logger.error(f"Error adding job to scheduler: {e}")
        return
    
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started successfully")
        
        # Register shutdown handler
        atexit.register(lambda: shutdown_scheduler())

def shutdown_scheduler():
    """Shutdown the scheduler gracefully"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Scheduler shutdown")

def send_daily_day_book_job():
    """Wrapper function to call the management command"""
    try:
        logger.info("Starting daily day book report generation...")
        call_command('send_daily_day_book')
        logger.info("Daily day book report completed successfully")
    except Exception as e:
        logger.error(f"Failed to send daily day book report: {str(e)}", exc_info=True)