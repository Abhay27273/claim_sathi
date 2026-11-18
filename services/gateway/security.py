"""Gateway-level protections: API-key auth, rate limiting, and upload hardening.

This is NOT the phone-OTP user authentication described in IMPLEMENTATION_PLAN.md
section 4 -- that's a real, separate feature (identifying *which family/policy*
a request belongs to). This is a lower-level stopgap that closes the "anyone on
the internet can call /cases and burn through Groq/Razorpay quota" hole in the
meantime. Both are needed eventually; only this one exists today.
"""
import os
import secrets
import uuid
from pathlib import Path

import redis
from fastapi import Header, HTTPException

ALLOWED_UPLOAD_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15MB/file, matching Grok/vision-model norms from the plan


def require_api_key(x_api_key: str = Header(default="")) -> None:
    expected = os.environ.get("GATEWAY_API_KEY", "")
    if not expected or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Missing or invalid X-API-Key header")


def _redis() -> redis.Redis:
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def enforce_rate_limit(bucket: str, limit: int, window_seconds: int) -> None:
    """Fixed-window limiter backed by Redis (shared across gateway instances,
    unlike an in-process counter). `bucket` should already be scoped to the
    caller, e.g. f"ratelimit:cases:{api_key}"."""
    client = _redis()
    key = f"{bucket}:{window_seconds}"
    count = client.incr(key)
    if count == 1:
        client.expire(key, window_seconds)
    if count > limit:
        raise HTTPException(429, f"Rate limit exceeded: {limit} requests per {window_seconds}s")


def validate_upload(content_type: str, data: bytes) -> None:
    if content_type not in ALLOWED_UPLOAD_MIME_TYPES:
        raise HTTPException(400, f"Unsupported file type: {content_type!r}. Allowed: PDF, JPEG, PNG.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File too large: {len(data)} bytes (max {MAX_UPLOAD_BYTES})")
    if len(data) == 0:
        raise HTTPException(400, "Empty file upload")


def safe_destination(case_dir: Path, original_filename: str) -> Path:
    """Never trust a client-supplied filename as a path component -- it can
    contain "../" traversal sequences or other path-breaking content. Keep
    only the extension from what the client sent and generate the rest."""
    suffix = Path(original_filename).suffix.lower()
    if suffix not in (".pdf", ".jpg", ".jpeg", ".png"):
        suffix = ""
    return case_dir / f"{uuid.uuid4()}{suffix}"
