import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from agents.shared.llm_router import LLMRouter
from agents.shared.markdown_writer import save_agent_output, _update_manifest
from agents.shared.band_utils import send_to_room, format_agent_message
from agents.shared.prompts import COORDINATOR_PROMPT

router = LLMRouter()

PHASE1_AGENTS = [
    "country-agent",
    "sector-agent",
    "company-agent",
    "buyer-country-agent",
    "buyer-sector-agent",
    "buyer-company-agent",
]

PHASE1_TIMEOUT_SECONDS = 300
POLL_INTERVAL_SECONDS = 30


def _infer_company_context(company: str, buyer_company: str) -> dict:
    """Quick LLM call to infer country/sector for both companies."""
    prompt = (
        f"Given these two companies involved in an M&A deal:\n"
        f"Target company: {company}\n"
        f"Buyer company: {buyer_company}\n\n"
        "Return ONLY a JSON object:\n"
        '{\n'
        f'  "target_country": "Pakistan",\n'
        f'  "target_sector": "Telecommunications",\n'
        f'  "buyer_country": "Saudi Arabia",\n'
        f'  "buyer_sector": "Telecommunications"\n'
        '}\n'
        "Use your knowledge to infer the most likely country and sector for each company. Return ONLY JSON."
    )
    response = router.complete(
        "coordinator",
        [{"role": "user", "content": prompt}],
    )
    from agents.shared.llm_utils import extract_json
    try:
        return json.loads(extract_json(response))
    except Exception:
        return {
            "target_country": "",
            "target_sector": "",
            "buyer_country": "",
            "buyer_sector": "",
        }


def _get_manifest(assessment_id: str) -> dict:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output")) / assessment_id
    manifest_path = output_dir / "00_assessment_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return {"completed_agents": {}}


def _assemble_final_report(assessment_id: str, manifest: dict) -> str:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output")) / assessment_id
    sections = [
        f"# M&A Assessment Report\n",
        f"**Assessment ID:** {assessment_id}",
        f"**Target:** {manifest.get('target_company', '')}",
        f"**Buyer:** {manifest.get('buyer_company', '')}",
        f"**Started:** {manifest.get('started_at', '')}",
        f"**Type:** {manifest.get('assessment_type', '')}",
        "\n---\n",
    ]
    for i in range(1, 9):
        for path in sorted(output_dir.glob(f"{i:02d}_*.md")):
            sections.append(path.read_text())
            sections.append("\n---\n")
    return "\n".join(sections)


async def run_assessment(
    assessment_id: str,
    target_company: str,
    buyer_company: str,
    assessment_type: str,
    room_id: str = "",
) -> dict:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output")) / assessment_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Infer context
    context = _infer_company_context(target_company, buyer_company)
    target_country = context.get("target_country", "")
    target_sector = context.get("target_sector", "")
    buyer_country = context.get("buyer_country", "")
    buyer_sector = context.get("buyer_sector", "")

    # Initialize manifest
    manifest = {
        "assessment_id": assessment_id,
        "buyer_company": buyer_company,
        "target_company": target_company,
        "assessment_type": assessment_type,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "phase": "PHASE_1",
        "completed_agents": {},
        "overall_status": "IN_PROGRESS",
        "target_country": target_country,
        "target_sector": target_sector,
        "buyer_country": buyer_country,
        "buyer_sector": buyer_sector,
        "room_id": room_id,
    }
    manifest_path = output_dir / "00_assessment_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    params_base = {
        "assessment_id": assessment_id,
        "target_company": target_company,
        "buyer_company": buyer_company,
        "country": target_country,
        "sector": target_sector,
        "buyer_country": buyer_country,
        "buyer_sector": buyer_sector,
        "assessment_type": assessment_type,
        "room_id": room_id,
    }

    # PHASE 1: Run all 6 research agents in parallel
    if room_id:
        send_to_room(room_id, format_agent_message("coordinator", "PHASE_1", "Dispatching 6 research agents in parallel..."))

    from agents.country_agent.agent import run_country_assessment
    from agents.sector_agent.agent import run_sector_assessment
    from agents.company_agent.agent import run_company_assessment
    from agents.buyer_country_agent.agent import run_buyer_country_assessment
    from agents.buyer_sector_agent.agent import run_buyer_sector_assessment
    from agents.buyer_company_agent.agent import run_buyer_company_assessment

    phase1_tasks = [
        run_country_assessment(assessment_id, target_company, target_country),
        run_sector_assessment(assessment_id, target_company, target_sector, target_country),
        run_company_assessment(assessment_id, target_company, buyer_company),
        run_buyer_country_assessment(assessment_id, buyer_company, buyer_country, target_country),
        run_buyer_sector_assessment(assessment_id, buyer_company, buyer_country, buyer_sector, target_country),
        run_buyer_company_assessment(assessment_id, buyer_company, buyer_country),
    ]

    agent_names = [
        ("country-agent", 1, f"Country Assessment: {target_country}"),
        ("sector-agent", 2, f"Sector Assessment: {target_sector}"),
        ("company-agent", 3, f"Company Assessment: {target_company}"),
        ("buyer-country-agent", 4, f"Buyer Country Assessment: {buyer_country}"),
        ("buyer-sector-agent", 5, f"Buyer Sector Assessment: {buyer_sector}"),
        ("buyer-company-agent", 6, f"Buyer Company Assessment: {buyer_company}"),
    ]

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*phase1_tasks, return_exceptions=True),
            timeout=PHASE1_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        results = [None] * 6

    for i, (result, (agent_name, file_index, title)) in enumerate(zip(results, agent_names)):
        if result is None or isinstance(result, Exception):
            continue
        save_agent_output(
            assessment_id=assessment_id,
            agent_name=agent_name,
            file_index=file_index,
            title=title,
            content=result["markdown"],
            metadata={"confidence": f"{result['confidence']:.0%}"},
        )

    # Update phase
    manifest = _get_manifest(assessment_id)
    manifest["phase"] = "PHASE_2"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    # PHASE 2: Risk agent
    if room_id:
        send_to_room(room_id, format_agent_message("coordinator", "PHASE_2", "Running risk synthesis..."))

    from agents.risk_agent.agent import run_risk_assessment
    risk_result = await run_risk_assessment(assessment_id, target_company, buyer_company)
    save_agent_output(
        assessment_id=assessment_id,
        agent_name="risk-agent",
        file_index=7,
        title=f"Risk Assessment: {target_company} / {buyer_company}",
        content=risk_result["markdown"],
        metadata={"rating": risk_result["structured"]["overall_risk_rating"]},
    )

    # Update phase
    manifest = _get_manifest(assessment_id)
    manifest["phase"] = "PHASE_3"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    # PHASE 3: Deal rationale agent
    if room_id:
        send_to_room(room_id, format_agent_message("coordinator", "PHASE_3", "Generating deal recommendation..."))

    from agents.deal_rationale_agent.agent import run_deal_rationale
    deal_result = await run_deal_rationale(
        assessment_id, target_company, buyer_company, target_sector, target_country
    )
    save_agent_output(
        assessment_id=assessment_id,
        agent_name="deal-rationale-agent",
        file_index=8,
        title=f"Deal Rationale: {buyer_company} / {target_company}",
        content=deal_result["markdown"],
        metadata={"decision": deal_result["decision"]},
    )

    # PHASE 4: Assemble final report
    manifest = _get_manifest(assessment_id)
    final_report = _assemble_final_report(assessment_id, manifest)
    report_path = output_dir / "09_full_assessment_report.md"
    report_path.write_text(final_report)

    overall_status = "COMPLETE"
    for result in [risk_result]:
        if result["structured"].get("human_review_required"):
            overall_status = "NEEDS_HUMAN_REVIEW"
    if deal_result["structured"].get("human_review_required"):
        overall_status = "NEEDS_HUMAN_REVIEW"

    manifest["phase"] = "COMPLETE"
    manifest["overall_status"] = overall_status
    manifest["completed_at"] = datetime.utcnow().isoformat() + "Z"
    manifest["final_report"] = str(report_path)
    manifest["decision"] = deal_result["decision"]
    manifest_path.write_text(json.dumps(manifest, indent=2))

    if room_id:
        summary = (
            f"Assessment complete! Decision: **{deal_result['decision']}** | "
            f"Status: {overall_status} | "
            f"Report: {report_path}"
        )
        send_to_room(room_id, format_agent_message("coordinator", "COMPLETE", summary))

    return manifest


def trigger_assessment(
    buyer_company: str,
    target_company: str,
    assessment_type: str = "LEVEL_2",
    room_id: str = "",
) -> str:
    assessment_id = str(uuid.uuid4())
    asyncio.run(run_assessment(assessment_id, target_company, buyer_company, assessment_type, room_id))
    return assessment_id


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_COORDINATOR"])

        async def handle_message(message: dict):
            params = json.loads(message.get("content", "{}"))
            await run_assessment(
                assessment_id=str(uuid.uuid4()),
                target_company=params["target_company"],
                buyer_company=params["buyer_company"],
                assessment_type=params.get("assessment_type", "LEVEL_2"),
                room_id=params.get("room_id", ""),
            )

        band.on_message(lambda msg: asyncio.run(handle_message(msg)))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
