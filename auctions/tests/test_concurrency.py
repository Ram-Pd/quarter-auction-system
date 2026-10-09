"""
Simultaneous bids, on a real PostgreSQL database.

Each thread is a different bidder with its OWN database connection. A
threading.Barrier holds them all at the starting line and releases them at
the same instant, so their transactions really do overlap. Only the row lock
(select_for_update in auctions/bidding.py) keeps the result correct.

TransactionTestCase is used (not TestCase) because TestCase wraps each test in
one transaction that other connections can't see.
"""
import threading
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless

from django.core import mail
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from auctions.bidding import BidRejected, place_bid
from auctions.closing import close_auction
from auctions.models import Auction, Bid
from auctions.tests.factories import make_auction, make_bidder

THREADS = 10


def run_simultaneously(jobs):
    """Run each job in its own thread, all released at once. Returns results in order."""
    barrier = threading.Barrier(len(jobs))
    results = [None] * len(jobs)

    def worker(i, job):
        try:
            barrier.wait()
            results[i] = job()
        except BidRejected as rejected:
            results[i] = rejected
        except Exception as error:  # surface unexpected errors in the test failure
            results[i] = error
        finally:
            connection.close()  # each thread opened its own connection

    threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


@skipUnless(connection.vendor == "postgresql", "Row locking needs PostgreSQL")
class SimultaneousBidTests(TransactionTestCase):

    def setUp(self):
        # Base rate 4500, increment 100.
        self.auction = make_auction(min_increment=Decimal("100"))
        self.bidders = [make_bidder(self.auction, n)[0] for n in range(1, THREADS + 1)]

    def bid_job(self, applicant, amount):
        return lambda: place_bid(self.auction.pk, applicant, amount, uuid.uuid4())

    def test_same_amount_at_same_moment_only_one_wins(self):
        results = run_simultaneously([self.bid_job(a, "4500") for a in self.bidders])

        accepted = [r for r in results if not isinstance(r, Exception)]
        rejected = [r for r in results if isinstance(r, BidRejected)]
        unexpected = [r for r in results if isinstance(r, Exception) and not isinstance(r, BidRejected)]
        self.assertEqual(unexpected, [])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), THREADS - 1)
        self.assertTrue(all(r.code == "too_low" for r in rejected))  # they saw the winner's bid
        self.assertEqual(Bid.objects.count(), 1)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.current_highest_bid, Decimal("4500"))

    def test_different_amounts_at_same_moment_keep_the_chain_valid(self):
        # Amounts 4500, 4550, 4600 ... some are only 50 apart, so whether they
        # are accepted depends on the order the lock hands them out.
        amounts = [str(4500 + 50 * i) for i in range(THREADS)]
        results = run_simultaneously([self.bid_job(a, amt) for a, amt in zip(self.bidders, amounts)])
        unexpected = [r for r in results if isinstance(r, Exception) and not isinstance(r, BidRejected)]
        self.assertEqual(unexpected, [])

        chain = list(Bid.objects.filter(auction=self.auction).order_by("created_at"))
        self.assertGreaterEqual(len(chain), 1)
        # Every accepted bid obeyed the rules against the bid accepted just before it.
        self.assertGreaterEqual(chain[0].amount, Decimal("4500"))
        self.assertIsNone(chain[0].previous_highest)
        for before, after in zip(chain, chain[1:]):
            self.assertEqual(after.previous_highest, before.amount)
            self.assertGreaterEqual(after.amount, before.amount + Decimal("100"))
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.current_highest_bid, chain[-1].amount)

    def test_many_rounds_stay_consistent(self):
        """5 rounds of everyone bidding minimum-next at once: exactly one winner per round."""
        for _ in range(5):
            self.auction.refresh_from_db()
            target = str(self.auction.minimum_next_bid)
            leader = Bid.objects.filter(auction=self.auction).order_by("-created_at").first()
            # The current leader can't outbid themselves, so leave them out.
            bidders = [a for a in self.bidders
                       if not leader or leader.participation.applicant_id != a.pk]
            before = Bid.objects.count()
            run_simultaneously([self.bid_job(a, target) for a in bidders])
            self.assertEqual(Bid.objects.count(), before + 1)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.current_highest_bid, Decimal("4900"))  # 4500 + 4 x 100


@skipUnless(connection.vendor == "postgresql", "Row locking needs PostgreSQL")
class SimultaneousJoinTests(TransactionTestCase):
    def test_simultaneous_joins_get_unique_codes(self):
        from accounts.tests.factories import make_activated_applicant
        from auctions.bidding import join_auction

        auction = make_auction()
        applicants = [make_activated_applicant(n)[0] for n in range(1, THREADS + 1)]
        results = run_simultaneously([(lambda a=a: join_auction(auction, a)) for a in applicants])
        self.assertTrue(all(not isinstance(r, Exception) for r in results), results)
        numbers = sorted(p.bidder_number for p in results)
        self.assertEqual(numbers, list(range(1, THREADS + 1)))


class AuctionStatusUnchangedTests(TransactionTestCase):
    """Sanity check that TransactionTestCase data is cleaned between tests."""
    def test_starts_empty(self):
        self.assertEqual(Auction.objects.count(), 0)


@skipUnless(connection.vendor == "postgresql", "Row locking needs PostgreSQL")
class SimultaneousClosureTests(TransactionTestCase):

    def test_many_closers_at_once_close_exactly_once(self):
        auction = make_auction()
        bidder = make_bidder(auction, 1)[0]
        place_bid(auction.pk, bidder, "4500", uuid.uuid4())
        Auction.objects.filter(pk=auction.pk).update(end_time=timezone.now() - timedelta(seconds=1))

        results = run_simultaneously([lambda: close_auction(auction.pk) for _ in range(8)])

        self.assertEqual([type(r) for r in results if isinstance(r, Exception)], [])
        self.assertEqual(sum(r.closed_now for r in results), 1)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.CLOSED)
        self.assertEqual(len(mail.outbox), 1)          # exactly one winner email
        self.assertIsNotNone(auction.winner_notified_at)

    def test_bids_racing_the_deadline_stay_consistent(self):
        """Bidders keep bidding while a closer keeps trying to close at the deadline."""
        auction = make_auction(anti_snipe_extension=timedelta(0))  # no extensions in this test
        bidders = [make_bidder(auction, n)[0] for n in range(1, 7)]
        # Everyone has joined; now the deadline is 1 second away.
        Auction.objects.filter(pk=auction.pk).update(end_time=timezone.now() + timedelta(seconds=1))

        def keep_bidding(applicant):
            def job():
                accepted = 0
                for _ in range(40):
                    current = Auction.objects.get(pk=auction.pk)
                    try:
                        place_bid(auction.pk, applicant, str(current.minimum_next_bid), uuid.uuid4())
                        accepted += 1
                    except BidRejected as rejected:
                        if rejected.code == "closed":
                            break
                    time.sleep(0.02)
                return accepted
            return job

        def keep_closing():
            for _ in range(200):
                if close_auction(auction.pk).closed_now:
                    return "closed"
                time.sleep(0.01)
            return "never closed"

        results = run_simultaneously([keep_bidding(a) for a in bidders] + [keep_closing])
        self.assertEqual(results[-1], "closed")
        self.assertEqual([r for r in results if isinstance(r, Exception)], [])

        auction.refresh_from_db()
        bids = list(Bid.objects.filter(auction=auction))
        self.assertTrue(bids, "some bids should have been accepted before the deadline")
        highest = max(bids, key=lambda b: b.amount)
        self.assertEqual(auction.status, Auction.Status.CLOSED)
        self.assertEqual(auction.winning_bid, highest)                      # winner = highest bid
        self.assertTrue(all(b.created_at < auction.end_time for b in bids))  # nothing after deadline


@skipUnless(connection.vendor == "postgresql", "Row locking needs PostgreSQL")
class OneQuarterAtATimeConcurrencyTests(TransactionTestCase):
    def test_simultaneous_first_bids_in_two_auctions_only_one_accepted(self):
        """The same person fires first bids at two different quarters at the same instant."""
        from auctions.bidding import join_auction
        from auctions.tests.factories import make_quarter

        first = make_auction(make_quarter("B-214"))
        second = make_auction(make_quarter("C-305"))
        applicant = make_bidder(first, 1)[0]
        join_auction(second, applicant)

        for _ in range(5):  # repeat to give a race every chance to show up
            Bid.objects.all().delete()  # start each round fresh
            Auction.objects.update(current_highest_bid=None)
            results = run_simultaneously([
                lambda: place_bid(first.pk, applicant, "4500", uuid.uuid4()),
                lambda: place_bid(second.pk, applicant, "4500", uuid.uuid4()),
            ])
            accepted = [r for r in results if not isinstance(r, Exception)]
            rejected = [r for r in results if isinstance(r, BidRejected)]
            self.assertEqual(len(accepted), 1, results)
            self.assertEqual(rejected[0].code, "one_quarter_at_a_time")
            self.assertEqual(Bid.objects.count(), 1)
