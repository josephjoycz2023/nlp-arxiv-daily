from __future__ import annotations

import io
import time

import requests
from pypdf import PdfReader
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, wait_random

from nlp_arxiv_daily.fetcher import ARXIV_MIN_INTERVAL_SECONDS


PDF_TIMEOUT_SECONDS = 60
_PDF_LAST_REQUEST_TS: float = 0.0


def paper_url_to_pdf_url(paper_url: str) -> str:
    pdf_url = paper_url.replace("/abs/", "/pdf/")
    if not pdf_url.endswith(".pdf"):
        pdf_url = f"{pdf_url}.pdf"
    return pdf_url


def _throttle_pdf_requests() -> None:
    global _PDF_LAST_REQUEST_TS
    elapsed = time.monotonic() - _PDF_LAST_REQUEST_TS
    if elapsed < ARXIV_MIN_INTERVAL_SECONDS:
        time.sleep(ARXIV_MIN_INTERVAL_SECONDS - elapsed)
    _PDF_LAST_REQUEST_TS = time.monotonic()


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=2, min=2, max=20) + wait_random(0, 1),
    stop=stop_after_attempt(3),
    reraise=True,
)
def download_pdf_text(pdf_url: str, *, timeout: int = PDF_TIMEOUT_SECONDS) -> tuple[str, int]:
    _throttle_pdf_requests()
    response = requests.get(pdf_url, timeout=timeout)
    response.raise_for_status()

    reader = PdfReader(io.BytesIO(response.content))
    page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(item for item in page_texts if item)
    if not text.strip():
        raise ValueError(f"PDF text extraction returned empty content for {pdf_url}.")
    return text, len(reader.pages)
