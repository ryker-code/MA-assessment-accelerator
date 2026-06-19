import asyncio
import json
import os
from datetime import datetime

from agents.shared.llm_router import LLMRouter
from agents.shared.search_tools import web_search
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import post_completion
from agents.shared.prompts import COUNTRY_AGENT_PROMPT
from agents.shared.schemas import CountryAssessment
from agents.shared.llm_utils import extract_json

router = LLMRouter()


def _format_markdown(data: CountryAssessment) -> str:
    lines = [
        f"## {data.country} — Country Assessment\n",
        f"**Status:** {data.status} | **Confidence:** {data.confidence_score:.0%}\n",
        f"### GDP Growth (5-Year)",
    ]
    for m in data.gdp_growth_5yr:
        lines.append(f"- {m.year}: {m.value:.1f}{m.unit}")

    lines.append(f"\n### Inflation Rate (5-Year)")
    if data.inflation_5yr:
        for m in data.inflation_5yr:
            lines.append(f"- {m.year}: {m.value:.1f}{m.unit}")
    else:
        lines.append(f"- Latest: {data.inflation_rate_latest:.1f}%")

    lines.append(f"\n### Currency Exchange Rate (5-Year: USD to {data.currency_code})")
    if data.currency_exchange_5yr:
        for m in data.currency_exchange_5yr:
            lines.append(f"- {m.year}: {m.value:.2f}")
    else:
        lines.append(f"- Trend: {data.currency_trend}")

    lines += [
        f"\n### Corporate Tax Rate",
        f"{data.corporate_tax_rate_pct:.1f}%",
        f"\n### Political Stability Score",
        f"{data.political_stability_score:.1f}/100",
        f"\n### Ease of Doing Business Rank",
        f"#{data.ease_of_doing_business_rank}",
        f"\n### Currency & Capital",
        f"{data.currency_repatriation_laws}",
        f"\n### Risk Flags",
    ]
    for flag in data.risk_flags:
        lines.append(f"- {flag}")
    lines += [
        f"\n### Narrative Summary",
        data.narrative_summary,
        f"\n### Data Sources",
    ]
    for src in data.data_sources:
        lines.append(f"- {src}")
    return "\n".join(lines)


async def run_country_assessment(assessment_id: str, company: str, country: str) -> dict:
    searches = [
        f"{country} GDP growth rate 2020 2024 IMF World Bank",
        f"{country} inflation rate currency exchange rate trend 2024",
        f"{country} corporate tax rate foreign investment M&A",
        f"{country} political stability ease of doing business 2024",
        f"{country} currency repatriation capital controls foreign investment",
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
        f"Target country: {country}\nTarget company: {company}\n"
        f"Assessment ID: {assessment_id}\n\n"
        f"Research data:\n{context}\n\n"
        "Produce a country assessment as a single JSON object with EXACTLY this structure "
        "(replace example values with real data from the research above):\n"
        "{\n"
        f'  "agent": "country-agent",\n'
        f'  "assessment_id": "{assessment_id}",\n'
        f'  "target_company": "{company}",\n'
        '  "buyer_company": "",\n'
        '  "timestamp": "2026-06-18T00:00:00Z",\n'
        '  "status": "COMPLETE",\n'
        '  "confidence_score": 0.8,\n'
        '  "human_review_required": false,\n'
        '  "data_sources": ["https://example.com"],\n'
        f'  "country": "{country}",\n'
        '  "gdp_growth_5yr": [{"year": 2020, "value": -0.5, "unit": "%"}, {"year": 2021, "value": 3.9, "unit": "%"}, {"year": 2022, "value": 6.1, "unit": "%"}, {"year": 2023, "value": 2.1, "unit": "%"}, {"year": 2024, "value": 2.5, "unit": "%"}],\n'
        '  "inflation_5yr": [{"year": 2020, "value": 2.1, "unit": "%"}, {"year": 2021, "value": 3.4, "unit": "%"}, {"year": 2022, "value": 7.0, "unit": "%"}, {"year": 2023, "value": 4.5, "unit": "%"}, {"year": 2024, "value": 3.2, "unit": "%"}],\n'
        '  "currency_exchange_5yr": [{"year": 2020, "value": 160.0, "unit": ""}, {"year": 2021, "value": 175.0, "unit": ""}, {"year": 2022, "value": 200.0, "unit": ""}, {"year": 2023, "value": 280.0, "unit": ""}, {"year": 2024, "value": 278.0, "unit": ""}],\n'
        '  "gdp_nominal_usd_bn": 338.0,\n'
        '  "inflation_rate_latest": 4.5,\n'
        '  "currency_code": "PKR",\n'
        '  "currency_trend": "DEPRECIATING",\n'
        '  "political_stability_score": 35.0,\n'
        '  "ease_of_doing_business_rank": 108,\n'
        '  "corporate_tax_rate_pct": 29.0,\n'
        '  "currency_repatriation_laws": "Describe the repatriation rules here.",\n'
        '  "risk_flags": ["Risk 1", "Risk 2"],\n'
        '  "narrative_summary": "2-3 paragraph narrative here."\n'
        "}\n\n"
        "Rules: currency_trend must be one of APPRECIATING, STABLE, DEPRECIATING, VOLATILE. "
        "status must be COMPLETE, PARTIAL, or NEEDS_HUMAN_REVIEW. "
        "inflation_5yr: 5 years of annual inflation data. "
        "currency_exchange_5yr: 5 years of USD to local currency exchange rates (how many local units per 1 USD). "
        "If the country IS the USA, set currency_exchange_5yr values to 1.0 each year. "
        "Return ONLY the JSON object, no other text."
    )

    response = router.complete(
        "country_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=COUNTRY_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        structured = CountryAssessment.model_validate_json(json_str)
    except Exception:
        # Partial result fallback
        structured = CountryAssessment(
            agent="country-agent",
            assessment_id=assessment_id,
            target_company=company,
            buyer_company="",
            timestamp=datetime.utcnow().isoformat() + "Z",
            status="PARTIAL",
            confidence_score=0.3,
            country=country,
            gdp_growth_5yr=[],
            gdp_nominal_usd_bn=0.0,
            inflation_rate_latest=0.0,
            currency_code="UNK",
            currency_trend="VOLATILE",
            political_stability_score=50.0,
            ease_of_doing_business_rank=999,
            corporate_tax_rate_pct=0.0,
            currency_repatriation_laws="Data unavailable",
            risk_flags=["LLM parsing failed — manual review required"],
            narrative_summary=response[:500],
            data_sources=sources[:5],
        )

    structured.data_sources = sources[:10]
    markdown = _format_markdown(structured)
    return {
        "structured": structured.model_dump(),
        "markdown": markdown,
        "confidence": structured.confidence_score,
        "sources": structured.data_sources,
    }


async def handle_message(message: dict):
    params = json.loads(message.get("content", "{}"))
    assessment_id = params["assessment_id"]
    target_company = params["target_company"]
    country = params.get("country", "")

    result = await run_country_assessment(assessment_id, target_company, country)

    file_path = save_agent_output(
        assessment_id=assessment_id,
        agent_name="country-agent",
        file_index=1,
        title=f"Country Assessment: {country}",
        content=result["markdown"],
        metadata={"confidence": f"{result['confidence']:.0%}", "sources": len(result["sources"])},
    )

    await post_completion(
        room_id=params.get("room_id", ""),
        agent_name="country-agent",
        output_schema=result["structured"],
        file_path=file_path,
    )


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_COUNTRY"])
        band.on_message(lambda msg: asyncio.run(handle_message(msg)))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
