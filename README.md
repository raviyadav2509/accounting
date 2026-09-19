# QuickBooks BAS Automation

A Flask application that reads QuickBooks Online data, calculates BAS figures deterministically, uses AI to review underlying transactions, and requires human approval before a BAS can move to a ready-to-lodge state.

## Application structure

- `app.py` - creates the Flask application and initializes the database
- `config.py` - environment and application configuration
- `routes/qbo_routes.py` - QuickBooks OAuth and diagnostic endpoints
- `routes/bas_routes.py` - dashboard, BAS review, AI review, approval and history routes
- `services/qbo_service.py` - QuickBooks API and token refresh
- `services/bas_service.py` - deterministic BAS calculation
- `services/ai_review_service.py` - AI transaction review
- `services/database.py` - SQLite BAS snapshots and audit history
- `services/review_store.py` - review/resolution/approval persistence facade
- `templates/` - dashboard and review pages
- `static/styles.css` - shared UI styling

## Data flow

```text
QuickBooks
   |
   v
Deterministic BAS calculation
   |
   v
Saved BAS snapshot
   |
   v
AI transaction review
   |
   v
Human review / resolution
   |
   v
Human approval
   |
   v
Ready to Lodge
```

AI does not replace the BAS calculation. It reviews the underlying transactions and flags issues for human attention.

## SQLite BAS history

The application creates:

```text
bas_history.db
```

automatically when it starts.

Each BAS snapshot stores:

- reporting period
- G1, 1A, 1B, W1 and W2
- GST position and estimated BAS payable
- BAS data signature
- AI review status and review text
- human resolution notes
- approval/rejection status
- review, resolution and approval timestamps

The database is intentionally excluded from Git because it contains business records.

The earlier JSON review file is still read as a one-time compatibility fallback when its period and BAS signature match.

## Run locally

Copy your existing `.env` and `tokens.json` into the project folder, then:

```cmd
py -m pip install -r requirements.txt
py app.py
```

Open:

```text
http://127.0.0.1:8000/
```

The home page is now the BAS Dashboard.

## Main pages

```text
/                       BAS Dashboard
/bas-review             Current BAS review
/ai-review              Run AI transaction review
/bas-history             BAS history
/connect                 Connect QuickBooks
```

## Sandbox payroll configuration

These defaults are currently configured for the sandbox:

```text
QBO_WAGE_ACCOUNT_ID=66
QBO_PAYG_ACCOUNT_ID=49
```

Configure the correct production account IDs before connecting real company data.

## Current limitation

Approval currently records a BAS as ready to lodge. It does not submit anything to the ATO. A supported ATO/SBR lodgement mechanism must be implemented and verified separately before automated lodgement is enabled.
