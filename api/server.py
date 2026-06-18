import asyncio
import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="M&A Assessment Accelerator API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AssessmentRequest(BaseModel):
    buyer_company: str
    target_company: str
    assessment_type: str = "LEVEL_2"


OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))


def _run_assessment_bg(assessment_id: str, target_company: str, buyer_company: str, assessment_type: str):
    from agents.coordinator.agent import run_assessment_sync
    run_assessment_sync(
        assessment_id=assessment_id,
        target_company=target_company,
        buyer_company=buyer_company,
        assessment_type=assessment_type,
        room_id="",
    )


@app.post("/assessments")
async def start_assessment(req: AssessmentRequest, background_tasks: BackgroundTasks):
    assessment_id = str(uuid.uuid4())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    background_tasks.add_task(
        _run_assessment_bg,
        assessment_id,
        req.target_company,
        req.buyer_company,
        req.assessment_type,
    )
    return {"assessment_id": assessment_id, "status": "started"}


@app.get("/assessments/{assessment_id}")
async def get_assessment_status(assessment_id: str):
    manifest_path = OUTPUT_DIR / assessment_id / "00_assessment_manifest.json"
    if not manifest_path.exists():
        return {"status": "not_found", "assessment_id": assessment_id}
    with open(manifest_path) as f:
        manifest = json.load(f)
    return manifest


@app.get("/assessments/{assessment_id}/files/{filename}")
async def get_assessment_file(assessment_id: str, filename: str):
    # Prevent path traversal
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = OUTPUT_DIR / assessment_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    with open(file_path) as f:
        content = f.read()
    return {"filename": filename, "content": content, "format": "markdown"}


@app.get("/assessments")
async def list_assessments():
    if not OUTPUT_DIR.exists():
        return []
    assessments = []
    for d in OUTPUT_DIR.iterdir():
        if not d.is_dir():
            continue
        manifest = d / "00_assessment_manifest.json"
        if manifest.exists():
            with open(manifest) as f:
                assessments.append(json.load(f))
    return sorted(assessments, key=lambda x: x.get("started_at", ""), reverse=True)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Serve dashboard — must be last to avoid shadowing API routes
web_dir = Path(__file__).parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")
