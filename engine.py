from __future__ import annotations

from datetime import date, datetime, timedelta
from io import StringIO
import calendar
import re
from typing import Optional

import pandas as pd

MERCHANT_RULES = [
    # Specific rules must come before broader rules.
    (r"\bjio\s*hotstar\b|\bjiohotstar\b", "JioHotstar", "OTT"),
    (r"disney|hotstar", "Disney+ Hotstar", "OTT"),
    (r"netflix", "Netflix", "OTT"),
    (r"amazon\s*prime|prime\s*video", "Amazon Prime Video", "OTT"),
    (r"\bprime\b", "Amazon Prime", "Shopping"),
    (r"spotify", "Spotify", "Music"),
    (r"youtube\s*premium|yt premium", "YouTube Premium", "Video-Music"),
    (r"apple\s*music", "Apple Music", "Music"),
    (r"google\s*one|google storage", "Google One", "Cloud Storage"),
    (r"icloud", "iCloud", "Cloud Storage"),
    (r"microsoft\s*365|office\s*365", "Microsoft 365", "Software"),
    (r"adobe", "Adobe", "Software"),
    (r"canva", "Canva", "Software"),
    (r"dropbox", "Dropbox", "Cloud Storage"),
    (r"hotstar", "Disney+ Hotstar", "OTT"),
]

DATE_COLUMNS = ["date", "transaction date", "txn date", "posted date", "value date"]
MERCHANT_COLUMNS = ["merchant", "description", "narration", "transaction", "details", "payee", "name"]
AMOUNT_COLUMNS = ["amount", "debit", "withdrawal", "transaction amount", "value", "spent"]


def _clean_col(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def guess_column(columns, candidates) -> Optional[str]:
    normalized = {_clean_col(c): c for c in columns}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    for norm, original in normalized.items():
        if any(candidate in norm for candidate in candidates):
            return original
    return None


def normalize_merchant(raw: object) -> tuple[str, str]:
    text = str(raw or "").strip()
    low = text.lower()
    for pattern, canonical, category in MERCHANT_RULES:
        if re.search(pattern, low, flags=re.I):
            return canonical, category
    cleaned = re.sub(r"\s+", " ", text).strip(" -*_")
    return (cleaned.title() if cleaned else "Unknown merchant"), "Other"


def _parse_amount(series: pd.Series) -> pd.Series:
    # Supports values such as ₹249, "1,299.00", and "(249.00)".
    cleaned = series.astype(str).str.replace(",", "", regex=False)
    cleaned = cleaned.str.replace("₹", "", regex=False).str.replace("$", "", regex=False)
    cleaned = cleaned.str.replace("INR", "", case=False, regex=False).str.strip()
    cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_transactions(
    df: pd.DataFrame,
    date_col: str,
    merchant_col: str,
    amount_col: str,
    date_format: str = "auto",
) -> pd.DataFrame:
    if df.empty:
        raise ValueError("The uploaded file contains no rows.")
    for col in (date_col, merchant_col, amount_col):
        if col not in df.columns:
            raise ValueError(f"Column not found: {col}")

    result = df[[date_col, merchant_col, amount_col]].copy()
    result.columns = ["date", "raw_merchant", "raw_amount"]

    if date_format == "day-first (DD/MM/YYYY)":
        result["date"] = pd.to_datetime(result["date"], errors="coerce", dayfirst=True)
    elif date_format == "month-first (MM/DD/YYYY)":
        result["date"] = pd.to_datetime(result["date"], errors="coerce", dayfirst=False)
    else:
        # ISO dates (YYYY-MM-DD) parse correctly without dayfirst ambiguity.
        raw_dates = result["date"].astype(str).str.strip()
        iso_mask = raw_dates.str.match(r"^\d{4}-\d{1,2}-\d{1,2}")
        parsed = pd.Series(pd.NaT, index=result.index, dtype="datetime64[ns]")
        parsed.loc[iso_mask] = pd.to_datetime(raw_dates.loc[iso_mask], errors="coerce", yearfirst=True)
        parsed.loc[~iso_mask] = pd.to_datetime(raw_dates.loc[~iso_mask], errors="coerce", dayfirst=True)
        result["date"] = parsed

    result["amount"] = _parse_amount(result["raw_amount"])
    result["raw_merchant"] = result["raw_merchant"].fillna("").astype(str).str.strip()
    result = result.dropna(subset=["date", "amount"])
    result = result[result["raw_merchant"].ne("")]
    # Bank exports often store expenses as negative debits. Keep sign so credits/refunds can be excluded.
    result["is_expense"] = result["amount"] > 0
    # Convention: negative amounts are expenses in some bank statements. User can select the sign convention in UI.
    result["merchant"], result["category"] = zip(*result["raw_merchant"].map(normalize_merchant))
    result["date"] = pd.to_datetime(result["date"]).dt.normalize()
    result = result.sort_values("date").reset_index(drop=True)
    return result


def apply_expense_sign(df: pd.DataFrame, expense_sign: str) -> pd.DataFrame:
    result = df.copy()
    if expense_sign == "Negative amounts are expenses":
        result["is_expense"] = result["amount"] < 0
        result["spend"] = result["amount"].abs().where(result["is_expense"], 0.0)
    else:
        result["is_expense"] = result["amount"] > 0
        result["spend"] = result["amount"].abs().where(result["is_expense"], 0.0)
    return result


def _infer_frequency(dates: list[pd.Timestamp]) -> tuple[str, int, float]:
    unique = sorted(pd.Timestamp(d).normalize() for d in set(dates))
    if len(unique) < 2:
        return "Insufficient history", 0, 0.0
    gaps = [(unique[i] - unique[i - 1]).days for i in range(1, len(unique))]
    median_gap = float(pd.Series(gaps).median())
    if 5 <= median_gap <= 9:
        freq, expected = "Weekly", 7
    elif 12 <= median_gap <= 17:
        freq, expected = "Fortnightly", 14
    elif 25 <= median_gap <= 35:
        freq, expected = "Monthly", 30
    elif 80 <= median_gap <= 100:
        freq, expected = "Quarterly", 90
    elif 350 <= median_gap <= 380:
        freq, expected = "Yearly", 365
    else:
        return "Irregular", int(round(median_gap)), median_gap
    return freq, expected, median_gap


def _next_date(last_date: pd.Timestamp, frequency: str, expected_gap: int) -> pd.Timestamp:
    last_date = pd.Timestamp(last_date).normalize()
    if frequency == "Monthly":
        month = last_date.month + 1
        year = last_date.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(last_date.day, calendar.monthrange(year, month)[1])
        return pd.Timestamp(year, month, day)
    if frequency == "Quarterly":
        month = last_date.month + 3
        year = last_date.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(last_date.day, calendar.monthrange(year, month)[1])
        return pd.Timestamp(year, month, day)
    if frequency == "Yearly":
        year = last_date.year + 1
        day = min(last_date.day, calendar.monthrange(year, last_date.month)[1])
        return pd.Timestamp(year, last_date.month, day)
    return last_date + pd.Timedelta(days=max(expected_gap, 1))


def detect_subscriptions(
    transactions: pd.DataFrame,
    amount_tolerance: float = 0.30,
    min_occurrences: int = 2,
) -> pd.DataFrame:
    if transactions.empty:
        return pd.DataFrame()
    expenses = transactions[transactions["is_expense"]].copy()
    if expenses.empty:
        return pd.DataFrame()

    rows = []
    for merchant, group in expenses.groupby("merchant"):
        group = group.sort_values("date")
        if len(group) < min_occurrences:
            continue
        freq, expected_gap, median_gap = _infer_frequency(group["date"].tolist())
        if freq not in {"Weekly", "Fortnightly", "Monthly", "Quarterly", "Yearly"}:
            continue

        # Require at least two recurring intervals for 3+ transactions, or one interval for 2 transactions.
        gaps = group["date"].sort_values().diff().dropna().dt.days
        if len(gaps) >= 2:
            within_frequency = ((gaps >= expected_gap * 0.70) & (gaps <= expected_gap * 1.30)).mean()
            if within_frequency < 0.5:
                continue

        amounts = group["spend"].abs()
        median_amount = float(amounts.median())
        if median_amount <= 0:
            continue
        similar_amount_share = float((amounts.sub(median_amount).abs() <= median_amount * amount_tolerance).mean())
        # A few variable charges are tolerated, but a mostly unrelated merchant pattern is rejected.
        if similar_amount_share < 0.5:
            continue

        last_date = pd.Timestamp(group["date"].max())
        next_date = _next_date(last_date, freq, expected_gap)
        monthly_cost = median_amount if freq == "Monthly" else (
            median_amount * 52 / 12 if freq == "Weekly" else
            median_amount * 26 / 12 if freq == "Fortnightly" else
            median_amount / 3 if freq == "Quarterly" else
            median_amount / 12 if freq == "Yearly" else 0
        )
        confidence = min(98, int(50 + min(len(group), 5) * 8 + similar_amount_share * 15))
        rows.append({
            "merchant": merchant,
            "category": group["category"].mode().iat[0],
            "frequency": freq,
            "typical_amount": round(median_amount, 2),
            "monthly_equivalent": round(monthly_cost, 2),
            "annual_estimate": round(monthly_cost * 12, 2),
            "occurrences": int(len(group)),
            "first_seen": pd.Timestamp(group["date"].min()),
            "last_seen": last_date,
            "next_renewal": next_date,
            "confidence": confidence,
            "amount_similarity": round(similar_amount_share * 100),
        })
    if not rows:
        return pd.DataFrame(columns=[
            "merchant", "category", "frequency", "typical_amount", "monthly_equivalent",
            "annual_estimate", "occurrences", "first_seen", "last_seen", "next_renewal",
            "confidence", "amount_similarity"
        ])
    return pd.DataFrame(rows).sort_values("monthly_equivalent", ascending=False).reset_index(drop=True)


def upcoming_renewals(subscriptions: pd.DataFrame, today: Optional[date] = None, days: int = 30) -> pd.DataFrame:
    if subscriptions.empty:
        return subscriptions.copy()
    today_ts = pd.Timestamp(today or date.today()).normalize()
    end = today_ts + pd.Timedelta(days=days)
    result = subscriptions.copy()
    result["next_renewal"] = pd.to_datetime(result["next_renewal"]).dt.normalize()
    # If old sample data yields a past predicted date, roll forward until in/after today.
    for idx, row in result.iterrows():
        next_date = row["next_renewal"]
        for _ in range(24):
            if next_date >= today_ts:
                break
            next_date = _next_date(next_date, row["frequency"], 30 if row["frequency"] == "Monthly" else
                                   90 if row["frequency"] == "Quarterly" else
                                   365 if row["frequency"] == "Yearly" else
                                   14 if row["frequency"] == "Fortnightly" else
                                   7 if row["frequency"] == "Weekly" else 30)
        result.at[idx, "next_renewal"] = next_date
    return result[(result["next_renewal"] >= today_ts) & (result["next_renewal"] <= end)].sort_values("next_renewal")


def detect_price_hikes(transactions: pd.DataFrame, subscriptions: pd.DataFrame, threshold: float = 0.10) -> pd.DataFrame:
    if transactions.empty or subscriptions.empty:
        return pd.DataFrame(columns=["merchant", "previous_amount", "latest_amount", "increase_pct", "latest_date"])
    expenses = transactions[transactions["is_expense"]].copy()
    alerts = []
    for _, sub in subscriptions.iterrows():
        group = expenses[expenses["merchant"] == sub["merchant"]].sort_values("date")
        if len(group) < 2:
            continue
        amounts = group["spend"].abs().tolist()
        # Compare latest charge to the median of prior charges to reduce noise.
        previous = float(pd.Series(amounts[:-1]).median())
        latest = float(amounts[-1])
        if previous > 0 and latest >= previous * (1 + threshold):
            alerts.append({
                "merchant": sub["merchant"],
                "previous_amount": round(previous, 2),
                "latest_amount": round(latest, 2),
                "increase_pct": round((latest - previous) / previous * 100, 1),
                "latest_date": group.iloc[-1]["date"],
            })
    return pd.DataFrame(alerts)


def make_savings_suggestions(subscriptions: pd.DataFrame) -> pd.DataFrame:
    if subscriptions.empty:
        return pd.DataFrame(columns=["suggestion", "reason", "potential_annual_saving"])
    rows = []
    category_counts = subscriptions.groupby("category")["merchant"].count().to_dict()
    for _, sub in subscriptions.iterrows():
        rows.append({
            "suggestion": f"Review whether you still need {sub['merchant']}",
            "reason": f"Estimated annual cost is ₹{sub['annual_estimate']:,.0f}. Cancelling could save up to this amount if you no longer use it.",
            "potential_annual_saving": round(float(sub["annual_estimate"]), 2),
        })
        if category_counts.get(sub["category"], 0) > 1:
            rows.append({
                "suggestion": f"Check overlapping {sub['category']} services",
                "reason": f"You have {category_counts[sub['category']]} detected subscriptions in this category; compare features before cancelling anything.",
                "potential_annual_saving": 0.0,
            })
    return pd.DataFrame(rows).drop_duplicates(subset=["suggestion"]).reset_index(drop=True)



def score_subscription_health(
    subscriptions: pd.DataFrame,
    hikes: pd.DataFrame | None = None,
    anomalies: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return transparent per-subscription health scores from 0 (review urgently) to 100 (healthy)."""
    if subscriptions.empty:
        return pd.DataFrame(columns=[
            "merchant", "health_score", "health_label", "health_reasons"
        ])

    hikes = hikes if hikes is not None else pd.DataFrame()
    anomalies = anomalies if anomalies is not None else pd.DataFrame()
    category_counts = subscriptions.groupby("category")["merchant"].nunique().to_dict()
    rows = []

    for _, sub in subscriptions.iterrows():
        score = 100
        reasons = []
        merchant = sub["merchant"]

        confidence = float(sub.get("confidence", 0))
        if confidence < 65:
            score -= 15
            reasons.append("Low detection confidence; verify the recurring pattern")

        if not hikes.empty and "merchant" in hikes.columns and merchant in set(hikes["merchant"]):
            score -= 25
            reasons.append("A price increase was detected")

        if not anomalies.empty and "merchant" in anomalies.columns and merchant in set(anomalies["merchant"]):
            score -= 20
            reasons.append("An unusual charge amount was detected")

        category = sub.get("category", "Other")
        if category_counts.get(category, 0) > 1:
            score -= 10
            reasons.append(f"You have multiple subscriptions in {category}; check for overlap")

        score = max(0, min(100, score))
        if score >= 80:
            label = "Healthy"
        elif score >= 60:
            label = "Review"
        else:
            label = "Needs attention"

        if not reasons:
            reasons.append("No price hike, unusual charge, or overlap signal was found")
        rows.append({
            "merchant": merchant,
            "health_score": score,
            "health_label": label,
            "health_reasons": "; ".join(reasons),
        })

    return pd.DataFrame(rows).sort_values(
        ["health_score", "merchant"], ascending=[True, True]
    ).reset_index(drop=True)


def detect_charge_anomalies(
    transactions: pd.DataFrame,
    subscriptions: pd.DataFrame,
    threshold: float = 0.25,
    min_history: int = 2,
) -> pd.DataFrame:
    """Flag subscription charges that differ from the median of earlier charges."""
    columns = [
        "merchant", "date", "expected_amount", "actual_amount",
        "deviation_pct", "direction", "reason"
    ]
    if transactions.empty or subscriptions.empty:
        return pd.DataFrame(columns=columns)

    expenses = transactions[transactions["is_expense"]].copy()
    subscription_names = set(subscriptions["merchant"])
    alerts = []

    for merchant, group in expenses[expenses["merchant"].isin(subscription_names)].groupby("merchant"):
        group = group.sort_values("date")
        amounts = group["spend"].abs().astype(float).tolist()
        dates = group["date"].tolist()

        # Compare each charge only with earlier charges; don't let the current charge
        # influence its own baseline. This needs at least min_history prior charges.
        for i in range(min_history, len(amounts)):
            history = amounts[:i]
            baseline = float(pd.Series(history).median())
            actual = amounts[i]
            if baseline <= 0:
                continue
            deviation = (actual - baseline) / baseline * 100
            if abs(deviation) >= threshold * 100:
                direction = "Higher than usual" if deviation > 0 else "Lower than usual"
                alerts.append({
                    "merchant": merchant,
                    "date": pd.Timestamp(dates[i]),
                    "expected_amount": round(baseline, 2),
                    "actual_amount": round(actual, 2),
                    "deviation_pct": round(deviation, 1),
                    "direction": direction,
                    "reason": (
                        f"Charge is {abs(deviation):.1f}% "
                        f"{'above' if deviation > 0 else 'below'} the median of earlier charges"
                    ),
                })

    if not alerts:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(alerts, columns=columns).sort_values(
        "date", ascending=False
    ).reset_index(drop=True)


def answer_spending_question(
    question: str,
    subscriptions: pd.DataFrame,
    hikes: pd.DataFrame | None = None,
    anomalies: pd.DataFrame | None = None,
    upcoming: pd.DataFrame | None = None,
    health_scores: pd.DataFrame | None = None,
) -> str:
    """A lightweight, transparent rule-based assistant for hackathon demos."""
    q = (question or "").strip().lower()
    hikes = hikes if hikes is not None else pd.DataFrame()
    anomalies = anomalies if anomalies is not None else pd.DataFrame()
    upcoming = upcoming if upcoming is not None else pd.DataFrame()
    health_scores = health_scores if health_scores is not None else pd.DataFrame()

    if not q:
        return "Ask me about spending, savings, renewals, price hikes, unusual charges, or subscription health."

    if subscriptions.empty:
        return "I couldn't detect subscriptions yet. Upload a statement with repeated charges and check the selected expense-sign convention."

    monthly_total = float(subscriptions["monthly_equivalent"].sum())
    annual_total = float(subscriptions["annual_estimate"].sum())

    if any(word in q for word in ["save", "cancel", "cut cost", "reduce", "cheaper"]):
        ranked = subscriptions.sort_values("annual_estimate", ascending=False).head(3)
        items = [
            f"{row['merchant']} (up to ₹{float(row['annual_estimate']):,.0f}/year)"
            for _, row in ranked.iterrows()
        ]
        return (
            f"Your estimated spend is ₹{monthly_total:,.0f}/month (₹{annual_total:,.0f}/year). "
            f"Start by reviewing the highest annual costs: {', '.join(items)}. "
            "These are potential savings only—cancel only if you no longer need the service."
        )

    if any(word in q for word in ["renew", "due", "upcoming"]):
        if upcoming.empty:
            return "No renewals are currently inside your selected reminder window."
        items = [
            f"{row['merchant']} on {pd.Timestamp(row['next_renewal']).strftime('%d %b %Y')} "
            f"(about ₹{float(row['typical_amount']):,.0f})"
            for _, row in upcoming.sort_values("next_renewal").head(5).iterrows()
        ]
        return "Upcoming predicted renewals: " + "; ".join(items) + "."

    if any(word in q for word in ["hike", "increase", "price"]):
        if hikes.empty:
            return "No price hikes crossed your selected alert threshold."
        items = [
            f"{row['merchant']}: ₹{float(row['previous_amount']):,.0f} → "
            f"₹{float(row['latest_amount']):,.0f} (+{float(row['increase_pct']):.1f}%)"
            for _, row in hikes.iterrows()
        ]
        return "Detected price increases: " + "; ".join(items) + ". Check whether the plan or taxes changed."

    if any(word in q for word in ["anomal", "unusual", "strange", "unexpected", "charge"]):
        if anomalies.empty:
            return "No unusual subscription charge amounts were detected using the current threshold."
        row = anomalies.iloc[0]
        return (
            f"Latest flagged charge: {row['merchant']} on "
            f"{pd.Timestamp(row['date']).strftime('%d %b %Y')} was ₹{float(row['actual_amount']):,.0f}; "
            f"the earlier-charge median was ₹{float(row['expected_amount']):,.0f} "
            f"({float(row['deviation_pct']):+.1f}%). Verify it with your statement."
        )

    if any(word in q for word in ["score", "health", "risk", "review"]):
        if health_scores.empty:
            return "Health scores aren't available yet."
        row = health_scores.sort_values("health_score").iloc[0]
        return (
            f"{row['merchant']} has the lowest health score at {int(row['health_score'])}/100 "
            f"({row['health_label']}). Reason: {row['health_reasons']}."
        )

    if any(word in q for word in ["total", "spend", "cost", "budget", "much"]):
        return (
            f"You have {len(subscriptions)} detected subscriptions, costing an estimated "
            f"₹{monthly_total:,.0f}/month and ₹{annual_total:,.0f}/year. "
            "These estimates use the detected billing frequency and typical charge."
        )

    return (
        f"You have {len(subscriptions)} detected subscriptions with an estimated total of "
        f"₹{monthly_total:,.0f}/month. Try asking: 'How can I save money?', "
        "'What renewals are upcoming?', 'Show unusual charges', or 'Which subscription needs review?'"
    )



def export_calendar(subscriptions: pd.DataFrame, today: Optional[date] = None, days: int = 90) -> str:
    upcoming = upcoming_renewals(subscriptions, today=today, days=days)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Subscription Sniper//EN", "CALSCALE:GREGORIAN"]
    for _, sub in upcoming.iterrows():
        dt = pd.Timestamp(sub["next_renewal"]).strftime("%Y%m%d")
        summary = str(sub["merchant"]).replace(",", r"\,").replace(";", r"\;")
        description = f"Estimated renewal ₹{float(sub['typical_amount']):.2f} ({sub['frequency']})"
        description = description.replace(",", r"\,").replace(";", r"\;")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{re.sub(r'[^a-zA-Z0-9]', '', summary)}-{dt}@subscription-sniper",
            f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;VALUE=DATE:{dt}",
            f"SUMMARY:{summary} renewal",
            f"DESCRIPTION:{description}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
