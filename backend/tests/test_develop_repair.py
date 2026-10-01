"""DEVELOP's one repair: a change the tests or the review show is wrong gets exactly one
bounded correction, tested and reviewed again; the diff stays original to final.
"""

import asyncio
import re
from typing import Any

import pytest

from app.repair import route_develop
from app.runs import RunManager
from app.state import CriticResult, SuiteComparison
from tests.fake_github import (
    DEVELOP_REPLIES,
    PLAN,
    REPOSITORY,
    REVIEW_PASS,
    SAMPLE_FILES,
    FakeGitHub,
)
from tests.fake_sandbox import INFRASTRUCTURE_ERROR, TESTS_PASSED, FakeSandbox
from tests.test_develop import (
    BOTH_PASS,
    EXISTING_FAILURES,
    NEW_TEST_FAILS,
    TIMED_OUT,
    HeldSandbox,
    RecordingReplies,
    data_bytes,
    finished,
    manager,
    run_once,
)
from tests.test_runs import wait_until

# A first change with a bug its own test catches: sub adds.
BUGGY_EDITS = {
    "edits": [
        {
            "path": "sample/__init__.py",
            "old": "    return a + b\n",
            "new": "    return a + b\n\n\ndef sub(a, b):\n    return a + b\n",
        },
        {
            "path": "tests/test_add.py",
            "old": "    assert add(1, 2) == 3\n",
            "new": "    assert add(1, 2) == 3\n\n\ndef test_sub():\n"
            "    from sample import sub\n\n    assert sub(3, 1) == 2\n",
        },
    ],
    "explanation": "Adds sub next to add, with a test.",
}
# The repair, against the files as the first change left them.
FIX = {
    "edits": [
        {
            "path": "sample/__init__.py",
            "old": "def sub(a, b):\n    return a + b\n",
            "new": "def sub(a, b):\n    return a - b\n",
        }
    ],
    "summary": "Adds sub next to add, with a test.",
    "fix": "sub subtracted the wrong way round; it now returns a - b.",
}
REVIEW_BUG = {
    "verdict": "code_failure",
    "reason": "test_sub fails.",
    "code_issue": "sub returns a + b instead of a - b.",
    "test_issue": "",
    "recommended_action": "revise_code",
}
# Failures the repository already had, named by pytest as it does: not the change's doing.
OLD_FAILURES = EXISTING_FAILURES.model_copy(
    update={"failed_tests": ["tests/test_a.py::test_x", "tests/test_a.py::test_y"]}
)
REPAIR_CALLS = [
    "ChangePlan",
    "CodeChanges",
    "CriticResult",
    "RepairChanges",
    "CriticResult",
]


def buggy(**changes: Any) -> RecordingReplies:
    return RecordingReplies(
        {
            **DEVELOP_REPLIES,
            "CodeChanges": BUGGY_EDITS,
            "RepairChanges": FIX,
            "CriticResult": [REVIEW_BUG, REVIEW_PASS],
            **changes,
        }
    )


FENCE = re.compile(
    r"<<<REPOSITORY DATA (\w+)>>>\n(.*?)\n<<<END REPOSITORY DATA \1>>>", re.DOTALL
)


def fenced_data(prompt: str) -> str:
    return "".join(match.group(2) for match in FENCE.finditer(prompt))


def test_failing_tests_get_one_repair_that_fixes_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages: list[str] = []
    update = RunManager._update

    def recording(self: RunManager, run_id: str, **changes: Any) -> None:
        if "stage" in changes:
            stages.append(changes["stage"])
        update(self, run_id, **changes)

    monkeypatch.setattr(RunManager, "_update", recording)
    sandbox = FakeSandbox(repository_result=[TESTS_PASSED, NEW_TEST_FAILS, BOTH_PASS])
    run, _, sandbox, llm = run_once(sandbox=sandbox, llm=buggy())

    assert (run.status, run.error) == ("completed", None)
    assert stages[-5:] == [
        "reviewing_changes",
        "fixing_issue",
        "running_tests",
        "reviewing_changes",
        "completed",
    ]
    assert llm.calls == REPAIR_CALLS
    # The final evidence is the repaired change's; the first attempt's is kept aside.
    assert (run.verification, run.critic_result.verdict) == (BOTH_PASS, "pass")
    assert run.first_attempt.verification == NEW_TEST_FAILS
    assert run.first_attempt.review.code_issue == REVIEW_BUG["code_issue"]
    assert run.revision_count == 1
    # The repair was tested on the repaired repository.
    assert b"return a - b" in sandbox.repositories[2]["sample/__init__.py"]
    # The diff is original to final: the bug it once had appears nowhere in it.
    source = run.changes.files[0]
    assert (source.path, source.additions, source.deletions) == (
        "sample/__init__.py",
        4,
        0,
    )
    assert "+def sub(a, b):\n+    return a - b\n" in source.diff
    assert "+    return a + b" not in source.diff
    # The summary describes the final change; what the repair corrected is kept apart.
    assert run.changes.explanation == FIX["summary"]
    assert run.first_attempt.explanation == BUGGY_EDITS["explanation"]
    assert run.first_attempt.fix == FIX["fix"]
    assert run.outcome == "ready"


def test_the_repair_sees_what_went_wrong_but_not_the_whole_repository() -> None:
    files = {**SAMPLE_FILES, "docs/unrelated.md": b"UNRELATED_CONTENT\n"}
    sandbox = FakeSandbox(repository_result=[TESTS_PASSED, NEW_TEST_FAILS, BOTH_PASS])
    _, _, _, llm = run_once(
        github=FakeGitHub(files=files), sandbox=sandbox, llm=buggy()
    )

    repair = llm.prompts[3]
    assert "Add a sub function." in repair  # The task.
    data = fenced_data(repair)
    # The files as the first change left them, its diff, the failing test and the review.
    assert "def sub(a, b):\n    return a + b" in data
    assert "+def sub(a, b):" in data
    assert "assert 4 == 2" in data
    assert REVIEW_BUG["code_issue"] in data
    # Only evidence and the changed files: not the rest of the repository, and nothing
    # repository-made outside the fence.
    assert "UNRELATED_CONTENT" not in repair and "README" not in repair
    assert "assert 4 == 2" not in FENCE.sub("", repair)
    assert "This is a repair" in llm.systems[3]
    assert "assert 4 == 2" not in llm.systems[3]


def test_a_repair_that_still_fails_ends_honestly_after_exactly_one_try() -> None:
    # The review approves both times: an approval never outvotes failing tests.
    sandbox = FakeSandbox(repository_result=[TESTS_PASSED, NEW_TEST_FAILS])
    llm = buggy(CriticResult=REVIEW_PASS)
    run, _, sandbox, llm = run_once(sandbox=sandbox, llm=llm)

    assert (run.status, run.error) == ("completed", None)
    assert llm.calls == REPAIR_CALLS  # One repair, never a second.
    assert len(sandbox.repositories) == 3
    assert (run.verification.status, run.verification.tests_failed) == ("failed", 1)
    assert run.critic_result.recommended_action == "needs_human_review"
    assert run.first_attempt.review.recommended_action == "needs_human_review"
    assert run.revision_count == 1


def test_a_review_finding_repairs_a_change_whose_tests_pass() -> None:
    sandbox = FakeSandbox(repository_result=[TESTS_PASSED, BOTH_PASS])
    run, _, _, llm = run_once(sandbox=sandbox, llm=buggy())

    assert llm.calls == REPAIR_CALLS
    assert run.first_attempt.verification == BOTH_PASS
    assert (run.status, run.critic_result.verdict) == ("completed", "pass")


@pytest.mark.parametrize(
    ("after", "existing"),
    [
        pytest.param(TIMED_OUT, TESTS_PASSED, id="timeout"),
        pytest.param(INFRASTRUCTURE_ERROR, TESTS_PASSED, id="sandbox"),
        pytest.param(OLD_FAILURES, OLD_FAILURES, id="same-old-failures"),
    ],
)
def test_no_repair_without_evidence_the_change_is_wrong(
    after: Any, existing: Any
) -> None:
    run, _, sandbox, llm = run_once(
        sandbox=FakeSandbox(repository_result=[existing, after]),
        llm=RecordingReplies(),
    )

    assert run.status == "completed"
    assert "CodeChanges" not in llm.calls[2:]
    assert (run.first_attempt, run.revision_count, len(sandbox.repositories)) == (
        None,
        0,
        2,
    )


@pytest.mark.parametrize(
    "fix",
    [
        pytest.param(
            {"edits": [{"path": ".github/workflows/ci.yml", "old": "", "new": "x"}]},
            id="protected",
        ),
        pytest.param(
            {"edits": [{"path": "README.md", "old": "# sample\n", "new": "# x\n"}]},
            id="not-shown",
        ),
        pytest.param(
            {"edits": [{"path": "sample/__init__.py", "old": "a * b", "new": "x"}]},
            id="not-found",
        ),
        pytest.param({"edits": []}, id="nothing"),
        pytest.param(
            {
                "edits": [
                    {
                        "path": "sample/__init__.py",
                        "old": "\n\ndef sub(a, b):\n    return a + b\n",
                        "new": "",
                    },
                    {
                        "path": "tests/test_add.py",
                        "old": BUGGY_EDITS["edits"][1]["new"],
                        "new": BUGGY_EDITS["edits"][1]["old"],
                    },
                ]
            },
            id="reverts-everything",
        ),
        pytest.param("not json", id="unusable-answer"),
    ],
)
def test_a_repair_that_cant_be_made_leaves_the_first_change_and_its_evidence(
    fix: Any,
) -> None:
    reply = fix if isinstance(fix, str) else {**fix, "summary": "x", "fix": "x"}
    sandbox = FakeSandbox(repository_result=[TESTS_PASSED, NEW_TEST_FAILS, BOTH_PASS])
    run, _, sandbox, _ = run_once(sandbox=sandbox, llm=buggy(RepairChanges=reply))

    assert (run.status, run.error) == ("completed", None)
    assert len(sandbox.repositories) == 2  # Nothing new to test.
    assert run.verification == NEW_TEST_FAILS
    assert "+    return a + b" in run.changes.files[0].diff
    assert run.changes.explanation == BUGGY_EDITS["explanation"]
    assert (run.first_attempt, run.revision_count) == (None, 1)


def test_the_router_repairs_at_most_once() -> None:
    bug = CriticResult.model_validate(REVIEW_BUG)
    broken = SuiteComparison(by_id=True, clean=False, broken=["t.py::test_x"])
    clean = SuiteComparison(by_id=True, clean=True)
    assert route_develop(NEW_TEST_FAILS, broken, bug, 0) == "repair_changes"
    assert route_develop(NEW_TEST_FAILS, broken, bug, 1) == "finish"
    assert route_develop(BOTH_PASS, clean, bug, 1) == "finish"
    # A review that can't tell, with passing tests, is left to the person.
    unsure = bug.model_copy(update={"recommended_action": "needs_human_review"})
    assert route_develop(BOTH_PASS, clean, unsure, 0) == "finish"
    # Tests that couldn't run are no evidence either way.
    assert route_develop(TIMED_OUT, None, bug, 0) == "finish"


def test_a_restart_during_the_repair_fails_it_once_and_keeps_no_files() -> None:
    marker = b"UNTOUCHED_FILE_CONTENT_" * 3
    files = {**SAMPLE_FILES, "big.py": marker}

    async def scenario() -> None:
        # Held while the repaired repository is tested: the repair has checkpointed.
        sandbox = HeldSandbox(
            hold=3, repository_result=[TESTS_PASSED, NEW_TEST_FAILS, BOTH_PASS]
        )
        crashed = manager(FakeGitHub(files=files), sandbox, buggy())
        await crashed.start()
        run_id = crashed.submit("task", "python", "develop", REPOSITORY).run_id
        await asyncio.wait_for(sandbox.started.wait(), 5)
        await wait_until(lambda: b"return a - b" in data_bytes())
        assert marker not in data_bytes()

        github, fresh, llm = FakeGitHub(), FakeSandbox(), RecordingReplies()
        restarted = manager(github, fresh, llm)
        await restarted.start()
        try:
            run = restarted.get(run_id)
            assert (run.status, run.error.code, run.error.stage) == (
                "failed",
                "shutdown",
                "running_tests",
            )
            # The repaired diff is kept, with no claim about tests it never finished.
            assert "+    return a - b" in run.changes.files[0].diff
            assert run.verification is None
            assert run.first_attempt.verification == NEW_TEST_FAILS
            await asyncio.sleep(0.05)
            assert (github.resolved, fresh.repositories, llm.calls) == ([], [], [])
            assert restarted._context.snapshots == restarted._context.originals == {}
        finally:
            await restarted.stop()
            await crashed.stop()
        assert marker not in data_bytes()

    asyncio.run(scenario())


def test_a_repaired_run_survives_a_restart() -> None:
    async def scenario() -> None:
        sandbox = FakeSandbox(
            repository_result=[TESTS_PASSED, NEW_TEST_FAILS, BOTH_PASS]
        )
        runs = manager(FakeGitHub(), sandbox, buggy())
        await runs.start()
        try:
            run_id = runs.submit("task", "python", "develop", REPOSITORY).run_id
            await wait_until(lambda: finished(runs, run_id))
            completed = runs.get(run_id)
        finally:
            await runs.stop()

        restarted = manager(FakeGitHub(), FakeSandbox(), RecordingReplies())
        await restarted.start()
        try:
            assert restarted.get(run_id) == completed
            assert completed.first_attempt is not None
        finally:
            await restarted.stop()

    asyncio.run(scenario())


def test_the_plan_files_are_offered_to_the_repair_too() -> None:
    # A file the plan read but the first change didn't touch may be where the fix goes.
    fix = {
        "edits": [
            {
                "path": "tests/test_add.py",
                "old": "    assert sub(3, 1) == 2\n",
                "new": "    assert sub(3, 1) == 4\n",
            }
        ],
        "summary": "x",
        "fix": "x",
    }
    llm = buggy(
        ChangePlan={**PLAN, "files": [*PLAN["files"], "README.md"]},
        RepairChanges=fix,
    )
    sandbox = FakeSandbox(repository_result=[TESTS_PASSED, NEW_TEST_FAILS, BOTH_PASS])
    _, _, _, llm = run_once(sandbox=sandbox, llm=llm)

    assert "--- FILE README.md ---" in llm.prompts[3]
