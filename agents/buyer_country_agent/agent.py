import asyncio
import json
import os
from datetime import datetime

from agents.shared.llm_router import LLMRouter
from agents.shared.search_tools import web_search
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import post_completion
from agents.shared.prompts import BUYER_COUNTRY_AGENT_PROMPT
from agents.shared.schemas import CountryAssessment
from agents.shared.llm_utils import extract_json

router = LLMRouter()


def _format_markdown(data: CountryAssessment, buyer_country: str) -> str:
    lines = [
        f"## {buyer_country} — Buyer Country Assessment (Buy-Side)\n",
        f"**Status:** {data.status} | **Confidence:** {data.confidence_score:.0%}\n",
        f"### Outbound M&A Environment",
        f"- **Currency:** {data.currency_code} ({data.currency_trend})",
        f"- **Political Stability Score:** {data.political_stability_score:.1f}/100",
        f"- **Corporate Tax Rate:** {data.corporate_tax_rate_pct:.1f}%",
        f"\n### Capital Repatriation & FX",
        data.currency_repatriation_laws,
        f"\n### Risk Flags (Outbound M&A Focus)",
    ]
    for flag in data.risk_flags:
        lines.append(f"- {flag}")
    lines += [f"\n### Narrative Summary", data.narrative_summary]
    lines.append(f"\n### Data Sources")
    for src in data.data_sources:
        lines.append(f"- {src}")
    return "\n".join(lines)


async def run_buyer_country_assessment(
    assessment_id: str, buyer_company: str, buyer_country: str, target_country: str = ""
) -> dict:
    searches = [
        f"{buyer_country} outbound M&A regulations foreign investment approval process",
        f"{buyer_country} tax treaty {target_country} dividend withholding repatriation",
        f"{buyer_country} currency stability capital outflows foreign investment 2024",
        f"{buyer_country} geopolitical relations {target_country} bilateral investment",
        f"{buyer_country} sovereign wealth fund M&A activity telecom sector 2024",
    ]
    research_data = []
    for q in searches:
        try:
            results = web_search(q, agent_type="country")
            research_data.extend(results)
        except Exception:
            pass

    sources = list({r["url"] for r in research_data if r.get("url")})
    context = "\n\n".join([
        f"Source: {r.get('url', 'unknown')}\n{r.get('content', '')}"
        for r in research_data[:10]
    ])

    prompt = (
        f"Buyer country: {buyer_country}\nBuyer company: {buyer_company}\n"
        f"Target country: {target_country}\nAssessment ID: {assessment_id}\n\n"
        f"Research data:\n{context}\n\n"
        "Produce a buyer country assessment focused on OUTBOUND M&A capability as a single JSON object:\n"
        "{\n"
        f'  "agent": "buyer-country-agent",\n'
        f'  "assessment_id": "{assessment_id}",\n'
        f'  "target_company": "",\n'
        f'  "buyer_company": "{buyer_company}",\n'
        '  "timestamp": "2026-06-18T00:00:00Z",\n'
        '  "status": "COMPLETE",\n'
        '  "confidence_score": 0.8,\n'
        '  "human_review_required": false,\n'
        '  "data_sources": ["https://example.com"],\n'
        f'  "country": "{buyer_country}",\n'
        '  "gdp_growth_5yr": [{"year": 2020, "value": -4.1, "unit": "%"}, {"year": 2021, "value": 3.2, "unit": "%"}, {"year": 2022, "value": 8.7, "unit": "%"}, {"year": 2023, "value": 4.4, "unit": "%"}, {"year": 2024, "value": 3.0, "unit": "%"}],\n'
        '  "gdp_nominal_usd_bn": 1000.0,\n'
        '  "inflation_rate_latest": 2.5,\n'
        '  "currency_code": "SAR",\n'
        '  "currency_trend": "STABLE",\n'
        '  "political_stability_score": 60.0,\n'
        '  "ease_of_doing_business_rank": 62,\n'
        '  "corporate_tax_rate_pct": 20.0,\n'
        '  "currency_repatriation_laws": "Describe outbound capital flow rules and any restrictions on foreign acquisitions.",\n'
        '  "risk_flags": ["Outbound M&A risk 1", "Geopolitical risk"],\n'
        '  "narrative_summary": "Frame around: can this buyer effectively deploy capital into the target country?"\n'
        "}\n\n"
        "Rules: currency_trend must be APPRECIATING, STABLE, DEPRECIATING, or VOLATILE. "
        "Focus on OUTBOUND investment risks, not domestic risks. Return ONLY JSON."
    )

    response = router.complete(
        "buyer_country_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=BUYER_COUNTRY_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        structured = CountryAssessment.model_validate_json(json_str)
    except Exception:
        structured = CountryAssessment(
            agent="buyer-country-agent",
            assessment_id=assessment_id,
            target_company="",
            buyer_company=buyer_company,
            timestamp=datetime.utcnow().isoformat() + "Z",
            status="PARTIAL",
            confidence_score=0.3,
            country=buyer_country,
            gdp_growth_5yr=[],
            gdp_nominal_usd_bn=0.0,
            inflation_rate_latest=0.0,
            currency_code="UNK",
            currency_trend="STABLE",
            political_stability_score=50.0,
            ease_of_doing_business_rank=999,
            corporate_tax_rate_pct=0.0,
            currency_repatriation_laws="Data unavailable",
            risk_flags=["LLM parsing failed — manual review required"],
            narrative_summary=response[:500],
            data_sources=sources[:5],
        )

    structured.data_sources = sources[:10]
    markdown = _format_markdown(structured, buyer_country)
    return {
        "structured": structured.model_dump(),
        "markdown": markdown,
        "confidence": structured.confidence_score,
        "sources": structured.data_sources,
    }


async def handle_message(message: dict):
    params = json.loads(message.get("content", "{}"))
    assessment_id = params["assessment_id"]
    buyer_company = params["buyer_company"]
    buyer_country = params.get("buyer_country", "")
    target_country = params.get("country", "")

    result = await run_buyer_country_assessment(
        assessment_id, buyer_company, buyer_country, target_country
    )

    file_path = save_agent_output(
        assessment_id=assessment_id,
        agent_name="buyer-country-agent",
        file_index=4,
        title=f"Buyer Country Assessment: {buyer_country}",
        content=result["markdown"],
        metadata={"confidence": f"{result['confidence']:.0%}", "sources": len(result["sources"])},
    )

    await post_completion(
        room_id=params.get("room_id", ""),
        agent_name="buyer-country-agent",
        output_schema=result["structured"],
        file_path=file_path,
    )


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_BUYER_COUNTRY"])
        band.on_message(lambda msg: asyncio.run(handle_message(msg)))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
