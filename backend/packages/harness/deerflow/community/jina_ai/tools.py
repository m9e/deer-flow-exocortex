import asyncio
from typing import Annotated

from langchain.tools import InjectedToolArg, ToolRuntime, tool
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState
from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.community.web_cache import cache_web_result, get_cached_web_result
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

readability_extractor = ReadabilityExtractor()


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_timeout(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _coerce_proxy(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    proxy = value.strip()
    return proxy or None


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(
    url: str,
    runtime: Annotated[ToolRuntime[ContextT, ThreadState] | None, InjectedToolArg] = None,
) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    cached_result = get_cached_web_result(runtime, provider="jina_ai", tool_name="web_fetch", value=url)
    if cached_result is not None:
        return cached_result

    jina_client = JinaClient()
    timeout = 10
    proxy = None
    trust_env = True
    config = get_app_config().get_tool_config("web_fetch")
    if config is not None:
        timeout = _coerce_timeout(config.model_extra.get("timeout"), timeout)
        proxy = _coerce_proxy(config.model_extra.get("proxy"))
        trust_env = _coerce_bool(config.model_extra.get("trust_env"), trust_env)
    html_content = await jina_client.crawl(url, return_format="html", timeout=timeout, proxy=proxy, trust_env=trust_env)
    if isinstance(html_content, str) and html_content.startswith("Error:"):
        return html_content
    article = await asyncio.to_thread(readability_extractor.extract_article, html_content)
    markdown = article.to_markdown()[:4096]
    cache_web_result(runtime, provider="jina_ai", tool_name="web_fetch", value=url, result=markdown)
    return markdown
