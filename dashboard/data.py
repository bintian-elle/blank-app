from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import time
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import streamlit as st

from klaviyo_client import DateWindow, KlaviyoClient, KlaviyoError, values_from_aggregate


METRIC_NAMES = ("Placed Order", "Received Email", "Opened Email", "Clicked Email", "Bounced Email", "Marked Email as Spam", "Unsubscribed from Email Marketing", "Sent Text Message", "Clicked Text Message", "Subscribed to Email Marketing", "Subscribed to Text Messaging Marketing", "Unsubscribed from Text Messaging Marketing")
COMPARISON_METRICS = METRIC_NAMES
REPORT_STATS = ["recipients", "delivered", "open_rate", "click_rate", "conversion_value", "conversions", "average_order_value", "unsubscribe_rate", "bounce_rate", "spam_complaint_rate"]


@st.cache_resource
def shared_yoy_store() -> dict[tuple[str, str], dict]:
    """Process-wide YoY results shared by all browser sessions."""
    return {}


def _total(values: dict[str, list[float]], measurement: str) -> float:
    return sum(values.get(measurement, []))


@st.cache_data(ttl=7200, show_spinner=False)
def load_aggregates(api_key: str, revision: str, start: date, end: date, names: tuple[str, ...]) -> dict:
    client, window = KlaviyoClient(api_key, revision), DateWindow(start, end)
    metric_ids = client.metrics()
    result: dict = {"metric_ids": metric_ids}
    for index, name in enumerate(names):
        metric_id = metric_ids.get(name)
        if not metric_id:
            result[name] = {"dates": [], "values": {}}
            continue
        measurements = ["count", "sum_value"] if name == "Placed Order" else ["count", "unique"]
        try:
            attrs = client.aggregate(metric_id, window, measurements, "day")
        except KlaviyoError as exc:
            if "measurement" not in str(exc).lower():
                raise
            attrs = client.aggregate(metric_id, window, ["count"], "day")
        dates, values = values_from_aggregate(attrs)
        result[name] = {"dates": dates, "values": values}
        if index < len(names) - 1:
            time.sleep(.36)
    return result


@st.cache_data(ttl=7200, show_spinner=False)
def load_reports(api_key: str, revision: str, start: date, end: date, previous_start: date, previous_end: date, order_id: str, compare: bool) -> dict:
    client, window = KlaviyoClient(api_key, revision), DateWindow(start, end)
    group_campaign = ["campaign_message_id", "campaign_id", "campaign_message_name", "send_channel", "variation", "variation_name"]
    group_flow = ["flow_message_id", "flow_id", "flow_name", "send_channel"]
    campaigns = client.reporting_values("campaign-values-report", window, order_id, REPORT_STATS, group_campaign)
    flows = client.reporting_values("flow-values-report", window, order_id, REPORT_STATS, group_flow)
    previous_campaigns: list[dict] = []
    previous_flows: list[dict] = []
    if compare:
        previous_window = DateWindow(previous_start, previous_end)
        previous_campaigns = client.reporting_values("campaign-values-report", previous_window, order_id, REPORT_STATS, group_campaign)
        previous_flows = client.reporting_values("flow-values-report", previous_window, order_id, REPORT_STATS, group_flow)
    email_names, email_dates = client.campaign_details("email")
    sms_names, sms_dates = client.campaign_details("sms")
    return {"campaigns": campaigns, "flows": flows, "previous_campaigns": previous_campaigns, "previous_flows": previous_flows, "campaign_names": {**email_names, **sms_names}, "campaign_dates": {**email_dates, **sms_dates}, "flow_names": client.flows()}


@st.cache_data(ttl=7200, show_spinner=False)
def load_channel_revenue(api_key: str, revision: str, start: date, end: date, order_id: str, received_email_id: str = "", sent_text_id: str = "", activity_metric_ids: tuple[str, ...] = ()) -> dict[str, object]:
    """Load one reporting window and return the metrics needed by YoY overview cards."""
    client, window = KlaviyoClient(api_key, revision), DateWindow(start, end)
    # Klaviyo requires message and parent IDs when grouping these reports. We
    # request the required dimensions, then collapse them locally by channel.
    campaign_groupings = ["campaign_message_id", "campaign_id", "campaign_message_name", "send_channel", "variation", "variation_name"]
    flow_groupings = ["flow_message_id", "flow_id", "flow_name", "send_channel"]
    campaigns = client.reporting_values("campaign-values-report", window, order_id, REPORT_STATS, campaign_groupings)
    flows = client.reporting_values("flow-values-report", window, order_id, REPORT_STATS, flow_groupings)
    email_campaign = report_totals(campaigns, "email")["conversion_value"]
    email_flow = report_totals(flows, "email")["conversion_value"]
    email = email_campaign + email_flow
    sms = report_totals(campaigns + flows, "sms")["conversion_value"]
    recipients = 0.0
    for metric_id in (received_email_id, sent_text_id):
        if metric_id:
            _, metric_values = values_from_aggregate(client.aggregate(metric_id, window, ["count"], "day"))
            recipients += sum(float(value or 0) for value in metric_values.get("count", []))
    activity_names = ("email_subscribers", "sms_subscribers", "email_unsubscribers", "sms_unsubscribers")
    activity_totals: dict[str, float] = {}
    for name, metric_id in zip(activity_names, activity_metric_ids):
        if not metric_id:
            continue
        _, metric_values = values_from_aggregate(client.aggregate(metric_id, window, ["count"], "day"))
        activity_totals[name] = sum(float(value or 0) for value in metric_values.get("count", []))
    email_health = report_totals(campaigns + flows, "email")
    return {"email": email, "sms": sms, "edm": email + sms, "email_flow": email_flow, "email_campaign": email_campaign, "recipients": recipients, "flows": flows, "email_health": email_health, **activity_totals}


@st.cache_data(ttl=21600, show_spinner=False)
def load_subscriber_inventory(api_key: str, revision: str, email_segment_id: str, sms_segment_id: str) -> dict[str, float]:
    if not email_segment_id or not sms_segment_id:
        return {"email": 0, "sms": 0}
    values = KlaviyoClient(api_key, revision).segment_values([email_segment_id, sms_segment_id])
    return {"email": values.get(email_segment_id, 0), "sms": values.get(sms_segment_id, 0)}


@st.cache_data(ttl=7200, show_spinner=False)
def load_creative_clicks(api_key: str, revision: str, start: date, end: date, clicked_email_id: str) -> dict:
    if not clicked_email_id:
        return {"dates": [], "data": []}
    return KlaviyoClient(api_key, revision).aggregate_grouped(clicked_email_id, DateWindow(start, end), ["count", "unique"], ["Message Name", "URL"], "day")


class _LinkedAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self.current_href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a":
            self.current_href = values.get("href") or ""
        elif tag == "img" and self.current_href:
            self.links.append({"url": self.current_href, "image_url": values.get("src") or "", "label": values.get("alt") or "Linked image"})

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.current_href = ""


def _clean_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    except ValueError:
        return value.strip()


@st.cache_data(ttl=7200, show_spinner=False)
def load_campaign_creatives(api_key: str, revision: str, messages: tuple[tuple[str, str], ...]) -> dict[str, list[dict[str, str]]]:
    client = KlaviyoClient(api_key, revision)
    result: dict[str, list[dict[str, str]]] = {}
    for message_name, message_id in messages[:5]:
        try:
            template = client.template_for_campaign_message(message_id)
            parser = _LinkedAssetParser()
            parser.feed(str(template.get("html") or ""))
            result[message_name] = parser.links
        except KlaviyoError:
            result[message_name] = []
        time.sleep(.15)
    return result


def load_dashboard(api_key: str, revision: str, start: date, end: date, previous_start: date, previous_end: date, compare: bool = True) -> tuple[dict, dict, dict]:
    if not api_key:
        st.error("Add KLAVIYO_API_KEY to .streamlit/secrets.toml.")
        st.stop()
    try:
        with st.spinner("Loading live data from Klaviyo…"):
            current = load_aggregates(api_key, revision, start, end, METRIC_NAMES)
            previous = load_aggregates(api_key, revision, previous_start, previous_end, COMPARISON_METRICS) if compare else {}
            order_id = current["metric_ids"].get("Placed Order")
            if not order_id:
                raise KlaviyoError("Placed Order metric was not found")
            reports = load_reports(api_key, revision, start, end, previous_start, previous_end, order_id, compare)
        return current, previous, reports
    except KlaviyoError as exc:
        st.error(f"Klaviyo data could not be loaded: {exc}")
        if st.button("Retry"):
            st.cache_data.clear(); st.rerun()
        st.stop()


def aggregate(source: dict, name: str, measurement: str = "count") -> float:
    return _total(source.get(name, {}).get("values", {}), measurement)


def report_totals(rows: list[dict], channel: str | None = None) -> dict[str, float]:
    selected = [r for r in rows if not channel or str(r.get("groupings", {}).get("send_channel") or "").strip().lower() == channel.strip().lower()]
    sums = {k: sum(float(r.get("statistics", {}).get(k) or 0) for r in selected) for k in ["recipients", "delivered", "conversion_value", "conversions"]}
    delivered = sums["delivered"]
    weighted = {k: sum(float(r.get("statistics", {}).get(k) or 0) * float(r.get("statistics", {}).get("delivered") or 0) for r in selected) / delivered if delivered else 0 for k in ["open_rate", "click_rate", "unsubscribe_rate", "bounce_rate", "spam_complaint_rate"]}
    return {**sums, **weighted, "average_order_value": sums["conversion_value"] / sums["conversions"] if sums["conversions"] else 0}


def report_frame(rows: list[dict], names: dict[str, str], id_field: str, channel: str | None = None, limit: int = 50, dates: dict[str, str] | None = None) -> pd.DataFrame:
    grouped: dict[str, dict[str, float]] = {}
    for row in rows:
        group = row.get("groupings", {})
        if channel and str(group.get("send_channel") or "").strip().lower() != channel.strip().lower():
            continue
        oid, stats = group.get(id_field, ""), row.get("statistics", {})
        target = grouped.setdefault(oid, {"Revenue": 0, "Recipients": 0, "Orders": 0, "open_num": 0, "click_num": 0, "delivered": 0})
        delivered = float(stats.get("delivered") or 0)
        target["Revenue"] += float(stats.get("conversion_value") or 0); target["Recipients"] += float(stats.get("recipients") or 0); target["Orders"] += float(stats.get("conversions") or 0)
        target["open_num"] += float(stats.get("open_rate") or 0) * delivered; target["click_num"] += float(stats.get("click_rate") or 0) * delivered; target["delivered"] += delivered
    records = []
    for oid, x in grouped.items():
        records.append({"Name": names.get(oid, oid), "Sent Date": (dates or {}).get(oid, "—") or "—", "Revenue": x["Revenue"], "Recipients": int(x["Recipients"]), "Open rate": x["open_num"] / x["delivered"] if x["delivered"] else 0, "Click rate": x["click_num"] / x["delivered"] if x["delivered"] else 0, "Orders": int(x["Orders"]), "AOV": x["Revenue"] / x["Orders"] if x["Orders"] else 0})
    columns = ["Name", "Sent Date", "Revenue", "Recipients", "Open rate", "Click rate", "Orders", "AOV"]
    if not records:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(records)
    if dates is not None:
        frame["_sent_at"] = pd.to_datetime(frame["Sent Date"], errors="coerce", utc=True)
        frame = frame.sort_values(["_sent_at", "Revenue"], ascending=[False, False], na_position="last").drop(columns="_sent_at")
    else:
        frame = frame.sort_values("Revenue", ascending=False)
    return frame.head(limit)


TABLE_FORMATS = {"Revenue": "${:,.2f}", "Open rate": "{:.2%}", "Click rate": "{:.2%}", "AOV": "${:,.2f}"}


def table_config(exclude: tuple[str, ...] = {}) -> dict:
    return {k: st.column_config.NumberColumn(format=v) for k, v in TABLE_FORMATS.items() if k not in exclude}


def ab_test_frame(rows: list[dict]) -> pd.DataFrame:
    records = []
    for row in rows:
        group, stats = row.get("groupings", {}), row.get("statistics", {})
        variation = group.get("variation_name") or group.get("variation")
        if not variation:
            continue
        conversions = float(stats.get("conversions") or 0)
        revenue = float(stats.get("conversion_value") or 0)
        records.append({"Campaign": group.get("campaign_message_name") or group.get("campaign_id"), "Variant": variation, "Channel": group.get("send_channel", ""), "Open rate": float(stats.get("open_rate") or 0), "Click rate": float(stats.get("click_rate") or 0), "Revenue": revenue, "AOV": revenue / conversions if conversions else 0})
    return pd.DataFrame(records).sort_values("Revenue", ascending=False) if records else pd.DataFrame(columns=["Campaign", "Variant", "Channel", "Open rate", "Click rate", "Revenue", "AOV"])


def creative_frame(rows: list[dict]) -> pd.DataFrame:
    grouped: dict[str, dict[str, float]] = {}
    for row in rows:
        group, stats = row.get("groupings", {}), row.get("statistics", {})
        name = group.get("campaign_message_name") or group.get("campaign_message_id")
        target = grouped.setdefault(name, {"Revenue": 0, "Recipients": 0, "click_num": 0, "delivered": 0})
        delivered = float(stats.get("delivered") or 0)
        target["Revenue"] += float(stats.get("conversion_value") or 0); target["Recipients"] += float(stats.get("recipients") or 0)
        target["click_num"] += float(stats.get("click_rate") or 0) * delivered; target["delivered"] += delivered
    records = [{"Creative / message": name, "Revenue": x["Revenue"], "Recipients": int(x["Recipients"]), "Click rate": x["click_num"] / x["delivered"] if x["delivered"] else 0} for name, x in grouped.items()]
    return pd.DataFrame(records).sort_values(["Click rate", "Revenue"], ascending=False).head(10) if records else pd.DataFrame(columns=["Creative / message", "Revenue", "Recipients", "Click rate"])


def creative_module_frame(attributes: dict, delivered_by_message: dict[str, float]) -> pd.DataFrame:
    """Treat tracked URLs as creative modules; Klaviyo does not expose visual block IDs."""
    records = []
    for group in attributes.get("data", []) or []:
        dimensions = group.get("dimensions", []) or []
        if len(dimensions) < 2:
            continue
        message, url = str(dimensions[0] or ""), str(dimensions[1] or "")
        if not message or not url:
            continue
        measurements = group.get("measurements", {})
        unique_clicks = sum(float(value or 0) for value in measurements.get("unique", []))
        delivered = delivered_by_message.get(message, 0)
        records.append({"Campaign": message, "Module / URL": url, "Unique clicks": int(unique_clicks), "Delivered": delivered, "Module click rate": unique_clicks / delivered if delivered else 0})
    return pd.DataFrame(records).sort_values(["Campaign", "Unique clicks"], ascending=[True, False]) if records else pd.DataFrame(columns=["Campaign", "Module / URL", "Unique clicks", "Delivered", "Module click rate"])


def attach_creative_assets(frame: pd.DataFrame, assets: dict[str, list[dict[str, str]]]) -> pd.DataFrame:
    if frame.empty:
        return frame.assign(Image=pd.Series(dtype=str), Type=pd.Series(dtype=str))
    output = frame.copy()
    images, types = [], []
    for _, row in output.iterrows():
        target = _clean_url(str(row["Module / URL"]))
        candidates = assets.get(str(row["Campaign"]), [])
        match = next((item for item in candidates if _clean_url(item.get("url", "")) == target), None)
        images.append(match.get("image_url", "") if match else "")
        types.append("Linked Creative" if match and match.get("image_url") else "Link")
    output["Image"] = images
    output["Type"] = types
    return output
