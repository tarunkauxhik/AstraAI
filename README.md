# AstraAi

AI software development agent. LangGraph orchestrates each run; FastAPI serves it.

Status: early backend. A run analyzes a coding task into structured requirements:

```
START → analyze_task → END
```

## Layout

```
compose.yaml             local Docker setup
backend/
  Dockerfile
  app/
    main.py              FastAPI app: GET /health, POST /runs
    config.py            settings from environment variables / .env
    llm.py               structured-output client for the OpenAI-compatible endpoint
    state.py             graph state, run context, Requirements schema
    graph.py             StateGraph wiring
    nodes/
      analyze_task.py    task → Requirements
  tests/
```

Nothing is installed globally: Python dependencies live in `backend/.venv` (managed by [uv](https://docs.astral.sh/uv/)) or inside the Docker image.

## Configuration

```bash
cd backend
cp .env.example .env      # Windows: copy .env.example .env
```

Fill in `backend/.env`:

| Variable              | Purpose                                                  |
| --------------------- | -------------------------------------------------------- |
| `OPENAI_BASE_URL`     | OpenAI-compatible endpoint base URL                      |
| `OPENAI_API_KEY`      | API key for that endpoint                                |
| `OPENAI_MODEL`        | Model name, e.g. a MiniMax model                         |
| `LLM_TIMEOUT_SECONDS` | Optional. Seconds before an LLM call is abandoned (120)  |

The app refuses to start if any required value is missing or invalid. Real environment variables override `.env`.

## Run with Docker

From the repository root:

```bash
docker compose up --build      # API on http://127.0.0.1:8000
docker compose watch           # same, rebuilding on changes to backend/app or uv.lock
```

## Run with the local venv

```bash
cd backend
uv sync                        # creates backend/.venv with runtime + dev dependencies
uv run uvicorn app.main:app --reload
```

## API

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"task": "Return indices of two numbers that add up to target.", "language": "cpp"}'
```

Supported languages: `python`, `cpp`.

| Status | Meaning                                                   |
| ------ | --------------------------------------------------------- |
| 200    | `{"run_id": "...", "requirements": {...}}`                |
| 422    | Invalid request: missing/blank task, unsupported language |
| 502    | LLM request failed or returned invalid structured output  |
| 504    | LLM request timed out                                     |

## Test

Tests run in the venv:

```bash
cd backend
uv run pytest                          # never calls a real LLM
uv run ruff format . && uv run ruff check .
```

Opt-in check against the real endpoint in `.env`:

```bash
ASTRAAI_LIVE_LLM=1 uv run pytest tests/test_llm_live.py        # PowerShell: $env:ASTRAAI_LIVE_LLM=1; uv run pytest tests/test_llm_live.py
```
