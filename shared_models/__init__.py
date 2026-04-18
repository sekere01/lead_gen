"""Shared ORM models — single source of truth for all services."""
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

from shared_models.company import Company
from shared_models.contact import Contact, ExtractedEmail
from shared_models.job_stats import JobStats, update_job_stats
from shared_models.discovery_job import DiscoveryJob
from shared_models.job_template import JobTemplate
from shared_models.service_metrics import ServiceMetrics

__all__ = [
    'Base',
    'Company',
    'Contact',
    'ExtractedEmail',
    'JobStats',
    'update_job_stats',
    'DiscoveryJob',
    'JobTemplate',
    'ServiceMetrics',
]