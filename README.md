# QuickBooks BAS Automation - Refactored

## Structure

- `app.py` - starts Flask and registers routes
- `config.py` - environment/configuration only
- `routes/qbo_routes.py` - QuickBooks/OAuth/debug endpoints
- `routes/bas_routes.py` - BAS review, AI review and approval endpoints
- `services/qbo_service.py` - QuickBooks API/token handling
- `services/bas_service.py` - deterministic BAS calculations
- `services/ai_review_service.py` - OpenAI review only
- `services/review_store.py` - review/approval persistence
- `templates/` - HTML pages
- `static/styles.css` - shared UI styling

## Run

Copy your existing `.env` and `tokens.json` into this folder, then:

```cmd
py -m pip install -r requirements.txt
py app.py
```

Open:

`http://127.0.0.1:8000/bas-review?start=2026-09-03&end=2026-09-30`

## Important

`QBO_WAGE_ACCOUNT_ID=66` and `QBO_PAYG_ACCOUNT_ID=49` are sandbox defaults. Configure the correct production account IDs before using real company data.
