"""The model's proposed edits, applied exactly to the in-memory snapshot, and their diff.

All or nothing: any edit that can't be applied exactly rejects the whole set, and the
snapshot is never modified in place. The diff is computed from the applied edits alone.
"""

import difflib
from collections.abc import Iterable
from itertools import pairwise

from app.repository import Snapshot, protected, safe_path
from app.state import ChangeSet, FileChange, FileEdit

MAX_EDITS = 20
MAX_FILE_BYTES = 200_000


class EditError(Exception):
    """An edit that can't be applied exactly. Says which file and why, for the logs."""


def apply_edits(
    snapshot: Snapshot, edits: Iterable[FileEdit], editable: set[str]
) -> Snapshot:
    """A new snapshot with every edit applied, or EditError and no changes at all.

    Existing files may be changed only if the model was shown them (`editable`), and each
    `old` must occur in the original file exactly once. Edits to one file must not overlap.
    A new file needs an empty `old`, a path that doesn't exist, and nothing else touching it.
    """
    edits = list(edits)
    if len(edits) > MAX_EDITS:
        raise EditError(f"{len(edits)} edits, more than {MAX_EDITS}")
    by_path: dict[str, list[FileEdit]] = {}
    for edit in edits:
        by_path.setdefault(edit.path, []).append(edit)

    changed = dict(snapshot)
    for path, file_edits in by_path.items():
        if not safe_path(path) or protected(path):
            raise EditError(f"{path!r} is not a path AstraAi may change")
        if path in snapshot:
            changed[path] = _replace(path, snapshot[path], file_edits, editable)
        else:
            changed[path] = _create(path, file_edits, snapshot)
        if len(changed[path]) > MAX_FILE_BYTES:
            raise EditError(f"{path}: larger than {MAX_FILE_BYTES} bytes")
    return changed


def _replace(
    path: str, data: bytes, edits: list[FileEdit], editable: set[str]
) -> bytes:
    if path not in editable:
        raise EditError(f"{path}: not one of the files AstraAi read")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EditError(f"{path}: not a text file") from exc
    crlf = "\r\n" in text
    spans: list[tuple[int, int, str]] = []
    for edit in edits:
        if not edit.old:
            raise EditError(f"{path}: already exists, so it can't be created")
        old, new = edit.old, edit.new
        if crlf:
            # The model sees and writes plain newlines; the file keeps its own.
            old = old.replace("\r\n", "\n").replace("\n", "\r\n")
            new = new.replace("\r\n", "\n").replace("\n", "\r\n")
        found = text.count(old)
        if found != 1:
            raise EditError(f"{path}: an edit matches {found} places, not exactly one")
        start = text.index(old)
        spans.append((start, start + len(old), new))
    spans.sort()
    for (_, end, _), (start, _, _) in pairwise(spans):
        if end > start:
            raise EditError(f"{path}: edits overlap")
    for start, end, new in reversed(spans):
        text = text[:start] + new + text[end:]
    return text.encode("utf-8")


def _create(path: str, edits: list[FileEdit], snapshot: Snapshot) -> bytes:
    if len(edits) != 1 or edits[0].old:
        raise EditError(f"{path}: doesn't exist, so it can only be created, once")
    if any(
        path.startswith(f"{existing}/") or existing.startswith(f"{path}/")
        for existing in snapshot
    ):
        raise EditError(f"{path}: clashes with an existing file or directory")
    return edits[0].new.encode("utf-8")


# How git writes the characters it must escape in a quoted path.
GIT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\a": "\\a",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\v": "\\v",
    "\f": "\\f",
    "\r": "\\r",
}


def git_path(path: str) -> str:
    """A path as git writes it in a patch: C-quoted only when it has to be."""
    if not any(
        char in GIT_ESCAPES or ord(char) < 0x20 or ord(char) == 0x7F for char in path
    ):
        return path
    escaped = "".join(
        GIT_ESCAPES.get(char)
        or (f"\\{ord(char):03o}" if ord(char) < 0x20 or ord(char) == 0x7F else char)
        for char in path
    )
    return f'"{escaped}"'


def lines(data: bytes) -> list[str]:
    """A file's lines as git sees them: split at \\n only, each keeping its end.

    str.splitlines would also split at \\r, form feeds and Unicode separators, which git
    treats as ordinary characters, and the patch would no longer apply.
    """
    parts = data.decode("utf-8").split("\n")
    return [f"{part}\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def review_order(path: str) -> tuple[int, str]:
    """Code first, then tests, then documentation and configuration; by path within each."""
    *directories, name = path.split("/")
    if (
        {"test", "tests"} & set(directories)
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    ):
        return 1, path
    return (0 if name.endswith((".py", ".pyi")) else 2), path


def describe_changes(
    original: Snapshot, changed: Snapshot, explanation: str
) -> ChangeSet:
    """One git-style diff per file that differs, in review order. Same inputs, same
    output, and together they are a patch `git apply` takes on the original files."""
    files: list[FileChange] = []
    differing = (path for path in changed if original.get(path) != changed[path])
    for path in sorted(differing, key=review_order):
        before = original.get(path)
        old, new = git_path(f"a/{path}"), git_path(f"b/{path}")
        hunks = list(
            difflib.unified_diff(
                lines(before) if before is not None else [], lines(changed[path]), n=3
            )
        )[2:]  # difflib's own ---/+++ lines; git's header is written below.
        header = [f"diff --git {old} {new}\n"]
        if before is None:
            header.append("new file mode 100644\n")
        if hunks:  # A new empty file has no hunks, and git wants no ---/+++ for it.
            header += [
                f"--- {old if before is not None else '/dev/null'}\n",
                f"+++ {new}\n",
            ]
        files.append(
            FileChange(
                path=path,
                status="modified" if before is not None else "added",
                additions=sum(1 for line in hunks if line.startswith("+")),
                deletions=sum(1 for line in hunks if line.startswith("-")),
                diff="".join(header)
                + "".join(
                    line
                    if line.endswith("\n")
                    else f"{line}\n\\ No newline at end of file\n"
                    for line in hunks
                ),
            )
        )
    return ChangeSet(files=files, explanation=explanation)


def patch(changes: ChangeSet) -> str:
    """The whole change as one patch, from the repository as downloaded to the final files."""
    return "".join(change.diff for change in changes.files)
