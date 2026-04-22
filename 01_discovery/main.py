"""
Discovery Service - Main entry point.
Polls DiscoveryJob for status='pending', discovers domains, calculates scores.
Entry: python main.py
"""
import time
import logging
import traceback
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from database import SessionLocal, init_db, DiscoveryJob, Company
from shared_models import update_job_stats
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import text
from config import settings

from services.search_orchestration import search_domains
from services.commoncrawl import discover_commoncrawl
from services.regional_scoring import get_global_region_score, maybe_reload_config, get_config_summary

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | discoverer | %(message)s'
)
logger = logging.getLogger("discoverer")

POLL_INTERVAL = settings.DISCOVERY_POLL_INTERVAL
MAX_JOB_RETRIES = settings.MAX_JOB_RETRIES

HEARTBEAT_INTERVAL = 10
BATCH_SIZE = 25
WATCHDOG_TIMEOUT_MINUTES = 30


def update_heartbeat(job, db) -> None:
    """Update job heartbeat timestamp."""
    job.last_heartbeat = datetime.now()
    db.commit()


def discover_domains_isolated(keyword: str, region: str = "") -> Dict[str, Any]:
    """
    Discovery with source isolation - each source runs independently.
    Returns dict with 'domains', 'sources_succeeded', 'sources_failed'.
    """
    result = {
        'domains': [],
        'sources_succeeded': [],
        'sources_failed': [],
    }

    logger.info(f"Starting isolated discovery for keyword: '{keyword}', region: '{region}'")

    # Source 1: DuckDuckGo + SearXNG (search_orchestration)
    try:
        search_results = search_domains(keyword, num_results=0, region=region)
        logger.info(f"Search found {len(search_results)} domains")
        if search_results:
            result['domains'].extend(search_results)
            result['sources_succeeded'].append('search')
    except Exception as e:
        logger.warning(f"Search failed for '{keyword}': {e}")
        result['sources_failed'].append('search')

    # Source 2: CommonCrawl (independent try/except)
    try:
        cc_results = discover_commoncrawl(keyword, region=region, max_results=500)
        logger.info(f"CommonCrawl found {len(cc_results)} domains")
        for cc in cc_results:
            cc_domain = cc.get('domain', '')
            if cc_domain and cc_domain not in result['domains']:
                result['domains'].append(cc_domain)
        if cc_results:
            result['sources_succeeded'].append('commoncrawl')
    except Exception as e:
        logger.warning(f"CommonCrawl failed for '{keyword}': {e}")
        result['sources_failed'].append('commoncrawl')

    result['domains'] = list(set(result['domains']))
    logger.info(f"Total unique domains: {len(result['domains'])}")
    logger.info(f"Sources succeeded: {result['sources_succeeded']}, failed: {result['sources_failed']}")

    return result


def save_batch_incremental(job_id: int, batch: List[Dict[str, Any]], db) -> int:
    """Save a batch of companies to DB. Returns count of saved companies."""
    if not batch:
        return 0

    saved_count = 0
    try:
        stmt = insert(Company).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=['domain'],
            set_={
                'discovery_score': stmt.excluded.discovery_score,
                'lead_source': stmt.excluded.lead_source,
                'status': stmt.excluded.status,
                'is_active': stmt.excluded.is_active
            }
        )
        result = db.execute(stmt)
        saved_count = result.rowcount
        db.commit()
        logger.info(f"Batch upsert completed: {saved_count} companies processed")
    except Exception as e:
        logger.error(f"Batch upsert failed: {e}")
        for company_data in batch:
            try:
                existing = db.query(Company).filter(Company.domain == company_data['domain']).first()
                if not existing:
                    company = Company(**company_data)
                    db.add(company)
                    saved_count += 1
                elif company_data.get('discovery_score'):
                    new_score = company_data['discovery_score']
                    if new_score > (existing.discovery_score or 0):
                        existing.discovery_score = new_score
                        saved_count += 1
            except Exception as ex:
                logger.error(f"Error saving {company_data['domain']}: {ex}")
                continue
        db.commit()

    return saved_count


def process_job(job, db) -> bool:
    """Process a single discovery job with heartbeat and incremental saves."""
    job.status = 'processing'
    job.last_run = datetime.now()
    job.last_heartbeat = datetime.now()
    db.commit()

    saved_count = 0
    last_heartbeat_time = time.time()

    try:
        discovery_result = discover_domains_isolated(job.keyword, job.region)
        domains = discovery_result['domains']
        sources_succeeded = discovery_result['sources_succeeded']

        # Check graceful degradation: all sources failed
        if not sources_succeeded and not domains:
            job.status = 'completed'
            job.results_count = 0
            job.error_message = 'All sources failed - no domains found'
            job.retry_count = 0
            job.last_error = None
            db.commit()
            logger.warning(f"Job {job.id}: All sources failed for '{job.keyword}'")
            return True

        if not domains:
            job.status = 'completed'
            job.results_count = 0
            job.error_message = 'No domains found'
            job.retry_count = 0
            db.commit()
            logger.warning(f"Job {job.id}: No domains found for '{job.keyword}'")
            return True

        # Process domains and save incrementally every BATCH_SIZE
        current_batch = []
        for domain in domains:
            try:
                score = get_global_region_score(domain, job.region) if job.region else 0
                current_batch.append({
                    'name': domain.lower(),
                    'domain': domain.lower(),
                    'discovery_score': score,
                    'lead_source': 'discoverer',
                    'status': 'discovered',
                    'is_active': True
                })

                # Save batch when full
                if len(current_batch) >= BATCH_SIZE:
                    saved_count += save_batch_incremental(job.id, current_batch, db)
                    current_batch = []

                # Update heartbeat every HEARTBEAT_INTERVAL seconds
                if time.time() - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                    update_heartbeat(job, db)
                    last_heartbeat_time = time.time()

            except Exception as e:
                logger.error(f"Error preparing domain {domain}: {e}")
                continue

        # Save remaining batch
        if current_batch:
            saved_count += save_batch_incremental(job.id, current_batch, db)

        # Final heartbeat update
        update_heartbeat(job, db)

        job.status = 'completed'
        job.results_count = saved_count
        job.error_message = None
        job.retry_count = 0
        job.last_error = None
        db.commit()

        
        update_job_stats(db, 'discovery', 'processing', -1, job.id)
        update_job_stats(db, 'discovery', 'completed', 1, job.id)

        logger.info(f"Job {job.id} completed: {saved_count} companies saved")
        return True

    except Exception as e:
        current_retry = (job.retry_count or 0) + 1
        job.retry_count = current_retry
        job.last_error = traceback.format_exc()

        
        if current_retry >= MAX_JOB_RETRIES:
            job.status = 'failed'
            job.error_message = f"Max retries ({MAX_JOB_RETRIES}) exceeded: {str(e)[:450]}"
            logger.error(f"Job {job.id} permanently failed after {current_retry} attempts: {e}")
            update_job_stats(db, 'discovery', 'processing', -1, job.id)
            update_job_stats(db, 'discovery', 'failed', 1, job.id)
        else:
            job.status = 'pending'
            job.error_message = f"Attempt {current_retry}/{MAX_JOB_RETRIES} failed: {str(e)[:450]}"
            logger.warning(f"Job {job.id} failed (attempt {current_retry}/{MAX_JOB_RETRIES}): {e}")
            update_job_stats(db, 'discovery', 'processing', -1, job.id)
            update_job_stats(db, 'discovery', 'pending', 1, job.id)

        db.commit()
        return False


def watchdog_reset_stuck_jobs(db) -> int:
    """
    Watchdog: Reset jobs stuck in 'processing' for too long.
    Checks both last_heartbeat and last_run for safety.
    Returns count of reset jobs.
    """
    cutoff_time = datetime.now() - timedelta(minutes=WATCHDOG_TIMEOUT_MINUTES)

    stuck_jobs = db.query(DiscoveryJob).filter(
        DiscoveryJob.status == 'processing',
        (DiscoveryJob.last_heartbeat < cutoff_time) | (DiscoveryJob.last_run < cutoff_time)
    ).all()

    reset_count = 0
    
    for job in stuck_jobs:
        old_retry = job.retry_count or 0
        job.retry_count = old_retry + 1

        if job.retry_count >= MAX_JOB_RETRIES:
            job.status = 'failed'
            job.error_message = f"Watchdog: stuck for >{WATCHDOG_TIMEOUT_MINUTES}min, max retries exceeded"
            logger.error(f"Job {job.id} permanently failed: watchdog timeout after {job.retry_count} retries")
            update_job_stats(db, 'discovery', 'processing', -1, job.id)
            update_job_stats(db, 'discovery', 'failed', 1, job.id)
        else:
            job.status = 'pending'
            job.error_message = f"Watchdog: stuck for >{WATCHDOG_TIMEOUT_MINUTES}min, reset to pending"
            logger.warning(f"Job {job.id} reset by watchdog: was stuck, retry {job.retry_count}/{MAX_JOB_RETRIES}")
            update_job_stats(db, 'discovery', 'processing', -1, job.id)
            update_job_stats(db, 'discovery', 'pending', 1, job.id)

        reset_count += 1

    if reset_count > 0:
        db.commit()
        logger.info(f"Watchdog reset {reset_count} stuck jobs")

    return reset_count


def write_metrics(db):
    """Write service metrics for graphing via API."""
    try:
        from database import Company, DiscoveryJob
        
        # Get current stats
        companies_found = db.query(Company).count()
        jobs_pending = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'pending').count()
        jobs_active = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'processing').count()
        
        # Write metrics via API call
        import httpx
        api_base = os.getenv('API_BASE', 'http://localhost:8000/api/v1')
        
        metrics = [
            ('discovery', 'companies_found', companies_found),
            ('discovery', 'jobs_pending', jobs_pending),
            ('discovery', 'jobs_active', jobs_active),
        ]
        
        for svc, metric, value in metrics:
            try:
                httpx.post(
                    f"{api_base}/dashboard/metrics",
                    json={"service": svc, "metric": metric, "value": value},
                    timeout=5.0,
                )
            except Exception as e:
                logger.debug(f"Failed to write metric {metric}: {e}")
                
    except Exception as e:
        logger.warning(f"Failed to write metrics: {e}")


def run_discoverer():
    """Main watcher loop."""
    logger.info(f"Discoverer service started (poll interval: {POLL_INTERVAL}s, max retries: {MAX_JOB_RETRIES}, watchdog timeout: {WATCHDOG_TIMEOUT_MINUTES}min)")
    logger.info(f"Loaded config: {get_config_summary()}")
    
    metrics_counter = 0
    
    while True:
        db = SessionLocal()
        try:
            # Check for config file changes and reload if needed
            maybe_reload_config()
            
            # Watchdog: reset stuck jobs before picking new job
            watchdog_reset_stuck_jobs(db)
            
            job = db.query(DiscoveryJob).filter(
                DiscoveryJob.status == 'pending',
                DiscoveryJob.retry_count < MAX_JOB_RETRIES
            ).with_for_update(skip_locked=True).first()

            if job:
                logger.info(f"Found pending job: {job.id} - '{job.keyword}' (attempt {job.retry_count + 1}/{MAX_JOB_RETRIES})")
                
                update_job_stats(db, 'discovery', 'pending', -1, job.id)
                job.status = 'processing'
                job.last_run = datetime.now()
                job.last_heartbeat = datetime.now()
                db.commit()
                update_job_stats(db, 'discovery', 'processing', 1, job.id)
                process_job(job, db)
            else:
                logger.debug("No pending jobs, waiting...")

            # Write metrics every 60 seconds
            metrics_counter += POLL_INTERVAL
            if metrics_counter >= 60:
                write_metrics(db)
                metrics_counter = 0

            time.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.error(f"Discoverer error: {e}")
            time.sleep(POLL_INTERVAL)
        finally:
            db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Discovery Service Starting...")
    print("=" * 50)
    print(f"Loaded config: {get_config_summary()}")
    print("=" * 50)
    init_db()
    run_discoverer()