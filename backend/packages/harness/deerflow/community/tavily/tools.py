import json
from typing import Annotated

from langchain.tools import InjectedToolArg, ToolRuntime, tool
from langgraph.typing import ContextT
from tavily import TavilyClient

from deerflow.agents.thread_state import ThreadState
from deerflow.community.web_cache import cache_web_result, get_cached_web_result
from deerflow.config import get_app_config


def _get_tavily_client() -> TavilyClient:
    config = get_app_config().get_tool_config("web_search")
    api_key = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")
    return TavilyClient(api_key=api_key)


@tool("web_search", parse_docstring=True)
def web_search_tool(
    query: str,
    runtime: Annotated[ToolRuntime[ContextT, ThreadState] | None, InjectedToolArg] = None,
) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    cached_result = get_cached_web_result(runtime, provider="tavily", tool_name="web_search", value=query)
    if cached_result is not None:
        return cached_result

    config = get_app_config().get_tool_config("web_search")
    max_results = 5
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results")

    client = _get_tavily_client()
    res = client.search(query, max_results=max_results)
    normalized_results = [
        {
            "title": result["title"],
            "url": result["url"],
            "snippet": result["content"],
        }
        for result in res["results"]
    ]
    json_results = json.dumps(normalized_results, indent=2, ensure_ascii=False)
    cache_web_result(runtime, provider="tavily", tool_name="web_search", value=query, result=json_results)
    return json_results


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
    cached_result = get_cached_web_result(runtime, provider="tavily", tool_name="web_fetch", value=url)
    if cached_result is not None:
        return cached_result

    client = _get_tavily_client()
    res = client.extract([url])
    if "failed_results" in res and len(res["failed_results"]) > 0:
        return f"Error: {res['failed_results'][0]['error']}"
    elif "results" in res and len(res["results"]) > 0:
        result = res["results"][0]
        content = f"# {result['title']}\n\n{result['raw_content'][:4096]}"
        cache_web_result(runtime, provider="tavily", tool_name="web_fetch", value=url, result=content)
        return content
    else:
        return "Error: No results found"
