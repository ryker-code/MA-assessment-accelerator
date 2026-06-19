# M&A Assessment Accelerator

> **Band of Agents Hackathon 2026** — Track 3: Regulated & High-Stakes Workflows

A multi-agent AI system that compresses a 2-week M&A target assessment into **2–4 hours**. Nine specialized agents coordinate through [Band](https://band.ai) to produce a structured Go/No-Go investment recommendation.

## Live Demo
🔗 **[Try it live →](YOUR_DEPLOYED_URL)**

## What It Does
Enter an acquirer and a target company. Nine AI agents run in parallel and sequentially to produce:
- Country risk profiles (buy-side + sell-side)
- Sector/competitive landscape (buy-side + sell-side)  
- Company financial profiles (buy-side + sell-side)
- Cross-workstream risk synthesis
- Deal rationale with Go/No-Go recommendation + valuation range

Each agent saves its output as a structured Markdown file. The dashboard shows results in real-time as agents complete.

## Agent Architecture

@coordinator (Gemini)
├── PHASE 1 (Parallel)
│ ├── @country-agent ← Sell-side country/macro
│ ├── @sector-agent ← Sell-side sector dynamics
│ ├── @company-agent ← Sell-side financials (Gemini vision)
│ ├── @buyer-country-agent ← Buy-side home market
│ ├── @buyer-sector-agent ← Buy-side competitive position
│ └── @buyer-company-agent ← Buy-side financial capacity
├── PHASE 2 (Sequential)
│ └── @risk-agent ← Cross-workstream synthesis (DeepSeek-R1)
└── PHASE 3
└── @deal-rationale-agent ← Go/No-Go + valuation (Gemini)


## Tech Stack
| Component | Technology |
|---|---|
| Agent Coordination | [Band](https://band.ai) @mention routing |
| Orchestration | Gemma 4 31B IT (Google AI Studio) |
| Research Agents | Qwen3-14B (Featherless AI) |
| Risk Reasoning | DeepSeek-R1 (Featherless AI) |
| Backend | FastAPI (Python) |
| Frontend | HTML/CSS/JS with SSE streaming |
| Caching | Disk-based SHA256 response cache |
| Output | Per-agent Markdown files in `/output` |

## Quickstart

```bash
git clone https://github.com/YOUR_USERNAME/MA-assessment-accelerator
cd MA-assessment-accelerator
cp .env.example .env   # Add your API keys
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

Open `http://localhost:8000`

## API Keys Required
GOOGLE_API_KEY= # Google AI Studio (free, 1500 req/day)
BAND_API_KEY= # Band Pro
FEATHERLESS_API_KEY= # Featherless Premium
AIML_API_KEY= # AI/ML API (optional, swap via config/models.yaml)


## Example Assessment
**Acquirer**: T-Mobile  
**Target**: Telesat  
→ Produces 9 agent reports + executive Go/No-Go memo in ~3-4 minutes

## Project Structure
├── agents/ # 9 Band-connected agent modules
│ └── shared/ # LLMRouter, caching, Band client
├── api/ # FastAPI backend with SSE streaming
├── web/ # Dashboard frontend
├── config/ # models.yaml — swap any model in one line
├── output/ # Per-assessment Markdown outputs
└── demo/ # Pre-cached demo scenarios


## Hackathon
Built for the **Band of Agents Hackathon** (June 2026) in 35 hours.  
Demonstrates meaningful multi-agent coordination where Band's @mention routing enables parallel research workflows impossible with single-agent systems.

## License
MIT
ENDOFREADME
echo "README updated"
