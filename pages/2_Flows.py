from __future__ import annotations

import streamlit as st

from dashboard.charts import bar_chart, donut_chart
from dashboard.components import date_filters, fmt_money, fmt_num, metric_card, page_header, section, chart_heading
from dashboard.config import API_KEY, REVISION
from dashboard.data import load_dashboard, report_frame, report_totals, table_config
from dashboard.styles import apply_styles

st.set_page_config(page_title="Flows", page_icon="↗", layout="wide")
apply_styles(); page_header("Flow Performance", "Monitor automated lifecycle messaging")
start, end, ps, pe, mode = date_filters("flows")
_, _, reports = load_dashboard(API_KEY, REVISION, start, end, ps, pe, mode != "No comparison")
totals = report_totals(reports["flows"]); email = report_totals(reports["flows"], "email"); sms = report_totals(reports["flows"], "sms")
section("01", "Automation summary")
cards = [("Flow revenue", fmt_money(totals["conversion_value"])), ("Flow recipients", fmt_num(totals["recipients"])), ("Orders", fmt_num(totals["conversions"])), ("Average order value", fmt_money(totals["average_order_value"]))]
cols = st.columns(4)
for col, item in zip(cols, cards):
    with col: metric_card(item[0], item[1], None)
flow_df = report_frame(reports["flows"], reports["flow_names"], "flow_id")
section("02", "Flow revenue")
c1, c2 = st.columns([2, 1])
with c1:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True); chart_heading("Top automated flows", "Ranked by attributed revenue")
    bar_chart(flow_df["Name"].head(10).tolist(), flow_df["Revenue"].head(10).tolist(), "flow_bar"); st.markdown('</div>', unsafe_allow_html=True)
with c2:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True); chart_heading("Channel contribution", "Email versus SMS automation")
    donut_chart({"Email": email["conversion_value"], "SMS": sms["conversion_value"]}, "flow_donut", 330); st.markdown('</div>', unsafe_allow_html=True)
section("03", "Flow details")
st.dataframe(flow_df, hide_index=True, width="stretch", column_config=table_config())
