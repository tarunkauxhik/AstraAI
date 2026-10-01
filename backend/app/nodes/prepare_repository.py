from langgraph.runtime import Runtime

from app.preflight import check_supported
from app.repository import read_archive
from app.state import AgentState, GraphContext, RepositoryRef


async def prepare_repository(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, RepositoryRef]:
    """Pin the repository's default branch to its current commit, read it into memory, and
    check that it is one AstraAi supports before anything runs.

    Only the pinned reference enters the state; the files stay in the run's snapshot. A
    repository that doesn't fit stops the run here: no sandbox run, no model call.
    """
    github = runtime.context.github
    if github is None:
        raise ValueError("prepare_repository needs a GitHub provider")
    repository_ref = await github.resolve(state["repository"])
    archive = await github.download(repository_ref)
    snapshot = read_archive(archive)
    check_supported(snapshot)
    runtime.context.snapshots[state["run_id"]] = snapshot
    return {"repository_ref": repository_ref}
