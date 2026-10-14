"""Public home page, logged-in quarter listing, auction page (auctions/views.py)."""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.tests.factories import make_user
from applications.tests.factories import activate, make_applicant, make_officer
from auctions.models import Participation
from auctions.tests.factories import make_auction, make_bidder, make_quarter


class HomePageTests(TestCase):
    def setUp(self):
        self.live = make_auction(make_quarter("B-214"))
        self.upcoming = make_auction(make_quarter("C-305", emd_amount=7500), starts_in=timedelta(days=2))

    def test_public_quarter_list_rules_and_faq(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        for text in ["B-214", "C-305", "Sector 4, Near market", "45,000", "7,500", "Live", "Upcoming",
                     "Bidding rules", "Frequently asked questions", "allotted at most 2"]:
            self.assertContains(response, text)
        self.assertContains(response, reverse("accounts:login"))      # Login button in the corner
        self.assertContains(response, reverse("accounts:signup"))
        self.assertContains(response, "not official SAIL policy")    # placeholder wording is labelled

    @override_settings(MAX_QUARTERS_PER_APPLICANT=3, DEFAULT_AUCTION_DURATION_MINUTES=7)
    def test_rules_follow_settings(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "allotted at most 3")
        self.assertContains(response, "usually 7 minutes")

    def test_no_bidder_identity_on_public_page(self):
        applicant, _, _ = make_bidder(self.live, 1)
        body = self.client.get(reverse("home")).content.decode()
        for private in [applicant.name, applicant.urn, applicant.email]:
            self.assertNotIn(private, body)


@override_settings(APPLICATION_CLOSES_HOURS_BEFORE_AUCTION=24)
class ListingPageTests(TestCase):
    def setUp(self):
        self.qa, self.qb = make_quarter("B-214"), make_quarter("C-305")
        self.a = make_auction(self.qa, starts_in=timedelta(days=3))
        self.b = make_auction(self.qb, starts_in=timedelta(days=3))
        self.url = reverse("auctions:listing")

    def test_requires_login(self):
        self.assertRedirects(self.client.get(self.url), f"{reverse('accounts:login')}?next={self.url}")

    def test_not_registered_user_sees_register_button(self):
        self.client.force_login(make_user())
        response = self.client.get(self.url)
        self.assertContains(response, "Not registered")
        self.assertContains(response, reverse("applications:apply"))
        self.assertContains(response, "9,000")             # EMD column
        self.assertContains(response, "Not applied")

    def test_documents_pending_then_active_with_eligible_quarters(self):
        applicant = make_applicant(1, [self.qa, self.qb])
        self.client.force_login(applicant.user)
        response = self.client.get(self.url)
        self.assertContains(response, "Documents pending")
        self.assertContains(response, "Applied")
        activate(applicant, make_officer(), verify_quarters=[self.qa])
        response = self.client.get(self.url)
        self.assertContains(response, "Active")
        self.assertContains(response, "eligible to bid on 1 quarter")
        self.assertContains(response, "Eligible to bid", count=1)


class AuctionPageTests(TestCase):
    def setUp(self):
        self.auction = make_auction()
        self.url = reverse("auctions:auction_room", args=[self.auction.pk])

    def test_public_can_view_but_not_bid(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Watching")
        self.assertContains(response, "Log in to bid.")
        self.assertNotContains(response, 'id="bid-form"')

    def test_eligible_applicant_gets_a_code_and_quick_bids(self):
        applicant = make_applicant(1, [self.auction.quarter])
        activate(applicant, make_officer())
        self.client.force_login(applicant.user)
        response = self.client.get(self.url)
        self.assertContains(response, 'id="bid-form"')
        self.assertContains(response, "Bidder 1")
        self.assertContains(response, "+5 steps: Rs. 45,360")
        self.assertContains(response, "Rs. 90")   # bid step shown
        self.assertEqual(Participation.objects.filter(applicant=applicant).count(), 1)
        self.client.get(self.url)                 # visiting again: same code, no new row
        self.assertEqual(Participation.objects.filter(applicant=applicant).count(), 1)

    def test_not_eligible_applicant_sees_reason_and_gets_no_code(self):
        applicant = make_applicant(1, [self.auction.quarter])   # not verified yet
        self.client.force_login(applicant.user)
        response = self.client.get(self.url)
        self.assertNotContains(response, 'id="bid-form"')
        self.assertContains(response, "not active")
        self.assertFalse(Participation.objects.exists())

    def test_emd_for_another_quarter_is_not_enough(self):
        other = make_quarter("C-305")
        applicant = make_applicant(1, [self.auction.quarter, other])
        activate(applicant, make_officer(), verify_quarters=[other])
        self.client.force_login(applicant.user)
        response = self.client.get(self.url)
        self.assertContains(response, "EMD for this quarter has not been verified")
        self.assertNotContains(response, 'id="bid-form"')

    def test_unknown_auction_404(self):
        self.assertEqual(self.client.get(reverse("auctions:auction_room", args=[99999])).status_code, 404)
