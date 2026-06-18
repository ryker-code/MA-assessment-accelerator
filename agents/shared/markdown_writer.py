import json
import os
from datetime import datetime
from pathlib import Path


def save_agent_output(
    assessment_id: str,
    agent_name: str,
    file_index: int,
    title: str,
    content: str,
    metadata: dict = None,
) -> str:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output")) / assessment_id
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{file_index:02d}_{agent_name.replace('-', '_')}.md"
    file_path = output_dir / filename

    header = f"# {title}\n\n"
    if metadata:
        header += "| Key | Value |\n|-----|-------|\n"
        for k, v in metadata.items():
            header += f"| {k} | {v} |\n"
        header += "\n---\n\n"

    file_path.write_text(header + content)

    _update_manifest(assessment_id, agent_name, str(file_path), output_dir)

    return str(file_path)


def _update_manifest(assessment_id: str, agent_name: str, file_path: str, output_dir: Path):
    manifest_path = output_dir / "00_assessment_manifest.json"

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {
            "assessment_id": assessment_id,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "phase": "PHASE_1",
            "completed_agents": {},
            "overall_status": "IN_PROGRESS",
        }

    manifest["completed_agents"][agent_name] = {
        "file": file_path,
        "completed_at": datetime.utcnow().isoformat() + "Z",
    }

    manifest_path.write_text(json.dumps(manifest, indent=2))
