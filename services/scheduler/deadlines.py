"""Deadline tracking for the GRO 30-day response window and the Ombudsman
1-year filing window (IMPLEMENTATION_PLAN.md section 5/8).

This is a standalone worker, not something the FastAPI gateway runs inline --
run it as its own process:

    python -m services.scheduler.deadlines

Notification is a log line for now -- there's no WhatsApp/email/SMS channel
wired up yet (WhatsApp intake itself isn't built either). This is the hook
point: swap the `logger.warning` in check_due_reminders() for a real send once
one of those channels exists. Deliberately NOT using Celery/RQ -- a single
polling loop against a few hundred rows is plenty for this volume, and adding
a task-queue dependency before there's a reason to isn't worth the complexity.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from services.gateway.db import get_connection

logger = logging.getLogger("claimsaathi.scheduler")

GRO_RESPONSE_WINDOW_DAYS = 30
OMBUDSMAN_FILING_WINDOW_DAYS = 365


def schedule_gro_deadline(case_id: str) -> None:
    due_at = datetime.now(timezone.utc) + timedelta(days=GRO_RESPONSE_WINDOW_DAYS)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO deadlines (case_id, type, due_at) VALUES (%s, 'gro_30_day', %s)",
                (case_id, due_at),
            )
        conn.commit()


def schedule_ombudsman_deadline(case_id: str, rejection_date_iso: str) -> None:
    """The 1-year Ombudsman filing clock runs from the rejection date, not from
    whenever the GRO letter happened to be drafted -- Insurance Ombudsman Rules
    2017 (IMPLEMENTATION_PLAN.md section 2)."""
    rejection_date = datetime.fromisoformat(rejection_date_iso).replace(tzinfo=timezone.utc)
    due_at = rejection_date + timedelta(days=OMBUDSMAN_FILING_WINDOW_DAYS)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO deadlines (case_id, type, due_at) VALUES (%s, 'ombudsman_1_year', %s)",
                (case_id, due_at),
            )
        conn.commit()


def check_due_reminders() -> list[dict]:
    """Find deadlines that are due and haven't been reminded about yet, mark
    them reminded, and return them for the caller to notify on."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, case_id, type, due_at
                FROM deadlines
                WHERE due_at <= now() AND reminded_at IS NULL AND status = 'pending'
                ORDER BY due_at ASC
                """
            )
            due = cur.fetchall()
            for row in due:
                cur.execute("UPDATE deadlines SET reminded_at = now() WHERE id = %s", (row["id"],))
        conn.commit()
    for row in due:
        logger.warning("DEADLINE DUE: case %s, type=%s, was due %s", row["case_id"], row["type"], row["due_at"])
    return [dict(r) for r in due]


def run_scheduler_loop(interval_seconds: int = 3600) -> None:
    logger.info("Deadline scheduler started, polling every %ss", interval_seconds)
    while True:
        try:
            check_due_reminders()
        except Exception:
            logger.exception("Error checking due reminders")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_scheduler_loop(int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "3600")))
