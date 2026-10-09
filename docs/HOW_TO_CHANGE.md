# How to change things

A map from **"I want to change X"** to **the file to edit**. Keep this up to date
when you move code around.

After any change, run the tests: `python manage.py test`

---

## 1. Values you can change WITHOUT editing code (`.env`)

Add the line to `.env` and restart the server. Defaults live in `config/settings.py`
under **PROJECT SETTINGS**.

| What | `.env` line | Default |
|---|---|---|
| Auction title on PDFs and emails | `AUCTION_TITLE=...` | Vacant Quarter Auction (Training Demo) |
| Auction reference on the Application Form | `AUCTION_REFERENCE=...` | DEMO/QA/2026/01 |
| EMD amount on the Intimation Slip | `EMD_AMOUNT=10000` | 10000 |
| Wrong attempts allowed per email/URN | `AUTH_RATE_LIMIT_ATTEMPTS=5` | 5 |
| Wrong attempts allowed per IP address | `AUTH_RATE_LIMIT_IP_ATTEMPTS=50` | 50 |
| Lock-out window (seconds) | `AUTH_RATE_LIMIT_WINDOW_SECONDS=900` | 900 (15 min) |
| Send real email via SMTP | `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` plus `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | Emails saved as `.eml` files in `sent_emails/` |
| Database (PostgreSQL required for bidding) | `DATABASE_URL=postgres://user:pass@localhost:5432/dbname` | SQLite file `db.sqlite3` |
| Anti-snipe window ("final minute") | `AUCTION_ANTI_SNIPE_WINDOW_SECONDS=60` | 60 |
| Minimum gap between bids from one browser tab | `AUCTION_BID_MIN_INTERVAL_SECONDS=1.0` | 1.0 |
| Redis for WebSockets across several processes | `REDIS_URL=redis://localhost:6379/0` | In-memory (one process) |

Production-only values (see `docs/DEPLOYMENT.md`): `DEBUG=False`, `CSRF_TRUSTED_ORIGINS`,
`BEHIND_HTTPS_PROXY`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`.

In `config/settings.py` (not in `.env`):
- `PASSWORD_RESET_TIMEOUT`: reset link lifetime in seconds. The pages and email update automatically.
- `TIME_ZONE`: currently `Asia/Kolkata`.

---

## 2. Business rules

| Rule | Where |
|---|---|
| URN format / how URNs are generated | `accounts/models.py`: `generate_urn()` and `urn_validator` |
| Application number format (`QA2026000001`) | `accounts/models.py`: `Applicant.save()` |
| Mobile / PIN validation | `accounts/models.py`: `mobile_validator`, `pin_validator` |
| List of states in the dropdown | `accounts/constants.py` |
| Who may activate (verified, not yet activated) | `accounts/forms.py`: `ActivationForm.clean()`, and `accounts/services.py`: `activate_applicant()` |
| Who may enter the lobby | `accounts/decorators.py`: `applicant_required` |
| Password strength rules | `config/settings.py`: `AUTH_PASSWORD_VALIDATORS` |
| First bid minimum / next bid minimum | `auctions/models.py`: `Auction.minimum_next_bid` |
| Default minimum increment / anti-snipe extension | `auctions/models.py`: `Auction.min_increment` / `anti_snipe_extension` defaults |
| Auction phases (Upcoming / Live / Closing) | `auctions/models.py`: `Auction.phase()` |
| Fields locked once an auction starts | `auctions/admin.py`: `AuctionAdmin.LOCKED_AFTER_START` |
| **Bid validation rules** (live, joined, minimum, self-outbid, duplicates, anti-sniping) | `auctions/bidding.py`: `place_bid()` (rules numbered in its docstring) |
| Joining an auction / how "Bidder N" codes are assigned | `auctions/bidding.py`: `join_auction()` |
| Accepted amount format (decimals, max) | `auctions/bidding.py`: `parse_amount()` |
| How many recent bids are shown | `config/settings.py`: `AUCTION_RECENT_BIDS_SHOWN` |

## 2a. Closing auctions and result emails

| What | Where |
|---|---|
| How the winner is chosen / what happens to the quarter | `auctions/closing.py`: `close_auction()` |
| How often the worker checks | `.env`: `AUCTION_WORKER_INTERVAL_SECONDS` (default 5) |
| Winner email text / "next steps" | `auctions/emails.py`: `notify_winner()` |
| Email losing bidders (off by default) | `.env`: `AUCTION_NOTIFY_LOSERS=True`; text in `auctions/emails.py`: `notify_losers()` |
| How long auctions stay under "Recently closed" | `config/settings.py`: `AUCTION_RECENTLY_CLOSED_DAYS` |
| Worker commands | `auctions/management/commands/run_auction_worker.py`, `close_auctions.py` |

## 2b. Real-time (WebSockets)

| What | Where |
|---|---|
| **What browsers are sent** (privacy-critical) | `auctions/realtime.py`: `public_bid()`, `auction_state()`, `snapshot()` |
| Who may connect, what messages are accepted | `auctions/consumers.py`: `AuctionConsumer` |
| WebSocket URL | `auctions/routing.py` |
| HTTP + WebSocket wiring, session login for sockets | `config/asgi.py` |
| Browser side: drawing updates, sending bids, reconnecting | `auctions/static/auctions/auction_room.js` |
| Auction page layout | `auctions/templates/auctions/auction_room.html` |
| Quarter types A/B/C/D, quarter statuses | `auctions/models.py`: `Quarter.QuarterType`, `Quarter.Status` |

---

## 3. Excel import

| What | Where |
|---|---|
| Expected column headers | `auctions/importers.py`: `EXPECTED_HEADERS` |
| Per-row validation rules | `auctions/importers.py`: `_validate_row()` |
| Maximum rows / file size | `auctions/importers.py`: `MAX_DATA_ROWS`; `auctions/forms.py`: `MAX_UPLOAD_MB` |
| Sample files | `sample_data/make_samples.py`, then run `python sample_data/make_samples.py` |

---

## 4. Documents and emails

| What | Where |
|---|---|
| Application Form PDF layout / text | `accounts/pdfs.py`: `application_form_pdf()` |
| Intimation Slip PDF layout / text | `accounts/pdfs.py`: `intimation_slip_pdf()` |
| What the QR code contains | `accounts/pdfs.py`: `qr_payload()` |
| "Training project" banner text | `accounts/pdfs.py`: `TRAINING_NOTICE` |
| Registration email text | `accounts/emails.py`: `send_registration_documents()` |
| Password reset email text / subject | `accounts/templates/accounts/emails/` |

---

## 5. Pages and look

| What | Where |
|---|---|
| Colours, fonts, spacing (whole site) | `static/css/site.css`: the variables at the top |
| Header, navigation, notice bar | `templates/base.html` |
| How form fields are displayed (all forms) | `templates/includes/form_fields.html` |
| Home page | `templates/home.html` |
| Registration / activation / login / reset pages | `accounts/templates/accounts/` |
| Lobby page | `auctions/templates/auctions/lobby.html` |
| Lobby table columns | `auctions/templates/auctions/includes/auction_table.html` |
| Countdown behaviour | `auctions/static/auctions/countdown.js` |
| URLs | `config/urls.py` (top level), `accounts/urls.py`, `auctions/urls.py` |

---

## 6. Admin screens

| What | Where |
|---|---|
| Quarter list columns / filters, Excel import page | `auctions/admin.py`: `QuarterAdmin` |
| Auction admin, cancel action, bid list on an auction | `auctions/admin.py`: `AuctionAdmin`, `BidInline` |
| Bid audit list (read-only, codes only) | `auctions/admin.py`: `BidAdmin` |
| Applicant ↔ bidder-code mapping (superusers only) | `auctions/admin.py`: `ParticipationAdmin` |
| Applicant admin, resend-documents action | `accounts/admin.py`: `ApplicantAdmin` |

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
| Test data helpers | `accounts/tests/factories.py`, `auctions/tests/factories.py` |
| Applicant model, URN generation | `accounts/tests/test_models.py`, `test_generation.py` |
| Registration, PDFs, email | `accounts/tests/test_registration.py`, `test_documents.py` |
| Activation | `accounts/tests/test_activation.py` |
| Login, logout, password reset | `accounts/tests/test_login_and_reset.py` |
| Quarter / Auction models | `auctions/tests/test_models.py` |
| Excel import | `auctions/tests/test_import.py` |
| Admin screens | `auctions/tests/test_admin.py` |
| Lobby, auction admin | `auctions/tests/test_lobby.py` |
| Bidding rules, anti-sniping | `auctions/tests/test_bidding.py` |
| **Simultaneous bids** (PostgreSQL only) | `auctions/tests/test_concurrency.py` |
| WebSocket consumer | `auctions/tests/test_consumers.py` |
| Auction page, admin privacy | `auctions/tests/test_auction_room.py` |
| Demo data command | `auctions/tests/test_seed_demo.py` |
| Closure, winner email, worker commands, result display | `auctions/tests/test_closing.py` |
