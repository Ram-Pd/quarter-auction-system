"""
PDF generation with ReportLab "platypus": you build a list of flowables
(paragraphs, tables, images) and ReportLab lays them out on A4 pages.

    application_form_pdf(applicant, applications)          PDF A
    intimation_slip_pdf(applicant, applications, ...)      PDF B

Both return the PDF as bytes, ready to attach to an email.

PRIVACY: Aadhaar and PAN appear MASKED only (last 4 characters).
"""
from io import BytesIO

import qrcode
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TRAINING_NOTICE = (
    "TRAINING PROJECT - NOT AN OFFICIAL SAIL DOCUMENT. "
    "All rules, amounts and instructions shown are placeholders."
)

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle("title", parent=_styles["Title"], fontSize=16, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=_styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontSize=10, leading=14)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=9, leading=12)
NOTICE = ParagraphStyle("notice", parent=BODY, fontSize=8, textColor=colors.HexColor("#b00020"),
                        alignment=1)  # centred


def qr_payload(applicant):
    """
    What the QR code on the Application Form contains. Deliberately NOT the
    URN, name, phone, email, Aadhaar or PAN: the QR is printable and scannable by anyone.
    """
    return f"QA-APPLICATION|{applicant.application_no}|{applicant.application_date:%Y-%m-%d}"


def _qr_image(data, size_mm=32):
    img = qrcode.make(data, box_size=8, border=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=size_mm * mm, height=size_mm * mm)


def _esc(text):
    """Escape user-entered text: ReportLab paragraphs treat <...> as markup."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _p(text, style=BODY):
    """Paragraph for a table cell."""
    return Paragraph(_esc(text).replace("\n", "<br/>"), style)


def rupees(amount):
    return f"Rs. {amount:,.2f}"


def _details_table(rows):
    table = Table([[_p(k), _p(v)] for k, v in rows], colWidths=[50 * mm, 120 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _quarters_table(applications, with_emd):
    """One row per selected quarter; with_emd adds the EMD column and a total row."""
    header = ["#", "Quarter", "Locality", "Type / floor", "Bidding slot"] + (["EMD"] if with_emd else [])
    rows = [[_p(h, SMALL) for h in header]]
    for i, app in enumerate(applications, start=1):
        q = app.quarter
        auction = q.auctions.filter(status="SCHEDULED").first()
        slot = (f"{timezone.localtime(auction.start_time):%d-%m-%Y %H:%M} ({auction.duration_minutes} min)"
                if auction else "-")
        row = [str(i), q.quarter_no, q.locality, f"{q.get_quarter_type_display()}, {q.floor}", slot]
        if with_emd:
            row.append(rupees(app.emd_amount))
        rows.append([_p(c, SMALL) for c in row])
    widths = [8 * mm, 24 * mm, 58 * mm, 36 * mm, 44 * mm]   # 170 mm: full page width
    if with_emd:
        total = sum(app.emd_amount for app in applications)
        rows.append([_p("", SMALL), _p("Total EMD", SMALL), "", "", "", _p(rupees(total), SMALL)])
        widths = [8 * mm, 20 * mm, 44 * mm, 28 * mm, 40 * mm, 30 * mm]
    table = Table(rows, colWidths=widths, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if with_emd:
        style += [("SPAN", (1, -1), (4, -1)), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f0f0f0"))]
    table.setStyle(TableStyle(style))
    return table


def _build(flowables, title):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title, author=settings.AUCTION_TITLE,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    doc.build(flowables)
    return buf.getvalue()


def application_form_pdf(applicant, applications):
    """PDF A: Auction Application Form."""
    header = Table(
        [[
            [Paragraph("Auction Application Form", TITLE),
             Paragraph(_esc(settings.AUCTION_TITLE), BODY),
             Spacer(1, 4),
             Paragraph(f"<b>Application No:</b> {applicant.application_no}", BODY),
             Paragraph(f"<b>Application Date:</b> {applicant.application_date:%d-%m-%Y}", BODY),
             Paragraph(f"<b>URN:</b> {applicant.urn}", BODY)],
            _qr_image(qr_payload(applicant)),
        ]],
        colWidths=[130 * mm, 40 * mm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    story = [
        Paragraph(TRAINING_NOTICE, NOTICE),
        Spacer(1, 6),
        header,
        Paragraph("Applicant details", H2),
        _details_table([
            ("Name", applicant.name),
            ("Father's name", applicant.father_name),
            ("Phone", applicant.phone),
            ("Email", applicant.email),
            ("Aadhaar (masked)", applicant.masked_aadhaar),
            ("PAN (masked)", applicant.masked_pan),
        ]),
        Paragraph("Address", H2),
        _details_table([
            ("Address", applicant.address),
            ("State", applicant.state),
            ("PIN code", applicant.pin_code),
        ]),
        Paragraph(f"Quarters applied for ({len(applications)})", H2),
        _quarters_table(applications, with_emd=False),
        Paragraph(f"Auction reference: {_esc(settings.AUCTION_REFERENCE)}. The applicant may be allotted at most "
                  f"{settings.MAX_QUARTERS_PER_APPLICANT} quarters (placeholder rule).", SMALL),
        Paragraph("Declaration", H2),
        Paragraph(
            "I declare that the information given in this application is true and correct "
            "to the best of my knowledge. I understand that the auction will be conducted "
            "under the terms and conditions notified by the auction authority, and that "
            "any false information may lead to cancellation of my application.", BODY),
        Spacer(1, 18),
        Paragraph(f"Name: {_esc(applicant.name)}"
                  "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Signature: ______________________",
                  BODY),
    ]
    return _build(story, f"Application Form {applicant.application_no}")


def intimation_slip_pdf(applicant, applications, supplementary=False):
    """PDF B: Auction Intimation Slip (URN + EMD per quarter + SBI Collect instructions)."""
    title = "Auction Intimation Slip" + (" (supplementary)" if supplementary else "")
    story = [
        Paragraph(TRAINING_NOTICE, NOTICE),
        Spacer(1, 6),
        Paragraph(title, TITLE),
        Paragraph(_esc(settings.AUCTION_TITLE), BODY),
        Paragraph("URN details", H2),
        _details_table([
            ("URN", applicant.urn),
            ("URN date", f"{applicant.urn_date:%d-%m-%Y}"),
            ("Application No", applicant.application_no),
            ("Applicant name", applicant.name),
            ("Phone", applicant.phone),
        ]),
        Paragraph("EMD to pay" + (" for the ADDED quarters only" if supplementary else ""), H2),
        _quarters_table(applications, with_emd=True),
        Paragraph("Pay the EMD separately for each quarter. Paying the EMD for one quarter gives no "
                  "right to bid on another.", SMALL),
        Paragraph("How to pay the EMD through SBI Collect (placeholder instructions)", H2),
        Paragraph(
            "1. Open SBI Collect (onlinesbi.sbi/sbicollect) and choose the payee: "
            f"<b>{_esc(settings.SBI_COLLECT_PAYEE)}</b>.<br/>"
            f"2. Enter your URN <b>{applicant.urn}</b> exactly as shown above, and the quarter number.<br/>"
            "3. Pay the EMD amount shown for that quarter. Make one payment per quarter.<br/>"
            "4. Keep every payment receipt.<br/>"
            "5. Bring the original documents and the receipts to the auction office. The office "
            "verifies them in person (offline); only then can you bid on those quarters.",
            BODY),
        Paragraph("Important", H2),
        Paragraph("Keep your URN confidential. These instructions are placeholders pending official "
                  "confirmation; follow the auction office's notice if it differs.", BODY),
    ]
    return _build(story, f"Intimation Slip {applicant.application_no}")
