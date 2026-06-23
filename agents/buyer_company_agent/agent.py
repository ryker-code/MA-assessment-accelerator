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
    ]
    if data.company_overview:
        lines += [f"\n### Company Overview", data.company_overview]
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
            f"- **Revenue Growth:** {data.revenue_growth_rate_pct:.1f}% p.a.",
        ]

    lines += [
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
    lines.append(f"\n### Key Shareholders")
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


async def run_buyer_company_assessment(
    assessment_id: str, buyer_company: str, buyer_country: str
) -> dict:
    searches = [
        f"{buyer_company} annual revenue EBITDA financial results 2024 2025",
        f"{buyer_company} balance sheet cash net debt 2025 annual report",
        f"{buyer_company} acquisition history M&A track record 2022 2023 2024 2025",
        f"{buyer_company} CEO strategic priorities investor day 2025 2026",
        f"{buyer_company} share price market cap enterprise value 2025",
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
        '  "company_overview": "- Leading company in its sector with strong competitive position\\n- Core products/services: [list key offerings]\\n- Geographic footprint: [key markets/countries]\\n- Key customers: [top customers]",\n'
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
        '  "financials_5yr": [\n'
        '    {"year": 2021, "revenue": 13000.0, "revenue_growth_pct": 3.0, "ebitda": 5000.0, "ebitda_margin_pct": 38.5, "net_profit": 2000.0, "net_profit_margin_pct": 15.4, "eps": 2.00, "capex": 1800.0, "net_debt": 6000.0},\n'
        '    {"year": 2022, "revenue": 13500.0, "revenue_growth_pct": 3.8, "ebitda": 5200.0, "ebitda_margin_pct": 38.5, "net_profit": 2100.0, "net_profit_margin_pct": 15.6, "eps": 2.10, "capex": 1900.0, "net_debt": 5800.0},\n'
        '    {"year": 2023, "revenue": 14000.0, "revenue_growth_pct": 3.7, "ebitda": 5500.0, "ebitda_margin_pct": 39.3, "net_profit": 2200.0, "net_profit_margin_pct": 15.7, "eps": 2.20, "capex": 1950.0, "net_debt": 5500.0},\n'
        '    {"year": 2024, "revenue": 14500.0, "revenue_growth_pct": 3.6, "ebitda": 5700.0, "ebitda_margin_pct": 39.3, "net_profit": 2300.0, "net_profit_margin_pct": 15.9, "eps": 2.30, "capex": 2000.0, "net_debt": 5200.0},\n'
        '    {"year": 2025, "revenue": 15000.0, "revenue_growth_pct": 3.4, "ebitda": 6000.0, "ebitda_margin_pct": 40.0, "net_profit": 2400.0, "net_profit_margin_pct": 16.0, "eps": 2.40, "capex": 2000.0, "net_debt": 5000.0}\n'
        '  ],\n'
        '  "cash_position_usd_m": 8000.0,\n'
        '  "acquisition_capacity_usd_m": 12000.0,\n'
        '  "stated_strategic_priorities": ["Expand into emerging markets", "Digital transformation"],\n'
        '  "previous_acquisitions": ["Acquisition 1 (2022)", "Acquisition 2 (2024)"]\n'
        "}\n\n"
        "Rules: is_buy_side must be true. Populate ALL buy-side specific fields. "
        "acquisition_capacity = cash + conservative debt headroom (e.g. 1-2x current EBITDA). "
        "financials_5yr MUST cover years 2021, 2022, 2023, 2024, 2025 — do NOT use 2020. "
        "company_overview: 4-6 concise bullet points starting with '- ' covering: what the company does, key products/services, geographic footprint, key customers/partners. "
        "All monetary values in USD millions. Return ONLY JSON."
    )

    response = router.complete(
        "buyer_company_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=BUYER_COMPANY_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        import json as _json
        parsed = _json.loads(json_str)
        # Backfill required envelope fields the model may omit
        parsed.setdefault("agent", "buyer-company-agent")
        parsed.setdefault("assessment_id", assessment_id)
        parsed.setdefault("target_company", "")
        parsed.setdefault("buyer_company", buyer_company)
        parsed.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
        parsed.setdefault("status", "COMPLETE")
        parsed.setdefault("confidence_score", 0.8)
        parsed.setdefault("company_name", buyer_company)
        parsed.setdefault("is_buy_side", True)
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
    except Exception as _parse_err:
        import traceback as _tb
        import logging as _log
        _log.getLogger(__name__).error("buyer-company-agent parse failed: %s\n%s\njson_str[:300]=%r",
                                       _parse_err, _tb.format_exc(), json_str[:300])
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
