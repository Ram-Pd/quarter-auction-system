from io import StringIO

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from accounts.models import User
from applications.models import Applicant
from auctions.models import Auction, Quarter


class SeedDemoTests(TestCase):
    @override_settings(DEBUG=True)
    def test_creates_demo_data_and_is_repeatable(self):
        call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", stdout=StringIO())  # second run must not duplicate anything
        self.assertEqual(Quarter.objects.count(), 11)                 # 8 samples + 3 live demo quarters
        self.assertEqual(Auction.objects.filter(status=Auction.Status.SCHEDULED).count(), 11)
        self.assertEqual(Applicant.objects.filter(status=Applicant.Status.ACTIVE).count(), 3)
        self.assertEqual(Applicant.objects.filter(status=Applicant.Status.DOCUMENTS_PENDING).count(), 1)
        self.assertTrue(User.objects.filter(email="demo5@example.com", applicant__isnull=True).exists())
        self.assertTrue(User.objects.get(email="officer@example.com").groups.filter(
            name="Verification Officer").exists())
        demo1 = Applicant.objects.get(user__email="demo1@example.com")
        live = Auction.objects.get(quarter__quarter_no="L-301")
        self.assertEqual(live.phase(), Auction.Phase.LIVE)
        self.assertTrue(demo1.is_eligible_for(live.quarter))
        self.assertEqual(len(mail.outbox), 0)   # demo emails go to sent_emails/, never SMTP / the outbox

    @override_settings(DEBUG=False)
    def test_refuses_without_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
