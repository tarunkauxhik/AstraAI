"""A GitHub stand-in and hand-built archives, so DEVELOP tests never touch the network."""

import io
import tarfile

from app.repository import RepositoryError, read_archive
from app.state import RepositoryRef

SHA = "a" * 40
REPOSITORY = "octo/sample"
ROOT = f"octo-sample-{SHA[:7]}"
SAMPLE_FILES = {
    "README.md": b"# sample\n",
    "sample/__init__.py": b"def add(a, b):\n    return a + b\n",
    "tests/test_add.py": b"from sample import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
}


def make_archive(
    files: dict[str, bytes], root: str = ROOT, extra: list[tarfile.TarInfo] = ()
) -> bytes:
    """A .tar.gz shaped like GitHub's: everything under one top-level directory."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        top = tarfile.TarInfo(root)
        top.type = tarfile.DIRTYPE
        archive.addfile(top)
        for path, data in files.items():
            entry = tarfile.TarInfo(f"{root}/{path}")
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        for entry in extra:
            archive.addfile(entry)
    return buffer.getvalue()


class FakeGitHub:
    """Resolves any repository to one pinned commit and serves one archive for it."""

    def __init__(
        self,
        files: dict[str, bytes] = SAMPLE_FILES,
        error: str | None = None,
        archive: bytes | None = None,
    ) -> None:
        self.archive = archive if archive is not None else make_archive(files)
        self.error = error
        self.resolved: list[str] = []
        self.downloaded: list[RepositoryRef] = []

    async def resolve(self, repository: str) -> RepositoryRef:
        self.resolved.append(repository)
        if self.error is not None:
            raise RepositoryError(self.error)
        return RepositoryRef(
            full_name=repository, default_branch="main", commit_sha=SHA
        )

    async def download(self, repository: RepositoryRef) -> bytes:
        self.downloaded.append(repository)
        return self.archive


def snapshot(files: dict[str, bytes] = SAMPLE_FILES) -> dict[str, bytes]:
    return read_archive(make_archive(files))
