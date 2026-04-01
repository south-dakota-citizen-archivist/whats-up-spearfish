"""
scrapers/slack.py

Slack notification helper.  Sends alerts to a configured channel via the
Slack Web API.  Silently no-ops when the credentials are not present so that
local development and CI without secrets continue to work.
"""

from __future__ import annotations

import os
from typing import Any


def send_alert(text: str, blocks: list[dict[str, Any]] | None = None) -> bool:
    """
    Post *text* (and optional Block Kit *blocks*) to the configured Slack
    channel.

    Reads ``SLACK_BOT_TOKEN`` and ``SLACK_CHANNEL_ID`` from the environment.
    Returns ``True`` if the message was sent successfully, ``False`` otherwise
    (including when credentials are absent — no exception is raised).
    """
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    channel = os.getenv("SLACK_CHANNEL_ID", "").strip()

    if not token or not channel:
        # Credentials not configured — skip silently.
        print("[slack] SLACK_BOT_TOKEN / SLACK_CHANNEL_ID not set; skipping alert.")
        return False

    try:
        from slack_sdk import WebClient

        client = WebClient(token=token)
        kwargs: dict[str, Any] = {
            "channel": channel,
            "text": text,
        }
        if blocks:
            kwargs["blocks"] = blocks

        response = client.chat_postMessage(**kwargs)
        if response["ok"]:
            print(f"[slack] Alert sent to {channel}.")
            return True
        else:
            print(f"[slack] Slack API returned not-ok: {response.get('error')}")
            return False

    except ImportError:
        print("[slack] slack_sdk not installed; skipping alert.")
        return False
    except Exception as exc:  # noqa: BLE001
        # Never let Slack errors crash the scrape pipeline.
        print(f"[slack] Failed to send alert: {exc}")
        return False
