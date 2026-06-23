import os
import re
from google import genai
from google.genai.types import GenerateContentConfig, Tool, GoogleSearch


def web_search(query: str, agent_type: str = "default", max_results: int = 5) -> list[dict]:
    """Search via gemma-4-31b-it Google Search grounding. Returns [{url, title, content}]."""
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    try:
        response = client.models.generate_content(
            model="gemma-4-31b-it",
            config=GenerateContentConfig(
                tools=[Tool(google_search=GoogleSearch())],
                temperature=0.1,
                max_output_tokens=2048,
            ),
            contents=f"Research and provide detailed facts, statistics, and data points for: {query}",
        )

        content = response.text or ""

        # Try to extract grounding chunk URLs (deduplicated)
        seen_urls: set[str] = set()
        urls = []
        try:
            chunks = response.candidates[0].grounding_metadata.grounding_chunks or []
            for chunk in chunks:
                if hasattr(chunk, "web") and chunk.web:
                    url = getattr(chunk.web, "uri", "") or ""
                    if url and url not in seen_urls:
                        urls.append(url)
                        seen_urls.add(url)
        except (AttributeError, IndexError, TypeError):
            pass

        # Fall back to any URLs mentioned inline in the response text
        if not urls:
            for u in re.findall(r'https?://[^\s\)\]"]+', content):
                if u not in seen_urls:
                    urls.append(u)
                    seen_urls.add(u)

        if not content:
            return []

        # Primary result carries the synthesized content; remaining entries carry source URLs
        results = [{"url": urls[0] if urls else "", "title": query, "content": content}]
        for url in urls[1:max_results]:
            results.append({"url": url, "title": "", "content": ""})

        return results

    except Exception:
        return []
