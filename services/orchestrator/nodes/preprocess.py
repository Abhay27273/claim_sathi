"""PREPROCESS node: rasterize any PDF documents to page-tagged PNGs.

Grok's vision endpoint only accepts JPG/PNG, so every PDF in a case's document
set must be converted before CLASSIFY/EXTRACT can run (IMPLEMENTATION_PLAN.md section 4.3).
"""
import tempfile
from pathlib import Path

import pypdfium2 as pdfium


def pdf_to_pages(pdf_path: str, out_dir: str, dpi: int = 150) -> list[str]:
    """Rasterize a PDF to one PNG per page. Returns output paths in page order."""
    pdf = pdfium.PdfDocument(pdf_path)
    scale = dpi / 72
    stem = Path(pdf_path).stem
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_paths = []
    for i, page in enumerate(pdf):
        image = page.render(scale=scale).to_pil()
        out_path = str(Path(out_dir) / f"{stem}_p{i + 1}.png")
        image.save(out_path)
        out_paths.append(out_path)
    return out_paths


def run(state: dict) -> dict:
    out_dir = str(Path(tempfile.gettempdir()) / state["case_id"])
    for doc in state["documents"]:
        if doc["mime_type"] == "application/pdf":
            doc["page_images"] = pdf_to_pages(doc["storage_path"], out_dir=out_dir)
        else:
            doc["page_images"] = [doc["storage_path"]]
    return state
