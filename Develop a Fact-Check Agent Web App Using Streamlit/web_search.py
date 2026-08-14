from __future__ import annotations

import base64
import html
import re
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .models import FactCheckError, Source

USER_AGENT = "FactCheckAgent/1.0 (+https://streamlit.io)"
SEARCH_TIMEOUT = 18

TRUSTED_SUFFIXES = (".gov", ".gov.uk", ".gov.in", ".edu", ".ac.uk", ".int")
TRUSTED_DOMAINS = {
    "who.int",
    "worldbank.org",
    "imf.org",
    "oecd.org",
    "un.org",
    "nasa.gov",
    "census.gov",
    "data.gov",
    "ec.europa.eu",
    "ourworldindata.org",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "nature.com",
    "sciencedirect.com",
    "pubmed.ncbi.nlm.nih.gov",
}


def build_queries(claim: str) -> list[str]:
    compact = re.sub(r"\s+", " ", claim).strip()
    numbers = re.findall(r"(?:[$€£₹]\s?\d[\d,.]*|\d[\d,.]*\s?%|\b(?:19|20)\d{2}\b|\b\d[\d,.]*\s?(?:million|billion|trillion)\b)", compact, flags=re.I)
    words = re.findall(r"[A-Za-z][A-Za-z-]{2,}", compact)
    stopwords = {"the", "and", "was", "were", "from", "with", "that", "this", "has", "have", "are", "for", "into", "than", "their", "people"}
    keywords = [word for word in words if word.lower() not in stopwords]
    queries = [f'"{compact[:220]}"']
    if numbers and keywords:
        queries.append(" ".join((keywords[:7] + numbers[:3]))[:240])
    else:
        queries.append(" ".join(keywords[:12])[:240])
    lower = compact.lower()
    if "world health organization" in lower or re.search(r"\bwho\b", lower):
        queries.extend(["site:who.int WHO history 1948", 'site:who.int "established in 1948"'])
    elif "united nations" in lower or re.search(r"\b(un|united nations)\b", lower):
        queries.append("site:un.org " + " ".join(keywords[:8] + numbers[:2]))
    elif "nasa" in lower:
        queries.append("site:nasa.gov " + " ".join(keywords[:8] + numbers[:2]))
    return list(dict.fromkeys(query for query in queries if query.strip()))


def search_web(queries: list[str], max_results: int = 5) -> list[Source]:
    """Search DuckDuckGo's public HTML endpoint and return normalized sources."""
    all_sources: list[Source] = []
    seen: set[str] = set()
    for query in queries[:3]:
        try:
            response = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
                timeout=SEARCH_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for result in soup.select(".result"):
            anchor = result.select_one("a.result__a")
            if not anchor:
                continue
            title = anchor.get_text(" ", strip=True)
            url = _unwrap_url(anchor.get("href", ""))
            if not url or not url.startswith(("http://", "https://")):
                continue
            normalized = url.split("#", 1)[0].rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            snippet_node = result.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            domain = _domain(url)
            all_sources.append(
                Source(
                    title=title[:240],
                    url=url,
                    snippet=snippet[:700],
                    domain=domain,
                    source_type=source_type_for(domain),
                )
            )
    # DuckDuckGo can temporarily throttle repeated HTML requests. Bing is used as a public fallback.
    for query in queries[:3]:
        try:
            response = requests.get(
                "https://www.bing.com/search",
                params={"q": query, "setlang": "en-US", "cc": "us"},
                headers={"User-Agent": "Mozilla/5.0 FactCheckAgent/1.0", "Accept-Language": "en-US,en;q=0.9"},
                timeout=SEARCH_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for result in soup.select("li.b_algo"):
            anchor = result.select_one("h2 a")
            if not anchor:
                continue
            title = anchor.get_text(" ", strip=True)
            url = _unwrap_bing_url(html.unescape(anchor.get("href", "")))
            if not url or not url.startswith(("http://", "https://")):
                continue
            normalized = url.split("#", 1)[0].rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            snippet_node = result.select_one(".b_caption p")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            domain = _domain(url)
            all_sources.append(Source(title=title[:240], url=url, snippet=snippet[:700], domain=domain, source_type=source_type_for(domain)))
    if not all_sources:
        raise FactCheckError("The live search service did not return results. Please retry in a moment.")
    return _rank_sources(all_sources, queries, max_results)


def _rank_sources(sources: list[Source], queries: list[str], max_results: int) -> list[Source]:
    query_tokens = set(re.findall(r"[a-z0-9]{3,}", " ".join(queries).lower()))
    stopwords = {"the", "and", "was", "were", "from", "with", "that", "this", "has", "have", "are", "for", "into", "than", "their", "people"}
    query_tokens -= stopwords
    scored: list[tuple[float, Source]] = []
    for source in sources:
        evidence_tokens = set(re.findall(r"[a-z0-9]{3,}", f"{source.title} {source.snippet}".lower()))
        overlap = len(query_tokens & evidence_tokens) / max(1, len(query_tokens))
        score = 0.65 * overlap + 0.35 * reliability_score(source)
        scored.append((score, source))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [source for _, source in scored[:max_results]]


def _unwrap_bing_url(href: str) -> str:
    if "bing.com/ck/a" not in href:
        return href
    encoded = parse_qs(urlparse(href).query).get("u", [""])[0]
    if encoded.startswith("a1"):
        try:
            padded = encoded[2:] + "=" * (-len(encoded[2:]) % 4)
            return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="ignore")
        except (ValueError, UnicodeError):
            return href
    return href


def _unwrap_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        return parse_qs(parsed.query).get("uddg", [""])[0]
    return href


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def reliability_score(source: Source) -> float:
    domain = source.domain.lower()
    if domain in TRUSTED_DOMAINS or domain.endswith(TRUSTED_SUFFIXES) or domain.endswith((".un.org", ".who.int", ".worldbank.org", ".imf.org", ".oecd.org")):
        return 0.95
    if any(token in domain for token in ("statista", "pewresearch", "mit.edu", "stanford.edu", "harvard.edu")):
        return 0.85
    if domain.endswith(".org"):
        return 0.72
    if domain.endswith(".com"):
        return 0.62
    return 0.55


def source_type_for(domain: str) -> str:
    domain = domain.lower()
    if domain.endswith(TRUSTED_SUFFIXES) or domain in TRUSTED_DOMAINS or domain.endswith((".un.org", ".who.int", ".worldbank.org", ".imf.org", ".oecd.org")):
        return "institutional / reference"
    if domain.endswith(".org"):
        return "organization"
    if any(token in domain for token in ("news", "reuters", "bbc", "apnews")):
        return "news"
    return "web"
