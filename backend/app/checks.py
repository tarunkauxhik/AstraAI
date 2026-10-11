"""DEVELOP's evidence: the repository's tests after a change, compared with before it, and
what that means for the run.

Tests are the hard evidence and the AI review only ever holds a result back: failing
tests can never be outvoted, and a review can't make a change ready that the tests don't
support. Pure functions, so the graph and the run manager decide with the same rules.
"""

import re
from typing import Literal

from app.changes import review_order
from app.state import ChangeSet, CriticResult, ExecutionResult, SuiteComparison

# A test function the diff adds: "+def test_x(" or "+    async def test_x(".
ADDED_TEST = re.compile(r"^\+\s*(?:async\s+)?def (test\w*)\(", re.MULTILINE)
REMOVED_TEST = re.compile(r"^-\s*(?:async\s+)?def (test\w*)\(", re.MULTILINE)

Outcome = Literal["ready", "needs_review", "not_verified", "no_changes"]
# Review verdicts that name a concrete problem with the change.
FINDINGS = frozenset({"code_failure", "test_failure"})


def ran(result: ExecutionResult | None) -> bool:
    """Whether pytest ran at all: passed or failed, not stopped by a time or memory limit
    or an unavailable sandbox."""
    return result is not None and result.status in ("passed", "failed")


def failing(result: ExecutionResult) -> set[str] | None:
    if result.status == "passed":
        return set()
    return set(result.failed_tests) if result.failed_tests is not None else None


def added_by(changes: ChangeSet, test_id: str) -> bool:
    """Whether a failing test is one the change added: in a file it created, or a test
    function its diff adds to that file."""
    path, _, rest = test_id.partition("::")
    name = re.sub(r"\[.*$", "", rest.rsplit("::", 1)[-1])
    for change in changes.files:
        if change.path == path:
            return change.status == "added" or name in ADDED_TEST.findall(change.diff)
    return False


def declared_tests(changes: ChangeSet) -> int:
    """How many test functions the diff adds to test files, net of the ones it removes, so
    a renamed or moved test counts as nothing new."""
    added: set[tuple[str, str]] = set()
    removed: set[tuple[str, str]] = set()
    for change in changes.files:
        if review_order(change.path)[0] != 1:  # Not a test file.
            continue
        added |= {(change.path, name) for name in ADDED_TEST.findall(change.diff)}
        removed |= {(change.path, name) for name in REMOVED_TEST.findall(change.diff)}
    return max(len(added - removed) - len(removed - added), 0)


def new_tests_ran(checks: SuiteComparison) -> bool:
    """Whether the test functions the diff adds all ran: at least that many more tests than
    before. Unknown counts never confirm it."""
    return checks.declared == 0 or (
        checks.added is not None and checks.added >= checks.declared
    )


def compare_tests(
    before: ExecutionResult, after: ExecutionResult, changes: ChangeSet
) -> SuiteComparison:
    """The tests after the change against before it: by test id when pytest named every
    failure both times, otherwise by count."""
    added = None
    if before.tests_passed is not None and after.tests_passed is not None:
        before_total = before.tests_passed + (before.tests_failed or 0)
        after_total = after.tests_passed + (after.tests_failed or 0)
        added = max(after_total - before_total, 0)
    old, new = failing(before), failing(after)
    if old is not None and new is not None and ran(after):
        newly = sorted(new - old)
        return SuiteComparison(
            by_id=True,
            clean=not newly,
            broken=[test for test in newly if not added_by(changes, test)],
            new_failing=[test for test in newly if added_by(changes, test)],
            still_failing=sorted(new & old),
            fixed=sorted(old - new),
            added=added,
            declared=declared_tests(changes),
        )
    # Without ids nothing shows which tests fail now: equal counts could hide a test that
    # broke behind one that was fixed. So only a run where every test passed is clean.
    return SuiteComparison(
        by_id=False,
        clean=after.status == "passed",
        added=added,
        declared=declared_tests(changes),
    )


def develop_outcome(
    changes: ChangeSet,
    after: ExecutionResult | None,
    checks: SuiteComparison | None,
    review: CriticResult | None,
) -> Outcome:
    """How a DEVELOP run that made (or declined to make) a change ended.

    Ready only when the tests ran, nothing fails that didn't before, every test the change
    added actually ran, and the final review raised nothing. Tests that couldn't run say
    nothing either way.
    """
    if not changes.files:
        return "no_changes"
    if not ran(after):
        return "not_verified"
    if checks is None or not checks.clean or not new_tests_ran(checks):
        return "needs_review"
    if review is not None and review.verdict in FINDINGS:
        return "needs_review"
    return "ready"
