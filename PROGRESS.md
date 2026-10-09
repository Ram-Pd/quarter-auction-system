# PROGRESS: SAIL Vacant Quarter Auction System

_Last updated: 2026-10-09, end of Milestone 4_

**Test status:** 162 automated tests, all passing on PostgreSQL 17 (`python manage.py test`).
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

## Current problems
- None known.
- PostgreSQL is a portable install and **must be started after every reboot** (`scripts\start_postgres.ps1`). The portable binaries are not code-signed (normal for EnterpriseDB's zip); they were downloaded over HTTPS from EnterpriseDB, the source postgresql.org links to.
- Redis is not installed. It isn't needed for one server process; it's required for multi-process production (`REDIS_URL`).
- The browser display of an anti-snipe extension is covered by unit tests on the server side, but wasn't exercised in the real-browser run.
- Auctions whose deadline has passed stay "Closing" until the closure job exists (Milestone 5).
- Registration has no CAPTCHA or rate limiting (out of scope for now; worth adding before any public deployment).
- The registration form says "email already registered", which reveals that an email address is registered. Accepted for usability; revisit if the mentor considers it a privacy issue.
- `manage.py check --deploy` shows 5 warnings (DEBUG, HTTPS, secure cookies, HSTS). Expected in development; production settings are planned for Milestone 5.
- The rate-limit counters use the in-memory cache: per process, and reset on restart. Switch CACHES to Redis for production.

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
- All sample figures are fake.

## Decisions made
- `on_delete=PROTECT` on Applicant→User (audit records never silently deleted).
- Constraints in both validators (friendly messages) and the DB (last line of defence).
- The importer is a plain function, separate from the admin view, for testability.
- Excel import is all-or-nothing.
- Applicant `__str__` shows only the application number.
- **Registration is general, not per quarter** (confirmed by user, 2026-10-09). Quarter choice happens in the lobby after login. Applicant ↔ Auction link = Participation (Milestone 4).
- **The URN is delivered only by email** (in the Intimation Slip), never on screen, so email + URN at activation proves control of the mailbox.
- Email is sent synchronously after saving. A background queue isn't needed yet; reconsider when the background worker is chosen in Milestone 5.

- Auction status stores only facts the clock can't provide. Upcoming / Live / Closing is computed (no job needed to flip states).
- Business actions live in `services.py` / model methods. Views stay thin.

- Bid rules live in one function (`place_bid`), and browser messages are built in one module (`realtime.py`), so the rules and the privacy guarantee are each in one place.
- Synchronous consumer (runs in a thread), so it can use the ORM like a normal view.
- Bidder codes are stored as a number (`bidder_number`) and displayed as "Bidder N". The brief's "unique (auction, anonymous_code)" is enforced as unique (auction, bidder_number).

## Next steps: Milestone 5
1. Background closure job: find OPEN auctions past end_time and close them atomically and idempotently (lock, re-check, set CLOSED / CLOSED_NO_BIDS, store winner, quarter → Allotted only with a winner). Choose the scheduler (explain options).
2. Winner email, exactly once (guard against duplicates). Loser emails off by default.
3. Broadcast the closure to open pages; show results in the lobby ("Recently closed").
4. Tests: idempotency with simultaneous closers, no-bid outcome, email once.
5. Production settings (HTTPS, secure cookies, HSTS, Redis cache/channel layer), documentation (architecture, ER and workflow diagrams, demo script).

Open questions to confirm with the mentor: is the EMD one payment for any quarter, or one per quarter? Can one person bid on several quarters at once?
