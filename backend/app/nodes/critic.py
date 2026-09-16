from langgraph.runtime import Runtime

from app.llm import LLMOutputError
from app.state import AgentState, CriticResult, ExecutionResult, GraphContext

INSTRUCTIONS = """You review an automated software engineer's work. Decide whether the
implementation satisfies the original requirements, using the test run as evidence.

The requirements are the source of truth. Never change them silently, never invent
requirements they do not state, and never recommend weakening a test just so the code passes.

Compare how the code actually behaved with what the requirements and the test plan intend.
A failing test does not by itself prove the implementation is wrong: check whether that
test's expected result is consistent with the requirements before blaming the code.

Choose exactly one verdict:
- pass: the implementation satisfies the requirements, and the evidence supports it.
- code_failure: the implementation does not do what the requirements describe.
- test_failure: a test's expected result contradicts the requirements, while the
  implementation behaves as the requirements describe.
- execution_failure: there is no trustworthy test evidence, because of a compiler error,
  a crash before the cases could run, or a tooling problem.
- ambiguous: the evidence cannot show whether the implementation or the test is wrong.

recommended_action is accept for pass, and otherwise revise_code, revise_tests,
retry_execution or needs_human_review. Explain the implementation problem in code_issue and
the test problem in test_issue, or leave each as an empty string. Do not write replacement
code or tests."""


def human_review(reason: str) -> CriticResult:
    """A safe verdict for when neither the code nor the tests can be trusted as judged."""
    return CriticResult(
        verdict="ambiguous",
        reason=reason,
        code_issue="",
        test_issue="",
        recommended_action="needs_human_review",
    )


def execution_failure(reason: str, action: str) -> CriticResult:
    return CriticResult(
        verdict="execution_failure",
        reason=reason,
        code_issue="",
        test_issue="",
        recommended_action=action,
    )


# Sandbox outcomes that carry no evidence about the code's logic. They are decided here,
# never by the model. A time or resource limit does not prove the code is wrong (it may be
# slow, loop forever, or face an oversized test), so it goes to a human, never to a rewrite.
DETERMINISTIC_FAILURES: dict[str, CriticResult] = {
    "infrastructure_error": execution_failure(
        "The sandbox could not run the code, so there is no test evidence.",
        "retry_execution",
    ),
    "timed_out": execution_failure(
        "The tests did not finish within the sandbox time limit. That alone does not "
        "show whether the code or a test is at fault.",
        "needs_human_review",
    ),
    "resource_exceeded": execution_failure(
        "The tests exceeded the sandbox memory or process limits. That alone does not "
        "show whether the code or a test is at fault.",
        "needs_human_review",
    ),
}
INVALID_VERDICT = human_review(
    "The critic's answer was not a valid verdict, so the result needs a human review."
)
REQUIRED_STATE = (
    "requirements",
    "generated_tests",
    "generated_code",
    "execution_result",
)


def reconcile(result: CriticResult, execution: ExecutionResult) -> CriticResult:
    """Never let a model verdict contradict what the sandbox actually showed."""
    deterministic = DETERMINISTIC_FAILURES.get(execution.status)
    if deterministic is not None:
        return deterministic
    if result.verdict == "pass" and execution.status != "passed":
        return human_review(
            f"The critic judged the work a pass, but the tests {execution.status}, so "
            "that verdict cannot be trusted."
        )
    return result


async def critic(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, CriticResult]:
    """Judge the work against the requirements. Never runs, edits or routes anything."""
    missing = [key for key in REQUIRED_STATE if state.get(key) is None]
    if missing:
        raise ValueError(f"critic needs {', '.join(missing)} from earlier nodes")

    execution_result = state["execution_result"]
    deterministic = DETERMINISTIC_FAILURES.get(execution_result.status)
    if deterministic is not None:
        return {"critic_result": deterministic}

    code = state["generated_code"]
    prompt = (
        f"Language: {state['language']}\n\n"
        f"Task:\n{state['task']}\n\n"
        f"Requirements:\n{state['requirements'].model_dump_json(indent=2)}\n\n"
        f"Test plan:\n{state['generated_tests'].model_dump_json(indent=2)}\n\n"
        f"Solution code:\n{code.solution_code}\n\n"
        f"Test code:\n{code.test_code}\n\n"
        f"Execution result:\n{execution_result.model_dump_json(indent=2)}"
    )
    try:
        judged = await runtime.context.llm.generate(INSTRUCTIONS, prompt, CriticResult)
    except LLMOutputError:
        # An unusable answer is not trusted: route it to a human instead of failing the run.
        return {"critic_result": INVALID_VERDICT}
    return {"critic_result": reconcile(judged, execution_result)}
