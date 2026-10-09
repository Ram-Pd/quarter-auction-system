# Demo script (about 15 minutes)

All data shown is **FAKE**. Say so at the start: this is a training project and its
rules are placeholders, not SAIL policy.

## Before the demo (5 minutes, do it beforehand)

Open **three** PowerShell windows in the project folder and run in each
`.\venv\Scripts\Activate.ps1` first.

| Window | Command |
|---|---|
| 1 | `.\scripts\start_postgres.ps1` then `python manage.py runserver` |
| 2 | `python manage.py run_auction_worker` |
| 3 | (for commands during the demo) |

Fresh demo data (optional): in window 3,
```powershell
python manage.py seed_demo
```
Note the printed URNs. Demo password: `Demo-Pass-2026`.

Browsers: use **two different browsers** (e.g. Edge and Chrome), or one normal and one
private window, so two bidders can be logged in at once.

---

## 1. Admin: Excel import (2 min)
1. Open http://127.0.0.1:8000/admin/ and log in as superuser.
2. **Quarters → Import from Excel →** upload `sample_data\quarters_bad_header.xlsx`.
   *Point out: wrong header detected, nothing imported.*
3. Upload `sample_data\quarters_invalid.xlsx`.
   *Point out: all 4 errors listed with row and column; valid row 2 NOT saved (all-or-nothing).*
4. (If quarters are not yet imported) upload `sample_data\quarters_sample.xlsx`: 8 imported.

## 2. Applicant registration and documents (3 min)
1. Open http://127.0.0.1:8000/ → **Register**. Fill in the form (any fake email).
   Show validation: a 5-digit mobile number, no declaration tick.
2. Submit → success page shows the application number, **not** the URN.
   *Explain: the URN is only sent by email, so email + URN proves mailbox ownership.*
3. Open the newest file in `sent_emails\` (double-click) → show both PDFs:
   Application Form (QR code, no URN) and Intimation Slip (URN, EMD, SBI Collect steps).

## 3. Verification and activation (2 min)
1. Admin → **Applicants** → open the new applicant → tick **verified** → Save.
   *Explain: this stands in for the offline EMD check.*
2. Browser → **Activate** → email + URN (from the slip) + password → lands in the lobby.
3. Optional: show that a wrong URN gives "do not match", and 5 wrong tries lock it out.

## 4. Lobby (1 min)
Show Live / Upcoming / Recently closed, countdowns, base rate, minimum next bid.
*Point out: no bidder names anywhere.*

## 5. Live bidding, the main part (5 min)
1. Browser 1: log in as demo applicant 1 → open **C-305** (or B-214) → **Join** → "Bidder N".
2. Browser 2: log in as demo applicant 2 → same auction → **Join**.
3. Bid in browser 1 → it appears **instantly** in browser 2, and vice versa.
4. Show the rules:
   - a bid below the minimum → rejected with the reason (only that bidder sees it);
   - trying to outbid yourself → rejected;
   - "You have been outbid" message in the other browser.
5. **Network drop:** stop the server (Ctrl+C in window 1). Pages show "Reconnecting…" and
   the bid button is disabled. Restart `python manage.py runserver` → pages reconnect by
   themselves and show the latest bids.
6. **Anti-sniping:** Admin → Auctions → open the auction → set **End time** to ~1 minute
   from now → Save (pages update instantly). Bid in the final minute → deadline extends,
   and the page says so.
7. Admin → **Bids**: show the audit trail with codes only. Then (superuser) **Participations**:
   the confidential code ↔ applicant mapping.

## 6. Automatic closure and winner email (2 min)
1. Let the short auction run out (or set its end time to now).
2. Within ~5 seconds: both pages show the result. The winner sees **"Congratulations, you
   won!"**; the other sees "Won by Bidder N".
3. Lobby → **Recently closed** shows it. Admin → Quarters: the quarter is **Allotted**.
4. Open the newest `sent_emails\` file: the winner email with quarter details and amount.

## 7. Proof of correctness (1 min)
```powershell
python manage.py test auctions.tests.test_concurrency -v 2
```
*Explain: 10 threads bid at the same instant on PostgreSQL; exactly one wins. These
tests fail if the row lock is removed (this was checked during development).*

Full suite: `python manage.py test`

---

## Likely questions

| Question | Answer |
|---|---|
| What if two people bid the same amount at the same time? | The auction row is locked; the first is accepted, the second sees the new minimum and is rejected. `test_concurrency.py` proves it. |
| Can someone see who is bidding? | No. Only "Bidder N" codes leave the server. The mapping is visible to superusers only. |
| What if the server crashes during an auction? | Bids are in PostgreSQL. Pages reconnect and resync automatically. The worker closes the auction when it is due. |
| Can a quarter be awarded twice? | No: closure locks and re-checks, and the database has a constraint allowing only one "won" auction per quarter. |
| Why no online payment? | Out of scope by design: EMD is paid via SBI Collect and verified offline. |
| Are these SAIL's real rules? | No. All rules are documented placeholders awaiting confirmation (see PROGRESS.md). |
