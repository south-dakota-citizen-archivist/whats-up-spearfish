"""
tests/test_slack.py

Tests for scrapers/slack.py: send_alert credential handling and error isolation.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

from scrapers.slack import send_alert


class TestSendAlert:
    # ── Missing credentials ───────────────────────────────────────────────────

    def test_no_credentials_returns_false(self):
        with patch.dict(os.environ, {}, clear=True):
            assert send_alert("test") is False

    def test_token_only_returns_false(self):
        env = {"SLACK_BOT_TOKEN": "xoxb-fake"}
        env.pop("SLACK_CHANNEL_ID", None)
        with patch.dict(os.environ, env, clear=True):
            assert send_alert("test") is False

    def test_channel_only_returns_false(self):
        env = {"SLACK_CHANNEL_ID": "C123"}
        env.pop("SLACK_BOT_TOKEN", None)
        with patch.dict(os.environ, env, clear=True):
            assert send_alert("test") is False

    # ── Successful send ───────────────────────────────────────────────────────

    def _env(self):
        return {"SLACK_BOT_TOKEN": "xoxb-fake", "SLACK_CHANNEL_ID": "C123"}

    def test_success_returns_true(self):
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}
        with patch.dict(os.environ, self._env()):
            with patch("slack_sdk.WebClient", return_value=mock_client):
                assert send_alert("hello") is True

    def test_calls_chat_post_message(self):
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}
        with patch.dict(os.environ, self._env()):
            with patch("slack_sdk.WebClient", return_value=mock_client):
                send_alert("hello")
        mock_client.chat_postMessage.assert_called_once()

    def test_passes_text_to_api(self):
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}
        with patch.dict(os.environ, self._env()):
            with patch("slack_sdk.WebClient", return_value=mock_client):
                send_alert("my message")
        kwargs = mock_client.chat_postMessage.call_args[1]
        assert kwargs["text"] == "my message"

    def test_passes_channel_from_env(self):
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}
        with patch.dict(os.environ, self._env()):
            with patch("slack_sdk.WebClient", return_value=mock_client):
                send_alert("hi")
        kwargs = mock_client.chat_postMessage.call_args[1]
        assert kwargs["channel"] == "C123"

    def test_passes_blocks_when_provided(self):
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]
        with patch.dict(os.environ, self._env()):
            with patch("slack_sdk.WebClient", return_value=mock_client):
                send_alert("hi", blocks=blocks)
        kwargs = mock_client.chat_postMessage.call_args[1]
        assert kwargs["blocks"] == blocks

    # ── API errors ────────────────────────────────────────────────────────────

    def test_api_not_ok_returns_false(self):
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": False, "error": "not_authed"}
        with patch.dict(os.environ, self._env()):
            with patch("slack_sdk.WebClient", return_value=mock_client):
                assert send_alert("hi") is False

    def test_exception_returns_false(self):
        mock_client = MagicMock()
        mock_client.chat_postMessage.side_effect = Exception("network error")
        with patch.dict(os.environ, self._env()):
            with patch("slack_sdk.WebClient", return_value=mock_client):
                assert send_alert("hi") is False

    def test_exception_does_not_propagate(self):
        mock_client = MagicMock()
        mock_client.chat_postMessage.side_effect = RuntimeError("boom")
        with patch.dict(os.environ, self._env()):
            with patch("slack_sdk.WebClient", return_value=mock_client):
                # Must not raise
                send_alert("hi")

    # ── Import error (sdk not installed) ─────────────────────────────────────

    def test_sdk_not_installed_returns_false(self):
        with patch.dict(os.environ, self._env()):
            with patch.dict(sys.modules, {"slack_sdk": None}):
                assert send_alert("hi") is False
