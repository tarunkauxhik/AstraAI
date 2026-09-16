from langgraph.runtime import Runtime

from app.state import AgentState, GeneratedCode, GraphContext

INSTRUCTIONS = """You write complete, runnable code for an automated software engineer.

Implement exactly what the requirements describe. Do not invent requirements, and never
weaken, skip or rewrite a test case to make the solution pass. When a case contradicts the
requirements, follow the requirements and say so in explanation.

solution_code holds the implementation only, with the interface the test plan states, and no
entry point that runs on import or start-up.
test_code holds a standalone program that runs every case in the plan, prints one line per
failure as FAIL <case_name>: expected <expected>, got <actual>, prints PASSED <count> tests
when they all pass, and exits non-zero if any case fails.

Python: the files are solution.py and test_solution.py, run as `python test_solution.py`.
Import the solution with `from solution import ...`. Use the standard library only, plain
comparisons, and sys.exit(1) on failure; never pytest.
C++: the files are solution.cpp and test_solution.cpp, compiled with
`g++ -std=c++17 test_solution.cpp -o tests`. Start test_solution.cpp with
#include "solution.cpp". solution.cpp must not define main(); test_solution.cpp defines main
and returns 1 on failure. Use the C++ standard library only.

Both files must be deterministic: no network, no file or environment access, no randomness, no
clocks, no third-party packages. Write code only, without markdown fences or commentary inside
solution_code and test_code; put any reasoning in explanation."""


async def generate_code(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, GeneratedCode]:
    requirements = state.get("requirements")
    if requirements is None:
        raise ValueError("generate_code needs requirements from analyze_task")
    generated_tests = state.get("generated_tests")
    if generated_tests is None:
        raise ValueError("generate_code needs generated_tests from generate_tests")
    prompt = (
        f"Language: {state['language']}\n\n"
        f"Task:\n{state['task']}\n\n"
        f"Requirements:\n{requirements.model_dump_json(indent=2)}\n\n"
        f"Test plan:\n{generated_tests.model_dump_json(indent=2)}"
    )
    generated_code = await runtime.context.llm.generate(
        INSTRUCTIONS, prompt, GeneratedCode
    )
    return {"generated_code": generated_code}
