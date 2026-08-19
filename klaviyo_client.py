from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import re
import time as time_module
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class KlaviyoError(RuntimeError):
    pass


@dataclass(frozen=True)
class DateWindow:
    start: date
    end: date

    @staticmethod
    def _timezone(timezone_name: str) -> ZoneInfo | timezone:
        try:
            return ZoneInfo(timezone_name)
        except Exception:
            return timezone.utc

    def api_timeframe(self, timezone_name: str = "UTC") -> dict[str, str]:
        account_tz = self._timezone(timezone_name)
        start_dt = datetime.combine(self.start, time.min, account_tz).astimezone(timezone.utc)
        end_dt = datetime.combine(self.end + timedelta(days=1), time.min, account_tz).astimezone(timezone.utc)
        return {"start": start_dt.isoformat(), "end": end_dt.isoformat()}

    def aggregate_filters(self, timezone_name: str = "UTC") -> list[str]:
        account_tz = self._timezone(timezone_name)
        start_dt = datetime.combine(self.start, time.min, account_tz).astimezone(timezone.utc)
        # less-than is exclusive, so use local midnight after the selected end date.
        end_dt = datetime.combine(self.end + timedelta(days=1), time.min, account_tz).astimezone(timezone.utc)
        return [
            f"greater-or-equal(datetime,{start_dt.isoformat().replace('+00:00', 'Z')})",
            f"less-than(datetime,{end_dt.isoformat().replace('+00:00', 'Z')})",
        ]


class KlaviyoClient:
    BASE_URL = "https://a.klaviyo.com/api"

    def __init__(self, api_key: str, revision: str = "2026-07-15") -> None:
        if not api_key:
            raise KlaviyoError("KLAVIYO_API_KEY is not configured")
        self.api_key = api_key
        self.revision = revision

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        if params:
            url += "?" + urlencode(params, doseq=True)
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Klaviyo-API-Key {self.api_key}",
                "revision": self.revision,
                "accept": "application/vnd.api+json",
                "content-type": "application/vnd.api+json",
                "User-Agent": "Bluevua-Klaviyo-Dashboard/1.0",
            },
        )
        for attempt in range(6):
            try:
                with urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode())
            except HTTPError as exc:
                detail = f"HTTP {exc.code}"
                error_text = ""
                try:
                    error_text = exc.read().decode()
                    error_doc = json.loads(error_text)
                    errors = error_doc.get("errors", [])
                    if errors:
                        detail += f": {errors[0].get('detail') or errors[0].get('title')}"
                except Exception:
                    pass
                if exc.code in (429, 503) and attempt < 5:
                    retry_after = float(exc.headers.get("Retry-After", "0") or 0)
                    # Klaviyo sometimes puts the reset delay only in the JSON detail.
                    delay_match = re.search(r"(?:available in|retry after)\s+(\d+(?:\.\d+)?)\s*seconds?", detail, re.I)
                    server_delay = float(delay_match.group(1)) if delay_match else 0
                    time_module.sleep(max(retry_after, server_delay + .5, min(2 ** attempt, 15)))
                    continue
                raise KlaviyoError(detail) from exc
            except (URLError, TimeoutError) as exc:
                raise KlaviyoError(f"Network error: {exc}") from exc
        raise KlaviyoError("Klaviyo request failed after retries")

    def get_all(self, path: str, params: dict[str, Any] | None = None, max_pages: int = 20) -> list[dict[str, Any]]:
        document = self._request("GET", path, params=params)
        rows = list(document.get("data", []))
        pages = 1
        next_url = document.get("links", {}).get("next")
        while next_url and pages < max_pages:
            request = Request(
                next_url,
                headers={
                    "Authorization": f"Klaviyo-API-Key {self.api_key}",
                    "revision": self.revision,
                    "accept": "application/vnd.api+json",
                    "User-Agent": "Bluevua-Klaviyo-Dashboard/1.0",
                },
            )
            try:
                with urlopen(request, timeout=30) as response:
                    document = json.loads(response.read().decode())
            except HTTPError as exc:
                raise KlaviyoError(f"HTTP {exc.code} while paginating {path}") from exc
            rows.extend(document.get("data", []))
            next_url = document.get("links", {}).get("next")
            pages += 1
        return rows

    def metrics(self) -> dict[str, str]:
        rows = self.get_all("metrics/")
        # Prefer the first matching metric. Names are unique for Klaviyo native events,
        # while commerce integrations can expose multiple similarly named metrics.
        return {row.get("attributes", {}).get("name", ""): row.get("id", "") for row in rows}

    def account_timezone(self) -> str:
        document = self._request("GET", "accounts/")
        rows = document.get("data") or []
        if not rows:
            return "UTC"
        return str((rows[0].get("attributes") or {}).get("timezone") or "UTC")

    def attributed_unsubscribe_profiles(self, metric_id: str, window: DateWindow, message_ids: tuple[str, ...], timezone_name: str) -> int:
        """Count unique unsubscribe profiles attributed to messages in the report."""
        if not metric_id or not message_ids:
            return 0
        try:
            account_tz = ZoneInfo(timezone_name)
        except Exception:
            account_tz = timezone.utc
        start_dt = datetime.combine(window.start, time.min, account_tz).astimezone(timezone.utc)
        end_dt = datetime.combine(window.end + timedelta(days=1), time.min, account_tz).astimezone(timezone.utc)
        event_filter = (
            f'and(equals(metric_id,"{metric_id}"),'
            f'greater-or-equal(datetime,{start_dt.isoformat().replace("+00:00", "Z")}),'
            f'less-than(datetime,{end_dt.isoformat().replace("+00:00", "Z")}))'
        )
        rows = self.get_all("events/", params={"filter": event_filter, "page[size]": 100}, max_pages=50)
        allowed = set(message_ids)
        profiles = set()
        for row in rows:
            properties = (row.get("attributes") or {}).get("event_properties") or {}
            if str(properties.get("method_detail") or "") not in allowed:
                continue
            profile = (row.get("relationships") or {}).get("profile", {}).get("data") or {}
            profile_id = str(profile.get("id") or "")
            if profile_id:
                profiles.add(profile_id)
        return len(profiles)

    def aggregate(
        self,
        metric_id: str,
        window: DateWindow,
        measurements: list[str],
        interval: str = "day",
        timezone_name: str = "UTC",
    ) -> dict[str, Any]:
        payload = {
            "data": {
                "type": "metric-aggregate",
                "attributes": {
                    "metric_id": metric_id,
                    "measurements": measurements,
                    "filter": window.aggregate_filters(timezone_name),
                    "interval": interval,
                    "timezone": timezone_name,
                    "page_size": 500,
                },
            }
        }
        return self._request("POST", "metric-aggregates/", payload=payload).get("data", {}).get("attributes", {})

    def aggregate_grouped(
        self,
        metric_id: str,
        window: DateWindow,
        measurements: list[str],
        by: list[str],
        interval: str = "day",
        timezone_name: str = "UTC",
    ) -> dict[str, Any]:
        payload = {
            "data": {
                "type": "metric-aggregate",
                "attributes": {
                    "metric_id": metric_id,
                    "measurements": measurements,
                    "filter": window.aggregate_filters(timezone_name),
                    "by": by,
                    "interval": interval,
                    "timezone": timezone_name,
                    "page_size": 500,
                },
            }
        }
        return self._request("POST", "metric-aggregates/", payload=payload).get("data", {}).get("attributes", {})

    def reporting_values(
        self,
        report_type: str,
        window: DateWindow,
        conversion_metric_id: str,
        statistics: list[str],
        group_by: list[str],
        timezone_name: str = "UTC",
    ) -> list[dict[str, Any]]:
        payload = {
            "data": {
                "type": report_type,
                "attributes": {
                    "timeframe": window.api_timeframe(timezone_name),
                    "conversion_metric_id": conversion_metric_id,
                    "statistics": statistics,
                    "group_by": group_by,
                },
            }
        }
        endpoint = "campaign-values-reports/" if report_type == "campaign-values-report" else "flow-values-reports/"
        document = self._request("POST", endpoint, payload=payload)
        return document.get("data", {}).get("attributes", {}).get("results", [])

    def segment_values(self, segment_ids: list[str]) -> dict[str, float]:
        payload = {
            "data": {
                "type": "segment-values-report",
                "attributes": {
                    "statistics": ["total_members"],
                    "timeframe": {"key": "today"},
                    "filter": f'any(segment_id,[{",".join(json.dumps(value) for value in segment_ids)}])',
                },
            }
        }
        document = self._request("POST", "segment-values-reports/", payload=payload)
        results = document.get("data", {}).get("attributes", {}).get("results", [])
        return {row.get("groupings", {}).get("segment_id", ""): float(row.get("statistics", {}).get("total_members") or 0) for row in results}

    def campaign_details(self, channel: str, timezone_name: str = "UTC") -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        rows = self.get_all(
            "campaigns/",
            params={"filter": f'equals(messages.channel,"{channel}")', "include": "campaign-messages", "page[size]": 50},
        )
        names = {row.get("id", ""): row.get("attributes", {}).get("name", "Unnamed campaign") for row in rows}
        dates = {}
        message_ids = {}
        for row in rows:
            attributes = row.get("attributes", {})
            sent_at = attributes.get("send_time") or attributes.get("scheduled_at")
            campaign_id = row.get("id", "")
            try:
                sent_date = datetime.fromisoformat(str(sent_at).replace("Z", "+00:00")).astimezone(DateWindow._timezone(timezone_name)).date().isoformat()
            except (TypeError, ValueError):
                sent_date = str(sent_at or "")[:10]
            dates[campaign_id] = sent_date
            related_messages = row.get("relationships", {}).get("campaign-messages", {}).get("data", []) or []
            if related_messages:
                message_ids[campaign_id] = str(related_messages[0].get("id") or "")
        return names, dates, message_ids

    def campaigns(self, channel: str) -> dict[str, str]:
        names, _, _ = self.campaign_details(channel)
        return names

    def template_for_campaign_message(self, message_id: str) -> dict[str, Any]:
        """Return the template attached to a campaign message, including content."""
        document = self._request(
            "GET",
            f"campaign-messages/{message_id}/template/",
            params={"fields[template]": "name,editor_type,html,text"},
        )
        # Klaviyo returns JSON:API `data: null` for messages without an
        # attached template (for example some SMS/MMS or draft messages).
        data = document.get("data") or {}
        return data.get("attributes") or {}

    def campaign_message(self, message_id: str) -> dict[str, Any]:
        """Return campaign-message attributes, including SMS definition/content."""
        document = self._request("GET", f"campaign-messages/{message_id}/")
        data = document.get("data") or {}
        return data.get("attributes") or {}

    def flows(self) -> dict[str, str]:
        rows = self.get_all("flows/", params={"page[size]": 50})
        return {row.get("id", ""): row.get("attributes", {}).get("name", "Unnamed flow") for row in rows}


def values_from_aggregate(attributes: dict[str, Any]) -> tuple[list[str], dict[str, list[float]]]:
    """Normalize Klaviyo metric-aggregate output into dates and measurement arrays."""
    dates = attributes.get("dates", []) or []
    data = attributes.get("data", []) or []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        # With no `by` grouping, Klaviyo returns one group containing measurements.
        measurements = data[0].get("measurements", data[0])
    elif isinstance(data, dict):
        measurements = data.get("measurements", data)
    else:
        measurements = {}
    normalized: dict[str, list[float]] = {}
    for key, value in measurements.items() if isinstance(measurements, dict) else []:
        if isinstance(value, list):
            normalized[key] = [float(item or 0) for item in value]
    return dates, normalized
