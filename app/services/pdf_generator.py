"""
PDF report generator.

Builds a professional single-page-style report from a CompanyData object
using reportlab's Platypus layout engine (flowables), matching the
sections shown in the spec's sample PDF: header, company info,
products/services, AI-generated pain points, competitors.

Returns raw PDF bytes so the route can stream them straight to the
client without touching disk.
"""

import io
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

from app.models import CompanyData

ACCENT_COLOR = colors.HexColor("#D97706")  # amber, matches sample screenshots
DARK_TEXT = colors.HexColor("#1F2937")
MUTED_TEXT = colors.HexColor("#6B7280")


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", fontSize=22, textColor=DARK_TEXT,
        spaceAfter=4, fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="ReportSubtitle", fontSize=9, textColor=MUTED_TEXT,
        spaceAfter=16, fontName="Helvetica",
    ))
    styles.add(ParagraphStyle(
        name="SectionHeader", fontSize=11, textColor=ACCENT_COLOR,
        spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="BodyTextCustom", fontSize=10, textColor=DARK_TEXT,
        leading=14, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="BulletItem", fontSize=10, textColor=DARK_TEXT,
        leading=14, leftIndent=12, spaceAfter=3,
    ))
    return styles


def generate_pdf(data: CompanyData) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )
    styles = _build_styles()
    story = []

    # Header
    story.append(Paragraph("RELU CONSULTANCY · COMPANY RESEARCH REPORT", styles["ReportSubtitle"]))
    story.append(Paragraph(data.company_name, styles["ReportTitle"]))
    story.append(HRFlowable(width="100%", color=ACCENT_COLOR, thickness=1.2, spaceAfter=10))

    # Company info table
    story.append(Paragraph("COMPANY INFORMATION", styles["SectionHeader"]))
    info_rows = [
        ["Website", data.website],
        ["Phone", data.phone or "Not publicly listed"],
        ["Address", data.address or "Not publicly listed"],
    ]
    info_table = Table(info_rows, colWidths=[1.2 * inch, 5.3 * inch])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED_TEXT),
        ("TEXTCOLOR", (1, 0), (1, -1), DARK_TEXT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(info_table)

    # Summary
    if data.summary:
        story.append(Paragraph("SUMMARY", styles["SectionHeader"]))
        story.append(Paragraph(data.summary, styles["BodyTextCustom"]))

    # Products / Services
    story.append(Paragraph("PRODUCTS & SERVICES", styles["SectionHeader"]))
    if data.products_services:
        for item in data.products_services:
            story.append(Paragraph(f"• {item}", styles["BulletItem"]))
    else:
        story.append(Paragraph("No product/service details found.", styles["BodyTextCustom"]))

    # Pain points
    story.append(Paragraph("AI-GENERATED PAIN POINTS", styles["SectionHeader"]))
    if data.pain_points:
        for item in data.pain_points:
            story.append(Paragraph(f"• {item}", styles["BulletItem"]))
    else:
        story.append(Paragraph("No pain points could be inferred.", styles["BodyTextCustom"]))

    # Competitors
    story.append(Paragraph("COMPETITORS", styles["SectionHeader"]))
    if data.competitors:
        comp_rows = [["Name", "Website"]] + [
            [c.name, c.website or "Unknown"] for c in data.competitors
        ]
        comp_table = Table(comp_rows, colWidths=[2.2 * inch, 4.3 * inch])
        comp_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), MUTED_TEXT),
            ("TEXTCOLOR", (0, 1), (-1, -1), DARK_TEXT),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#E5E7EB")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(comp_table)
    else:
        story.append(Paragraph("No competitors identified.", styles["BodyTextCustom"]))

    doc.build(story)
    return buffer.getvalue()