# Deployment checklist (production)

> The approved deployment environment is an **open question** (CLAUDE.md #11). This is a
> generic checklist; confirm the real environment with the mentor / IT department first.

## 1. Services needed

| Service | Why |
|---|---|
| PostgreSQL 14+ | Data; row locking for correct simultaneous bids. **Not SQLite.** |
| Redis | Shared channel layer (WebSockets across processes) and shared rate-limit cache. |
| Daphne (or another ASGI server) | Serves HTTP and WebSockets. |
| Reverse proxy with HTTPS (nginx / IIS) | TLS certificates, static files, forwards `/ws/` as WebSocket. |
| The worker | `python manage.py run_auction_worker` as a service, so auctions close on time. |
| SMTP account | Registration, password reset and winner emails. |

## 2. `.env` for production

```ini
DEBUG=False
SECRET_KEY=<new random 50+ character key, never the development one>
ALLOWED_HOSTS=auction.example.org
CSRF_TRUSTED_ORIGINS=https://auction.example.org
DATABASE_URL=postgres://sail_user:<strong password>@db-host:5432/sail_auction
REDIS_URL=redis://redis-host:6379/0
BEHIND_HTTPS_PROXY=True

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.org
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=auction@example.org

AUCTION_TITLE=...
AUCTION_REFERENCE=...
EMD_AMOUNT=...
```

With `DEBUG=False` the settings automatically turn on: https redirect, secure cookies,
HSTS (30 days), and secure proxy headers when `BEHIND_HTTPS_PROXY=True`.
Optional, only if every subdomain is https: `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`.

## 3. Steps

```powershell
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic          # copies CSS/JS to staticfiles/ for the proxy to serve
python manage.py createsuperuser
python manage.py check --deploy         # expect only the 2 optional HSTS warnings
python manage.py test                   # against a test database on the real PostgreSQL
```

Run as services (examples):
```powershell
daphne -b 127.0.0.1 -p 8000 config.asgi:application
python manage.py run_auction_worker
```
Several Daphne processes are fine **only with REDIS_URL set**.

## 4. Proxy notes
- Forward `/ws/` with WebSocket upgrade headers (`Upgrade`, `Connection`).
- Set `X-Forwarded-Proto: https`.
- Serve `/static/` from the `staticfiles/` folder.

## 5. Operations
- **Backups:** daily `pg_dump`; the `Bid` and `Participation` tables are the audit trail.
- **Never delete** auctions, bids or participations (the admin already prevents it).
- **Logs:** the `auctions` and `accounts` loggers report failed emails and worker errors.
- **Admin accounts:** give ordinary staff only the permissions they need. The
  Participation screen (identity ↔ code) is superusers only.
- `seed_demo` refuses to run when `DEBUG=False`.
