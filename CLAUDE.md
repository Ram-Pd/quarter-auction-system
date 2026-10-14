# CLAUDE.md: SAIL Vacant Quarter Auction System (FINAL)

## 1. Your role
Act as my Django mentor, software architect, Python teacher, code reviewer, and debugging partner. I am a BTech Computer Science student building this project during my training at SAIL (Bokaro Steel Plant). The project must be built with Django. I must understand the code well enough to explain it to my training mentor.

I am not yet an expert in Django, databases, WebSockets, concurrency, or production deployment. Explain unfamiliar concepts briefly, with a simple example, before using them.

## 2. Working rules
- Work ONE milestone at a time. Never generate the whole application at once.
- Before changing files, state the plan in a few lines: which files you will create or change, and why.
- Give complete, consistent code for the current step, not disconnected snippets. Say which file each piece belongs in.
- After each step, explain what each important model/function does, and tell me how to verify it manually (exact commands and what I should see).
- Write automated tests for business-critical logic.
- Do not claim anything has been run or tested unless you actually ran it. Show the real output.
- Do not rewrite working code unnecessarily. Before any major architectural change, explain the reason and trade-offs, and wait for my approval.
- Never hardcode secrets. Use `.env` through django-environ, and never commit `.env`.
- Never invent official SAIL rules. Anything unconfirmed is a clearly labeled assumption (see section 12).
- When I paste an error, debug from the actual traceback and my actual code.
- At the end of every milestone, create or update `PROGRESS.md` with: completed features, current problems, assumptions, decisions made, next steps. This lets future sessions continue without losing context.
- Keep a git-friendly workflow: suggest a commit message at the end of each milestone.

## 3. Project summary
A Django web application to manage vacant-quarter auctions: public home page with rules and FAQ, email-OTP sign-up and email login, "Register for bidding" (multiple quarters, Aadhaar/PAN encrypted), two emailed PDFs, offline EMD payment through SBI Collect verified by an officer per quarter, Excel import of quarters with their bidding slots, real-time anonymous bidding with Django Channels and WebSockets, automatic closure with a 2-quarter allotment cap, and winner email.

The workflow below follows Change Request #3 (`docs/CHANGE_REQUEST_3.md`, the mentor's final workflow), which superseded the original workflow.

This is a proposed training system. Do not describe its workflow or business rules as official SAIL policy unless I provide authoritative confirmation.

## 4. Business workflow (Change Request #3)

**1. Public website (no login)**: home page with an introduction, bidding rules and FAQ (one editable place: `templates/content/`), and Login / Create account buttons. **No quarter information is public** (user decision 2026-10-14, overriding CR #3's placeholder): the quarter list and the auction pages need a login. All wording is placeholder text, never official SAIL policy.

**2. Sign-up**: name, phone (collected, NOT verified), email; then a 6-digit email OTP (stored hashed, 10-minute expiry, 5 wrong attempts max, resend cooldown, rate limits per email and per IP, single use); then a password (Django hashing + validators). The user is logged in and lands on the quarter listing. Secure password reset by email.

**3. Login and quarter listing**: login with email + password. The listing shows every quarter up for auction (including EMD and slot and status), the user's registration status (not registered / documents pending / active), and which quarters they are eligible for. "Register for bidding" button in the corner.

**4. Register for bidding**: name (pre-filled), father's name, address/state/PIN (addition, to be confirmed), Aadhaar (12 digits, Verhoeff), PAN, and any number of quarters (searchable list with EMD per quarter and a running total). Aadhaar/PAN are encrypted at rest, masked everywhere (last 4 only), never logged or emailed, and revealed only through one audited admin action. On submit: Application (number + date), 7-digit URN (+ date), and ONE email (sent after commit, exactly once) with: A. Application Form (application no./date, QR, applicant details, quarters, declaration, URN); B. Intimation Slip (URN/date, name, phone, quarter table with EMD each and total, SBI Collect instructions). Quarters can be added later (supplementary slip for the added ones only) until N hours before their slot.

**5. Offline verification (admin)**: the applicant brings originals and EMD receipts. The Verification Officer ticks a document checklist (admin-editable) and records/verifies the EMD receipt PER QUARTER (receipt no., amount, date, amount covers the EMD). "Activate" only when all required documents are ticked. Reject / suspend / un-verify need a reason. Every action is audit-logged (who, when). States: REGISTERED -> DOCUMENTS_PENDING -> ACTIVE (or REJECTED / SUSPENDED). Bidding right for a quarter = ACTIVE AND that quarter's EMD verified. Roles: "Verification Officer" (applicant data, verification) and "Auction Admin" (Excel import, auctions; no personal data).

**6. Admin uploads the quarter Excel**: each row creates a Quarter AND its Auction (SCHEDULED) atomically; the bidding window comes from the file (see section 9).

**7. Bidding day**: each quarter has its own slot (default 5 minutes, editable per auction before it starts); several can run at once. Only eligible applicants get an anonymous per-auction code ("Bidder 7") and may bid; any logged-in user may watch. Step = `increment_percent` x base rate (default 0.20 %), whole rupees. Quick bids +1/+2/+5 steps; custom amount >= highest + one step; first bid >= base rate. `transaction.atomic()` + `select_for_update()` on the Auction row; duplicates and out-of-window bids rejected; accepted bids stored and broadcast (code, amount, time, new highest, remaining time); reconnect resyncs. Anti-sniping: per-auction `anti_snipe_seconds`, 0 = off (default).

**8. Closing and results**: a background worker closes due auctions atomically and idempotently. Winner = highest valid bid (tie: earliest). If that bidder already holds `MAX_QUARTERS_PER_APPLICANT` (2) allotted quarters or is no longer eligible, the next-highest eligible bidder wins; if none: CLOSED_NO_VALID_WINNER. Outcomes: CLOSED_WON, CLOSED_NO_BIDS, CLOSED_NO_VALID_WINNER. The result (winning code, amount, total bids) is published on the same auction page. Winner email once (`winner_email_sent_at`); loser emails off by default.

Online/QR/mock payment is dropped: EMD is paid offline through SBI Collect and verified by the officer. Refunds are out of scope.

## 5. Anonymity and privacy
- Bidder identity must NEVER appear on public auction pages, bid history, ordinary admin screens, or in WebSocket messages (no name, email, phone, URN, Aadhaar, PAN, password, or other private data).
- Aadhaar and PAN: encrypted at rest (Fernet, keys in `.env`), keyed hash for uniqueness, masked display (last 4), never logged or emailed, full value only via the audited "reveal" action (Verification Officer).
- The database keeps an internal Applicant-to-anonymous-code mapping so eligibility can be checked, bids audited, disputes resolved, and the real winner notified.
- Do not claim identities are cryptographically anonymous or absent from the database.

## 6. Technology stack
Python, Django 5.2 LTS, Django ORM, django-environ, openpyxl (Excel), Django Channels + Daphne (ASGI), Redis channel layer for multi-process deployment, Django templates/HTML/CSS/JavaScript, a Python PDF library and QR library (explain options and choose with me), Django SMTP email backend, a background scheduler/worker (explain options and choose with me).

Database: start on SQLite for early milestones ONLY. PostgreSQL is required before the bidding work, because `select_for_update()` has no effect on SQLite. Do not add blockchain, machine learning, microservices, or unrelated technology.

## 7. Project structure
```
AUCTION/
├── manage.py, requirements.txt, .env (not committed), .env.example
├── CLAUDE.md, PROGRESS.md, README.md
├── docs/            (architecture, demo script, deployment, how-to-change, change requests)
├── sample_data/     (FAKE Excel files + make_samples.py + README.md)
├── scripts/         (PowerShell helpers: PostgreSQL, server, worker, email)
├── config/          (settings, urls, asgi, email helpers)
├── templates/       (base layout, home page, content/ = rules + FAQ text)
├── accounts/        (custom User with email login, sign-up OTP, login, password reset)
├── applications/    (Register for bidding, Aadhaar/PAN, URN, PDFs, verification, roles, audit log, eligibility)
└── auctions/        (quarters, Excel import, auctions, bidding, WebSockets, closure, result emails)
```
**Current state:** all features of Change Request #3 are built (see PROGRESS.md). `TIME_ZONE = "Asia/Kolkata"`, `USE_TZ = True`, `AUTH_USER_MODEL = "accounts.User"`.

## 8. Data models
- **User** (accounts): custom, email is the login (`USERNAME_FIELD = "email"`, unique case-insensitively), `full_name`, `phone` (not verified), `email_verified_at`.
- **EmailOTP** (accounts): email, purpose, `code_hash` (keyed hash, never the code), `expires_at`, `failed_attempts`, `used_at`.
- **Applicant** (applications): OneToOne User; name, father's name, address, state, PIN; Aadhaar/PAN as `*_encrypted` + `*_index` (unique keyed hash) + `*_last4`; application no./date; URN (unique 7 digits)/date; `documents_emailed_at`; `status` (REGISTERED, DOCUMENTS_PENDING, ACTIVE, REJECTED, SUSPENDED) + reason/when/by.
- **QuarterApplication** (applications): applicant + quarter (unique together), `emd_amount` (copied), slip emailed; EMD receipt no., amount paid, payment date, `emd_verified`, verified by/at (DB check: verified => complete and amount >= EMD).
- **DocumentChecklistItem / DocumentCheck** (applications): admin-editable checklist; one tick per applicant per item with who/when.
- **AuditLog** (applications): actor, action, applicant, summary, details (never a full Aadhaar/PAN).
- **Quarter** (auctions): `quarter_no` (unique, case-insensitive), sector, location/block, type A-D, floor, area, base rate, `emd_amount`, status (Vacant / In Auction / Allotted).
- **Auction** (auctions): quarter, `start_time`, `duration_minutes`, `end_time` (= start + duration, extended by anti-sniping), `original_end_time`, status (SCHEDULED, CLOSED_WON, CLOSED_NO_BIDS, CLOSED_NO_VALID_WINNER, CANCELLED), `increment_percent`, `anti_snipe_seconds`, `extensions_count`, `current_highest_bid`, `winning_bid`, `closed_at`, `total_bids`, `winner_email_sent_at`.
- **Participation** (auctions): applicant + auction + `bidder_number` ("Bidder N"); unique (applicant, auction) and (auction, number). Only for eligible applicants.
- **Bid** (auctions): auction, participation, amount (whole rupees), time, `client_bid_id` (duplicate protection), previous highest, deadline extension (audit).

Money is DecimalField; constraints, indexes and PROTECT foreign keys as described in `docs/ARCHITECTURE.md`.

## 9. Excel import
Columns, in this exact order and spelling (row 1 = headers):
`Quarter No | Sector | Location / Block | Type | Floor | Area (sq ft) | Base Rate (Rs.) | EMD Amount (Rs.) | Bidding Date | Start Time | Duration (min)`

Rules:
- Each valid row creates a Quarter and its Auction (SCHEDULED). End = start + duration; blank duration = `DEFAULT_AUCTION_DURATION_MINUTES` (5).
- Quarter No unique text; Area, Base Rate, EMD positive numbers ("4,500" accepted); date and time read in Asia/Kolkata from real Excel date/time cells or text (DD-MM-YYYY, HH:MM, 2:15 PM...); start must be in the future; duration a whole number 1-1440.
- Report ALL errors with row numbers and column names. Reject duplicates inside the file and against the database. All-or-nothing (`transaction.atomic()`). Blank rows and extra whitespace handled.

### Sample data (FAKE test data, `sample_data/`)
`python sample_data/make_samples.py` writes four files with the bidding date one week ahead (the importer refuses past starts): `quarters_sample.xlsx` (8 valid rows: B-214, B-118, C-305, C-112, D-407, D-203, A-021, A-134; base rates in tens of thousands), `quarters_invalid.xlsx` (9 deliberate errors), `quarters_bad_header.xlsx`, `quarters_edge_cases.xlsx` (valid but awkward: text dates/times, separators, spaces, blank duration, blank row). See `sample_data/README.md`. The tests build the same workbooks in memory.

## 10. Critical engineering requirements
- Server-side validation for every bid.
- Atomic transactions for bidding and closure; correct behavior under simultaneous bids.
- Auction-specific WebSocket authorization.
- Secure activation and password reset.
- Protection against duplicate bids and duplicate notifications.
- Clear Excel import errors.
- No leakage of applicant information.
- Secure production configuration and secrets management.
- Audit-friendly accepted-bid history.
- Automated tests for important business rules.
- Graceful handling of network interruptions and stale browser state (reconnect, resync current highest bid and time).

Before introducing database locking, Channels groups, WebSocket consumers, transaction boundaries, and background jobs, explain each with a simple example first.

## 11. Milestones (Change Request #3) - all complete
1. Foundation: custom user model, Quarter + Auction models, Excel import (new columns), admin, sample files, tests.
2. Public site (home, rules, FAQ), email-OTP sign-up, login/logout, password reset, quarter listing.
3. Register for bidding, Aadhaar/PAN safeguards, URN, Application Form + Intimation Slip PDFs, email.
4. Admin verification: checklist, per-quarter EMD, activation, audit log, roles, eligibility.
5. Auction room on PostgreSQL/Channels/Daphne: anonymous codes, percentage/custom/quick bidding with locking, live updates, timer.
6. Automatic closure, 2-quarter cap, result on the auction page, winner email, concurrency tests, documentation, demo.

Before CR #3 the original five milestones were completed (git history up to commit 3e68a94).

## 12. Open questions (keep unresolved; use labeled placeholders)
From the original plan:
1. Who generates the URN? (placeholder: system, 7 digits)
2. SBI Collect payee details? (placeholder: `SBI_COLLECT_PAYEE` setting, "DEMO")
3. Ties? (placeholder: earliest accepted bid wins; amounts are unique per auction anyway)
4. Official auction, allotment and record-retention rules? (ask mentor)
5. What does "Base Rate" mean: total, monthly rent, or per sq ft? (affects labels)
6. Step rounding: 0.2 % of the base rate is rounded to the nearest rupee, minimum Rs. 1 (user: base rates are in tens of thousands, so this rarely matters).

From Change Request #3:
7. Is storing the full Aadhaar number permitted? (placeholder: encrypted + masked, pending mentor/legal approval; alternative: last 4 + verified flag) - MUST be confirmed before real use.
8. Ranked choices or multi-select? (placeholder: unranked multi-select)
9. First bid = base rate or base + one step? (placeholder: >= base rate)
10. Adding quarters later, and until when? (placeholder: allowed until `APPLICATION_CLOSES_HOURS_BEFORE_AUCTION` = 24 h before that quarter's slot; supplementary slip)
11. Custom bid a multiple of the step? (placeholder: any whole-rupee amount >= highest + one step)
12. Anti-sniping on 5-minute auctions? (placeholder: off; recommendation if wanted: 30 s, max 5 extensions)
13. Capped top bidder: next-highest or vacant? (placeholder: next-highest eligible bidder, at their own highest bid)
14. Exact document checklist and official wording (rules, FAQ, declaration)? (placeholder: CR #3 list, editable)
15. Phone verification by SMS later? (placeholder: not verified)
16. Quarter information public before login? DECIDED by the user (2026-10-14): **no**, quarters, auction pages and live updates need a login.
17. Deployment, database, retention, refunds? (placeholder: PostgreSQL; refunds out of scope)
Also: paying MORE than the EMD is accepted as verified (assumption); "you cannot outbid yourself" kept from earlier milestones (assumption).

If one of these blocks a design decision, ASK me instead of guessing.

## 13. Final deliverable
A working Django app demonstrating: public site with rules/FAQ, email-OTP sign-up and email login, password reset, register for bidding (Aadhaar/PAN safeguards), PDF generation and email, offline verification with audit log, Excel import of quarters and slots, multiple simultaneous auctions, anonymous real-time bidding, correct concurrent-bid handling, automatic closure and winner selection, winner notification, bid history and auditability, automated tests, and project documentation (report, architecture diagram, ER diagram, workflow diagram, demo script).

## 14. Next session
Read PROGRESS.md first. All CR #3 features are built and tested; remaining work is whatever the mentor answers to the open questions in section 12.
