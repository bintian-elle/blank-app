from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from html.parser import HTMLParser
import time
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import streamlit as st

from klaviyo_client import DateWindow, KlaviyoClient, KlaviyoError, values_from_aggregate


METRIC_NAMES = ("Placed Order", "Received Email", "Opened Email", "Clicked Email", "Bounced Email", "Marked Email as Spam", "Unsubscribed from Email Marketing", "Sent Text Message", "Clicked Text Message", "Subscribed to Email Marketing", "Subscribed to Text Messaging Marketing", "Unsubscribed from Text Messaging Marketing")
COMPARISON_METRICS = METRIC_NAMES
REPORT_STATS = ["recipients", "delivered", "open_rate", "click_rate", "conversion_value", "conversions", "average_order_value", "unsubscribe_rate", "unsubscribe_uniques", "bounce_rate", "spam_complaint_rate"]
REPORT_CACHE_VERSION = "2026-08-18-attributed-unsubscribers-v1"
METADATA_TTL = 86400
LIVE_DATA_TTL = 7200
HISTORICAL_DATA_TTL = 2592000


@st.cache_resource
def shared_yoy_store() -> dict[tuple[str, str], dict]:
    """Process-wide YoY results shared by all browser sessions."""
    return {}


def _total(values: dict[str, list[float]], measurement: str) -> float:
    return sum(values.get(measurement, []))


@st.cache_data(ttl=METADATA_TTL, show_spinner=False)
def load_metric_ids(api_key: str, revision: str) -> dict[str, str]:
    """Metric IDs are account metadata and do not need fetching per period."""
    return KlaviyoClient(api_key, revision).metrics()


@st.cache_data(ttl=METADATA_TTL, show_spinner=False)
def load_reporting_metadata(api_key: str, revision: str, timezone_name: str, campaign_channels: tuple[tuple[str, str], ...], flow_items: tuple[tuple[str, str], ...]) -> dict[str, dict[str, str]]:
    """Fetch metadata only for campaigns present in the selected reports."""
    client = KlaviyoClient(api_key, revision)
    ids_by_channel = {
        channel: tuple(campaign_id for campaign_id, item_channel in campaign_channels if item_channel == channel)
        for channel in ("email", "sms")
    }
    email_names, email_dates, email_message_ids = client.campaign_details("email", timezone_name, ids_by_channel["email"]) if ids_by_channel["email"] else ({}, {}, {})
    sms_names, sms_dates, sms_message_ids = client.campaign_details("sms", timezone_name, ids_by_channel["sms"]) if ids_by_channel["sms"] else ({}, {}, {})
    return {
        "campaign_names": {**email_names, **sms_names},
        "campaign_dates": {**email_dates, **sms_dates},
        "campaign_message_ids": {**email_message_ids, **sms_message_ids},
        "flow_names": dict(flow_items),
    }


def _reporting_metadata_keys(reports: dict) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    campaign_channels: set[tuple[str, str]] = set()
    flow_items: set[tuple[str, str]] = set()
    for row in reports.get("campaigns", []) + reports.get("previous_campaigns", []):
        group = row.get("groupings") or {}
        campaign_id = str(group.get("campaign_id") or "")
        channel = str(group.get("send_channel") or "").strip().lower()
        if campaign_id and channel in ("email", "sms"):
            campaign_channels.add((campaign_id, channel))
    for row in reports.get("flows", []) + reports.get("previous_flows", []):
        group = row.get("groupings") or {}
        flow_id = str(group.get("flow_id") or "")
        flow_name = str(group.get("flow_name") or "Unnamed flow")
        if flow_id:
            flow_items.add((flow_id, flow_name))
    return tuple(sorted(campaign_channels)), tuple(sorted(flow_items))


@st.cache_data(ttl=METADATA_TTL, show_spinner=False)
def load_campaign_metadata_by_names(api_key: str, revision: str, timezone_name: str, names: tuple[str, ...]) -> dict[str, dict[str, str]]:
    campaign_names, dates, message_ids, requested_ids = KlaviyoClient(api_key, revision).campaign_details_by_names("email", names, timezone_name)
    return {
        "campaign_names": campaign_names,
        "campaign_dates": dates,
        "campaign_message_ids": message_ids,
        "requested_ids": requested_ids,
    }


def _metric_id_map(items: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return dict(items)


def _date_key(value: object) -> date | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _slice_metric(metric: dict, start: date, end: date) -> dict:
    dates = metric.get("dates", [])
    indexes = [index for index, value in enumerate(dates) if (parsed := _date_key(value)) and start <= parsed <= end]
    return {
        "dates": [dates[index] for index in indexes],
        "values": {
            measurement: [series[index] for index in indexes if index < len(series)]
            for measurement, series in metric.get("values", {}).items()
        },
    }


def _fetch_year_aggregates(api_key: str, revision: str, year: int, year_end: date, names: tuple[str, ...], metric_items: tuple[tuple[str, str], ...], timezone_name: str) -> dict:
    client = KlaviyoClient(api_key, revision)
    window = DateWindow(date(year, 1, 1), year_end)
    metric_ids = _metric_id_map(metric_items)
    result: dict = {"metric_ids": metric_ids}
    for index, name in enumerate(names):
        metric_id = metric_ids.get(name)
        if not metric_id:
            result[name] = {"dates": [], "values": {}}
            continue
        measurements = ["count", "sum_value"] if name == "Placed Order" else ["count", "unique"]
        try:
            attrs = client.aggregate(metric_id, window, measurements, "day", timezone_name)
        except KlaviyoError as exc:
            if "measurement" not in str(exc).lower():
                raise
            attrs = client.aggregate(metric_id, window, ["count"], "day", timezone_name)
        dates, values = values_from_aggregate(attrs)
        result[name] = {"dates": dates, "values": values}
        if index < len(names) - 1:
            time.sleep(.36)
    return result


@st.cache_data(ttl=LIVE_DATA_TTL, show_spinner=False)
def load_current_year_aggregates(api_key: str, revision: str, year: int, year_end: date, names: tuple[str, ...], metric_items: tuple[tuple[str, str], ...], timezone_name: str) -> dict:
    """Refresh the active calendar year every two hours."""
    return _fetch_year_aggregates(api_key, revision, year, year_end, names, metric_items, timezone_name)


@st.cache_data(ttl=HISTORICAL_DATA_TTL, show_spinner=False)
def load_historical_year_aggregates(api_key: str, revision: str, year: int, year_end: date, names: tuple[str, ...], metric_items: tuple[tuple[str, str], ...], timezone_name: str) -> dict:
    """Refresh completed calendar years every 30 days."""
    return _fetch_year_aggregates(api_key, revision, year, year_end, names, metric_items, timezone_name)


def _merge_year_metrics(year_data: list[dict], names: tuple[str, ...]) -> dict:
    metric_ids = year_data[0]["metric_ids"] if year_data else {}
    merged: dict = {"metric_ids": metric_ids}
    for name in names:
        dates: list = []
        values: dict[str, list[float]] = {}
        for yearly in year_data:
            metric = yearly.get(name, {})
            dates.extend(metric.get("dates", []))
            for measurement, series in metric.get("values", {}).items():
                values.setdefault(measurement, []).extend(series)
        merged[name] = {"dates": dates, "values": values}
    return merged


def load_period_aggregates(api_key: str, revision: str, start: date, end: date, names: tuple[str, ...], metric_items: tuple[tuple[str, str], ...], timezone_name: str) -> dict:
    """Build any selected period from reusable calendar-year daily caches."""
    today = date.today()
    yearly = []
    for year in range(start.year, end.year + 1):
        year_end = min(date(year, 12, 31), today) if year == today.year else date(year, 12, 31)
        loader = load_current_year_aggregates if year == today.year else load_historical_year_aggregates
        yearly.append(loader(api_key, revision, year, year_end, names, metric_items, timezone_name))
    merged = _merge_year_metrics(yearly, names)
    result: dict = {"metric_ids": merged["metric_ids"]}
    for name in names:
        result[name] = _slice_metric(merged.get(name, {}), start, end)
    return result


def _fetch_reports(api_key: str, revision: str, start: date, end: date, previous_start: date, previous_end: date, order_id: str, compare: bool, cache_version: str, timezone_name: str) -> dict:
    client, window = KlaviyoClient(api_key, revision), DateWindow(start, end)
    group_campaign = ["campaign_message_id", "campaign_id", "campaign_message_name", "send_channel", "variation", "variation_name"]
    group_flow = ["flow_message_id", "flow_id", "flow_name", "send_channel"]
    campaigns = client.reporting_values("campaign-values-report", window, order_id, REPORT_STATS, group_campaign, timezone_name)
    flows = client.reporting_values("flow-values-report", window, order_id, REPORT_STATS, group_flow, timezone_name)
    previous_campaigns: list[dict] = []
    previous_flows: list[dict] = []
    if compare:
        previous_window = DateWindow(previous_start, previous_end)
        previous_campaigns = client.reporting_values("campaign-values-report", previous_window, order_id, REPORT_STATS, group_campaign, timezone_name)
        previous_flows = client.reporting_values("flow-values-report", previous_window, order_id, REPORT_STATS, group_flow, timezone_name)
    return {"campaigns": campaigns, "flows": flows, "previous_campaigns": previous_campaigns, "previous_flows": previous_flows}


@st.cache_data(ttl=LIVE_DATA_TTL, show_spinner=False)
def load_live_reports(api_key: str, revision: str, start: date, end: date, previous_start: date, previous_end: date, order_id: str, compare: bool, cache_version: str, timezone_name: str) -> dict:
    return _fetch_reports(api_key, revision, start, end, previous_start, previous_end, order_id, compare, cache_version, timezone_name)


@st.cache_data(ttl=HISTORICAL_DATA_TTL, show_spinner=False)
def load_historical_reports(api_key: str, revision: str, start: date, end: date, previous_start: date, previous_end: date, order_id: str, compare: bool, cache_version: str, timezone_name: str) -> dict:
    return _fetch_reports(api_key, revision, start, end, previous_start, previous_end, order_id, compare, cache_version, timezone_name)


def load_reports(api_key: str, revision: str, start: date, end: date, previous_start: date, previous_end: date, order_id: str, compare: bool, cache_version: str, timezone_name: str) -> dict:
    latest_end = max(end, previous_end) if compare else end
    loader = load_historical_reports if latest_end.year < date.today().year else load_live_reports
    if not compare:
        return loader(api_key, revision, start, end, previous_start, previous_end, order_id, False, cache_version, timezone_name)

    current_window = (start, end)
    comparison_window = (previous_start, previous_end)
    first_window, second_window = sorted((current_window, comparison_window))
    reports = loader(
        api_key,
        revision,
        first_window[0],
        first_window[1],
        second_window[0],
        second_window[1],
        order_id,
        True,
        cache_version,
        timezone_name,
    )
    if first_window == current_window:
        return reports
    return {
        "campaigns": reports["previous_campaigns"],
        "flows": reports["previous_flows"],
        "previous_campaigns": reports["campaigns"],
        "previous_flows": reports["flows"],
    }


def _report_message_ids(campaigns: list[dict], flows: list[dict]) -> tuple[str, ...]:
    ids: set[str] = set()
    for row in campaigns:
        group = row.get("groupings") or {}
        for field in ("campaign_message_id", "campaign_id", "variation"):
            if group.get(field):
                ids.add(str(group[field]))
    for row in flows:
        group = row.get("groupings") or {}
        for field in ("flow_message_id", "flow_id"):
            if group.get(field):
                ids.add(str(group[field]))
    return tuple(sorted(ids))


@st.cache_data(ttl=METADATA_TTL, show_spinner=False)
def load_account_timezone(api_key: str, revision: str) -> str:
    return KlaviyoClient(api_key, revision).account_timezone()


def _fetch_attributed_email_unsubscribers(api_key: str, revision: str, start: date, end: date, metric_id: str, message_ids: tuple[str, ...], timezone_name: str) -> int:
    return KlaviyoClient(api_key, revision).attributed_unsubscribe_profiles(metric_id, DateWindow(start, end), message_ids, timezone_name)


@st.cache_data(ttl=LIVE_DATA_TTL, show_spinner=False)
def load_live_attributed_email_unsubscribers(api_key: str, revision: str, start: date, end: date, metric_id: str, message_ids: tuple[str, ...], timezone_name: str) -> int:
    return _fetch_attributed_email_unsubscribers(api_key, revision, start, end, metric_id, message_ids, timezone_name)


@st.cache_data(ttl=HISTORICAL_DATA_TTL, show_spinner=False)
def load_historical_attributed_email_unsubscribers(api_key: str, revision: str, start: date, end: date, metric_id: str, message_ids: tuple[str, ...], timezone_name: str) -> int:
    return _fetch_attributed_email_unsubscribers(api_key, revision, start, end, metric_id, message_ids, timezone_name)


def load_attributed_email_unsubscribers(api_key: str, revision: str, start: date, end: date, metric_id: str, message_ids: tuple[str, ...], timezone_name: str) -> int:
    loader = load_historical_attributed_email_unsubscribers if end.year < date.today().year else load_live_attributed_email_unsubscribers
    return loader(api_key, revision, start, end, metric_id, message_ids, timezone_name)


@st.cache_data(ttl=HISTORICAL_DATA_TTL, show_spinner=False)
def load_channel_revenue(api_key: str, revision: str, start: date, end: date, order_id: str, received_email_id: str = "", sent_text_id: str = "", activity_metric_ids: tuple[str, ...] = ()) -> dict[str, object]:
    """Load one reporting window and return the metrics needed by YoY overview cards."""
    client, window = KlaviyoClient(api_key, revision), DateWindow(start, end)
    # Klaviyo requires message and parent IDs when grouping these reports. We
    # request the required dimensions, then collapse them locally by channel.
    campaign_groupings = ["campaign_message_id", "campaign_id", "campaign_message_name", "send_channel", "variation", "variation_name"]
    flow_groupings = ["flow_message_id", "flow_id", "flow_name", "send_channel"]
    timezone_name = load_account_timezone(api_key, revision)
    campaigns = client.reporting_values("campaign-values-report", window, order_id, REPORT_STATS, campaign_groupings, timezone_name)
    flows = client.reporting_values("flow-values-report", window, order_id, REPORT_STATS, flow_groupings, timezone_name)
    email_campaign = report_totals(campaigns, "email")["conversion_value"]
    email_flow = report_totals(flows, "email")["conversion_value"]
    email = email_campaign + email_flow
    sms = report_totals(campaigns + flows, "sms")["conversion_value"]
    recipients = 0.0
    for metric_id in (received_email_id, sent_text_id):
        if metric_id:
            _, metric_values = values_from_aggregate(client.aggregate(metric_id, window, ["count"], "day", timezone_name))
            recipients += sum(float(value or 0) for value in metric_values.get("count", []))
    activity_names = ("email_subscribers", "sms_subscribers", "email_unsubscribers", "sms_unsubscribers")
    activity_totals: dict[str, float] = {}
    for name, metric_id in zip(activity_names, activity_metric_ids):
        if not metric_id:
            continue
        _, metric_values = values_from_aggregate(client.aggregate(metric_id, window, ["count"], "day", timezone_name))
        activity_totals[name] = sum(float(value or 0) for value in metric_values.get("count", []))
    email_health = report_totals(campaigns + flows, "email")
    sms_health = report_totals(campaigns + flows, "sms")
    # Match Klaviyo message-performance reporting rather than raw consent-event
    # counts for unsubscribe comparisons.
    activity_totals["email_unsubscribers"] = load_attributed_email_unsubscribers(api_key, revision, start, end, activity_metric_ids[2] if len(activity_metric_ids) > 2 else "", _report_message_ids(campaigns, flows), timezone_name)
    activity_totals["sms_unsubscribers"] = sms_health["unsubscribe_uniques"]
    return {"email": email, "sms": sms, "edm": email + sms, "email_flow": email_flow, "email_campaign": email_campaign, "recipients": recipients, "flows": flows, "email_health": email_health, **activity_totals}


@st.cache_data(ttl=21600, show_spinner=False)
def load_subscriber_inventory(api_key: str, revision: str, email_segment_id: str, sms_segment_id: str) -> dict[str, float]:
    if not email_segment_id or not sms_segment_id:
        return {"email": 0, "sms": 0}
    values = KlaviyoClient(api_key, revision).segment_values([email_segment_id, sms_segment_id])
    return {"email": values.get(email_segment_id, 0), "sms": values.get(sms_segment_id, 0)}


def _fetch_creative_clicks(api_key: str, revision: str, start: date, end: date, clicked_email_id: str) -> dict:
    if not clicked_email_id:
        return {"dates": [], "data": []}
    timezone_name = load_account_timezone(api_key, revision)
    return KlaviyoClient(api_key, revision).aggregate_grouped(clicked_email_id, DateWindow(start, end), ["count", "unique"], ["Message Name", "URL"], "day", timezone_name)


@st.cache_data(ttl=LIVE_DATA_TTL, show_spinner=False)
def load_live_creative_clicks(api_key: str, revision: str, start: date, end: date, clicked_email_id: str) -> dict:
    return _fetch_creative_clicks(api_key, revision, start, end, clicked_email_id)


@st.cache_data(ttl=HISTORICAL_DATA_TTL, show_spinner=False)
def load_historical_creative_clicks(api_key: str, revision: str, start: date, end: date, clicked_email_id: str) -> dict:
    return _fetch_creative_clicks(api_key, revision, start, end, clicked_email_id)


def load_creative_clicks(api_key: str, revision: str, start: date, end: date, clicked_email_id: str) -> dict:
    loader = load_historical_creative_clicks if end.year < date.today().year else load_live_creative_clicks
    return loader(api_key, revision, start, end, clicked_email_id)


class _LinkedAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self.current_href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a":
            self.current_href = values.get("href") or ""
        elif tag == "img":
            self.links.append(
                {
                    "url": self.current_href,
                    "image_url": values.get("src") or "",
                    "label": values.get("alt") or "Campaign image",
                    "width": values.get("width") or "",
                    "height": values.get("height") or "",
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.current_href = ""


def _clean_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    except ValueError:
        return value.strip()


def _image_dimension(value: str) -> int:
    digits = "".join(character for character in str(value) if character.isdigit())
    return int(digits) if digits else 0


def _asset_score(asset: dict[str, str]) -> tuple[int, int]:
    """Prefer the large editorial image over logos, spacers, and tracking pixels."""
    image_url = asset.get("image_url", "").lower()
    width = _image_dimension(asset.get("width", ""))
    height = _image_dimension(asset.get("height", ""))
    penalty = -1 if any(token in image_url for token in ("pixel", "tracking", "spacer", "logo")) else 0
    return penalty, width * max(height, 1)


@st.cache_resource
def campaign_creative_store() -> dict[str, list[dict[str, str]]]:
    """Keep immutable campaign creative metadata for the life of the app."""
    return {}


def load_campaign_creatives(api_key: str, revision: str, messages: tuple[tuple[str, str], ...]) -> dict[str, list[dict[str, str]]]:
    client = KlaviyoClient(api_key, revision)
    cached_assets = campaign_creative_store()
    result: dict[str, list[dict[str, str]]] = {}
    for message_name, message_id in messages:
        # Only positive results are permanent. A template can temporarily be
        # unavailable or the first resolved message can be an empty variation.
        if cached_assets.get(message_id):
            result[message_name] = cached_assets[message_id]
            continue
        try:
            template = client.template_for_campaign_message(message_id)
            parser = _LinkedAssetParser()
            parser.feed(str(template.get("html") or ""))
            assets = sorted(
                (asset for asset in parser.links if asset.get("image_url", "").startswith(("http://", "https://"))),
                key=_asset_score,
                reverse=True,
            )
            if assets:
                cached_assets[message_id] = assets
            result[message_name] = assets
        except (KlaviyoError, AttributeError, TypeError, ValueError):
            # Do not cache transient API errors; the next rerun can try again.
            result[message_name] = []
        time.sleep(.25)
    return result


@st.cache_resource
def sms_preview_store() -> dict[str, dict[str, object]]:
    """Keep sent SMS content indefinitely for the life of the app process."""
    return {}


def load_sms_previews(api_key: str, revision: str, messages: tuple[tuple[str, str], ...]) -> dict[str, dict[str, object]]:
    client = KlaviyoClient(api_key, revision)
    cached_previews = sms_preview_store()
    result: dict[str, dict[str, object]] = {}
    for campaign_name, message_id in messages:
        if message_id in cached_previews:
            result[campaign_name] = cached_previews[message_id]
            continue
        try:
            attributes = client.campaign_message(message_id)
            definition = attributes.get("definition") or {}
            content = definition.get("content") or {}
            render_options = definition.get("render_options") or {}
            preview: dict[str, object] = {
                "body": str(content.get("body") or ""),
                "media_url": str(content.get("media_url") or ""),
                "add_org_prefix": bool(render_options.get("add_org_prefix")),
                "add_opt_out_language": bool(render_options.get("add_opt_out_language")),
            }
            cached_previews[message_id] = preview
            result[campaign_name] = preview
        except (KlaviyoError, AttributeError, TypeError, ValueError):
            # Retry transient failures on the next rerun.
            result[campaign_name] = {}
        time.sleep(.25)
    return result


def load_dashboard(api_key: str, revision: str, start: date, end: date, previous_start: date, previous_end: date, compare: bool = True) -> tuple[dict, dict, dict]:
    if not api_key:
        st.error("Add KLAVIYO_API_KEY to .streamlit/secrets.toml.")
        st.stop()
    try:
        with st.spinner("Loading live data from Klaviyo…"):
            timezone_name = load_account_timezone(api_key, revision)
            metric_items = tuple(sorted(load_metric_ids(api_key, revision).items()))
            order_id = dict(metric_items).get("Placed Order")
            if not order_id:
                raise KlaviyoError("Placed Order metric was not found")
            all_start = min(start, previous_start) if compare else start
            all_end = max(end, previous_end) if compare else end
            # Metric aggregates and Reporting API use separate endpoint quotas,
            # so they can safely run together without increasing either burst.
            with ThreadPoolExecutor(max_workers=2) as executor:
                aggregate_future = executor.submit(load_period_aggregates, api_key, revision, all_start, all_end, METRIC_NAMES, metric_items, timezone_name)
                reports_future = executor.submit(load_reports, api_key, revision, start, end, previous_start, previous_end, order_id, compare, REPORT_CACHE_VERSION, timezone_name)
                combined = aggregate_future.result()
                reports = reports_future.result()
            current = {"metric_ids": combined["metric_ids"], **{name: _slice_metric(combined.get(name, {}), start, end) for name in METRIC_NAMES}}
            previous = {"metric_ids": combined["metric_ids"], **{name: _slice_metric(combined.get(name, {}), previous_start, previous_end) for name in COMPARISON_METRICS}} if compare else {}
            campaign_channels, flow_items = _reporting_metadata_keys(reports)
            reports.update(load_reporting_metadata(api_key, revision, timezone_name, campaign_channels, flow_items))
            reports["account_timezone"] = timezone_name
            email_unsubscribe_metric_id = current["metric_ids"].get("Unsubscribed from Email Marketing", "")
            with ThreadPoolExecutor(max_workers=2) as executor:
                current_unsubs = executor.submit(load_attributed_email_unsubscribers, api_key, revision, start, end, email_unsubscribe_metric_id, _report_message_ids(reports["campaigns"], reports["flows"]), timezone_name)
                previous_unsubs = executor.submit(load_attributed_email_unsubscribers, api_key, revision, previous_start, previous_end, email_unsubscribe_metric_id, _report_message_ids(reports["previous_campaigns"], reports["previous_flows"]), timezone_name) if compare else None
                reports["email_unsubscribe_uniques"] = current_unsubs.result()
                reports["previous_email_unsubscribe_uniques"] = previous_unsubs.result() if previous_unsubs else 0
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
    sums = {k: sum(float(r.get("statistics", {}).get(k) or 0) for r in selected) for k in ["recipients", "delivered", "conversion_value", "conversions", "unsubscribe_uniques"]}
    delivered = sums["delivered"]
    weighted = {k: sum(float(r.get("statistics", {}).get(k) or 0) * float(r.get("statistics", {}).get("delivered") or 0) for r in selected) / delivered if delivered else 0 for k in ["open_rate", "click_rate", "unsubscribe_rate", "bounce_rate", "spam_complaint_rate"]}
    return {**sums, **weighted, "average_order_value": sums["conversion_value"] / sums["conversions"] if sums["conversions"] else 0}


def report_frame(rows: list[dict], names: dict[str, str], id_field: str, channel: str | None = None, limit: int | None = 50, dates: dict[str, str] | None = None) -> pd.DataFrame:
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
    return frame if limit is None else frame.head(limit)


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
