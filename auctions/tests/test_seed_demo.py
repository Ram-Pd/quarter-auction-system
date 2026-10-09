from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from accounts.models import Applicant
from auctions.models import Auction, Quarter


class SeedDemoTests(TestCase):
    @override_settings(DEBUG=True)
    def test_creates_demo_data_and_is_repeatable(self):
        call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", stdout=StringIO())  # second run must not duplicate anything
        self.assertEqual(Quarter.objects.count(), 8)
        self.assertEqual(Auction.objects.count(), 4)
        self.assertEqual(Applicant.objects.filter(is_activated=True).count(), 3)
        self.assertEqual(Applicant.objects.filter(is_verified=True, is_activated=False).count(), 1)

    @override_settings(DEBUG=False)
    def test_refuses_without_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
