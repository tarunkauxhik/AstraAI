from typing import Any

from langgraph.runtime import Runtime

from app.nodes.revision import revision_count_before, revision_prompt
from app.state import AgentState, GraphContext, RevisedTests

INSTRUCTIONS = """You fix the test code written by an automated software engineer.

A reviewer examined the latest test run and concluded that a test, not the implementation,
is wrong. Fix the problem described in test_issue.

Rules:
- Change only the test code. The requirements, the test plan and the solution are fixed.
- The original requirements decide what is correct. Before changing an expected result,
  confirm from the requirements that the current expectation is wrong. Never change an
  expectation just to match what the current implementation returns.
- If the test plan repeats the same mistake, follow the requirements, not the plan.
- Keep every legitimate case and all coverage. Do not delete, skip or loosen tests to make
  them pass.
- Keep the runner contract: print FAIL <case_name>: expected <expected>, got <actual> for
  each failure, print PASSED <count> tests when all pass, and exit non-zero if any fails.
- Keep it deterministic and standard-library only: no network, files, environment,
  randomness or clocks.

Python: this is test_solution.py, run as `python test_solution.py`, importing the solution
with `from solution import ...`. Never use pytest.
C++: this is test_solution.cpp. It starts with #include "solution.cpp", defines main, and is
compiled with g++ -std=c++17.

Return the complete revised test_code, without markdown fences, and a short explanation of
what changed."""


async def revise_tests(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, Any]:
    """Replace only the test code, guided by the critic's test_issue."""
    revisions = revision_count_before(state, "revise_tests")
    revised = await runtime.context.llm.generate(
        INSTRUCTIONS, revision_prompt(state), RevisedTests
    )
    code = state["generated_code"]
    return {
        "generated_code": code.model_copy(
            update={"test_code": revised.test_code, "explanation": revised.explanation}
        ),
        "revision_count": revisions + 1,
    }
