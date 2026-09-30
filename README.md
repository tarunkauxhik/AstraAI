# AstraAi

AI software development agent. LangGraph orchestrates each run; FastAPI serves it.

Status: early backend. A run analyzes a coding task into structured requirements, designs a language-neutral test plan, writes the solution and its tests, runs them in a locked-down Docker container, has a critic judge the result, and repairs the code or tests within a small budget:

```
START → analyze_task → generate_tests → generate_code → execute_sandbox → critic
critic → END                                  (accept, human review, budget exhausted)
critic → revise_code     → execute_sandbox   (at most 2 revisions in total)
critic → revise_tests    → execute_sandbox
critic → retry_execution → execute_sandbox   (at most 1 retry, infrastructure errors only)
```

## Layout

```
compose.yaml             local Docker setup
backend/
  Dockerfile
  app/
    main.py              FastAPI app: /health, /runs, /runs/{run_id}, approval and more time
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
      revise_code.py     diagnosis → RevisedSolution (solution code only)
      revise_tests.py    diagnosis → RevisedTests (test code only)
      retry_execution.py counts one re-execution after an infrastructure error
    repair.py            revision/retry budgets and the router after the critic
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
| `APPROVAL_TIMEOUT_SECONDS` | Optional. Seconds a verified solution waits for a human decision (restartable with more time) before the run expires, 5-86400 (600) |
| `DATA_DIR` | Optional. Directory for the run and checkpoint databases (`backend/data`) |
| `GITHUB_TOKEN` | Optional. Only for private repositories in Develop: a read-only fine-grained token (Contents: read). Public repositories need none |

Run lifecycle and sandbox limits are listed, with defaults, in `backend/.env.example`.

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
| `POST /runs` | 422 | Invalid request: missing/blank task, unsupported language, or a Develop run without a GitHub repository |
| `POST /runs` | 429 | Queue full (`Retry-After: 30`) |
| `GET /runs/{run_id}` | 200 | The run, with whatever results exist so far |
| `GET /runs/{run_id}` | 404 | Unknown run |
| `POST /runs/{run_id}/approval` | 202 | `{"decision": "approve"}` resumes the run (`status: running`); `"reject"` ends it (`status: failed`) |
| `POST /runs/{run_id}/approval` | 404 | Unknown run |
| `POST /runs/{run_id}/approval` | 409 | Not waiting for approval: already decided, finished, or expired |
| `POST /runs/{run_id}/approval` | 422 | Anything other than exactly `approve` or `reject` |
| `POST /runs/{run_id}/approval` | 429 / 503 | Queue full / shutting down |
| `POST /runs/{run_id}/approval/extend` | 200 | More time: `{"run_id", "approval_expires_at"}`, a fresh window counted from now |
| `POST /runs/{run_id}/approval/extend` | 404 / 409 / 503 | Unknown run / not waiting or already expired / shutting down |

A run has `status` (`queued`, `running`, `waiting_for_approval`, `completed`, `failed`, `expired`) and a `stage` that moves in
this order: `queued` → `analyzing` → `generating_tests` → `generating_code` → `executing` →
`reviewing` → `waiting_for_approval` → `resuming` → `completed` (or `expired`), or `failed` from any step. A repair adds `revising_code` or
`revising_tests` followed by `executing` and `reviewing` again. `requirements`, `generated_tests`, `generated_code`
`execution_result` and `critic_result` fill in as each step finishes and are kept if a later step fails.
A failed run carries a safe `error` of `{code, message, stage}`, never internal details.

A run is `completed` only when the critic accepts the final code **and a human approves it**.
When the critic accepts, the run pauses at `waiting_for_approval` (`approval_status: pending`,
`approval_required: true`) with a compact `approval_request` and `approval_expires_at`. The
paused graph is checkpointed in SQLite under the run id and frees the worker for other runs.
Approving sets `approval_status: approved` and stage `resuming`, then continues the same
LangGraph thread without repeating any LLM call or execution. Rejecting fails the run at once
with `approval_rejected`. With no decision within `APPROVAL_TIMEOUT_SECONDS`, counted from
when approval was requested, the run ends as `expired` (`approval_status: expired`, no
`error`): the solution passed every check, so it is not a failure, and its code, tests and
evidence stay on the run. A background sweep checks once a minute, and a late decision gets
409 either way. `POST /runs/{run_id}/approval/extend` restarts the window from now, as often
as the reviewer needs. Checkpoints are deleted as soon as a run ends.

Otherwise it is `failed`
with `error.code` `needs_human_review`, `revision_budget_exhausted` or `sandbox_unavailable`,
keeping the latest code, execution result and critic result. `revision_count` and
`execution_retry_count` show how much of each budget a run used.

One full run executes at a time (`RUN_MAX_ACTIVE_RUNS`), up to `RUN_MAX_QUEUED_RUNS` wait,
and the newest `RUN_MAX_RETAINED_RUNS` runs are kept; only finished runs are ever removed.

A whole run is stopped after `RUN_TIMEOUT_SECONDS` (300) of active work (per-LLM-call and
sandbox timeouts still apply inside it; time waiting for approval never counts) and fails with `run_timeout`; its sandbox container is removed and the
next queued run starts. On shutdown the service stops accepting runs (`POST` returns 503) and
the active run is cancelled, failing with `shutdown`, and its container removed before the
process exits, unless it was resuming an approved run: queued, approval-waiting and
approved runs are all left for the next start.

## Develop (first slice)

`POST /runs` with `"mode": "develop"` and a `"repository"` (a GitHub URL or `owner/name`)
checks an existing Python repository instead of writing a function:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"task": "Add a --json flag.", "language": "python", "mode": "develop", "repository": "https://github.com/owner/name"}'
```

AstraAi resolves the repository's default branch to its current commit, downloads the
repository at exactly that commit, and runs its existing test suite as-is with
`python -m pytest` in the sandbox. The run then carries `repository_ref` (the pinned
version) and `existing_tests` (the result, failing tests included) and ends `completed`,
or `failed` when the repository can't be fetched (`repository_not_public`,
`repository_not_found`, `repository_empty`, `repository_too_large`,
`repository_unsupported`, `github_unavailable`) or its tests can't run here
(`environment_unsupported`: usually a dependency, since nothing is installed). No code is
changed and nothing is written to GitHub yet.

- **Repository data is untrusted.** The archive is read in memory, never extracted to
  disk: regular files only, no links or devices, no absolute or `..` paths, at most 20 MB
  downloaded, 64 MB unpacked and 10,000 files. It reaches the sandbox only as a tar on
  stdin, and is dropped as soon as the run stops working. It never enters run state or
  checkpoints.
- **GitHub access is read-only.** Public repositories need no token. `GITHUB_TOKEN`, if
  set, is sent to `api.github.com` only: never to the download redirect, the sandbox, the
  model, run state, checkpoints or logs.
- **The sandbox image** is Python 3.12 with a pinned pytest and nothing else. Build it once;
  only the build uses the network:

  ```bash
  docker build -t astraai-sandbox-python:3.12.14-pytest9.1.1 backend/sandbox
  ```

  Tests run with the usual sandbox restrictions (no network, read-only root, no
  capabilities, non-root), 1 GB of memory, a 256 MB tmpfs and a 120-second limit.

## Durability

Runs survive restarts. Two SQLite files live in `DATA_DIR` (default `backend/data`, a named
volume under Docker): `runs.sqlite3` holds every run exactly as `GET /runs/{run_id}` returns
it and is the only source of truth for the API; `checkpoints.sqlite3` holds LangGraph
checkpoints, only for runs paused at approval, so an approval after a restart resumes the
same thread. On start, before any run executes, leftover sandbox containers are removed and
each unfinished run is reconciled:

| Stored as | After a restart |
| --- | --- |
| `queued` | Queued again in its original order; it had not started. |
| `running` (any working stage) | `failed` with `shutdown`, keeping the evidence it had. The work is never continued and no unobserved execution is reported. |
| `waiting_for_approval` | Still waiting, same `approval_expires_at`; approve, reject or extend as before. Fails with `shutdown` if its checkpoint is missing. |
| `running` / `resuming` (approved) | Completes: resumes the same thread if its checkpoint is paused at approval, or records the completion if the resume already reached the end. Resuming replays only the approval step, which has no side effects, so repeated crashes never repeat work. Fails with `shutdown` only without a usable checkpoint. |
| `completed`, `failed`, `expired` | Unchanged, with all evidence. |

Both databases use SQLite's WAL mode: each is its `.sqlite3` file plus the `-wal` and
`-shm` files beside it, and after a crash the latest writes may exist only in `-wal`. Back
up by stopping the service and copying the whole `DATA_DIR`, those files included; never
copy a `.sqlite3` file alone, or one database without the other. Reset by stopping the
service and deleting the whole `DATA_DIR` (`docker compose down --volumes` under Docker,
whose named volume is that directory); it is recreated empty on start.

One API process per `DATA_DIR`. One AstraAi process owns the Docker sandbox namespace
(containers named `astraai-sandbox-*`) on a Docker daemon, and removes any it finds there
when it starts.

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

## Repair loop

After each execution the critic's reconciled `recommended_action` decides what happens next
(`app/repair.py`). The verdict alone never routes.

| Action | Next step | Budget |
| ------ | --------- | ------ |
| `accept` | `human_approval`, then completed, failed (rejected) or expired | approval timeout, extendable |
| `needs_human_review` | end, needs review | - |
| `revise_code` | `revise_code` rewrites **only** the solution, then re-executes | 2 revisions per run, shared with tests |
| `revise_tests` | `revise_tests` rewrites **only** the test code, then re-executes | same budget |
| `retry_execution` | re-runs the same code after an infrastructure error | 1 retry per run |

When a budget is spent the run ends safely instead of looping. Each execution gets exactly one
critic review, and the critic always judges the code that actually ran.

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
ASTRAAI_LIVE_GITHUB=1 uv run pytest tests/test_github_live.py  # real GitHub, public repo, no token
```

Opt-in check of the whole workflow against the real endpoint in `.env`:

```bash
ASTRAAI_LIVE_LLM=1 uv run pytest tests/test_llm_live.py        # PowerShell: $env:ASTRAAI_LIVE_LLM=1; uv run pytest tests/test_llm_live.py
```
