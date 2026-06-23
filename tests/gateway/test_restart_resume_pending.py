"""Regression tests that gateway restart auto-resume/replay stays disabled.

The old resume_pending feature synthesized a "gateway is back online" turn after
restart. That path caused Telegram restart loops by replaying the interrupted
conversation. Restart/shutdown may preserve transcript history in SQLite, but it
must not auto-replay or inject a fake comeback prompt.
"""

from datetime import datetime

from gateway.config import GatewayConfig, Platform
from gateway.session import SessionEntry, SessionSource, SessionStore
from tests.gateway.restart_test_helpers import make_restart_runner


def _make_source(platform=Platform.TELEGRAM, chat_id="123", user_id="u1"):
    return SessionSource(platform=platform, chat_id=chat_id, user_id=user_id)


def _make_store(tmp_path):
    return SessionStore(sessions_dir=tmp_path, config=GatewayConfig())


class TestRestartAutoResumeDisabled:
    def test_mark_resume_pending_is_noop(self, tmp_path):
        store = _make_store(tmp_path)
        source = _make_source()
        entry = store.get_or_create_session(source)

        assert store.mark_resume_pending(entry.session_key, "restart_timeout") is False

        refreshed = store.get_or_create_session(source)
        assert refreshed.session_id == entry.session_id
        assert refreshed.resume_pending is False
        assert refreshed.resume_reason is None
        assert refreshed.last_resume_marked_at is None

    def test_suspend_recently_active_is_noop(self, tmp_path):
        store = _make_store(tmp_path)
        source = _make_source()
        entry = store.get_or_create_session(source)

        assert store.suspend_recently_active() == 0

        refreshed = store.get_or_create_session(source)
        assert refreshed.session_id == entry.session_id
        assert refreshed.resume_pending is False
        assert refreshed.suspended is False

    def test_legacy_resume_pending_starts_fresh_session(self, tmp_path):
        store = _make_store(tmp_path)
        source = _make_source()
        entry = store.get_or_create_session(source)
        old_session_id = entry.session_id

        with store._lock:
            entry.resume_pending = True
            entry.resume_reason = "restart_timeout"
            entry.last_resume_marked_at = datetime.now()
            store._save()

        refreshed = store.get_or_create_session(source)
        assert refreshed.session_id != old_session_id
        assert refreshed.was_auto_reset is True
        assert refreshed.auto_reset_reason == "restart_resume_disabled"
        assert refreshed.resume_pending is False

    def test_scheduler_does_not_synthesize_resume_events(self):
        runner, _adapter = make_restart_runner()
        assert runner._schedule_resume_pending_sessions() == 0
