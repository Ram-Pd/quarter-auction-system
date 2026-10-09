# Architecture

> Training project, not an official SAIL system. Business rules marked "placeholder"
> are assumptions listed in `PROGRESS.md`.

The diagrams use [Mermaid](https://mermaid.js.org/). GitHub and VS Code (with the
"Markdown Preview Mermaid Support" extension) draw them automatically. To export a
picture for a report, paste a diagram into https://mermaid.live.

---

## 1. System architecture

```mermaid
flowchart LR
    subgraph Browser
        P[Pages: register, activate,<br/>login, lobby, auction]
        JS[auction_room.js<br/>live updates + reconnect]
    end

    subgraph Server["Daphne (ASGI server)"]
        HTTP[Django views<br/>accounts/ + auctions/]
        WS[AuctionConsumer<br/>auctions/consumers.py]
        BID[Bidding rules<br/>auctions/bidding.py]
        CLOSE[Closure<br/>auctions/closing.py]
        RT[Message builder<br/>auctions/realtime.py]
    end

    W[run_auction_worker<br/>every 5 s]
    DB[(PostgreSQL)]
    CL[[Channel layer<br/>in-memory / Redis]]
    MAIL[[Email<br/>.eml files / SMTP]]
    ADMIN[Admin staff<br/>Django admin]

    P -- HTTP --> HTTP
    JS -- WebSocket --> WS
    ADMIN -- HTTP --> HTTP
    HTTP --> DB
    WS --> BID --> DB
    WS -- deadline sync --> CLOSE
    W --> CLOSE --> DB
    BID -- after commit --> RT
    CLOSE -- after commit --> RT
    RT --> CL --> WS
    HTTP -- PDFs --> MAIL
    CLOSE -- winner email --> MAIL
```

| Part | Role |
|---|---|
| **Daphne** | One server process for both normal pages (HTTP) and live connections (WebSocket). `runserver` uses it automatically. |
| **Django views** | Registration, activation, login, lobby, auction page, admin. |
| **AuctionConsumer** | One per open auction tab. Checks the user may watch that auction, receives bids, pushes updates. |
| **bidding.py** | *All* bid rules, run inside a transaction holding a row lock on the auction. |
| **closing.py** | Closes finished auctions exactly once and picks the winner. |
| **realtime.py** | Builds every message sent to browsers: anonymous codes, amounts and times only. |
| **Channel layer** | Delivers a message to every tab in an auction's group (`auction_<id>`). In-memory for one process; Redis for several. |
| **Worker** | `manage.py run_auction_worker`: closes due auctions and retries failed emails. |
| **PostgreSQL** | All data. Row locks (`select_for_update`) make simultaneous bids safe. |

---

## 2. Data model (ER diagram)

```mermaid
erDiagram
    USER ||--o| APPLICANT : "login for (created at activation)"
    APPLICANT ||--o{ PARTICIPATION : "joins auctions as"
    QUARTER ||--o{ AUCTION : "is auctioned in"
    AUCTION ||--o{ PARTICIPATION : "has bidders"
    AUCTION ||--o{ BID : "receives"
    PARTICIPATION ||--o{ BID : "places"
    AUCTION |o--o| BID : "winning_bid"

    USER {
        string username "= URN"
        string password "hashed"
        string email
    }
    APPLICANT {
        string name
        string father_name
        string mobile
        string email "unique, case-insensitive"
        string address
        string state
        string pin_code
        string application_no "unique, QA2026000001"
        string urn "unique, 7 digits, random"
        date urn_date
        bool is_verified "admin: EMD checked"
        bool is_activated
        datetime documents_emailed_at
    }
    QUARTER {
        string quarter_no "unique, upper case"
        string sector
        string location_block
        string quarter_type "A/B/C/D"
        string floor
        decimal area_sqft "> 0"
        decimal base_rate "> 0"
        string status "Vacant / In Auction / Allotted"
    }
    AUCTION {
        datetime start_time
        datetime end_time "current deadline"
        datetime original_end_time "before extensions"
        string status "OPEN / CLOSED / CLOSED_NO_BIDS / CANCELLED"
        decimal min_increment "> 0"
        duration anti_snipe_extension
        decimal current_highest_bid
        datetime closed_at
        datetime winner_notified_at "email sent once"
    }
    PARTICIPATION {
        int bidder_number "shown as Bidder N"
        datetime joined_at
    }
    BID {
        decimal amount "> 0"
        datetime created_at
        uuid client_bid_id "duplicate guard"
        decimal previous_highest "audit"
        datetime deadline_extended_to "audit"
    }
```

**Key database rules** (enforced by PostgreSQL itself, not only by Python):

| Rule | Constraint |
|---|---|
| Quarter numbers unique, ignoring case | `quarter_no_unique_ci` |
| Area, base rate, increment, bid amount > 0 | check constraints |
| Auction ends after it starts | `auction_end_after_start` |
| Only one OPEN auction per quarter | `one_open_auction_per_quarter` (partial unique) |
| **A quarter can be won only once** | `quarter_won_only_once` (partial unique) |
| "Closed - won" ⇔ has a winning bid | `winning_bid_matches_status` |
| One code per applicant per auction; codes unique per auction | `participation` unique constraints |
| The same browser submission can't create two bids | `no_duplicate_bid_submission` |
| Two bids in one auction never have the same amount | `unique_bid_amount_per_auction` |
| Activated applicant must have a login | `applicant_activated_has_user` |

**Privacy:** `PARTICIPATION` is the only link between a person and a "Bidder N" code.
Public pages, bid history, WebSocket messages and ordinary admin screens show codes only.
The Participation admin screen is visible to superusers only.

---

## 3. Workflow (end to end)

```mermaid
flowchart TD
    A[Admin imports quarters from Excel] --> B[Admin creates auctions<br/>start, end, increment, extension]
    R[Applicant registers] --> E[System generates URN + application no.<br/>emails Application Form + Intimation Slip]
    E --> F[Applicant pays EMD via SBI Collect<br/>offline, outside the system]
    F --> G[Admin verifies payment<br/>ticks 'verified']
    G --> H[Applicant activates: email + URN + password]
    H --> I[Applicant logs in with URN, opens lobby]
    B --> I
    I --> J[Joins an auction, gets 'Bidder N']
    J --> K[Live bidding over WebSocket]
    K --> L{Deadline passed?}
    L -- "bid in final minute" --> M[Deadline extended] --> K
    L -- yes --> N[Closure: lock, re-check, pick highest bid]
    N --> O{Any valid bid?}
    O -- yes --> P[CLOSED, quarter Allotted<br/>winner email once]
    O -- no --> Q[CLOSED_NO_BIDS, quarter stays Vacant]
```

---

## 4. One bid, step by step

```mermaid
sequenceDiagram
    participant A as Bidder A (browser)
    participant C as AuctionConsumer
    participant S as place_bid()
    participant D as PostgreSQL
    participant G as Channel layer
    participant B as Other bidders

    A->>C: {"type":"bid","amount":"4600","client_bid_id":"..."}
    C->>S: place_bid(auction, applicant, amount, id)
    S->>D: BEGIN; SELECT ... FOR UPDATE (auction row)
    Note over S,D: other bids for this auction wait here
    S->>S: live? joined? duplicate? >= minimum? not self-outbid? anti-snipe?
    S->>D: INSERT bid; UPDATE auction; COMMIT
    S-->>G: (after commit) bid_accepted: Bidder 1, 4600, new deadline
    G-->>A: bid_accepted
    G-->>B: bid_accepted
    C-->>A: bid_result ok
```

If any check fails, `place_bid` raises `BidRejected`, the transaction rolls back, and
only the sender receives `bid_result` with the reason.

---

## 5. Why each design choice

| Choice | Reason |
|---|---|
| Row lock on the **auction** row | Every bid for one auction is processed one at a time, while different auctions don't block each other. Proven by `test_concurrency.py`, which fails if the lock is removed. |
| Broadcast **after commit** | Nobody ever sees a bid that was later rolled back. |
| Phase computed from the clock | No job needs to flip "Upcoming" to "Live"; the page is always right. |
| Closure is idempotent | Several workers, or a worker plus a browser sync, can't award a quarter twice. Also enforced by the `quarter_won_only_once` constraint. |
| `client_bid_id` from the browser | A double-click or a resend after reconnect can't create two bids. |
| Snapshot on every (re)connect | A tab that lost its connection or slept shows the true current state. |
| All browser messages in `realtime.py` | One file to audit for privacy. |
| Management-command worker (not Celery) | No extra services. Easy to run and to explain. |
