from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from deerflow.tools.builtins.setup_agent_tool import setup_agent


class _DummyRuntime(SimpleNamespace):
    context: dict
    tool_call_id: str


def test_setup_agent_rejects_invalid_agent_name_before_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    outside_dir = tmp_path.parent / "outside-target"
    traversal_agent = f"../../../{outside_dir.name}/evil"
    runtime = _DummyRuntime(context={"agent_name": traversal_agent}, tool_call_id="tool-1")

    result = setup_agent.func(soul="test soul", description="desc", runtime=runtime)

    messages = result.update["messages"]
    assert len(messages) == 1
    assert "Invalid agent name" in messages[0].content
    assert not (tmp_path / "agents").exists()
    assert not (outside_dir / "evil" / "SOUL.md").exists()


def test_setup_agent_rejects_absolute_agent_name_before_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    absolute_agent = str(tmp_path / "outside-agent")
    runtime = _DummyRuntime(context={"agent_name": absolute_agent}, tool_call_id="tool-2")

    result = setup_agent.func(soul="test soul", description="desc", runtime=runtime)

    messages = result.update["messages"]
    assert len(messages) == 1
    assert "Invalid agent name" in messages[0].content
    assert not (tmp_path / "agents").exists()
    assert not (Path(absolute_agent) / "SOUL.md").exists()


def test_setup_agent_syncs_remote_store_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setenv("DEER_FLOW_AGENTS_API_BASE_URL", "http://gateway:8001")
    runtime = _DummyRuntime(context={"agent_name": "sync-agent"}, tool_call_id="tool-3")

    from unittest.mock import patch

    with patch("deerflow.tools.builtins.setup_agent_tool.sync_agent_to_remote_store", return_value=True) as sync_remote:
        result = setup_agent.func(soul="test soul", description="desc", runtime=runtime)

    sync_remote.assert_called_once_with("sync-agent", soul="test soul", description="desc")
    assert "created successfully" in result.update["messages"][0].content
    assert (tmp_path / "agents" / "sync-agent" / "SOUL.md").read_text(encoding="utf-8") == "test soul"
