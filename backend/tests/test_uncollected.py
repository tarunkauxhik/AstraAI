"""Tests a change adds that never run never count as checks.

The pilot case: four test methods added to six's `class EnsureTests:`, which pytest's
default rules never collect (no `Test` prefix, not a TestCase). The tests "passed" because
none of them ran, and the result read as ready. The diff says how many test functions the
change adds; pytest's own counts say how many more tests ran. Fewer ran: needs review.
"""

from app.changes import describe_changes
from app.checks import compare_tests, declared_tests, develop_outcome, new_tests_ran
from app.state import ChangeSet, ExecutionResult, SuiteComparison
from tests.fake_github import DEVELOP_REPLIES, FakeGitHub
from tests.fake_sandbox import FakeSandbox
from tests.test_develop import RecordingReplies, run_once

# A small repository shaped like six: a module and a test file whose `EnsureTests` class
# pytest never collects, beside one test function it does.
SIX_LIKE = {
    "sixlike.py": b"def ensure_text(s):\n"
    b"    if isinstance(s, bytes):\n"
    b"        return s.decode()\n"
    b"    if isinstance(s, str):\n"
    b"        return s\n"
    b"    raise TypeError(type(s))\n",
    "test_sixlike.py": b"import pytest\n\nimport sixlike\n\n\n"
    b"def test_module():\n    assert sixlike\n\n\n"
    b"class EnsureTests:\n"
    b"    def test_ensure_text(self):\n"
    b"        assert sixlike.ensure_text(b'a') == 'a'\n",
}
# What AstraAi added in the pilot: methods inside the class pytest skips.
INTO_ENSURE_TESTS = (
    "        assert sixlike.ensure_text(b'a') == 'a'\n"
    "\n"
    "    def test_ensure_text_raise_type_error_int(self):\n"
    "        with pytest.raises(TypeError):\n"
    "            sixlike.ensure_text(1)\n"
    "\n"
    "    def test_ensure_text_raise_type_error_none(self):\n"
    "        with pytest.raises(TypeError):\n"
    "            sixlike.ensure_text(None)\n"
)
# The same tests where pytest does collect them.
AS_FUNCTIONS = (
    "\n\ndef test_ensure_text_raise_type_error_int():\n"
    "    with pytest.raises(TypeError):\n"
    "        sixlike.ensure_text(1)\n"
    "\n\ndef test_ensure_text_raise_type_error_none():\n"
    "    with pytest.raises(TypeError):\n"
    "        sixlike.ensure_text(None)\n"
)


def changed(**files: str) -> ChangeSet:
    edited = {**SIX_LIKE, **{path: text.encode() for path, text in files.items()}}
    return describe_changes(SIX_LIKE, edited, "x")


def pytest_run(passed: int) -> ExecutionResult:
    return ExecutionResult(
        status="passed",
        exit_code=0,
        stdout=f"{passed} passed in 0.01s\n",
        tests_passed=passed,
        tests_failed=0,
        failed_tests=[],
    )


ENSURE_CHANGE = changed(
    **{
        "test_sixlike.py": SIX_LIKE["test_sixlike.py"]
        .decode()
        .replace("        assert sixlike.ensure_text(b'a') == 'a'\n", INTO_ENSURE_TESTS)
    }
)
COLLECTED_CHANGE = changed(
    **{"test_sixlike.py": SIX_LIKE["test_sixlike.py"].decode() + AS_FUNCTIONS}
)
CODE_ONLY_CHANGE = changed(
    **{
        "sixlike.py": SIX_LIKE["sixlike.py"]
        .decode()
        .replace("TypeError(type(s))", "TypeError(f'not text: {type(s)}')")
    }
)


# What the diff declares.


def test_the_diff_says_how_many_test_functions_the_change_adds() -> None:
    assert declared_tests(ENSURE_CHANGE) == 2
    assert declared_tests(COLLECTED_CHANGE) == 2
    assert declared_tests(CODE_ONLY_CHANGE) == 0


def test_renamed_and_moved_tests_are_nothing_new() -> None:
    renamed = changed(
        **{
            "test_sixlike.py": SIX_LIKE["test_sixlike.py"]
            .decode()
            .replace("test_module", "test_mod")
        }
    )
    moved = changed(
        **{
            "test_sixlike.py": SIX_LIKE["test_sixlike.py"]
            .decode()
            .replace("def test_module():\n    assert sixlike\n\n\n", ""),
            "tests/test_moved.py": "import sixlike\n\n\ndef test_module():\n    assert sixlike\n",
        }
    )

    assert declared_tests(renamed) == 0
    assert declared_tests(moved) == 0


def test_test_named_functions_outside_test_files_dont_count() -> None:
    helper = changed(
        **{
            "sixlike.py": SIX_LIKE["sixlike.py"].decode()
            + "\n\ndef test_helper():\n    return 1\n"
        }
    )

    assert declared_tests(helper) == 0


# Whether they ran.


def test_new_tests_pytest_never_collected_are_not_confirmed() -> None:
    # The pilot: the count didn't move although the diff adds tests.
    checks = compare_tests(pytest_run(1), pytest_run(1), ENSURE_CHANGE)

    assert (checks.clean, checks.added, checks.declared) == (True, 0, 2)
    assert not new_tests_ran(checks)
    assert develop_outcome(ENSURE_CHANGE, pytest_run(1), checks, None) == "needs_review"


def test_new_tests_that_ran_confirm_the_change() -> None:
    checks = compare_tests(pytest_run(1), pytest_run(3), COLLECTED_CHANGE)

    assert (checks.added, checks.declared) == (2, 2)
    assert develop_outcome(COLLECTED_CHANGE, pytest_run(3), checks, None) == "ready"


def test_a_change_that_adds_no_tests_is_not_held_back_for_it() -> None:
    checks = compare_tests(pytest_run(1), pytest_run(1), CODE_ONLY_CHANGE)

    assert new_tests_ran(checks)
    assert develop_outcome(CODE_ONLY_CHANGE, pytest_run(1), checks, None) == "ready"


def test_unknown_counts_never_confirm_new_tests() -> None:
    unknown = SuiteComparison(by_id=False, clean=True, added=None, declared=2)

    assert not new_tests_ran(unknown)
    assert new_tests_ran(unknown.model_copy(update={"declared": 0}))


def test_only_some_new_tests_running_is_not_enough() -> None:
    partly = SuiteComparison(by_id=True, clean=True, added=1, declared=2)

    assert not new_tests_ran(partly)


# Whole runs: the outcome, and nothing else changes.


def develop(test_file: str, after_passed: int) -> tuple:
    edit = {
        "path": "test_sixlike.py",
        "old": SIX_LIKE["test_sixlike.py"].decode().split("import sixlike\n", 1)[1],
        "new": test_file.split("import sixlike\n", 1)[1],
    }
    llm = RecordingReplies(
        {
            **DEVELOP_REPLIES,
            "ChangePlan": {
                "summary": "Add ensure_text tests.",
                "files": ["test_sixlike.py"],
            },
            "CodeChanges": {"edits": [edit], "explanation": "Adds ensure_text tests."},
        }
    )
    sandbox = FakeSandbox(repository_result=[pytest_run(1), pytest_run(after_passed)])
    return run_once(github=FakeGitHub(files=SIX_LIKE), sandbox=sandbox, llm=llm)


ENSURE_FILE = (
    SIX_LIKE["test_sixlike.py"]
    .decode()
    .replace("        assert sixlike.ensure_text(b'a') == 'a'\n", INTO_ENSURE_TESTS)
)
COLLECTED_FILE = SIX_LIKE["test_sixlike.py"].decode() + AS_FUNCTIONS


def test_a_run_whose_new_tests_never_ran_needs_review_and_says_so() -> None:
    run, _, _, llm = develop(ENSURE_FILE, after_passed=1)

    assert (run.status, run.outcome) == ("completed", "needs_review")
    assert (run.checks.added, run.checks.declared) == (0, 2)
    # Not a test failure, not a repair: the repair limit and routing are unchanged.
    assert (run.checks.clean, run.revision_count, run.first_attempt) == (True, 0, None)
    assert "RepairChanges" not in llm.calls


def test_a_run_whose_new_tests_ran_is_ready() -> None:
    run, _, _, _ = develop(COLLECTED_FILE, after_passed=3)

    assert (run.outcome, run.checks.added, run.checks.declared) == ("ready", 2, 2)
