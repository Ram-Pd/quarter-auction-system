"""Offline verification: checklist, EMD per quarter, status, audit log, roles, eligibility."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from applications import eligibility, services
from applications.models import Applicant, AuditLog, DocumentChecklistItem
from applications.tests.factories import activate, fake_aadhaar, make_applicant, make_officer, make_staff, verify_emd
from auctions.tests.factories import make_auction, make_quarter


class VerificationServiceTests(TestCase):
    def setUp(self):
        self.officer = make_officer()
        self.qa, self.qb = make_quarter("B-214"), make_quarter("C-305")
        self.applicant = make_applicant(1, [self.qa, self.qb])
        self.app_a = self.applicant.quarter_applications.get(quarter=self.qa)

    def tick_all(self):
        for item in DocumentChecklistItem.objects.filter(is_active=True):
            services.set_document_check(self.applicant, item, True, self.officer)

    def test_placeholder_checklist_exists(self):
        names = list(DocumentChecklistItem.objects.values_list("name", flat=True))
        self.assertEqual(len(names), 6)
        self.assertIn("Identity proof (Aadhaar)", names)

    def test_first_action_moves_to_documents_pending(self):
        item = DocumentChecklistItem.objects.first()
        services.set_document_check(self.applicant, item, True, self.officer)
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.status, Applicant.Status.DOCUMENTS_PENDING)

    def test_activation_blocked_until_required_documents_ticked(self):
        with self.assertRaisesMessage(services.VerificationError, "Cannot activate"):
            services.activate(self.applicant, self.officer)
        # Ticking only the required items is enough ("Other" is optional).
        for item in DocumentChecklistItem.objects.filter(required=True):
            services.set_document_check(self.applicant, item, True, self.officer)
        services.activate(self.applicant, self.officer)
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.status, Applicant.Status.ACTIVE)
        self.assertEqual(self.applicant.status_changed_by, self.officer)

    def test_emd_verification_needs_receipt_and_enough_money(self):
        with self.assertRaisesMessage(services.VerificationError, "Enter the receipt"):
            services.verify_emd(self.app_a, self.officer)
        services.record_emd(self.app_a, "SBI123", Decimal("8999"), timezone.localdate(), self.officer)
        with self.assertRaisesMessage(services.VerificationError, "less than"):
            services.verify_emd(self.app_a, self.officer)
        services.record_emd(self.app_a, "SBI123", Decimal("9000"), timezone.localdate(), self.officer)
        app = services.verify_emd(self.app_a, self.officer)
        self.assertTrue(app.emd_verified)
        self.assertEqual(app.emd_verified_by, self.officer)

    def test_unverify_needs_reason_and_is_logged(self):
        verify_emd(self.applicant, self.qa, self.officer)
        with self.assertRaises(services.VerificationError):
            services.unverify_emd(self.app_a, self.officer, "  ")
        services.unverify_emd(self.app_a, self.officer, "Receipt was for another URN")
        self.app_a.refresh_from_db()
        self.assertFalse(self.app_a.emd_verified)
        entry = AuditLog.objects.filter(action=AuditLog.Action.EMD_UNVERIFIED).get()
        self.assertEqual(entry.details["reason"], "Receipt was for another URN")
        self.assertEqual(entry.actor, self.officer)

    def test_verified_receipt_cannot_be_edited(self):
        verify_emd(self.applicant, self.qa, self.officer)
        with self.assertRaisesMessage(services.VerificationError, "Un-verify"):
            services.record_emd(self.app_a, "OTHER", Decimal("9000"), timezone.localdate(), self.officer)

    def test_reject_and_suspend(self):
        with self.assertRaises(services.VerificationError):
            services.reject(self.applicant, self.officer, "")
        with self.assertRaisesMessage(services.VerificationError, "Only an active"):
            services.suspend(self.applicant, self.officer, "reason")
        activate(self.applicant, self.officer)
        services.suspend(self.applicant, self.officer, "Dispute under review")
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.status, Applicant.Status.SUSPENDED)
        services.activate(self.applicant, self.officer)          # can be re-activated
        services.reject(self.applicant, self.officer, "Forged receipt")
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.status, Applicant.Status.REJECTED)
        with self.assertRaises(services.VerificationError):     # rejected is final
            services.activate(self.applicant, self.officer)

    def test_every_action_is_audited_with_actor(self):
        activate(self.applicant, self.officer)
        actions = set(AuditLog.objects.filter(applicant=self.applicant).values_list("action", flat=True))
        self.assertTrue({"APPLICATION_SUBMITTED", "DOCUMENT_CHECKED", "EMD_VERIFIED", "STATUS_CHANGED"} <= actions)
        self.assertFalse(AuditLog.objects.exclude(action="APPLICATION_SUBMITTED").filter(actor__isnull=True)
                         .exclude(action="DOCUMENTS_EMAILED").exists())

    def test_reveal_needs_permission_and_reason_and_is_audited(self):
        auction_admin = make_staff("aa@example.com", "Auction Admin")
        with self.assertRaises(PermissionDenied):
            services.reveal_identity_numbers(self.applicant, auction_admin, "curious")
        with self.assertRaises(services.VerificationError):
            services.reveal_identity_numbers(self.applicant, self.officer, "")
        aadhaar, _ = services.reveal_identity_numbers(self.applicant, self.officer, "Matching original card")
        self.assertEqual(aadhaar, fake_aadhaar(1))
        entry = AuditLog.objects.get(action=AuditLog.Action.IDENTITY_REVEALED)
        self.assertEqual(entry.actor, self.officer)
        self.assertNotIn(fake_aadhaar(1), str(entry.details) + entry.summary)  # the number itself is never logged


class EligibilityTests(TestCase):
    def setUp(self):
        self.officer = make_officer()
        self.qa, self.qb, self.qc = make_quarter("B-214"), make_quarter("C-305"), make_quarter("D-407")
        self.applicant = make_applicant(1, [self.qa, self.qb])

    def test_rules_in_order(self):
        self.assertIn("Register", eligibility.check(None, self.qa).reason)
        self.assertIn("did not apply", eligibility.check(self.applicant, self.qc).reason)
        self.assertIn("not active", eligibility.check(self.applicant, self.qa).reason)
        activate(self.applicant, self.officer, verify_quarters=[self.qa])
        self.assertTrue(eligibility.check(self.applicant, self.qa).allowed)
        # EMD paid for A gives no right to bid on B.
        self.assertIn("EMD for this quarter", eligibility.check(self.applicant, self.qb).reason)
        self.assertEqual(self.applicant.eligible_quarter_ids(), {self.qa.pk})

    def test_suspension_removes_eligibility(self):
        activate(self.applicant, self.officer)
        services.suspend(self.applicant, self.officer, "check")
        self.applicant.refresh_from_db()
        self.assertFalse(eligibility.check(self.applicant, self.qa).allowed)

    def test_allotment_cap(self):
        from auctions.models import Auction
        from auctions.tests.factories import make_bidder
        activate(self.applicant, self.officer)
        for quarter in [make_quarter("X-1"), make_quarter("X-2")]:
            auction = make_auction(quarter)
            _, _, participation = make_bidder(auction, 1, applicant=self.applicant)
            bid = auction.bids.create(participation=participation, amount=Decimal("45000"),
                                      client_bid_id=uuid.uuid4())
            Auction.objects.filter(pk=auction.pk).update(status=Auction.Status.CLOSED_WON, winning_bid=bid)
        self.assertEqual(eligibility.allotted_count(self.applicant), 2)
        self.assertIn("maximum of 2", eligibility.check(self.applicant, self.qa).reason)


class VerificationScreenTests(TestCase):
    def setUp(self):
        self.officer = make_officer()
        self.auction_admin = make_staff("aa@example.com", "Auction Admin")
        self.quarter = make_quarter("B-214")
        make_auction(self.quarter, starts_in=timedelta(days=2))
        self.applicant = make_applicant(1, [self.quarter])
        self.url = reverse("admin:applications_applicant_verify", args=[self.applicant.pk])

    def post(self, **data):
        return self.client.post(self.url, data, follow=True)

    def test_auction_admin_sees_no_applicant_data(self):
        self.client.force_login(self.auction_admin)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:applications_applicant_changelist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:auctions_participation_changelist")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("admin:index")), "Applicants")

    def test_ordinary_user_cannot_open_admin(self):
        self.client.force_login(self.applicant.user)
        self.assertEqual(self.client.get(self.url).status_code, 302)  # sent to the admin login

    def test_full_verification_through_the_screen(self):
        self.client.force_login(self.officer)
        page = self.client.get(self.url)
        self.assertContains(page, self.applicant.masked_aadhaar)
        self.assertNotContains(page, fake_aadhaar(1))
        self.assertContains(page, "Activation needs")

        items = list(DocumentChecklistItem.objects.filter(required=True).values_list("pk", flat=True))
        self.assertContains(self.post(action="documents", items=items), "Document checklist saved")
        application = self.applicant.quarter_applications.get()
        self.post(action="save_emd", application_id=application.pk, receipt_no="SBI-77",
                  amount_paid="9,000", payment_date=timezone.localdate().isoformat())
        self.assertContains(self.post(action="verify_emd", application_id=application.pk), "EMD verified for B-214")
        self.assertContains(self.post(action="activate"), "Applicant activated")
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.status, Applicant.Status.ACTIVE)
        self.assertTrue(eligibility.check(self.applicant, self.quarter).allowed)

    def test_bad_input_shows_error(self):
        self.client.force_login(self.officer)
        application = self.applicant.quarter_applications.get()
        future = (timezone.localdate() + timedelta(days=3)).isoformat()
        self.assertContains(self.post(action="save_emd", application_id=application.pk, receipt_no="X",
                                      amount_paid="9000", payment_date=future), "cannot be in the future")
        self.assertContains(self.post(action="reject", reason=""), "Give a reason")

    def test_reveal_is_shown_once_and_audited(self):
        self.client.force_login(self.officer)
        response = self.client.post(self.url, {"action": "reveal", "reason": "Compare with original"})
        self.assertContains(response, fake_aadhaar(1))
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.IDENTITY_REVEALED).count(), 1)
        self.assertNotContains(self.client.get(self.url), fake_aadhaar(1))  # gone after reload
