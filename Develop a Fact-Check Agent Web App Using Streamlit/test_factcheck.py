from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from factcheck.models import Claim, FactCheckReport, Source, VerificationResult
from factcheck.pdf_utils import extract_claims, extract_pdf_text
from factcheck.reports import report_csv, report_json, report_markdown
from factcheck.verification import _heuristic_assessment


def sample_pdf() -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.drawString(72, 760, "The company reached $12 million in revenue in 2024.")
    pdf.drawString(72, 740, "The platform has 75% market share among enterprise users.")
    pdf.save()
    return buffer.getvalue()


def test_extract_pdf_text_and_claims():
    text, pages, page_map = extract_pdf_text(sample_pdf())
    assert pages == 1
    assert "12 million" in text
    claims = extract_claims(page_map, use_llm=False, max_claims=8)
    assert len(claims) == 2
    assert claims[0].page == 1
    assert claims[0].category in {"financial", "statistical"}


def test_heuristic_verdict_detects_numeric_mismatch():
    claim = Claim(id=1, text="The company reached $12 million in revenue in 2024.", page=1, category="financial")
    sources = [
        Source(
            title="Annual report",
            url="https://example.gov/report",
            domain="example.gov",
            snippet="The company reported $8 million in revenue in 2024.",
        )
    ]
    result = _heuristic_assessment(claim, sources, [claim.text])
    assert result.verdict == "Inaccurate"
    assert result.sources == sources


def test_report_serialization():
    claim = Claim(id=1, text="The population was 10 million in 2020.", page=1, category="statistical")
    source = Source(title="Reference", url="https://example.gov/source", domain="example.gov", snippet="Population was 10 million in 2020.")
    result = VerificationResult(claim=claim, verdict="Verified", confidence=0.9, rationale="Supported.", sources=[source], search_queries=[claim.text], checked_at="2026-01-01T00:00:00+00:00")
    report = FactCheckReport(filename="sample.pdf", pages=1, extracted_characters=100, claims=[claim], results=[result], created_at="2026-01-01T00:00:00+00:00")
    assert "# Fact-Check Report" in report_markdown(report)
    assert b"claim_id" in report_csv(report)
    assert b'"filename": "sample.pdf"' in report_json(report)
