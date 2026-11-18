"""Thin client for Sarvam AI's STT (Saaras) and TTS (Bulbul) APIs -- the
Hindi/Hinglish voice intake path, separate from the Groq-based document
pipeline (Groq has no audio I/O).

Verified working end-to-end on 2026-11-17: a TTS'd Hinglish phrase
("Mera claim reject ho gaya hai, kripya madad kijiye.") round-tripped through
STT came back as "मेरा क्लेम रिजेक्ट हो गया है, कृपया मदद कीजिए।" -- correct
meaning, with "claim"/"reject" correctly kept as phonetic loanwords rather than
mistranslated, which is exactly the code-mixing handling this product needs.
"""
import base64
import os

import requests

_BASE_URL_DEFAULT = "https://api.sarvam.ai"


def _headers() -> dict:
    return {"api-subscription-key": os.environ["SARVAM_API_KEY"]}


def _base_url() -> str:
    return os.environ.get("SARVAM_BASE_URL", _BASE_URL_DEFAULT)


def text_to_speech(text: str, language_code: str = "hi-IN") -> bytes:
    """Returns WAV audio bytes for the given text."""
    response = requests.post(
        f"{_base_url()}/text-to-speech",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"text": text, "target_language_code": language_code},
        timeout=30,
    )
    response.raise_for_status()
    audio_b64 = response.json()["audios"][0]
    return base64.b64decode(audio_b64)


def speech_to_text(audio_bytes: bytes, language_code: str = "hi-IN", model: str = "saaras:v4") -> dict:
    """Returns the full response dict: {request_id, transcript, language_code}."""
    response = requests.post(
        f"{_base_url()}/speech-to-text",
        headers=_headers(),
        files={"file": ("audio.wav", audio_bytes, "audio/wav")},
        data={"model": model, "language_code": language_code},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()
