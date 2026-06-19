import asyncio
import json
import os
from datetime import datetime

from agents.shared.llm_router import LLMRouter
from agents.shared.search_tools import web_search
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import post_completion
from agents.shared.prompts import SECTOR_AGENT_PROMPT
from agents.shared.schemas import SectorAssessment
from agents.shared.llm_utils import extract_json

router = LLMRouter()


def _format_markdown(data: SectorAssessment) -> str:
    lines = [
        f"## {data.sector} Sector — {data.country}\n",
        f"**Status:** {data.status} | **Confidence:** {data.confidence_score:.0%}\n",
        f"### Market Overview",
        f"- **Market Size (Latest):** USD {data.market_size_usd_bn:.1f}bn",
        f"- **Growth Rate:** {data.market_growth_rate_pct:.1f}% p.a.",
        f"- **Major Players:** {data.num_major_players}",
        f"- **Top 3:** {', '.join(data.top_3_players)}",
    ]
    if data.market_size_5yr:
        lines.append(f"\n#### Market Size History (5-Year, USD bn)")
        for m in data.market_size_5yr:
            lines.append(f"- {m.year}: {m.value:.1f}")
    if data.top_players_market_share:
        lines.append(f"\n#### Market Share (%)")
        for player, share in data.top_players_market_share.items():
            lines.append(f"- {player}: {share}")

    lines += [f"\n### Risk Assessment",
        f"- **Regulatory Risk:** {data.regulatory_risk}",
        f"- **Technology Disruption Risk:** {data.technology_disruption_risk}",
    ]
    for flag in data.risk_flags:
        lines.append(f"- {flag}")

    lines.append(f"\n### Key Regulations")
    for reg in data.key_regulations:
        lines.append(f"- {reg}")

    lines.append(f"\n### Sector KPIs")
    for k, v in data.sector_specific_kpis.items():
        lines.append(f"- **{k}:** {v}")

    lines += [f"\n### Narrative Summary", data.narrative_summary]

    lines.append(f"\n### Data Sources")
    for src in data.data_sources:
        lines.append(f"- {src}")

    return "\n".join(lines)


async def run_sector_assessment(assessment_id: str, company: str, sector: str, country: str) -> dict:
    searches = [
        f"{sector} {country} market size revenue 2024 2025",
        f"{sector} {country} major players market share competition",
        f"{sector} {country} regulatory environment compliance requirements",
        f"{sector} technology disruption trends 2024 2025",
        f"{sector} {country} M&A deals consolidation recent",
    ]
    research_data = []
    for q in searches:
        try:
            results = web_search(q, agent_type="sector")
            research_data.extend(results)
        except Exception:
            pass

    sources = list({r["url"] for r in research_data if r.get("url")})
    context = "\n\n".join([
        f"Source: {r.get('url', 'unknown')}\n{r.get('content', '')}"
        for r in research_data[:10]
    ])

    prompt = (
        f"Target company: {company}\nSector: {sector}\nCountry: {country}\n"
        f"Assessment ID: {assessment_id}\n\n"
        f"Research data:\n{context}\n\n"
        "Produce a sector assessment as a single JSON object with EXACTLY this structure:\n"
        "{\n"
        f'  "agent": "sector-agent",\n'
        f'  "assessment_id": "{assessment_id}",\n'
        f'  "target_company": "{company}",\n'
        '  "buyer_company": "",\n'
        '  "timestamp": "2026-06-18T00:00:00Z",\n'
        '  "status": "COMPLETE",\n'
        '  "confidence_score": 0.8,\n'
        '  "human_review_required": false,\n'
        '  "data_sources": ["https://example.com"],\n'
        f'  "sector": "{sector}",\n'
        f'  "country": "{country}",\n'
        '  "market_size_usd_bn": 5.0,\n'
        '  "market_size_5yr": [{"year": 2020, "value": 3.5, "unit": "USD bn"}, {"year": 2021, "value": 3.9, "unit": "USD bn"}, {"year": 2022, "value": 4.2, "unit": "USD bn"}, {"year": 2023, "value": 4.6, "unit": "USD bn"}, {"year": 2024, "value": 5.0, "unit": "USD bn"}],\n'
        '  "top_players_market_share": {"Player A": 25.0, "Player B": 20.0, "Player C": 15.0, "Others": 40.0},\n'
        '  "market_growth_rate_pct": 4.5,\n'
        '  "num_major_players": 5,\n'
        '  "top_3_players": ["Player A", "Player B", "Player C"],\n'
        '  "regulatory_risk": "MEDIUM",\n'
        '  "key_regulations": ["Regulation 1", "Regulation 2"],\n'
        '  "technology_disruption_risk": "MEDIUM",\n'
        '  "sector_specific_kpis": {"ARPU_USD": 5.0, "churn_rate_pct": 2.5},\n'
        '  "risk_flags": ["Risk 1"],\n'
        '  "narrative_summary": "2-3 paragraph narrative here."\n'
        "}\n\n"
        "Rules: regulatory_risk and technology_disruption_risk must be HIGH, MEDIUM, or LOW. "
        "status must be COMPLETE, PARTIAL, or NEEDS_HUMAN_REVIEW. "
        "market_size_5yr: 5 years of market size data in USD bn. "
        "top_players_market_share: dict of {player_name: market_share_pct} including 'Others'. "
        "Return ONLY the JSON object, no other text."
    )

    response = router.complete(
        "sector_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=SECTOR_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        structured = SectorAssessment.model_validate_json(json_str)
    except Exception:
        structured = SectorAssessment(
            agent="sector-agent",
            assessment_id=assessment_id,
            target_company=company,
            buyer_company="",
            timestamp=datetime.utcnow().isoformat() + "Z",
            status="PARTIAL",
            confidence_score=0.3,
            sector=sector,
            country=country,
            market_size_usd_bn=0.0,
            market_growth_rate_pct=0.0,
            num_major_players=0,
            top_3_players=[],
            regulatory_risk="MEDIUM",
            key_regulations=[],
            technology_disruption_risk="MEDIUM",
            sector_specific_kpis={},
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
    sector = params.get("sector", "")
    country = params.get("country", "")

    result = await run_sector_assessment(assessment_id, target_company, sector, country)

    file_path = save_agent_output(
        assessment_id=assessment_id,
        agent_name="sector-agent",
        file_index=2,
        title=f"Sector Assessment: {sector} ({country})",
        content=result["markdown"],
        metadata={"confidence": f"{result['confidence']:.0%}", "sources": len(result["sources"])},
    )

    await post_completion(
        room_id=params.get("room_id", ""),
        agent_name="sector-agent",
        output_schema=result["structured"],
        file_path=file_path,
    )


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_SECTOR"])
        band.on_message(lambda msg: asyncio.run(handle_message(msg)))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
