---
name: run-ma-assessment-accelerator
description: Run, start, launch, screenshot, or verify the M&A Assessment Accelerator web app. Use when asked to run the app, take a screenshot, check the dashboard, inspect assessment results, or confirm a UI change is working.
---

The M&A Assessment Accelerator is a FastAPI server (`api/server.py`) that serves a single-page dashboard (`web/index.html`). The SPA takes buyer/target company inputs, fires nine parallel AI agents, and displays structured Go/No-Go results across four tabs. Drive it with the Node.js driver at `.claude/skills/run-ma-assessment-accelerator/driver.mjs`, which uses Playwright's Chromium to interact headlessly.

## Prerequisites

Python deps are pre-installed in this container. Playwright Chromium is cached at `~/.cache/ms-playwright/`. Node modules for Playwright live at `/tmp/node_modules/` — if missing:

```bash
cd /tmp && npm install playwright
npx playwright install chromium
```

No API keys are needed to run the server or take screenshots. Submitting a new assessment requires Band, Google AI, Featherless AI, and Tavily keys in `.env`.

## Start the server

```bash
cd /workspaces/MA-assessment-accelerator
uvicorn api.server:app --port 8000 &> /tmp/ma-server.log &
echo $! > /tmp/ma-server.pid
until curl -sf http://localhost:8000/health > /dev/null; do sleep 1; done
curl http://localhost:8000/health
# → {"status":"ok"}
```

Logs: `/tmp/ma-server.log`. Stop: `kill $(cat /tmp/ma-server.pid)` or `pkill -f 'uvicorn api.server'`.

## Run (agent path)

Driver lives at `.claude/skills/run-ma-assessment-accelerator/driver.mjs`. Always run from the repo root.

**Check server health:**
```bash
node .claude/skills/run-ma-assessment-accelerator/driver.mjs health
# → { status: 'ok' }
```

**List all assessments (shows IDs, status, buyer → target):**
```bash
node .claude/skills/run-ma-assessment-accelerator/driver.mjs list
```

**Screenshot the home form:**
```bash
node .claude/skills/run-ma-assessment-accelerator/driver.mjs screenshot
# → /tmp/ma-driver/home.png
```

**Screenshot results for an existing completed assessment:**
```bash
node .claude/skills/run-ma-assessment-accelerator/driver.mjs screenshot <assessment_id>
# → /tmp/ma-driver/results-<first8chars>.png
```

Example with the STC → Telenor Pakistan assessment (pre-loaded in `output/`):
```bash
node .claude/skills/run-ma-assessment-accelerator/driver.mjs screenshot c35614cf-3fa1-4d2f-9c7f-3eaaadf3263d
# → Screenshot: /tmp/ma-driver/results-c35614cf.png
# → Tabs rendered: Buy Side Analysis, Sell Side Analysis, Risk Assessment, Deal Recommendation
```

Screenshots render all four tabs' content (Buy Side, Sell Side, Risk Assessment, Deal Recommendation) with agent markdown rendered into the page.

## Run (human path)

```bash
uvicorn api.server:app --port 8000 --reload
# Open http://localhost:8000 in a browser
```

Useless headless — the `--reload` flag is nice for development but `&` it for agent use.

## Smoke-test the REST API directly

```bash
# Health
curl http://localhost:8000/health

# List assessments
curl http://localhost:8000/assessments | python3 -m json.tool | head -20

# Start a new assessment (needs API keys in .env)
curl -X POST http://localhost:8000/assessments \
  -H "Content-Type: application/json" \
  -d '{"buyer_company":"stc","target_company":"Telenor Pakistan"}'

# Poll status
curl http://localhost:8000/assessments/<assessment_id>

# Fetch an agent's markdown report
curl http://localhost:8000/assessments/<assessment_id>/files/01_country_agent.md
```

## Gotchas

**`let currentAssessmentId` is module-scoped, not window-exposed.** When injecting state via `page.evaluate()`, setting `window.currentAssessmentId = id` does NOT update the local binding that `updateUI()` closes over. This causes all agent file fetches to go to `/assessments/null/files/...` (404). Fix: use `page.route()` to intercept and rewrite `/assessments/null/**` to the real ID. The driver does this automatically.

**Playwright installed at `/tmp/node_modules/`**, not in the project. The driver imports from that path explicitly. If you move it, update the import path.

**Assessment files use a specific naming scheme.** Agent markdown files are named `{index}_{agent_id_with_underscores}.md` (e.g. `04_buyer_country_agent.md`). The index-to-agent mapping is in `AGENT_FILES` in `web/index.html:322`.

**New assessments fail without API keys.** The POST `/assessments` endpoint starts a background job that calls Band SDK + LLM APIs. Without a valid `.env`, the job logs errors but the server itself stays up. Pre-existing assessments in `output/` load fine without any keys.

## Troubleshooting

**`ModuleNotFoundError: No module named 'band_sdk'` in logs** → Band SDK isn't installed or isn't the expected package name. Check `pip list | grep band`. The agent pipeline fails but the server/dashboard still runs.

**`Cannot find module '/tmp/node_modules/playwright/index.mjs'`** → Run `cd /tmp && npm install playwright` then `npx playwright install chromium`.

**Port 8000 already in use** → `pkill -f 'uvicorn api.server'` then restart.

**Screenshot shows blank tabs** → The server is up but the assessment ID has no files in `output/<id>/`. Use `node driver.mjs list` to find an assessment with `NEEDS_HUMAN_REVIEW` status.
