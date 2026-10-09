"""
Close finished auctions ONCE and exit:

    python manage.py close_auctions

Use this from Windows Task Scheduler or cron (e.g. every minute). For a
continuously running worker use run_auction_worker instead. Both are safe to
run at the same time: closing is idempotent (see auctions/closing.py).
"""
from django.core.management.base import BaseCommand

from auctions.closing import close_due_auctions, retry_unsent_notifications


class Command(BaseCommand):
    help = "Close every open auction whose deadline has passed, then exit."

    def handle(self, *args, **options):
        closed = close_due_auctions()
        retry_unsent_notifications()
        for result in closed:
            self.stdout.write(f"Closed auction #{result.auction_id}: {result.status}")
        self.stdout.write(self.style.SUCCESS(f"Done. {len(closed)} auction(s) closed."))
