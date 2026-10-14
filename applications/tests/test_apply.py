"""'Register for bidding': form, URN, emails with the two PDFs, add quarters."""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from pypdf import PdfReader

from accounts.tests.factories import make_user
from applications.models import Applicant, AuditLog, QuarterApplication
from applications.pdfs import qr_payload
from applications.tests.factories import fake_aadhaar, fake_pan, make_applicant
from auctions.tests.factories import make_auction, make_quarter


def pdf_text(content):
    return " ".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)


def form_data(quarters, n=1, **overrides):
    data = {"name": "Ravi Kumar", "father_name": "Mohan Kumar", "address": "Qr 12, Sector 4\nBokaro",
            "state": "Jharkhand", "pin_code": "827 004", "aadhaar": fake_aadhaar(n), "pan": fake_pan(n).lower(),
            "quarters": [q.pk for q in quarters], "declaration": "on"}
    data.update(overrides)
    return data


@override_settings(APPLICATION_CLOSES_HOURS_BEFORE_AUCTION=24)
class ApplyPageTests(TestCase):
    def setUp(self):
        self.user = make_user(full_name="Ravi Kumar")
        self.client.force_login(self.user)
        # Bidding in 3 days: open for applications. Another in 2 hours: closed (24-hour cut-off).
        self.q1 = make_quarter("B-214", emd_amount=Decimal("9000"))
        self.q2 = make_quarter("C-305", emd_amount=Decimal("7500"))
        self.late = make_quarter("D-407")
        for q in (self.q1, self.q2):
            make_auction(q, starts_in=timedelta(days=3), lasts=timedelta(minutes=5))
        make_auction(self.late, starts_in=timedelta(hours=2), lasts=timedelta(minutes=5))

    def submit(self, quarters, **overrides):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("applications:apply"), form_data(quarters, **overrides))

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("applications:apply"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('applications:apply')}")

    def test_form_prefills_name_and_lists_only_open_quarters_with_emd(self):
        response = self.client.get(reverse("applications:apply"))
        self.assertContains(response, 'value="Ravi Kumar"')
        self.assertContains(response, 'data-emd="9000.00"')
        self.assertContains(response, "C-305")
        self.assertNotContains(response, "D-407")   # application window closed

    def test_submit_creates_application_and_emails_two_pdfs_once(self):
        response = self.submit([self.q1, self.q2])
        self.assertRedirects(response, reverse("applications:mine"))
        applicant = Applicant.objects.get(user=self.user)
        self.assertEqual(applicant.status, Applicant.Status.REGISTERED)
        self.assertEqual(applicant.pin_code, "827004")
        self.assertRegex(applicant.urn, r"^\d{7}$")
        self.assertEqual([a.emd_amount for a in applicant.quarter_applications.order_by("quarter__quarter_no")],
                         [Decimal("9000"), Decimal("7500")])
        self.assertIsNotNone(applicant.documents_emailed_at)
        self.assertTrue(AuditLog.objects.filter(applicant=applicant,
                                                action=AuditLog.Action.APPLICATION_SUBMITTED).exists())

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.user.email])
        names = [a[0] for a in message.attachments]
        self.assertEqual(names, [f"Application_Form_{applicant.application_no}.pdf",
                                 f"Intimation_Slip_{applicant.application_no}.pdf"])
        self.assertIn("Total EMD: Rs. 16,500.00", message.body)

        # PRIVACY: never the full Aadhaar / PAN in the email body or the PDFs.
        form_text, slip_text = (pdf_text(a[1]) for a in message.attachments)
        for text in (message.body, form_text, slip_text):
            self.assertNotIn(fake_aadhaar(1), text.replace(" ", ""))
            self.assertNotIn(fake_pan(1), text)

        # Application Form: number, date, URN, applicant, quarters, masked IDs, declaration.
        for expected in [applicant.application_no, applicant.urn, "Ravi Kumar", "Mohan Kumar", "B-214", "C-305",
                         applicant.masked_aadhaar, "Declaration"]:
            self.assertIn(expected, form_text)
        # Intimation Slip: URN, each quarter's EMD and the total, SBI Collect instructions.
        for expected in [applicant.urn, "9,000.00", "7,500.00", "Total EMD", "16,500.00", "SBI Collect"]:
            self.assertIn(expected, slip_text)

        # Refreshing the next page does not submit or email again (Post/Redirect/Get).
        self.client.get(reverse("applications:mine"))
        self.assertEqual(len(mail.outbox), 1)

    def test_qr_code_holds_no_personal_data(self):
        self.submit([self.q1])
        applicant = Applicant.objects.get(user=self.user)
        payload = qr_payload(applicant)
        self.assertIn(applicant.application_no, payload)
        for private in [applicant.urn, applicant.name, self.user.email, fake_aadhaar(1)]:
            self.assertNotIn(private, payload)

    def test_second_application_not_possible(self):
        self.submit([self.q1])
        self.assertRedirects(self.client.get(reverse("applications:apply")), reverse("applications:mine"))

    def test_validation_errors(self):
        good = fake_aadhaar(1)
        cases = {
            "aadhaar": good[:-1] + str((int(good[-1]) + 1) % 10),   # wrong check digit
            "pan": "ABC1234567",
            "pin_code": "0123",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                response = self.submit([self.q1], **{field: value})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors.get(field))
        response = self.submit([])
        self.assertContains(response, "Select at least one quarter.")
        response = self.submit([self.late])      # closed quarter can't be forced in by a crafted POST
        self.assertTrue(response.context["form"].errors.get("quarters"))
        self.assertFalse(Applicant.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_duplicate_aadhaar_is_reported(self):
        make_applicant(1, user=make_user(2))
        response = self.submit([self.q1])
        self.assertContains(response, "This Aadhaar number is already registered.")

    def test_numbers_are_not_echoed_back_on_errors_from_other_users(self):
        # The page for MY application shows only masked numbers.
        self.submit([self.q1])
        response = self.client.get(reverse("applications:mine"))
        self.assertNotContains(response, fake_aadhaar(1))
        self.assertContains(response, f"XXXX XXXX {fake_aadhaar(1)[-4:]}")

    def test_email_failure_keeps_the_application(self):
        from unittest import mock
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=OSError("SMTP down")):
            response = self.submit([self.q1])
        self.assertRedirects(response, reverse("applications:mine"))
        applicant = Applicant.objects.get(user=self.user)
        self.assertIsNone(applicant.documents_emailed_at)
        self.assertContains(self.client.get(reverse("applications:mine")), "Not sent")


@override_settings(APPLICATION_CLOSES_HOURS_BEFORE_AUCTION=24)
class AddQuartersTests(TestCase):
    def setUp(self):
        self.q1, self.q2, self.q3 = (make_quarter(n) for n in ["B-214", "C-305", "D-407"])
        for q in (self.q1, self.q2, self.q3):
            make_auction(q, starts_in=timedelta(days=3))
        self.applicant = make_applicant(1, [self.q1])
        self.client.force_login(self.applicant.user)

    def test_adding_quarters_sends_slip_for_added_only(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("applications:add"), {"quarters": [self.q2.pk, self.q3.pk]})
        self.assertRedirects(response, reverse("applications:mine"))
        self.assertEqual(self.applicant.quarter_applications.count(), 3)
        self.assertEqual(len(mail.outbox), 1)
        attachment = mail.outbox[0].attachments
        self.assertEqual(len(attachment), 1)
        text = pdf_text(attachment[0][1])
        self.assertIn("supplementary", text)
        self.assertIn("C-305", text)
        self.assertIn("D-407", text)
        self.assertNotIn("B-214", text)
        self.assertEqual(QuarterApplication.objects.filter(slip_emailed_at__isnull=False).count(), 2)

    def test_already_applied_quarters_are_not_offered(self):
        response = self.client.get(reverse("applications:add"))
        self.assertNotContains(response, 'value="%d"' % self.q1.pk)
        self.assertContains(response, "C-305")

    def test_rejected_applicant_cannot_add(self):
        Applicant.objects.filter(pk=self.applicant.pk).update(status=Applicant.Status.REJECTED)
        response = self.client.post(reverse("applications:add"), {"quarters": [self.q2.pk]})
        self.assertRedirects(response, reverse("applications:mine"))
        self.assertEqual(self.applicant.quarter_applications.count(), 1)
