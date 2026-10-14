# Vacant Quarter Auction System (training project)

A Django web application for auctioning vacant residential quarters, following the
mentor's final workflow (Change Request #3):

public home page with rules and FAQ → sign-up with an email code (OTP) → login →
**Register for bidding** (any number of quarters, Aadhaar/PAN stored encrypted) →
Application Form + Intimation Slip emailed (URN, EMD per quarter) → EMD paid offline
through SBI Collect → **Verification Officer** checks documents and each EMD receipt →
live anonymous bidding over WebSockets, one slot per quarter → automatic closure with
a 2-quarter allotment cap → winner email.

> **Training project.** Built during training at SAIL Bokaro Steel Plant. It is **not**
> an official SAIL system. All business rules, amounts and sample data are placeholders.

- Progress, decisions and assumptions: [`PROGRESS.md`](PROGRESS.md)
- Where to change what: [`docs/HOW_TO_CHANGE.md`](docs/HOW_TO_CHANGE.md)
- Architecture, ER and workflow diagrams: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Step-by-step demo for the mentor: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
- Production checklist: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- The brief and the change request: [`CLAUDE.md`](CLAUDE.md), [`docs/CHANGE_REQUEST_3.md`](docs/CHANGE_REQUEST_3.md)

## Setup (Windows, PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env               # then fill in SECRET_KEY, DATABASE_URL and the two keys below
python manage.py generate_secret_keys   # prints FIELD_ENCRYPTION_KEYS and IDENTITY_HASH_KEY for .env
python manage.py migrate             # also creates the staff groups and the document checklist
python manage.py createsuperuser     # asks for email, name and password
```

**Back up `FIELD_ENCRYPTION_KEYS`.** It decrypts the stored Aadhaar/PAN numbers; if it is
lost they can never be read again.

### PostgreSQL (required for bidding)

Simultaneous bids and closures are made safe by row locking (`select_for_update`), which
only works on PostgreSQL. On this machine PostgreSQL 17 is a **portable install** (no admin
rights, no Windows service):

| | |
|---|---|
| Programs | `%USERPROFILE%\pgsql` |
| Data | `%USERPROFILE%\pgsql-data` (log: `server.log`) |
| Superuser password | `%USERPROFILE%\pgsql-superuser-password.txt` |
| App database / user | `sail_auction` / `sail_user` (password in `.env`) |

It does **not** start automatically. After each reboot:
```powershell
.\scripts\start_postgres.ps1     # stop with .\scripts\stop_postgres.ps1
```

## Run

Two terminals, no venv activation needed:
```powershell
.\scripts\run_server.ps1     # terminal 1: starts PostgreSQL + the website (HTTP and WebSockets)
.\scripts\run_worker.ps1     # terminal 2: background worker (closes finished auctions, sends winner emails)
```
- Site: http://127.0.0.1:8000/ (public home page)
- Admin: http://127.0.0.1:8000/admin/

> **`ModuleNotFoundError: No module named 'environ'`** means the computer-wide Python ran
> instead of the project's venv. Use the scripts above, or run `.\venv\Scripts\Activate.ps1`.

**Emails in development:** with no SMTP password in `.env`, every email is saved as a `.eml`
file in `sent_emails\` (double-click to open it, PDFs included) **and printed in the server
terminal**, so a sign-up code can be read straight from the console. With
`EMAIL_HOST_PASSWORD` set (`.\scripts\setup_email.ps1`) emails are really sent.

## Demo data (FAKE)

```powershell
python manage.py seed_demo
```
Imports the 8 sample quarters (bidding a week from today), adds 3 demo quarters whose
auctions are live now / start in 10 minutes, and creates demo accounts (password
`Demo-Pass-2026`):

| Account | Role |
|---|---|
| `officer@example.com` | Verification Officer (staff) |
| `auctionadmin@example.com` | Auction Admin (staff) |
| `demo1..3@example.com` | ACTIVE bidders, EMD verified for the live demo quarters |
| `demo4@example.com` | applied, documents pending (use it to show the verification screen) |
| `demo5@example.com` | account only (use it to show "Register for bidding") |

`seed_demo` only runs with `DEBUG=True`, and its emails always go to `sent_emails\`, never SMTP.
To demo live bidding, log in as two demo bidders in two different browsers (or one normal
and one private window) and open the same live auction.

## Tests

```powershell
python manage.py test        # 208 tests, about 1 minute, needs PostgreSQL running
```

## Project layout

```
config/        settings, top-level URLs, ASGI (HTTP + WebSockets), email helpers
accounts/      login accounts: custom User (email login), sign-up OTP, password reset
applications/  Register for bidding, Aadhaar/PAN, URN, PDFs, verification, roles, audit log, eligibility
auctions/      quarters, Excel import, auctions, quarter listing, bidding, WebSockets, closure
templates/     base layout, home page, content/ (rules + FAQ text), shared includes, email footer
static/        site-wide CSS
sample_data/   FAKE Excel files + generator script (see sample_data/README.md)
scripts/       start/stop PostgreSQL, run server/worker, email setup
docs/          project documentation
```

File-by-file map and "how do I change X" recipes: `docs/HOW_TO_CHANGE.md`.
