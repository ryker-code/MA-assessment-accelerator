import asyncio
import json
import os
from datetime import datetime

from agents.shared.llm_router import LLMRouter
from agents.shared.search_tools import web_search
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import post_completion
from agents.shared.prompts import BUYER_SECTOR_AGENT_PROMPT
from agents.shared.schemas import SectorAssessment
from agents.shared.llm_utils import extract_json

router = LLMRouter()


def _format_markdown(data: SectorAssessment, buyer_company: str) -> str:
    lines = [
        f"## {data.sector} — Buyer Sector Assessment (Buy-Side: {buyer_company})\n",
        f"**Status:** {data.status} | **Confidence:** {data.confidence_score:.0%}\n",
        f"### Buyer's Market Position",
        f"- **Sector:** {data.sector} ({data.country})",
        f"- **Market Size:** USD {data.market_size_usd_bn:.1f}bn",
        f"- **Growth Rate:** {data.market_growth_rate_pct:.1f}% p.a.",
        f"- **Competitive Risk:** {data.regulatory_risk}",
        f"- **Tech Disruption Risk:** {data.technology_disruption_risk}",
        f"\n### Buyer's Competitive Gaps (KPIs)",
    ]
    for k, v in data.sector_specific_kpis.items():
        lines.append(f"- **{k}:** {v}")
    lines.append(f"\n### Key Regulatory Considerations (Antitrust)")
    for reg in data.key_regulations:
        lines.append(f"- {reg}")
    lines.append(f"\n### Risk Flags")
    for flag in data.risk_flags:
        lines.append(f"- {flag}")
    lines += [f"\n### Narrative Summary", data.narrative_summary]
    return "\n".join(lines)


async def run_buyer_sector_assessment(
    assessment_id: str, buyer_company: str, buyer_country: str, buyer_sector: str, target_country: str = ""
) -> dict:
    searches = [
        f"{buyer_company} market share revenue 2024 2025 {buyer_sector}",
        f"{buyer_company} technology gaps strategic priorities 2025 2026 investor day",
        f"{buyer_company} antitrust regulatory {target_country} expansion approval",
        f"{buyer_sector} consolidation M&A trends 2025 2026 cross-border",
        f"{buyer_company} international expansion strategy 2025 2026",
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
        f"Buyer company: {buyer_company}\nBuyer country: {buyer_country}\n"
        f"Buyer sector: {buyer_sector}\nTarget country: {target_country}\n"
        f"Assessment ID: {assessment_id}\n\n"
        f"Research data:\n{context}\n\n"
        "Produce a buyer sector assessment as a single JSON object:\n"
        "{\n"
        f'  "agent": "buyer-sector-agent",\n'
        f'  "assessment_id": "{assessment_id}",\n'
        '  "target_company": "",\n'
        f'  "buyer_company": "{buyer_company}",\n'
        '  "timestamp": "2026-06-18T00:00:00Z",\n'
        '  "status": "COMPLETE",\n'
        '  "confidence_score": 0.8,\n'
        '  "human_review_required": false,\n'
        '  "data_sources": ["https://example.com"],\n'
        f'  "sector": "{buyer_sector}",\n'
        f'  "country": "{buyer_country}",\n'
        '  "market_size_usd_bn": 10.0,\n'
        '  "market_growth_rate_pct": 4.0,\n'
        '  "num_major_players": 4,\n'
        '  "top_3_players": ["Player A", "Player B", "Player C"],\n'
        '  "regulatory_risk": "LOW",\n'
        '  "key_regulations": ["Antitrust review required for cross-border deals"],\n'
        '  "technology_disruption_risk": "MEDIUM",\n'
        '  "sector_specific_kpis": {"REPLACE_WITH_RELEVANT_KPIs_FOR_THIS_SECTOR": 0.0},\n'
        '  "risk_flags": ["Antitrust risk in target market"],\n'
        '  "narrative_summary": "Frame around: why does buyer need exposure to target sector/market?"\n'
        "}\n\n"
        f"CRITICAL: sector_specific_kpis must contain 4-6 KPIs most relevant to {buyer_sector} showing buyer's competitive position. "
        "For telecom buyer: use buyer_market_share_pct, gap_vs_leader_pct, ARPU_USD, mobile_subscribers_m, broadband_penetration_pct. "
        "For tower/passive infra buyer: use tenancy_ratio, towers_owned, revenue_per_site_usd_monthly, buyer_market_share_pct, gap_vs_leader_pct. "
        "For cloud/AI buyer: use gpu_utilization_pct, compute_cost_per_hour_usd, buyer_market_share_pct, gap_vs_leader_pct. "
        "Rules: regulatory_risk and technology_disruption_risk must be HIGH, MEDIUM, or LOW. Return ONLY JSON."
    )

    response = router.complete(
        "buyer_sector_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=BUYER_SECTOR_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        structured = SectorAssessment.model_validate_json(json_str)
    except Exception:
        structured = SectorAssessment(
            agent="buyer-sector-agent",
            assessment_id=assessment_id,
            target_company="",
            buyer_company=buyer_company,
            timestamp=datetime.utcnow().isoformat() + "Z",
            status="PARTIAL",
            confidence_score=0.3,
            sector=buyer_sector,
            country=buyer_country,
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
    markdown = _format_markdown(structured, buyer_company)
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
    buyer_sector = params.get("buyer_sector", params.get("sector", ""))
    target_country = params.get("country", "")

    result = await run_buyer_sector_assessment(
        assessment_id, buyer_company, buyer_country, buyer_sector, target_country
    )

    file_path = save_agent_output(
        assessment_id=assessment_id,
        agent_name="buyer-sector-agent",
        file_index=5,
        title=f"Buyer Sector Assessment: {buyer_sector} ({buyer_company})",
        content=result["markdown"],
        metadata={"confidence": f"{result['confidence']:.0%}", "sources": len(result["sources"])},
    )

    await post_completion(
        room_id=params.get("room_id", ""),
        agent_name="buyer-sector-agent",
        output_schema=result["structured"],
        file_path=file_path,
    )


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_BUYER_SECTOR"])
        band.on_message(lambda msg: asyncio.run(handle_message(msg)))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
