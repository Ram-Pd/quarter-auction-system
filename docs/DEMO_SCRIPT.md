# Demo script (about 20 minutes)

All data shown is **FAKE**. Say so at the start: this is a training project and its
rules are placeholders, not SAIL policy. The workflow is the mentor's Change Request #3.

## Before the demo (do it 5 minutes beforehand)

Three PowerShell windows in the project folder:

| Window | Command |
|---|---|
| 1 | `.\scripts\run_server.ps1` (starts PostgreSQL + the website) |
| 2 | `.\scripts\run_worker.ps1` (closes finished auctions, sends winner emails) |
| 3 | `.\venv\Scripts\Activate.ps1`, then commands during the demo |

Fresh demo data, in window 3 (to start from zero first: drop/recreate the database, then `python manage.py migrate`):
```powershell
python sample_data/make_samples.py   # sample files with a bidding date one week ahead
python manage.py seed_demo           # demo quarters, live auctions, staff and bidders
```
The live demo auctions (L-301, L-302) run for 20 minutes from the moment you seed, and
L-303 starts 10 minutes later: **seed just before the demo**. Password for every demo
account: `Demo-Pass-2026`.

Use **two different browsers** (Edge and Chrome), or one normal and one private window,
so two people can be logged in at once.

If no SMTP password is set, emails appear in window 1 and as `.eml` files in `sent_emails\`
(double-click to open, PDFs attached).

---

## 1. Public website (1 min)
1. Open http://127.0.0.1:8000/ without logging in.
2. *Point out:* the **rules** and **FAQ** (one editable place: `templates/content/`) and the
   **Login** button in the corner. **No quarter information** is shown to visitors: the
   quarter list appears only after sign-up / login. Try http://127.0.0.1:8000/auctions/1/
   directly: you are sent to the login page.

## 2. Admin: Excel import (2 min) - log in as `auctionadmin@example.com` at /admin/
1. **Quarters → Import from Excel →** `sample_data\quarters_bad_header.xlsx`: header error, nothing imported.
2. `quarters_invalid.xlsx`: **9 errors** with row and column (duplicate, "abc" area,
   negative rate, missing number, EMD 0, 31-02-2026, start in the past, 25:00, duration 0).
   The valid row 2 is NOT saved (all-or-nothing).
3. `quarters_edge_cases.xlsx`: 4 quarters imported even with text dates, "2:15 PM",
   "1,050", extra spaces and a blank row. Open **Auctions**: each row created its slot;
   blank duration = 5 minutes.
4. *Point out:* the Auction Admin has **no** Applicants menu: no personal data.

## 3. Sign-up with email code (2 min) - browser 1
1. **Login → Create account**: name, phone (`+91 98765 43210` is accepted), a new email.
2. The 6-digit code appears in window 1 (or the `.eml` file). Type a wrong code first:
   *"Incorrect code. 4 attempts left."* Then the right code.
3. Choose a weak password (`password`): refused. Then a strong one → logged in, on the
   quarter listing with status **Not registered**.
4. *Explain:* the code is stored only as a keyed hash, expires in 10 minutes, dies after
   5 wrong tries, works once; resend has a 60 s cooldown and hourly limits.

## 4. Register for bidding (3 min) - same browser
1. **Register for bidding**: name is pre-filled. Type in the search box ("Sector 4"), tick
   two or three quarters: **running EMD total** updates.
2. Enter a mistyped Aadhaar (change the last digit of a valid one): *"check digit does not match"*.
   (A valid FAKE number: `234567890124`.) PAN e.g. `ABCPE1234F`.
3. Submit → **My application**: status *Documents pending*, Aadhaar shown as `XXXX XXXX 0124`.
4. Open the email: **Application Form** (QR, URN, quarters, declaration, masked IDs) and
   **Intimation Slip** (URN, EMD per quarter, total, SBI Collect steps). Refresh the page:
   no second email.

## 5. Offline verification (3 min) - browser 2, `officer@example.com` at /admin/
1. **Applicants → Verify** on the new application.
2. *Activate bidder* is disabled: required documents missing. Tick the checklist → save.
3. For ONE quarter: enter a receipt with a **smaller** amount → "amount is LESS than EMD",
   *Mark EMD verified* disabled. Correct the amount → verify.
4. **Activate bidder.** Show the **history (audit log)**: who did what, when.
5. **Reveal** (type a reason): full Aadhaar shown once and logged; reload → hidden again.
6. Back in browser 1, the listing now says **Active**, "eligible to bid on **1** quarter":
   the EMD for one quarter gives no right to bid on another.

## 6. Live bidding (5 min) - `demo1@example.com` in browser 1, `demo2@example.com` in browser 2
1. Both open **L-301** (live). Each sees only their own code ("Bidder 1" / "Bidder 2").
2. Bidder 1 clicks **+1 step** (= base rate for the first bid). Bidder 2 sees it instantly.
3. Bidder 2 types an amount below highest + one step: refused with the minimum.
   Then **+5 steps**: accepted. Bid step = 0.2 % of the base rate (Rs. 90 on 45,000).
4. Log in as `demo5@example.com` (not registered for bidding) in a private window and open
   the same auction: it can watch live but has no bid panel, and says why.
5. Stop and restart the server (window 1): pages show "Reconnecting…", then resync.
6. Admin (superuser) → Bids: amounts by code only. **Participations** (who is behind
   each code) is visible to superusers only.

## 7. Closing and results (3 min)
1. Wait for L-301 to end, or in admin set an auction's time so it ends now. The worker
   closes it within ~5 s (or the open page triggers closure at 00:00).
2. Winner's page: "Congratulations, you won!"; other logged-in users see
   "Won by Bidder N with Rs. ..., Total bids: N". Winner email in window 1 (once only).
3. *Explain the 2-quarter cap:* if the top bidder already holds 2 quarters, the
   next-highest eligible bidder wins; if nobody qualifies: "No valid winner", quarter stays
   vacant. Show `AllotmentCapConcurrencyTests`: two auctions closing at the same instant
   can't give anyone a third quarter (it fails if the lock is removed).

## 8. Tests (1 min)
```powershell
python manage.py test        # 211 tests
```

---

## Likely questions

| Question | Answer |
|---|---|
| Is the Aadhaar number safe? | Encrypted (Fernet) with keys in `.env`, never in plain text in the database, emails or logs; masked everywhere; full number only via an audited reveal. Whether we may store it at all is an **open legal question** for the mentor. |
| What if two people bid at the same moment? | The auction row is locked; bids are processed one at a time. Proven by the concurrency tests on real PostgreSQL. |
| What if the internet drops? | The page reconnects with backoff and the server sends a full snapshot. A double-sent bid is recognised by its id. |
| Who can see who bid? | Only superusers (Participation table). Everyone else sees codes. |
| Can the officer change a verified EMD? | Only by un-verifying it first, with a reason; both actions are logged. |
| Why can't the Auction Admin see applicants? | Separation of duties: the roles are Django groups defined in `applications/roles.py`. |
| What rules are official? | None yet. All rules are placeholders listed in CLAUDE.md section 12. |
