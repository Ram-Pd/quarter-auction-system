# PROGRESS: SAIL Vacant Quarter Auction System

_Last updated: 2026-10-14, Change Request #3 implemented (all six CR #3 milestones)_

**Test status:** 211 automated tests, all passing on PostgreSQL 17 (`python manage.py test`, about 1 minute).
**Before running anything:** start PostgreSQL with `.\scripts\start_postgres.ps1` (it does not auto-start).

See also: `README.md` (setup/run/demo), `docs/HOW_TO_CHANGE.md` (which file to edit for what),
`docs/ARCHITECTURE.md` (diagrams), `docs/DEMO_SCRIPT.md`, `docs/CHANGE_REQUEST_3.md` (the mentor's final workflow).

---

## Change Request #3 (2026-10-14) ✅ COMPLETE

CR #3 replaced the workflow: email login with OTP sign-up instead of URN activation;
"Register for bidding" after login with multiple quarters and Aadhaar/PAN; per-quarter
EMD verification by an officer; bidding slots from the Excel file; percentage bid steps
with quick bids; a 2-quarter allotment cap.

### Decisions confirmed by the user (2026-10-14)
1. **Custom user model** (`accounts.User`, email login) with **migrations reset** and the
   dev database recreated (fake demo data only). Fresh `0001_initial` migrations in all apps.
2. **Aadhaar/PAN encryption:** `cryptography` Fernet (MultiFernet for key rotation), keys in `.env`.
3. **One application per Aadhaar and per PAN:** enforced with a keyed hash (HMAC-SHA256) unique column.
4. **"One quarter at a time" rule removed** (the 2-allotment cap replaces it).
5. **Step rounding:** user says base rates are in tens of thousands, so it rarely matters;
   implemented as nearest rupee, minimum Rs. 1 (assumption).
6. **Anti-sniping off by default** (`anti_snipe_seconds = 0`), per auction; when on, at most
   `AUCTION_MAX_EXTENSIONS` (5) extensions. Pending mentor confirmation.

### Milestone 1: Foundation ✅
- **Custom `User`** (`accounts/models.py`): no username; `email` is the login, unique
  case-insensitively at DB level; `full_name`, `phone` (not verified), `email_verified_at`.
  Custom manager so `createsuperuser` works with email. Admin adapted.
- **New app `applications/`** (bidding registration + verification), separate from
  `accounts/` (login) and `auctions/` (quarters/bidding). *Why:* each app has one job.
- **Quarter** gains `emd_amount`. **Auction** gains `duration_minutes` (end = start + duration),
  `increment_percent` (default 0.20 %), `anti_snipe_seconds`, `extensions_count`, `total_bids`,
  statuses SCHEDULED / CLOSED_WON / CLOSED_NO_BIDS / CLOSED_NO_VALID_WINNER / CANCELLED,
  `winner_email_sent_at`. `min_increment` and the old duration-type extension are gone.
- **Excel import** (`auctions/importers.py`): 11 columns; each row creates Quarter + Auction
  atomically; dates/times as Excel cells or text, India time; start must be in the future;
  duration optional (default 5), 1-1440; all errors with row + column; all-or-nothing.
- **Sample files** regenerated (`sample_data/make_samples.py`, now importable by tests; dates
  relative to today) incl. a new edge-case file; `sample_data/README.md`.
- **Staff roles** as groups, rebuilt after every `migrate` (`applications/roles.py`):
  Verification Officer (applicant data, verification, audited reveal) and Auction Admin
  (import, auctions, bids by code; no personal data). Participation stays superuser-only.

### Milestone 2: Public site, sign-up, login ✅
- **Home page** (public): introduction, rules and FAQ from `templates/content/` (one place,
  placeholder wording, numbers from settings); Login / Create account buttons.
  **Change 2026-10-14 (user):** the quarter list was removed from the home page; quarter
  information, auction pages and live WebSocket updates now need a login (anonymous
  sockets are refused with code 4401).
- **Sign-up in 3 steps** (`accounts/views.py`, `accounts/otp.py`): details → 6-digit code →
  password. Nothing is saved in the User table until the last step. OTP: `secrets` random,
  stored as a keyed hash (`salted_hmac`), 10-minute expiry, 5 wrong attempts (counted under
  a row lock, saved even when the guess is wrong), single use, newest code replaces older
  ones, 60 s resend cooldown, max 5 codes per email and 20 per IP per hour.
  The code is not in the email subject.
- **Login** with email + password (case-insensitive), rate limited; password reset unchanged
  (Django's token flow). Password similarity validator now checks `email` and `full_name`.
- **Quarter listing** (`/auctions/`): every quarter with EMD and slot, the user's status
  (Not registered / Documents pending / Active / Rejected / Suspended), "Applied" and
  "Eligible to bid" per quarter, allotted n of 2.
- **Dev email backend** prints every email to the console as well as saving the `.eml`.

### Milestone 3: Register for bidding ✅
- **Form** (`/apply/`): name (pre-filled), father's name, address/state/PIN (addition, to
  confirm), Aadhaar (12 digits, not starting 0/1, **Verhoeff** check digit), PAN
  (AAAAA9999A), quarters, declaration. Quarter picker: scrollable, searchable, EMD per
  quarter and a running total (`quarter_picker.js`; works without JS too).
- Only quarters whose slot starts more than `APPLICATION_CLOSES_HOURS_BEFORE_AUCTION` (24 h)
  ahead can be selected (also enforced on the server for crafted POSTs).
- **Aadhaar/PAN safeguards:** encrypted token + keyed hash + last 4; masked everywhere;
  `sensitive_post_parameters` keeps them out of error reports; never in emails (tested);
  PDFs show them masked; never in the audit log.
- **On submit** (`services.submit_application`): Applicant (application no. `QA2026000001`,
  URN 7 digits random), QuarterApplication per quarter (EMD copied), audit entry; ONE email
  with both PDFs via `transaction.on_commit`; Post/Redirect/Get so a refresh never resends.
  A failed email keeps the application and shows "Not sent; contact the office" (officer
  can "Resend documents").
- **PDFs** (`applications/pdfs.py`): Application Form (no./date, URN, QR without personal
  data, applicant, masked IDs, quarters table with slots, declaration); Intimation Slip
  (URN/date, name, phone, quarter table with EMD each + total, SBI Collect steps with the
  `SBI_COLLECT_PAYEE` placeholder). Checked visually.
- **Add quarters later** (`/apply/add/`): supplementary Intimation Slip for the added
  quarters only.

### Milestone 4: Offline verification ✅
- **Verification screen** (`/admin/applications/applicant/<id>/verify/`, needs
  `verify_applicant`): applicant details (masked), document checklist with who/when,
  EMD receipt per quarter (receipt no., amount, date; "amount covers EMD" indicator; a
  verified receipt can't be edited, only un-verified with a reason), Activate (disabled
  until all required items ticked), Suspend / Reject with reason, audited Reveal, history.
- **Rules in `applications/services.py`**, each with an audit entry and the acting user;
  first action moves REGISTERED → DOCUMENTS_PENDING; REJECTED is final; SUSPENDED can be
  re-activated. DB check: a verified EMD always has receipt, date, officer and amount ≥ EMD.
- **Checklist** = admin-editable model, seeded by a data migration with the CR #3 placeholder items.
- **Eligibility** (`applications/eligibility.py`): ACTIVE + EMD verified for THAT quarter +
  fewer than `MAX_QUARTERS_PER_APPLICANT` allotted. Used everywhere.

### Milestone 5: Bidding ✅
- Auction page needs a **login** (any logged-in user may watch, see history and result); an eligible applicant
  automatically gets a "Bidder N" code on first visit and the bid panel; others see the reason.
- WebSocket: logged-in users may connect read-only; bids only from an eligible participant's connection.
- **Step** = increment % × base rate, whole rupees; **quick bids** +1/+2/+5 steps (buttons show
  the amount and follow the live highest bid); custom amount ≥ highest + one step; first bid ≥
  base rate; whole rupees only; duplicate `client_bid_id` = same bid; can't outbid yourself.
- `place_bid` **re-reads the applicant** inside the lock, so a suspension or un-verified EMD
  stops an already-open connection (bug found by a test while building this, now tested).
- Anti-sniping per auction (`anti_snipe_seconds`, default off), capped extensions.

### Milestone 6: Closure, cap, results ✅
- `close_auction` locks the auction, then **all its bidders' Applicant rows in id order**,
  then picks the highest bid whose bidder is still eligible and under the cap; otherwise the
  next-highest (at their own highest bid). Outcomes CLOSED_WON / CLOSED_NO_BIDS /
  CLOSED_NO_VALID_WINNER; quarter Allotted only with a winner.
- Result on the same auction page: code, amount, total bids. Winner email once
  (`winner_email_sent_at`, retried by the worker on failure); loser emails off by default.
- **Concurrency test** (`AllotmentCapConcurrencyTests`): applicant with 1 quarter tops two
  auctions that close at the same instant → exactly 2 quarters, the other goes to the
  runner-up. **Verified it FAILS (3 quarters) when the applicant lock is removed.**

### Verified end to end on the real server (2026-10-14)
Server run with emails forced to `.eml` files; a stdlib script drove HTTP and real
WebSockets (42 checks, all PASS): public home; sign-up with the console OTP (wrong code
refused); application with checksum-invalid Aadhaar refused, then valid; email with 2 PDFs,
no Aadhaar/PAN in the body, not resent on refresh; officer verification (short payment
flagged, EMD verified, activated, reveal shown once and logged); Auction Admin gets 403 on
the verification screen; listing shows "eligible to bid on 1 quarter"; two bidders + an
anonymous watcher on a live auction: live broadcast without identity, too-low bid refused,
+5 quick bid accepted, duplicate click not a second bid, watcher can't bid, reconnect
resyncs. Then `close_auctions` closed it (CLOSED_WON, winner email once; a second run closed
nothing). Screenshots checked (headless Edge): home, listing, apply (running total), auction
page desktop and 390 px phone width, winner and public result pages, verification screen.
PDFs checked visually.

### Tests (208)
accounts: user model, sign-up/OTP (expiry, attempts, single use, cooldown, limits per
email/IP, replacement), login/reset. applications: Verhoeff/PAN/masking, encryption,
key rotation, keyed hash, raw DB row has no plain number, duplicates, apply flow, PDFs and
email contents, privacy, add quarters, verification rules, audit log, reveal, roles,
eligibility, verification screen. auctions: models (step rounding table), import (all four
samples, formats, every rule), pages, admin + role privacy, bidding rules, anti-sniping cap,
broadcast timing, closure + cap, emails, worker, consumers (watchers, eligibility, privacy,
suspension on an open socket), concurrency (bids, joins, closers, cap race), seed_demo.
The test run uses a fast password hasher (real hashing is ~0.5 s per user); production is unchanged.

---

## Current problems / limitations
- `docs/Code_Guide_for_Beginners.pdf` describes the code **before** CR #3 (URN activation,
  lobby). It needs regenerating for the new code.
- Storing full Aadhaar numbers is legally sensitive; implemented with safeguards but needs
  mentor/legal approval (CLAUDE.md section 12, question 7).
- `seed_demo` live auctions last 20 minutes from seeding: re-seed (on a fresh database) just
  before a demo.
- During this session, before `seed_demo` was changed to always save emails locally, one
  seeding run sent ~6 emails through the configured Gmail account to fake `demo*@example.com`
  addresses (undeliverable; may cause bounce notices). Fixed: seeding never uses SMTP now.

## Assumptions (placeholders; full list in CLAUDE.md section 12)
URN system-generated · first bid ≥ base rate · any amount ≥ highest + one step · step rounded
to nearest rupee (min Rs. 1) · unranked multi-select · add quarters until 24 h before the slot
· capped top bidder → next-highest eligible at their own bid · paying more than the EMD is
accepted · cannot outbid yourself · anti-sniping off · phone not verified · checklist items as in CR #3 · tie: earliest bid · loser emails off.

## Next steps
1. Ask the mentor the open questions (CLAUDE.md section 12), especially Aadhaar storage,
   anti-sniping, the cap fallback and the document checklist.
2. Regenerate the beginner's code guide PDF for the new code.
3. Production rehearsal per `docs/DEPLOYMENT.md` (Redis, HTTPS proxy, new keys).

---

## History before Change Request #3 (commits 58baba6 … 3e68a94)
Milestones 1-5 of the original plan were completed: Excel import, public registration with
URN + PDFs, URN-based activation, lobby, PostgreSQL + Channels live bidding with row locking,
automatic closure and winner email, production settings, documentation, a code-organisation
pass and a beginner's code guide. CR #3 reused the bidding engine, consumer, realtime
messages, closure, worker, PDF/email/QR tooling, rate limiter and importer design, and
replaced the account, registration and eligibility model.
