"""DEVELOP's evidence: which tests a change broke, by pytest id, and how a run ends.

The property that matters most: a test that passed before the change never fails after it
while AstraAi calls the change clean. Tests that were already failing don't count against
a change, and the AI review can hold a result back but never make it ready.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.checks import compare_tests, develop_outcome
from app.llm import LLMClient
from app.main import app
from app.nodes.edit_code import EDIT_TIMEOUT_SECONDS
from app.sandbox.docker import failed_tests
from app.state import ChangeSet, CriticResult, ExecutionResult, FileChange
from tests.fake_github import DEVELOP_REPLIES, REVIEW_PASS, FakeGitHub
from tests.fake_llm import ScriptedReplies
from tests.fake_runs import manager_factory, poll
from tests.fake_sandbox import INFRASTRUCTURE_ERROR, TESTS_PASSED, FakeSandbox
from tests.test_develop import BOTH_PASS, TIMED_OUT, replies, run_once

X, Y, Z = (
    "tests/test_a.py::test_x",
    "tests/test_a.py::test_y",
    "tests/test_b.py::test_z",
)


def result(
    passed: int, failing: list[str] | None, failed: int | None = None
) -> ExecutionResult:
    count = len(failing) if failing is not None else failed
    return ExecutionResult(
        status="failed" if count else "passed",
        exit_code=1 if count else 0,
        stdout=f"{count} failed, {passed} passed in 1.00s\n",
        tests_passed=passed,
        tests_failed=count,
        error_type="test_failure" if count else None,
        failed_tests=failing,
    )


def change(path: str, diff: str = "", status: str = "modified") -> ChangeSet:
    return ChangeSet(
        files=[
            FileChange(path=path, status=status, additions=1, deletions=0, diff=diff)
        ],
        explanation="x",
    )


ADDS_TEST = change("tests/test_b.py", "+def test_new():\n+    assert True\n")
REVIEW_BUG = CriticResult(
    verdict="code_failure",
    reason="r",
    code_issue="sub adds.",
    test_issue="",
    recommended_action="revise_code",
)


# pytest's own summary is the source of the ids.

SUMMARY = (
    "....F.E\n"
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_a.py::T::test_x - assert 1 == 2\n"
    "FAILED tests/test_a.py::test_p[a - b] - AssertionError\n"
    "ERROR tests/test_b.py::test_y - RuntimeError: boom\n"
    "2 failed, 5 passed, 1 error in 0.10s\n"
)


def test_failing_ids_come_from_pytests_summary() -> None:
    assert failed_tests(SUMMARY, 3) == [
        "tests/test_a.py::T::test_x",
        "tests/test_a.py::test_p[a - b]",
        "tests/test_b.py::test_y",
    ]


def test_failing_subtests_count_and_name_their_test_once() -> None:
    # pytest 9, as a real more-itertools run printed it: "5 failed" is 4 subtests and 1 test.
    stdout = (
        "=========================== short test summary info ============================\n"
        "SUBFAILED(iterable=[1, 4, 9, 16]) tests/test_recipes.py::T::test_basic\n"
        "SUBFAILED(iterable=[10, 5, 0, -5]) tests/test_recipes.py::T::test_basic\n"
        "SUBFAILED(iterable=[1, -2, 3, -4]) tests/test_recipes.py::T::test_basic\n"
        "SUBFAILED(iterable=[0.5, 1.5, 2.5]) tests/test_recipes.py::T::test_basic\n"
        "FAILED tests/test_recipes.py::T::test_iterator_input\n"
        "5 failed, 770 passed, 21202 subtests passed in 45.33s\n"
    )

    assert failed_tests(stdout, 5) == [
        "tests/test_recipes.py::T::test_basic",
        "tests/test_recipes.py::T::test_iterator_input",
    ]


@pytest.mark.parametrize(
    ("stdout", "expected", "ids"),
    [
        pytest.param(SUMMARY, 2, None, id="count-mismatch"),
        pytest.param(
            "FAILED tests/x.py::t\n1 failed in 1s\n", 1, None, id="summary-cut-off"
        ),
        pytest.param("5 passed in 1s\n", 0, [], id="all-passed"),
        pytest.param(
            "=== short test summary info ===\nERROR tests/test_new.py - ImportError\n"
            "!!! Interrupted: 1 error during collection !!!\n1 error in 0.2s\n",
            None,
            ["tests/test_new.py"],
            id="collection-error",
        ),
    ],
)
def test_a_summary_that_cant_be_read_whole_is_not_trusted(
    stdout: str, expected: int | None, ids: list[str] | None
) -> None:
    assert failed_tests(stdout, expected) == ids


# Comparing the runs.


def test_already_failing_tests_dont_count_against_a_change() -> None:
    checks = compare_tests(result(126, [X, Y]), result(128, [X, Y]), ADDS_TEST)

    assert (checks.by_id, checks.clean, checks.still_failing) == (True, True, [X, Y])
    assert (checks.broken, checks.added) == ([], 2)


def test_a_passing_test_that_now_fails_is_never_clean_even_at_the_same_count() -> None:
    # Two failures before and two after: by count this looked fine.
    checks = compare_tests(result(126, [X, Y]), result(126, [X, Z]), ADDS_TEST)

    assert (checks.clean, checks.broken, checks.fixed) == (False, [Z], [Y])


def test_a_failing_test_the_change_added_is_told_apart_from_a_broken_one() -> None:
    new = "tests/test_b.py::test_new"
    checks = compare_tests(result(10, []), result(10, [new, X]), ADDS_TEST)

    assert (checks.new_failing, checks.broken) == ([new], [X])
    created = change("tests/test_c.py", status="added")
    assert compare_tests(
        result(10, []), result(10, ["tests/test_c.py"]), created
    ).new_failing == ["tests/test_c.py"]


def test_without_ids_only_an_all_passing_run_is_clean() -> None:
    unknown = result(126, None, failed=2)

    # Two failures before and two after could be a broken test hiding behind a fixed one.
    assert compare_tests(
        unknown, result(126, None, failed=2), ADDS_TEST
    ).model_dump() == {
        "by_id": False,
        "clean": False,
        "broken": [],
        "new_failing": [],
        "still_failing": [],
        "fixed": [],
        "added": 0,
    }
    assert not compare_tests(TESTS_PASSED, result(1, None, failed=1), ADDS_TEST).clean
    assert compare_tests(unknown, result(130, []), ADDS_TEST).clean


def test_tests_that_couldnt_run_are_never_clean() -> None:
    for after in (TIMED_OUT, INFRASTRUCTURE_ERROR):
        assert not compare_tests(TESTS_PASSED, after, ADDS_TEST).clean


# How a run ends.


def test_the_outcome_follows_the_tests_first_and_the_review_second() -> None:
    clean = compare_tests(result(1, []), result(2, []), ADDS_TEST)
    broken = compare_tests(result(1, []), result(1, [X]), ADDS_TEST)
    passed = result(2, [])

    assert develop_outcome(ADDS_TEST, passed, clean, None) == "ready"
    assert develop_outcome(ADDS_TEST, result(1, [X]), broken, None) == "needs_review"
    # A review finding holds a passing change back; an approval can't rescue failing tests.
    assert develop_outcome(ADDS_TEST, passed, clean, REVIEW_BUG) == "needs_review"
    approval = CriticResult.model_validate(REVIEW_PASS)
    assert (
        develop_outcome(ADDS_TEST, result(1, [X]), broken, approval) == "needs_review"
    )
    assert develop_outcome(ADDS_TEST, TIMED_OUT, None, None) == "not_verified"
    assert (
        develop_outcome(ChangeSet(files=[], explanation="x"), None, None, None)
        == "no_changes"
    )


# Whole runs.


def test_a_change_to_a_repository_with_failing_tests_can_still_be_ready() -> None:
    sandbox = FakeSandbox(repository_result=[result(126, [X, Y]), result(128, [X, Y])])
    run, _, sandbox, llm = run_once(sandbox=sandbox)

    assert (run.status, run.outcome) == ("completed", "ready")
    assert (run.checks.still_failing, run.checks.added) == ([X, Y], 2)
    assert run.critic_result.verdict == "pass"
    assert "RepairChanges" not in llm.calls


def test_a_broken_test_at_the_same_failure_count_is_repaired_then_left_for_review() -> (
    None
):
    sandbox = FakeSandbox(repository_result=[result(126, [X, Y]), result(126, [X, Z])])
    run, _, _, llm = run_once(sandbox=sandbox)

    assert llm.calls.count("RepairChanges") == 1
    assert (run.status, run.outcome) == ("completed", "needs_review")
    assert run.checks.broken == [Z]
    # The review's approval was not trusted over the broken test.
    assert run.critic_result.recommended_action == "needs_human_review"


def test_nothing_to_change_ends_with_the_reason_and_runs_nothing_more() -> None:
    reason = "sub already exists in sample/__init__.py, with a test."
    llm = replies(CodeChanges={"edits": [], "explanation": reason})
    run, _, sandbox, llm = run_once(llm=llm)

    assert (run.status, run.outcome, run.error) == ("completed", "no_changes", None)
    assert (run.changes.files, run.changes.explanation) == ([], reason)
    assert (llm.calls, len(sandbox.repositories)) == (["ChangePlan", "CodeChanges"], 1)


def test_tests_that_couldnt_run_leave_the_change_unverified() -> None:
    run, _, _, llm = run_once(
        sandbox=FakeSandbox(repository_result=[TESTS_PASSED, TIMED_OUT])
    )

    assert (run.status, run.outcome) == ("completed", "not_verified")
    assert "RepairChanges" not in llm.calls


def test_an_unresolved_review_finding_needs_review_not_failure() -> None:
    finding = REVIEW_BUG.model_dump()
    run, _, _, llm = run_once(llm=replies(CriticResult=finding))

    assert llm.calls.count("RepairChanges") == 1
    assert (run.status, run.outcome, run.verification) == (
        "completed",
        "needs_review",
        BOTH_PASS,
    )


def test_edits_and_repairs_get_the_longer_model_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeouts: dict[str, float | None] = {}
    generate = LLMClient.generate

    async def recording(
        self: LLMClient, *args: Any, timeout: float | None = None
    ) -> Any:
        timeouts[args[2].__name__] = timeout
        return await generate(self, *args, timeout=timeout)

    monkeypatch.setattr(LLMClient, "generate", recording)
    run_once(llm=replies(CriticResult=REVIEW_BUG.model_dump()))

    assert timeouts == {
        "ChangePlan": None,
        "CodeChanges": EDIT_TIMEOUT_SECONDS,
        "CriticResult": None,
        "RepairChanges": EDIT_TIMEOUT_SECONDS,
    }
    assert EDIT_TIMEOUT_SECONDS == 240


def test_there_is_no_patch_when_nothing_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unchanged = {**DEVELOP_REPLIES, "CodeChanges": {"edits": [], "explanation": "x"}}
    monkeypatch.setattr(
        "app.main.build_run_manager",
        manager_factory(ScriptedReplies(unchanged), FakeSandbox, github=FakeGitHub),
    )
    with TestClient(app) as client:
        run_id = client.post(
            "/runs",
            json={
                "task": "t",
                "language": "python",
                "mode": "develop",
                "repository": "o/r",
            },
        ).json()["run_id"]
        poll(client, run_id, lambda r: r["status"] == "completed")
        response = client.get(f"/runs/{run_id}/patch")

    assert response.status_code == 409
