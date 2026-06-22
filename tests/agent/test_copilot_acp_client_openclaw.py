from types import SimpleNamespace

from agent.agent_runtime_helpers import create_openai_client
from agent.copilot_acp_client import (
    CopilotACPClient,
    _clean_openclaw_response_text,
    _format_messages_as_openclaw_acp_prompt,
    _format_messages_as_prompt,
    _is_openclaw_command,
)


def test_openclaw_command_detection():
    assert _is_openclaw_command("openclaw") is True
    assert _is_openclaw_command("/opt/homebrew/bin/openclaw") is True
    assert _is_openclaw_command("openclaw-dev") is True
    assert _is_openclaw_command("copilot") is False
    assert _is_openclaw_command(None) is False


def test_openclaw_acp_prompt_is_compact_and_directive_routed():
    huge_system = "SYSTEM RULES\n" + ("x" * 50_000)
    older_user = "older request should not be forwarded"
    latest_user = "Reply with exactly OPENCLAW_ACP_SMOKE_OK."
    messages = [
        {"role": "system", "content": huge_system},
        {"role": "user", "content": older_user},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": latest_user},
    ]

    prompt = _format_messages_as_openclaw_acp_prompt(messages, model="gpt-5.5")

    assert prompt.startswith("/model cocaptain_medium\n\n/think medium")
    assert latest_user in prompt
    assert older_user not in prompt
    assert huge_system not in prompt
    assert "Hermes requested model hint: gpt-5.5" in prompt
    assert "Do not emit tool calls" in prompt
    assert len(prompt) < 1200


def test_generic_acp_prompt_keeps_full_transcript_and_tool_specs():
    messages = [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "latest request"},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "example_tool",
                "description": "Example",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    prompt = _format_messages_as_prompt(messages, model="gpt-5.5", tools=tools)

    assert "Conversation transcript" in prompt
    assert "System:\nsystem rules" in prompt
    assert "User:\nlatest request" in prompt
    assert "example_tool" in prompt


def test_openclaw_response_cleanup_strips_funding_banner_and_unwraps_text():
    raw = '> **⚠️ Wallet empty** — using free model. Send USDC to `0xabc1234567890abc1234567890abc1234567890`\n\n{"type": "text", "text": "OPENCLAW_OK"}'

    assert _clean_openclaw_response_text(raw) == "OPENCLAW_OK"


def test_openclaw_response_cleanup_preserves_regular_json():
    raw = '{"answer": "OPENCLAW_OK"}'

    assert _clean_openclaw_response_text(raw) == raw


def test_openclaw_acp_provider_builds_native_acp_client():
    agent = SimpleNamespace(
        provider="openclaw-acp",
        _client_log_context=lambda: "test-agent",
    )

    client = create_openai_client(
        agent,
        {
            "api_key": "openclaw-acp",
            "base_url": "http://127.0.0.1:8402/v1",
            "command": "/opt/homebrew/bin/openclaw",
            "args": ["acp", "--session", "agent:hermes-cocaptain:test"],
        },
        reason="unit-test",
        shared=False,
    )

    assert isinstance(client, CopilotACPClient)
    assert client._acp_command == "/opt/homebrew/bin/openclaw"
    assert client._acp_args == ["acp", "--session", "agent:hermes-cocaptain:test"]
