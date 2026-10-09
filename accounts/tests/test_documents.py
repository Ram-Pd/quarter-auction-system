from io import BytesIO

from django.core import mail
from django.test import TestCase, override_settings
from pypdf import PdfReader

from accounts.emails import send_registration_documents
from accounts.pdfs import application_form_pdf, intimation_slip_pdf, qr_payload
from accounts.tests.test_generation import new_applicant


def pdf_text(data):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


@override_settings(AUCTION_TITLE="Test Auction", AUCTION_REFERENCE="TEST/REF/1", EMD_AMOUNT=12345)
class PdfTests(TestCase):
    def setUp(self):
        self.applicant = new_applicant(name="Ravi Kumar", father_name="Mohan Kumar",
                                       address="Qtr 12, Street 3\nSector 4")
        self.applicant.save()

    def test_application_form_contents(self):
        data = application_form_pdf(self.applicant)
        self.assertTrue(data.startswith(b"%PDF"))
        text = pdf_text(data)
        for expected in ["Auction Application Form", self.applicant.application_no,
                         "Ravi Kumar", "Mohan Kumar", "9876543210", "applicant1@example.com",
                         "Sector 4", "Jharkhand", "827001", "Test Auction", "TEST/REF/1",
                         "Declaration", "NOT AN OFFICIAL SAIL DOCUMENT"]:
            self.assertIn(expected, text)

    def test_application_form_does_not_contain_urn(self):
        # The URN is an activation secret; it belongs only on the Intimation Slip.
        self.assertNotIn(self.applicant.urn, pdf_text(application_form_pdf(self.applicant)))

    def test_qr_payload_has_no_personal_data(self):
        payload = qr_payload(self.applicant)
        self.assertIn(self.applicant.application_no, payload)
        for private in [self.applicant.urn, "Ravi", self.applicant.mobile, self.applicant.email]:
            self.assertNotIn(private, payload)

    def test_intimation_slip_contents(self):
        text = pdf_text(intimation_slip_pdf(self.applicant))
        for expected in ["Auction Intimation Slip", self.applicant.urn, "Ravi Kumar",
                         "9876543210", "Rs. 12,345.00", "SBI Collect", "placeholder"]:
            self.assertIn(expected, text)

    def test_markup_characters_in_user_input_do_not_break_pdf(self):
        a = new_applicant(2, name="A <b>& Co", address="<para> & stuff")
        a.save()
        self.assertIn("A <b>& Co", pdf_text(application_form_pdf(a)))


class EmailTests(TestCase):
    def test_email_has_both_pdfs_and_records_time(self):
        a = new_applicant()
        a.save()
        send_registration_documents(a)

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["applicant1@example.com"])
        self.assertIn(a.application_no, msg.subject)
        names = [att[0] for att in msg.attachments]
        self.assertEqual(names, [f"Application_Form_{a.application_no}.pdf",
                                 f"Intimation_Slip_{a.application_no}.pdf"])
        for _, content, mimetype in msg.attachments:
            self.assertEqual(mimetype, "application/pdf")
            self.assertTrue(content.startswith(b"%PDF"))
        a.refresh_from_db()
        self.assertIsNotNone(a.documents_emailed_at)
