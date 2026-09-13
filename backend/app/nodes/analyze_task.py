from langgraph.runtime import Runtime

from app.state import AgentState, GraphContext, Requirements

INSTRUCTIONS = """You analyze coding tasks for an automated software engineer.
Describe what a correct solution must do. Do not write code or tests.
Be specific and concise. Use an empty list when a field does not apply."""


async def analyze_task(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, Requirements]:
    prompt = f"Language: {state['language']}\n\nTask:\n{state['task']}"
    requirements = await runtime.context.llm.generate(
        INSTRUCTIONS, prompt, Requirements
    )
    return {"requirements": requirements}
