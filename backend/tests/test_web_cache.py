"""Tests for persistent per-thread web tool caching."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deerflow.community.web_cache import cache_web_result, get_cached_web_result


def _make_runtime(tmp_path):
    user_data = tmp_path / "threads" / "thread-1" / "user-data"
    return SimpleNamespace(
        state={
            "thread_data": {
                "workspace_path": str(user_data / "workspace"),
                "uploads_path": str(user_data / "uploads"),
                "outputs_path": str(user_data / "outputs"),
            }
        }
    )


def test_cache_web_result_persists_successful_response(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)
    result = json.dumps([{"title": "Cached", "url": "https://example.com"}], ensure_ascii=False)

    assert cache_web_result(runtime, provider="exa", tool_name="web_search", value="cached query", result=result) is True
    assert get_cached_web_result(runtime, provider="exa", tool_name="web_search", value="cached query") == result


def test_cache_web_result_skips_errors(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)

    assert cache_web_result(runtime, provider="exa", tool_name="web_fetch", value="https://example.com", result="Error: boom") is False
    assert cache_web_result(
        runtime,
        provider="ddg_search",
        tool_name="web_search",
        value="nothing",
        result=json.dumps({"error": "No results found"}),
    ) is False
    assert get_cached_web_result(runtime, provider="exa", tool_name="web_fetch", value="https://example.com") is None


def test_firecrawl_web_search_reuses_thread_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _make_runtime(tmp_path)

    search_config = MagicMock()
    search_config.model_extra = {"api_key": "firecrawl-search-key", "max_results": 7}
    mock_app_config = MagicMock()
    mock_app_config.get_tool_config.return_value = search_config
    monkeypatch.setattr("deerflow.community.firecrawl.tools.get_app_config", lambda: mock_app_config)

    mock_firecrawl_cls = MagicMock()
    mock_result = MagicMock()
    mock_result.web = [MagicMock(title="Result", url="https://example.com", description="Snippet")]
    mock_firecrawl_cls.return_value.search.return_value = mock_result
    monkeypatch.setattr("deerflow.community.firecrawl.tools.FirecrawlApp", mock_firecrawl_cls)

    from deerflow.community.firecrawl.tools import web_search_tool

    first = web_search_tool.func(runtime=runtime, query="test query")
    second = web_search_tool.func(runtime=runtime, query="test query")

    assert json.loads(first) == json.loads(second)
    mock_firecrawl_cls.return_value.search.assert_called_once_with("test query", limit=7)


@pytest.mark.anyio
async def test_jina_web_fetch_reuses_thread_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _make_runtime(tmp_path)

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)

    crawl_calls = 0

    async def mock_crawl(self, url, **kwargs):
        nonlocal crawl_calls
        crawl_calls += 1
        return "<html><body><p>Hello world</p></body></html>"

    class _Article:
        def to_markdown(self) -> str:
            return "Hello world"

    monkeypatch.setattr("deerflow.community.jina_ai.tools.JinaClient.crawl", mock_crawl)
    monkeypatch.setattr(
        "deerflow.community.jina_ai.tools.readability_extractor.extract_article",
        lambda html: _Article(),
    )

    from deerflow.community.jina_ai.tools import web_fetch_tool

    first = await web_fetch_tool.coroutine(runtime=runtime, url="https://example.com")
    second = await web_fetch_tool.coroutine(runtime=runtime, url="https://example.com")

    assert first == "Hello world"
    assert second == "Hello world"
    assert crawl_calls == 1


def test_tavily_web_search_tool_schema_is_json_serializable() -> None:
    from deerflow.community.tavily.tools import web_search_tool

    schema = web_search_tool.tool_call_schema.model_json_schema()

    assert "runtime" not in schema.get("properties", {})
    assert schema["properties"]["query"]["type"] == "string"
