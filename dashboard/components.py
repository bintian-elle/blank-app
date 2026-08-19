from __future__ import annotations

from datetime import date, timedelta
from html import escape
import re

import streamlit as st


def fmt_money(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def fmt_num(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def change(current: float, previous: float) -> float | None:
    return None if previous == 0 else (current - previous) / abs(previous) * 100


def metric_card(label: str, value: str, delta: float | None, inverse: bool = False) -> None:
    if delta is None:
        detail = '<span class="delta-flat">— no comparison data</span>'
    else:
        good = delta <= 0 if inverse else delta >= 0
        css = "delta-up" if good else "delta-down"
        arrow = "↑" if delta >= 0 else "↓"
        detail = f'<span class="{css}">{arrow} {abs(delta):.1f}%</span><span class="delta-note">vs comparison</span>'
    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div>{detail}</div>', unsafe_allow_html=True)


def metric_card_delta(label: str, value: str, delta_text: str | None, positive: bool = True) -> None:
    if delta_text is None:
        detail = '<span class="delta-flat">— no comparison data</span>'
    else:
        css = "delta-up" if positive else "delta-down"
        detail = f'<span class="{css}">{delta_text}</span><span class="delta-note">vs comparison</span>'
    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div>{detail}</div>', unsafe_allow_html=True)


def insight_card(label: str, value: str, delta: tuple[str, str] | None, detail: str | None = None, comparison: str | None = None, secondary_delta: tuple[str, str] | None = None) -> None:
    delta_html = ""
    if delta:
        delta_text, delta_class = delta
        delta_html = f'<div class="insight-delta {delta_class}">{delta_text}</div>'
    comparison_html = f'<span class="insight-comparison">{comparison}</span>' if comparison else ""
    secondary_html = ""
    if secondary_delta:
        secondary_text, secondary_class = secondary_delta
        secondary_html = f'<div class="insight-delta secondary {secondary_class}">{secondary_text}</div><span class="insight-comparison">vs Previous Year</span>'
    detail_html = f'<div class="insight-detail">{detail}</div>' if detail else ""
    st.markdown(f'<div class="insight-card"><div class="insight-label">{label}</div><div class="insight-value">{value}</div>{delta_html}{comparison_html}{secondary_html}{detail_html}</div>', unsafe_allow_html=True)


def group_card(title: str, comparison: str, rows: list[tuple[str, str, tuple[str, str]]], icon: str | None = None) -> None:
    body = "".join(f'<div class="group-row"><span>{label}</span><strong>{value}</strong><em class="{css}">{delta}</em></div>' for label, value, (delta, css) in rows)
    icons = {
        "email": '<span class="group-icon email-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4.5 7 7.5 6 7.5-6"/></svg></span>',
        "sms": '<span class="group-icon sms-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5.5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-8l-5 3v-3H5a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2Z"/><path d="M7.5 11.5h9"/></svg></span>',
    }
    icon_html = icons.get(icon or "", "")
    st.markdown(f'<div class="group-card"><div class="group-title">{icon_html}{title}</div><div class="group-head"><span>Metric</span><span>Value</span><span>{comparison}</span></div>{body}</div>', unsafe_allow_html=True)


def detail_cards(cards: list[tuple], columns: int = 1, key: str = "detail") -> None:
    """Render compact record cards while retaining every supplied metric."""
    if not cards:
        return
    rendered_cards = []
    for index, card in enumerate(cards):
        title, metrics = card[0], card[1]
        image_url = str(card[2]) if len(card) > 2 and card[2] else ""
        modal_id = f"{key}-campaign-preview-{index}"
        if image_url == "__loading__":
            thumbnail = '<div class="campaign-thumb campaign-thumb-loading"><span>Loading…</span></div>'
            modal = ""
        elif image_url:
            safe_image = escape(image_url, quote=True)
            thumbnail = (
                f'<a class="campaign-thumb-link" href="#{modal_id}" aria-label="Open image preview for {escape(str(title), quote=True)}">'
                f'<img class="campaign-thumb" src="{safe_image}" alt="{escape(str(title), quote=True)}"></a>'
            )
            modal = (
                f'<div id="{modal_id}" class="campaign-lightbox"><a class="campaign-lightbox-backdrop" href="#{key}-campaign-previews" aria-label="Close preview"></a>'
                f'<div class="campaign-lightbox-dialog"><a class="campaign-lightbox-close" href="#{key}-campaign-previews" aria-label="Close preview">&times;</a>'
                f'<img src="{safe_image}" alt="{escape(str(title), quote=True)}"><div>{escape(str(title))}</div></div></div>'
            )
        else:
            thumbnail = '<div class="campaign-thumb campaign-thumb-empty" aria-hidden="true">▧</div>'
            modal = ""
        metric_html = "".join(
            f'<div class="detail-metric"><span>{escape(str(label))}</span><strong class="{css}">{escape(str(value))}</strong></div>'
            for label, value, css in metrics
        )
        rendered_cards.append(
            f'<div class="detail-card"><div class="detail-card-heading">{thumbnail}'
            f'<div class="detail-title" title="{escape(str(title), quote=True)}">{escape(str(title))}</div></div>'
            f'<div class="detail-metrics">{metric_html}</div></div>{modal}'
        )
    body = "".join(rendered_cards)
    css_class = " detail-card-grid" if columns == 2 else ""
    st.markdown(f'<div id="{key}-campaign-previews" class="detail-card-list{css_class}">{body}</div>', unsafe_allow_html=True)


def _sms_body_html(preview: dict[str, object]) -> str:
    body = str(preview.get("body") or "").strip()
    if preview.get("add_org_prefix") and not body.lower().startswith("bluevua"):
        body = f"Bluevua Water: {body}"
    escaped = escape(body)
    linked = re.sub(
        r"(https?://[^\s<]+)",
        lambda match: f'<a href="{escape(match.group(1), quote=True)}" target="_blank" rel="noopener">{match.group(1)}</a>',
        escaped,
    )
    if preview.get("add_opt_out_language"):
        linked += "<br><br>Reply STOP to opt-out"
    return linked.replace("\n", "<br>")


def sms_campaign_cards(cards: list[tuple], previews: dict[str, dict[str, object]], columns: int = 2, key: str = "sms") -> None:
    """Render SMS metrics with a generated phone preview from Klaviyo message content."""
    rendered_cards = []
    for index, (title, metrics, *_rest) in enumerate(cards):
        preview = previews.get(str(title), {})
        modal_id = f"{key}-phone-preview-{index}"
        if preview.get("loading"):
            thumbnail = '<div class="campaign-thumb campaign-thumb-loading"><span>Loading…</span></div>'
            modal = ""
        elif preview.get("body"):
            media_url = str(preview.get("media_url") or "")
            media_html = f'<img class="sms-media" src="{escape(media_url, quote=True)}" alt="MMS creative">' if media_url.startswith(("http://", "https://")) else ""
            thumbnail = (
                f'<a class="sms-phone-thumb-link" href="#{modal_id}" aria-label="Open SMS preview for {escape(str(title), quote=True)}">'
                '<div class="sms-phone-thumb"><i></i><span></span><span></span><span></span></div></a>'
            )
            modal = (
                f'<div id="{modal_id}" class="campaign-lightbox sms-lightbox"><a class="campaign-lightbox-backdrop" href="#{key}-campaign-previews" aria-label="Close preview"></a>'
                f'<div class="sms-preview-dialog"><a class="campaign-lightbox-close" href="#{key}-campaign-previews" aria-label="Close preview">&times;</a>'
                '<div class="sms-phone"><div class="sms-phone-top"><i></i></div><div class="sms-contact"><b></b><span>Bluevua Water</span></div>'
                f'<div class="sms-conversation"><div class="sms-bubble">{media_html}{_sms_body_html(preview)}</div></div>'
                '<div class="sms-phone-bottom"><i></i><i></i><span></span></div></div>'
                f'<div class="sms-preview-title">{escape(str(title))}</div></div></div>'
            )
        else:
            thumbnail = '<div class="campaign-thumb campaign-thumb-empty" aria-hidden="true">▧</div>'
            modal = ""
        metric_html = "".join(
            f'<div class="detail-metric"><span>{escape(str(label))}</span><strong class="{css}">{escape(str(value))}</strong></div>'
            for label, value, css in metrics
        )
        rendered_cards.append(
            f'<div class="detail-card"><div class="detail-card-heading">{thumbnail}'
            f'<div class="detail-title" title="{escape(str(title), quote=True)}">{escape(str(title))}</div></div>'
            f'<div class="detail-metrics">{metric_html}</div></div>{modal}'
        )
    css_class = " detail-card-grid" if columns == 2 else ""
    st.markdown(f'<div id="{key}-campaign-previews" class="detail-card-list{css_class}">{"".join(rendered_cards)}</div>', unsafe_allow_html=True)


def activity_card(label: str, value: str, delta: tuple[str, str], rate: str, rate_delta: tuple[str, str], comparison: str, secondary_delta: tuple[str, str], rate_secondary_delta: tuple[str, str]) -> None:
    delta_text, delta_css = delta
    rate_delta_text, rate_delta_css = rate_delta
    secondary_text, secondary_css = secondary_delta
    rate_secondary_text, rate_secondary_css = rate_secondary_delta
    st.markdown(
        f'<div class="activity-card"><div class="activity-label">{label}</div>'
        f'<div class="activity-value">{value}</div><div class="activity-delta {delta_css}">{delta_text}</div>'
        f'<span class="insight-comparison">{comparison}</span><div class="activity-delta secondary {secondary_css}">{secondary_text}</div>'
        f'<span class="insight-comparison">vs Previous Year</span>'
        f'<div class="activity-rate-label">Rate</div><div class="activity-rate">{rate}</div>'
        f'<div class="activity-delta {rate_delta_css}">{rate_delta_text}</div><span class="insight-comparison">{comparison}</span>'
        f'<div class="activity-delta secondary {rate_secondary_css}">{rate_secondary_text}</div><span class="insight-comparison">vs Previous Year</span></div>',
        unsafe_allow_html=True,
    )


def ab_test_card(title: str, variants: list[dict[str, str]], winner: str, winning_rate: str, lift: str) -> None:
    rows = "".join(
        f'<div class="ab-row"><strong>{escape(str(row["variant"]))}</strong><span>{escape(row["open_rate"])}</span>'
        f'<span>{escape(row["click_rate"])}</span><span>{escape(row["revenue"])}</span><span>{escape(row["aov"])}</span></div>'
        for row in variants
    )
    st.markdown(
        f'<div class="ab-card"><div class="ab-title">{escape(title)}</div>'
        f'<div class="ab-head"><span>Variation</span><span>Open Rate</span><span>Click Rate</span><span>Revenue</span><span>Average Order Value</span></div>'
        f'{rows}<div class="ab-winner"><span class="winner-trophy">♕</span><strong>Winner: {escape(winner)}</strong>'
        f'<small>by Open Rate</small><span class="winner-stat">Winning Open Rate <b>{escape(winning_rate)}</b></span>'
        f'<span class="winner-stat">Open Rate Lift <b>{escape(lift)}</b></span></div></div>',
        unsafe_allow_html=True,
    )


def _table_campaign_preview(title: str, image_url: str, modal_id: str, subtitle: str = "") -> tuple[str, str]:
    title_html = f'<strong>{escape(title)}</strong>'
    if subtitle:
        title_html += f'<span>{escape(subtitle)}</span>'
    if not image_url:
        return f'<div class="table-campaign"><div class="campaign-thumb campaign-thumb-empty">▧</div><div>{title_html}</div></div>', ""
    safe_image = escape(image_url, quote=True)
    preview = (
        f'<a class="campaign-thumb-link" href="#{modal_id}" aria-label="Open image preview for {escape(title, quote=True)}">'
        f'<img class="campaign-thumb" src="{safe_image}" alt="{escape(title, quote=True)}"></a>'
    )
    modal = (
        f'<div id="{modal_id}" class="campaign-lightbox"><a class="campaign-lightbox-backdrop" href="#creative-tables" aria-label="Close preview"></a>'
        f'<div class="campaign-lightbox-dialog"><a class="campaign-lightbox-close" href="#creative-tables" aria-label="Close preview">&times;</a>'
        f'<img src="{safe_image}" alt="{escape(title, quote=True)}"><div>{escape(title)}</div></div></div>'
    )
    return f'<div class="table-campaign">{preview}<div>{title_html}</div></div>', modal


def module_performance_table(campaigns: list[tuple[str, str, list[tuple[str, str]], str]]) -> None:
    max_modules = max((len(modules) for _, _, modules, _ in campaigns), default=0)
    head = "".join(f"<th>Module {index + 1}</th>" for index in range(max_modules))
    rows = ""
    modals = ""
    for index, (campaign, sent_date, modules, image_url) in enumerate(campaigns):
        cells = "".join(f'<td><strong>{escape(rate)}</strong><a href="{escape(url, quote=True)}" target="_blank" rel="noopener">{escape(url)}</a></td>' for url, rate in modules)
        cells += "<td>—</td>" * (max_modules - len(modules))
        campaign_cell, modal = _table_campaign_preview(campaign, image_url, f"module-campaign-preview-{index}", f"Sent {sent_date}")
        rows += f'<tr><th>{campaign_cell}</th>{cells}</tr>'
        modals += modal
    st.markdown(f'<div id="creative-tables" class="module-table-wrap"><table class="module-table"><thead><tr><th>Campaign</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>{modals}', unsafe_allow_html=True)


def top_creative_table(rows: list[dict[str, str]]) -> None:
    body = ""
    modals = ""
    for index, row in enumerate(rows):
        campaign_cell, modal = _table_campaign_preview(row["campaign"], row.get("image", ""), f"top-creative-preview-{index}", row["module"])
        body += (
            f'<tr><td>{campaign_cell}</td>'
            f'<td><a href="{escape(row["url"], quote=True)}" target="_blank" rel="noopener" title="{escape(row["url"], quote=True)}">{escape(row["url"])}</a></td>'
            f'<td>{escape(row["clicks"])}</td><td class="top-rate">{escape(row["rate"])}</td></tr>'
        )
        modals += modal
    st.markdown(f'<div class="module-table-wrap"><table class="top-creative-table"><thead><tr><th>Creative</th><th>URL</th><th>Unique Clicks</th><th>Click Rate</th></tr></thead><tbody>{body}</tbody></table></div>{modals}', unsafe_allow_html=True)


def comparison_label(mode: str) -> str:
    return {"Previous period": "vs Previous Period %", "Previous year": "YoY %", "Custom": "vs Custom Period %"}.get(mode, "Change %")


def percent_change_text(current: float, previous: float) -> tuple[str, str]:
    if previous == 0:
        return ("No change", "neutral") if current == 0 else ("From 0", "neutral")
    value = (current - previous) / abs(previous) * 100
    return f"{value:+.1f}%", "positive" if value >= 0 else "negative"


def pp_change_text(current: float, previous: float, lower_is_better: bool = False) -> tuple[str, str]:
    value = (current - previous) * 100
    good = value <= 0 if lower_is_better else value >= 0
    return f"{value:+.2f} pp", "positive" if good else "negative"


def metric_table(headers: list[str], rows: list[tuple[str, list[tuple[str, str]]]], submetrics: set[str] | None = None) -> None:
    submetrics = submetrics or set()
    head = "".join(f"<th>{item}</th>" for item in headers)
    body = ""
    for label, cells in rows:
        label_class = ' class="submetric"' if label in submetrics else ""
        values = "".join(f'<td class="{css}">{value}</td>' for value, css in cells)
        body += f"<tr><td{label_class}>{label}</td>{values}</tr>"
    st.markdown(f'<table class="metric-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>', unsafe_allow_html=True)


def section(icon: str, title: str) -> None:
    st.markdown(f'<div class="section-title"><span class="section-icon">{icon}</span>{title}</div>', unsafe_allow_html=True)


def page_header(title: str, subtitle: str) -> None:
    left, right = st.columns([3, 1], vertical_alignment="center")
    with left:
        st.markdown('<div class="brand-kicker">BLUEVUA · KLAVIYO ANALYTICS</div>', unsafe_allow_html=True)
        st.title(title)
        st.caption(subtitle)
    with right:
        st.markdown('<div style="text-align:right"><span class="status"><i class="dot"></i>Live data</span></div>', unsafe_allow_html=True)


def _swap_date_windows(key: str) -> None:
    """Swap the active and comparison windows before Streamlit reruns the page."""
    current = st.session_state.get(f"{key}_active_window")
    comparison = st.session_state.get(f"{key}_comparison_window")
    if current and comparison:
        st.session_state[f"{key}_period"] = "Custom"
        st.session_state[f"{key}_dates"] = tuple(comparison)
        st.session_state[f"{key}_dates_draft"] = tuple(comparison)
        st.session_state[f"{key}_compare"] = "Custom"
        st.session_state[f"{key}_compare_dates"] = tuple(current)
        st.session_state[f"{key}_compare_dates_draft"] = tuple(current)


def date_filters(key: str = "global") -> tuple[date, date, date, date, str]:
    today = date.today()
    date_key = f"{key}_dates"
    mode_key = f"{key}_compare"
    period_key = f"{key}_period"
    compare_date_key = f"{key}_compare_dates"
    date_draft_key = f"{key}_dates_draft"
    compare_draft_key = f"{key}_compare_dates_draft"
    period_popover_version_key = f"{key}_period_popover_version"
    compare_popover_version_key = f"{key}_compare_popover_version"
    period_options = ["Week-to-date", "Month-to-date", "Year-to-date", "Last 7 days", "Last 30 days", "Last 90 days", "Last month", "Last 3 months", "Last 12 months", "Last year", "Custom"]

    def month_start(value: date, offset: int = 0) -> date:
        month_index = value.year * 12 + value.month - 1 + offset
        return date(month_index // 12, month_index % 12 + 1, 1)

    def resolve_active(period_name: str) -> tuple[date, date]:
        if period_name == "Custom":
            value = st.session_state.get(date_key, (today - timedelta(days=30), today))
            return tuple(value) if isinstance(value, (tuple, list)) and len(value) == 2 else (today - timedelta(days=30), today)
        if period_name == "Week-to-date": return today - timedelta(days=today.weekday()), today
        if period_name == "Month-to-date": return today.replace(day=1), today
        if period_name == "Year-to-date": return today.replace(month=1, day=1), today
        if period_name == "Last 7 days": return today - timedelta(days=7), today
        if period_name == "Last 30 days": return today - timedelta(days=30), today
        if period_name == "Last 90 days": return today - timedelta(days=90), today
        if period_name == "Last month":
            end = month_start(today) - timedelta(days=1)
            return end.replace(day=1), end
        if period_name == "Last 3 months": return month_start(today, -2), today
        if period_name == "Last 12 months":
            end = month_start(today) - timedelta(days=1)
            return month_start(today, -12), end
        if period_name == "Last year": return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        return today - timedelta(days=30), today

    preview_period = st.session_state.get(period_key, "Last 30 days")
    preview_start, preview_end = resolve_active(preview_period)
    preview_mode = st.session_state.get(mode_key, "Previous period")
    preview_days = (preview_end - preview_start).days + 1
    if preview_mode == "Custom":
        preview_custom = st.session_state.get(compare_date_key, (preview_start - timedelta(days=preview_days), preview_start - timedelta(days=1)))
        preview_previous_start, preview_previous_end = tuple(preview_custom)
    elif preview_mode == "Previous year":
        try:
            preview_previous_start, preview_previous_end = preview_start.replace(year=preview_start.year - 1), preview_end.replace(year=preview_end.year - 1)
        except ValueError:
            preview_previous_start, preview_previous_end = preview_start - timedelta(days=365), preview_end - timedelta(days=365)
    else:
        preview_previous_end = preview_start - timedelta(days=1)
        preview_previous_start = preview_previous_end - timedelta(days=preview_days - 1)

    left_space, c1, swap_col, c2, right_space = st.columns([.32, 1, .16, 1, .32], vertical_alignment="top")
    with c1:
        period_args = {"label": f"Time period (**{preview_start:%b %d, %Y} – {preview_end:%b %d, %Y}**)", "options": period_options, "key": period_key}
        if period_key not in st.session_state:
            period_args["index"] = 4
        period = st.selectbox(**period_args)
        if period == "Custom":
            if date_key not in st.session_state:
                st.session_state[date_key] = (today - timedelta(days=30), today)
            if date_draft_key not in st.session_state:
                st.session_state[date_draft_key] = tuple(st.session_state[date_key])
            period_popover_version = int(st.session_state.get(period_popover_version_key, 0))
            with st.popover("📅 Set custom time period", width="stretch", key=f"{key}_period_popover_{period_popover_version}"):
                st.caption("Type dates directly or choose them from the calendar.")
                with st.form(f"{key}_period_form", border=False):
                    st.date_input("Custom time period", max_value=today, format="YYYY-MM-DD", key=date_draft_key, label_visibility="collapsed")
                    apply_period = st.form_submit_button("Apply time period", type="primary", width="stretch")
                if apply_period:
                    draft = st.session_state.get(date_draft_key)
                    if isinstance(draft, tuple) and len(draft) == 2:
                        st.session_state[date_key] = tuple(draft)
                        st.session_state[period_popover_version_key] = period_popover_version + 1
                        st.rerun()
            selected = st.session_state[date_key]
        else:
            selected = resolve_active(period)
    with swap_col:
        st.markdown('<div class="swap-button-wrap"></div>', unsafe_allow_html=True)
        st.button(
            "⇄",
            key=f"{key}_swap",
            help="Swap Date range and Compare with",
            on_click=_swap_date_windows,
            args=(key,),
            width="stretch",
        )
    with c2:
        compare_args = {"label": f"Compare with (**{preview_previous_start:%b %d, %Y} – {preview_previous_end:%b %d, %Y}**)", "options": ["Previous period", "Previous year", "Custom"], "key": mode_key}
        mode = st.selectbox(**compare_args)
        custom_comparison = None
        if mode == "Custom":
            if compare_date_key not in st.session_state:
                st.session_state[compare_date_key] = (today - timedelta(days=59), today - timedelta(days=30))
            if compare_draft_key not in st.session_state:
                st.session_state[compare_draft_key] = tuple(st.session_state[compare_date_key])
            compare_popover_version = int(st.session_state.get(compare_popover_version_key, 0))
            with st.popover("📅 Set custom comparison", width="stretch", key=f"{key}_compare_popover_{compare_popover_version}"):
                st.caption("Type dates directly or choose them from the calendar.")
                with st.form(f"{key}_comparison_form", border=False):
                    st.date_input("Custom comparison period", max_value=today, format="YYYY-MM-DD", key=compare_draft_key, label_visibility="collapsed")
                    apply_comparison = st.form_submit_button("Apply comparison", type="primary", width="stretch")
                if apply_comparison:
                    draft = st.session_state.get(compare_draft_key)
                    if isinstance(draft, tuple) and len(draft) == 2:
                        st.session_state[compare_date_key] = tuple(draft)
                        st.session_state[compare_popover_version_key] = compare_popover_version + 1
                        st.rerun()
            custom_comparison = st.session_state[compare_date_key]
    if not isinstance(selected, tuple) or len(selected) != 2:
        st.info("Please select both a start and end date.")
        st.stop()
    start, end = selected
    days = (end - start).days + 1
    if days > 365:
        st.error("Klaviyo supports a maximum reporting range of 365 days.")
        st.stop()
    if mode == "Custom":
        if not isinstance(custom_comparison, tuple) or len(custom_comparison) != 2:
            st.info("Please select both dates for the custom comparison period.")
            st.stop()
        previous_start, previous_end = custom_comparison
    elif mode == "Previous year":
        try:
            previous_start, previous_end = start.replace(year=start.year - 1), end.replace(year=end.year - 1)
        except ValueError:
            previous_start, previous_end = start - timedelta(days=365), end - timedelta(days=365)
    else:
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=days - 1)

    st.session_state[f"{key}_active_window"] = (start, end)
    st.session_state[f"{key}_comparison_window"] = (previous_start, previous_end)
    return start, end, previous_start, previous_end, mode


def chart_heading(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="chart-title">{title}</div><div class="chart-subtitle">{subtitle}</div>', unsafe_allow_html=True)
