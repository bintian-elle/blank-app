from __future__ import annotations

import streamlit as st

from dashboard.charts import bar_chart, donut_chart
from dashboard.components import date_filters, fmt_money, fmt_num, metric_card, page_header, section, chart_heading
from dashboard.config import API_KEY, REVISION
from dashboard.data import load_dashboard, report_frame, report_totals, table_config
from dashboard.styles import apply_styles

st.set_page_config(page_title="Campaigns", page_icon="✦", layout="wide")
apply_styles(); page_header("Campaign Performance", "Explore email and SMS campaign results")
start, end, ps, pe, mode = date_filters("campaigns")
_, _, reports = load_dashboard(API_KEY, REVISION, start, end, ps, pe, mode != "No comparison")
email = report_totals(reports["campaigns"], "email"); sms = report_totals(reports["campaigns"], "sms")
section("01", "Campaign summary")
cards = [("Total campaign revenue", fmt_money(email["conversion_value"]+sms["conversion_value"])), ("Campaign recipients", fmt_num(email["recipients"]+sms["recipients"])), ("Email open rate", f"{email['open_rate']:.2%}"), ("SMS click rate", f"{sms['click_rate']:.2%}")]
cols = st.columns(4)
for col, item in zip(cols, cards):
    with col: metric_card(item[0], item[1], None)
section("02", "Campaign revenue")
email_df = report_frame(reports["campaigns"], reports["campaign_names"], "campaign_id", "email")
sms_df = report_frame(reports["campaigns"], reports["campaign_names"], "campaign_id", "sms")
c1, c2 = st.columns([2, 1])
with c1:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True); chart_heading("Top campaigns", "Ranked by attributed revenue")
    combined = report_frame(reports["campaigns"], reports["campaign_names"], "campaign_id", limit=10); bar_chart(combined["Name"].tolist(), combined["Revenue"].tolist(), "campaign_bar"); st.markdown('</div>', unsafe_allow_html=True)
with c2:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True); chart_heading("Channel contribution", "Email versus SMS")
    donut_chart({"Email": email["conversion_value"], "SMS": sms["conversion_value"]}, "campaign_donut", 330); st.markdown('</div>', unsafe_allow_html=True)
section("03", "Campaign details")
t1, t2 = st.tabs(["Email campaigns", "SMS campaigns"])
with t1: st.dataframe(email_df, hide_index=True, width="stretch", column_config=table_config())
with t2: st.dataframe(sms_df.drop(columns=["Open rate"]), hide_index=True, width="stretch", column_config=table_config(("Open rate",)))
