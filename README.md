# BiasharaSmart AI

A responsive Flask starter app for small businesses to record products, sales and expenses and view simple operating-profit estimates.

## Version 1 features

- Business account registration and sign-in with hashed passwords.
- Separate user-owned inventory, sales and expense records.
- Inventory list with cost and selling prices and low-stock indicators.
- Sale recording that checks stock and reduces quantity automatically.
- Expense categories and a dashboard for revenue, cost of goods sold, gross profit, expenses and estimated net operating profit.
- CSRF protection on forms and HTTP-only session cookies.
- Responsive layout for desktop and mobile.

## Run locally on Windows

Install Python 3.12+ if needed, then open PowerShell and run:

```powershell
git clone https://github.com/johnnychess43/biashara-smart-ai.git
cd biashara-smart-ai
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
python app.py
```

Open http://127.0.0.1:5000 in your browser. If PowerShell blocks activation, run `.venv\Scripts\python.exe -m pip install -r requirements.txt` and `.venv\Scripts\python.exe app.py` instead.

The local SQLite database is created under `instance/biashara.db`. Keep the `instance/` folder private and do not commit it.

## Important before public deployment

This is an MVP, not yet a production accounting or tax system. Before inviting real customers, configure a strong secret key in the hosting environment, use a managed PostgreSQL database with backups, enable HTTPS/secure cookies, add login rate limiting and password-reset flow, and test database migrations and recovery. Never commit passwords, API keys, or customer data.

The dashboard totals the transactions entered so far; it does not yet implement date filters, refunds, supplier purchases, tax, payment reconciliation, or M-PESA API integration. AI insights and subscriptions are planned for later iterations.
