# M&A Assessment Accelerator

A multi-agent system that compresses M&A target due diligence from 2 weeks to 2-4 hours. Given a buyer and target company, nine specialized AI agents collaborate through Band to produce a structured Go/No-Go investment recommendation covering country risk, sector dynamics, company financials, cross-workstream risk synthesis, and deal valuation.

Built for the Band of Agents Hackathon (June 2026), the system demonstrates how agent-to-agent coordination via Band's @mention routing enables parallel research workflows that would otherwise require sequential analyst handoffs.

## Architecture

```
                        ┌─────────────────────────────────────────┐
                        │           @coordinator                   │
                        │   Orchestrates all 9 agents via Band    │
                        └──────────────┬──────────────────────────┘
                                       │ @mentions (parallel)
              ┌────────────────────────┼──────────────────────────────────┐
              │                        │                                  │
     SELL-SIDE (target)        SELL-SIDE (target)              BUY-SIDE (acquirer)
   ┌──────────────────┐     ┌──────────────────┐          ┌───────────────────────┐
   │ @country-agent   │     │ @company-agent   │          │ @buyer-country-agent  │
   │ @sector-agent    │     │ (financials,     │          │ @buyer-sector-agent   │
   │ (macro, policy,  │     │  management,     │          │ @buyer-company-agent  │
   │  FX, regulations)│     │  shareholders)   │          │ (capacity, strategy,  │
   └──────────────────┘     └──────────────────┘          │  M&A track record)    │
                                                           └───────────────────────┘
                                       │ (Phase 2)
                              ┌────────────────┐
                              │  @risk-agent   │
                              │ Cross-workstream│
                              │ risk synthesis │
                              └───────┬────────┘
                                      │ (Phase 3)
                              ┌────────────────────┐
                              │ @deal-rationale-   │
                              │ agent              │
                              │ Go/No-Go + valuation│
                              └────────────────────┘
```

## Prerequisites

- Python 3.11+
- Band account with 9 registered agents
- API keys: Google AI Studio, Featherless AI, Tavily, Band SDK

## Setup

```bash
# 1. Clone and install
git clone https://github.com/ryker-code/MA-assessment-accelerator
cd MA-assessment-accelerator
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Verify setup
python -c "import openai, yaml; print('deps OK')"
```

## Running the Demo

```bash
# Terminal 1: Start the API server
uvicorn api.server:app --port 8000 --reload

# Terminal 2: Run the demo (stc acquiring Telenor Pakistan)
python demo/run_demo.py

# Open the dashboard
open http://localhost:8000
```

## Hackathon Track

**Band of Agents** — demonstrating multi-agent coordination via @mention routing.

**Judging criteria alignment:**
- **Band integration**: All 9 agents communicate exclusively through Band @mentions
- **Multi-agent**: Parallel Phase 1 (6 agents) → Sequential Phase 2-3 synthesis
- **Real-world utility**: M&A due diligence is a documented 2-week process compressed to hours
- **Cross-workstream insight**: Risk agent surfaces risks only visible by combining buy+sell data
