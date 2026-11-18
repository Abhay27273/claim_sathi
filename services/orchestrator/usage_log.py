"""Persists per-call Grok token usage to grok_usage_log (IMPLEMENTATION_PLAN.md section 14)."""
import os

import psycopg


def record(case_id: str, usage: dict) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO grok_usage_log (case_id, node, model, prompt_tokens, completion_tokens, latency_ms)
                VALUES (%(case_id)s, %(task)s, %(model)s, %(prompt_tokens)s, %(completion_tokens)s, %(latency_ms)s)
                """,
                {"case_id": case_id, **usage},
            )
        conn.commit()
