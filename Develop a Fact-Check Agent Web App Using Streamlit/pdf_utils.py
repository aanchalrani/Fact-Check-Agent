from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from io import BytesIO

import requests
from pypdf import PdfReader

from .models import Claim, FactCheckError

MAX_TEXT_CHARS = 120_000
MAX_CLAIMS = 12


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int, dict[int, str]]:
    """Extract page-aware text from a digitally-born PDF.

    The page map is retained so every claim can be traced back to its page.
    Scanned PDFs without a text layer are rejected with a useful remediation.
    """
    if not pdf_bytes:
        raise FactCheckError("The uploaded file is empty.")
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise FactCheckError("Please upload a PDF smaller than 20 MB.")

    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
        page_map: dict[int, str] = {}
        parts: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except TypeError:
                text = page.extract_text() or ""
            text = _clean_text(text)
            page_map[page_number] = text
            if text:
                parts.append(f"[Page {page_number}]\n{text}")
    except Exception as exc:  # pypdf exposes several parser-specific exceptions
        raise FactCheckError(f"The PDF could not be read: {exc}") from exc

    full_text = "\n\n".join(parts).strip()
    if len(full_text) < 40:
        raise FactCheckError(
            "This PDF has little or no extractable text. It may be scanned or image-only; "
            "please upload an OCR-enabled PDF."
        )
    return full_text[:MAX_TEXT_CHARS], len(reader.pages), page_map


def _clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_claims(
    page_map: dict[int, str],
    use_llm: bool = True,
    max_claims: int = MAX_CLAIMS,
) -> list[Claim]:
    """Extract specific factual assertions, preferring an LLM when configured."""
    heuristic_claims = _heuristic_claims(page_map, max_claims=max_claims)
    if not use_llm or not os.getenv("OPENAI_API_KEY"):
        return heuristic_claims

    try:
        llm_claims = _llm_claims(page_map, max_claims=max_claims)
        return llm_claims or heuristic_claims
    except (requests.RequestException, FactCheckError, TypeError, ValueError, KeyError):
        # A document should remain checkable if the optional model is unavailable.
        return heuristic_claims


def _sentence_candidates(text: str) -> Iterable[str]:
    # Preserve PDF line boundaries so headings do not get concatenated with the first claim.
    for line in re.split(r"\n+", text):
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|(?<=;)[ ]+", normalized):
            candidate = sentence.strip(" -–—•\t\n")
            if 35 <= len(candidate) <= 420:
                yield candidate


def _is_claim_like(sentence: str) -> bool:
    lower = sentence.lower()
    factual_markers = (
        r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|million|billion|trillion|k|m|bn)?\b",
        r"\b(?:19|20)\d{2}\b",
        r"\b(?:is|are|was|were|has|have|had|will|can|could|increased|decreased|grew|fell|accounts for|costs|reached)\b",
        r"[$€£₹]\s?\d|\b(?:USD|EUR|GBP|INR)\s?\d",
    )
    excluded_starts = ("note:", "source:", "references:", "trap document", "table of contents", "executive summary")
    return any(re.search(marker, lower) for marker in factual_markers) and not lower.startswith(excluded_starts)


def _category(sentence: str) -> str:
    lower = sentence.lower()
    if any(token in lower for token in ("revenue", "cost", "price", "$", "€", "£", "₹", "usd", "inr")):
        return "financial"
    if any(token in lower for token in ("percent", "%", "million", "billion", "population", "users", "market share")):
        return "statistical"
    if any(token in lower for token in ("algorithm", "model", "latency", "accuracy", "api", "technical")):
        return "technical"
    if re.search(r"\b(?:19|20)\d{2}\b", lower):
        return "date / historical"
    return "general"


def _heuristic_claims(page_map: dict[int, str], max_claims: int) -> list[Claim]:
    claims: list[Claim] = []
    seen: set[str] = set()
    for page_number, text in page_map.items():
        for sentence in _sentence_candidates(text):
            cleaned = re.sub(r"^\[?page\s+\d+\]?[:\s-]*", "", sentence, flags=re.IGNORECASE)
            key = re.sub(r"\W+", " ", cleaned.lower()).strip()
            if key in seen or not _is_claim_like(cleaned):
                continue
            seen.add(key)
            claims.append(
                Claim(
                    id=len(claims) + 1,
                    text=cleaned,
                    page=page_number,
                    category=_category(cleaned),
                    confidence=0.72,
                )
            )
            if len(claims) >= max_claims:
                return claims
    return claims


def _llm_claims(page_map: dict[int, str], max_claims: int) -> list[Claim]:
    base_url = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    document = "\n\n".join(f"PAGE {page}: {text}" for page, text in page_map.items())[:MAX_TEXT_CHARS]
    prompt = (
        f"Extract up to {max_claims} independently checkable factual claims from the document. "
        "Prefer statements with numbers, dates, comparisons, financial or technical assertions. "
        "Do not output opinions, recommendations, definitions, or claims that cannot be searched. "
        f"Return JSON only in the form {{claims:[{{text,page,category,confidence}}]}}.\n\nDOCUMENT:\n{document}"
    )
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"},
        json={
            "model": model,
            "max_completion_tokens": 1800,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "fact_claims",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "claims": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string"},
                                        "page": {"type": ["integer", "null"]},
                                        "category": {"type": "string"},
                                        "confidence": {"type": "number"},
                                    },
                                    "required": ["text", "page", "category", "confidence"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["claims"],
                        "additionalProperties": False,
                    },
                },
            },
            "messages": [
                {"role": "system", "content": "You are a careful fact-checking claim extractor."},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=45,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    payload = json.loads(content)
    claims: list[Claim] = []
    for raw in payload.get("claims", [])[:max_claims]:
        text = str(raw.get("text", "")).strip()
        if len(text) < 20:
            continue
        page = raw.get("page")
        page = int(page) if str(page).isdigit() else None
        confidence = float(raw.get("confidence", 0.85))
        claims.append(
            Claim(
                id=len(claims) + 1,
                text=text,
                page=page,
                category=str(raw.get("category", "general")),
                confidence=max(0.0, min(1.0, confidence)),
            )
        )
    return claims
