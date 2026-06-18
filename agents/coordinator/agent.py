import asyncio
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from agents.shared.llm_router import LLMRouter
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import send_to_room, format_agent_message

router = LLMRouter()

PHASE1_TIMEOUT_SECONDS = 600  # 10 min — 6 agents × ~60s each, running in parallel


def _post_to_band(room_id: str, agent: str, status: str, message: str):
    """Post a message to the Band room if room_id is available."""
    rid = room_id or os.environ.get("BAND_ROOM_ID", "")
    if not rid:
        return
    try:
        send_to_room(rid, format_agent_message(agent, status, message))
    except Exception:
        pass  # Band messaging is best-effort


def _make_partial_risk(assessment_id, target_company, buyer_company, error_msg):
    from datetime import datetime
    from agents.shared.markdown_writer import _format_markdown_fallback
    structured = {
        "agent": "risk-agent", "assessment_id": assessment_id,
        "target_company": target_company, "buyer_company": buyer_company,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "PARTIAL", "confidence_score": 0.1,
        "human_review_required": True,
        "overall_risk_rating": "AMBER", "risks": [], "cross_workstream_insights": [],
        "data_sources": [],
    }
    return {
        "structured": structured,
        "markdown": f"## Risk Assessment — PARTIAL\n\nAgent failed: {error_msg[:200]}\n\nHuman review required.",
        "confidence": 0.1,
    }


def _make_partial_deal(assessment_id, target_company, buyer_company, error_msg):
    from datetime import datetime
    structured = {
        "agent": "deal-rationale-agent", "assessment_id": assessment_id,
        "target_company": target_company, "buyer_company": buyer_company,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "PARTIAL", "confidence_score": 0.1,
        "human_review_required": True,
        "decision": "REVISIT", "revisit_timeframe": "Pending manual review",
        "decision_rationale": [f"Automated synthesis failed: {error_msg[:200]}"],
        "value_creation_avenues": [], "ev_ebitda_comparable_range": {},
        "implied_valuation_range_usd_m": {}, "key_conditions_for_reversal": [],
        "recommended_next_steps": ["Re-run assessment or complete manually"],
        "strategic_fit_score": 5.0, "data_sources": [],
    }
    return {
        "structured": structured,
        "markdown": f"## Deal Rationale — PARTIAL\n\nAgent failed: {error_msg[:200]}\n\nHuman review required.",
        "confidence": 0.1,
        "decision": "REVISIT",
    }


def _infer_company_context(company: str, buyer_company: str) -> dict:
    from agents.shared.llm_utils import extract_json
    prompt = (
        f"Given these two companies involved in an M&A deal:\n"
        f"Target company: {company}\nBuyer company: {buyer_company}\n\n"
        "Return ONLY a JSON object:\n"
        '{\n'
        '  "target_country": "Pakistan",\n'
        '  "target_sector": "Telecommunications",\n'
        '  "buyer_country": "Saudi Arabia",\n'
        '  "buyer_sector": "Telecommunications"\n'
        '}\n'
        "Infer the most likely home country and primary sector for each company. Return ONLY JSON."
    )
    try:
        response = router.complete("coordinator", [{"role": "user", "content": prompt}])
        return json.loads(extract_json(response))
    except Exception:
        return {"target_country": "", "target_sector": "", "buyer_country": "", "buyer_sector": ""}


def _get_manifest(assessment_id: str) -> dict:
    path = Path(os.environ.get("OUTPUT_DIR", "output")) / assessment_id / "00_assessment_manifest.json"
    return json.loads(path.read_text()) if path.exists() else {"completed_agents": {}}


def _write_manifest(manifest_path: Path, manifest: dict):
    manifest_path.write_text(json.dumps(manifest, indent=2))


def _assemble_final_report(assessment_id: str, manifest: dict) -> str:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output")) / assessment_id
    sections = [
        "# M&A Assessment Report\n",
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


def _run_phase1_agent(fn, args: tuple, agent_name: str, file_index: int, title: str, assessment_id: str):
    """Run one Phase 1 agent synchronously in a thread and save its output."""
    try:
        result = asyncio.run(fn(*args))
        save_agent_output(
            assessment_id=assessment_id,
            agent_name=agent_name,
            file_index=file_index,
            title=title,
            content=result["markdown"],
            metadata={"confidence": f"{result['confidence']:.0%}"},
        )
        room_id = os.environ.get("BAND_ROOM_ID", "")
        _post_to_band(room_id, agent_name, "COMPLETE",
            f"Completed — confidence: {result['confidence']:.0%} | sources: {len(result.get('sources', []))}")
        return agent_name, result
    except Exception as e:
        room_id = os.environ.get("BAND_ROOM_ID", "")
        _post_to_band(room_id, agent_name, "ERROR", f"Failed: {str(e)[:100]}")
        return agent_name, e


def run_assessment_sync(
    assessment_id: str,
    target_company: str,
    buyer_company: str,
    assessment_type: str,
    room_id: str = "",
) -> dict:
    """Fully synchronous pipeline — safe to call from any thread."""
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output")) / assessment_id
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "00_assessment_manifest.json"

    # Infer context
    context = _infer_company_context(target_company, buyer_company)
    target_country = context.get("target_country", "")
    target_sector = context.get("target_sector", "")
    buyer_country = context.get("buyer_country", "")
    buyer_sector = context.get("buyer_sector", "")

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
    _write_manifest(manifest_path, manifest)

    _post_to_band(room_id, "coordinator", "PHASE_1_START",
        f"Assessment started: **{buyer_company}** acquiring **{target_company}** ({assessment_type})\n"
        f"Target: {target_company} ({target_country}, {target_sector})\n"
        f"Buyer: {buyer_company} ({buyer_country}, {buyer_sector})\n"
        "Dispatching 6 research agents in parallel: @country-agent @sector-agent @company-agent "
        "@buyer-country-agent @buyer-sector-agent @buyer-company-agent")

    # --- PHASE 1: 6 agents in parallel threads ---
    from agents.country_agent.agent import run_country_assessment
    from agents.sector_agent.agent import run_sector_assessment
    from agents.company_agent.agent import run_company_assessment
    from agents.buyer_country_agent.agent import run_buyer_country_assessment
    from agents.buyer_sector_agent.agent import run_buyer_sector_assessment
    from agents.buyer_company_agent.agent import run_buyer_company_assessment

    phase1_work = [
        (run_country_assessment,       (assessment_id, target_company, target_country),          "country-agent",       1, f"Country Assessment: {target_country}"),
        (run_sector_assessment,        (assessment_id, target_company, target_sector, target_country), "sector-agent",  2, f"Sector Assessment: {target_sector}"),
        (run_company_assessment,       (assessment_id, target_company, buyer_company),            "company-agent",       3, f"Company Assessment: {target_company}"),
        (run_buyer_country_assessment, (assessment_id, buyer_company, buyer_country, target_country), "buyer-country-agent", 4, f"Buyer Country: {buyer_country}"),
        (run_buyer_sector_assessment,  (assessment_id, buyer_company, buyer_country, buyer_sector, target_country), "buyer-sector-agent", 5, f"Buyer Sector: {buyer_sector}"),
        (run_buyer_company_assessment, (assessment_id, buyer_company, buyer_country),             "buyer-company-agent", 6, f"Buyer Company: {buyer_company}"),
    ]

    import time as _time
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {}
        for i, (fn, args, name, idx, title) in enumerate(phase1_work):
            futures[pool.submit(_run_phase1_agent, fn, args, name, idx, title, assessment_id)] = name
            if i < len(phase1_work) - 1:
                _time.sleep(0.5)  # stagger submissions to avoid Featherless rate limits
        for future in as_completed(futures, timeout=PHASE1_TIMEOUT_SECONDS):
            agent_name, result = future.result()
            if not isinstance(result, Exception):
                manifest = _get_manifest(assessment_id)
                manifest["completed_agents"][agent_name] = {
                    "completed_at": datetime.utcnow().isoformat() + "Z"
                }
                _write_manifest(manifest_path, manifest)

    _post_to_band(room_id, "coordinator", "PHASE_2_START", "Phase 1 complete. Running cross-workstream risk synthesis (@risk-agent)...")

    # --- PHASE 2: Risk agent ---
    manifest = _get_manifest(assessment_id)
    manifest["phase"] = "PHASE_2"
    _write_manifest(manifest_path, manifest)

    from agents.risk_agent.agent import run_risk_assessment_sync
    try:
        risk_result = run_risk_assessment_sync(assessment_id, target_company, buyer_company)
    except Exception as e:
        risk_result = _make_partial_risk(assessment_id, target_company, buyer_company, str(e))

    save_agent_output(
        assessment_id=assessment_id,
        agent_name="risk-agent",
        file_index=7,
        title=f"Risk Assessment: {target_company} / {buyer_company}",
        content=risk_result["markdown"],
        metadata={"rating": risk_result["structured"]["overall_risk_rating"]},
    )

    manifest = _get_manifest(assessment_id)
    manifest["phase"] = "PHASE_3"
    manifest["completed_agents"]["risk-agent"] = {"completed_at": datetime.utcnow().isoformat() + "Z"}
    _write_manifest(manifest_path, manifest)

    _post_to_band(room_id, "risk-agent", "COMPLETE",
        f"Risk rating: {risk_result['structured']['overall_risk_rating']} — running deal rationale (@deal-rationale-agent)...")

    # --- PHASE 3: Deal rationale agent ---
    from agents.deal_rationale_agent.agent import run_deal_rationale_sync
    try:
        deal_result = run_deal_rationale_sync(
            assessment_id, target_company, buyer_company, target_sector, target_country
        )
    except Exception as e:
        deal_result = _make_partial_deal(assessment_id, target_company, buyer_company, str(e))

    save_agent_output(
        assessment_id=assessment_id,
        agent_name="deal-rationale-agent",
        file_index=8,
        title=f"Deal Rationale: {buyer_company} / {target_company}",
        content=deal_result["markdown"],
        metadata={"decision": deal_result["decision"]},
    )

    # --- PHASE 4: Assemble final report ---
    manifest = _get_manifest(assessment_id)
    final_report = _assemble_final_report(assessment_id, manifest)
    (output_dir / "09_full_assessment_report.md").write_text(final_report)

    overall_status = "COMPLETE"
    if risk_result["structured"].get("human_review_required") or deal_result["structured"].get("human_review_required"):
        overall_status = "NEEDS_HUMAN_REVIEW"

    deal_structured = deal_result["structured"]
    manifest["phase"] = "COMPLETE"
    manifest["overall_status"] = overall_status
    manifest["completed_at"] = datetime.utcnow().isoformat() + "Z"
    manifest["decision"] = deal_result["decision"]
    manifest["strategic_fit_score"] = deal_structured.get("strategic_fit_score")
    manifest["implied_valuation_range_usd_m"] = deal_structured.get("implied_valuation_range_usd_m", {})
    manifest["ev_ebitda_comparable_range"] = deal_structured.get("ev_ebitda_comparable_range", {})
    manifest["overall_risk_rating"] = risk_result["structured"].get("overall_risk_rating")
    manifest["completed_agents"]["deal-rationale-agent"] = {"completed_at": datetime.utcnow().isoformat() + "Z"}
    _write_manifest(manifest_path, manifest)

    _post_to_band(room_id, "coordinator", "COMPLETE",
        f"Assessment complete. Decision: **{deal_result['decision']}** | "
        f"Strategic fit: {deal_result['structured'].get('strategic_fit_score', 'N/A')}/10 | "
        f"Risk: {risk_result['structured']['overall_risk_rating']}")

    return manifest


# Keep async wrapper for Band compatibility
async def run_assessment(assessment_id, target_company, buyer_company, assessment_type, room_id=""):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        run_assessment_sync,
        assessment_id, target_company, buyer_company, assessment_type, room_id,
    )


def trigger_assessment(buyer_company: str, target_company: str, assessment_type: str = "LEVEL_2", room_id: str = "") -> str:
    assessment_id = str(uuid.uuid4())
    run_assessment_sync(assessment_id, target_company, buyer_company, assessment_type, room_id)
    return assessment_id


if __name__ == "__main__":
    try:
        from band import Band
        band = Band(agent_uuid=os.environ["BAND_AGENT_UUID_COORDINATOR"])
        band.on_message(lambda msg: asyncio.run(run_assessment(
            str(uuid.uuid4()),
            json.loads(msg.get("content", "{}")).get("target_company", ""),
            json.loads(msg.get("content", "{}")).get("buyer_company", ""),
            json.loads(msg.get("content", "{}")).get("assessment_type", "LEVEL_2"),
        )))
        band.connect()
    except ImportError:
        print("Band SDK not available — run in standalone test mode")
