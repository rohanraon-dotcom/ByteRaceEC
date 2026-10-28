# Subscription Sniper — Enhanced MVP

A Streamlit prototype that analyzes a CSV bank statement to find recurring subscription-like charges, estimate monthly/annual spend, predict renewals, flag potential price hikes, suggest reviews, and export an `.ics` calendar.

## Features
- Upload a CSV statement or load the included demo CSV.
- Select date, merchant/description, and amount columns.
- Date parsing modes for ISO/auto, day-first, and month-first dates.
- Supports positive-expense or negative-expense bank statement conventions.
- Merchant normalization for common services (Netflix, Spotify, Google One, Hotstar, etc.).
- Recurrence inference for weekly, fortnightly, monthly, quarterly, and yearly patterns.
- Similar-amount check to reduce false positives.
- Monthly/annual cost estimates and a confidence indicator.
- Upcoming renewal view, price-hike alerts, savings review suggestions, and `.ics` calendar export.
- Exclude detected merchants that are not subscriptions.

## Requirements
- Python 3.10–3.13 is recommended for broad package compatibility.
- Internet access is needed the first time to install packages.
- A code editor such as VS Code.

## Run on Windows (VS Code or PowerShell)
1. Extract the ZIP to a normal folder.
2. Open that folder in VS Code (`File` → `Open Folder`).
3. Open **Terminal** → **New Terminal**.
4. Check Python:
   ```powershell
   py --version
   ```
   If `py` is not found, install Python from https://www.python.org/downloads/ and enable **Add Python to PATH** during setup.
5. Create a virtual environment:
   ```powershell
   py -m venv .venv
   ```
6. Activate it:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   If PowerShell blocks activation, use Command Prompt terminal and run:
   ```bat
   .venv\Scripts\activate.bat
   ```
7. Upgrade pip and install dependencies:
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
8. Start the app:
   ```powershell
   streamlit run app.py
   ```
9. Streamlit prints a local URL, usually `http://localhost:8501`. Open it in your browser.
10. Click **Load demo statement** or upload your own CSV.

## Run on macOS/Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

## CSV format
The app tries to guess column names. At minimum, your CSV needs:
- a date column
- a merchant/description column
- an amount column

Example:
```csv
date,merchant,amount
2026-08-05,Netflix,249
2026-09-05,Netflix,249
2026-10-05,Netflix,249
```

Use the sidebar to choose whether expenses are positive or negative in your bank export. Refunds/credits should use the opposite sign and will be excluded from spending calculations.

## Important limitations
- This is a hackathon prototype, not a financial product or bank-integrated service.
- A recurring pattern is a heuristic, not proof that a merchant is a subscription.
- Irregular billing, changing billing dates, annual plans, partial refunds, split payments, and merchant name variations can cause missed or incorrect detections.
- Price-hike alerts compare the latest charge with the median of previous charges; taxes, plan changes, foreign exchange, and one-off fees can trigger false alerts.
- Renewal dates are estimates. Verify dates and amounts before relying on them.
- Do not upload real financial statements to an untrusted or public host.

## Hackathon integrity
Follow the event's rules about when code may be created, copied, or committed. If pre-written code is prohibited, use this project only as a learning reference until the permitted coding window begins, and implement/debug it within the event rules.
