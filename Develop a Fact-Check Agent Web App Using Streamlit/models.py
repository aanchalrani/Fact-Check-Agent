from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Claim:
    """A factual assertion extracted from the source document."""

    id: int
    text: str
    page: int | None = None
    category: str = "general"
    confidence: float = 0.0
    selected: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Source:
    """A web source returned by a live search."""

    title: str
    url: str
    snippet: str = ""
    domain: str = ""
    published: str | None = None
    source_type: str = "web"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    """Evidence-backed result for one claim."""

    claim: Claim
    verdict: str
    confidence: float
    rationale: str
    corrected_fact: str = ""
    sources: list[Source] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    evidence_summary: str = ""
    checked_at: str = ""
    method: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["claim"] = self.claim.to_dict()
        payload["sources"] = [source.to_dict() for source in self.sources]
        return payload

    @property
    def is_actionable(self) -> bool:
        return self.verdict in {"Inaccurate", "False"}


@dataclass
class FactCheckReport:
    """Complete report for one uploaded PDF."""

    filename: str
    pages: int
    extracted_characters: int
    claims: list[Claim]
    results: list[VerificationResult]
    created_at: str
    source_text_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "pages": self.pages,
            "extracted_characters": self.extracted_characters,
            "claims": [claim.to_dict() for claim in self.claims],
            "results": [result.to_dict() for result in self.results],
            "created_at": self.created_at,
            "source_text_preview": self.source_text_preview,
        }

    @property
    def counts(self) -> dict[str, int]:
        counts = {"Verified": 0, "Inaccurate": 0, "False": 0, "Unclear": 0}
        for result in self.results:
            counts[result.verdict] = counts.get(result.verdict, 0) + 1
        return counts

    @property
    def overall_status(self) -> str:
        if self.counts.get("False", 0) or self.counts.get("Inaccurate", 0):
            return "Needs review"
        if self.counts.get("Unclear", 0):
            return "Partially verified"
        return "All checked claims verified"


class FactCheckError(RuntimeError):
    """A user-facing, recoverable application error."""
