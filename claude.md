# CLAUDE.md — Autonomous Build Instructions
# MA Assessment Accelerator — Band of Agents Hackathon
# Submission deadline: June 19, 2026 11:00 AM EDT

## Your Mission
Build a working multi-agent M&A assessment system. Work through the task list below
in order. Each task is self-contained. When a task is complete, commit with a
descriptive message and move to the next task immediately.

## Environment
- Python 3.11 in GitHub Codespace (Ubuntu 24.04)
- API keys are in .env — run `source .env` before executing any Python
- Install dependencies: `pip install -r requirements.txt`
- Run the API server with: `uvicorn api.server:app --port 8000 --reload`

## Critical Rules
1. NEVER hardcode API keys. Always use os.environ.get("KEY_NAME")
2. ALWAYS call save_agent_output() after every agent completes its analysis
3. ALL Band communication MUST use band_send_message() — not print() or return
4. Test each agent in isolation before wiring into the coordinator
5. If an API call fails 3 times with exponential backoff, save PARTIAL result and continue
6. Use async/await throughout — all agents are async
7. Commit after every completed task with a descriptive message
8. Read config/models.yaml for all model assignments — never hardcode model names

## Shared Context: What This System Does
This is a multi-agent M&A target assessment system. Given a buyer company name
and a target (sell-side) company name, 9 agents collaborate through Band to produce
a structured Go/No-Go investment recommendation in 2-4 hours instead of 2 weeks.

The 9 agents are:
- @coordinator: orchestrates everything
- SELL-SIDE: @country-agent, @sector-agent, @company-agent (target company)
- BUY-SIDE: @buyer-country-agent, @buyer-sector-agent, @buyer-company-agent (acquirer)
- SYNTHESIS: @risk-agent, @deal-rationale-agent

All agent handles and UUIDs are in .env as BAND_AGENT_UUID_{NAME}.

---

## TASK 1: Project Foundation
**Goal**: Create project structure, install dependencies, verify environment.

Create this exact directory structure:

agents/shared/
agents/coordinator/
agents/country_agent/
agents/sector_agent/
agents/company_agent/
agents/buyer_country_agent/
agents/buyer_sector_agent/
agents/buyer_company_agent/
agents/risk_agent/
agents/deal_rationale_agent/
api/
web/
config/
output/
.cache/llm/
demo/targets/


Create agents/__init__.py and agents/shared/__init__.py (empty files).

Create config/models.yaml:
yaml
agents:
  coordinator:
    provider: google_gemini
    model: gemma-4-31b-it
    temperature: 0.2
    max_tokens: 2048
    use_cache: true
  country_agent:
    provider: featherless
    model: Qwen/Qwen3-14B
    temperature: 0.3
    max_tokens: 4096
    use_cache: true
  sector_agent:
    provider: featherless
    model: Qwen/Qwen3-14B
    temperature: 0.3
    max_tokens: 4096
    use_cache: true
  company_agent:
    provider: google_gemini
    model: gemma-4-31b-it
    temperature: 0.2
    max_tokens: 6000
    use_cache: true
  buyer_country_agent:
    provider: featherless
    model: Qwen/Qwen3-14B
    temperature: 0.3
    max_tokens: 4096
    use_cache: true
  buyer_sector_agent:
    provider: featherless
    model: Qwen/Qwen3-14B
    temperature: 0.3
    max_tokens: 4096
    use_cache: true
  buyer_company_agent:
    provider: featherless
    model: Qwen/Qwen3-14B
    temperature: 0.2
    max_tokens: 4096
    use_cache: true
  risk_agent:
    provider: featherless
    model: deepseek-ai/DeepSeek-R1
    temperature: 0.1
    max_tokens: 4096
    use_cache: true
  deal_rationale_agent:
    provider: google_gemini
    model: gemma-4-31b-it
    temperature: 0.2
    max_tokens: 8000
    use_cache: false


Run: pip install -r requirements.txt
Verify: python -c "import openai, yaml; print('deps OK')"

COMMIT: "feat: project structure, model config, dependencies"

---

## TASK 2: Shared Infrastructure

**Goal**: Build all shared utilities that every agent depends on.

### 2a. agents/shared/llm_router.py
Build a unified LLM interface supporting:
- Provider "google_gemini": uses `google-genai` SDK with `genai.Client()`
  - model call: `client.models.generate_content(model=model, config=GenerateContentConfig(system_instruction=...), contents=last_user_message)`
  - API key from env: GOOGLE_API_KEY
- Provider "featherless": uses `openai` SDK with base_url="https://api.featherless.ai/v1"
  - API key from env: FEATHERLESS_API_KEY
- Provider "aiml_api": uses `openai` SDK with base_url="https://api.aimlapi.com/v1"
  - API key from env: AIML_API_KEY

The router must:
- Load model config from config/models.yaml
- Implement disk-based response caching in .cache/llm/ using SHA256 of (model+messages) as key
- Cache TTL: 24 hours
- Retry with exponential backoff: 1s, 2s, 4s on failure
- Expose: `complete(agent_name, messages, system_prompt=None) -> str`
  (agent_name looks up provider+model from config/models.yaml)

### 2b. agents/shared/schemas.py
Build Pydantic v2 models for all 9 agent outputs:

python
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime

class AgentOutput(BaseModel):
    agent: str
    assessment_id: str
    target_company: str
    buyer_company: str
    timestamp: str
    status: Literal["COMPLETE", "PARTIAL", "NEEDS_HUMAN_REVIEW"]
    confidence_score: float  # 0-1
    human_review_required: bool = False
    data_sources: list[str] = []

class MacroIndicator(BaseModel):
    year: int
    value: float
    unit: str

class CountryAssessment(AgentOutput):
    country: str
    gdp_growth_5yr: list[MacroIndicator]
    gdp_nominal_usd_bn: float
    inflation_rate_latest: float
    currency_code: str
    currency_trend: Literal["APPRECIATING", "STABLE", "DEPRECIATING", "VOLATILE"]
    political_stability_score: float  # 0-100
    ease_of_doing_business_rank: int
    corporate_tax_rate_pct: float
    currency_repatriation_laws: str
    risk_flags: list[str]
    narrative_summary: str

class SectorAssessment(AgentOutput):
    sector: str
    country: str
    market_size_usd_bn: float
    market_growth_rate_pct: float
    num_major_players: int
    top_3_players: list[str]
    regulatory_risk: Literal["HIGH", "MEDIUM", "LOW"]
    key_regulations: list[str]
    technology_disruption_risk: Literal["HIGH", "MEDIUM", "LOW"]
    sector_specific_kpis: dict
    risk_flags: list[str]
    narrative_summary: str

class CompanyAssessment(AgentOutput):
    company_name: str
    is_buy_side: bool  # True for buyer, False for target
    revenue_latest_usd_m: float
    ebitda_latest_usd_m: float
    ebitda_margin_pct: float
    net_debt_usd_m: float
    net_debt_to_ebitda: float
    capex_usd_m: float
    revenue_growth_rate_pct: float
    key_shareholders: list[dict]
    management_quality_score: float  # 0-10
    recent_strategic_moves: list[str]
    sector_kpis: dict
    risk_flags: list[str]
    narrative_summary: str
    # Buy-side specific fields (only populated when is_buy_side=True)
    cash_position_usd_m: Optional[float] = None
    acquisition_capacity_usd_m: Optional[float] = None
    stated_strategic_priorities: Optional[list[str]] = None
    previous_acquisitions: Optional[list[str]] = None

class Risk(BaseModel):
    title: str
    category: Literal["GEOPOLITICAL", "CURRENCY", "REGULATORY", "MARKET", "COMPANY", "CROSS_WORKSTREAM"]
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    probability: Literal["HIGH", "MEDIUM", "LOW"]
    description: str
    mitigants: list[str] = []
    is_cross_workstream: bool = False  # True = risk only visible by combining buy+sell data

class RiskAssessment(AgentOutput):
    overall_risk_rating: Literal["RED", "AMBER", "GREEN"]
    risks: list[Risk]
    cross_workstream_insights: list[str]

class ValueCreationAvenue(BaseModel):
    category: Literal["NEW_PRODUCTS", "NEW_CUSTOMERS", "ASSET_MONETIZATION", "COST_SYNERGY", "REVENUE_SYNERGY"]
    description: str
    estimated_impact: Literal["HIGH", "MEDIUM", "LOW"]
    requires_integration: bool

class DealRationale(AgentOutput):
    decision: Literal["GO", "NO_GO", "REVISIT"]
    revisit_timeframe: Optional[str] = None
    decision_rationale: list[str]  # Top 5 bullet points
    value_creation_avenues: list[ValueCreationAvenue]
    ev_ebitda_comparable_range: dict  # {"low": 6.0, "high": 9.5, "median": 7.8}
    implied_valuation_range_usd_m: dict  # {"low": ..., "high": ...}
    key_conditions_for_reversal: list[str]
    recommended_next_steps: list[str]
    strategic_fit_score: float  # 0-10; how well target fills buyer's gaps


### 2c. agents/shared/markdown_writer.py
Build exactly as specified in the workflow document (save_agent_output function).
File naming: {index:02d}_{agent_name}.md inside output/{assessment_id}/
Update output/{assessment_id}/00_assessment_manifest.json after each save.

### 2d. agents/shared/search_tools.py
Build web search using Tavily:
python
from tavily import TavilyClient
import os

DOMAIN_WHITELIST = {
    "country": ["imf.org", "worldbank.org", "reuters.com", "bloomberg.com", "ft.com", "economist.com"],
    "sector": ["gsma.com", "itu.int", "lightreading.com", "gartner.com", "mckinsey.com", "itu.int"],
    "company": ["sec.gov", "businesswire.com", "prnewswire.com", "reuters.com", "ft.com"],
    "default": ["reuters.com", "bloomberg.com", "ft.com", "wsj.com"]
}

def web_search(query: str, agent_type: str = "default", max_results: int = 5) -> list[dict]:
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    domains = DOMAIN_WHITELIST.get(agent_type, DOMAIN_WHITELIST["default"])
    results = client.search(
        query=query,
        max_results=max_results,
        search_depth="advanced",
        include_domains=domains
    )
    return results.get("results", [])


### 2e. agents/shared/band_utils.py
Build Band SDK helpers:
- `send_to_room(room_id, message, mentions=[])` — wraps band_send_message
- `format_agent_message(agent_name, status, content_summary)` — formats messages
- `post_completion(room_id, agent_name, output_schema, file_path)` — standard completion message

### 2f. agents/shared/prompts.py
Define all system prompts as constants:
- COORDINATOR_PROMPT
- COUNTRY_AGENT_PROMPT
- SECTOR_AGENT_PROMPT
- COMPANY_AGENT_PROMPT (sell-side)
- BUYER_COUNTRY_AGENT_PROMPT
- BUYER_SECTOR_AGENT_PROMPT
- BUYER_COMPANY_AGENT_PROMPT
- RISK_AGENT_PROMPT
- DEAL_RATIONALE_AGENT_PROMPT

Each prompt must include:
1. Agent role and objective
2. Specific data sources to search (with example search queries)
3. Output schema reference (Pydantic class name)
4. Explicit instruction to call save_agent_output() then band_send_message()
5. Fallback instructions if data not found

See the full system prompts in MA_Assessment_Accelerator_Build_Workflow_V2.md Part 4.
For buy-side agents, the prompts focus on: acquirer's strategic context, balance sheet capacity,
outbound M&A regulatory environment, and how the acquirer's gaps map to the target's strengths.

Test shared infrastructure:
python
from agents.shared.llm_router import LLMRouter
r = LLMRouter()
result = r.complete("country_agent", [{"role": "user", "content": "What is Pakistan GDP growth rate in 2024? Answer in one sentence."}])
print(result)


COMMIT: "feat: shared infrastructure complete - LLMRouter, schemas, markdown writer, search tools"

---

## TASK 3: Sell-Side Research Agents

**Goal**: Build the 3 sell-side agents that research the target company.

Build each agent as a standalone Python process that:
1. Connects to Band via the SDK using its UUID from env
2. Listens for @mention messages containing assessment parameters
3. Runs its research workflow using LLMRouter + search_tools
4. Saves output as markdown using markdown_writer
5. Posts completion to Band room via band_utils

### Agent base pattern (use for all 9 agents):
python
# agents/{agent_name}/agent.py

import asyncio
import os
import json
from agents.shared.llm_router import LLMRouter
from agents.shared.search_tools import web_search
from agents.shared.markdown_writer import save_agent_output
from agents.shared.band_utils import post_completion
from agents.shared.prompts import COUNTRY_AGENT_PROMPT  # swap per agent
from agents.shared.schemas import CountryAssessment  # swap per agent

router = LLMRouter()

async def handle_message(message: dict):
    """Called by Band SDK when this agent receives an @mention"""
    params = json.loads(message.get("content", "{}"))
    assessment_id = params["assessment_id"]
    target_company = params["target_company"]
    country = params.get("country", "")  # May need to infer from company name
    
    # Run research
    result = await run_country_assessment(assessment_id, target_company, country)
    
    # Save markdown
    file_path = save_agent_output(
        assessment_id=assessment_id,
        agent_name="country-agent",
        file_index=1,
        title=f"Country Assessment: {country}",
        content=result["markdown"],
        metadata={"confidence": result["confidence"], "sources": len(result["sources"])}
    )
    
    # Post to Band
    await post_completion(
        room_id=params["room_id"],
        agent_name="country-agent",
        output_schema=result["structured"],
        file_path=file_path
    )

async def run_country_assessment(assessment_id, company, country):
    # 1. Search for data across 5 search queries
    searches = [
        f"{country} GDP growth rate 2020 2024 IMF World Bank",
        f"{country} inflation rate currency exchange rate trend 2024",
        f"{country} corporate tax rate foreign investment M&A",
        f"{country} political stability ease of doing business 2024",
        f"{country} currency repatriation capital controls foreign investment"
    ]
    research_data = []
    for q in searches:
        results = web_search(q, agent_type="country")
        research_data.extend(results)
    
    # 2. Synthesize with LLM
    context = "\n\n".join([f"Source: {r['url']}\n{r['content']}" for r in research_data[:10]])
    response = router.complete(
        "country_agent",
        [{"role": "user", "content": f"Target country: {country}\n\nResearch data:\n{context}\n\nProduce a structured country assessment as JSON following the CountryAssessment schema."}],
        system_prompt=COUNTRY_AGENT_PROMPT
    )
    
    # 3. Parse and validate
    structured = CountryAssessment.model_validate_json(response)
    
    # 4. Format as markdown
    markdown = format_country_markdown(structured)
    
    return {"structured": structured.model_dump(), "markdown": markdown, 
            "confidence": structured.confidence_score, "sources": structured.data_sources}


### Sell-side agents to build:
1. `agents/country_agent/agent.py` — researches TARGET company's country
2. `agents/sector_agent/agent.py` — researches TARGET company's sector
3. `agents/company_agent/agent.py` — researches TARGET company itself

For each: implement the full research loop (5+ search queries), LLM synthesis, schema validation,
markdown output, and Band completion message.

The company_agent is the most data-rich. Its search queries must cover:
- "{company} annual report investor relations 2024"
- "{company} revenue EBITDA financial results 2024"
- "{company} CEO management team executive 2024"
- "{company} shareholders ownership structure"
- "{company} strategic announcement product launch 2024 2025"
- "{company} quarterly results latest earnings"

Test command:
bash
# Test country agent directly (without Band)
python -c "
import asyncio
from agents.country_agent.agent import run_country_assessment
result = asyncio.run(run_country_assessment('test-001', 'Telenor', 'Pakistan'))
print(result['markdown'][:500])
"


COMMIT: "feat: sell-side research agents - country, sector, company"

---

## TASK 4: Buy-Side Research Agents

**Goal**: Build the 3 buy-side agents that profile the acquiring company.

Build agents/buyer_country_agent/agent.py, agents/buyer_sector_agent/agent.py,
and agents/buyer_company_agent/agent.py.

**Key difference from sell-side agents:**
The buy-side agents focus on the ACQUIRER's strategic context:

buyer_country_agent searches for:
- "{buyer_country} outbound M&A regulations foreign investment approval"
- "{buyer_country} tax treaty {target_country} dividend withholding"  
- "{buyer_country} currency stability capital repatriation rules"
- "{buyer_country} geopolitical relations {target_country}"

buyer_sector_agent searches for:
- "{buyer_company} market share revenue 2024 {buyer_sector}"
- "{buyer_company} technology gaps strategic priorities 2025"
- "{buyer_company} antitrust regulatory {target_country} expansion"
- "{buyer_sector} consolidation M&A trends 2024 2025"

buyer_company_agent searches for:
- "{buyer_company} balance sheet cash net debt 2024 annual report"
- "{buyer_company} acquisition history M&A track record"
- "{buyer_company} CEO strategic priorities investor day 2024 2025"
- "{buyer_company} credit rating debt capacity"
- "{buyer_company} share price market cap EV 2024"

The CompanyAssessment schema has buy-side specific fields (cash_position, acquisition_capacity,
stated_strategic_priorities, previous_acquisitions) — populate these for buy-side agents.

Test command:
bash
python -c "
import asyncio
from agents.buyer_company_agent.agent import run_buyer_company_assessment
result = asyncio.run(run_buyer_company_assessment('test-001', 'stc', 'Saudi Arabia'))
print(result['markdown'][:500])
"


COMMIT: "feat: buy-side research agents - buyer country, sector, company"

---

## TASK 5: Synthesis Agents

**Goal**: Build the risk and deal rationale agents that synthesize all prior work.

### risk_agent (agents/risk_agent/agent.py)
Model: deepseek-ai/DeepSeek-R1 on Featherless
This agent reads ALL 6 Phase 1 outputs from the Band room context.

Risk synthesis logic:
1. Parse all 6 structured JSON outputs from room messages
2. Run LLM synthesis prompting it to identify:
   a. Sell-side risks (country + sector + company specific)
   b. Buy-side capability gaps
   c. CROSS-WORKSTREAM RISKS — risks that only emerge when combining buy+sell data
      Example: "Target's 40% net debt/EBITDA + Buyer's existing 3x leverage = HIGH integration debt risk"
      Example: "Target country currency depreciation + Buyer reports in USD = FX earnings volatility"
3. Produce risk matrix with Severity × Probability for each risk
4. Set overall_risk_rating: RED (any HIGH severity HIGH probability), AMBER (any HIGH severity), GREEN (all LOW/MEDIUM)
5. If overall_risk_rating == RED: set human_review_required = True in output

### deal_rationale_agent (agents/deal_rationale_agent/agent.py)
Model: gemma-4-31b-it on Google AI Studio
This agent reads ALL 7 prior outputs (6 Phase 1 + risk assessment).

Deal rationale logic:
1. Parse all prior structured outputs
2. Additional search queries:
   - "{target_company} EV EBITDA valuation multiple 2024 2025"
   - "{sector} {target_country} comparable M&A deals EV multiple 2023 2024"
   - "{target_company} comparable public companies EV EBITDA"
3. Compute:
   - strategic_fit_score (0-10): how specifically does the target fill the buyer's stated gaps?
   - value_creation_avenues: grounded in BUYER's specific gaps and TARGET's specific strengths
   - valuation range: from comp analysis, not generic formula
4. Decision logic:
   - GO: strategic_fit_score >= 7 AND overall_risk_rating != RED
   - NO_GO: strategic_fit_score < 4 OR overall_risk_rating == RED
   - REVISIT: everything in between (specify timeframe and conditions)

Test both agents with mock data from previous task outputs.

COMMIT: "feat: synthesis agents - risk (cross-workstream) + deal rationale (strategic fit)"

---

## TASK 6: Coordinator Agent

**Goal**: Wire everything together through Band's @mention routing.

Build agents/coordinator/agent.py

The coordinator is the most complex agent. It:
1. Listens for a "start_assessment" message with: {buyer_company, target_company, assessment_type}
2. Creates assessment_id (UUID)
3. Infers country and sector for both companies from their names using a quick LLM call
4. Creates output/{assessment_id}/ directory and writes 00_assessment_manifest.json
5. PHASE 1: Simultaneously @mentions all 6 research agents with full params
   - Each @mention message contains: {assessment_id, room_id, target_company, buyer_company, country, sector, assessment_type}
6. Monitors for completion: polls output/{assessment_id}/00_assessment_manifest.json
   - Checks every 30 seconds if completed_agents has all 6 Phase 1 agents
7. PHASE 2: When all 6 Phase 1 agents complete, @mentions @risk-agent
8. PHASE 3: When @risk-agent completes, @mentions @deal-rationale-agent
9. PHASE 4: When @deal-rationale-agent completes:
   - Assembles 09_full_assessment_report.md from all 8 prior files
   - If human_review_required in any output: calls band_add_participant() to add human reviewer
   - Posts final completion message with summary and file list to room
10. Timeout: if any Phase 1 agent doesn't complete within 5 minutes, proceed with PARTIAL

Manifest structure (00_assessment_manifest.json):
json
{
  "assessment_id": "uuid",
  "buyer_company": "stc",
  "target_company": "Telenor Pakistan",
  "assessment_type": "LEVEL_2",
  "started_at": "2026-06-19T02:00:00Z",
  "phase": "PHASE_1 | PHASE_2 | PHASE_3 | COMPLETE",
  "completed_agents": {
    "country-agent": {"file": "...", "completed_at": "..."},
    ...
  },
  "overall_status": "IN_PROGRESS | COMPLETE | NEEDS_HUMAN_REVIEW"
}


Run full integration test:
bash
# Start all agents in separate processes
python -m agents.coordinator.agent &
python -m agents.country_agent.agent &
python -m agents.sector_agent.agent &
python -m agents.company_agent.agent &
python -m agents.buyer_country_agent.agent &
python -m agents.buyer_sector_agent.agent &
python -m agents.buyer_company_agent.agent &
python -m agents.risk_agent.agent &
python -m agents.deal_rationale_agent.agent &

# Trigger assessment via Band (or direct message to coordinator)
python -c "
from agents.coordinator.agent import trigger_assessment
trigger_assessment('stc', 'Telenor Pakistan', 'LEVEL_2')
"


COMMIT: "feat: coordinator agent - full 9-agent pipeline orchestration through Band"

---

## TASK 7: FastAPI Backend

**Goal**: REST API that the dashboard uses to trigger and monitor assessments.

Build api/server.py:

python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uuid, json, os
from pathlib import Path

app = FastAPI(title="M&A Assessment Accelerator API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class AssessmentRequest(BaseModel):
    buyer_company: str
    target_company: str
    assessment_type: str = "LEVEL_2"

@app.post("/assessments")
async def start_assessment(req: AssessmentRequest):
    assessment_id = str(uuid.uuid4())
    # Trigger coordinator agent (send message to Band room or direct call)
    # Return immediately with assessment_id
    return {"assessment_id": assessment_id, "status": "started"}

@app.get("/assessments/{assessment_id}")
async def get_assessment_status(assessment_id: str):
    manifest_path = Path(f"output/{assessment_id}/00_assessment_manifest.json")
    if not manifest_path.exists():
        return {"status": "not_found"}
    with open(manifest_path) as f:
        manifest = json.load(f)
    return manifest

@app.get("/assessments/{assessment_id}/files/{filename}")
async def get_assessment_file(assessment_id: str, filename: str):
    file_path = Path(f"output/{assessment_id}/{filename}")
    if not file_path.exists():
        return {"error": "not found"}
    with open(file_path) as f:
        content = f.read()
    return {"filename": filename, "content": content, "format": "markdown"}

@app.get("/assessments")
async def list_assessments():
    output_dir = Path("output")
    if not output_dir.exists():
        return []
    assessments = []
    for d in output_dir.iterdir():
        manifest = d / "00_assessment_manifest.json"
        if manifest.exists():
            with open(manifest) as f:
                assessments.append(json.load(f))
    return sorted(assessments, key=lambda x: x.get("started_at", ""), reverse=True)


Also serve the dashboard: app.mount("/", StaticFiles(directory="web", html=True), name="static")

Test: uvicorn api.server:app --port 8000 --reload
Verify: curl http://localhost:8000/assessments

COMMIT: "feat: FastAPI backend - assessment management API"

---

## TASK 8: Real-Time Dashboard

**Goal**: Single-file HTML dashboard with live agent progress and streaming results.

Build web/dashboard.html — a complete single-file HTML app (no external dependencies
other than CDN-loaded marked.js for markdown rendering).

### Design System
- Background: #0f172a (dark slate)
- Surface: #1e293b
- Surface 2: #334155
- Text primary: #f8fafc
- Text muted: #94a3b8
- Accent: #14b8a6 (teal)
- Success: #22c55e (green)
- Warning: #f59e0b (amber)
- Error: #ef4444 (red)
- Font: Inter (Google Fonts CDN)

### Layout (single page, no routing)

**Header**: Logo + "M&A Assessment Accelerator" + Band room link (when active)

**Input Section** (shown when no assessment running):
- "Acquirer / Buy-Side Company" text input (placeholder: "e.g. stc — Saudi Telecom Company")
- "Target / Sell-Side Company" text input (placeholder: "e.g. Telenor Pakistan")
- Assessment Type radio: "Level 1 — Ongoing Monitoring" / "Level 2 — Near-term Opportunity"
- "Start Assessment" primary button (teal, full-width)

**Pipeline Status** (shown once assessment starts, updates every 5 seconds):
Show 9 cards in a 3×3 grid:
- Each card: agent icon + agent name + status badge (WAITING/RUNNING/COMPLETE/ERROR)
- When complete: card turns green, shows "Completed in Xm Ys"
- Running card: animated pulse border in teal
- Waiting card: grey, dimmed

**Results Tabs** (shown as agents complete, tabs appear progressively):
Tab 1: "Sell-Side: [Target Country]" — renders country + sector assessment markdown
Tab 2: "Sell-Side: [Target Company]" — renders company assessment markdown
Tab 3: "Buy-Side: [Buyer Company]" — renders buyer country + sector + company markdown combined
Tab 4: "Risk Assessment" — renders risk markdown + visual risk matrix
  Risk matrix: 3×3 grid (severity × probability), risks plotted as colored dots
Tab 5: "Deal Recommendation" — renders deal rationale markdown
  PROMINENT: Large colored badge: GO (green) / NO-GO (red) / REVISIT (amber)
  Below badge: 5 rationale bullet points
  Below that: valuation range as a visual bar chart

**Polling logic** (JavaScript):
- After starting assessment, poll GET /assessments/{id} every 5 seconds
- When a new agent appears in completed_agents, fetch its file and render in the appropriate tab
- Tab appears as soon as its agent(s) complete
- Stop polling when manifest.overall_status == "COMPLETE" or "NEEDS_HUMAN_REVIEW"

**Band room link**: Display prominently at top: "Watch agents collaborate in real-time →"
Link to the Band room URL (hardcode as a constant at top of HTML since it's fixed per deployment)

Use marked.js CDN for rendering markdown to HTML:
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>

COMMIT: "feat: real-time dashboard with progressive agent output display"

---

## TASK 9: Demo Data + Documentation

### demo/targets/telenor_pakistan.json
json
{
  "buyer_company": "stc",
  "buyer_country": "Saudi Arabia",
  "buyer_sector": "Telecommunications",
  "target_company": "Telenor Pakistan",
  "target_country": "Pakistan",
  "target_sector": "Telecommunications",
  "assessment_type": "LEVEL_2",
  "context": "November 2022: Telenor is exploring options to sell its mobile operations in Pakistan. stc is evaluating as a potential acquirer."
}


### demo/run_demo.py
Script that:
1. Triggers an assessment via POST /assessments
2. Prints status every 30 seconds
3. Reports when each agent completes
4. Prints final Go/No-Go decision

### README.md
Write a comprehensive README with:
1. Project overview (2 paragraphs)
2. Architecture diagram (ASCII art showing 9 agents + Band coordination)
3. Prerequisites: Python 3.11, Band account, API keys
4. Setup steps (numbered, copy-pasteable commands)
5. Running the demo
6. Hackathon track and judging criteria alignment

### ARCHITECTURE.md
Write technical architecture doc with:
1. Agent responsibilities table
2. Band integration explanation (why @mention routing, what goes through Band)
3. API model allocation table (which model for which agent, why)
4. Data flow diagram
5. Output file structure

COMMIT: "feat: demo data, run_demo.py, complete documentation"

---

## TASK 10: Final Pre-Submission Checks

Run this checklist and fix anything that fails:

bash
# 1. Full pipeline test
python demo/run_demo.py

# 2. Verify all output files created
ls output/*/  

# 3. API server test
uvicorn api.server:app --port 8000 &
curl http://localhost:8000/assessments
curl http://localhost:8000/assessments/{id from demo run}

# 4. Dashboard manual check
# Open web/dashboard.html in browser (or via port 8000)
# Verify: input form works, pipeline status updates, all tabs load

# 5. Security check — no hardcoded keys
grep -r "sk-" agents/ || echo "No hardcoded keys found"
grep -r "AIza" agents/ || echo "No Google keys found"

# 6. Requirements check
pip freeze > requirements_actual.txt
diff requirements.txt requirements_actual.txt  # Fix any missing packages

# 7. .env.example completeness
diff <(cat .env.example | grep "=" | cut -d= -f1) <(cat .env | grep "=" | cut -d= -f1)


Fix all failures. Then:

COMMIT: "chore: final pre-submission verification - all checks passing"

---

## After All Tasks Complete

Print this to the terminal:

========================================
BUILD COMPLETE
========================================
All 10 tasks finished.
Output directory: output/
API server: uvicorn api.server:app --port 8000
Dashboard: http://localhost:8000
Demo: python demo/run_demo.py

Next steps for human:
1. Record demo video (5 min max)
2. Submit on lablab.ai before June 19 11:00 AM EDT
========================================