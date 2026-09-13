from langgraph.runtime import Runtime

from app.state import AgentState, GeneratedTests, GraphContext

INSTRUCTIONS = """You design tests for an automated software engineer.
Write a language-neutral test plan from the task and its requirements.
Do not write the solution. Do not write test code in any programming language.

Choose only the categories that apply to this task:
- basic: a normal, typical case
- boundary: limits from the constraints and edge cases
- empty_or_small: empty or minimal input
- duplicates: repeated values
- negative_or_zero: negative numbers or zero
- performance: input near the stated size limits
- invalid_input: only when the requirements define the expected behavior

Write at most 8 cases; prefer a few meaningful cases over many similar ones.
Every expected output must be exactly correct for its input.
For a performance case, build the input with input_generator and choose one whose exact
expected output is short, such as a count or a pair of indices; otherwise skip it."""


async def generate_tests(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, GeneratedTests]:
    requirements = state.get("requirements")
    if requirements is None:
        raise ValueError("generate_tests needs requirements from analyze_task")
    prompt = (
        f"Language: {state['language']}\n\n"
        f"Task:\n{state['task']}\n\n"
        f"Requirements:\n{requirements.model_dump_json(indent=2)}"
    )
    generated_tests = await runtime.context.llm.generate(
        INSTRUCTIONS, prompt, GeneratedTests
    )
    return {"generated_tests": generated_tests}
