import json
from pathlib import Path

from agent import web_preflight


class DummyAgent:
    session_id = "session:telegram:1"
    platform = "telegram"


def test_mandatory_web_preflight_disabled_by_default(monkeypatch):
    monkeypatch.setattr(web_preflight, "_load_config", lambda: {"web": {}})
    out = web_preflight.run_mandatory_web_preflight(DummyAgent(), "latest python release", turn_id="t1")
    assert out["status"] == "disabled"
    assert out["enabled"] is False


def test_mandatory_web_preflight_searches_writes_trace_and_returns_ephemeral_context(monkeypatch, tmp_path):
    monkeypatch.setattr(
        web_preflight,
        "_load_config",
        lambda: {"web": {"mandatory_preflight": {"enabled": True, "inject_context": True, "write_trace": True, "limit": 2}}},
    )
    monkeypatch.setattr(web_preflight, "get_hermes_home", lambda: tmp_path)

    def fake_web_search_tool(query, limit=5):
        assert "latest python release" in query
        assert limit == 2
        return json.dumps(
            {
                "success": True,
                "data": {
                    "web": [
                        {"title": "Python News", "url": "https://example.com/python", "description": "Current release info"}
                    ]
                },
            }
        )

    import tools.web_tools as web_tools

    monkeypatch.setattr(web_tools, "web_search_tool", fake_web_search_tool)
    out = web_preflight.run_mandatory_web_preflight(DummyAgent(), "latest python release", turn_id="turn-1")

    assert out["status"] == "searched"
    assert out["search_ok"] is True
    assert out["result_count"] == 1
    assert out["inject_context"] is True
    assert "Mandatory web preflight" in out["context"]
    assert "https://example.com/python" in out["context"]
    trace_path = Path(out["trace_path"])
    assert trace_path.exists()
    trace = json.loads(trace_path.read_text())
    assert trace["status"] == "searched"
    assert trace["session_id"] == "session:telegram:1"
    assert "context" not in trace


def test_preflight_query_redacts_secrets_and_local_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        web_preflight,
        "_load_config",
        lambda: {"web": {"mandatory_preflight": {"enabled": True, "inject_context": False, "write_trace": False}}},
    )
    captured = {}

    def fake_web_search_tool(query, limit=5):
        captured["query"] = query
        return json.dumps({"success": True, "data": {"web": []}})

    import tools.web_tools as web_tools

    monkeypatch.setattr(web_tools, "web_search_tool", fake_web_search_tool)
    out = web_preflight.run_mandatory_web_preflight(
        DummyAgent(),
        "check sk-1234567890abcdef and /Users/agentmoney/.hermes/config.yaml",
        turn_id="turn-2",
    )

    assert "sk-" not in captured["query"]
    assert "/Users/agentmoney" not in captured["query"]
    assert "[REDACTED_SECRET]" in captured["query"]
    assert "[LOCAL_PATH]" in captured["query"]
