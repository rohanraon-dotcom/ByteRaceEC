# Subscription Sniper 
Track recurring charges, estimate subscription spend, detect price hikes, and plan renewals—all offline from your bank statement.

Subscription Sniper is a lightweight, privacy-focused Streamlit web application that analyzes CSV bank statements to automatically identify recurring subscription payments, calculate monthly/annual overhead, predict renewal dates, detect stealth price hikes, and export renewal reminders to your calendar.

# Features

Local & Privacy-First: All data is processed entirely within your running app session. No bank credentials or statements are uploaded to third-party cloud servers or external AI models.

Smart CSV Parsing: Automatically detects date, merchant, and amount columns with support for multi-currency symbols (₹, $) and custom date formats (DD/MM/YYYY, MM/DD/YYYY, ISO).

Recurring Pattern Detection: Detects weekly, fortnightly, monthly, quarterly, and yearly subscriptions using interval inference and amount-tolerance checks.

Price Hike & Anomaly Alerts: Flags latest charges that exceed historical median baselines by a user-configured threshold.

Health Scoring: Rule-based transparency rating (0–100) per subscription to highlight services with price increases, anomalies, or category overlaps.

Rule-Based Assistant: Ask natural-language questions about your spend, potential savings, and upcoming renewals without relying on an external LLM.

Calendar Export: Export predicted renewals within a 90-day window as an .ics file for Google Calendar, Apple Calendar, or Microsoft Outlook.

# Installation & Setup
Prerequisites:
Python 3.10 to 3.13 installed.
Git (optional).

# Install Dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Launch the Streamlit App
streamlit run app.py

Open http://localhost:8501 in your browser. Click "Load demo statement" to explore using sample data!

# CSV File Requirements
To scan your own statement, export a .csv file from your online banking app. Your CSV should include at least three columns:
Date Column: Date, Transaction Date, Value Date, etc.
Merchant/Description Column: Merchant, Description, Narration, Payee, etc.
Amount Column: Amount, Debit, Spent, Value, etc.

# Example CSV Format:
date,description,amount
2026-08-05,NETFLIX.COM,249
2026-08-15,Disney+ Hotstar,149
