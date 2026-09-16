# AstraAi

AI software development agent. LangGraph orchestrates each run; FastAPI serves it.

Status: early backend. A run analyzes a coding task into structured requirements, designs a language-neutral test plan, writes the solution and its tests, runs them in a locked-down Docker container, then has a critic judge the result:

```
START → analyze_task → generate_tests → generate_code → execute_sandbox → critic → END
```

## Layout

```
compose.yaml             local Docker setup
backend/
  Dockerfile
  app/
    main.py              FastAPI app: GET /health, POST /runs, GET /runs/{run_id}
    runs.py              RunManager: run records, bounded queue, in-process workers
    config.py            settings from environment variables / .env
    llm.py               structured-output client for the OpenAI-compatible endpoint
    state.py             graph state, run context, Requirements/GeneratedTests/GeneratedCode
    graph.py             StateGraph wiring
    nodes/
      analyze_task.py    task → Requirements
      generate_tests.py  task + Requirements → GeneratedTests (test plan, no code)
      generate_code.py   + test plan → GeneratedCode (solution and test code)
      execute_sandbox.py + sandbox → ExecutionResult (runs the tests)
      critic.py          everything so far → CriticResult (verdict, no code)
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

Runs are asynchronous. `POST /runs` validates the request, queues the run and returns at
once; poll `GET /runs/{run_id}` for progress and results.

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"task": "Return indices of two numbers that add up to target.", "language": "cpp"}'
# 202 {"run_id": "…", "status": "queued"}

curl http://127.0.0.1:8000/runs/<run_id>
```

Supported languages: `python`, `cpp`.

| Endpoint | Status | Meaning |
| -------- | ------ | ------- |
| `POST /runs` | 202 | Accepted: `{"run_id", "status": "queued"}` |
| `POST /runs` | 422 | Invalid request: missing/blank task, unsupported language |
| `POST /runs` | 429 | Queue full (`Retry-After: 30`) |
| `GET /runs/{run_id}` | 200 | The run, with whatever results exist so far |
| `GET /runs/{run_id}` | 404 | Unknown run |

A run has `status` (`queued`, `running`, `completed`, `failed`) and a `stage` that moves in
this order: `queued` → `analyzing` → `generating_tests` → `generating_code` → `executing` →
`reviewing` → `completed`, or `failed` from any step. `requirements`, `generated_tests`, `generated_code`
`execution_result` and `critic_result` fill in as each step finishes and are kept if a later step fails.
A failed run carries a safe `error` of `{code, message, stage}`, never internal details.

Failing generated tests still produce a `completed` run: the answer is in
`execution_result.status`. A run only fails when a step could not do its job.

One full run executes at a time (`RUN_MAX_ACTIVE_RUNS`), up to `RUN_MAX_QUEUED_RUNS` wait,
and the newest `RUN_MAX_RETAINED_RUNS` finished runs are kept in memory.

A whole run is stopped after `RUN_TIMEOUT_SECONDS` (300; per-LLM-call and sandbox timeouts
still apply inside it) and fails with `run_timeout`; its sandbox container is removed and the
next queued run starts. On shutdown the service stops accepting runs (`POST` returns 503),
waiting runs fail with `shutdown`, and the active run is cancelled and its container removed
before the process exits. Runs are held in memory, so a restart forgets them.

## Generated code contract

`generated_code` holds four strings: `language`, `solution_code`, `test_code` and `explanation`.
The Docker sandbox will write them to files and run them:

| Language | Files | Command |
| -------- | ----- | ------- |
| `python` | `solution.py`, `test_solution.py` | `python test_solution.py` |
| `cpp` | `solution.cpp`, `test_solution.cpp` | `g++ -std=c++17 test_solution.cpp -o tests && ./tests` |

Test code imports or includes the solution, uses only the standard library, prints `FAIL <case>: expected <x>, got <y>` per failure and `PASSED <n> tests` otherwise, and exits non-zero if any case fails.

## Critic

`critic_result` is five flat fields: `verdict`, `reason`, `code_issue`, `test_issue` and
`recommended_action`. It judges the code against the **requirements**, treating the test run
as evidence rather than truth, so a failing test can be blamed on the test.

| Verdict | Meaning | Usual action |
| ------- | ------- | ------------ |
| `pass` | The code meets the requirements | `accept` (and only for pass) |
| `code_failure` | The implementation is wrong | `revise_code` |
| `test_failure` | A test's expected result contradicts the requirements | `revise_tests` |
| `execution_failure` | No trustworthy evidence (compile error, crash, tooling) | varies |
| `ambiguous` | The evidence cannot tell code and test apart | `needs_human_review` |

Sandbox outcomes that say nothing about the code's logic are classified without the model, as
`execution_failure`: `infrastructure_error` recommends `retry_execution`; `timed_out` and
`resource_exceeded` recommend `needs_human_review`, because a limit does not prove the code is
wrong. Compile errors, runtime errors and failed assertions go to the model.

The model's verdict is then checked against the evidence. A `pass` only stands when the tests
passed; otherwise it becomes `ambiguous` with `needs_human_review`. An invalid answer from the
model becomes the same safe verdict rather than being trusted or failing the run.

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
ASTRAAI_E2E_TESTS=1 uv run pytest tests/test_runs_e2e.py   # lifecycle over HTTP, fakes
```

Opt-in check of the whole workflow against the real endpoint in `.env`:

```bash
ASTRAAI_LIVE_LLM=1 uv run pytest tests/test_llm_live.py        # PowerShell: $env:ASTRAAI_LIVE_LLM=1; uv run pytest tests/test_llm_live.py
```
