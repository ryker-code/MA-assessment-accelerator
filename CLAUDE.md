# CLAUDE.md — M&A Assessment Accelerator

## Project State (as of June 19, 2026)
This is a working V1 submission for the Band of Agents Hackathon.
The app runs on FastAPI + Band SDK with 9 agents.

## Running the App
```bash
uvicorn api.server:app --reload --port 8000
```

## Key Files
- `api/server.py` — FastAPI app, SSE streaming endpoint
- `agents/` — 9 agent modules, each calls Band + LLMRouter
- `agents/shared/llm_router.py` — Pluggable model interface
- `config/models.yaml` — Change any model here (no code changes)
- `web/index.html` — Dashboard frontend

## Model Config (Current Default)
- Coordinator: gemma-4-31b-it via Google AI Studio
- Country/Sector/Buyer agents: Qwen3-14B via Featherless
- Risk agent: DeepSeek-R1 via Featherless  
- Deal Rationale: gemma-4-31b-it via Google AI Studio

## To Swap a Model
Edit `config/models.yaml` and change provider/model for any agent. No code changes needed.

## V2 Priorities
1. Real financial data ingestion (SEC EDGAR, Bloomberg API)
2. PDF/filing upload support for company-agent vision tasks
3. Human-in-the-loop review gates via Band shared rooms
4. Persistent database for assessment history
5. Export to PowerPoint/PDF
