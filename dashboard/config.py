from __future__ import annotations

import streamlit as st


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


API_KEY = secret("KLAVIYO_API_KEY")
REVISION = secret("KLAVIYO_REVISION", "2026-07-15")
EMAIL_SUBSCRIBER_SEGMENT_ID = secret("EMAIL_SUBSCRIBER_SEGMENT_ID", "XbbG5w")
SMS_SUBSCRIBER_SEGMENT_ID = secret("SMS_SUBSCRIBER_SEGMENT_ID", "TNhv7y")
