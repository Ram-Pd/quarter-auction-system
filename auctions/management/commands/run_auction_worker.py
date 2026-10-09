"""
Background worker: keeps closing finished auctions and retrying unsent emails.

    python manage.py run_auction_worker            # runs until Ctrl+C
    python manage.py run_auction_worker --rounds 1 # one round, then exit (tests)

Run it in its own terminal next to "runserver". Checks every
AUCTION_WORKER_INTERVAL_SECONDS (default 5). Running two workers by mistake is
harmless: closing is idempotent (see auctions/closing.py).
"""
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from auctions.closing import close_due_auctions, retry_unsent_notifications

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Continuously close finished auctions and send result emails."

    def add_arguments(self, parser):
        parser.add_argument("--rounds", type=int, default=0,
                            help="Stop after this many rounds (0 = run forever).")

    def handle(self, *args, rounds=0, **options):
        interval = settings.AUCTION_WORKER_INTERVAL_SECONDS
        self.stdout.write(f"Auction worker started (every {interval}s). Press Ctrl+C to stop.")
        done = 0
        try:
            while True:
                self.run_round()
                done += 1
                if rounds and done >= rounds:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")

    def run_round(self):
        close_old_connections()  # drop dead DB connections (e.g. after a DB restart)
        try:
            for result in close_due_auctions():
                self.stdout.write(f"Closed auction #{result.auction_id}: {result.status}")
            retry_unsent_notifications()
        except Exception:
            # Never let one bad round kill the worker; log it and try again next round.
            logger.exception("Auction worker round failed")
