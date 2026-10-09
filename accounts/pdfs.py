"""
PDF generation with ReportLab "platypus": you build a list of flowables
(paragraphs, tables, images) and ReportLab lays them out on A4 pages.

Both functions return the PDF as bytes, ready to attach to an email.
"""
from io import BytesIO

import qrcode
from django.conf import settings
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
NOTICE = ParagraphStyle("notice", parent=BODY, fontSize=8, textColor=colors.HexColor("#b00020"),
                        alignment=1)  # centred


def qr_payload(applicant):
    """
    What the QR code on the Application Form contains. Deliberately NOT the
    URN, name, mobile or email: the QR is printable and scannable by anyone.
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


def _p(text):
    """Paragraph for a table cell."""
    return Paragraph(_esc(text).replace("\n", "<br/>"), BODY)


def _details_table(rows):
    table = Table([[_p(k), _p(v)] for k, v in rows], colWidths=[50 * mm, 120 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _build(flowables, title):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title, author=settings.AUCTION_TITLE,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    doc.build(flowables)
    return buf.getvalue()


def application_form_pdf(applicant):
    """PDF A: Auction Application Form."""
    header = Table(
        [[
            [Paragraph("Auction Application Form", TITLE),
             Paragraph(settings.AUCTION_TITLE, BODY),
             Spacer(1, 4),
             Paragraph(f"<b>Application No:</b> {applicant.application_no}", BODY),
             Paragraph(f"<b>Application Date:</b> {applicant.application_date:%d-%m-%Y}", BODY)],
            _qr_image(qr_payload(applicant)),
        ]],
        colWidths=[130 * mm, 40 * mm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    story = [
        Paragraph(TRAINING_NOTICE, NOTICE),
        Spacer(1, 6),
        header,
        Paragraph("Auction details", H2),
        _details_table([
            ("Auction", settings.AUCTION_TITLE),
            ("Auction reference", settings.AUCTION_REFERENCE),
            ("Quarter", "Chosen by the applicant after login, from the quarters "
                        "listed in the auction lobby."),
        ]),
        Paragraph("Applicant details", H2),
        _details_table([
            ("Name", applicant.name),
            ("Father's name", applicant.father_name),
            ("Mobile", applicant.mobile),
            ("Email", applicant.email),
        ]),
        Paragraph("Address", H2),
        _details_table([
            ("Address", applicant.address),
            ("State", applicant.state),
            ("PIN code", applicant.pin_code),
        ]),
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


def intimation_slip_pdf(applicant):
    """PDF B: Auction Intimation Slip (URN + EMD payment instructions)."""
    story = [
        Paragraph(TRAINING_NOTICE, NOTICE),
        Spacer(1, 6),
        Paragraph("Auction Intimation Slip", TITLE),
        Paragraph(settings.AUCTION_TITLE, BODY),
        Paragraph("URN details", H2),
        _details_table([
            ("URN", applicant.urn),
            ("URN date", f"{applicant.urn_date:%d-%m-%Y}"),
            ("Application No", applicant.application_no),
            ("Applicant name", applicant.name),
            ("Mobile", applicant.mobile),
            ("EMD amount", f"Rs. {settings.EMD_AMOUNT:,.2f} (placeholder amount)"),
        ]),
        Paragraph("How to pay the EMD (placeholder instructions)", H2),
        Paragraph(
            "1. Pay the EMD through SBI Collect, quoting your URN exactly as shown above.<br/>"
            "2. Keep the payment receipt.<br/>"
            "3. The auction office verifies payments manually (offline). This can take some time.<br/>"
            "4. After verification you can activate your account on the auction website "
            "using your email address and URN, and then choose the quarter(s) to bid on.",
            BODY),
        Paragraph("Important", H2),
        Paragraph(
            "Keep your URN confidential. Together with your email address it is used to "
            "activate your account. Never share it with anyone.", BODY),
    ]
    return _build(story, f"Intimation Slip {applicant.application_no}")
