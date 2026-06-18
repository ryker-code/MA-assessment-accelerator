import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from agents.shared.llm_router import LLMRouter
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import post_completion
from agents.shared.prompts import RISK_AGENT_PROMPT
from agents.shared.schemas import RiskAssessment
from agents.shared.llm_utils import extract_json

router = LLMRouter()


def _format_markdown(data: RiskAssessment) -> str:
    rating_emoji = {"RED": "🔴", "AMBER": "🟡", "GREEN": "🟢"}.get(data.overall_risk_rating, "⚪")
    lines = [
        f"## Risk Assessment\n",
        f"**Overall Risk Rating:** {rating_emoji} {data.overall_risk_rating}",
        f"**Human Review Required:** {'Yes' if data.human_review_required else 'No'}\n",
        f"### Risk Matrix\n",
        f"| Risk | Category | Severity | Probability | Cross-Workstream |",
        f"|------|----------|----------|-------------|-----------------|",
    ]
    for risk in data.risks:
        cw = "✓" if risk.is_cross_workstream else ""
        lines.append(
            f"| {risk.title} | {risk.category} | {risk.severity} | {risk.probability} | {cw} |"
        )
    lines.append(f"\n### Risk Details")
    for risk in data.risks:
        lines += [
            f"\n#### {risk.title}",
            f"- **Category:** {risk.category}",
            f"- **Severity:** {risk.severity} | **Probability:** {risk.probability}",
            f"- **Description:** {risk.description}",
        ]
        if risk.mitigants:
            lines.append("- **Mitigants:**")
            for m in risk.mitigants:
                lines.append(f"  - {m}")
    lines += [
        f"\n### Cross-Workstream Insights",
        *[f"- {insight}" for insight in data.cross_workstream_insights],
    ]
    return "\n".join(lines)


def _load_phase1_outputs(assessment_id: str) -> dict:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output")) / assessment_id
    phase1_agents = [
        "country-agent", "sector-agent", "company-agent",
        "buyer-country-agent", "buyer-sector-agent", "buyer-company-agent",
    ]
    outputs = {}
    for agent_name in phase1_agents:
        filename = f"{['country-agent','sector-agent','company-agent','buyer-country-agent','buyer-sector-agent','buyer-company-agent'].index(agent_name)+1:02d}_{agent_name.replace('-','_')}.md"
        path = output_dir / filename
        if path.exists():
            outputs[agent_name] = path.read_text()
    return outputs


async def run_risk_assessment(assessment_id: str, target_company: str, buyer_company: str) -> dict:
    phase1_outputs = _load_phase1_outputs(assessment_id)
    combined_context = "\n\n---\n\n".join([
        f"### {agent}\n{content[:2000]}"
        for agent, content in phase1_outputs.items()
    ])

    prompt = (
        f"Target company: {target_company}\nBuyer company: {buyer_company}\n"
        f"Assessment ID: {assessment_id}\n\n"
        f"Phase 1 research outputs:\n{combined_context}\n\n"
        "Produce a comprehensive risk assessment as a single JSON object. "
        "Pay special attention to CROSS_WORKSTREAM risks that only emerge by combining buy-side and sell-side data.\n"
        "{\n"
        f'  "agent": "risk-agent",\n'
        f'  "assessment_id": "{assessment_id}",\n'
        f'  "target_company": "{target_company}",\n'
        f'  "buyer_company": "{buyer_company}",\n'
        '  "timestamp": "2026-06-18T00:00:00Z",\n'
        '  "status": "COMPLETE",\n'
        '  "confidence_score": 0.85,\n'
        '  "human_review_required": false,\n'
        '  "data_sources": [],\n'
        '  "overall_risk_rating": "AMBER",\n'
        '  "risks": [\n'
        '    {\n'
        '      "title": "Risk title",\n'
        '      "category": "GEOPOLITICAL",\n'
        '      "severity": "HIGH",\n'
        '      "probability": "MEDIUM",\n'
        '      "description": "Detailed description",\n'
        '      "mitigants": ["Mitigant 1"],\n'
        '      "is_cross_workstream": false\n'
        '    },\n'
        '    {\n'
        '      "title": "Cross-workstream risk example",\n'
        '      "category": "CROSS_WORKSTREAM",\n'
        '      "severity": "HIGH",\n'
        '      "probability": "HIGH",\n'
        '      "description": "Risk only visible when combining buy+sell data",\n'
        '      "mitigants": [],\n'
        '      "is_cross_workstream": true\n'
        '    }\n'
        '  ],\n'
        '  "cross_workstream_insights": [\n'
        '    "Insight only visible across both workstreams 1",\n'
        '    "Insight 2"\n'
        '  ]\n'
        "}\n\n"
        "Rules:\n"
        "- overall_risk_rating: RED if any severity=HIGH AND probability=HIGH; AMBER if any severity=HIGH; else GREEN\n"
        "- If RED: set human_review_required=true\n"
        "- Include 5-15 risks total; at least 2 must be CROSS_WORKSTREAM\n"
        "- category must be: GEOPOLITICAL, CURRENCY, REGULATORY, MARKET, COMPANY, or CROSS_WORKSTREAM\n"
        "- severity and probability must be: HIGH, MEDIUM, or LOW\n"
        "- Return ONLY JSON"
    )

    response = router.complete(
        "risk_agent",
        [{"role": "user", "content": prompt}],
        system_prompt=RISK_AGENT_PROMPT,
    )

    json_str = extract_json(response)

    try:
        structured = RiskAssessment.model_validate_json(json_str)
    except Exception:
        structured = RiskAssessment(
            agent="risk-agent",
            assessment_id=assessment_id,
            target_company=target_company,
            buyer_company=buyer_company,
            timestamp=datetime.utcnow().isoformat() + "Z",
            status="PARTIAL",
            confidence_score=0.3,
            human_review_required=True,
            overall_risk_rating="AMBER",
            risks=[],
            cross_workstream_insights=["LLM parsing failed — manual review required"],
            data_sources=[],
        )

    if structured.overall_risk_rating == "RED":
        structured.human_review_required = True

    markdown = _format_markdown(structured)
    return {
        "structured": structured.model_dump(),
        "markdown": markdown,
        "confidence": structured.confidence_score,
    }


async def handle_message(message: dict):
    params = json.loads(message.get("content", "{}"))
    assessment_id = params["assessment_id"]
    target_company = params["target_company"]
    buyer_company = params.get("buyer_company", "")

    result = await run_risk_assessment(assessment_id, target_company, buyer_company)

    file_path = save_agent_output(
        assessment_id=assessment_id,
        agent_name="risk-agent",
        file_index=7,
        title=f"Risk Assessment: {target_company} / {buyer_company}",
        content=result["markdown"],
        metadata={
            "rating": result["structured"]["overall_risk_rating"],
            "confidence": f"{result['confidence']:.0%}",
            "risks": len(result["structured"]["risks"]),
        },
    )

    await post_completion(
        room_id=params.get("room_id", ""),
        agent_name="risk-agent",
        output_schema=result["structured"],
        file_path=file_path,
    )


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_RISK"])
        band.on_message(lambda msg: asyncio.run(handle_message(msg)))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
