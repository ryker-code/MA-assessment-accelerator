# Architecture

## Agent Responsibilities

| Agent | Model | Phase | Responsibility |
|-------|-------|-------|----------------|
| @coordinator | gemma-4-31b-it (Gemini) | 0 | Orchestrates all agents, assembles final report |
| @country-agent | Qwen3-14B (Featherless) | 1 | Target country macro, FX, political risk |
| @sector-agent | Qwen3-14B (Featherless) | 1 | Target sector size, competition, regulation |
| @company-agent | gemma-4-31b-it (Gemini) | 1 | Target company financials, management, shareholders |
| @buyer-country-agent | Qwen3-14B (Featherless) | 1 | Buyer country outbound M&A environment |
| @buyer-sector-agent | Qwen3-14B (Featherless) | 1 | Buyer competitive gaps and antitrust |
| @buyer-company-agent | Qwen3-14B (Featherless) | 1 | Buyer balance sheet and acquisition capacity |
| @risk-agent | DeepSeek-R1 (Featherless) | 2 | Cross-workstream risk synthesis |
| @deal-rationale-agent | gemma-4-31b-it (Gemini) | 3 | Go/No-Go decision, valuation, next steps |

## Band Integration

All inter-agent communication happens via Band @mentions. The coordinator dispatches Phase 1 agents simultaneously by posting a single message mentioning all 6 handles. Agents receive their parameters as JSON in the message body, execute independently, save output as markdown, and post a completion notification back to the room.

The coordinator monitors completion by polling the local `00_assessment_manifest.json` file, which each agent updates via `save_agent_output()`. This avoids complex polling of Band's API and keeps the state machine simple.

## Model Allocation

| Provider | Models | Agents | Rationale |
|----------|--------|--------|-----------|
| Google AI Studio | gemma-4-31b-it | coordinator, company, deal_rationale | Long context for synthesis (6-8k tokens output) |
| Featherless | Qwen3-14B | country, sector, buyer agents | Cost-efficient for structured JSON research tasks |
| Featherless | DeepSeek-R1 | risk_agent | Reasoning model for cross-workstream inference |

## Data Flow

```
User Input (buyer + target)
    ↓
API POST /assessments
    ↓ (background task)
coordinator.run_assessment()
    ↓ infer_company_context() — quick LLM call
    ↓
Phase 1: asyncio.gather(6 research agents)
    ↓ each agent:
    │   web_search() × 5 queries → Tavily API
    │   LLMRouter.complete() → provider API
    │   save_agent_output() → output/{id}/NN_agent.md
    │   update_manifest() → 00_assessment_manifest.json
    ↓
Phase 2: risk_agent.run_risk_assessment()
    ↓ reads all 6 Phase 1 markdown files
    ↓ LLM synthesis → RiskAssessment JSON
    ↓ save_agent_output() → 07_risk_agent.md
    ↓
Phase 3: deal_rationale_agent.run_deal_rationale()
    ↓ reads all 7 prior markdown files
    ↓ additional valuation web_search() × 3
    ↓ LLM synthesis → DealRationale JSON
    ↓ save_agent_output() → 08_deal_rationale_agent.md
    ↓
assemble_final_report() → 09_full_assessment_report.md
    ↓
manifest.overall_status = COMPLETE
    ↓
Dashboard poll picks up → renders tabs progressively
```

## Output File Structure

```
output/{assessment_id}/
├── 00_assessment_manifest.json   # Live state tracker
├── 01_country_agent.md           # Pakistan macro assessment
├── 02_sector_agent.md            # Telecom sector analysis
├── 03_company_agent.md           # Telenor Pakistan profile
├── 04_buyer_country_agent.md     # Saudi Arabia outbound M&A
├── 05_buyer_sector_agent.md      # stc competitive position
├── 06_buyer_company_agent.md     # stc financial capacity
├── 07_risk_agent.md              # Risk matrix + cross-workstream
├── 08_deal_rationale_agent.md    # Go/No-Go + valuation
└── 09_full_assessment_report.md  # Assembled complete report
```

## LLM Response Caching

All LLM responses are cached to `.cache/llm/` using SHA256(model + messages) as the key. Default TTL is 24 hours (configurable via `CACHE_TTL_HOURS`). The `deal_rationale_agent` disables caching (`use_cache: false`) since its output must reflect the latest risk synthesis.
