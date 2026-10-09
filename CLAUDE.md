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
A Django web application to manage vacant-quarter auctions: Excel import of quarters, applicant registration, two emailed PDFs, offline EMD payment through SBI Collect, URN-based account activation, auction lobby, real-time anonymous bidding with Django Channels and WebSockets, automatic auction closure, and winner email.

This is a proposed training system. Do not describe its workflow or business rules as official SAIL policy unless I provide authoritative confirmation.

## 4. Business workflow

**Phase 1, Admin setup**
- Admin imports vacant-quarter data from Excel, with validation and no duplicate quarter numbers.
- Admin configures an auction per eligible quarter (start, end, minimum increment, anti-sniping extension).
- Multiple auctions must be able to run simultaneously.

**Phase 2, Applicant registration**
Collect: name, father's name, mobile number, email, address, state, PIN code. No password or URN is entered at this stage.

**Phase 3, Two PDFs generated and emailed**
- A. Auction Application Form: application number and date, QR code, auction and quarter details, applicant details and address, declaration.
- B. Auction Intimation Slip: URN and URN date, applicant name and mobile, EMD amount, SBI Collect payment instructions.
- URN: unique seven-digit number, system-generated for now (assumption). If SAIL supplies URNs, design an import mechanism instead.

**Phase 4, External EMD payment**
- Applicant pays through SBI Collect using the URN.
- Verification is manual and offline. No online payment gateway. Refunds are out of scope.

**Phase 5, Account activation**
- Applicant enters email + URN. The system verifies a matching, eligible applicant record. Applicant sets a password.
- Username = URN. Use Django authentication and password hashing. Include secure password reset.
- Never allow activation based only on publicly guessable information.

**Phase 6, Auction lobby**
Show quarter number, sector/location, floor, area, base rate, start and end time, auction status, and relevant live information.

**Phase 7, Real-time bidding** (Django Channels + WebSockets)
- Each auction has its own WebSocket group. Different auctions run at the same time.
- A participant gets an anonymous code such as "Bidder 7" per auction, unique within that auction. The same applicant may have different codes in different auctions.
- Validate every bid on the server. A bid must exceed the current highest accepted bid by at least the configured minimum increment.
- Store accepted bids in the database. Broadcast accepted bids (anonymous code, amount, timestamp), the new highest bid, and remaining time.
- Use database transactions and row locking (`select_for_update()` on the Auction row) so simultaneous bids cannot conflict.
- Anti-sniping: a valid bid in the final minute extends the deadline. Extension length is a per-auction field.
- Reject duplicate submissions and bids on closed auctions.
- Authorize each WebSocket connection per auction.

**Phase 8, Automatic closure**
- A background process finds auctions past their deadline and closes them atomically.
- Closure must be idempotent: multiple workers must never award the same quarter twice.
- Determine the highest valid bid, store the final result and winner, mark the quarter Allotted only when there is a valid winner.
- Separate outcome for auctions with no valid bids.

**Phase 9, Winner notification**
Email the winner: congratulations, quarter number, sector/location, floor, area, winning amount, next steps. Loser notifications are optional and off by default.

## 5. Anonymity and privacy
- Bidder identity must NEVER appear on public auction pages, bid history, ordinary admin screens, or in WebSocket messages (no name, email, URN, mobile, password, or other private data).
- The database keeps an internal Applicant-to-anonymous-code mapping so eligibility can be checked, bids audited, disputes resolved, and the real winner notified.
- Do not claim identities are cryptographically anonymous or absent from the database.

## 6. Technology stack
Python, Django 5.2 LTS, Django ORM, django-environ, openpyxl (Excel), Django Channels + Daphne (ASGI), Redis channel layer for multi-process deployment, Django templates/HTML/CSS/JavaScript, a Python PDF library and QR library (explain options and choose with me), Django SMTP email backend, a background scheduler/worker (explain options and choose with me).

Database: start on SQLite for early milestones ONLY. PostgreSQL is required before the bidding work, because `select_for_update()` has no effect on SQLite. Do not add blockchain, machine learning, microservices, or unrelated technology.

## 7. Project structure
```
sail_auction/
├── manage.py
├── requirements.txt
├── .env              (secrets, not committed)
├── .gitignore
├── CLAUDE.md
├── PROGRESS.md
├── sample_data/
├── config/           (settings, urls, asgi)
├── accounts/         (applicants, registration, activation)
└── auctions/         (quarters, auctions, participation, bids)
```
**Current state: nothing is built yet. Fresh start.** Create the project with `django-admin startproject config .` and the two apps `accounts` and `auctions`. Set `TIME_ZONE = "Asia/Kolkata"` and `USE_TZ = True`.

## 8. Data models
- **Quarter**: `quarter_no` (CharField, UNIQUE, alphanumeric like "B-214"), `sector`, `location_block`, `quarter_type` (A/B/C/D), `floor` (text: Ground, 1st, 2nd...), `area_sqft` (Decimal), `base_rate` (Decimal), `status` (Vacant / In Auction / Allotted).
- **Applicant**: name, father's name, mobile, email, address, state, PIN, application number/date, URN (unique 7-digit), URN date, `is_verified` (manual admin flag), `is_activated`, and a nullable `OneToOneField` to Django's `User`. The User is created only at activation with username = URN, so the password is stored in one place only.
- **Auction**: link to Quarter, start_time, end_time, status, min_increment, anti_snipe_extension, current_highest_bid, final result and winner fields.
- **Participation**: Applicant + Auction + anonymous_code. UniqueConstraint on (applicant, auction) and on (auction, anonymous_code).
- **Bid**: auction, participation, amount, timestamp, acceptance/audit information.

Use DecimalField for money, proper foreign keys, uniqueness constraints, indexes, and sensible `on_delete` rules. Explain any extra model you introduce.

## 9. Excel import
Expected columns, in this exact order and spelling:
`Quarter No | Sector | Location / Block | Type | Floor | Area (sq ft) | Base Rate (Rs.) | Status`

Rules:
- Quarter No is unique and stored as text. Sector, Location/Block, Type, Floor are text. Area and Base Rate are positive numbers. Status is "Vacant" on import.
- Validate the header row and every data row. Report ALL errors with row numbers and column names, not just the first.
- Reject duplicates inside the file and against the database.
- Import atomically (all or nothing) inside `transaction.atomic()`, unless I choose otherwise.
- Handle blank rows, extra whitespace, and numbers with thousands separators (e.g. "4,500") sensibly.

### Sample data (create these, clearly marked as FAKE test data)
Using openpyxl, create:
1. `sample_data/quarters_sample.xlsx` with exactly these 8 valid rows:

| Quarter No | Sector | Location / Block | Type | Floor | Area (sq ft) | Base Rate (Rs.) | Status |
|---|---|---|---|---|---|---|---|
| B-214 | Sector 4 | Near market | Type B | 2nd | 750 | 4500 | Vacant |
| B-118 | Sector 4 | Near market | Type B | Ground | 750 | 4800 | Vacant |
| C-305 | Sector 2 | Opposite park | Type C | 3rd | 620 | 3600 | Vacant |
| C-112 | Sector 2 | Opposite park | Type C | 1st | 620 | 3900 | Vacant |
| D-407 | Sector 9 | Near school | Type D | 4th | 480 | 2400 | Vacant |
| D-203 | Sector 9 | Near school | Type D | 2nd | 480 | 2700 | Vacant |
| A-021 | Sector 12 | Main road side | Type A | Ground | 980 | 6200 | Vacant |
| A-134 | Sector 12 | Main road side | Type A | 1st | 980 | 6000 | Vacant |

2. `sample_data/quarters_invalid.xlsx` with deliberate errors: a duplicate Quarter No, a non-numeric Area, a negative Base Rate, and a missing Quarter No.
3. `sample_data/quarters_bad_header.xlsx` with a wrong header name.

The sample figures are placeholders, not official SAIL data. Use these files in the import tests and in my manual demonstration.

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

## 11. Milestones (proposed, not completed)
1. **Foundation** (CURRENT): project and apps, settings, `.env`, Quarter + Applicant models with constraints, admin registration, sample Excel files, Excel import (admin upload) with validation and tests.
2. Applicant registration form, URN generation, PDF generation (form + slip with QR), email sending.
3. Activation, login/logout, password reset, auction creation, lobby.
4. Switch to PostgreSQL, Channels, Daphne, Redis, consumers, anonymous codes, bid validation with locking, live updates, countdown, anti-sniping.
5. Automatic closure, winner selection and email, bid history, concurrent-auction tests, documentation, demo.

Target pace is about four weeks; treat it as a proposal.

## 12. Open questions (keep unresolved; use labeled placeholders)
1. Who generates the URN? (placeholder: system, 7 digits)
2. Official EMD amount and SBI Collect process? (placeholder: configurable setting)
3. How is eligibility verified? (placeholder: admin `is_verified` flag)
4. Minimum bid increment? (placeholder: per-auction field)
5. Anti-sniping extension length? (placeholder: per-auction field, e.g. 2 minutes)
6. Ties or equal bids? (placeholder: earliest accepted bid wins)
7. No valid bids? (placeholder: status CLOSED_NO_BIDS, quarter stays Vacant)
8. Winning bidder becomes ineligible? (out of scope; keep audit data)
9. Notify losing bidders? (placeholder: off by default)
10. Official auction, allotment, and record-retention rules? (ask my mentor)
11. Approved database and deployment environment? (PostgreSQL preferred; ask my mentor)
12. What does "Base Rate" mean: total price, monthly rent, or per sq ft? (affects field labels and increment sizing)

If one of these blocks a design decision, ASK me instead of guessing.

## 13. Final deliverable
A working Django app demonstrating: Excel quarter import, applicant registration, PDF generation and email, URN-based activation, authentication and password reset, auction creation and lobby, multiple simultaneous auctions, anonymous real-time bidding, correct concurrent-bid handling, automatic closure and winner selection, winner notification, bid history and auditability, automated tests, and project documentation (report, architecture diagram, ER diagram, workflow diagram, demo script).

## 14. First task
1. Read this file and summarize your understanding in a few lines.
2. Confirm the Milestone 1 plan.
3. Ask me for what you need: my operating system, my Python version (`python --version`), and whether PostgreSQL is installed.
4. Do not write code until I confirm.
