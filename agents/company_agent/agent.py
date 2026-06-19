import asyncio
import json
import os
from datetime import datetime

from agents.shared.llm_router import LLMRouter
from agents.shared.search_tools import web_search
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import post_completion
from agents.shared.prompts import COMPANY_AGENT_PROMPT
from agents.shared.schemas import CompanyAssessment
from agents.shared.llm_utils import extract_json

router = LLMRouter()


def _format_markdown(data: CompanyAssessment) -> str:
    side = "Sell-Side" if not data.is_buy_side else "Buy-Side"
    lines = [
        f"## {data.company_name} — Company Assessment ({side})\n",
        f"**Status:** {data.status} | **Confidence:** {data.confidence_score:.0%}\n",
    ]
    if data.financials_5yr:
        lines.append("### Financials (5-Year)")
        lines.append("| Year | Revenue (USDm) | Rev Growth % | EBITDA (USDm) | EBITDA % | Net Profit (USDm) | NP % | EPS (USD) | CapEx (USDm) | Net Debt (USDm) |")
        lines.append("|------|----------------|--------------|---------------|----------|-------------------|------|-----------|--------------|-----------------|")
        for yr in data.financials_5yr:
            lines.append(
                f"| {yr.get('year','')} "
                f"| {yr.get('revenue','—')} "
                f"| {yr.get('revenue_growth_pct','—')} "
                f"| {yr.get('ebitda','—')} "
                f"| {yr.get('ebitda_margin_pct','—')} "
                f"| {yr.get('net_profit','—')} "
                f"| {yr.get('net_profit_margin_pct','—')} "
                f"| {yr.get('eps','—')} "
                f"| {yr.get('capex','—')} "
                f"| {yr.get('net_debt','—')} |"
            )
    else:
        lines += [
            "### Financial Snapshot",
            f"- **Revenue:** USD {data.revenue_latest_usd_m:.1f}m",
            f"- **EBITDA:** USD {data.ebitda_latest_usd_m:.1f}m ({data.ebitda_margin_pct:.1f}% margin)",
            f"- **Net Debt:** USD {data.net_debt_usd_m:.1f}m ({data.net_debt_to_ebitda:.1f}x EBITDA)",
            f"- **CapEx:** USD {data.capex_usd_m:.1f}m",
            f"- **Revenue Growth:** {data.revenue_growth_rate_pct:.1f}% p.a.",
        ]

    lines += [
        f"\n### Management",
        f"- **Quality Score:** {data.management_quality_score:.1f}/10",
        f"\n### Key Shareholders",
    ]
    for sh in data.key_shareholders:
        lines.append(f"- {sh.get('name', 'N/A')}: {sh.get('stake_pct', 'N/A')}% ({sh.get('type', '')})")
    lines.append(f"\n### Recent Strategic Moves")
    for move in data.recent_strategic_moves:
        lines.append(f"- {move}")
    lines.append(f"\n### Operational KPIs")
    for k, v in data.sector_kpis.items():
        lines.append(f"- **{k}:** {v}")
    lines.append(f"\n### Risks")
    for flag in data.risk_flags:
        lines.append(f"- {flag}")
    lines += [f"\n### Narrative Summary", data.narrative_summary]
    lines.append(f"\n### Data Sources")
    for src in data.data_sources:
        lines.append(f"- {src}")
    return "\n".join(lines)


async def run_company_assessment(assessment_id: str, company: str, buyer_company: str = "") -> dict:
    searches = [
        f"{company} annual report investor relations 2024",
        f"{company} revenue EBITDA financial results 2024",
        f"{company} CEO management team executive 2024",
        f"{company} shareholders ownership structure",
        f"{company} strategic announcement product launch 2024 2025",
        f"{company} quarterly results latest earnings",
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
        f"Target company: {company}\nBuyer company: {buyer_company}\n"
        f"Assessment ID: {assessment_id}\n\n"
        f"Research data:\n{context}\n\n"
        "Produce a company assessment as a single JSON object with EXACTLY this structure:\n"
        "{\n"
        f'  "agent": "company-agent",\n'
        f'  "assessment_id": "{assessment_id}",\n'
        f'  "target_company": "{company}",\n'
        f'  "buyer_company": "{buyer_company}",\n'
        '  "timestamp": "2026-06-18T00:00:00Z",\n'
        '  "status": "COMPLETE",\n'
        '  "confidence_score": 0.75,\n'
        '  "human_review_required": false,\n'
        '  "data_sources": ["https://example.com"],\n'
        f'  "company_name": "{company}",\n'
        '  "is_buy_side": false,\n'
        '  "revenue_latest_usd_m": 500.0,\n'
        '  "ebitda_latest_usd_m": 150.0,\n'
        '  "ebitda_margin_pct": 30.0,\n'
        '  "net_debt_usd_m": 200.0,\n'
        '  "net_debt_to_ebitda": 1.3,\n'
        '  "capex_usd_m": 80.0,\n'
        '  "revenue_growth_rate_pct": 5.0,\n'
        '  "key_shareholders": [{"name": "Telenor ASA", "stake_pct": 55.0, "type": "strategic"}],\n'
        '  "management_quality_score": 7.0,\n'
        '  "recent_strategic_moves": ["Move 1", "Move 2"],\n'
        '  "sector_kpis": {"subscribers_m": 45.0, "ARPU_USD": 3.5},\n'
        '  "risk_flags": ["Risk 1"],\n'
        '  "narrative_summary": "2-3 paragraph narrative here.",\n'
        '  "financials_5yr": [\n'
        '    {"year": 2020, "revenue": 450.0, "revenue_growth_pct": -5.0, "ebitda": 130.0, "ebitda_margin_pct": 28.9, "net_profit": 45.0, "net_profit_margin_pct": 10.0, "eps": 0.45, "capex": 70.0, "net_debt": 210.0},\n'
        '    {"year": 2021, "revenue": 470.0, "revenue_growth_pct": 4.4, "ebitda": 138.0, "ebitda_margin_pct": 29.4, "net_profit": 48.0, "net_profit_margin_pct": 10.2, "eps": 0.48, "capex": 72.0, "net_debt": 205.0},\n'
        '    {"year": 2022, "revenue": 490.0, "revenue_growth_pct": 4.3, "ebitda": 145.0, "ebitda_margin_pct": 29.6, "net_profit": 52.0, "net_profit_margin_pct": 10.6, "eps": 0.52, "capex": 75.0, "net_debt": 200.0},\n'
        '    {"year": 2023, "revenue": 495.0, "revenue_growth_pct": 1.0, "ebitda": 148.0, "ebitda_margin_pct": 29.9, "net_profit": 50.0, "net_profit_margin_pct": 10.1, "eps": 0.50, "capex": 78.0, "net_debt": 200.0},\n'
        '    {"year": 2024, "revenue": 500.0, "revenue_growth_pct": 1.0, "ebitda": 150.0, "ebitda_margin_pct": 30.0, "net_profit": 55.0, "net_profit_margin_pct": 11.0, "eps": 0.55, "capex": 80.0, "net_debt": 200.0}\n'
        '  ],\n'
        '  "cash_position_usd_m": null,\n'
        '  "acquisition_capacity_usd_m": null,\n'
        '  "stated_strategic_priorities": null,\n'
        '  "previous_acquisitions": null\n'
        "}\n\n"
        "Rules: status must be COMPLETE, PARTIAL, or NEEDS_HUMAN_REVIEW. is_buy_side must be false. "
        "financials_5yr: provide actual 5-year financial data from the research. All monetary values in USD millions. "
        "Return ONLY the JSON object, no other text."
    )

    response = router.complete(
        "company_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=COMPANY_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        structured = CompanyAssessment.model_validate_json(json_str)
    except Exception:
        structured = CompanyAssessment(
            agent="company-agent",
            assessment_id=assessment_id,
            target_company=company,
            buyer_company=buyer_company,
            timestamp=datetime.utcnow().isoformat() + "Z",
            status="PARTIAL",
            confidence_score=0.3,
            company_name=company,
            is_buy_side=False,
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
    buyer_company = params.get("buyer_company", "")

    result = await run_company_assessment(assessment_id, target_company, buyer_company)

    file_path = save_agent_output(
        assessment_id=assessment_id,
        agent_name="company-agent",
        file_index=3,
        title=f"Company Assessment: {target_company}",
        content=result["markdown"],
        metadata={"confidence": f"{result['confidence']:.0%}", "sources": len(result["sources"])},
    )

    await post_completion(
        room_id=params.get("room_id", ""),
        agent_name="company-agent",
        output_schema=result["structured"],
        file_path=file_path,
    )


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_COMPANY"])
        band.on_message(lambda msg: asyncio.run(handle_message(msg)))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
