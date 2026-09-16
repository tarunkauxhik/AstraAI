from typing import Any

from langgraph.runtime import Runtime

from app.nodes.revision import revision_count_before, revision_prompt
from app.state import AgentState, GraphContext, RevisedSolution

INSTRUCTIONS = """You fix the solution code written by an automated software engineer.

A reviewer examined the latest test run and concluded that the implementation is wrong.
Fix the problem described in code_issue so the solution satisfies the original requirements.

Rules:
- Change only the solution. The requirements, the test plan and the test code are fixed,
  and the solution must pass the tests as they are written.
- Implement what the requirements describe. Do not invent requirements or drop any.
- Never special-case test inputs or otherwise game the tests.
- Keep the same interface, and change only what the diagnosis requires.
- Keep it deterministic and standard-library only: no network, files, environment,
  randomness or clocks.

Python: this is solution.py, imported by the tests with `from solution import ...`, and no
code may run on import.
C++: this is solution.cpp, #included by test_solution.cpp and compiled with
g++ -std=c++17. It must not define main().

Return the complete revised solution_code, without markdown fences, and a short explanation
of what changed."""


async def revise_code(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, Any]:
    """Replace only the solution code, guided by the critic's code_issue."""
    revisions = revision_count_before(state, "revise_code")
    revised = await runtime.context.llm.generate(
        INSTRUCTIONS, revision_prompt(state), RevisedSolution
    )
    code = state["generated_code"]
    return {
        "generated_code": code.model_copy(
            update={
                "solution_code": revised.solution_code,
                "explanation": revised.explanation,
            }
        ),
        "revision_count": revisions + 1,
    }
