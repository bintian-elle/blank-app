# Email Marketing Performance Dashboard

A Streamlit dashboard for Klaviyo email and SMS performance reporting.

### Project structure

- `streamlit_app.py` — overview page
- `pages/` — Streamlit subpages (Campaigns and Flows)
- `dashboard/data.py` — cached Klaviyo data service
- `dashboard/charts.py` — reusable ECharts visualizations
- `dashboard/components.py` — filters, KPI cards, and page components
- `dashboard/styles.py` — shared application theme
- `klaviyo_client.py` — low-level Klaviyo API client

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://blank-app-template.streamlit.app/)

### Connect Klaviyo

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, then put your
Klaviyo private API key in that file. The real secrets file is ignored by Git.

### How to run it on your own machine

Prerequisite: install `uv` if you don't already have it.

```
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```

1. Sync the dependencies

   ```
   $ uv sync
   ```

2. Run the app

   ```
   $ uv run streamlit run streamlit_app.py
   ```
