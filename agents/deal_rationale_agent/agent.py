import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from agents.shared.llm_router import LLMRouter
from agents.shared.search_tools import web_search
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import post_completion
from agents.shared.prompts import DEAL_RATIONALE_AGENT_PROMPT
from agents.shared.schemas import DealRationale
from agents.shared.llm_utils import extract_json

router = LLMRouter()


def _format_markdown(data: DealRationale) -> str:
    decision_style = {
        "GO": "✅ **GO**",
        "NO_GO": "❌ **NO-GO**",
        "REVISIT": "⏳ **REVISIT**",
    }
    lines = [
        f"## Deal Rationale & Recommendation\n",
        f"### Decision: {decision_style.get(data.decision, data.decision)}\n",
        f"**Strategic Fit Score:** {data.strategic_fit_score:.1f}/10\n",
    ]
    if data.revisit_timeframe:
        lines.append(f"**Revisit Timeframe:** {data.revisit_timeframe}\n")
    lines += [f"### Top 5 Decision Rationale"]
    for i, point in enumerate(data.decision_rationale[:5], 1):
        lines.append(f"{i}. {point}")
    lines += [f"\n### Value Creation Avenues"]
    for avenue in data.value_creation_avenues:
        impact_icon = {"HIGH": "🔼", "MEDIUM": "➡️", "LOW": "🔽"}.get(avenue.estimated_impact, "")
        lines.append(
            f"- **{avenue.category}** {impact_icon}: {avenue.description}"
            + (" _(requires integration)_" if avenue.requires_integration else "")
        )
    ev = data.ev_ebitda_comparable_range
    val = data.implied_valuation_range_usd_m
    lines += [
        f"\n### Valuation",
        f"- **EV/EBITDA Range:** {ev.get('low', 'N/A')}x – {ev.get('high', 'N/A')}x (median: {ev.get('median', 'N/A')}x)",
        f"- **Implied Enterprise Value:** USD {val.get('low', 'N/A')}m – USD {val.get('high', 'N/A')}m",
        f"\n### Conditions for Reversal",
    ]
    for cond in data.key_conditions_for_reversal:
        lines.append(f"- {cond}")
    lines += [f"\n### Recommended Next Steps"]
    for step in data.recommended_next_steps:
        lines.append(f"- {step}")
    return "\n".join(lines)


def _load_all_outputs(assessment_id: str) -> str:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output")) / assessment_id
    all_agents = [
        "country-agent", "sector-agent", "company-agent",
        "buyer-country-agent", "buyer-sector-agent", "buyer-company-agent",
        "risk-agent",
    ]
    parts = []
    for i, agent_name in enumerate(all_agents, 1):
        filename = f"{i:02d}_{agent_name.replace('-', '_')}.md"
        path = output_dir / filename
        if path.exists():
            parts.append(f"### {agent_name}\n{path.read_text()[:2000]}")
    return "\n\n---\n\n".join(parts)


async def run_deal_rationale(assessment_id: str, target_company: str, buyer_company: str, sector: str = "", target_country: str = "") -> dict:
    searches = [
        f"{target_company} EV EBITDA valuation multiple 2024 2025",
        f"{sector} {target_country} comparable M&A deals EV multiple 2023 2024",
        f"{target_company} comparable public companies EV EBITDA trading multiples",
    ]
    research_data = []
    for q in searches:
        try:
            results = web_search(q, agent_type="company")
            research_data.extend(results)
        except Exception:
            pass

    valuation_context = "\n\n".join([
        f"Source: {r.get('url', 'unknown')}\n{r.get('content', '')}"
        for r in research_data[:8]
    ])

    prior_outputs = _load_all_outputs(assessment_id)

    prompt = (
        f"Target company: {target_company}\nBuyer company: {buyer_company}\n"
        f"Sector: {sector}\nTarget country: {target_country}\n"
        f"Assessment ID: {assessment_id}\n\n"
        f"Prior agent outputs:\n{prior_outputs}\n\n"
        f"Valuation research:\n{valuation_context}\n\n"
        "Produce the final deal rationale and Go/No-Go recommendation as a single JSON object:\n"
        "{\n"
        f'  "agent": "deal-rationale-agent",\n'
        f'  "assessment_id": "{assessment_id}",\n'
        f'  "target_company": "{target_company}",\n'
        f'  "buyer_company": "{buyer_company}",\n'
        '  "timestamp": "2026-06-18T00:00:00Z",\n'
        '  "status": "COMPLETE",\n'
        '  "confidence_score": 0.85,\n'
        '  "human_review_required": false,\n'
        '  "data_sources": [],\n'
        '  "decision": "GO",\n'
        '  "revisit_timeframe": null,\n'
        '  "decision_rationale": [\n'
        '    "Rationale point 1 grounded in specific data",\n'
        '    "Rationale point 2",\n'
        '    "Rationale point 3",\n'
        '    "Rationale point 4",\n'
        '    "Rationale point 5"\n'
        '  ],\n'
        '  "value_creation_avenues": [\n'
        '    {"category": "NEW_CUSTOMERS", "description": "Specific buyer gap + target strength", "estimated_impact": "HIGH", "requires_integration": false}\n'
        '  ],\n'
        '  "ev_ebitda_comparable_range": {"low": 6.0, "high": 9.5, "median": 7.8},\n'
        '  "implied_valuation_range_usd_m": {"low": 900.0, "high": 1425.0},\n'
        '  "key_conditions_for_reversal": ["Condition 1", "Condition 2"],\n'
        '  "recommended_next_steps": ["Step 1", "Step 2", "Step 3"],\n'
        '  "strategic_fit_score": 7.5\n'
        "}\n\n"
        "Rules:\n"
        "- decision: GO if strategic_fit_score >= 7 AND risk_rating != RED; NO_GO if score < 4 OR risk=RED; REVISIT otherwise\n"
        "- decision_rationale: exactly 5 bullet points referencing specific data from prior outputs\n"
        "- category must be: NEW_PRODUCTS, NEW_CUSTOMERS, ASSET_MONETIZATION, COST_SYNERGY, or REVENUE_SYNERGY\n"
        "- estimated_impact must be: HIGH, MEDIUM, or LOW\n"
        "- Return ONLY JSON"
    )

    response = router.complete(
        "deal_rationale_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=DEAL_RATIONALE_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        structured = DealRationale.model_validate_json(json_str)
    except Exception:
        structured = DealRationale(
            agent="deal-rationale-agent",
            assessment_id=assessment_id,
            target_company=target_company,
            buyer_company=buyer_company,
            timestamp=datetime.utcnow().isoformat() + "Z",
            status="PARTIAL",
            confidence_score=0.3,
            human_review_required=True,
            decision="REVISIT",
            decision_rationale=["LLM parsing failed — manual review required"],
            value_creation_avenues=[],
            ev_ebitda_comparable_range={},
            implied_valuation_range_usd_m={},
            key_conditions_for_reversal=[],
            recommended_next_steps=["Re-run assessment with corrected data"],
            strategic_fit_score=5.0,
            data_sources=[],
        )

    markdown = _format_markdown(structured)
    return {
        "structured": structured.model_dump(),
        "markdown": markdown,
        "confidence": structured.confidence_score,
        "decision": structured.decision,
    }


async def handle_message(message: dict):
    params = json.loads(message.get("content", "{}"))
    assessment_id = params["assessment_id"]
    target_company = params["target_company"]
    buyer_company = params.get("buyer_company", "")
    sector = params.get("sector", "")
    target_country = params.get("country", "")

    result = await run_deal_rationale(
        assessment_id, target_company, buyer_company, sector, target_country
    )

    file_path = save_agent_output(
        assessment_id=assessment_id,
        agent_name="deal-rationale-agent",
        file_index=8,
        title=f"Deal Rationale: {buyer_company} / {target_company}",
        content=result["markdown"],
        metadata={
            "decision": result["decision"],
            "strategic_fit": result["structured"]["strategic_fit_score"],
            "confidence": f"{result['confidence']:.0%}",
        },
    )

    await post_completion(
        room_id=params.get("room_id", ""),
        agent_name="deal-rationale-agent",
        output_schema=result["structured"],
        file_path=file_path,
    )


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_DEAL_RATIONALE"])
        band.on_message(lambda msg: asyncio.run(handle_message(msg)))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
