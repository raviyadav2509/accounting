# BAS Automation

A Flask application for accounting firms to manage multiple client BAS workflows from QuickBooks Online.

## Current product model

```text
Accounting firm user
        |
        +-- Client A
        |     |
        |     +-- QuickBooks connection
        |     +-- BAS calculations
        |     +-- AI reviews
        |     +-- approvals / audit history
        |
        +-- Client B
        |     |
        |     +-- separate QuickBooks connection
        |     +-- separate BAS records
        |
        +-- Client C
              |
              +-- separate QuickBooks connection
              +-- separate BAS records
```

A signed-in user can register multiple clients. Each client has an independent QuickBooks OAuth connection and client-scoped BAS records.

## Main workflow

1. Sign up or sign in.
2. Open **Clients**.
3. Add a client.
4. Connect that client's QuickBooks company.
5. Open the client dashboard.
6. Calculate BAS periods.
7. Run the AI transaction review.
8. Resolve review items where required.
9. Approve the BAS.
10. Lodgement integration will be added separately once a supported ATO/SBR mechanism is implemented.

## Main routes

```text
/login                  Sign in
/signup                 Create user account
/clients/               Accounting firm client list
/clients/new            Add a client
/                       Selected client's BAS dashboard
/bas-history            Selected client's BAS history
/connect                Connect selected client to QuickBooks
```

## Data isolation

The SQLite database contains:

- `users` — accounting firm user accounts
- `clients` — businesses registered under a user
- `qbo_connections` — one QuickBooks connection per client
- `bas_records` — BAS records scoped by `client_id`

All BAS history, AI review state, approval state and QuickBooks API calls are scoped to the selected client.

Existing BAS records from the earlier single-client schema are migrated with a nullable client ID. When the first client is created, any legacy unassigned BAS records are attached to that first client.

## QuickBooks

OAuth tokens are now stored per client rather than in one global `tokens.json` connection.

For production, OAuth token material should be encrypted at rest rather than stored as plain JSON in SQLite.

## BAS calculation

The BAS calculator remains deterministic. AI does not replace BAS figures; it reviews underlying transactions for potential issues.

Current simplified BAS calculation includes:

- G1 total sales
- 1A GST on sales
- 1B GST on purchases
- W1 gross wages
- W2 PAYG withheld
- estimated GST/PAYG amount

The current payroll account IDs are still sandbox defaults configured through:

```text
QBO_WAGE_ACCOUNT_ID
QBO_PAYG_ACCOUNT_ID
```

These must become client-specific mappings before multi-client production use.

## Run locally

```cmd
py -m pip install -r requirements.txt
py app.py
```

Open:

```text
http://127.0.0.1:8000/
```

Unauthenticated users are redirected to the login page.

## Mock ATO lodgement for local testing

Real ATO/SBR lodgement is not connected. The feature branch includes a disabled-by-default mock lodgement mode for testing the workflow after approval.

Enable it locally in `.env`:

```text
ENABLE_MOCK_ATO_LODGEMENT=true
```

Before lodgement, approved BAS and annual tax returns can be reopened for editing. Reopening removes the approval but does not alter a lodged record. If figures are changed, the normal review and approval workflow must be completed again.

With the switch enabled:

- an approved BAS shows **Edit BAS** and **Simulate ATO Lodgement**
- the mock action records a `MOCK-BAS-...` reference, marks the BAS as lodged, removes it from **Active BAS**, and places it under **BAS History**
- an approved annual tax return shows **Edit Return** and **Simulate ATO Lodgement**
- the mock action records a `MOCK-TAX-...` reference, marks the return as lodged, and moves it from **Active Tax Returns** to **Tax Return History**

No request is sent to the ATO. Leave the switch unset or set it to `false` outside local/test environments.

## Production work still required

Before production use:

- encrypt QuickBooks OAuth tokens at rest
- add CSRF protection
- set a strong `FLASK_SECRET_KEY`
- set secure cookies under HTTPS
- add password reset and email verification
- make payroll/tax account mappings client-specific
- support proper BAS obligation/period discovery instead of sandbox defaults
- implement and verify supported ATO/SBR lodgement
- store immutable lodgement receipts and references
- add firm/team roles if multiple staff users will share the same accounting practice
