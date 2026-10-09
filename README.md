# Vacant Quarter Auction System (training project)

A Django web application for auctioning vacant residential quarters: Excel import of
quarters, applicant registration with emailed PDFs, URN-based account activation,
an auction lobby, and (in progress) real-time anonymous bidding.

> **Training project.** Built during training at SAIL Bokaro Steel Plant. It is **not**
> an official SAIL system. All business rules, amounts and sample data are placeholders.

- Progress, decisions and assumptions: [`PROGRESS.md`](PROGRESS.md)
- Where to change what: [`docs/HOW_TO_CHANGE.md`](docs/HOW_TO_CHANGE.md)
- Original brief: [`CLAUDE.md`](CLAUDE.md)

## Setup (Windows, PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # then put a real SECRET_KEY and DATABASE_URL in .env
python manage.py migrate
python manage.py createsuperuser
```

### PostgreSQL (required for bidding)

Simultaneous bids are made safe by row locking (`select_for_update`), which only works
on PostgreSQL. On this machine PostgreSQL 17 is a **portable install** (no admin rights,
no Windows service):

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

Generate a secret key:
```powershell
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

## Run

```powershell
.\scripts\start_postgres.ps1
python manage.py runserver
```
`runserver` uses Daphne (ASGI), so WebSockets work too.
- Site: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin/

To demo live bidding, log in as two demo applicants in two different browsers (or one
normal and one private window), open the same live auction, join, and bid.

Emails are not really sent in development. Each one is saved as a `.eml` file in
`sent_emails\`; double-click to open it with its attachments.

## Demo data (FAKE)

```powershell
python manage.py seed_demo
```
Imports the 8 sample quarters, creates 2 live and 2 upcoming auctions, 3 demo
applicants who can log in, and 1 who is ready to activate. It prints their URNs
and the demo password. It only runs with `DEBUG=True`.

## Tests

```powershell
python manage.py test
```

## Project layout

```
config/      settings, top-level URLs, ASGI (HTTP + WebSockets), email backend
accounts/    applicants: registration, URN, PDFs, email, activation, login
auctions/    quarters, Excel import, auctions, lobby, bidding, WebSockets
scripts/     start/stop the portable PostgreSQL server
templates/   site-wide templates (base layout, home page, shared includes)
static/      site-wide CSS
sample_data/ FAKE Excel files + generator script
docs/        project documentation
```
