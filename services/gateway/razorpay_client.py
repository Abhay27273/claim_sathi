"""Razorpay order creation and payment verification.

The signature check in verify_payment_signature() is the actual security
boundary here -- without it, anyone could POST a made-up payment_id to
/cases/{id}/draft and get a free letter. Razorpay's documented scheme: HMAC-SHA256
of "{order_id}|{payment_id}" using the account's key_secret must equal the
signature Razorpay's checkout returns to the client. Verified against a real
test order on 2026-11-17 (see fetch_payment, called after signature check to
also confirm the order is actually captured and for the expected amount --
the signature alone proves the payment belongs to this order/account, not that
it was ever captured, so both checks matter)."""
import hashlib
import hmac
import os

import requests

_BASE_URL = "https://api.razorpay.com/v1"


def _auth() -> tuple[str, str]:
    return os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]


def create_order(amount_paise: int, receipt: str) -> dict:
    key_id, key_secret = _auth()
    response = requests.post(
        f"{_BASE_URL}/orders",
        auth=(key_id, key_secret),
        json={"amount": amount_paise, "currency": "INR", "receipt": receipt},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    _, key_secret = _auth()
    expected = hmac.new(
        key_secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def fetch_payment(payment_id: str) -> dict:
    key_id, key_secret = _auth()
    response = requests.get(f"{_BASE_URL}/payments/{payment_id}", auth=(key_id, key_secret), timeout=15)
    response.raise_for_status()
    return response.json()
