# PROGRESS: SAIL Vacant Quarter Auction System

_Last updated: 2026-10-09, end of Milestone 5 (all proposed milestones complete)_

**Test status:** 184 automated tests, all passing on PostgreSQL 17 (`python manage.py test`).
**Before running anything:** start PostgreSQL with `.\scripts\start_postgres.ps1` (it does not auto-start).

See also: `README.md` (setup/run/demo) and `docs/HOW_TO_CHANGE.md` (which file to edit for what).

## Milestone 1: Foundation ✅ COMPLETE
- **Project setup:** Django 5.2.18 on Python 3.13.5 (Windows 11), virtualenv `venv\`, pinned `requirements.txt`, git repo, `.gitignore`.
- **Settings:** secrets from `.env` via django-environ (`SECRET_KEY` has no default; `DEBUG` defaults to False). Optional `DATABASE_URL`, falling back to SQLite. `Asia/Kolkata`, `USE_TZ=True`. Committed `.env.example`.
- **`Quarter` model:** unique upper-case `quarter_no` plus a case-insensitive DB constraint. Decimal area and base rate with DB checks (> 0) and friendly error messages. Type A/B/C/D. Status Vacant / In Auction / Allotted.
- **`Applicant` model:** validated mobile and PIN. Unique 7-digit text URN. Unique case-insensitive email. `is_verified`, `is_activated`, nullable `OneToOneField(User, PROTECT)`. DB rule: activated ⇒ user set.
- **Sample data** (`sample_data/`, FAKE) and generator script.
- **Excel import** (`auctions/importers.py`) plus an admin upload page at `/admin/auctions/quarter/import/`. Reports all errors with row and column. All-or-nothing.

## Milestone 2: Registration, URN, PDFs, email ✅ COMPLETE
- **Libraries chosen:** ReportLab (PDF), qrcode + Pillow (QR). `pypdf` is used only by tests.
- **Automatic generation** (`Applicant.save()` in `accounts/models.py`):
  - URN: random 7 digits from `secrets` (not guessable, no leading zero). Collisions are retried using savepoints, up to 10 attempts. A duplicate *email* is not mistaken for a URN collision.
  - Application number: `QA` + year + 6-digit row id, e.g. `QA2026000001`. Written in the same transaction as the insert.
  - The URN stays editable in the admin (blank = auto) in case SAIL ever supplies URNs.
- **Public pages:**
  - `/` home page with "how it works".
  - `/register/` registration form: name, father's name, mobile, email, address, state dropdown (36 states/UTs), PIN, required declaration. Mobile, PIN, name and email are normalised.
  - `/register/done/` success page (Post/Redirect/Get). Shows the application number but **not** the URN.
- **PDFs** (`accounts/pdfs.py`):
  - Application Form: application no and date, QR code, auction details, applicant details, address, declaration, signature line.
  - Intimation Slip: URN and URN date, name, mobile, EMD amount, SBI Collect placeholder instructions.
  - Both carry a "TRAINING PROJECT - NOT AN OFFICIAL SAIL DOCUMENT" banner. User-entered text is escaped.
- **Email** (`accounts/emails.py`): one email with both PDFs attached. Records `documents_emailed_at`. Sent after the applicant is saved: if sending fails, the registration is kept, the failure is logged, and the page tells the user to contact the office.
- **Development email:** `config/email_backends.py` saves each email as a `.eml` file in `sent_emails/` (gitignored). Double-click to open it with the attachments. For SMTP, set `EMAIL_*` in `.env` (see `.env.example`).
- **Admin:** application number and `documents_emailed_at` are read-only. New action "Resend registration documents".
- **Verified end to end** on the real dev server: registered through the form, then opened the saved email and rendered both PDFs to images to check the layout.

## Milestone 3: Activation, login, password reset, auctions, lobby ✅ COMPLETE
- **Activation** (`/activate/`, `accounts/forms.py` `ActivationForm`, `accounts/services.py` `activate_applicant`):
  - Email + URN + new password, only for verified, not-yet-activated applicants.
  - Creates a Django `User` (username = URN, password hashed) inside a transaction with the applicant row locked, then logs the user in.
  - Wrong email or URN gives the same message. Once both match, the message says exactly what's wrong (not verified / already activated).
  - Django's password validators apply, including "too similar to URN".
- **Rate limiting** (`accounts/ratelimit.py`): 5 failures per email/URN and 50 per IP address within 15 minutes (all in settings). Applies to activation and login. Uses Django's cache (Redis in production).
- **Login / logout:** `/login/` with the username labelled "URN"; `/logout/` is POST only. Navigation changes when logged in.
- **Password reset:** Django's token flow at `/password-reset/`. Same response for unknown emails. Links are single-use and expire after `PASSWORD_RESET_TIMEOUT` (1 hour). User.email is kept in sync with Applicant.email.
- **Auction model** (`auctions/models.py`):
  - Quarter (PROTECT), start/end time, stored status (Open / Closed - won / Closed - no bids / Cancelled), min increment, anti-snipe extension (DurationField), current highest bid.
  - DB constraints: end > start; increment > 0; extension ≥ 0; **one OPEN auction per quarter** (partial unique constraint).
  - Phase (Upcoming / Live / Closing) is **computed from the clock**, never stored.
  - Creating an auction sets the quarter to In Auction; `cancel()` returns it to Vacant.
- **Auction admin:**
  - Only Vacant quarters are offered.
  - Quarter, start time, increment and extension lock once bidding starts. Closed or cancelled auctions are fully read-only.
  - No delete (audit); "Cancel" action instead.
- **Lobby** (`/auctions/`, activated applicants and staff only): "Live now" and "Upcoming" tables showing quarter, location, floor, area, base rate, schedule, status, live countdown, highest bid and minimum next bid. No bidder data.
- **Countdown** (`auctions/static/auctions/countdown.js`): corrects for the user's PC clock using server time and reloads when a phase changes.
- **Demo data:** `python manage.py seed_demo` (DEBUG only).
- **Maintainability:** shared form include, site CSS file with colour variables, a context processor for settings-driven text, test factories, `README.md`, `docs/HOW_TO_CHANGE.md`.
- **Verified end to end** on the real server: wrong URN, activation, logout, lobby redirect, login, lobby contents, password reset via the emailed link, login with the new password. Lobby screenshots checked at desktop and narrow widths.

## Milestone 4: PostgreSQL, Channels, live anonymous bidding ✅ COMPLETE
- **PostgreSQL 17.11**, portable install (no admin rights): programs in `%USERPROFILE%\pgsql`, data in `%USERPROFILE%\pgsql-data`, app DB `sail_auction` / user `sail_user` (CREATEDB for tests), localhost only, scram-sha-256 passwords. `scripts/start_postgres.ps1` and `stop_postgres.ps1`. `DATABASE_URL` is in `.env`.
- **Channels + Daphne:**
  - `daphne` first in INSTALLED_APPS, so `runserver` is ASGI.
  - `config/asgi.py` routes HTTP and WebSocket; `AuthMiddlewareStack` provides session login and `AllowedHostsOriginValidator` blocks cross-site sockets.
  - Channel layer is in-memory by default; `REDIS_URL` switches it to Redis.
- **Models:**
  - `Participation`: applicant + auction + `bidder_number`, shown as "Bidder N". Unique per (applicant, auction) and per (auction, number).
  - `Bid`: accepted bids only; never edited or deleted. Stores `client_bid_id` (duplicate protection), `previous_highest` and `deadline_extended_to` for audit.
  - DB backstops: unique (participation, client_bid_id); unique (auction, amount); amount > 0.
  - `Auction.original_end_time` keeps the scheduled deadline (data migration filled existing rows).
- **Bidding service** (`auctions/bidding.py`), everything inside `transaction.atomic()` with `select_for_update(of=("self",))` on the Auction row:
  1. The auction must be LIVE.
  2. The applicant must have joined.
  3. The same `client_bid_id` returns the earlier bid (duplicate, not a new bid).
  4. First bid ≥ base rate; later bids ≥ highest + increment.
  5. You can't outbid yourself.
  6. A bid in the final 60 s sets the deadline to now + extension, and never shortens it.
  - Broadcast happens only after commit (`transaction.on_commit`).
  - `join_auction` numbers codes under the same lock. `Auction.cancel()` also takes the lock and broadcasts.
- **Realtime** (`auctions/realtime.py`): the only place browser messages are built. They contain codes, amounts and times only. Includes `server_now` for clock correction. One group per auction (`auction_<id>`).
- **Consumer** (`auctions/consumers.py`):
  - Per-auction authorisation: logged in (else close 4401); auction exists (else 4404); joined participant or staff watcher (else 4403).
  - Messages: `bid` and `sync`. Rejections are sent only to the sender.
  - Anti-flooding: 1 bid per second per connection.
  - Staff can watch but not bid.
- **Auction page** (`/auctions/<id>/`, `auction_room.js`):
  - Join button, bid form, "Use minimum", live highest/minimum/countdown (red in the final minute), extension notice, bid history with "(you)", connection status.
  - Auto-reconnect with backoff (1 s to 15 s) and resync snapshot. Resync when the tab becomes visible. Bid button disabled while offline or awaiting a reply, with a 10 s timeout.
  - "You have been outbid" notice. The bid box follows the new minimum.
- **Lobby:** "Open" button per auction and a "Joined" marker.
- **Admin:**
  - Bids are read-only and show the code only; the auction page lists its bids read-only.
  - **Participation (identity ↔ code) is superusers only.**
  - Admin edits to an auction are pushed live to open pages.
- **Tests:**
  - `test_bidding.py`: every rule, anti-sniping, broadcast-after-commit.
  - `test_concurrency.py`: 10 threads bidding at the same instant on PostgreSQL; exactly one winner, the chain stays valid, simultaneous joins get unique codes. **Verified that 2 of these tests FAIL when `select_for_update` is removed.**
  - `test_consumers.py`: authorisation, broadcast, privacy, isolation between auctions, resync, flooding, cancel push.
  - `test_auction_room.py`: page, join, admin privacy.
- **Real-browser end-to-end** (headless Edge via DevTools + a second WebSocket client, on Daphne + PostgreSQL):
  - The page connects and shows Live; the other bidder's bid appears instantly; a bid typed in the page is accepted.
  - Server killed: "Reconnecting…" and bidding disabled. Server restarted: auto-reconnect, and a bid missed while offline is shown, with the outbid message.

## Milestone 5: Automatic closure, winner email, production settings, documentation ✅ COMPLETE
- **Worker choice:** management commands, no extra services (Celery and APScheduler were considered; see `docs/ARCHITECTURE.md`).
  - `run_auction_worker`: loops every `AUCTION_WORKER_INTERVAL_SECONDS` (5).
  - `close_auctions`: one round, for Task Scheduler or cron.
  - The worker survives errors and refreshes DB connections each round.
- **Closure** (`auctions/closing.py` `close_auction`):
  - Locks the auction row and re-checks that it is OPEN and past its deadline, otherwise does nothing. This makes it idempotent.
  - Highest amount wins (earliest on a theoretical tie). With a winner: status CLOSED, `winning_bid` stored, quarter Allotted. Without bids: CLOSED_NO_BIDS, quarter Vacant.
  - Broadcast and emails run after commit.
  - Also triggered when a browser's countdown hits zero (consumer `sync`), so results appear within about 3 s even without the worker.
- **DB backstops:** `quarter_won_only_once` (partial unique: one CLOSED auction per quarter); `winning_bid_matches_status`.
- **Winner email** (`auctions/emails.py`): congratulations, quarter number, sector/location, floor, area, winning amount, bidder code, placeholder next steps, application number.
  - Sent once: lock, check `winner_notified_at`, send, set timestamp.
  - If sending fails, the timestamp stays empty and the worker retries. The tiny "sent but commit failed" window is documented.
  - Loser emails are implemented and off by default (`AUCTION_NOTIFY_LOSERS`).
- **Display:**
  - The auction page shows a result panel ("Congratulations, you won!" or "Won by Bidder N"), hides the bid form and minimum, and shows "Bidding closed".
  - The lobby has a "Recently closed" section (codes only).
  - The admin list shows the result by code, with actions "Close now if due" and "Send result emails (unsent only)".
- **Production settings** (on automatically when `DEBUG=False`): https redirect, secure cookies, HSTS (30 days), optional proxy header, `CSRF_TRUSTED_ORIGINS`, 8-hour sessions, HttpOnly cookies, Redis cache when `REDIS_URL` is set, console logging for app errors. `check --deploy` leaves only 2 optional HSTS warnings (subdomains/preload, policy decisions).
- **Documentation:**
  - `docs/ARCHITECTURE.md`: architecture, ER, workflow and bid-sequence diagrams (Mermaid), DB rules, design reasons.
  - `docs/DEMO_SCRIPT.md`: about 15 minutes, step by step, with likely questions.
  - `docs/DEPLOYMENT.md`: production checklist.
  - README and HOW_TO_CHANGE updated.
- **Tests:**
  - `test_closing.py`: rules, no-bid outcome, idempotency, cancelled, DB refuses a double award, winner email contents, failed-email retry sends once, losers on/off, commands, worker resilience, result pages.
  - `test_concurrency.py`: 8 simultaneous closers close once with one email; bids racing the deadline keep winner = highest and no bid after the deadline. **Verified the closer test FAILS (2 closures) without the lock.**
  - `test_consumers.py`: a sync after the deadline closes the auction and pushes the result to every tab.
- **Real-browser end-to-end** (no worker running):
  - Bids in the final seconds extended the deadline (21:09:19 → 21:09:29) and showed the notice.
  - The countdown turned red; at the deadline the page switched to Closed with "Congratulations, you won!".
  - Exactly one winner email was written. The losing bidder's page shows "Won by Bidder 1" and "Bidding closed".

## Current problems
- None known.
- PostgreSQL is a portable install and **must be started after every reboot** (`scripts\start_postgres.ps1`). The portable binaries are not code-signed (normal for EnterpriseDB's zip); they were downloaded over HTTPS from EnterpriseDB, the source postgresql.org links to.
- Redis is not installed. It isn't needed for one server process; it's required for multi-process production (`REDIS_URL`).
- The worker must be running (or a browser watching) for auctions to close at their deadline. In production, run it as a service.
- Registration has no CAPTCHA or rate limiting (out of scope for now; worth adding before any public deployment).
- The registration form says "email already registered", which reveals that an email address is registered. Accepted for usability; revisit if the mentor considers it a privacy issue.
- `manage.py check --deploy` in production mode shows 2 optional warnings (HSTS subdomains/preload). These are policy decisions for the real domain.
- Without `REDIS_URL`, rate-limit counters and WebSocket groups are per process (fine for one process; production needs Redis).
- An applicant can currently win several quarters (open question 8, out of scope).

## Assumptions (placeholders, NOT official SAIL rules)
- URN = system-generated random 7-digit number, stored as text (open question 1).
- EMD amount = `EMD_AMOUNT` setting, default Rs. 10,000 placeholder. SBI Collect instructions are placeholder text (open question 2).
- Eligibility = admin ticks `is_verified` after offline EMD check (open question 3).
- Base Rate unit unknown; labeled as a placeholder (open question 12).
- One Applicant record per email address.
- Mobile validation assumes Indian 10-digit numbers starting 6–9.
- Imported quarters must have Status "Vacant" or blank.
- One EMD payment per applicant makes them eligible to bid on any quarter. Confirm with mentor.
- An applicant may bid in several simultaneous auctions. Winning more than one is out of scope (open question 8).
- The Application Form shows general auction details (`AUCTION_TITLE` / `AUCTION_REFERENCE` settings) and states that the quarter is chosen after login.
- The QR code contains only `QA-APPLICATION|<application no>|<date>`, no personal data and no URN.
- The first bid must be at least the quarter's base rate. Later bids must beat the highest bid by the auction's minimum increment.
- Default minimum increment Rs. 100 and default anti-snipe extension 2 minutes (both editable per auction).
- Staff accounts may view the lobby (for monitoring and demos).
- A bidder cannot outbid themselves while holding the highest bid.
- Equal bids: the first one accepted wins; later equal bids are "too low" (open question 6).
- Anti-snipe window is 60 s (setting). The new deadline is now + the auction's extension, never earlier than the current deadline.
- Bidder codes are numbered in join order per auction ("Bidder 1, 2, …").
- Staff may watch an auction page live but cannot bid.
- Admins may cancel an auction even after bids were placed; the bids are kept for audit.
- No valid bids: status CLOSED_NO_BIDS and the quarter goes back to Vacant (open question 7).
- Losing bidders are not emailed unless `AUCTION_NOTIFY_LOSERS=True` (open question 9).
- Winner email "next steps" are placeholder text.
- All sample figures are fake.

## Decisions made
- `on_delete=PROTECT` on Applicant→User (audit records never silently deleted).
- Constraints in both validators (friendly messages) and the DB (last line of defence).
- The importer is a plain function, separate from the admin view, for testability.
- Excel import is all-or-nothing.
- Applicant `__str__` shows only the application number.
- **Registration is general, not per quarter** (confirmed by user, 2026-10-09). Quarter choice happens in the lobby after login. Applicant ↔ Auction link = Participation (Milestone 4).
- **The URN is delivered only by email** (in the Intimation Slip), never on screen, so email + URN at activation proves control of the mailbox.
- Registration email is sent synchronously after saving. The admin can resend it if it fails.

- Auction status stores only facts the clock can't provide. Upcoming / Live / Closing is computed (no job needed to flip states).
- Business actions live in `services.py` / model methods. Views stay thin.

- Bid rules live in one function (`place_bid`), and browser messages are built in one module (`realtime.py`), so the rules and the privacy guarantee are each in one place.
- Synchronous consumer (runs in a thread), so it can use the ORM like a normal view.
- Bidder codes are stored as a number (`bidder_number`) and displayed as "Bidder N". The brief's "unique (auction, anonymous_code)" is enforced as unique (auction, bidder_number).
- Worker = plain management command (no Celery/Redis requirement). Closure is idempotent, so running two workers, or a worker plus a browser trigger, is safe.
- Closure is also triggered by a watching browser at the deadline, for an immediate result.

## Next steps (after the five proposed milestones)
1. **Ask the mentor** about the open questions in CLAUDE.md section 12, especially: EMD (one for all quarters or one per quarter?), the Base Rate unit, whether one person may win several quarters, the official increment and extension values, record retention, and the approved deployment environment.
2. Replace placeholder texts (SBI Collect instructions, winner "next steps", auction title/reference, EMD amount) with official wording once provided.
3. Before any real deployment: CAPTCHA or rate limit on registration, Redis, HTTPS proxy, backups (see `docs/DEPLOYMENT.md`).
4. Project report: use `docs/ARCHITECTURE.md` (diagrams can be exported from https://mermaid.live) and `docs/DEMO_SCRIPT.md`.
5. Optional improvements: admin dashboard of live auctions; CSV export of bid history for audits; SAIL-supplied URN import if URNs come from SAIL (open question 1).
