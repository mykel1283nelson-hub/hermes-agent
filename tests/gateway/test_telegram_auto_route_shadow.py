from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from gateway.run import (
    _classify_telegram_auto_route,
    _maybe_record_telegram_auto_route_shadow,
    _parse_modelroute_args,
    _telegram_auto_route_active_plan,
    _telegram_auto_route_config,
)
from hermes_cli.commands import is_gateway_known_command, resolve_command


def _telegram_event(text: str = "summarize this") -> SimpleNamespace:
    source = SimpleNamespace(
        platform=SimpleNamespace(value="telegram"),
        chat_type="group",
        thread_id=123,
    )
    return SimpleNamespace(
        text=text,
        source=source,
        message_id=456,
        media_types=[],
        media_urls=[],
    )


def test_modelroute_command_is_registered_for_gateway() -> None:
    command = resolve_command("modelroute")
    assert command is not None
    assert command.gateway_only is True
    assert is_gateway_known_command("modelroute") is True


def test_parse_modelroute_args_requires_task_and_message() -> None:
    assert _parse_modelroute_args("cheap_summary_or_draft hello") == (
        "cheap_summary_or_draft",
        "hello",
    )


def test_invalid_auto_route_config_fails_closed() -> None:
    config = {"telegram": {"auto_route": {"mode": "active", "confidence_floor": 2}}}
    result = _telegram_auto_route_config(config)
    assert result["mode"] == "off"


def test_summary_message_is_active_route_eligible() -> None:
    plan = _telegram_auto_route_active_plan(
        {"telegram": {"auto_route": {"mode": "active", "confidence_floor": 0.7}}},
        _telegram_event("summarize this short note"),
    )
    assert plan is not None
    assert plan["lane"] == "free_utility_general"
    assert plan["decision"]["task_class"] == "cheap_summary_or_draft"


def test_build_message_stays_on_hermes_default_path() -> None:
    decision = _classify_telegram_auto_route(_telegram_event("fix the repo and commit it"))
    assert decision["task_class"] == "build_completion"
    assert decision["needs_tools"] is True
    plan = _telegram_auto_route_active_plan(
        {"telegram": {"auto_route": {"mode": "active", "confidence_floor": 0.7}}},
        _telegram_event("fix the repo and commit it"),
    )
    assert plan is None


def test_shadow_telemetry_is_sanitized(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "godmode-workspace"
    (repo_root / "scripts/runtime").mkdir(parents=True)
    (repo_root / "runtime/configs").mkdir(parents=True)
    (repo_root / "scripts/runtime/run_selected_model_route.py").write_text("", encoding="utf-8")
    (repo_root / "runtime/configs/model-route-policy.yaml").write_text("", encoding="utf-8")
    monkeypatch.setenv("HERMES_MODEL_ROUTE_REPO_ROOT", str(repo_root))

    decision = _maybe_record_telegram_auto_route_shadow(
        {"telegram": {"auto_route": {"mode": "shadow", "confidence_floor": 0.7}}},
        _telegram_event("summarize private token abc123"),
    )
    assert decision is not None
    out_path = repo_root / "evidence/runtime_health/telegram_auto_route/shadow.jsonl"
    record = json.loads(out_path.read_text(encoding="utf-8").strip())
    assert record["raw_text_recorded"] is False
    assert "private token" not in json.dumps(record)
