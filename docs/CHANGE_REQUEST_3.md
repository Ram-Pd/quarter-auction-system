# CHANGE REQUEST #3: Final workflow from my mentor (supersedes Change Requests #1 and #2)

This file REPLACES the workflow, data model, Excel format, and milestone sections of CLAUDE.md. Keep CLAUDE.md's role, working rules (one step at a time, state the plan first, real command output, tests, no invented official rules), anonymity/privacy rules, tech stack, and engineering requirements. If this file conflicts with CLAUDE.md, this file wins. Online/QR/mock payment is DROPPED. EMD is paid offline through SBI Collect and verified by the admin.

## Before writing any code
1. Inspect the project folder and tell me what already exists and which parts this change affects. If nothing exists yet, say so.
2. Settle the user model first: login is by email + password, so propose a custom user model (email as the login identifier) BEFORE the first migration, because changing it later is painful. Explain your recommendation.
3. Give me a short step plan, ask the open questions at the bottom, and wait for my confirmation. Do not code until I confirm.

## The flow, step by step

### 1. Public website (no login needed)
- Home page with: basic information about the quarters being auctioned (quarter no., locality, type, floor, area, base rate, bidding date/time slot; public data only), the basic bidding rules, an FAQ section about bidding, and a "Login" button in the top corner.
- Rules and FAQ text must live in one editable place (template include or admin-editable content model), not scattered across files. All wording is placeholder text pending mentor confirmation. Never present it as official SAIL policy.

### 2. Sign-up (account creation)
- "Login" button leads to a page with Login and a "Create account" option.
- Create account form: name, phone number, email, then EMAIL OTP verification, then create a password. Phone number is collected but NOT verified (only email is).
- OTP rules: 6 digits, stored hashed (never plaintext), expires in 10 minutes (setting), maximum 5 wrong attempts, resend cooldown, rate limiting per email and per IP, single use. In development use Django's console email backend.
- Passwords use Django's hashing and password validators. Include secure password reset (also via email).
- After sign-up the user is logged in and lands on the auction listing page (step 3).

### 3. Returning login and the quarter listing page
- Returning users log in with email + password.
- The landing page after login lists all quarters up for auction (quarter no., locality, type, floor, area, base rate, EMD amount, bidding date and time slot, auction status).
- A "Register for bidding" button sits in the top corner (see step 4). The page also shows the user's registration status (not registered / documents pending / active) and, once registered, which quarters they are eligible for.

### 4. Register for bidding (application form)
- Fields: name, father's name, quarter choices, Aadhaar number, PAN number. (Pre-fill name from the account; also collect the address, state, and PIN code that the Application Form needs, flagged as an addition I will confirm.)
- Quarter choices: a scrollable, searchable list where the user can select as many quarters as they want. They may apply for many, but can be ALLOTTED at most 2 (setting `MAX_QUARTERS_PER_APPLICANT = 2`). Show each quarter's EMD amount next to its name and a running total of EMD for the selection.
- Aadhaar and PAN handling (sensitive; treat carefully):
  - Validate format (PAN pattern; Aadhaar 12 digits with Verhoeff checksum).
  - Store encrypted at rest (explain the library options and choose with me), never log them, never put them in email bodies, never show the full number in lists. Mask all but the last 4 characters everywhere except a single audited admin "reveal" action.
  - Never expose them on any public page, bid history, WebSocket message, or non-verification admin screen.
  - This needs mentor/legal confirmation (see open questions); until then implement the safeguards above.
- On submit, the system: creates an Application (unique application number and date), generates a unique 7-digit URN with its date, and emails TWO PDFs:
  A. Application Form: application no. and date, QR code, applicant details, selected quarters, declaration, URN.
  B. Intimation Slip: URN and date, applicant name and phone, a table of selected quarters each with its own EMD amount and the total, and SBI Collect payment instructions using the URN.
- Send the email after the database commit (`transaction.on_commit`), exactly once; do not re-send on page refresh.

### 5. Offline verification and activation (admin side)
- The applicant brings the original documents and the payment receipt(s) in person. The admin records the result in a verification screen with a CHECKLIST per application:
  - Document checklist (placeholder items, editable by admin/setting): identity proof (Aadhaar), PAN, address proof, photograph, signed application form, other.
  - For each selected quarter: EMD receipt verified (receipt/reference no., amount paid, payment date, amount matches that quarter's EMD, verified yes/no).
- Admin "Activate bidder" is allowed only when all required document items are ticked. Record who did each action and when (audit log). The admin can also reject an application or un-verify a quarter's payment with a reason.
- Applicant states: `REGISTERED` (applied) -> `DOCUMENTS_PENDING` -> `ACTIVE` (or `REJECTED`/`SUSPENDED`).
- Bidding eligibility for a given quarter requires BOTH: applicant is `ACTIVE`, AND that quarter's EMD is marked verified for this applicant. Paying EMD for quarter A grants no right to bid on quarter B.
- Applicant data is visible only to authorized admin roles (use Django groups, for example "Verification Officer" and "Auction Admin"; explain how they differ).

### 6. Admin uploads the quarter Excel
Columns (exact order and spelling, row 1 = headers):
`Quarter No | Sector | Location / Block | Type | Floor | Area (sq ft) | Base Rate (Rs.) | EMD Amount (Rs.) | Bidding Date | Start Time | Duration (min)`
- "Locality details" = Sector + Location/Block. Keep Floor and Area because the winner email needs them (flagged as my addition; I will confirm).
- Each valid row creates a Quarter AND its Auction (status `SCHEDULED`) atomically, so the bidding window comes straight from the Excel. Duration is optional per row; default is the global setting (`DEFAULT_AUCTION_DURATION_MINUTES = 5`). End time = start time + duration. Duration remains editable per auction in the admin before the auction starts.
- Validation: row-level errors with row numbers and column names (all errors, not just the first); Quarter No unique and text; Base Rate and EMD positive numbers; EMD may differ per quarter; date and time parsed in Asia/Kolkata (handle both real Excel date/time cells and text); start must be in the future; duration positive; duplicates inside the file and against the database rejected; whole import is all-or-nothing (`transaction.atomic()`). Handle blank rows, whitespace, and thousands separators like "4,500".
- Update `sample_data/` (valid file, invalid file with deliberate errors, bad-header file, edge-case file) and `sample_data/README.md` for the new columns, and mark them as FAKE data.

### 7. Bidding day
- Each quarter has its OWN bidding slot (its own Auction with its own start and end). Several auctions may run at the same time or back to back.
- A user may enter a quarter's auction room only if eligible for THAT quarter (rule in step 5). Others can view the public page but cannot bid. Enforce on the server and on the WebSocket connection, per auction.
- Duration: 5 minutes by default, editable (see step 6).
- Anonymous code per applicant per auction ("Bidder 7"), unique within that auction, different across auctions. Names, emails, phone numbers, URNs, Aadhaar, and PAN must never appear on public pages, bid history, or WebSocket messages.
- Bid increments (all money in Decimal, rounded to whole rupees, server-side validation):
  - Increment step = `increment_percent` x Base Rate. Default `increment_percent = 0.2` (percent), editable per auction. Example: base rate 4,500 -> step 9.
  - Quick-bid buttons: "+1 step", "+2 steps", "+5 steps" over the current highest bid.
  - Custom amount: the user types any amount; it is accepted only if it is at least the current highest bid plus one step.
  - First bid placeholder rule: at least the Base Rate. (Open question 3.)
- Use `transaction.atomic()` and `select_for_update()` on the Auction row so simultaneous bids cannot conflict. Reject duplicate submissions and bids outside the window. Store every accepted bid for audit. Broadcast the accepted bid (anonymous code, amount, timestamp), the new highest bid, and the remaining time to the auction's WebSocket group. Support reconnect: on reconnect, resync current highest bid and remaining time.
- Anti-sniping: keep as an optional per-auction setting (`anti_snipe_seconds`, default 0 = off). With 5-minute auctions, I want your recommendation, and I will confirm with my mentor.

### 8. Closing and results
- A background process closes auctions whose end time has passed, atomically and idempotently (multiple workers must never award the same quarter twice).
- Winner = highest valid bid. Tie rule placeholder: the earliest accepted bid wins.
- 2-quarter cap: at closure, inside the same transaction, if the top bidder already holds `MAX_QUARTERS_PER_APPLICANT` allotted quarters, skip to the next-highest eligible bidder. If none, the outcome is "no valid winner" and the quarter stays vacant. Test that two auctions closing at the same moment cannot give one applicant a third quarter.
- Publish the result on the SAME auction page: status closed, winning amount, winner's anonymous code, total number of bids. No real identity is shown.
- Email the winner only: congratulations, quarter no., locality, floor, area, winning amount, next steps (placeholder wording). Send once only (track `winner_email_sent_at`). Loser emails: off by default (setting).
- Separate outcomes: `CLOSED_WON`, `CLOSED_NO_BIDS`, `CLOSED_NO_VALID_WINNER`.

## Data model (propose it, explain every table, and wait for my approval)
Likely: custom User (email login); EmailOTP; Applicant (profile, status, URN, URN date, application no., encrypted Aadhaar/PAN, masked display fields); Quarter (with `emd_amount`); Auction (quarter, start, end, duration, increment_percent, anti_snipe_seconds, status, highest bid, result fields); QuarterApplication (applicant + quarter selected, unique together); EmdVerification (per applicant per quarter: receipt no., amount, date, verified, verified_by, verified_at); DocumentChecklistItem / ApplicantDocumentCheck (item, ticked, ticked_by, ticked_at); Participation (applicant + auction + anonymous code, only for eligible bidders); Bid; AuditLog (who did what, when). Use DecimalField for money, proper constraints, indexes, and sensible `on_delete` rules.

## Revised milestones (proposal; one at a time)
1. Foundation: project, settings, `.env`, custom user model, Quarter + Auction models, Excel import (new columns, atomic, row-level errors), admin, sample files, tests.
2. Public site (home, rules, FAQ), email-OTP sign-up, login/logout, password reset, quarter listing page.
3. "Register for bidding" form, Aadhaar/PAN safeguards, URN, Application Form + Intimation Slip PDFs, email.
4. Admin verification: document checklist, per-quarter EMD receipt verification, activation, audit log, eligibility rules.
5. PostgreSQL, Channels, Daphne, Redis, auction room, anonymous codes, percentage/custom bidding with locking, live updates, timer.
6. Automatic closure, 2-quarter cap, result on the auction page, winner email, concurrency tests, documentation, demo.

## Also update
CLAUDE.md (sections 4, 8, 9, 11, 12), PROGRESS.md, and the sample files, so they all match this flow.

## Open questions (use the placeholder until I answer; ask me when one blocks a decision)
1. Is storing the full Aadhaar number permitted for this system? Aadhaar collection and storage are legally restricted in India. Placeholder: encrypted storage with masked display, pending mentor/legal approval; alternative: store only the last 4 digits plus a document-verified flag.
2. "Choice of quarters (1st choice...)": are choices RANKED (1st, 2nd, 3rd preference) or just a multi-select? Placeholder: unranked multi-select.
3. Can the first bid equal the Base Rate, or must it be Base Rate plus one step? Placeholder: first bid >= Base Rate.
4. Can an applicant add more quarters after the first application (a supplementary slip), and until when? Placeholder: allowed before a registration deadline setting; each addition triggers a new slip for the added quarters only.
5. Must a custom bid be a multiple of the step, or any amount above current + step? Placeholder: any whole-rupee amount >= current + one step.
6. Anti-sniping on a 5-minute auction: keep, and with what extension? Placeholder: off.
7. If the top bidder is capped out at 2 allotments, does the next-highest bidder win or does the quarter go back to vacant? Placeholder: next-highest eligible bidder.
8. Exact document checklist items and the official wording for rules/FAQ/declaration? Placeholder: my list above.
9. Does "phone number" need verification later (SMS OTP)? Placeholder: not verified.
10. Is quarter information, including base rate, allowed on the public page before login? Placeholder: yes.
11. Deployment and database (PostgreSQL), record-retention rules, and refund handling for non-winners? Placeholder: PostgreSQL; refunds out of scope.