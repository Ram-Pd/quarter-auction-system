# How to change things

A map from **"I want to change X"** to **the file to edit**. Keep this up to date
when you move code around.

After any change, run the tests: `python manage.py test`

---

## 0. Where everything is (file map)

Each file has ONE job. If you know the job, you know the file.

```
config/
  settings.py            all settings; business values at the BOTTOM ("PROJECT SETTINGS")
  urls.py                top-level URLs (home page + includes of each app's urls.py)
  asgi.py                HTTP + WebSocket wiring (Daphne)
  mail.py                build_email(): turns email templates into an email
  email_backends.py      dev email: .eml file in sent_emails/ AND printed to the console
  context_processors.py  values every page template can use (AUCTION_TITLE, MAX_QUARTERS_PER_APPLICANT, ...)

accounts/                 LOGIN ACCOUNTS
  models.py              User (email login, no username), EmailOTP
  otp.py                 send_signup_otp(), verify_signup_otp(): ALL sign-up code rules
  forms.py               sign-up, code, password, login forms
  views.py               the 3 sign-up pages (details -> code -> password)
  urls.py                /signup/..., /login/, /logout/, /password-reset/...
  ratelimit.py           counters that slow down password guessing and code spamming
  admin.py               User admin (email login), read-only OTP list (superusers)
  templates/accounts/    page templates; emails/ = OTP and password-reset wording

applications/             REGISTER FOR BIDDING AND OFFLINE VERIFICATION
  models.py              Applicant, QuarterApplication (EMD per quarter), DocumentChecklistItem,
                         DocumentCheck, AuditLog
  services.py            ALL actions: submit_application, add_quarters, set_document_check,
                         record_emd, verify_emd, unverify_emd, activate, reject, suspend,
                         reveal_identity_numbers (each writes the audit log)
  eligibility.py         WHO MAY BID ON WHICH QUARTER (one place; used by pages, sockets, bidding, closure)
  crypto.py              Aadhaar/PAN encryption + keyed hash (keys from .env)
  validators.py          Aadhaar (Verhoeff) and PAN format checks, masking
  forms.py               Register-for-bidding form, add-quarters form
  views.py               /apply/, /apply/mine/, /apply/add/
  pdfs.py                Application Form + Intimation Slip PDFs
  emails.py              sends the documents / supplementary slip (wording in templates)
  roles.py               staff groups "Verification Officer" and "Auction Admin" and their permissions
  admin.py               applicant list, VERIFICATION SCREEN, checklist items, audit log
  constants.py           list of Indian states
  management/commands/   generate_secret_keys
  migrations/0003_...    the placeholder document checklist
  templates/             applications/ (pages, emails/), admin/applications/applicant/verify.html
  static/applications/   quarter_picker.js (search box + running EMD total)

auctions/                 QUARTERS, AUCTIONS AND BIDS
  models.py              Quarter, Auction (step, quick bids, phase), Participation, Bid
  importers.py           Excel import + validation (creates quarter AND auction)
  bidding.py             join_auction(), place_bid(): ALL bid rules
  closing.py             close_auction(): winner selection with the 2-quarter cap
  emails.py              winner / loser emails (wording in templates)
  realtime.py            EVERYTHING sent to browsers over WebSockets (privacy)
  consumers.py           the WebSocket endpoint (connect, receive bids)
  routing.py             WebSocket URL
  views.py               home page, quarter listing, auction page
  urls.py                /auctions/... URLs
  forms.py               Excel upload form
  admin.py               Quarter / Auction / Bid / Participation admin screens, import page
  management/commands/   run_auction_worker, close_auctions, seed_demo
  templates/auctions/    page templates; includes/ = quarter tables; emails/ = result wording
  static/auctions/       auction_room.js (live page, quick bids), countdown.js

templates/                site-wide: base.html (header/nav), home.html, includes/form_fields.html,
                          content/rules.html + content/faq.html (THE rules and FAQ text),
                          emails/training_footer.txt (footer of every email)
static/css/site.css       site-wide look
scripts/                  run_server.ps1, run_worker.ps1, Postgres start/stop, email setup
sample_data/              make_samples.py + the FAKE Excel files (README.md explains them)
```

**The pattern used everywhere:** *views / consumers / admin* receive the request, then
call a *business function* (`otp.py`, `services.py`, `eligibility.py`, `bidding.py`,
`closing.py`), which uses the *models*. Business rules never live in views or templates,
so each rule exists in exactly one place and is tested there.

---

## 0a. Recipes for common changes

**Change the bidding rules / FAQ text on the home page**
1. Edit `templates/content/rules.html` or `templates/content/faq.html`. That is the only place.
2. Numbers in the text (`{{ MAX_QUARTERS_PER_APPLICANT }}` ...) come from settings; keep them.

**Change an email's wording**
1. Open the `.txt` file (section 4 below). Edit the text; keep the `{{ ... }}` parts.
2. Run `python manage.py test`.

**Change a number (duration, step %, cap of 2, OTP minutes, ...)**
1. Look it up in section 1. Put the line in `.env` and restart the server. No code change.

**Change the document checklist**
1. Admin > Applications and verification > Document checklist items. Add, rename, untick
   "required", or untick "is active" to retire an item. No code change.

**Change what a staff role may do**
1. `applications/roles.py`: edit `ROLE_PERMISSIONS`, then run `python manage.py migrate`
   (the groups are rebuilt after every migrate).
2. Give a staff user a role: admin > Users > the user > Groups.

**Add a new tunable setting**
1. `config/settings.py`, bottom section: `MY_VALUE = env.int('MY_VALUE', default=10)`
2. Use it in code as `settings.MY_VALUE` (`from django.conf import settings`).
3. Add `# MY_VALUE=10` to `.env.example` and a row to section 1 of this file.

**Add a field to Quarter (or Applicant)**
1. Add the field in `auctions/models.py` (or `applications/models.py`).
2. `python manage.py makemigrations` then `python manage.py migrate`.
3. Show it: `list_display` in `admin.py`; the quarter table in
   `auctions/templates/auctions/includes/quarter_table.html`.
4. If it comes from Excel: add the column to `EXPECTED_HEADERS` and a check in
   `_validate_row()` in `auctions/importers.py`; add it to `sample_data/make_samples.py`
   and regenerate the samples.
5. If bidders should see it live: add it in `auctions/realtime.py` only, and never add
   personal applicant data there.

**Add or change a bid rule**
1. `auctions/bidding.py`, `place_bid()`: add the check next to the numbered rules
   and raise `BidRejected("short_code", "Message shown to the bidder.")`.
2. Add the rule to the numbered list in the docstring and a test in `auctions/tests/test_bidding.py`.

**Change who may bid** (e.g. a new eligibility condition)
1. `applications/eligibility.py`, `check()`. Pages, WebSockets, bidding and closure all use it.
2. Add a test in `applications/tests/test_verification.py` (EligibilityTests).

**Add a new page**
1. A function in `views.py`, a URL in that app's `urls.py`, and a template in
   `<app>/templates/<app>/` that starts with `{% extends "base.html" %}`.
2. Logged-in users only? Put `@login_required` above the view.

---

## 1. Values you can change WITHOUT editing code (`.env`)

Add the line to `.env` and restart the server. Defaults live in `config/settings.py`
under **PROJECT SETTINGS**. All business values are PLACEHOLDERS (CLAUDE.md section 12).

| What | `.env` line | Default |
|---|---|---|
| Max quarters one applicant can be ALLOTTED | `MAX_QUARTERS_PER_APPLICANT=2` | 2 |
| Auction length when the Excel "Duration" is blank | `DEFAULT_AUCTION_DURATION_MINUTES=5` | 5 |
| Bid step, % of base rate (new auctions) | `DEFAULT_INCREMENT_PERCENT=0.20` | 0.20 (= 0.2 %) |
| Max anti-snipe extensions per auction | `AUCTION_MAX_EXTENSIONS=5` | 5 |
| Applications for a quarter close this long before its slot | `APPLICATION_CLOSES_HOURS_BEFORE_AUCTION=24` | 24 |
| Sign-up code valid for (minutes) | `OTP_VALID_MINUTES=10` | 10 |
| Wrong code attempts allowed | `OTP_MAX_ATTEMPTS=5` | 5 |
| Wait before "send a new code" (seconds) | `OTP_RESEND_COOLDOWN_SECONDS=60` | 60 |
| Codes per email / per IP address per hour | `OTP_SENDS_PER_EMAIL_PER_HOUR=5`, `OTP_SENDS_PER_IP_PER_HOUR=20` | 5 / 20 |
| Time to choose a password after the code | `SIGNUP_VERIFIED_WINDOW_MINUTES=30` | 30 |
| Wrong logins allowed per email / per IP | `AUTH_RATE_LIMIT_ATTEMPTS=5`, `AUTH_RATE_LIMIT_IP_ATTEMPTS=50` | 5 / 50 |
| Lock-out window (seconds) | `AUTH_RATE_LIMIT_WINDOW_SECONDS=900` | 900 (15 min) |
| Auction title on PDFs and emails | `AUCTION_TITLE=...` | Vacant Quarter Auction (Training Demo) |
| Auction reference on the Application Form | `AUCTION_REFERENCE=...` | DEMO/QA/2026/01 |
| SBI Collect payee name on the Intimation Slip | `SBI_COLLECT_PAYEE=...` | placeholder "(DEMO)" text |
| Aadhaar/PAN encryption keys (REQUIRED, secret) | `FIELD_ENCRYPTION_KEYS=...`, `IDENTITY_HASH_KEY=...` | none: `python manage.py generate_secret_keys` |
| Send real email via SMTP | `EMAIL_HOST_PASSWORD` (+ `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `DEFAULT_FROM_EMAIL`), or `.\scripts\setup_email.ps1` | `.eml` files in `sent_emails/` + console |
| Database (PostgreSQL required) | `DATABASE_URL=postgres://user:pass@localhost:5432/dbname` | SQLite (do not use for bidding) |
| Minimum gap between bids from one browser tab | `AUCTION_BID_MIN_INTERVAL_SECONDS=1.0` | 1.0 |
| Redis for WebSockets across several processes | `REDIS_URL=redis://localhost:6379/0` | In-memory (one process) |
| Recent bids shown on the auction page | `AUCTION_RECENT_BIDS_SHOWN=20` | 20 |
| Days closed auctions stay in "Recently closed" | `AUCTION_RECENTLY_CLOSED_DAYS=7` | 7 |
| How often the worker checks for finished auctions | `AUCTION_WORKER_INTERVAL_SECONDS=5` | 5 |
| Email losing bidders | `AUCTION_NOTIFY_LOSERS=True` | False |

Per auction (admin > Auctions, editable until the auction starts): duration, increment %,
anti-snipe seconds (0 = off).

Production-only values (see `docs/DEPLOYMENT.md`): `DEBUG=False`, `CSRF_TRUSTED_ORIGINS`,
`BEHIND_HTTPS_PROXY`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`.

In `config/settings.py` (not in `.env`): `PASSWORD_RESET_TIMEOUT`, `TIME_ZONE`, `QUICK_BID_STEPS` (1, 2, 5), `OTP_LENGTH`.

---

## 2. Business rules

| Rule | Where |
|---|---|
| Login with email; email unique | `accounts/models.py`: `User` |
| Sign-up code: hashing, expiry, attempts, cooldown, limits | `accounts/otp.py` |
| Password strength rules | `config/settings.py`: `AUTH_PASSWORD_VALIDATORS` |
| URN format / generation; application number format | `applications/models.py`: `generate_urn()`, `Applicant.save()` |
| Aadhaar / PAN format, masking | `applications/validators.py` |
| Encryption and "one application per Aadhaar/PAN" | `applications/crypto.py`; `Applicant.set_aadhaar()` / `set_pan()` |
| Which quarters can still be selected | `applications/services.py`: `application_window_open()`, `auctions_open_for_application()` |
| Status flow, activation needs all required documents, reasons | `applications/services.py` |
| EMD verification (receipt, date, amount covers EMD) | `applications/services.py`: `verify_emd()`; DB check in `QuarterApplication.Meta` |
| **Who may bid on which quarter** (incl. the 2-quarter cap) | `applications/eligibility.py`: `check()` |
| Who may reveal full Aadhaar/PAN | permission `reveal_identity_numbers` (Verification Officer group) |
| Bid step (percent of base rate, rounding), first bid, quick-bid amounts | `auctions/models.py`: `Auction.bid_step`, `minimum_next_bid`, `quick_bid_amounts()` |
| Auction phases (Upcoming / Live / Closing) | `auctions/models.py`: `Auction.phase()` |
| End time = start + duration | `auctions/models.py`: `Auction.schedule_end()` |
| Fields locked once an auction starts | `auctions/admin.py`: `AuctionAdmin.LOCKED_AFTER_START` |
| **Bid validation rules** | `auctions/bidding.py`: `place_bid()` (rules numbered in its docstring) |
| How "Bidder N" codes are assigned | `auctions/bidding.py`: `join_auction()` |
| Accepted amount format (whole rupees) | `auctions/bidding.py`: `parse_amount()` |

## 2a. Closing auctions and result emails

| What | Where |
|---|---|
| Winner choice, 2-quarter cap, the three closed outcomes | `auctions/closing.py`: `close_auction()`, `pick_winning_bid()` |
| Winner email text / "next steps" | `auctions/templates/auctions/emails/winner_body.txt`, `winner_subject.txt` |
| When the winner email is sent (once only) | `auctions/emails.py`: `notify_winner()` |
| Email losing bidders (off by default) | `.env`: `AUCTION_NOTIFY_LOSERS=True`; text in `loser_body.txt` |
| Worker commands | `auctions/management/commands/run_auction_worker.py`, `close_auctions.py` |

## 2b. Real-time (WebSockets)

| What | Where |
|---|---|
| **What browsers are sent** (privacy-critical) | `auctions/realtime.py`: `public_bid()`, `auction_state()`, `snapshot()` |
| Who may connect / bid, what messages are accepted | `auctions/consumers.py`: `AuctionConsumer` |
| WebSocket URL | `auctions/routing.py` |
| HTTP + WebSocket wiring, session login for sockets | `config/asgi.py` |
| Browser side: drawing, quick bids, sending bids, reconnecting | `auctions/static/auctions/auction_room.js` |
| Auction page layout (and the result panel) | `auctions/templates/auctions/auction_room.html` |

---

## 3. Excel import

| What | Where |
|---|---|
| Expected column headers | `auctions/importers.py`: `EXPECTED_HEADERS` |
| Per-row validation, accepted date/time formats | `auctions/importers.py`: `_validate_row()`, `DATE_FORMATS`, `TIME_FORMATS` |
| Maximum rows / duration / file size | `auctions/importers.py`: `MAX_DATA_ROWS`, `MAX_DURATION_MINUTES`; `auctions/forms.py`: `MAX_UPLOAD_MB` |
| Sample files | `sample_data/make_samples.py`, then `python sample_data/make_samples.py` |

---

## 4. Documents and emails

| What | Where |
|---|---|
| Application Form PDF layout / text | `applications/pdfs.py`: `application_form_pdf()` |
| Intimation Slip PDF (quarter table, EMD total, SBI Collect steps) | `applications/pdfs.py`: `intimation_slip_pdf()` |
| What the QR code contains | `applications/pdfs.py`: `qr_payload()` |
| "Training project" banner text | `applications/pdfs.py`: `TRAINING_NOTICE` |
| Documents email text / subject | `applications/templates/applications/emails/documents_body.txt`, `documents_subject.txt` |
| Supplementary slip email | `applications/templates/applications/emails/supplementary_*.txt` |
| Sign-up code email | `accounts/templates/accounts/emails/otp_body.txt`, `otp_subject.txt` |
| Password reset email | `accounts/templates/accounts/emails/password_reset_*.txt` |
| Footer at the bottom of every email | `templates/emails/training_footer.txt` |
| How emails are built from templates | `config/mail.py`: `build_email()` |

---

## 5. Pages and look

| What | Where |
|---|---|
| Colours, fonts, spacing (whole site) | `static/css/site.css`: the variables at the top |
| Header, navigation (Login button), notice bar | `templates/base.html` |
| How form fields are displayed (all forms) | `templates/includes/form_fields.html` |
| Home page (public) | `templates/home.html` + `templates/content/` |
| Quarter tables (home + listing) | `auctions/templates/auctions/includes/quarter_table.html`, `closed_table.html` |
| Quarter listing after login | `auctions/templates/auctions/listing.html` |
| Sign-up / login / reset pages | `accounts/templates/accounts/` |
| Register for bidding / my application / add quarters | `applications/templates/applications/` |
| Quarter picker (search + EMD total) | `applications/templates/applications/includes/quarter_picker.html`, `applications/static/applications/quarter_picker.js` |
| Countdown behaviour | `auctions/static/auctions/countdown.js` |

---

## 6. Admin screens

| What | Where |
|---|---|
| Users (email login), staff roles via Groups | `accounts/admin.py`: `UserAdmin` |
| Applicant list, **verification screen**, reveal, resend documents | `applications/admin.py`: `ApplicantAdmin`; template `applications/templates/admin/applications/applicant/verify.html` |
| Document checklist items | `applications/admin.py`: `DocumentChecklistItemAdmin` |
| Audit log (read-only) | `applications/admin.py`: `AuditLogAdmin` |
| Quarter list, Excel import page | `auctions/admin.py`: `QuarterAdmin` |
| Auctions: timings, increment, anti-snipe, cancel, close, result emails | `auctions/admin.py`: `AuctionAdmin` |
| Bid audit list (read-only, codes only) | `auctions/admin.py`: `BidAdmin` |
| Applicant ↔ bidder-code mapping (superusers only) | `auctions/admin.py`: `ParticipationAdmin` |

---

## 7. After changing a model

```powershell
python manage.py makemigrations
python manage.py migrate
python manage.py test
```
Commit the new file in `*/migrations/` together with the model change.

---

## 8. Tests: where they live

| Area | File |
|---|---|
| Test data helpers | `accounts/tests/factories.py`, `applications/tests/factories.py`, `auctions/tests/factories.py` |
| User model (email login) | `accounts/tests/test_user_model.py` |
| Sign-up with OTP (all code rules) | `accounts/tests/test_signup.py` |
| Login, logout, password reset | `accounts/tests/test_login_and_reset.py` |
| Aadhaar/PAN validation, encryption, storage | `applications/tests/test_identity_numbers.py` |
| Register for bidding, PDFs, emails, add quarters | `applications/tests/test_apply.py` |
| Verification, status, audit log, roles, eligibility, verification screen | `applications/tests/test_verification.py` |
| Quarter / Auction models, bid step | `auctions/tests/test_models.py` |
| Excel import | `auctions/tests/test_import.py` |
| Admin screens and role privacy | `auctions/tests/test_admin.py` |
| Home, listing, auction pages | `auctions/tests/test_pages.py` |
| Bidding rules, anti-sniping | `auctions/tests/test_bidding.py` |
| **Simultaneous bids / closures / 2-quarter cap race** (PostgreSQL only) | `auctions/tests/test_concurrency.py` |
| WebSocket consumer | `auctions/tests/test_consumers.py` |
| Closure, cap, winner email, worker, result display | `auctions/tests/test_closing.py` |
| Demo data command | `auctions/tests/test_seed_demo.py` |
