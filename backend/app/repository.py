"""Repositories as untrusted data: the address a user typed, and the archive GitHub sends.

A snapshot is a repository's regular files, in memory, keyed by validated relative path.
Nothing here writes to disk, extracts an archive or runs repository code.
"""

import io
import re
import tarfile
import zlib
from urllib.parse import urlsplit

# Bounds on what one run may hold in memory and hand to the sandbox.
MAX_FILES = 10_000
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
# The tar around the files: headers and padding, at most a few KB per file.
MAX_TAR_BYTES = MAX_SNAPSHOT_BYTES + 16 * 1024 * 1024

# GitHub's rules: owner up to 39 letters, digits and single inner hyphens; repository names
# are letters, digits, '.', '-' and '_'.
OWNER = re.compile(r"(?=.{1,39}$)[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
NAME = re.compile(r"[A-Za-z0-9._-]{1,100}")
GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})

Snapshot = dict[str, bytes]

MESSAGES = {
    "repository_not_found": "AstraAi couldn't find this repository, or doesn't have access "
    "to it.",
    "repository_not_public": "AstraAi couldn't find a public repository at this address. "
    "If it's private, GitHub access isn't configured yet.",
    "repository_empty": "This repository has no commits yet.",
    "github_unavailable": "AstraAi couldn't get this repository from GitHub right now. "
    "Try again in a few minutes.",
    "repository_too_large": "This repository is larger than AstraAi can check right now.",
    "repository_unsupported": "This repository contains files AstraAi can't safely handle "
    "yet, such as symbolic links.",
}


class RepositoryError(Exception):
    """A repository problem the user can act on. The code and message are safe to show."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = MESSAGES[code]


def parse_repository(text: str) -> str:
    """`owner/name` from a GitHub repository URL or `owner/name`; ValueError otherwise.

    Accepts https://github.com/owner/name, with or without www., a trailing slash or
    .git. Anything else (another host, a deeper path, a query) is refused.
    """
    value = text.strip()
    if "://" in value:
        parts = urlsplit(value)
        if (
            parts.scheme not in ("https", "http")
            or parts.hostname not in GITHUB_HOSTS
            or parts.port is not None
            or parts.username is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("not a GitHub repository URL")
        path = parts.path
    elif value.split("/", 1)[0] in GITHUB_HOSTS:
        path = value.split("/", 1)[1] if "/" in value else ""
    else:
        path = value
    # One leading and one trailing slash at most; an empty segment anywhere is refused.
    path = path.removeprefix("/").removesuffix("/").removesuffix(".git")
    segments = path.split("/")
    if (
        len(segments) != 2
        or not OWNER.fullmatch(segments[0])
        or not NAME.fullmatch(segments[1])
        or segments[1] in (".", "..")
    ):
        raise ValueError("not a GitHub repository")
    return f"{segments[0]}/{segments[1]}"


def safe_path(path: str) -> bool:
    """A relative path that stays inside the repository, with no surprises in it."""
    if not path or path.startswith("/") or "\x00" in path or "\\" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def read_archive(data: bytes) -> Snapshot:
    """The regular files of a GitHub .tar.gz archive, in memory. Never extracts anything.

    Decompression is capped before tarfile sees a byte, so every header and file is
    bounded. Links, devices and unsafe paths refuse the whole archive rather than being
    skipped, so the snapshot is always the repository as it is.
    """
    inflater = zlib.decompressobj(wbits=31)
    try:
        tar = inflater.decompress(data, MAX_TAR_BYTES + 1)
    except zlib.error as exc:
        raise RepositoryError("repository_unsupported") from exc
    if len(tar) > MAX_TAR_BYTES:
        raise RepositoryError("repository_too_large")
    if not inflater.eof:
        raise RepositoryError("repository_unsupported")

    files: Snapshot = {}
    total = 0
    root: str | None = None
    try:
        with tarfile.open(fileobj=io.BytesIO(tar), mode="r:") as archive:
            for member in archive:
                # GitHub wraps everything in one top-level directory, owner-name-sha/.
                top, _, path = member.name.partition("/")
                root = root if root is not None else top
                if not top or top != root:
                    raise RepositoryError("repository_unsupported")
                if member.isdir():
                    continue
                if not member.isreg() or not safe_path(path) or path in files:
                    raise RepositoryError("repository_unsupported")
                total += member.size
                if len(files) >= MAX_FILES or total > MAX_SNAPSHOT_BYTES:
                    raise RepositoryError("repository_too_large")
                # Reads the member's bytes out of the in-memory tar; nothing touches disk.
                content = archive.extractfile(member)
                files[path] = content.read() if content is not None else b""
    except tarfile.TarError as exc:
        raise RepositoryError("repository_unsupported") from exc
    return files
