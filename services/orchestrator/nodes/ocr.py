"""OCR node: extract text from each rasterized page image via Tesseract.

Added 2026-11-17 in place of vision-model reading: no vision model is available
on Groq Cloud's self-serve API, confirmed by listing models on three separate
keys (identical text-only lineup on all three). This runs between PREPROCESS and
CLASSIFY/EXTRACT, which now reason over plain text instead of page images.

English only for now -- no Hindi tessdata pack installed. Revisit if real
rejection letters/policy wordings turn out to need Hindi OCR; the voice
intake path (Sarvam, separate from this) was always expected to carry the
Hindi/Hinglish load, not document OCR.
"""
import shutil

import pytesseract
from PIL import Image

_WINDOWS_FALLBACK = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _configure_tesseract_cmd() -> None:
    """Use whatever's on PATH (the normal case in a Linux container with
    tesseract-ocr apt-installed); fall back to the known local dev install path
    only if PATH resolution fails."""
    import os

    if shutil.which("tesseract") is None and os.path.exists(_WINDOWS_FALLBACK):
        pytesseract.pytesseract.tesseract_cmd = _WINDOWS_FALLBACK


_configure_tesseract_cmd()


def ocr_image(image_path: str) -> str:
    return pytesseract.image_to_string(Image.open(image_path))


def run(state: dict) -> dict:
    for doc in state["documents"]:
        doc["page_text"] = [ocr_image(p) for p in doc["page_images"]]
    return state
