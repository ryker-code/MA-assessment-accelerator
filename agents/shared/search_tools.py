import os
from tavily import TavilyClient


DOMAIN_WHITELIST = {
    "country": ["imf.org", "worldbank.org", "reuters.com", "bloomberg.com", "ft.com", "economist.com"],
    "sector": ["gsma.com", "itu.int", "lightreading.com", "gartner.com", "mckinsey.com"],
    "company": ["sec.gov", "businesswire.com", "prnewswire.com", "reuters.com", "ft.com"],
    "default": ["reuters.com", "bloomberg.com", "ft.com", "wsj.com"],
}


def web_search(query: str, agent_type: str = "default", max_results: int = 5) -> list[dict]:
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    domains = DOMAIN_WHITELIST.get(agent_type, DOMAIN_WHITELIST["default"])
    results = client.search(
        query=query,
        max_results=max_results,
        search_depth="basic",
        include_domains=domains,
    )
    return results.get("results", [])
