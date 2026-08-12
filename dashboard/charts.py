from __future__ import annotations

from typing import Sequence

from streamlit_echarts import st_echarts


PALETTE = ["#6c5ce7", "#16b784", "#ff9f43", "#ef5b67", "#3b82f6"]


def line_chart(
    dates: Sequence,
    series: dict[str, Sequence],
    key: str,
    height: int = 290,
    area: bool = False,
    y_suffix: str = "",
    colors: Sequence[str] | None = None,
    show_symbols: bool = True,
) -> None:
    options = {
        "color": list(colors) if colors else PALETTE,
        "tooltip": {"trigger": "axis", "backgroundColor": "rgba(25,29,47,.94)", "borderWidth": 0, "textStyle": {"color": "#fff"}},
        "legend": {"top": 4, "right": 8, "icon": "circle", "itemWidth": 8, "textStyle": {"color": "#778196", "fontSize": 11}},
        "grid": {"left": 15, "right": 18, "top": 42, "bottom": 12, "containLabel": True},
        "xAxis": {"type": "category", "boundaryGap": False, "data": [str(item)[:10] for item in dates], "axisLine": {"lineStyle": {"color": "#e7ebf2"}}, "axisLabel": {"color": "#8d96a7", "fontSize": 10}},
        "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": "#eef1f6"}}, "axisLabel": {"color": "#8d96a7", "fontSize": 10, "formatter": f"{{value}}{y_suffix}"}},
        "series": [{"name": name, "type": "line", "smooth": False, "symbol": "circle", "symbolSize": 7, "showSymbol": show_symbols, "lineStyle": {"width": 2.5}, "areaStyle": {"opacity": .08} if area else None, "data": [round(float(v or 0), 3) for v in values]} for name, values in series.items()],
    }
    st_echarts(options=options, height=f"{height}px", key=key)


def donut_chart(data: dict[str, float], key: str, height: int = 260) -> None:
    options = {
        "color": PALETTE,
        "tooltip": {"trigger": "item", "formatter": "{b}: ${c} ({d}%)"},
        "legend": {"bottom": 0, "icon": "circle", "itemWidth": 8, "textStyle": {"color": "#778196", "fontSize": 11}},
        "series": [{"type": "pie", "radius": ["55%", "78%"], "center": ["50%", "44%"], "avoidLabelOverlap": True, "itemStyle": {"borderRadius": 6, "borderColor": "#fff", "borderWidth": 3}, "label": {"show": False}, "data": [{"name": name, "value": round(value, 2)} for name, value in data.items()]}],
    }
    st_echarts(options=options, height=f"{height}px", key=key)


def bar_chart(labels: Sequence[str], values: Sequence[float], key: str, height: int = 330) -> None:
    options = {
        "color": ["#6c5ce7"], "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 10, "right": 18, "top": 15, "bottom": 8, "containLabel": True},
        "xAxis": {"type": "value", "splitLine": {"lineStyle": {"color": "#eef1f6"}}, "axisLabel": {"color": "#8d96a7"}},
        "yAxis": {"type": "category", "data": list(labels)[::-1], "axisLine": {"show": False}, "axisTick": {"show": False}, "axisLabel": {"color": "#596276", "width": 150, "overflow": "truncate"}},
        "series": [{"type": "bar", "data": [round(float(v), 2) for v in list(values)[::-1]], "barWidth": 13, "itemStyle": {"borderRadius": [0, 7, 7, 0]}}],
    }
    st_echarts(options=options, height=f"{height}px", key=key)


def revenue_mix_bar(flow_share: float, campaign_share: float, key: str, height: int = 105) -> None:
    options = {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 8, "right": 52, "top": 4, "bottom": 4, "containLabel": True},
        "xAxis": {"type": "value", "max": 100, "show": False},
        "yAxis": {"type": "category", "data": ["Campaign", "Flow"], "axisLine": {"show": False}, "axisTick": {"show": False}, "axisLabel": {"color": "#596276", "fontSize": 11}},
        "series": [{"type": "bar", "data": [round(campaign_share * 100, 1), round(flow_share * 100, 1)], "barWidth": 12, "label": {"show": True, "position": "right", "formatter": "{c}%", "color": "#596276", "fontWeight": 700}, "itemStyle": {"borderRadius": [0, 7, 7, 0], "color": "#6c5ce7"}}],
    }
    st_echarts(options=options, height=f"{height}px", key=key)
