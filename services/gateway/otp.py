"""Phone-OTP authentication via MSG91 (https://control.msg91.com/api/v5/otp).

Dev-mode fallback requires BOTH `MSG91_AUTH_KEY` unset AND `ALLOW_DEV_OTP=true`
set explicitly -- not just "no key configured". A real account's key going
missing from a misconfigured deployment must fail loudly, not silently fall
back to a mode that returns the OTP in the API response. That fallback exists
only so the request-otp -> verify-otp -> session-token flow is testable
without a real MSG91 account (none is available yet -- MSG91_AUTH_KEY and
MSG91_OTP_TEMPLATE_ID, both account-specific from the MSG91 dashboard, are
still needed before this can send a real SMS).

MSG91 gotcha from its docs, not from testing against a real account (none
exists yet): it replies HTTP 200 even on errors -- check the `type` field in
the response body, not just the status code.
"""
import hashlib
import os
import random
import secrets
import string
from datetime import datetime, timedelta, timezone

import requests
from fastapi import HTTPException

from services.gateway.db import get_connection

MSG91_OTP_URL = "https://control.msg91.com/api/v5/otp"
OTP_EXPIRY_MINUTES = 10
SESSION_EXPIRY_DAYS = 30


def _dev_mode() -> bool:
    has_key = bool(os.environ.get("MSG91_AUTH_KEY"))
    allow_dev = os.environ.get("ALLOW_DEV_OTP") == "true"
    if not has_key and not allow_dev:
        raise HTTPException(
            500,
            "MSG91_AUTH_KEY is not configured and ALLOW_DEV_OTP is not set to "
            "'true' -- refusing to silently fall back to an insecure dev mode.",
        )
    return not has_key


def _generate_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


def _hash_otp(phone: str, otp: str) -> str:
    return hashlib.sha256(f"{phone}:{otp}".encode()).hexdigest()


def request_otp(phone: str) -> dict:
    dev_mode = _dev_mode()
    otp = _generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO otp_requests (phone, otp_hash, expires_at) VALUES (%s, %s, %s)",
                (phone, _hash_otp(phone, otp), expires_at),
            )
        conn.commit()

    if dev_mode:
        return {"dev_mode": True, "otp": otp}

    response = requests.post(
        MSG91_OTP_URL,
        headers={"authkey": os.environ["MSG91_AUTH_KEY"], "Content-Type": "application/json"},
        params={
            "template_id": os.environ["MSG91_OTP_TEMPLATE_ID"],
            "mobile": phone,
            "otp": otp,
            "otp_length": 6,
            "otp_expiry": OTP_EXPIRY_MINUTES,
        },
        timeout=15,
    )
    body = response.json()
    if body.get("type") == "error":
        raise RuntimeError(f"MSG91 OTP send failed: {body}")
    return {"dev_mode": False}


def verify_otp(phone: str, otp: str) -> bool:
    otp_hash = _hash_otp(phone, otp)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM otp_requests
                WHERE phone = %s AND otp_hash = %s AND expires_at > now() AND consumed_at IS NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (phone, otp_hash),
            )
            row = cur.fetchone()
            if row is None:
                return False
            cur.execute("UPDATE otp_requests SET consumed_at = now() WHERE id = %s", (row["id"],))
        conn.commit()
    return True


def create_session(phone: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_EXPIRY_DAYS)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE phone = %s", (phone,))
            row = cur.fetchone()
            if row is None:
                cur.execute("INSERT INTO users (phone) VALUES (%s) RETURNING id", (phone,))
                row = cur.fetchone()
            user_id = row["id"]
            cur.execute(
                "INSERT INTO user_sessions (user_id, token, expires_at) VALUES (%s, %s, %s)",
                (user_id, token, expires_at),
            )
        conn.commit()
    return token


def resolve_session(token: str) -> str | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM user_sessions WHERE token = %s AND expires_at > now()",
                (token,),
            )
            row = cur.fetchone()
    return str(row["user_id"]) if row else None
