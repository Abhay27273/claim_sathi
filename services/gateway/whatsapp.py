"""WhatsApp Business (Meta Cloud API) webhook handling.

Three things need real Meta credentials and are UNTESTED (no WhatsApp Business
Account exists yet): download_media(), send_text_message(), and the app-secret
value used in verify_signature(). Everything else here is testable without
them -- Meta's webhook payload format is public and stable, and the
verification handshake only needs a token we choose ourselves.

verify_signature() exists because an unauthenticated public webhook URL is
exactly the kind of endpoint that needs a signature check, same principle as
Razorpay's payment signature (services/gateway/razorpay_client.py) -- without
it, anyone who finds the webhook URL could POST a fake "message" payload and
create spam cases or worse. Meta signs the raw request body with HMAC-SHA256
using the app secret, header `X-Hub-Signature-256: sha256=<hex>`.
"""
import hashlib
import hmac
import os

import requests

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

SUPPORTED_DOCUMENT_TYPES = {"document", "image"}


def verify_webhook_challenge(mode: str, token: str, challenge: str) -> str:
    """Meta's one-time GET verification handshake when a webhook URL is registered."""
    if mode != "subscribe" or token != os.environ["WHATSAPP_VERIFY_TOKEN"]:
        raise ValueError("Webhook verification failed: mode/token mismatch")
    return challenge


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        os.environ["WHATSAPP_APP_SECRET"].encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


def parse_incoming_message(payload: dict) -> dict | None:
    """Returns {from_phone, message_type, media_id, mime_type, caption} for a
    document/image message, or None for anything else (text-only messages,
    status callbacks, etc. -- not every webhook POST is a new message)."""
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
    except (KeyError, IndexError):
        return None

    message_type = message.get("type")
    if message_type not in SUPPORTED_DOCUMENT_TYPES:
        return None

    media = message[message_type]
    return {
        "from_phone": message["from"],
        "message_type": message_type,
        "media_id": media["id"],
        "mime_type": media.get("mime_type", "application/octet-stream"),
        "caption": media.get("caption", ""),
    }


def download_media(media_id: str) -> tuple[bytes, str]:
    """Two-step Graph API fetch: resolve the media_id to a signed URL, then
    download it. NOT tested -- needs a real WHATSAPP_TOKEN."""
    token = os.environ["WHATSAPP_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    meta_response = requests.get(f"{GRAPH_API_BASE}/{media_id}", headers=headers, timeout=15)
    meta_response.raise_for_status()
    media_url = meta_response.json()["url"]

    data_response = requests.get(media_url, headers=headers, timeout=30)
    data_response.raise_for_status()
    return data_response.content, data_response.headers.get("Content-Type", "application/octet-stream")


def send_text_message(to_phone: str, text: str) -> None:
    """NOT tested -- needs a real WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID."""
    token = os.environ["WHATSAPP_TOKEN"]
    phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    response = requests.post(
        f"{GRAPH_API_BASE}/{phone_number_id}/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": text},
        },
        timeout=15,
    )
    response.raise_for_status()
