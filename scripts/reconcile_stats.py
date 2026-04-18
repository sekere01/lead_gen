#!/home/fisazkido/lead_gen2/04_api/venv/bin/python
"""
job_stats reconciliation script.
Recalculates all job_stats counts from source tables and upserts them.
Run via: python scripts/reconcile_stats.py
Or via cron: 0 3 * * * cd /home/fisazkido/lead_gen2 && python scripts/reconcile_stats.py
"""
import sys
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(SCRIPT_DIR, '..', '04_api', '.env'))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/leadgen")

engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})
SessionLocal = sessionmaker(bind=engine)


def reconcile():
    db = SessionLocal()
    try:
        print("Starting job_stats reconciliation...")

        reconciliation_rules = [
            {
                'job_type': 'discovery',
                'source_table': 'discovery_jobs',
                'status_column': 'status',
            },
            {
                'job_type': 'browsing',
                'source_table': 'companies',
                'status_column': 'status',
                'valid_statuses': ['discovered', 'browsing', 'browsed', 'enriching', 'enriched', 'verified', 'failed'],
            },
            {
                'job_type': 'enrichment',
                'source_table': 'companies',
                'status_column': 'status',
                'valid_statuses': ['browsed', 'enriching', 'enriched', 'verified', 'failed'],
            },
            {
                'job_type': 'verification',
                'source_table': 'contacts',
                'status_column': 'verification_status',
            },
        ]

        for rule in reconciliation_rules:
            job_type = rule['job_type']
            source_table = rule['source_table']
            status_column = rule['status_column']

            query = text(f"""
                SELECT {status_column}, COUNT(*) as cnt
                FROM {source_table}
                GROUP BY {status_column}
            """)
            results = db.execute(query).fetchall()

            for status, count in results:
                if status is None:
                    continue

                db.execute(
                    text("""
                        INSERT INTO job_stats (job_type, status, count, updated_at)
                        VALUES (:job_type, :status, :count, NOW())
                        ON CONFLICT (job_type, status)
                        DO UPDATE SET
                            count = :count,
                            updated_at = NOW()
                    """),
                    {'job_type': job_type, 'status': status, 'count': count}
                )

            existing_counts = {r[0]: r[1] for r in results}
            print(f"  {job_type}: {existing_counts}")

        db.commit()
        print("Reconciliation complete.")

    finally:
        db.close()


if __name__ == "__main__":
    reconcile()