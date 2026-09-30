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


def describe_changes(
    original: Snapshot, changed: Snapshot, explanation: str
) -> ChangeSet:
    """Unified diffs of every file that differs, sorted by path. Same inputs, same output."""
    files: list[FileChange] = []
    for path in sorted(path for path in changed if original.get(path) != changed[path]):
        before = original.get(path)
        lines = list(
            difflib.unified_diff(
                before.decode("utf-8").splitlines(keepends=True)
                if before is not None
                else [],
                changed[path].decode("utf-8").splitlines(keepends=True),
                fromfile=f"a/{path}" if before is not None else "/dev/null",
                tofile=f"b/{path}",
            )
        )
        body = lines[2:]  # After the ---/+++ header.
        files.append(
            FileChange(
                path=path,
                status="modified" if before is not None else "added",
                additions=sum(1 for line in body if line.startswith("+")),
                deletions=sum(1 for line in body if line.startswith("-")),
                diff="".join(
                    line
                    if line.endswith("\n")
                    else f"{line}\n\\ No newline at end of file\n"
                    for line in lines
                ),
            )
        )
    return ChangeSet(files=files, explanation=explanation)
