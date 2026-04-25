"""
Celery tasks for lead generation pipeline.
Each task picks up work from the database and enqueues the next stage.
"""
from celery_tasks import celery_app
import sys
import os
import logging

logger = logging.getLogger(__name__)

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@celery_app.task(bind=True, name="celery_tasks.tasks.process_discovery_job")
def process_discovery_job(self, job_id: int):
    """
    Process a single discovery job.
    Picks up job from database, searches for domains, enqueues browsing for discovered companies.
    """
    from shared_models import update_job_stats
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from shared_models import DiscoveryJob, Company

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set")
        return {"error": "DATABASE_URL not set"}

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_timeout=10)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        job = db.query(DiscoveryJob).filter(DiscoveryJob.id == job_id).first()
        if not job:
            return {"error": f"Job {job_id} not found"}

        job.status = "processing"
        job.last_run = datetime.now(timezone.utc)
        db.commit()
        update_job_stats(db, "discovery", "processing", 1, job.id)
        update_job_stats(db, "discovery", "pending", -1, job.id)

        # Run discovery (placeholder - actual implementation would call search_orchestration)
        logger.info(f"Processing discovery job {job_id}: {job.keyword}")

        # Simulate domain discovery
        domains = []  # Would be populated by actual search

        for domain in domains:
            existing = db.query(Company).filter(Company.domain == domain).first()
            if not existing:
                company = Company(
                    name=domain.split(".")[0].capitalize(),
                    domain=domain,
                    status="discovered",
                    lead_source=f"discovery_job_{job_id}",
                )
                db.add(company)
                update_job_stats(db, "browsing", "pending", 1, company.id)

        job.status = "completed"
        job.results_count = len(domains)
        db.commit()
        update_job_stats(db, "discovery", "processing", -1, job.id)
        update_job_stats(db, "discovery", "completed", 1, job.id)

        return {"job_id": job_id, "domains_found": len(domains)}

    except Exception as e:
        logger.error(f"Error processing discovery job {job_id}: {e}")
        job = db.query(DiscoveryJob).filter(DiscoveryJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)[:500]
            db.commit()
            update_job_stats(db, "discovery", "processing", -1, job.id)
            update_job_stats(db, "discovery", "failed", 1, job.id)
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True, name="celery_tasks.tasks.process_browsing")
def process_browsing(self, company_id: int):
    """
    Process a single company for browsing signals.
    Extracts contact links, addresses, social links, and emails.
    """
    import httpx
    from shared_models import update_job_stats, Company, Contact
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime, timezone

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        return {"error": "DATABASE_URL not set"}

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_timeout=10)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            return {"error": f"Company {company_id} not found"}

        company.status = "browsing"
        company.browse_heartbeat = datetime.now(timezone.utc)
        db.commit()
        update_job_stats(db, "browsing", "processing", 1, company.id)
        update_job_stats(db, "browsing", "pending", -1, company.id)

        # Browse homepage (placeholder - actual implementation uses Playwright)
        html = ""  # Would be populated by actual browse

        # Extract signals (placeholder)
        signals = {}

        company.has_contact_link = signals.get("has_contact_link", False)
        company.has_address = signals.get("has_address", False)
        company.has_social_links = signals.get("has_social_links", False)
        company.has_email_on_homepage = signals.get("has_email", False)
        company.status = "browsed"
        company.browse_heartbeat = None
        db.commit()
        update_job_stats(db, "browsing", "processing", -1, company.id)
        update_job_stats(db, "browsing", "completed", 1, company.id)

        return {"company_id": company_id, "signals": signals}

    except Exception as e:
        logger.error(f"Error browsing company {company_id}: {e}")
        company = db.query(Company).filter(Company.id == company_id).first()
        if company:
            company.status = "failed"
            company.failure_reason = str(e)[:500]
            db.commit()
            update_job_stats(db, "browsing", "processing", -1, company.id)
            update_job_stats(db, "browsing", "failed", 1, company.id)
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True, name="celery_tasks.tasks.process_enrichment")
def process_enrichment(self, company_id: int):
    """
    Enrich company with emails from theHarvester and explicit page scans.
    """
    from shared_models import update_job_stats, Company, Contact, ExtractedEmail
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime, timezone

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        return {"error": "DATABASE_URL not set"}

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_timeout=10)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            return {"error": f"Company {company_id} not found"}

        company.status = "enriching"
        db.commit()
        update_job_stats(db, "enrichment", "processing", 1, company.id)
        update_job_stats(db, "enrichment", "pending", -1, company.id)

        # Enrich emails (placeholder - actual implementation uses theHarvester)
        emails = []

        for email_data in emails:
            contact = Contact(
                first_name=email_data.get("first_name", "Unknown"),
                last_name=email_data.get("last_name", "Unknown"),
                email=email_data["email"],
                company_id=company_id,
                verification_status="pending",
                is_verified=False,
                source_url=email_data.get("source_url", ""),
            )
            db.add(contact)

            extracted = ExtractedEmail(
                email=email_data["email"],
                email_type=email_data.get("type", "enrichment"),
                source_url=email_data.get("source_url", ""),
                company_id=company_id,
            )
            db.add(extracted)

        company.status = "enriched"
        db.commit()
        update_job_stats(db, "enrichment", "processing", -1, company.id)
        update_job_stats(db, "enrichment", "completed", 1, company.id)

        return {"company_id": company_id, "emails_found": len(emails)}

    except Exception as e:
        logger.error(f"Error enriching company {company_id}: {e}")
        company = db.query(Company).filter(Company.id == company_id).first()
        if company:
            company.status = "failed"
            company.failure_reason = str(e)[:500]
            db.commit()
            update_job_stats(db, "enrichment", "processing", -1, company.id)
            update_job_stats(db, "enrichment", "failed", 1, company.id)
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True, name="celery_tasks.tasks.process_verification")
def process_verification(self, contact_id: int):
    """
    Verify a contact's email via syntax, MX, and SMTP checks.
    """
    from shared_models import update_job_stats, Contact
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        return {"error": "DATABASE_URL not set"}

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_timeout=10)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            return {"error": f"Contact {contact_id} not found"}

        update_job_stats(db, "verification", "processing", 1, contact.id)
        update_job_stats(db, "verification", "pending", -1, contact.id)

        # Verify email (placeholder - actual implementation uses verification.py)
        result = {"is_verified": False, "verification_status": "invalid_syntax"}

        contact.is_verified = result.get("is_verified", False)
        contact.verification_status = result.get("verification_status", "unknown")

        db.commit()
        update_job_stats(db, "verification", "processing", -1, contact.id)
        update_job_stats(db, "verification", "completed" if contact.is_verified else "failed", 1, contact.id)

        return {"contact_id": contact_id, "verified": contact.is_verified}

    except Exception as e:
        logger.error(f"Error verifying contact {contact_id}: {e}")
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if contact:
            contact.verification_status = "failed"
            db.commit()
            update_job_stats(db, "verification", "processing", -1, contact.id)
            update_job_stats(db, "verification", "failed", 1, contact.id)
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="celery_tasks.tasks.enqueue_discovery_jobs")
def enqueue_discovery_jobs():
    """
    Periodic task that scans for pending discovery jobs and enqueues them.
    This replaces the while True polling loop.
    """
    from shared_models import DiscoveryJob, update_job_stats
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        return {"error": "DATABASE_URL not set"}

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_timeout=10)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        pending_jobs = (
            db.query(DiscoveryJob)
            .filter(DiscoveryJob.status == "pending", DiscoveryJob.retry_count < 3)
            .limit(10)
            .all()
        )

        enqueued = 0
        for job in pending_jobs:
            job.status = "queued"
            db.commit()
            process_discovery_job.delay(job.id)
            enqueued += 1

        return {"enqueued": enqueued, "pending": len(pending_jobs)}

    finally:
        db.close()


@celery_app.task(bind=True, name="celery_tasks.tasks.collect_metrics")
def collect_metrics(self):
    """
    Periodic task that collects service metrics every 30 seconds.
    Stores current counts in ServiceMetrics table for the dashboard chart.
    """
    import logging
    from sqlalchemy import func
    from shared_models import ServiceMetrics, Company, Contact, DiscoveryJob
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import timedelta

    logger = logging.getLogger(__name__)

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        return {"error": "DATABASE_URL not set"}

    RETENTION_HOURS = int(os.getenv("METRICS_RETENTION_HOURS", "24"))

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_timeout=10)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        timestamp = datetime.now(timezone.utc)

        # Fix 1: Single grouped query for company status counts (was 5 queries)
        company_counts = dict(
            db.query(Company.status, func.count(Company.id))
            .group_by(Company.status)
            .all()
        )

        # Single grouped query for contact verification status counts (was 2 queries)
        contact_counts = dict(
            db.query(Contact.verification_status, func.count(Contact.id))
            .group_by(Contact.verification_status)
            .all()
        )

        # Single grouped query for job status counts (was 3 queries)
        job_counts = dict(
            db.query(DiscoveryJob.status, func.count(DiscoveryJob.id))
            .group_by(DiscoveryJob.status)
            .all()
        )

        # Extract values from grouped counts
        companies_total = sum(company_counts.values())
        pages_browsed = company_counts.get('browsed', 0)
        domains_processed = company_counts.get('enriched', 0)
        enrich_requeued = company_counts.get('enrich_requeued', 0)

        contacts_total = sum(contact_counts.values())
        verified_count = contact_counts.get('valid_verified', 0)
        invalid_count = contact_counts.get('invalid_syntax', 0) + contact_counts.get('no_mx_records', 0)
        pending_count = contact_counts.get('pending', 0)

        jobs_pending = job_counts.get('pending', 0)
        jobs_completed = job_counts.get('completed', 0)
        jobs_failed = job_counts.get('failed', 0)

        # Final metrics list
        # Note: 'failed' status (domain_failed) is shared across all services - companies
        # marked failed by any stage will show up here. This represents total pipeline failures.
        metrics_to_write = [
            # Discovery metrics
            ('discovery', 'companies_total', companies_total),
            ('discovery', 'jobs_pending', jobs_pending),
            ('discovery', 'jobs_completed', jobs_completed),
            ('discovery', 'jobs_failed', jobs_failed),
            # Browsing metrics
            ('browsing', 'pages_browsed', pages_browsed),
            ('browsing', 'domain_browsed', company_counts.get('browsing', 0)),
            ('browsing', 'domain_failed', company_counts.get('failed', 0)),
            # Enrichment metrics
            ('enrichment', 'emails_collected', contacts_total),
            ('enrichment', 'domains_processed', domains_processed),
            ('enrichment', 'enrich_requeued', enrich_requeued),
            # Verification metrics
            ('verification', 'contacts_total', contacts_total),
            ('verification', 'verified_count', verified_count),
            ('verification', 'invalid_count', invalid_count),
            ('verification', 'pending_count', pending_count),
        ]

        # Fix 4: Wrap each write in try/except
        for service, metric, value in metrics_to_write:
            try:
                record = ServiceMetrics(
                    service=service,
                    metric=metric,
                    value=value,
                    recorded_at=timestamp
                )
                db.add(record)
            except Exception as e:
                logger.warning(f"Failed to write metric {service}.{metric}: {e}")

        db.commit()

        # Fix 5: Configurable cleanup window
        cutoff = timestamp - timedelta(hours=RETENTION_HOURS)
        deleted = db.query(ServiceMetrics).filter(
            ServiceMetrics.recorded_at < cutoff
        ).delete()
        if deleted:
            db.commit()

        return {"recorded": len(metrics_to_write), "cleaned_up": deleted}

    except Exception as e:
        logger.error(f"Error collecting metrics: {e}")
        return {"error": str(e)}
    finally:
        db.close()


from datetime import datetime, timezone