import asyncio
from pathlib import Path
from typing import Any

import pytest
from langgraph.runtime import Runtime

from app.nodes.execute_sandbox import execute_sandbox
from app.state import ExecutionResult, GeneratedCode, GraphContext
from tests.fake_llm import VALID_CPP_CODE, VALID_PYTHON_CODE
from tests.fake_sandbox import PASSED, FakeSandbox

PYTHON_CODE = GeneratedCode.model_validate(VALID_PYTHON_CODE)
STATE = {
    "run_id": "run-1",
    "task": "Reverse a string.",
    "language": "python",
    "generated_code": PYTHON_CODE,
}


def run_node(sandbox: FakeSandbox, state: dict[str, Any] = STATE) -> dict[str, Any]:
    runtime = Runtime(context=GraphContext(llm=None, sandbox=sandbox))
    return asyncio.run(execute_sandbox(state, runtime))


def test_execute_sandbox_stores_the_execution_result() -> None:
    sandbox = FakeSandbox()

    update = run_node(sandbox)

    assert update == {"execution_result": PASSED}
    assert sandbox.calls == [PYTHON_CODE]


def test_execute_sandbox_runs_cpp_code() -> None:
    code = GeneratedCode.model_validate(VALID_CPP_CODE)
    sandbox = FakeSandbox()

    run_node(sandbox, {**STATE, "language": "cpp", "generated_code": code})

    assert sandbox.calls == [code]


def test_execute_sandbox_needs_generated_code() -> None:
    sandbox = FakeSandbox()
    state = {key: value for key, value in STATE.items() if key != "generated_code"}

    with pytest.raises(ValueError, match="needs generated_code"):
        run_node(sandbox, state)

    assert sandbox.calls == []


def test_execute_sandbox_rejects_a_language_mismatch() -> None:
    sandbox = FakeSandbox()

    with pytest.raises(ValueError, match="generated code is python"):
        run_node(sandbox, {**STATE, "language": "cpp"})

    assert sandbox.calls == []


def test_execute_sandbox_propagates_executor_failures() -> None:
    sandbox = FakeSandbox(RuntimeError("sandbox exploded"))

    with pytest.raises(RuntimeError, match="sandbox exploded"):
        run_node(sandbox)


def test_execute_sandbox_stores_failures_as_results() -> None:
    failure = ExecutionResult(
        status="failed",
        exit_code=1,
        stdout="FAIL basic_word: expected cba, got abc\n",
        duration_ms=40,
        tests_failed=1,
        error_type="test_failure",
    )

    update = run_node(FakeSandbox(failure))

    assert update["execution_result"].status == "failed"
    assert update["execution_result"].error_type == "test_failure"


def test_execute_sandbox_node_holds_no_docker_details() -> None:
    source = Path("app/nodes/execute_sandbox.py").read_text(encoding="utf-8")

    for implementation_detail in (
        "app.sandbox.docker",
        "DockerSandbox",
        "subprocess",
        "container",
        "--network",
        "tmpfs",
    ):
        assert implementation_detail not in source
