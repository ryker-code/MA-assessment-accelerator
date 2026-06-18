#!/usr/bin/env python3
"""Demo runner: triggers a full M&A assessment and reports progress."""

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

API_BASE = "http://localhost:8000"
DEMO_FILE = Path(__file__).parent / "targets" / "telenor_pakistan.json"


def api_get(path: str) -> dict:
    url = f"{API_BASE}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def api_post(path: str, payload: dict) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def main():
    # Load demo target
    if not DEMO_FILE.exists():
        print(f"Demo file not found: {DEMO_FILE}")
        sys.exit(1)

    with open(DEMO_FILE) as f:
        target = json.load(f)

    print("=" * 60)
    print("M&A ASSESSMENT ACCELERATOR — DEMO RUN")
    print("=" * 60)
    print(f"Buyer:  {target['buyer_company']} ({target['buyer_country']})")
    print(f"Target: {target['target_company']} ({target['target_country']})")
    print(f"Type:   {target['assessment_type']}")
    print(f"Context: {target['context']}")
    print()

    # Check API is up
    health = api_get("/health")
    if health.get("error"):
        print(f"ERROR: API not reachable at {API_BASE}. Start it with:")
        print("  uvicorn api.server:app --port 8000")
        sys.exit(1)

    # Trigger assessment
    print("Triggering assessment...")
    result = api_post("/assessments", {
        "buyer_company": target["buyer_company"],
        "target_company": target["target_company"],
        "assessment_type": target["assessment_type"],
    })

    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    assessment_id = result["assessment_id"]
    print(f"Assessment ID: {assessment_id}")
    print(f"Dashboard: {API_BASE}")
    print()

    # Poll for status
    last_completed = set()
    while True:
        status = api_get(f"/assessments/{assessment_id}")
        if status.get("status") == "not_found":
            print("Waiting for assessment to initialize...")
            time.sleep(5)
            continue

        overall = status.get("overall_status", "IN_PROGRESS")
        phase = status.get("phase", "PHASE_1")
        completed = status.get("completed_agents", {})

        # Report newly completed agents
        for agent_name, info in completed.items():
            if agent_name not in last_completed:
                last_completed.add(agent_name)
                print(f"  ✓ {agent_name} completed")

        print(f"[{phase}] Status: {overall} | Completed: {len(completed)}/8", end="\r")

        if overall in ("COMPLETE", "NEEDS_HUMAN_REVIEW"):
            print()
            break

        time.sleep(30)

    print()
    print("=" * 60)
    print(f"ASSESSMENT COMPLETE")
    print("=" * 60)

    final = api_get(f"/assessments/{assessment_id}")
    decision = final.get("decision", "UNKNOWN")
    print(f"Decision:  {decision}")
    print(f"Status:    {final.get('overall_status', 'UNKNOWN')}")
    print(f"Completed: {final.get('completed_at', 'N/A')}")
    print()
    print(f"View report: {API_BASE}")
    print(f"Output dir:  output/{assessment_id}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
