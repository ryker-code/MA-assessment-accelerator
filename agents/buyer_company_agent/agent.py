import asyncio
import json
import os
from datetime import datetime

from agents.shared.llm_router import LLMRouter
from agents.shared.search_tools import web_search
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import post_completion
from agents.shared.prompts import BUYER_COMPANY_AGENT_PROMPT
from agents.shared.schemas import CompanyAssessment
from agents.shared.llm_utils import extract_json

router = LLMRouter()


def _format_markdown(data: CompanyAssessment) -> str:
    lines = [
        f"## {data.company_name} — Buyer Company Assessment (Buy-Side)\n",
        f"**Status:** {data.status} | **Confidence:** {data.confidence_score:.0%}\n",
        f"### Financial Snapshot",
        f"- **Revenue:** USD {data.revenue_latest_usd_m:.1f}m",
        f"- **EBITDA:** USD {data.ebitda_latest_usd_m:.1f}m ({data.ebitda_margin_pct:.1f}% margin)",
        f"- **Net Debt:** USD {data.net_debt_usd_m:.1f}m ({data.net_debt_to_ebitda:.1f}x EBITDA)",
        f"- **Revenue Growth:** {data.revenue_growth_rate_pct:.1f}% p.a.",
        f"\n### Acquisition Capacity",
        f"- **Cash Position:** USD {data.cash_position_usd_m or 0:.1f}m",
        f"- **Estimated Acquisition Capacity:** USD {data.acquisition_capacity_usd_m or 0:.1f}m",
        f"\n### Strategic Priorities",
    ]
    for p in (data.stated_strategic_priorities or []):
        lines.append(f"- {p}")
    lines.append(f"\n### Previous Acquisitions")
    for acq in (data.previous_acquisitions or []):
        lines.append(f"- {acq}")
    lines.append(f"\n### Management Quality")
    lines.append(f"Score: {data.management_quality_score:.1f}/10")
    lines.append(f"\n### Recent Strategic Moves")
    for move in data.recent_strategic_moves:
        lines.append(f"- {move}")
    lines.append(f"\n### Risk Flags")
    for flag in data.risk_flags:
        lines.append(f"- {flag}")
    lines += [f"\n### Narrative Summary", data.narrative_summary]
    return "\n".join(lines)


async def run_buyer_company_assessment(
    assessment_id: str, buyer_company: str, buyer_country: str
) -> dict:
    searches = [
        f"{buyer_company} balance sheet cash net debt 2024 annual report",
        f"{buyer_company} acquisition history M&A track record integration",
        f"{buyer_company} CEO strategic priorities investor day 2024 2025",
        f"{buyer_company} credit rating debt capacity leverage",
        f"{buyer_company} share price market cap enterprise value 2024",
    ]
    research_data = []
    for q in searches:
        try:
            results = web_search(q, agent_type="company")
            research_data.extend(results)
        except Exception:
            pass

    sources = list({r["url"] for r in research_data if r.get("url")})
    context = "\n\n".join([
        f"Source: {r.get('url', 'unknown')}\n{r.get('content', '')}"
        for r in research_data[:12]
    ])

    prompt = (
        f"Buyer company: {buyer_company}\nBuyer country: {buyer_country}\n"
        f"Assessment ID: {assessment_id}\n\n"
        f"Research data:\n{context}\n\n"
        "Produce a buyer company assessment as a single JSON object:\n"
        "{\n"
        f'  "agent": "buyer-company-agent",\n'
        f'  "assessment_id": "{assessment_id}",\n'
        '  "target_company": "",\n'
        f'  "buyer_company": "{buyer_company}",\n'
        '  "timestamp": "2026-06-18T00:00:00Z",\n'
        '  "status": "COMPLETE",\n'
        '  "confidence_score": 0.8,\n'
        '  "human_review_required": false,\n'
        '  "data_sources": ["https://example.com"],\n'
        f'  "company_name": "{buyer_company}",\n'
        '  "is_buy_side": true,\n'
        '  "revenue_latest_usd_m": 15000.0,\n'
        '  "ebitda_latest_usd_m": 6000.0,\n'
        '  "ebitda_margin_pct": 40.0,\n'
        '  "net_debt_usd_m": 5000.0,\n'
        '  "net_debt_to_ebitda": 0.8,\n'
        '  "capex_usd_m": 2000.0,\n'
        '  "revenue_growth_rate_pct": 8.0,\n'
        '  "key_shareholders": [{"name": "Saudi government", "stake_pct": 64.0, "type": "government"}],\n'
        '  "management_quality_score": 8.0,\n'
        '  "recent_strategic_moves": ["Move 1", "Move 2"],\n'
        '  "sector_kpis": {"subscribers_m": 35.0, "ARPU_USD": 25.0},\n'
        '  "risk_flags": ["Integration risk from prior acquisitions"],\n'
        '  "narrative_summary": "Comprehensive buyer profile narrative here.",\n'
        '  "cash_position_usd_m": 8000.0,\n'
        '  "acquisition_capacity_usd_m": 12000.0,\n'
        '  "stated_strategic_priorities": ["Expand into emerging markets", "Digital transformation"],\n'
        '  "previous_acquisitions": ["Acquisition 1 (2021)", "Acquisition 2 (2023)"]\n'
        "}\n\n"
        "Rules: is_buy_side must be true. Populate ALL buy-side specific fields. "
        "acquisition_capacity = cash + conservative debt headroom (e.g. 1-2x current EBITDA). "
        "Return ONLY JSON."
    )

    response = router.complete(
        "buyer_company_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=BUYER_COMPANY_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        structured = CompanyAssessment.model_validate_json(json_str)
    except Exception:
        structured = CompanyAssessment(
            agent="buyer-company-agent",
            assessment_id=assessment_id,
            target_company="",
            buyer_company=buyer_company,
            timestamp=datetime.utcnow().isoformat() + "Z",
            status="PARTIAL",
            confidence_score=0.3,
            company_name=buyer_company,
            is_buy_side=True,
            revenue_latest_usd_m=0.0,
            ebitda_latest_usd_m=0.0,
            ebitda_margin_pct=0.0,
            net_debt_usd_m=0.0,
            net_debt_to_ebitda=0.0,
            capex_usd_m=0.0,
            revenue_growth_rate_pct=0.0,
            key_shareholders=[],
            management_quality_score=5.0,
            recent_strategic_moves=[],
            sector_kpis={},
            risk_flags=["LLM parsing failed — manual review required"],
            narrative_summary=response[:500],
            data_sources=sources[:5],
            cash_position_usd_m=None,
            acquisition_capacity_usd_m=None,
            stated_strategic_priorities=None,
            previous_acquisitions=None,
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
    buyer_company = params["buyer_company"]
    buyer_country = params.get("buyer_country", "")

    result = await run_buyer_company_assessment(assessment_id, buyer_company, buyer_country)

    file_path = save_agent_output(
        assessment_id=assessment_id,
        agent_name="buyer-company-agent",
        file_index=6,
        title=f"Buyer Company Assessment: {buyer_company}",
        content=result["markdown"],
        metadata={"confidence": f"{result['confidence']:.0%}", "sources": len(result["sources"])},
    )

    await post_completion(
        room_id=params.get("room_id", ""),
        agent_name="buyer-company-agent",
        output_schema=result["structured"],
        file_path=file_path,
    )


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_BUYER_COMPANY"])
        band.on_message(lambda msg: asyncio.run(handle_message(msg)))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
