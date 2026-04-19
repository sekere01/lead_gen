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

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=1, max_overflow=1)
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

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=1, max_overflow=1)
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

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=1, max_overflow=1)
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

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=1, max_overflow=1)
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

    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=1, max_overflow=1)
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
    from shared_models import ServiceMetrics, Company, Contact, DiscoveryJob
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import timedelta
    
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        return {"error": "DATABASE_URL not set"}
    
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=1, max_overflow=1)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        timestamp = datetime.now(timezone.utc)
        
        # Get current counts
        companies_total = db.query(Company).count()
        contacts_total = db.query(Contact).count()
        verified_count = db.query(Contact).filter(Contact.verification_status == 'valid_verified').count()
        jobs_pending = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'pending').count()
        jobs_completed = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'completed').count()
        jobs_failed = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'failed').count()
        
        # Browse service metrics
        pages_browsed = db.query(Company).filter(Company.status == 'browsed').count()
        contacts_found = db.query(Contact).filter(Contact.source_url.like('%browse%')).count()
        
        # Enrichment service metrics
        emails_collected = db.query(Contact).filter(
            Contact.first_name.isnot(None),
            Contact.email.isnot(None)
        ).count()
        domains_processed = db.query(Company).filter(Company.status == 'enriched').count()
        
        # Metrics to record
        metrics_data = [
            # Discovery metrics
            ('discovery', 'companies_total', companies_total),
            ('discovery', 'jobs_pending', jobs_pending),
            ('discovery', 'jobs_completed', jobs_completed),
            ('discovery', 'jobs_failed', jobs_failed),
            # Browsing metrics
            ('browsing', 'pages_browsed', pages_browsed),
            ('browsing', 'contacts_found', contacts_found),
            # Enrichment metrics  
            ('enrichment', 'emails_collected', emails_collected),
            ('enrichment', 'domains_processed', domains_processed),
            # Verification metrics
            ('verification', 'contacts_total', contacts_total),
            ('verification', 'verified_count', verified_count),
        ]
        
        for service, metric, value in metrics_data:
            record = ServiceMetrics(
                service=service,
                metric=metric,
                value=value,
                recorded_at=timestamp
            )
            db.add(record)
        
        db.commit()
        
        # Clean up old data (> 24 hours)
        cutoff = timestamp - timedelta(hours=24)
        deleted = db.query(ServiceMetrics).filter(
            ServiceMetrics.recorded_at < cutoff
        ).delete()
        if deleted:
            db.commit()
        
        return {"recorded": len(metrics_data), "cleaned_up": deleted}
    
    except Exception as e:
        logger.error(f"Error collecting metrics: {e}")
        return {"error": str(e)}
    finally:
        db.close()


from datetime import datetime, timezone