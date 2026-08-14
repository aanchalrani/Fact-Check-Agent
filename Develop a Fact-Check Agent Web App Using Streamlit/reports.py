from __future__ import annotations

import csv
import io
import json
from html import escape
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import FactCheckReport, VerificationResult
from .web_search import reliability_score


def report_markdown(report: FactCheckReport) -> str:
    counts = report.counts
    lines = [
        f"# Fact-Check Report: {report.filename}",
        "",
        f"**Created:** {report.created_at}  ",
        f"**Pages:** {report.pages}  ",
        f"**Extracted characters:** {report.extracted_characters:,}  ",
        f"**Overall status:** {report.overall_status}",
        "",
        "## Summary",
        "",
        "| Verdict | Count |",
        "|---|---:|",
        f"| Verified | {counts.get('Verified', 0)} |",
        f"| Inaccurate | {counts.get('Inaccurate', 0)} |",
        f"| False | {counts.get('False', 0)} |",
        "",
        "> This report is an evidence review, not a substitute for editorial, legal, medical, or financial judgment. Search results and source availability can change over time.",
        "",
        "## Claim findings",
        "",
    ]
    for index, result in enumerate(report.results, start=1):
        lines.extend(
            [
                f"### {index}. {result.verdict} — {result.claim.category}",
                "",
                f"**Claim:** {result.claim.text}",
                f"**Source page:** {result.claim.page or 'Not identified'}  ",
                f"**Confidence:** {result.confidence:.0%}  ",
                f"**Method:** {result.method}",
                "",
                f"**Assessment:** {result.rationale}",
                "",
            ]
        )
        if result.corrected_fact:
            lines.extend([f"**Correction / context:** {result.corrected_fact}", ""])
        if result.evidence_summary:
            lines.extend([f"**Evidence summary:** {result.evidence_summary}", ""])
        lines.extend(["**Sources:**", ""])
        if result.sources:
            for source in result.sources:
                quality = f"reliability signal {reliability_score(source):.0%}"
                lines.append(f"- [{source.title}]({source.url}) — `{source.domain}`; {quality}. {source.snippet}")
        else:
            lines.append("- No sources returned.")
        lines.extend(["", f"**Search queries:** {', '.join(result.search_queries)}", "", "---", ""])
    return "\n".join(lines)


def report_json(report: FactCheckReport) -> bytes:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")


def report_csv(report: FactCheckReport) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "claim_id",
            "claim",
            "page",
            "category",
            "verdict",
            "confidence",
            "rationale",
            "corrected_fact",
            "source_count",
            "sources",
            "search_queries",
            "method",
            "checked_at",
        ]
    )
    for result in report.results:
        writer.writerow(
            [
                result.claim.id,
                result.claim.text,
                result.claim.page or "",
                result.claim.category,
                result.verdict,
                f"{result.confidence:.4f}",
                result.rationale,
                result.corrected_fact,
                len(result.sources),
                " | ".join(source.url for source in result.sources),
                " | ".join(result.search_queries),
                result.method,
                result.checked_at,
            ]
        )
    return buffer.getvalue().encode("utf-8")


def report_pdf(report: FactCheckReport) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Fact-Check Report: {report.filename}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor("#123047"), spaceAfter=8))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#405568")))
    styles.add(ParagraphStyle(name="Verdict", parent=styles["Heading2"], textColor=colors.HexColor("#0B7285"), spaceBefore=10))
    story = [
        Paragraph(escape(f"Fact-Check Report: {report.filename}"), styles["ReportTitle"]),
        Paragraph(escape(f"Created {report.created_at} | {report.pages} pages | {report.overall_status}"), styles["Small"]),
        Spacer(1, 5 * mm),
    ]
    summary_table = Table(
        [["Verified", "Inaccurate", "False"], [str(report.counts.get("Verified", 0)), str(report.counts.get("Inaccurate", 0)), str(report.counts.get("False", 0))]],
        colWidths=[55 * mm] * 3,
    )
    summary_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7F5F7")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#123047")), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B9D8DE")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]))
    story.extend([summary_table, Spacer(1, 6 * mm)])
    for index, result in enumerate(report.results, start=1):
        story.append(Paragraph(escape(f"{index}. {result.verdict} — {result.claim.category}"), styles["Verdict"]))
        story.append(Paragraph(f"<b>Claim:</b> {escape(result.claim.text)}", styles["BodyText"]))
        story.append(Paragraph(f"<b>Confidence:</b> {result.confidence:.0%} | <b>Page:</b> {result.claim.page or 'Not identified'}", styles["Small"]))
        story.append(Paragraph(f"<b>Assessment:</b> {escape(result.rationale)}", styles["BodyText"]))
        if result.corrected_fact:
            story.append(Paragraph(f"<b>Correction / context:</b> {escape(result.corrected_fact)}", styles["BodyText"]))
        story.append(Spacer(1, 2 * mm))
        source_rows = [["Source", "Domain", "Evidence"]]
        for source in result.sources[:5]:
            source_rows.append([Paragraph(f"<link href='{escape(source.url)}'>{escape(source.title[:90])}</link>", styles["Small"]), Paragraph(escape(source.domain), styles["Small"]), Paragraph(escape(source.snippet[:240]), styles["Small"])])
        if len(source_rows) == 1:
            source_rows.append(["No sources returned", "", ""])
        source_table = Table(source_rows, colWidths=[60 * mm, 32 * mm, 78 * mm], repeatRows=1)
        source_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F7")), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5DA")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), 8)]))
        story.extend([source_table, Spacer(1, 4 * mm)])
    doc.build(story)
    return buffer.getvalue()
