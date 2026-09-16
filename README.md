# AstraAi

AI software development agent. LangGraph orchestrates each run; FastAPI serves it.

Status: early backend. A run analyzes a coding task into structured requirements, designs a language-neutral test plan, writes the solution and its tests, then runs them in a locked-down Docker container:

```
START → analyze_task → generate_tests → generate_code → execute_sandbox → END
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
    state.py             graph state, run context, Requirements/GeneratedTests/GeneratedCode
    graph.py             StateGraph wiring
    nodes/
      analyze_task.py    task → Requirements
      generate_tests.py  task + Requirements → GeneratedTests (test plan, no code)
      generate_code.py   + test plan → GeneratedCode (solution and test code)
      execute_sandbox.py + sandbox → ExecutionResult (runs the tests)
    sandbox/
      executor.py        SandboxExecutor protocol and per-language layout
      docker.py          ephemeral container runner
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
| `LLM_MAX_ATTEMPTS`    | Optional. Total attempts per LLM call, 1-5 (2)           |
| `LLM_RETRY_BACKOFF_SECONDS` | Optional. Backoff × attempt number between tries; a 429's Retry-After up to 30s wins (1) |
| `LLM_MAX_CONCURRENCY` | Optional. LLM requests in flight at once per process, 1-8 (2) |

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

| Status | Meaning                                                             |
| ------ | ------------------------------------------------------------------- |
| 200    | `{"run_id": "...", "requirements": {...}, "generated_tests": {...}, "generated_code": {...}, "execution_result": {...}}` |
| 422    | Invalid request: missing/blank task, unsupported language           |
| 502    | LLM request failed or returned invalid structured output            |
| 504    | LLM request timed out                                               |

## Generated code contract

`generated_code` holds four strings: `language`, `solution_code`, `test_code` and `explanation`.
The Docker sandbox will write them to files and run them:

| Language | Files | Command |
| -------- | ----- | ------- |
| `python` | `solution.py`, `test_solution.py` | `python test_solution.py` |
| `cpp` | `solution.cpp`, `test_solution.cpp` | `g++ -std=c++17 test_solution.cpp -o tests && ./tests` |

Test code imports or includes the solution, uses only the standard library, prints `FAIL <case>: expected <x>, got <y>` per failure and `PASSED <n> tests` otherwise, and exits non-zero if any case fails.

## Sandbox

Every execution gets its own container, which is removed afterwards. The generated code is
streamed in as a tar on the container's stdin and unpacked into a tmpfs, so **no host directory
is ever mounted** and the root filesystem stays read-only.

| Restriction | Setting |
| ----------- | ------- |
| No network | `--network none` |
| Non-root | `--user 65534:65534` |
| No privilege escalation | `--security-opt no-new-privileges`, `--cap-drop ALL` |
| Read-only root | `--read-only`, writable tmpfs only at `/sandbox` |
| CPU / memory | `--cpus 1.0`, `--memory 512m`, `--memory-swap 512m` (no swap) |
| Processes | `--pids-limit 64` |
| Time | killed after `SANDBOX_TIMEOUT_SECONDS` (30) |
| Output | capped at `SANDBOX_MAX_OUTPUT_BYTES` (64000) |
| Concurrency | one execution at a time (`SANDBOX_MAX_CONCURRENCY`) |

Only the C++ tmpfs allows `exec`, because the compiled test binary runs from it.

**Deployment note.** The backend drives the host Docker daemon through the `docker` CLI, so it
must run somewhere that is allowed to do that. Do not mount the Docker socket into a
publicly reachable API container: socket access is equivalent to root on the host. For the
Oracle VPS, run the API on the host (systemd) next to the daemon, or split the executor into a
separate internal service. `SandboxExecutor` exists so that swap needs no changes to the graph.

## Test

Tests run in the venv:

```bash
cd backend
uv run pytest                          # never calls a real LLM, never uses Docker
uv run ruff format . && uv run ruff check .
```

Opt-in checks. The Docker suite needs the local daemon and the sandbox images:

```bash
ASTRAAI_DOCKER_TESTS=1 uv run pytest tests/test_sandbox_docker.py
```

Opt-in check of the whole workflow against the real endpoint in `.env`:

```bash
ASTRAAI_LIVE_LLM=1 uv run pytest tests/test_llm_live.py        # PowerShell: $env:ASTRAAI_LIVE_LLM=1; uv run pytest tests/test_llm_live.py
```
