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

## Automated tests and CI

Install the development dependencies and run the test suite locally:

```cmd
py -m pip install -r requirements-dev.txt
py -m pytest
```

Once registered in Azure DevOps, `azure-pipelines.yml` runs the same tests for
`main`, `feature/*` and GitHub pull requests targeting those branches containing
this YAML. It publishes JUnit results, code coverage and a tested application
ZIP containing only allowlisted application files (no databases or credentials).
Tests use a fresh temporary SQLite database per test, disable `.env` loading,
block network connections, and stub external integrations. No real QuickBooks,
OpenAI, SMTP or ATO credentials are required. Coverage measures the starting
baseline; there is not yet a minimum overall coverage gate.

### Register the Azure DevOps pipeline

1. Connect the GitHub repository to your Azure DevOps project.
2. Create a pipeline using the existing `/azure-pipelines.yml` on
   `feature/annual-tax-return`; keep `main` unchanged until review/merge.
3. Run it on the feature branch and confirm test results, coverage and the
   `accounting` ZIP artifact are published.
4. Configure the resulting build status as a required GitHub check separately
   if merges should be blocked on failures; YAML alone does not protect branches.

CD is deliberately not active yet. Before adding a deployment stage, identify
the Azure service connection, App Service target and Azure DevOps environment,
then configure environment approval checks outside YAML. Configure runtime
secrets securely and persistent storage for SQLite; never deploy a test database.
The existing production-readiness gaps below still apply. No Azure resources,
deployment, or ATO lodgement are created by this CI pipeline.

The coverage publisher includes the .NET prerequisite documented by
[Microsoft](https://learn.microsoft.com/en-us/azure/devops/pipelines/tasks/reference/publish-code-coverage-results-v2?view=azure-pipelines).

## Email verification

New firm accounts must verify their login email before accessing clients, QuickBooks, BAS or annual tax returns.

Configure SMTP in `.env`:

```text
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your-smtp-username
SMTP_PASSWORD=your-smtp-password
SMTP_USE_TLS=true
SMTP_USE_SSL=false
EMAIL_FROM=no-reply@example.com
EMAIL_VERIFICATION_EXPIRY_MINUTES=30
```

Signup now creates an unverified account, sends a time-limited verification link, and keeps the user outside the authenticated workspace until the link is used. Users can resend the verification email or correct the address before verification.

Verification tokens are stored only as SHA-256 hashes in the database. Existing users are grandfathered as verified during the schema migration so current accounts are not locked out.

For local development without SMTP, enable:

```text
EMAIL_VERIFICATION_DEBUG_LINKS=true
```

The verification page will then expose a clearly labelled local-only verification link. Do not enable debug verification links in production.

## Password reset

The sign-in page includes **Forgot password?**. Password reset uses the same SMTP configuration as email verification.

The workflow is:

1. Enter the login email.
2. If an active account exists, a time-limited reset link is issued.
3. The token is stored only as a SHA-256 hash.
4. The user chooses a new password.
5. The token is invalidated immediately after use.
6. The user signs in with the new password.

The response to the forgot-password form is deliberately generic so it does not reveal whether an email address is registered.

Configure the reset lifetime with:

```text
PASSWORD_RESET_EXPIRY_MINUTES=30
```

For local testing without working SMTP, enable:

```text
PASSWORD_RESET_DEBUG_LINKS=true
```

This exposes a clearly labelled local password-reset link after a request for an existing active account. Never enable it in production.

## Mock ATO lodgement for local testing

Real ATO/SBR lodgement is not connected. The feature branch includes a disabled-by-default mock lodgement mode for testing the workflow after approval.

Enable it locally in `.env`:

```text
ENABLE_MOCK_ATO_LODGEMENT=true
```

Before lodgement, approved BAS and annual tax returns can be reopened for editing. Reopening removes the approval but does not alter a lodged record. If figures are changed, the normal review and approval workflow must be completed again.

With the switch enabled:

- an approved BAS shows **Edit BAS** and **Simulate ATO Lodgement**
- the mock action records a `MOCK-BAS-...` reference, marks the BAS as lodged, removes it from **BAS in Progress**, and places it under **BAS History**
- an approved annual tax return shows **Edit Return** and **Simulate ATO Lodgement**
- the mock action records a `MOCK-TAX-...` reference, marks the return as lodged, and moves it from **Active Tax Returns** to **Tax Return History**

No request is sent to the ATO. Leave the switch unset or set it to `false` outside local/test environments.

## Production work still required

Before production use:

- encrypt QuickBooks OAuth tokens at rest
- add CSRF protection
- set a strong `FLASK_SECRET_KEY`
- set secure cookies under HTTPS
- make payroll/tax account mappings client-specific
- support proper BAS obligation/period discovery instead of sandbox defaults
- implement and verify supported ATO/SBR lodgement
- store immutable lodgement receipts and references
- add firm/team roles if multiple staff users will share the same accounting practice
