# PROGRESS: SAIL Vacant Quarter Auction System

_Last updated: 2026-10-09, end of Milestone 3_

**Test status:** 112 automated tests, all passing (`python manage.py test`).

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

## Current problems
- None known.
- PostgreSQL is **not installed** yet. It's needed before Milestone 4.
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

## Next steps: Milestone 4
1. PostgreSQL (needed for `select_for_update()` row locking).
2. Django Channels + Daphne; channel layer (in-memory for development, Redis for multi-process).
3. Participation model (anonymous "Bidder N" per auction) and Bid model.
4. Bid placement service: transaction + `select_for_update()` on the Auction row, server-side validation, duplicate protection, anti-sniping.
5. WebSocket consumer per auction: authorisation, broadcast of accepted bids, resync on reconnect.
6. Auction page with live bid history and countdown.
7. Concurrency tests on PostgreSQL.

Open questions to confirm with the mentor: is the EMD one payment for any quarter, or one per quarter? Can one person bid on several quarters at once?
