from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from factcheck.models import Claim, FactCheckError, FactCheckReport, VerificationResult
from factcheck.pdf_utils import MAX_CLAIMS, extract_claims, extract_pdf_text
from factcheck.reports import report_csv, report_json, report_markdown, report_pdf
from factcheck.verification import verify_claim
from factcheck.web_search import reliability_score

st.set_page_config(
    page_title="FactCheck Agent",
    page_icon="✓",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        :root { --navy:#123047; --teal:#0b7285; --mint:#e7f5f7; --ink:#1f2933; --muted:#62717c; }
        .block-container { padding-top: 2.4rem; padding-bottom: 3rem; max-width: 1260px; }
        .brand { display:flex; align-items:center; gap:0.75rem; margin-bottom:0.25rem; }
        .brand-mark { width:42px; height:42px; border-radius:12px; background:linear-gradient(135deg,#123047,#0b7285); color:white; display:flex; align-items:center; justify-content:center; font-size:24px; font-weight:700; }
        .brand-name { color:#123047; font-size:1.5rem; font-weight:750; letter-spacing:-0.02em; }
        .subtitle { color:#62717c; margin:0 0 1.4rem 3.25rem; }
        .hero { padding:1.25rem 1.5rem; border:1px solid #d6e5e8; border-radius:18px; background:linear-gradient(135deg,#f6fbfc,#ffffff); }
        .hero h1 { color:#123047; margin:0 0 0.35rem 0; letter-spacing:-0.035em; }
        .hero p { color:#405568; margin:0; max-width:780px; }
        .status-pill { display:inline-block; padding:0.2rem 0.55rem; border-radius:999px; font-size:0.78rem; font-weight:700; }
        .status-verified { background:#d3f9d8; color:#2b8a3e; }
        .status-inaccurate { background:#fff3bf; color:#a07900; }
        .status-false { background:#ffe3e3; color:#c92a2a; }
        .status-unclear { background:#e9ecef; color:#495057; }
        .source-card { padding:0.75rem 0.9rem; margin:0.45rem 0; border:1px solid #e1eaed; border-radius:12px; background:#fbfdfd; }
        .source-meta { color:#62717c; font-size:0.8rem; }
        .small-note { color:#62717c; font-size:0.85rem; }
        div[data-testid="stMetric"] { border:1px solid #e1eaed; border-radius:12px; padding:0.6rem 0.75rem; background:#fff; }
    </style>
    """,
    unsafe_allow_html=True,
)


def initialize_state() -> None:
    defaults = {
        "file_hash": None,
        "filename": None,
        "page_map": None,
        "full_text": None,
        "pages": 0,
        "claims": [],
        "report": None,
        "claims_df": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_for_new_file(file_hash: str, filename: str) -> None:
    if st.session_state.file_hash != file_hash:
        for key in ("page_map", "full_text", "claims", "report", "claims_df"):
            st.session_state[key] = None if key not in ("claims",) else []
        st.session_state.file_hash = file_hash
        st.session_state.filename = filename


def verdict_class(verdict: str) -> str:
    return verdict.lower().replace(" ", "-")


def safe_result(claim: Claim, error: Exception) -> VerificationResult:
    return VerificationResult(
        claim=claim,
        verdict="False",
        confidence=0.2,
        rationale=f"Live evidence could not be retrieved for this claim: {error}",
        corrected_fact="Retry the verification when the live search service is available.",
        evidence_summary="No evidence was available because the live search request failed.",
        checked_at=datetime.now(UTC).isoformat(),
        method="live search unavailable",
    )


def render_source(source, index: int) -> None:
    quality = reliability_score(source)
    st.markdown(
        f"""<div class="source-card"><strong>{index}. <a href="{source.url}" target="_blank">{source.title}</a></strong><br><span class="source-meta">{source.domain} · {source.source_type} · reliability signal {quality:.0%}</span><br><span>{source.snippet or 'No snippet returned; open the source for the full context.'}</span></div>""",
        unsafe_allow_html=True,
    )


initialize_state()

with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">✓</div><div class="brand-name">FactCheck Agent</div></div>', unsafe_allow_html=True)
    st.caption("A live-evidence truth layer for documents")
    st.divider()
    st.subheader("Run settings")
    use_llm = st.toggle(
        "Use model-assisted analysis",
        value=bool(os.getenv("OPENAI_API_KEY")),
        help="Uses OPENAI_API_KEY when configured. The deterministic evidence scorer remains available without it.",
    )
    max_claims = st.slider("Maximum claims", min_value=3, max_value=MAX_CLAIMS, value=8)
    max_sources = st.slider("Sources per claim", min_value=3, max_value=8, value=5)
    st.divider()
    if os.getenv("OPENAI_API_KEY"):
        st.success("Model-assisted extraction and adjudication are available.")
    else:
        st.info("Running in no-key mode: live search plus deterministic evidence scoring. Add OPENAI_API_KEY for model-assisted extraction and adjudication.")
    with st.expander("How verdicts work"):
        st.markdown(
            "**Verified** means the retrieved evidence supports the claim. **Inaccurate** means credible evidence indicates a material error, outdated value, or missing qualification. **False** means the evidence contradicts the claim or no reliable evidence supports it."
        )
    with st.expander("Privacy and limits"):
        st.markdown(
            "Uploaded PDFs are processed in memory by the running app. The app does not persist uploaded documents. Text sent to an optional model provider is controlled by your deployment's API configuration. Search snippets and page availability can change, so review cited sources before publication."
        )

st.markdown('<div class="hero"><h1>Fact-check claims before they become facts.</h1><p>Upload a PDF. Extract specific factual assertions. Search the live web. Compare each claim with evidence, show the sources, and export a review-ready report.</p></div>', unsafe_allow_html=True)
st.write("")

uploaded = st.file_uploader(
    "Upload a PDF to fact-check",
    type=["pdf"],
    max_upload_size=20,
    help="PDFs up to 20 MB are accepted. OCR-enabled PDFs work best for scanned documents.",
)

if uploaded is None:
    st.info("Start by uploading a PDF. The assessment document, a marketing memo, or any fact-heavy report will work.")
    cols = st.columns(3)
    for col, title, description in zip(
        cols,
        ("1. Extract", "2. Verify", "3. Report"),
        ("Find statistics, dates, financial figures, and technical assertions in the PDF.", "Search current web evidence and weigh institutional and reputable sources.", "Review verdicts, corrections, sources, and download a Markdown, CSV, JSON, or PDF report."),
    ):
        with col:
            st.subheader(title)
            st.write(description)
    st.stop()

file_bytes = uploaded.getvalue()
reset_for_new_file(hashlib.sha256(file_bytes).hexdigest(), uploaded.name)

if st.session_state.full_text is None:
    with st.spinner("Reading PDF text and mapping pages…"):
        try:
            full_text, pages, page_map = extract_pdf_text(file_bytes)
            st.session_state.full_text = full_text
            st.session_state.pages = pages
            st.session_state.page_map = page_map
        except FactCheckError as exc:
            st.error(str(exc))
            st.stop()

meta_cols = st.columns(4)
meta_cols[0].metric("File", st.session_state.filename)
meta_cols[1].metric("Pages", st.session_state.pages)
meta_cols[2].metric("Extracted characters", f"{len(st.session_state.full_text):,}")
meta_cols[3].metric("Claims", len(st.session_state.claims) if st.session_state.claims else "—")

source_tab, claims_tab, results_tab = st.tabs(["Document", "Claims", "Results"])

with source_tab:
    st.subheader("Extracted document text")
    st.caption("Page markers are retained so claims can be traced back to the source PDF.")
    st.text_area("Text preview", st.session_state.full_text[:30_000], height=420, label_visibility="collapsed")
    if len(st.session_state.full_text) > 30_000:
        st.caption("Preview is limited to 30,000 characters; the complete text is used for claim extraction up to the configured processing limit.")

with claims_tab:
    st.subheader("Claims to check")
    if not st.session_state.claims:
        if st.button("Extract factual claims", type="primary", width="stretch"):
            with st.spinner("Identifying checkable factual assertions…"):
                claims = extract_claims(st.session_state.page_map, use_llm=use_llm, max_claims=max_claims)
                st.session_state.claims = claims
                st.session_state.claims_df = pd.DataFrame([claim.to_dict() for claim in claims])
            if claims:
                st.success(f"Found {len(claims)} candidate claim(s). Review or edit them before verification.")
                st.rerun()
            st.warning("No checkable factual claims were found. Try a PDF containing figures, dates, or measurable statements.")
    else:
        claim_df = st.session_state.claims_df.copy() if st.session_state.claims_df is not None else pd.DataFrame([claim.to_dict() for claim in st.session_state.claims])
        edited_df = st.data_editor(
            claim_df[["selected", "id", "text", "page", "category", "confidence"]],
            hide_index=True,
            width="stretch",
            height=min(480, 120 + 44 * len(claim_df)),
            column_config={
                "selected": st.column_config.CheckboxColumn("Check", help="Include this claim in live verification."),
                "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                "text": st.column_config.TextColumn("Claim", width="large"),
                "page": st.column_config.NumberColumn("Page", disabled=True, width="small"),
                "category": st.column_config.TextColumn("Category", disabled=True),
                "confidence": st.column_config.ProgressColumn("Extraction confidence", min_value=0, max_value=1, format="%0.0f%%"),
            },
            key="claims_editor",
        )
        st.session_state.claims_df = edited_df
        selected_count = int(edited_df["selected"].sum()) if "selected" in edited_df else 0
        st.caption(f"{selected_count} claim(s) selected. You can edit claim wording before searching.")
        if st.button("Run live verification", type="primary", disabled=selected_count == 0, width="stretch"):
            edited_claims: list[Claim] = []
            for row in edited_df.to_dict(orient="records"):
                if not row.get("selected", True):
                    continue
                edited_claims.append(
                    Claim(
                        id=int(row["id"]),
                        text=str(row["text"]).strip(),
                        page=int(row["page"]) if pd.notna(row["page"]) else None,
                        category=str(row["category"]),
                        confidence=float(row["confidence"]),
                        selected=True,
                    )
                )
            results: list[VerificationResult] = []
            progress = st.progress(0, text="Starting live verification…")
            for index, claim in enumerate(edited_claims, start=1):
                progress.progress((index - 1) / len(edited_claims), text=f"Searching evidence for claim {index} of {len(edited_claims)}…")
                try:
                    results.append(verify_claim(claim, max_sources=max_sources))
                except (FactCheckError, ValueError, RuntimeError, TimeoutError) as exc:
                    results.append(safe_result(claim, exc))
            progress.progress(1.0, text="Verification complete.")
            st.session_state.report = FactCheckReport(
                filename=st.session_state.filename,
                pages=st.session_state.pages,
                extracted_characters=len(st.session_state.full_text),
                claims=edited_claims,
                results=results,
                created_at=datetime.now(UTC).isoformat(),
                source_text_preview=st.session_state.full_text[:2000],
            )
            st.success("Verification complete. Open the Results tab to review findings and download the report.")
            st.rerun()

with results_tab:
    report = st.session_state.report
    if report is None:
        st.info("Your findings will appear here after you extract and verify claims.")
    else:
        counts = report.counts
        st.subheader("Verification summary")
        summary_cols = st.columns(4)
        summary_cols[0].metric("Overall", report.overall_status)
        summary_cols[1].metric("Verified", counts.get("Verified", 0))
        summary_cols[2].metric("Inaccurate", counts.get("Inaccurate", 0))
        summary_cols[3].metric("False", counts.get("False", 0))

        st.subheader("Download report")
        download_cols = st.columns(4)
        download_cols[0].download_button("Markdown", report_markdown(report), file_name="fact_check_report.md", mime="text/markdown", on_click="ignore", width="stretch")
        download_cols[1].download_button("CSV", report_csv(report), file_name="fact_check_results.csv", mime="text/csv", on_click="ignore", width="stretch")
        download_cols[2].download_button("JSON", report_json(report), file_name="fact_check_results.json", mime="application/json", on_click="ignore", width="stretch")
        download_cols[3].download_button("PDF", report_pdf(report), file_name="fact_check_report.pdf", mime="application/pdf", on_click="ignore", width="stretch")

        st.subheader("Claim findings")
        filter_value = st.selectbox("Filter by verdict", ["All", "Verified", "Inaccurate", "False"])
        visible_results = report.results if filter_value == "All" else [result for result in report.results if result.verdict == filter_value]
        for result in visible_results:
            label = f"{result.verdict} · {result.claim.text[:100]}"
            with st.expander(label, expanded=result.verdict in {"Inaccurate", "False"}):
                st.markdown(f'<span class="status-pill status-{verdict_class(result.verdict)}">{result.verdict}</span>', unsafe_allow_html=True)
                st.markdown(f"**Claim:** {result.claim.text}")
                st.caption(f"Page {result.claim.page or 'not identified'} · {result.claim.category} · confidence {result.confidence:.0%} · {result.method}")
                st.write(result.rationale)
                if result.corrected_fact:
                    st.warning(result.corrected_fact)
                if result.evidence_summary:
                    st.info(result.evidence_summary)
                st.markdown("**Sources reviewed**")
                if result.sources:
                    for index, source in enumerate(result.sources, start=1):
                        render_source(source, index)
                else:
                    st.caption("No sources were returned.")
                st.caption(f"Search queries: {' · '.join(result.search_queries)}")
