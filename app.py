from datetime import date
import io

import pandas as pd
import plotly.express as px
import streamlit as st

from engine import (
    guess_column, normalize_transactions, apply_expense_sign, detect_subscriptions,
    upcoming_renewals, detect_price_hikes, make_savings_suggestions, export_calendar,
    score_subscription_health, detect_charge_anomalies, answer_spending_question
)

st.set_page_config(page_title="Subscription Sniper", page_icon="🎯", layout="wide")
st.title("🎯 Subscription Sniper")
st.caption("Find recurring charges, estimate subscription spend, catch price hikes, and plan renewals.")

with st.sidebar:
    st.header("1. Upload statement")
    uploaded = st.file_uploader("CSV bank statement", type=["csv"])
    st.caption("Demo data is included in sample_data/sample_statement.csv.")
    st.divider()
    st.header("Detection settings")
    expense_sign = st.radio(
        "How are expenses represented?",
        ["Positive amounts are expenses", "Negative amounts are expenses"],
        index=0,
        help="Choose the convention used by your bank export. Credits/refunds are excluded from spend."
    )
    amount_tolerance = st.slider("Allowed charge variation", 0.05, 0.60, 0.30, 0.05,
                                 help="A transaction amount is considered similar if within this percentage of the merchant's median.")
    price_threshold = st.slider("Price hike alert threshold", 5, 50, 10, 5) / 100
    anomaly_threshold = st.slider("Unusual charge threshold (%)", 10, 100, 25, 5) / 100
    renewal_window = st.slider("Upcoming renewal window (days)", 7, 90, 7, 1)

if uploaded is None:
    st.info("Upload a CSV statement or load the included sample data to try the app.")
    if st.button("Load demo statement", type="primary"):
        st.session_state["load_demo"] = True
    if not st.session_state.get("load_demo", False):
        st.stop()
    try:
        raw = pd.read_csv("sample_data/sample_statement.csv")
    except Exception as exc:
        st.error(f"Could not load demo CSV: {exc}")
        st.stop()
else:
    try:
        raw = pd.read_csv(uploaded)
    except Exception as exc:
        st.error(f"Could not read CSV: {exc}")
        st.stop()

if raw.empty:
    st.error("This CSV has no rows.")
    st.stop()

st.subheader("2. Match your CSV columns")
columns = list(raw.columns)
suggested_date = guess_column(columns, ["date", "transaction date", "txn date", "posted date", "value date"])
suggested_merchant = guess_column(columns, ["merchant", "description", "narration", "transaction", "details", "payee", "name"])
suggested_amount = guess_column(columns, ["amount", "debit", "withdrawal", "transaction amount", "value", "spent"])

c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
with c1:
    date_col = st.selectbox("Date column", columns, index=columns.index(suggested_date) if suggested_date in columns else 0)
with c2:
    merchant_col = st.selectbox("Merchant / description", columns, index=columns.index(suggested_merchant) if suggested_merchant in columns else min(1, len(columns)-1))
with c3:
    amount_col = st.selectbox("Amount column", columns, index=columns.index(suggested_amount) if suggested_amount in columns else min(2, len(columns)-1))
with c4:
    date_format = st.selectbox("Date format", ["auto", "day-first (DD/MM/YYYY)", "month-first (MM/DD/YYYY)"])

try:
    transactions = normalize_transactions(raw, date_col, merchant_col, amount_col, date_format)
    transactions = apply_expense_sign(transactions, expense_sign)
except Exception as exc:
    st.error(f"Could not normalize this statement: {exc}")
    st.stop()

if transactions.empty:
    st.error("No valid rows were found. Check your date, merchant, and amount column selections.")
    st.stop()

st.caption(f"Imported {len(transactions)} valid transactions. Rows with invalid dates/amounts or empty merchants were skipped.")
with st.expander("Preview cleaned transactions"):
    st.dataframe(transactions[["date", "raw_merchant", "amount", "merchant", "category", "is_expense"]], use_container_width=True)

subscriptions = detect_subscriptions(transactions, amount_tolerance=amount_tolerance)
if not subscriptions.empty:
    # User corrections are stored for this browser session and excluded from results.
    if "ignored_merchants" not in st.session_state:
        st.session_state["ignored_merchants"] = []
    ignored = st.multiselect(
        "Exclude false positives",
        options=subscriptions["merchant"].tolist(),
        default=[m for m in st.session_state["ignored_merchants"] if m in subscriptions["merchant"].tolist()],
        help="Choose merchants that are not subscriptions."
    )
    st.session_state["ignored_merchants"] = ignored
    subscriptions = subscriptions[~subscriptions["merchant"].isin(ignored)].reset_index(drop=True)

st.divider()
st.subheader("3. Your subscription overview")
monthly_total = float(subscriptions["monthly_equivalent"].sum()) if not subscriptions.empty else 0.0
annual_total = float(subscriptions["annual_estimate"].sum()) if not subscriptions.empty else 0.0
upcoming = upcoming_renewals(subscriptions, days=renewal_window)
hikes = detect_price_hikes(transactions, subscriptions, threshold=price_threshold)
anomalies = detect_charge_anomalies(
    transactions, subscriptions, threshold=anomaly_threshold
)
health_scores = score_subscription_health(subscriptions, hikes, anomalies)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Detected subscriptions", len(subscriptions))
m2.metric("Estimated monthly spend", f"₹{monthly_total:,.0f}")
m3.metric("Estimated annual spend", f"₹{annual_total:,.0f}")
m4.metric(f"Renewals in next {renewal_window} days", len(upcoming))

left, right = st.columns([1.2, 1])
with left:
    st.markdown("#### Detected subscriptions")
    if subscriptions.empty:
        st.warning("No recurring charges detected yet. Try a statement with at least 2–3 charges per merchant and check the expense sign.")
    else:
        display = subscriptions[[
            "merchant", "category", "frequency", "typical_amount", "monthly_equivalent",
            "annual_estimate", "occurrences", "next_renewal", "confidence"
        ]].copy()
        display["next_renewal"] = pd.to_datetime(display["next_renewal"]).dt.strftime("%d %b %Y")
        display = display.rename(columns={
            "merchant": "Service", "category": "Category", "frequency": "Frequency",
            "typical_amount": "Typical charge (₹)", "monthly_equivalent": "Monthly est. (₹)",
            "annual_estimate": "Annual est. (₹)", "occurrences": "Charges found",
            "next_renewal": "Next predicted date", "confidence": "Confidence (%)"
        })
        st.dataframe(display, use_container_width=True, hide_index=True)
with right:
    st.markdown("#### Monthly cost by service")
    if not subscriptions.empty:
        chart = px.bar(subscriptions, x="merchant", y="monthly_equivalent", color="category",
                       labels={"merchant": "Service", "monthly_equivalent": "Monthly equivalent (₹)", "category": "Category"})
        chart.update_layout(xaxis_tickangle=-25, legend_title_text="Category", margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(chart, use_container_width=True)
    else:
        st.write("The chart appears after subscriptions are detected.")

st.divider()
r1, r2 = st.columns(2)
with r1:
    st.markdown("#### 📅 Upcoming renewals")
    if upcoming.empty:
        st.info("No predicted renewals in the selected window. Prediction depends on the dates in your statement.")
    else:
        renewal_view = upcoming[["merchant", "next_renewal", "typical_amount", "frequency"]].copy()
        renewal_view["next_renewal"] = pd.to_datetime(renewal_view["next_renewal"]).dt.strftime("%d %b %Y")
        renewal_view = renewal_view.rename(columns={"merchant": "Service", "next_renewal": "Predicted date", "typical_amount": "Est. charge (₹)", "frequency": "Frequency"})
        st.dataframe(renewal_view, use_container_width=True, hide_index=True)

with r2:
    st.markdown("#### 🚨 Price-hike alerts")
    if hikes.empty:
        st.success("No price hikes detected at the selected threshold.")
    else:
        hike_view = hikes.rename(columns={"merchant": "Service", "previous_amount": "Previous typical charge (₹)", "latest_amount": "Latest charge (₹)", "increase_pct": "Increase (%)", "latest_date": "Latest transaction"})
        st.dataframe(hike_view, use_container_width=True, hide_index=True)

st.divider()
st.subheader("4. Subscription health score")
st.caption("Scores are transparent rule-based indicators, not financial advice. Higher scores mean fewer review signals.")
if health_scores.empty:
    st.info("Health scores will appear when subscriptions are detected.")
else:
    score_view = health_scores.rename(columns={
        "merchant": "Service",
        "health_score": "Health score / 100",
        "health_label": "Status",
        "health_reasons": "Why this score?",
    })
    st.dataframe(score_view, use_container_width=True, hide_index=True)
    lowest = health_scores.iloc[0]
    st.info(
        f"Start your review with **{lowest['merchant']}** "
        f"(score {int(lowest['health_score'])}/100): {lowest['health_reasons']}."
    )

st.subheader("5. Unusual charge detection")
st.caption(
    f"A charge is flagged when it differs by at least {anomaly_threshold:.0%} "
    "from the median of earlier charges for that detected subscription. "
    "This is a heuristic; plan changes and taxes can create false alarms."
)
if anomalies.empty:
    st.success("No unusual subscription charge amounts detected at the current threshold.")
else:
    anomaly_view = anomalies.rename(columns={
        "merchant": "Service",
        "date": "Transaction date",
        "expected_amount": "Earlier-charge median (₹)",
        "actual_amount": "Actual charge (₹)",
        "deviation_pct": "Deviation (%)",
        "direction": "Signal",
        "reason": "Explanation",
    })
    anomaly_view["Transaction date"] = pd.to_datetime(
        anomaly_view["Transaction date"]
    ).dt.strftime("%d %b %Y")
    st.dataframe(anomaly_view, use_container_width=True, hide_index=True)

st.divider()
st.subheader("6. Smart spending assistant")
st.caption("Rule-based prototype: answers common questions from the current CSV, without sending your statement to an external AI service.")
question = st.text_input(
    "Ask about your subscriptions",
    placeholder="e.g. How can I save money? / What renewals are upcoming? / Show unusual charges"
)
if st.button("Ask Subscription Sniper", type="primary"):
    answer = answer_spending_question(
        question, subscriptions, hikes, anomalies, upcoming, health_scores
    )
    st.markdown(answer)

st.divider()
st.subheader("7. Savings ideas")
suggestions = make_savings_suggestions(subscriptions)
if suggestions.empty:
    st.write("No suggestions yet.")
else:
    for _, row in suggestions.iterrows():
        st.markdown(f"**{row['suggestion']}** — {row['reason']}")
    st.caption("Potential savings are estimates, not guaranteed. Review service terms and usage before cancelling.")

st.divider()
st.subheader("8. Export renewal calendar")
st.write("Download predicted renewals within the next 90 days as an `.ics` file for Google Calendar, Apple Calendar, or Outlook.")
ics = export_calendar(subscriptions, days=90)
st.download_button(
    "⬇️ Download renewal calendar (.ics)",
    data=ics,
    file_name="subscription_renewals.ics",
    mime="text/calendar",
    disabled=subscriptions.empty,
)

st.caption("Privacy note: this demo processes the uploaded CSV in the running app session. Do not upload statements containing information you do not want to share with the app host. Predictions can be wrong; verify charges against your bank statement.")
