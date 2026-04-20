import json
from typing import Annotated

from firecrawl import FirecrawlApp
from langchain.tools import InjectedToolArg, ToolRuntime, tool
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState
from deerflow.community.web_cache import cache_web_result, get_cached_web_result
from deerflow.config import get_app_config


def _get_firecrawl_client(tool_name: str = "web_search") -> FirecrawlApp:
    config = get_app_config().get_tool_config(tool_name)
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    return FirecrawlApp(api_key=api_key)  # type: ignore[arg-type]


@tool("web_search", parse_docstring=True)
def web_search_tool(
    query: str,
    runtime: Annotated[ToolRuntime[ContextT, ThreadState] | None, InjectedToolArg] = None,
) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    cached_result = get_cached_web_result(runtime, provider="firecrawl", tool_name="web_search", value=query)
    if cached_result is not None:
        return cached_result

    try:
        config = get_app_config().get_tool_config("web_search")
        max_results = 5
        if config is not None:
            max_results = config.model_extra.get("max_results", max_results)

        client = _get_firecrawl_client("web_search")
        result = client.search(query, limit=max_results)

        # result.web contains list of SearchResultWeb objects
        web_results = result.web or []
        normalized_results = [
            {
                "title": getattr(item, "title", "") or "",
                "url": getattr(item, "url", "") or "",
                "snippet": getattr(item, "description", "") or "",
            }
            for item in web_results
        ]
        json_results = json.dumps(normalized_results, indent=2, ensure_ascii=False)
        cache_web_result(runtime, provider="firecrawl", tool_name="web_search", value=query, result=json_results)
        return json_results
    except Exception as e:
        return f"Error: {str(e)}"


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(
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
    cached_result = get_cached_web_result(runtime, provider="firecrawl", tool_name="web_fetch", value=url)
    if cached_result is not None:
        return cached_result

    try:
        client = _get_firecrawl_client("web_fetch")
        result = client.scrape(url, formats=["markdown"])

        markdown_content = result.markdown or ""
        metadata = result.metadata
        title = metadata.title if metadata and metadata.title else "Untitled"

        if not markdown_content:
            return "Error: No content found"
    except Exception as e:
        return f"Error: {str(e)}"

    content = f"# {title}\n\n{markdown_content[:4096]}"
    cache_web_result(runtime, provider="firecrawl", tool_name="web_fetch", value=url, result=content)
    return content
