from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher

import requests

from .models import Claim, FactCheckError, Source, VerificationResult
from .web_search import build_queries, reliability_score, search_web

VERDICTS = ("Verified", "Inaccurate", "False")


def verify_claim(claim: Claim, max_sources: int = 5) -> VerificationResult:
    queries = build_queries(claim.text)
    try:
        sources = search_web(queries, max_results=max_sources)
    except (requests.RequestException, FactCheckError, ValueError, RuntimeError, TimeoutError) as exc:
        return VerificationResult(
            claim=claim,
            verdict="False",
            confidence=0.2,
            rationale=f"Live evidence could not be retrieved for this claim: {exc}",
            corrected_fact="Retry the verification when the live search service is available.",
            evidence_summary="No evidence was available because the live search request failed.",
            search_queries=queries,
            checked_at=_now(),
            method="live search unavailable",
        )
    llm_result = _llm_assessment(claim, sources, queries) if os.getenv("OPENAI_API_KEY") else None
    if llm_result:
        llm_result.sources = sources
        llm_result.search_queries = queries
        llm_result.checked_at = _now()
        llm_result.method = "live search + structured model"
        return llm_result
    return _heuristic_assessment(claim, sources, queries)


def _heuristic_assessment(claim: Claim, sources: list[Source], queries: list[str]) -> VerificationResult:
    claim_numbers = _numbers(claim.text)
    source_text = " ".join(f"{s.title} {s.snippet}" for s in sources)
    source_numbers = _numbers(source_text)
    credible_sources = [source for source in sources if reliability_score(source) >= 0.78]
    claim_lower = claim.text.lower()
    exact_support = max((_similarity(claim_lower, f"{source.title} {source.snippet}".lower()) for source in sources), default=0.0)

    verdict = "False"
    confidence = 0.58
    corrected_fact = ""
    rationale = "No reliable evidence supporting this claim was found in the live search results."
    evidence_summary = "Search results were reviewed, but no sufficiently reliable source directly supported the assertion."

    if claim_numbers:
        matching_numbers = sum(number in source_numbers for number in claim_numbers)
        claim_fact_numbers = [number for number in claim_numbers if not re.fullmatch(r"(?:19|20)\d{2}", number)]
        source_fact_numbers = [number for number in source_numbers if not re.fullmatch(r"(?:19|20)\d{2}", number)]
        contradictory_numbers = bool(claim_fact_numbers and source_fact_numbers) and not set(claim_fact_numbers).intersection(source_fact_numbers)
        if contradictory_numbers and credible_sources:
            verdict = "Inaccurate"
            confidence = min(0.95, 0.67 + 0.06 * len(credible_sources))
            corrected_fact = _best_correction(credible_sources, claim_numbers)
            rationale = "Reliable sources surfaced numeric or dated evidence that conflicts with the claim."
            evidence_summary = "The claim's figures do not match the figures reported by the strongest retrieved sources."
        elif matching_numbers == len(claim_numbers) and credible_sources:
            verdict = "Verified"
            confidence = min(0.96, 0.72 + 0.05 * len(credible_sources))
            rationale = "The key figures in the claim appear in one or more reliable retrieved sources."
            evidence_summary = "The retrieved evidence contains the claim's reported figures and is consistent with the assertion."
        elif exact_support >= 0.74:
            verdict = "Verified"
            confidence = 0.72
            rationale = "The claim closely matches the retrieved evidence, although the search returned limited primary-source coverage."
            evidence_summary = "At least one retrieved source closely matches the wording of the claim."
        elif credible_sources:
            verdict = "Inaccurate"
            confidence = 0.61
            corrected_fact = _best_correction(credible_sources, claim_numbers)
            rationale = "The search surfaced credible context, but it did not corroborate the claim's exact figures."
            evidence_summary = "The claim requires correction or qualification based on the available credible context."
    elif exact_support >= 0.78 and credible_sources:
        verdict = "Verified"
        confidence = min(0.9, 0.68 + 0.05 * len(credible_sources))
        rationale = "The wording and substance of the claim closely match reliable retrieved sources."
        evidence_summary = "The strongest retrieved sources support the claim's central assertion."

    return VerificationResult(
        claim=claim,
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
        corrected_fact=corrected_fact,
        sources=sources,
        search_queries=queries,
        evidence_summary=evidence_summary,
        checked_at=_now(),
        method="live search + deterministic evidence scoring",
    )


def _llm_assessment(claim: Claim, sources: list[Source], queries: list[str]) -> VerificationResult | None:
    base_url = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    evidence = "\n".join(
        f"[{index}] {source.title} | {source.domain}\nURL: {source.url}\nSnippet: {source.snippet}"
        for index, source in enumerate(sources, start=1)
    )
    prompt = f"""Evaluate this factual claim against the retrieved web evidence.

Claim: {claim.text}
Search queries: {queries}

Evidence:
{evidence}

Rules:
- Verified means the evidence directly supports the claim's central facts.
- Inaccurate means the evidence indicates a material error, outdated figure, wrong date, or missing qualification.
- False means the evidence contradicts the claim or no reliable evidence supports it.
- Do not treat search ranking as proof. Prefer government, academic, intergovernmental, primary, and highly reputable sources.
- If a source is only a snippet, state that limitation.
- If the exact claim cannot be resolved, use False only when no reliable evidence supports it; otherwise use Inaccurate if the available evidence points to a correction.
Return JSON only with keys: verdict, confidence, rationale, corrected_fact, evidence_summary.
"""
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"},
            json={
                "model": model,
                "max_completion_tokens": 1200,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "fact_verdict",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "verdict": {"type": "string", "enum": ["Verified", "Inaccurate", "False"]},
                                "confidence": {"type": "number"},
                                "rationale": {"type": "string"},
                                "corrected_fact": {"type": "string"},
                                "evidence_summary": {"type": "string"},
                            },
                            "required": ["verdict", "confidence", "rationale", "corrected_fact", "evidence_summary"],
                            "additionalProperties": False,
                        },
                    },
                },
                "messages": [
                    {"role": "system", "content": "You are a cautious evidence-based fact checker. Never invent sources or facts."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = json.loads(response.json()["choices"][0]["message"]["content"])
        verdict = str(payload.get("verdict", "")).strip().title()
        if verdict not in VERDICTS:
            return None
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.7))))
        return VerificationResult(
            claim=claim,
            verdict=verdict,
            confidence=confidence,
            rationale=str(payload.get("rationale", "")).strip(),
            corrected_fact=str(payload.get("corrected_fact", "")).strip(),
            sources=sources,
            search_queries=queries,
            evidence_summary=str(payload.get("evidence_summary", "")).strip(),
            checked_at=_now(),
            method="live search + structured model",
        )
    except (requests.RequestException, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _numbers(text: str) -> list[str]:
    tokens = re.findall(
        r"(?:[$€£₹]\s?\d[\d,.]*|\d[\d,.]*\s?%|\b(?:19|20)\d{2}\b|\b\d[\d,.]*\s?(?:million|billion|trillion|thousand)\b)",
        text,
        flags=re.IGNORECASE,
    )
    return [re.sub(r"\s+", "", token.lower()) for token in tokens]


def _similarity(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9]{3,}", left))
    right_tokens = set(re.findall(r"[a-z0-9]{3,}", right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens))
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(overlap, sequence)


def _best_correction(sources: list[Source], claim_numbers: list[str]) -> str:
    for source in sorted(sources, key=reliability_score, reverse=True):
        if source.snippet:
            return f"Review the source's reported figure or date: {source.snippet}"
    return "The claim should be corrected using the strongest cited source."


def _now() -> str:
    return datetime.now(UTC).isoformat()
