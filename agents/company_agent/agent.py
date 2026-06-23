import asyncio
import json
import os
from datetime import datetime

from agents.shared.llm_router import LLMRouter
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
    if data.company_overview:
        lines += [f"\n### Company Overview", data.company_overview]
    if data.stated_strategic_priorities:
        lines.append(f"\n### Strategic Priorities")
        for p in data.stated_strategic_priorities:
            lines.append(f"- {p}")
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
    prompt = (
        f"You are conducting an M&A due-diligence assessment of {company} as a potential acquisition target"
        f"{f' for {buyer_company}' if buyer_company else ''}.\n\n"
        f"Use your Google Search tool to research {company} thoroughly. Search for:\n"
        f"- Latest annual/quarterly financial results (revenue, EBITDA, net profit, capex, net debt)\n"
        f"- 5-year financial history (2021-2025)\n"
        f"- Key shareholders and ownership structure\n"
        f"- CEO and senior management team quality\n"
        f"- Recent strategic moves, acquisitions, partnerships\n"
        f"- Sector KPIs relevant to {company}'s industry\n"
        f"- Key risks and competitive threats\n\n"
        "After researching, return ONLY a single JSON object with EXACTLY this structure "
        "(replace example values with real data you found):\n"
        "{\n"
        f'  "agent": "seller-company-agent",\n'
        f'  "assessment_id": "{assessment_id}",\n'
        f'  "target_company": "{company}",\n'
        f'  "buyer_company": "{buyer_company}",\n'
        f'  "timestamp": "{datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}",\n'
        '  "status": "COMPLETE",\n'
        '  "confidence_score": 0.85,\n'
        '  "human_review_required": false,\n'
        '  "data_sources": ["https://actual-source-you-used.com"],\n'
        f'  "company_name": "{company}",\n'
        '  "is_buy_side": false,\n'
        '  "company_overview": "- Brief description of what the company does\\n- Core products/services and competitive position\\n- Geographic footprint and key markets\\n- Key customers and partnerships",\n'
        '  "revenue_latest_usd_m": 500.0,\n'
        '  "ebitda_latest_usd_m": 150.0,\n'
        '  "ebitda_margin_pct": 30.0,\n'
        '  "net_debt_usd_m": 200.0,\n'
        '  "net_debt_to_ebitda": 1.3,\n'
        '  "capex_usd_m": 80.0,\n'
        '  "revenue_growth_rate_pct": 5.0,\n'
        '  "key_shareholders": [{"name": "Shareholder Name", "stake_pct": 55.0, "type": "strategic"}],\n'
        '  "management_quality_score": 7.0,\n'
        '  "recent_strategic_moves": ["Actual move 1", "Actual move 2"],\n'
        '  "sector_kpis": {"kpi_name": "value"},\n'
        '  "risk_flags": ["Actual risk 1"],\n'
        '  "narrative_summary": "2-3 paragraph narrative based on your research.",\n'
        '  "financials_5yr": [\n'
        '    {"year": 2021, "revenue": 450.0, "revenue_growth_pct": 4.0, "ebitda": 130.0, "ebitda_margin_pct": 28.9, "net_profit": 45.0, "net_profit_margin_pct": 10.0, "eps": 0.45, "capex": 70.0, "net_debt": 210.0},\n'
        '    {"year": 2022, "revenue": 470.0, "revenue_growth_pct": 4.4, "ebitda": 138.0, "ebitda_margin_pct": 29.4, "net_profit": 48.0, "net_profit_margin_pct": 10.2, "eps": 0.48, "capex": 72.0, "net_debt": 205.0},\n'
        '    {"year": 2023, "revenue": 490.0, "revenue_growth_pct": 4.3, "ebitda": 145.0, "ebitda_margin_pct": 29.6, "net_profit": 52.0, "net_profit_margin_pct": 10.6, "eps": 0.52, "capex": 75.0, "net_debt": 200.0},\n'
        '    {"year": 2024, "revenue": 495.0, "revenue_growth_pct": 1.0, "ebitda": 148.0, "ebitda_margin_pct": 29.9, "net_profit": 50.0, "net_profit_margin_pct": 10.1, "eps": 0.50, "capex": 78.0, "net_debt": 200.0},\n'
        '    {"year": 2025, "revenue": 520.0, "revenue_growth_pct": 5.0, "ebitda": 158.0, "ebitda_margin_pct": 30.4, "net_profit": 58.0, "net_profit_margin_pct": 11.2, "eps": 0.58, "capex": 82.0, "net_debt": 195.0}\n'
        '  ],\n'
        '  "cash_position_usd_m": null,\n'
        '  "acquisition_capacity_usd_m": null,\n'
        '  "stated_strategic_priorities": ["Actual strategic priority 1 from latest IR/annual report", "Actual strategic priority 2"],\n'
        '  "previous_acquisitions": null\n'
        "}\n\n"
        "Rules: all monetary values in USD millions. status must be COMPLETE, PARTIAL, or NEEDS_HUMAN_REVIEW. "
        "is_buy_side must be false. financials_5yr MUST cover years 2021, 2022, 2023, 2024, 2025 — do NOT use 2020. "
        "company_overview: 4-6 concise bullet points starting with '- ' covering: what the company does, key products/services, geographic footprint with specific metrics (e.g. data center MW, subscribers), key customers/partners. "
        "stated_strategic_priorities: populate with ACTUAL stated priorities from the company's latest investor relations materials. "
        "Return ONLY the JSON object, no other text, no markdown fences."
    )

    response = router.complete(
        "company_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=COMPANY_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        import json as _json
        parsed = _json.loads(json_str)
        # Backfill required envelope fields the model may omit
        parsed.setdefault("agent", "seller-company-agent")
        parsed.setdefault("assessment_id", assessment_id)
        parsed.setdefault("target_company", company)
        parsed.setdefault("buyer_company", buyer_company)
        parsed.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
        parsed.setdefault("status", "COMPLETE")
        parsed.setdefault("confidence_score", 0.75)
        parsed.setdefault("company_name", company)
        parsed.setdefault("is_buy_side", False)
        parsed.setdefault("company_overview", None)
        parsed.setdefault("key_shareholders", [])
        parsed.setdefault("recent_strategic_moves", [])
        parsed.setdefault("sector_kpis", {})
        parsed.setdefault("risk_flags", [])
        # Coerce null list fields to empty list
        for field in ("financials_5yr", "key_shareholders", "recent_strategic_moves", "risk_flags"):
            if parsed.get(field) is None:
                parsed[field] = []
        # Coerce null float fields to 0.0
        for field in ("revenue_latest_usd_m", "ebitda_latest_usd_m", "ebitda_margin_pct",
                      "net_debt_usd_m", "net_debt_to_ebitda", "capex_usd_m",
                      "revenue_growth_rate_pct", "management_quality_score"):
            if parsed.get(field) is None:
                parsed[field] = 0.0
        # Normalize key_shareholders: model sometimes returns list of strings instead of dicts
        raw_sh = parsed.get("key_shareholders", [])
        parsed["key_shareholders"] = [
            s if isinstance(s, dict) else {"name": str(s), "stake_pct": 0, "type": "unknown"}
            for s in raw_sh
        ]
        # Normalize previous_acquisitions: model sometimes returns list of dicts instead of strings
        raw_acq = parsed.get("previous_acquisitions") or []
        parsed["previous_acquisitions"] = [
            a if isinstance(a, str) else f"{a.get('company', str(a))} ({a.get('year', a.get('date', ''))})"
            for a in raw_acq
        ]
        structured = CompanyAssessment.model_validate(parsed)
    except Exception:
        structured = CompanyAssessment(
            agent="seller-company-agent",
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
            data_sources=[],
        )

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
        agent_name="seller-company-agent",
        file_index=3,
        title=f"Company Assessment: {target_company}",
        content=result["markdown"],
        metadata={"confidence": f"{result['confidence']:.0%}", "sources": len(result["sources"])},
    )

    await post_completion(
        room_id=params.get("room_id", ""),
        agent_name="seller-company-agent",
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
