"""Mandatory web preflight support.

The preflight is intentionally side-effect/ephemeral-context based:
- it may call the configured web_search backend before the first model call;
- it writes a trace under HERMES_HOME/state/web_preflight;
- it returns a compact context block for the current user API message only;
- it never mutates persisted conversation history or the cached system prompt.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

_SECRETISH = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{16,}|[0-9]{6,}:[A-Za-z0-9_-]{20,})")
_LOCAL_PATH = re.compile(r"/(?:Users|private|var|tmp)/[^\s`'\"]+")
_WS = re.compile(r"\s+")


def _load_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _config_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "always"}
    return default


def _preflight_config() -> dict[str, Any]:
    cfg = _load_config()
    raw_web = cfg.get("web")
    web: dict[str, Any] = raw_web if isinstance(raw_web, dict) else {}
    raw_mandatory = web.get("mandatory_preflight")
    mandatory: dict[str, Any] = raw_mandatory if isinstance(raw_mandatory, dict) else {}
    return {
        "enabled": _config_bool(mandatory.get("enabled"), default=False),
        "inject_context": _config_bool(mandatory.get("inject_context"), default=True),
        "write_trace": _config_bool(mandatory.get("write_trace"), default=True),
        "limit": int(mandatory.get("limit") or 3),
        "max_query_chars": int(mandatory.get("max_query_chars") or 240),
    }


def _summarize_message(user_message: Any, max_chars: int) -> str:
    if isinstance(user_message, str):
        text = user_message
    else:
        try:
            text = json.dumps(user_message, ensure_ascii=False)
        except Exception:
            text = str(user_message)
    text = _SECRETISH.sub("[REDACTED_SECRET]", text)
    text = _LOCAL_PATH.sub("[LOCAL_PATH]", text)
    text = _WS.sub(" ", text).strip()
    return text[:max_chars].strip()


def _trace_path(session_id: str | None, turn_id: str | None) -> Path:
    root = get_hermes_home() / "state" / "web_preflight"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    sid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "no-session"))[:80]
    tid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(turn_id or "no-turn"))[:80]
    return root / f"{stamp}_{sid}_{tid}.json"


def _compact_context(results: dict[str, Any], query: str) -> str:
    web_items = (((results or {}).get("data") or {}).get("web") or [])
    lines = [
        "[Mandatory web preflight — ephemeral current-source context; verify with deeper extraction before hard claims]",
        f"Query: {query}",
    ]
    for item in web_items[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:160]
        url = str(item.get("url") or "").strip()
        desc = str(item.get("description") or "").strip()[:260]
        if title or url or desc:
            lines.append(f"- {title} — {url} — {desc}".strip())
    return "\n".join(lines)


def run_mandatory_web_preflight(agent: Any, user_message: Any, *, turn_id: str | None = None) -> dict[str, Any]:
    config = _preflight_config()
    session_id = getattr(agent, "session_id", None)
    platform = getattr(agent, "platform", None) or ""
    trace: dict[str, Any] = {
        "status": "disabled",
        "enabled": config["enabled"],
        "session_id": session_id,
        "turn_id": turn_id,
        "platform": platform,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "inject_context": False,
        "query": "",
        "search_ok": False,
        "result_count": 0,
        "error": None,
    }
    if not config["enabled"]:
        return trace

    query = _summarize_message(user_message, config["max_query_chars"])
    trace["query"] = query
    if not query:
        trace["status"] = "skipped_empty_query"
        return trace

    started = time.monotonic()
    try:
        from tools.web_tools import web_search_tool

        raw = web_search_tool(query=query, limit=max(1, min(config["limit"], 10)))
        payload = json.loads(raw) if isinstance(raw, str) else raw
        trace["raw_success"] = bool((payload or {}).get("success")) if isinstance(payload, dict) else False
        items = (((payload or {}).get("data") or {}).get("web") or []) if isinstance(payload, dict) else []
        trace["result_count"] = len(items)
        trace["search_ok"] = bool(trace["raw_success"] and items)
        trace["status"] = "searched" if trace["search_ok"] else "search_no_results_or_failed"
        if config["inject_context"] and trace["search_ok"]:
            trace["context"] = _compact_context(payload, query)
            trace["inject_context"] = True
    except Exception as exc:  # noqa: BLE001 - preflight must fail-open for the turn
        trace["status"] = "search_error"
        trace["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        trace["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        trace["finished_at"] = datetime.now(timezone.utc).isoformat()
        if config["write_trace"]:
            try:
                path = _trace_path(session_id, turn_id)
                trace_to_write = dict(trace)
                # Context can be repeated in the API message; keep trace compact.
                trace_to_write.pop("context", None)
                path.write_text(json.dumps(trace_to_write, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                trace["trace_path"] = str(path)
            except Exception as exc:  # noqa: BLE001
                trace["trace_write_error"] = f"{type(exc).__name__}: {exc}"
    return trace
