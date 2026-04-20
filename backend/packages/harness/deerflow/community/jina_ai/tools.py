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
    config = get_app_config().get_tool_config("web_fetch")
    if config is not None and "timeout" in config.model_extra:
        timeout = config.model_extra.get("timeout")
    html_content = await jina_client.crawl(url, return_format="html", timeout=timeout)
    if isinstance(html_content, str) and html_content.startswith("Error:"):
        return html_content
    article = await asyncio.to_thread(readability_extractor.extract_article, html_content)
    markdown = article.to_markdown()[:4096]
    cache_web_result(runtime, provider="jina_ai", tool_name="web_fetch", value=url, result=markdown)
    return markdown
