"""The downloadable patch: what plain `git apply` needs to turn the repository as
downloaded into exactly the final files, and nothing else from the repository."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.changes import apply_edits, describe_changes, git_path, patch
from app.state import FileEdit

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

ORIGINAL = {
    "pkg/core.py": b"def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n",
    "pkg/windows.py": b"def hello():\r\n    return 'hi'\r\n",
    "pkg/no_newline.py": b"VALUE = 1",
    "pkg/odd.py": b"A = 1\n\x0c\nB = '\r'\nC = 3\n",
    "docs/my notes.md": b"# Notes\n",
    "pkg/café.py".encode().decode(): b"X = 1\n",
    "pkg/untouched.py": b"UNTOUCHED_FILE_CONTENT = True\n" * 50,
}


def edit(path: str, old: str, new: str) -> FileEdit:
    return FileEdit(path=path, old=old, new=new)


def git(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Plain git, untouched by this machine's own git configuration."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def applied(tmp_path: Path, original: dict[str, bytes], text: str) -> dict[str, bytes]:
    """The original files after `git apply --check` and `git apply` of the patch."""
    for path, data in original.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
    (tmp_path.parent / "change.patch").write_bytes(text.encode("utf-8"))
    for args in (["apply", "--check"], ["apply"]):
        result = git(tmp_path, *args, str(tmp_path.parent / "change.patch"))
        assert result.returncode == 0, result.stderr
    return {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }


def roundtrip(tmp_path: Path, edits: list[FileEdit]) -> None:
    changed = apply_edits(ORIGINAL, edits, editable=set(ORIGINAL))
    text = patch(describe_changes(ORIGINAL, changed, "x"))
    assert applied(tmp_path, ORIGINAL, text) == changed


def test_modified_and_new_files_apply_exactly(tmp_path: Path) -> None:
    roundtrip(
        tmp_path,
        [
            edit("pkg/core.py", "    return a + b\n", "    return b + a\n"),
            edit("pkg/new.py", "", "NEW = True\n"),
            edit("tests/test_new.py", "", "def test_new():\n    assert True\n"),
        ],
    )


def test_a_new_empty_file_applies(tmp_path: Path) -> None:
    roundtrip(tmp_path, [edit("pkg/__init__.py", "", "")])


def test_crlf_files_keep_their_line_endings(tmp_path: Path) -> None:
    roundtrip(tmp_path, [edit("pkg/windows.py", "'hi'", "'hello'")])


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("VALUE = 1", "VALUE = 2"),  # Still no final newline.
        ("VALUE = 1", "VALUE = 2\n"),  # Gains one.
    ],
    ids=["kept", "added"],
)
def test_a_missing_final_newline_is_kept_or_fixed_exactly(
    tmp_path: Path, old: str, new: str
) -> None:
    roundtrip(tmp_path, [edit("pkg/no_newline.py", old, new)])


def test_a_new_file_without_a_final_newline_applies(tmp_path: Path) -> None:
    roundtrip(tmp_path, [edit("pkg/last.py", "", "LAST = 1")])


def test_form_feeds_and_lone_carriage_returns_are_ordinary_characters(
    tmp_path: Path,
) -> None:
    # str.splitlines would split at both, and git would reject the patch.
    roundtrip(tmp_path, [edit("pkg/odd.py", "C = 3", "C = 4")])


def test_spaces_and_non_ascii_in_paths_apply(tmp_path: Path) -> None:
    roundtrip(
        tmp_path,
        [
            edit("docs/my notes.md", "# Notes", "# My notes"),
            edit("pkg/café.py", "X = 1", "X = 2"),
        ],
    )


def test_paths_git_must_quote_are_quoted_as_git_does() -> None:
    assert git_path("a/plain name.py") == "a/plain name.py"
    assert git_path('a/say "hi".py') == '"a/say \\"hi\\".py"'
    assert git_path("a/tab\there.py") == '"a/tab\\there.py"'


@pytest.mark.skipif(os.name == "nt", reason="Windows can't name a file with a quote")
def test_a_quoted_path_applies(tmp_path: Path) -> None:
    original = {**ORIGINAL, 'pkg/say "hi".py': b"Q = 1\n"}
    changed = {**original, 'pkg/say "hi".py': b"Q = 2\n"}
    text = patch(describe_changes(original, changed, "x"))
    assert applied(tmp_path, original, text) == changed


def test_the_patch_holds_only_the_change(tmp_path: Path) -> None:
    changed = apply_edits(
        ORIGINAL,
        [edit("pkg/core.py", "    return a * b\n", "    return a * b * 1\n")],
        editable=set(ORIGINAL),
    )

    text = patch(describe_changes(ORIGINAL, changed, "x"))

    # Untouched files, and lines far from the change, never leave the snapshot.
    assert "UNTOUCHED_FILE_CONTENT" not in text
    assert "pkg/untouched.py" not in text
    assert text.count("diff --git") == 1
    assert applied(tmp_path, ORIGINAL, text) == changed


def test_files_are_ordered_code_then_tests_then_the_rest() -> None:
    changed = {
        **ORIGINAL,
        "docs/my notes.md": b"# Changed\n",
        "tests/test_core.py": b"def test(): pass\n",
        "pkg/core.py": b"CHANGED = 1\n",
        "README.md": b"# readme\n",
        "pkg/core.pyi": b"CHANGED: int\n",
    }

    paths = [change.path for change in describe_changes(ORIGINAL, changed, "x").files]

    assert paths == [
        "pkg/core.py",
        "pkg/core.pyi",
        "tests/test_core.py",
        "README.md",
        "docs/my notes.md",
    ]
