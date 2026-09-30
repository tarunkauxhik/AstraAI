from langgraph.runtime import Runtime

from app.repository import read_archive
from app.state import AgentState, GraphContext, RepositoryRef


async def prepare_repository(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, RepositoryRef]:
    """Pin the repository's default branch to its current commit and read it into memory.

    Only the pinned reference enters the state; the files stay in the run's snapshot.
    """
    github = runtime.context.github
    if github is None:
        raise ValueError("prepare_repository needs a GitHub provider")
    repository_ref = await github.resolve(state["repository"])
    archive = await github.download(repository_ref)
    runtime.context.snapshots[state["run_id"]] = read_archive(archive)
    return {"repository_ref": repository_ref}
