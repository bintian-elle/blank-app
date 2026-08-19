from __future__ import annotations

import math
import re
import time

import pandas as pd
import streamlit as st

from dashboard.charts import line_chart
from dashboard.components import ab_test_card, activity_card, change, comparison_label, date_filters, detail_cards, fmt_money, fmt_num, insight_card, module_performance_table, percent_change_text, section, sms_campaign_cards, top_creative_table
from dashboard.config import API_KEY, EMAIL_SUBSCRIBER_SEGMENT_ID, REVISION, SMS_SUBSCRIBER_SEGMENT_ID
from dashboard.data import ab_test_frame, aggregate, creative_module_frame, load_campaign_creatives, load_channel_revenue, load_creative_clicks, load_dashboard, load_sms_previews, load_subscriber_inventory, report_frame, report_totals, shared_yoy_store
from dashboard.styles import apply_styles
from klaviyo_client import KlaviyoError


st.set_page_config(page_title="Email Marketing Performance Dashboard", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
apply_styles()

st.markdown('<div class="brand-kicker">BLUEVUA · KLAVIYO ANALYTICS</div>', unsafe_allow_html=True)
st.title("EMAIL MARKETING PERFORMANCE DASHBOARD")

start, end, previous_start, previous_end, mode = date_filters("dashboard")
current, previous, reports = load_dashboard(API_KEY, REVISION, start, end, previous_start, previous_end, mode != "No comparison")
period_label = st.session_state.get("dashboard_period", "Last 30 days")
comparison_note = {
    "Previous period": "vs Previous Period",
    "Previous year": "vs Previous Year",
    "Custom": "vs Custom Period",
}.get(mode, "Current period")


def agg(name: str, measurement: str = "count", prior: bool = False) -> float:
    return aggregate(previous if prior else current, name, measurement)


def change_text(current_value: float, previous_value: float, formatted_current: str | None = None) -> str:
    """Describe change without implying that an increase is inherently positive."""
    if mode == "No comparison":
        return ""
    if previous_value == 0:
        if current_value == 0:
            return "remained at 0"
        return f"changed from 0 to {formatted_current or fmt_num(current_value)}"
    delta = (current_value - previous_value) / abs(previous_value) * 100
    return f"changed by {delta:+.1f}%"


total_revenue = agg("Placed Order", "sum_value")
prev_total_revenue = agg("Placed Order", "sum_value", True)
email_received, text_sent = agg("Received Email"), agg("Sent Text Message")
prev_email, prev_text = agg("Received Email", prior=True), agg("Sent Text Message", prior=True)
campaign_total, flow_total = report_totals(reports["campaigns"]), report_totals(reports["flows"])
email_campaign = report_totals(reports["campaigns"], "email")
sms_campaign = report_totals(reports["campaigns"], "sms")
email_all = report_totals(reports["campaigns"] + reports["flows"], "email")
sms_all = report_totals(reports["campaigns"] + reports["flows"], "sms")
previous_campaign_total, previous_flow_total = report_totals(reports["previous_campaigns"]), report_totals(reports["previous_flows"])
previous_email_campaign = report_totals(reports["previous_campaigns"], "email")
previous_email_all = report_totals(reports["previous_campaigns"] + reports["previous_flows"], "email")
previous_sms_all = report_totals(reports["previous_campaigns"] + reports["previous_flows"], "sms")
edm_revenue = email_all["conversion_value"] + sms_all["conversion_value"]
previous_edm_revenue = previous_email_all["conversion_value"] + previous_sms_all["conversion_value"]
try:
    yoy_start, yoy_end = start.replace(year=start.year - 1), end.replace(year=end.year - 1)
except ValueError:
    yoy_start, yoy_end = start.replace(year=start.year - 1, day=28), end.replace(year=end.year - 1, day=28)
yoy_revenue = None
yoy_status = "--%"
yoy_window_key = (yoy_start.isoformat(), yoy_end.isoformat())
stored_yoy = st.session_state.get("dashboard_yoy_data")
if stored_yoy and stored_yoy.get("window") == yoy_window_key:
    yoy_revenue = stored_yoy.get("revenue")
shared_yoy = shared_yoy_store()
shared_entry = shared_yoy.get(yoy_window_key)
if shared_entry and time.time() - float(shared_entry.get("loaded_at", 0)) < 7200:
    yoy_revenue = shared_entry.get("revenue")
elif shared_entry:
    shared_yoy.pop(yoy_window_key, None)


def yoy_change(current_value: float, channel: str) -> tuple[str, str]:
    previous_year_value = yoy_revenue.get(channel) if yoy_revenue else None
    return percent_change_text(current_value, previous_year_value) if previous_year_value is not None else (yoy_status, "neutral")


def inverse_change_text(current_value: float, previous_value: float) -> tuple[str, str]:
    text, css = percent_change_text(current_value, previous_value)
    return text, {"positive": "negative", "negative": "positive"}.get(css, css)


def yoy_health_change(current_value: float, metric: str, lower_is_better: bool = True) -> tuple[str, str]:
    previous_year_value = yoy_revenue.get("email_health", {}).get(metric) if yoy_revenue else None
    if previous_year_value is None:
        return "--%", "neutral"
    return inverse_change_text(current_value, previous_year_value) if lower_is_better else percent_change_text(current_value, previous_year_value)


@st.fragment(run_every=1)
def yoy_button(has_data: bool) -> None:
    cooldown_until = float(st.session_state.get("dashboard_yoy_cooldown_until", 0))
    remaining = max(0, math.ceil(cooldown_until - time.time()))
    if remaining:
        label = f"Retry YoY ({remaining}s)"
    else:
        label = "Refresh YoY" if has_data else "Load YoY"
    if st.button(label, key="load_yoy", disabled=remaining > 0, help=f"Load Previous Year data ({yoy_start:%b %d, %Y} – {yoy_end:%b %d, %Y})", width="stretch"):
        st.session_state["dashboard_yoy_requested"] = True
        st.rerun()

# Executive summary
st.markdown('<div class="summary-card">', unsafe_allow_html=True)
summary, r1, r2, r3, r4 = st.columns([2.2, 1, 1, 1, 1])
with summary:
    st.markdown('<div class="summary-title">▣ &nbsp; EXECUTIVE SUMMARY</div>', unsafe_allow_html=True)
    change_candidates = {"Email": change(email_all["conversion_value"], previous_email_all["conversion_value"]), "SMS": change(sms_all["conversion_value"], previous_sms_all["conversion_value"]), "Flows": change(flow_total["conversion_value"], previous_flow_total["conversion_value"]), "Campaigns": change(campaign_total["conversion_value"], previous_campaign_total["conversion_value"])}
    valid_changes = {name: value for name, value in change_candidates.items() if value is not None}
    largest_change_area = max(valid_changes, key=lambda name: abs(valid_changes[name])) if valid_changes else "No comparison"
    edm_share = f"{edm_revenue/total_revenue:.1%}" if total_revenue else "—"
    comparison_sentences = ""
    if mode != "No comparison":
        comparison_sentences = (
            f' EDM revenue <b>{change_text(edm_revenue, previous_edm_revenue, fmt_money(edm_revenue))}</b>.'
            f' Email recipients <b>{change_text(email_received, prev_email, fmt_num(email_received))}</b>, while text recipients <b>{change_text(text_sent, prev_text, fmt_num(text_sent))}</b>.'
            f' By channel, Email revenue <b>{change_text(email_all["conversion_value"], previous_email_all["conversion_value"], fmt_money(email_all["conversion_value"]))}</b> and SMS revenue <b>{change_text(sms_all["conversion_value"], previous_sms_all["conversion_value"], fmt_money(sms_all["conversion_value"]))}</b>.'
            f' By message type, Flows revenue <b>{change_text(flow_total["conversion_value"], previous_flow_total["conversion_value"], fmt_money(flow_total["conversion_value"]))}</b> and Campaigns revenue <b>{change_text(campaign_total["conversion_value"], previous_campaign_total["conversion_value"], fmt_money(campaign_total["conversion_value"]))}</b>.'
        )
    st.markdown(f'<div class="summary-copy">From <b>{start:%b %d}</b> to <b>{end:%b %d, %Y}</b>, email and SMS marketing generated <b>{fmt_money(edm_revenue)}</b>, accounting for <b>{edm_share}</b> of total revenue. Email reached <b>{fmt_num(email_received)}</b> recipients and text reached <b>{fmt_num(text_sent)}</b> recipients.{comparison_sentences}</div>', unsafe_allow_html=True)
summary_items = [(r1, "TOTAL EDM REVENUE", fmt_money(edm_revenue), change(edm_revenue, previous_edm_revenue)), (r2, "EMAIL RECIPIENTS", fmt_num(email_received), change(email_received, prev_email)), (r3, "TEXT RECIPIENTS", fmt_num(text_sent), change(text_sent, prev_text)), (r4, "LARGEST CHANGE", largest_change_area, valid_changes.get(largest_change_area))]
for col, label, value, delta in summary_items:
    with col:
        st.markdown(f'<div class="mini-label">{label}</div><div class="mini-value">{value}</div>', unsafe_allow_html=True)
        st.markdown('<span class="delta-flat">Current period</span>' if delta is None else f'<span class="delta-flat">Change {delta:+.1f}%</span><span class="delta-note">vs comparison</span>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# 1 Business overall
section("1", "BUSINESS OVERALL")
_, yoy_action = st.columns([6, 1])
with yoy_action:
    yoy_button(yoy_revenue is not None)
request_yoy = st.session_state.pop("dashboard_yoy_requested", False)
if request_yoy:
    try:
        with st.spinner("Loading Previous Year data…"):
            activity_metric_ids = tuple(current["metric_ids"].get(name, "") for name in ("Subscribed to Email Marketing", "Subscribed to Text Messaging Marketing", "Unsubscribed from Email Marketing", "Unsubscribed from Text Messaging Marketing"))
            yoy_revenue = load_channel_revenue(API_KEY, REVISION, yoy_start, yoy_end, current["metric_ids"]["Placed Order"], current["metric_ids"].get("Received Email", ""), current["metric_ids"].get("Sent Text Message", ""), activity_metric_ids)
        st.session_state["dashboard_yoy_data"] = {"window": yoy_window_key, "revenue": yoy_revenue}
        shared_yoy[yoy_window_key] = {"loaded_at": time.time(), "revenue": yoy_revenue}
    except KlaviyoError as exc:
        yoy_status = "--%"
        error_text = str(exc)
        delay_match = re.search(r"(?:available in|retry after)\s+(\d+(?:\.\d+)?)\s*seconds?", error_text, re.I)
        if delay_match:
            retry_seconds = max(1, math.ceil(float(delay_match.group(1))))
            st.session_state["dashboard_yoy_cooldown_until"] = time.time() + retry_seconds
            st.warning(f"Klaviyo rate limit reached. YoY can be retried in {retry_seconds} seconds.")
        else:
            st.warning(f"Previous Year data could not be loaded: {exc}")
email_flow_revenue = report_totals(reports["flows"], "email")["conversion_value"]
previous_email_flow_revenue = report_totals(reports["previous_flows"], "email")["conversion_value"]
total_recipients = email_received + text_sent
previous_total_recipients = prev_email + prev_text
business_card_data = [
    ("Total EDM Revenue", fmt_money(edm_revenue), percent_change_text(edm_revenue, previous_edm_revenue), f"{edm_revenue/total_revenue:.1%} of total revenue" if total_revenue else "Share of total revenue —", yoy_change(edm_revenue, "edm")),
    ("SMS Revenue", fmt_money(sms_all["conversion_value"]), percent_change_text(sms_all["conversion_value"], previous_sms_all["conversion_value"]), f"{sms_all['conversion_value']/edm_revenue:.1%} of EDM revenue" if edm_revenue else "Share of EDM revenue —", yoy_change(sms_all["conversion_value"], "sms")),
    ("Total Recipients", fmt_num(total_recipients), percent_change_text(total_recipients, previous_total_recipients), "Email + text recipients", yoy_change(total_recipients, "recipients")),
    ("Email Revenue", fmt_money(email_all["conversion_value"]), percent_change_text(email_all["conversion_value"], previous_email_all["conversion_value"]), f"{email_all['conversion_value']/edm_revenue:.1%} of EDM revenue" if edm_revenue else "Share of EDM revenue —", yoy_change(email_all["conversion_value"], "email")),
    ("Flows Revenue", fmt_money(email_flow_revenue), percent_change_text(email_flow_revenue, previous_email_flow_revenue), f"{email_flow_revenue/email_all['conversion_value']:.1%} of Email revenue" if email_all["conversion_value"] else "Share of Email revenue —", yoy_change(email_flow_revenue, "email_flow")),
    ("Campaigns Revenue", fmt_money(email_campaign["conversion_value"]), percent_change_text(email_campaign["conversion_value"], previous_email_campaign["conversion_value"]), f"{email_campaign['conversion_value']/email_all['conversion_value']:.1%} of Email revenue" if email_all["conversion_value"] else "Share of Email revenue —", yoy_change(email_campaign["conversion_value"], "email_campaign")),
]
for row_start in (0, 3):
    business_cards = st.columns(3)
    for col, card in zip(business_cards, business_card_data[row_start:row_start + 3]):
        with col:
            insight_card(*card[:4], comparison=comparison_note, secondary_delta=card[4])

# 2 List health
section("2", "LIST HEALTH")
bounces, spam = agg("Bounced Email"), agg("Marked Email as Spam")
email_unsubs = float(reports.get("email_unsubscribe_uniques", email_all["unsubscribe_uniques"]))
health_metrics, health_chart = st.columns([1, 2.2])
with health_metrics:
    health_cards = st.columns(2)
    health_data = [("Unsubscribe Rate", f"{email_all['unsubscribe_rate']:.2%}", inverse_change_text(email_all["unsubscribe_rate"], previous_email_all["unsubscribe_rate"]), yoy_health_change(email_all["unsubscribe_rate"], "unsubscribe_rate")), ("Spam Complaint Rate", f"{email_all['spam_complaint_rate']:.3%}", inverse_change_text(email_all["spam_complaint_rate"], previous_email_all["spam_complaint_rate"]), yoy_health_change(email_all["spam_complaint_rate"], "spam_complaint_rate")), ("Bounce Rate", f"{email_all['bounce_rate']:.2%}", inverse_change_text(email_all["bounce_rate"], previous_email_all["bounce_rate"]), yoy_health_change(email_all["bounce_rate"], "bounce_rate")), ("Total Recipients", fmt_num(email_received + text_sent), percent_change_text(email_received + text_sent, prev_email + prev_text), yoy_change(email_received + text_sent, "recipients"))]
    for index, card in enumerate(health_data):
        with health_cards[index % 2]:
            insight_card(*card[:3], comparison=comparison_note, secondary_delta=card[3])
with health_chart:
    st.markdown(f'<div class="chart-card"><div class="chart-title">List Health Trend ({period_label})</div><div class="chart-subtitle">Rates across the selected time period</div>', unsafe_allow_html=True)
    received_daily = current["Received Email"]["values"].get("count", [])
    def daily_rate(metric_name: str) -> list[float]:
        events = current[metric_name]["values"].get("count", [])
        return [(float(value or 0) / float(received_daily[index] or 1)) * 100 if index < len(received_daily) else 0 for index, value in enumerate(events)]
    line_chart(current["Bounced Email"]["dates"], {"Unsubscribe Rate (%)": daily_rate("Unsubscribed from Email Marketing"), "Spam Rate (%)": daily_rate("Marked Email as Spam"), "Bounce Rate (%)": daily_rate("Bounced Email")}, "list_health", 285, y_suffix="%", colors=["#16a365", "#ff7a00", "#6c45d8"])
    st.markdown('</div>', unsafe_allow_html=True)

# 3 Subscribers
section("3", "SUBSCRIBERS")
email_subs, sms_subs = agg("Subscribed to Email Marketing"), agg("Subscribed to Text Messaging Marketing")
sms_unsubs = sms_all["unsubscribe_uniques"]
previous_email_subs, previous_sms_subs = agg("Subscribed to Email Marketing", prior=True), agg("Subscribed to Text Messaging Marketing", prior=True)
previous_email_unsubs = float(reports.get("previous_email_unsubscribe_uniques", previous_email_all["unsubscribe_uniques"]))
previous_sms_unsubs = previous_sms_all["unsubscribe_uniques"]
inventory = load_subscriber_inventory(API_KEY, REVISION, EMAIL_SUBSCRIBER_SEGMENT_ID, SMS_SUBSCRIBER_SEGMENT_ID)
email_subscription_rate = email_subs / inventory["email"] if inventory["email"] else 0
sms_subscription_rate = sms_subs / inventory["sms"] if inventory["sms"] else 0
email_unsubscription_rate = email_unsubs / inventory["email"] if inventory["email"] else 0
sms_unsubscription_rate = sms_unsubs / inventory["sms"] if inventory["sms"] else 0
email_start_inventory = max(inventory["email"] - email_subs + email_unsubs, 0)
sms_start_inventory = max(inventory["sms"] - sms_subs + sms_unsubs, 0)
previous_email_subscription_rate = previous_email_subs / email_start_inventory if email_start_inventory else 0
previous_sms_subscription_rate = previous_sms_subs / sms_start_inventory if sms_start_inventory else 0
previous_email_unsubscription_rate = previous_email_unsubs / email_start_inventory if email_start_inventory else 0
previous_sms_unsubscription_rate = previous_sms_unsubs / sms_start_inventory if sms_start_inventory else 0


total_cols = st.columns(2)
with total_cols[0]:
    insight_card("Total Email Subscribers", fmt_num(inventory["email"]), None)
with total_cols[1]:
    insight_card("Total SMS Subscribers", fmt_num(inventory["sms"]), None)

email_daily = current["Subscribed to Email Marketing"]["values"].get("count", [])
email_unsub_daily = current["Unsubscribed from Email Marketing"]["values"].get("count", [])
sms_daily = current["Subscribed to Text Messaging Marketing"]["values"].get("count", [])
sms_unsub_daily = current["Unsubscribed from Text Messaging Marketing"]["values"].get("count", [])

email_activity = st.columns([1, 1, 2.4])
with email_activity[0]:
    activity_card("Email Subscribers", fmt_num(email_subs), percent_change_text(email_subs, previous_email_subs), f"{email_subscription_rate:.2%}", percent_change_text(email_subscription_rate, previous_email_subscription_rate), comparison_note, yoy_change(email_subs, "email_subscribers"), ("--%", "neutral"))
with email_activity[1]:
    activity_card("Email Unsubscribers", fmt_num(email_unsubs), inverse_change_text(email_unsubs, previous_email_unsubs), f"{email_unsubscription_rate:.2%}", inverse_change_text(email_unsubscription_rate, previous_email_unsubscription_rate), comparison_note, inverse_change_text(email_unsubs, yoy_revenue["email_unsubscribers"]) if yoy_revenue and "email_unsubscribers" in yoy_revenue else ("--%", "neutral"), ("--%", "neutral"))
with email_activity[2]:
    st.markdown(f'<div class="chart-card"><div class="chart-title">Email Subscriber Trend ({period_label})</div><div class="chart-subtitle">New subscribers and unsubscribers</div>', unsafe_allow_html=True)
    line_chart(current["Subscribed to Email Marketing"]["dates"], {"New Subscribers": email_daily, "Unsubscribers": email_unsub_daily}, "email_subscriber_activity", 267, colors=["#6c5ce7", "#ef5b67"])
    st.markdown('</div>', unsafe_allow_html=True)

sms_activity = st.columns([1, 1, 2.4])
with sms_activity[0]:
    activity_card("SMS Subscribers", fmt_num(sms_subs), percent_change_text(sms_subs, previous_sms_subs), f"{sms_subscription_rate:.2%}", percent_change_text(sms_subscription_rate, previous_sms_subscription_rate), comparison_note, yoy_change(sms_subs, "sms_subscribers"), ("--%", "neutral"))
with sms_activity[1]:
    activity_card("SMS Unsubscribers", fmt_num(sms_unsubs), inverse_change_text(sms_unsubs, previous_sms_unsubs), f"{sms_unsubscription_rate:.2%}", inverse_change_text(sms_unsubscription_rate, previous_sms_unsubscription_rate), comparison_note, inverse_change_text(sms_unsubs, yoy_revenue["sms_unsubscribers"]) if yoy_revenue and "sms_unsubscribers" in yoy_revenue else ("--%", "neutral"), ("--%", "neutral"))
with sms_activity[2]:
    st.markdown(f'<div class="chart-card"><div class="chart-title">SMS Subscriber Trend ({period_label})</div><div class="chart-subtitle">New subscribers and unsubscribers</div>', unsafe_allow_html=True)
    line_chart(current["Subscribed to Text Messaging Marketing"]["dates"], {"New Subscribers": sms_daily, "Unsubscribers": sms_unsub_daily}, "sms_subscriber_activity", 267, colors=["#ffae00", "#ff6500"])
    st.markdown('</div>', unsafe_allow_html=True)

email_campaign_df = report_frame(reports["campaigns"], reports["campaign_names"], "campaign_id", "email", None, reports.get("campaign_dates", {}))
sms_campaign_df = report_frame(reports["campaigns"], reports["campaign_names"], "campaign_id", "sms", None, reports.get("campaign_dates", {}))


def paginated_campaigns(frame: pd.DataFrame, channel: str) -> tuple[pd.DataFrame, int, int]:
    """Keep campaign pagination local to each browser session and date window."""
    window_key = (start.isoformat(), end.isoformat())
    stored_window_key = f"dashboard_{channel}_campaign_window"
    count_key = f"dashboard_{channel}_campaign_count"
    if st.session_state.get(stored_window_key) != window_key:
        st.session_state[stored_window_key] = window_key
        st.session_state[count_key] = 20
    visible_count = min(int(st.session_state.get(count_key, 20)), len(frame))
    return frame.head(visible_count), visible_count, len(frame)


def campaign_load_more(channel: str, visible_count: int, total_count: int) -> None:
    label = f"Showing {visible_count} of {total_count} campaigns"
    info_column, button_column = st.columns([5, 1.25], vertical_alignment="center")
    with info_column:
        st.caption(label)
    if visible_count < total_count:
        with button_column:
            if st.button("Load 20 more", key=f"{channel}_campaign_load_more", use_container_width=True):
                count_key = f"dashboard_{channel}_campaign_count"
                st.session_state[count_key] = min(visible_count + 20, total_count)
                st.rerun()


email_df, email_visible_count, email_campaign_count = paginated_campaigns(email_campaign_df, "email")
sms_df, sms_visible_count, sms_campaign_count = paginated_campaigns(sms_campaign_df, "sms")


def flow_revenue(rows: list[dict], aliases: tuple[str, ...], channel: str) -> float:
    total = 0.0
    for row in rows:
        group = row.get("groupings", {})
        name = str(group.get("flow_name") or reports["flow_names"].get(str(group.get("flow_id") or ""), "")).lower()
        send_channel = str(group.get("send_channel") or "").strip().lower()
        if send_channel == channel and any(alias in name for alias in aliases):
            total += float(row.get("statistics", {}).get("conversion_value") or 0)
    return total


def select_flow(label: str, aliases: tuple[str, ...], channel: str = "email") -> dict:
    current_value = flow_revenue(reports["flows"], aliases, channel)
    previous_value = flow_revenue(reports["previous_flows"], aliases, channel)
    yoy_value = flow_revenue(yoy_revenue.get("flows", []), aliases, channel) if yoy_revenue else None
    return {"Flow Name": label, "Revenue": current_value, "Previous Revenue": previous_value, "YoY Revenue": yoy_value}


featured_flows = [select_flow("Welcome Flow", ("welcome",), "email"), select_flow("SMS Welcome Flow", ("welcome",), "sms"), select_flow("Abandoned Checkout Flow", ("abandoned checkout", "checkout abandon"), "email"), select_flow("Abandoned Cart Flow", ("abandoned cart", "cart abandon"), "email"), select_flow("Post Purchase Flow", ("post purchase", "post-purchase", "instructions", "reminders"), "email")]
featured_flow_df = pd.DataFrame(featured_flows)


def cards_from_frame(frame: pd.DataFrame, title_field: str, specs: list[tuple[str, str, object, bool]], images: dict[str, str] | None = None) -> list[tuple]:
    cards = []
    for _, row in frame.iterrows():
        metrics = []
        for field, label, formatter, color_change in specs:
            raw = row.get(field)
            value = formatter(raw)
            css = "neutral"
            if color_change and pd.notna(raw):
                css = "positive" if float(raw) >= 0 else "negative"
            metrics.append((label, value, css))
        title = str(row.get(title_field) or "Untitled")
        cards.append((title, metrics, (images or {}).get(title, "")))
    return cards


def campaign_messages(frame: pd.DataFrame, channel: str) -> tuple[tuple[str, str], ...]:
    """Return one message/template per visible campaign, preserving display order."""
    message_by_campaign: dict[str, str] = {}
    for report_row in reports["campaigns"]:
        group = report_row.get("groupings", {})
        if str(group.get("send_channel") or "").strip().lower() != channel:
            continue
        campaign_id = str(group.get("campaign_id") or "")
        # A/B templates are attached to the variation. For standard campaigns,
        # reporting can return the campaign ID in `campaign_message_id`, so use
        # the real campaign-message relationship collected from Campaigns API.
        message_id = str(
            group.get("variation")
            or reports.get("campaign_message_ids", {}).get(campaign_id)
            or group.get("campaign_message_id")
            or ""
        )
        if campaign_id and message_id and campaign_id not in message_by_campaign:
            message_by_campaign[campaign_id] = message_id
    campaign_id_by_name = {name: campaign_id for campaign_id, name in reports["campaign_names"].items()}
    return tuple(
        (str(row["Name"]), message_by_campaign[campaign_id_by_name[str(row["Name"])]])
        for _, row in frame.iterrows()
        if str(row["Name"]) in campaign_id_by_name and campaign_id_by_name[str(row["Name"])] in message_by_campaign
    )


money = lambda value: fmt_money(float(value or 0))
number = lambda value: fmt_num(float(value or 0))
rate = lambda value: f"{float(value or 0):.2%}"
# 4–6 performance cards
section("4", "FLOWS PERFORMANCE")
flow_records = list(featured_flow_df.iterrows())
for row_start, row_size in ((0, 3), (3, 2)):
    flow_columns = st.columns(row_size)
    for col, (_, flow) in zip(flow_columns, flow_records[row_start:row_start + row_size]):
        with col:
            yoy_delta = percent_change_text(float(flow["Revenue"]), float(flow["YoY Revenue"])) if pd.notna(flow["YoY Revenue"]) else ("--%", "neutral")
            insight_card(str(flow["Flow Name"]), fmt_money(float(flow["Revenue"])), percent_change_text(float(flow["Revenue"]), float(flow["Previous Revenue"])), comparison=comparison_note, secondary_delta=yoy_delta)

section("5", "EMAIL CAMPAIGN PERFORMANCE")
email_messages = campaign_messages(email_df, "email")
loading_images = {name: "__loading__" for name, _ in email_messages}
campaign_cards = st.empty()
with campaign_cards.container():
    detail_cards(cards_from_frame(email_df, "Name", [("Sent Date", "Sent Date", str, False), ("Revenue", "Revenue", money, False), ("Open rate", "Open Rate", rate, False), ("Click rate", "Click Rate", rate, False), ("Orders", "Orders", number, False), ("AOV", "Average Order Value ($)", money, False)], loading_images), columns=2, key="email-loading")
campaign_assets = load_campaign_creatives(API_KEY, REVISION, email_messages)
campaign_images = {name: assets[0]["image_url"] for name, assets in campaign_assets.items() if assets}
with campaign_cards.container():
    detail_cards(cards_from_frame(email_df, "Name", [("Sent Date", "Sent Date", str, False), ("Revenue", "Revenue", money, False), ("Open rate", "Open Rate", rate, False), ("Click rate", "Click Rate", rate, False), ("Orders", "Orders", number, False), ("AOV", "Average Order Value ($)", money, False)], campaign_images), columns=2, key="email")
campaign_load_more("email", email_visible_count, email_campaign_count)

section("6", "SMS CAMPAIGN PERFORMANCE")
if sms_df.empty:
    st.info(f"No SMS campaigns were returned by Klaviyo for {start:%b %d, %Y} – {end:%b %d, %Y}.")
else:
    sms_messages = campaign_messages(sms_df, "sms")
    sms_cards_data = cards_from_frame(sms_df, "Name", [("Sent Date", "Sent Date", str, False), ("Revenue", "Revenue", money, False), ("Click rate", "Click Rate", rate, False), ("Orders", "Orders", number, False), ("AOV", "Average Order Value ($)", money, False)])
    sms_cards = st.empty()
    with sms_cards.container():
        sms_campaign_cards(sms_cards_data, {name: {"loading": True} for name, _ in sms_messages}, columns=2, key="sms-loading")
    sms_previews = load_sms_previews(API_KEY, REVISION, sms_messages)
    with sms_cards.container():
        sms_campaign_cards(sms_cards_data, sms_previews, columns=2, key="sms")
    campaign_load_more("sms", sms_visible_count, sms_campaign_count)

# 7–8 experimentation and creative detail
section("7", "A/B TESTING")
ab_df = ab_test_frame(reports["campaigns"])
if ab_df.empty:
    st.info("No campaign variations were returned for this period.")
else:
    ab_columns = st.columns(2)
    for campaign_index, (campaign_name, variants) in enumerate(ab_df.groupby("Campaign", sort=False)):
        with ab_columns[campaign_index % 2]:
            variants = variants.sort_values("Variant").copy()
            variants["Display Variant"] = [f"Variation {chr(65 + index)}" for index in range(len(variants))]
            ranked = variants.sort_values(["Open rate", "Click rate", "Revenue"], ascending=False)
            winner = str(ranked.iloc[0]["Display Variant"])
            winning_open_rate = float(ranked.iloc[0]["Open rate"])
            runner_up_open_rate = float(ranked.iloc[1]["Open rate"]) if len(ranked) > 1 else 0
            open_rate_lift = (winning_open_rate - runner_up_open_rate) / runner_up_open_rate if runner_up_open_rate else None
            variant_rows = [{"variant": str(row["Display Variant"]), "open_rate": f'{float(row["Open rate"]):.2%}', "click_rate": f'{float(row["Click rate"]):.2%}', "revenue": fmt_money(float(row["Revenue"])), "aov": fmt_money(float(row["AOV"]))} for _, row in variants.iterrows()]
            ab_test_card(str(campaign_name), variant_rows, winner, f"{winning_open_rate:.2%}", f"{open_rate_lift:.2%}" if open_rate_lift is not None else "—")

section("8", "CAMPAIGN CREATIVE PERFORMANCE")
creative_attributes = load_creative_clicks(API_KEY, REVISION, start, end, current["metric_ids"].get("Clicked Email", ""))
delivered_by_message = {}
for row in reports["campaigns"]:
    message_name = row.get("groupings", {}).get("campaign_message_name") or ""
    delivered_by_message[message_name] = delivered_by_message.get(message_name, 0) + float(row.get("statistics", {}).get("delivered") or 0)
creative_df = creative_module_frame(creative_attributes, delivered_by_message)
if creative_df.empty:
    st.info("No URL-level creative/module click tracking was returned for this period.")
else:
    creative_df = creative_df.copy()
    message_metadata = {}
    for report_row in reports["campaigns"]:
        group = report_row.get("groupings", {})
        message_name = str(group.get("campaign_message_name") or "")
        campaign_id = str(group.get("campaign_id") or "")
        message_metadata[message_name] = {
            "campaign": reports["campaign_names"].get(campaign_id, message_name),
            "sent_date": reports.get("campaign_dates", {}).get(campaign_id, "—") or "—",
        }
    creative_df["Campaign Name"] = creative_df["Campaign"].map(lambda name: message_metadata.get(str(name), {}).get("campaign", str(name)))
    creative_df["Sent Date"] = creative_df["Campaign"].map(lambda name: message_metadata.get(str(name), {}).get("sent_date", "—"))
    creative_df["_sent_at"] = pd.to_datetime(creative_df["Sent Date"], errors="coerce", utc=True)
    creative_df = creative_df.sort_values(["_sent_at", "Campaign Name", "Unique clicks"], ascending=[False, True, False], na_position="last")
    creative_df["Module"] = creative_df.groupby("Campaign").cumcount().add(1).map(lambda value: f"Module {value}")
    module_campaign_names = creative_df.drop_duplicates("Campaign").head(8)["Campaign Name"].astype(str).tolist()
    top_creatives = creative_df.sort_values(["Module click rate", "Unique clicks"], ascending=False).head(10)
    creative_campaign_names = list(dict.fromkeys(module_campaign_names + top_creatives["Campaign Name"].astype(str).tolist()))
    creative_messages = campaign_messages(pd.DataFrame({"Name": creative_campaign_names}), "email")
    missing_creative_messages = tuple((name, message_id) for name, message_id in creative_messages if name not in campaign_images)
    if missing_creative_messages:
        extra_campaign_assets = load_campaign_creatives(API_KEY, REVISION, missing_creative_messages)
        campaign_images.update({name: assets[0]["image_url"] for name, assets in extra_campaign_assets.items() if assets})
    module_campaigns = []
    for _, modules in creative_df.groupby("Campaign", sort=False):
        campaign_name = str(modules.iloc[0]["Campaign Name"])
        module_campaigns.append((campaign_name, str(modules.iloc[0]["Sent Date"]), [(str(row["Module / URL"]), f'{float(row["Module click rate"]):.2%}') for _, row in modules.head(6).iterrows()], campaign_images.get(campaign_name, "")))
    st.markdown('<div class="chart-title">Module Performance (Click Rate)</div><div class="chart-subtitle">Each unique tracked URL is treated as one module</div>', unsafe_allow_html=True)
    module_performance_table(module_campaigns[:8])
    st.markdown('<div class="chart-title" style="margin-top:1rem">Top Creative</div><div class="chart-subtitle">Tracked URLs ranked by click rate</div>', unsafe_allow_html=True)
    top_creative_table([{"campaign": str(row["Campaign Name"]), "module": str(row["Module"]), "url": str(row["Module / URL"]), "clicks": fmt_num(float(row["Unique clicks"])), "rate": f'{float(row["Module click rate"]):.2%}', "image": campaign_images.get(str(row["Campaign Name"]), "")} for _, row in top_creatives.iterrows()])

st.write("")
if st.button("↻ Refresh Klaviyo data"):
    shared_yoy_store().clear()
    st.session_state.pop("dashboard_yoy_data", None)
    st.cache_data.clear()
    st.rerun()
st.markdown(f'<div class="page-note">Data covers {start:%Y-%m-%d} to {end:%Y-%m-%d} from Klaviyo · API revision {REVISION} · Cached for 2 hours</div>', unsafe_allow_html=True)
