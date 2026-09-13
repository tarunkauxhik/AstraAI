# AstraAi

AI software development agent. LangGraph orchestrates each run; FastAPI serves it.

Status: backend foundation only — `GET /health` and a compiling LangGraph `StateGraph`. No agent workflow yet.

## Layout

```
backend/
  app/
    main.py     FastAPI app and /health
    config.py   settings from environment variables / .env
    state.py    LangGraph state schema
    graph.py    StateGraph builder
  tests/
```

## Local setup

Requires [uv](https://docs.astral.sh/uv/). It installs Python 3.12 if missing and keeps everything in `backend/.venv`.

```bash
cd backend
uv sync                   # runtime + dev dependencies into .venv
cp .env.example .env      # Windows: copy .env.example .env
```

Fill in `backend/.env`:

| Variable          | Purpose                             |
| ----------------- | ----------------------------------- |
| `OPENAI_BASE_URL` | OpenAI-compatible endpoint base URL |
| `OPENAI_API_KEY`  | API key for that endpoint           |
| `OPENAI_MODEL`    | Model name, e.g. a MiniMax model    |

The app refuses to start if any of these are missing or invalid. Real environment variables override `.env`.

## Run

```bash
uv run uvicorn app.main:app --reload
curl http://127.0.0.1:8000/health   # {"status":"ok","service":"astraai"}
```

## Test

```bash
uv run pytest
```

Tests use dummy settings; they never read `.env` or call a real LLM.
