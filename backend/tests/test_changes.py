"""Edits are exact, inside the snapshot, all or nothing; the diff follows from them alone."""

import pytest

from app.changes import EditError, apply_edits, describe_changes
from app.state import FileEdit

SNAPSHOT = {
    "pkg/core.py": b"def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n",
    "tests/test_core.py": b"from pkg.core import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    "README.md": b"# pkg\n",
    "windows.py": b"x = 1\r\ny = 2\r\n",
}
EDITABLE = {"pkg/core.py", "tests/test_core.py", "windows.py"}


def edit(path: str, old: str, new: str) -> FileEdit:
    return FileEdit(path=path, old=old, new=new)


def test_an_exact_edit_is_applied_and_nothing_else_changes() -> None:
    changed = apply_edits(
        SNAPSHOT,
        [edit("pkg/core.py", "    return a * b\n", "    return b * a\n")],
        EDITABLE,
    )

    assert changed["pkg/core.py"].endswith(b"    return b * a\n")
    assert {path: data for path, data in changed.items() if path != "pkg/core.py"} == {
        path: data for path, data in SNAPSHOT.items() if path != "pkg/core.py"
    }
    # The snapshot itself is never modified.
    assert SNAPSHOT["pkg/core.py"].endswith(b"    return a * b\n")


def test_several_edits_to_one_file_apply_against_the_original() -> None:
    changed = apply_edits(
        SNAPSHOT,
        [
            edit("pkg/core.py", "def mul(a, b):", "def multiply(a, b):"),
            edit("pkg/core.py", "def add(a, b):", "def plus(a, b):"),
        ],
        EDITABLE,
    )

    assert changed["pkg/core.py"].startswith(b"def plus(a, b):")
    assert b"def multiply(a, b):" in changed["pkg/core.py"]


def test_a_new_file_is_created() -> None:
    changed = apply_edits(SNAPSHOT, [edit("pkg/extra.py", "", "X = 1\n")], EDITABLE)

    assert changed["pkg/extra.py"] == b"X = 1\n"


def test_line_endings_follow_the_file() -> None:
    changed = apply_edits(
        SNAPSHOT, [edit("windows.py", "x = 1\ny", "x = 10\ny")], EDITABLE
    )

    assert changed["windows.py"] == b"x = 10\r\ny = 2\r\n"


@pytest.mark.parametrize(
    ("edits", "reason"),
    [
        pytest.param(
            [edit("pkg/core.py", "return a - b", "x")], "0 places", id="not-found"
        ),
        pytest.param(
            [edit("pkg/core.py", "    return a", "x")], "2 places", id="ambiguous"
        ),
        pytest.param(
            [
                edit("pkg/core.py", "def add(a, b):\n    return", "x"),
                edit("pkg/core.py", "return a + b", "y"),
            ],
            "overlap",
            id="overlapping",
        ),
        pytest.param(
            [
                edit("pkg/core.py", "def mul", "def m"),
                edit("pkg/core.py", "def mul", "def m"),
            ],
            "overlap",
            id="duplicate",
        ),
        pytest.param([edit("/etc/passwd", "", "x")], "not a path", id="absolute"),
        pytest.param([edit("../escape.py", "", "x")], "not a path", id="dot-dot"),
        pytest.param(
            [edit("pkg//core.py", "add", "x")], "not a path", id="empty-segment"
        ),
        pytest.param(
            [edit(".github/workflows/ci.yml", "", "x")], "not a path", id="workflow"
        ),
        pytest.param([edit(".env", "", "KEY=1")], "not a path", id="credentials"),
        pytest.param([edit("Dockerfile", "", "FROM x")], "not a path", id="deployment"),
        pytest.param(
            [edit("README.md", "# pkg", "# p")], "not one of the files", id="unread"
        ),
        pytest.param(
            [edit("missing.py", "old", "new")], "doesn't exist", id="outside-snapshot"
        ),
        pytest.param(
            [edit("pkg/core.py", "", "x")], "already exists", id="create-existing"
        ),
        pytest.param(
            [edit("new.py", "", "a"), edit("new.py", "", "b")],
            "only be created, once",
            id="create-twice",
        ),
        pytest.param([edit("README.md/x.py", "", "x")], "clashes", id="under-a-file"),
        pytest.param([edit("pkg", "", "x")], "clashes", id="over-a-directory"),
    ],
)
def test_edits_that_cannot_apply_exactly_change_nothing(
    edits: list[FileEdit], reason: str
) -> None:
    with pytest.raises(EditError, match=reason):
        apply_edits(
            SNAPSHOT, [edit("pkg/core.py", "def add", "def plus"), *edits], EDITABLE
        )


def test_too_many_edits_are_refused() -> None:
    with pytest.raises(EditError, match="more than"):
        apply_edits(
            SNAPSHOT, [edit(f"new_{n}.py", "", "x") for n in range(21)], EDITABLE
        )


def test_the_diff_is_a_normal_unified_diff_of_changed_files_only() -> None:
    changed = apply_edits(
        SNAPSHOT,
        [
            edit("pkg/core.py", "    return a * b\n", "    return b * a\n"),
            edit("pkg/new.py", "", "NEW = True"),
        ],
        EDITABLE,
    )

    changes = describe_changes(SNAPSHOT, changed, "Why.")

    assert [(f.path, f.status, f.additions, f.deletions) for f in changes.files] == [
        ("pkg/core.py", "modified", 1, 1),
        ("pkg/new.py", "added", 1, 0),
    ]
    assert changes.files[0].diff == (
        "--- a/pkg/core.py\n+++ b/pkg/core.py\n@@ -3,4 +3,4 @@\n \n \n def mul(a, b):\n"
        "-    return a * b\n+    return b * a\n"
    )
    assert changes.files[1].diff == (
        "--- /dev/null\n+++ b/pkg/new.py\n@@ -0,0 +1 @@\n+NEW = True\n"
        "\\ No newline at end of file\n"
    )
    assert changes.explanation == "Why."


def test_the_same_edits_always_give_the_same_diff() -> None:
    edits = [
        edit("tests/test_core.py", "== 3", "== 3  # sum"),
        edit("pkg/core.py", "a + b", "b + a"),
    ]

    first = describe_changes(SNAPSHOT, apply_edits(SNAPSHOT, edits, EDITABLE), "x")
    second = describe_changes(
        SNAPSHOT, apply_edits(SNAPSHOT, list(reversed(edits)), EDITABLE), "x"
    )

    assert first == second
    assert [f.path for f in first.files] == ["pkg/core.py", "tests/test_core.py"]


def test_unchanged_content_is_not_a_change() -> None:
    changed = apply_edits(SNAPSHOT, [edit("pkg/core.py", "a + b", "a + b")], EDITABLE)

    assert describe_changes(SNAPSHOT, changed, "x").files == []
