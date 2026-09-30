"""The repository address and archive are untrusted input: only safe shapes get through."""

import builtins
import io
import tarfile
from pathlib import Path

import pytest

from app import repository
from app.repository import RepositoryError, parse_repository, read_archive, safe_path
from tests.fake_github import ROOT, SAMPLE_FILES, make_archive


@pytest.mark.parametrize(
    "text",
    [
        "octo/sample",
        "https://github.com/octo/sample",
        "https://github.com/octo/sample/",
        "https://github.com/octo/sample.git",
        "http://github.com/octo/sample",
        "https://www.github.com/octo/sample",
        "github.com/octo/sample",
        "  https://github.com/octo/sample  ",
    ],
)
def test_github_repository_addresses_become_owner_and_name(text: str) -> None:
    assert parse_repository(text) == "octo/sample"


def test_real_names_keep_their_characters() -> None:
    assert (
        parse_repository("https://github.com/py-lib/my_repo.v2") == "py-lib/my_repo.v2"
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "octo",
        "https://gitlab.com/octo/sample",
        "https://github.com.evil.com/octo/sample",
        "https://evil.com/github.com/octo/sample",
        "https://github.com/octo/sample/tree/main",
        "https://github.com/octo/sample/blob/main/README.md",
        "https://github.com/octo/sample?tab=readme",
        "https://github.com/octo/sample#readme",
        "https://user@github.com/octo/sample",
        "https://github.com:8443/octo/sample",
        "ftp://github.com/octo/sample",
        "git@github.com:octo/sample.git",
        "file:///etc/passwd",
        "octo/../sample",
        "octo/..",
        "../octo/sample",
        "-octo/sample",
        "octo-/sample",
        "oc--to/sample",
        "octo/sam ple",
        "octo/sample%2F..",
        f"{'a' * 40}/sample",
        "https://github.com//octo/sample",
    ],
)
def test_anything_else_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_repository(text)


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../evil",
        "a/../../evil",
        "a/./b",
        "a//b",
        "a\\b",
        "a\x00b",
        "",
        ".",
    ],
)
def test_unsafe_paths_are_recognized(path: str) -> None:
    assert not safe_path(path)


def test_a_github_archive_becomes_its_files_under_the_top_directory() -> None:
    files = read_archive(make_archive(SAMPLE_FILES))

    assert files == SAMPLE_FILES


def member(name: str, kind: bytes, **fields: object) -> tarfile.TarInfo:
    entry = tarfile.TarInfo(f"{ROOT}/{name}")
    entry.type = kind
    for key, value in fields.items():
        setattr(entry, key, value)
    return entry


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(
            member("link", tarfile.SYMTYPE, linkname="/etc/passwd"), id="symlink"
        ),
        pytest.param(
            member("hard", tarfile.LNKTYPE, linkname=f"{ROOT}/README.md"), id="hardlink"
        ),
        pytest.param(
            member("tty", tarfile.CHRTYPE, devmajor=4, devminor=0), id="char-device"
        ),
        pytest.param(
            member("disk", tarfile.BLKTYPE, devmajor=8, devminor=0), id="block-device"
        ),
        pytest.param(member("pipe", tarfile.FIFOTYPE), id="fifo"),
    ],
)
def test_links_and_devices_refuse_the_whole_repository(extra: tarfile.TarInfo) -> None:
    with pytest.raises(RepositoryError) as refused:
        read_archive(make_archive(SAMPLE_FILES, extra=[extra]))

    assert refused.value.code == "repository_unsupported"


def raw_archive(names: list[str]) -> bytes:
    """A .tar.gz with members named exactly as given, however unsafe."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in names:
            entry = tarfile.TarInfo(name)
            entry.size = 1
            archive.addfile(entry, io.BytesIO(b"x"))
    return buffer.getvalue()


@pytest.mark.parametrize(
    "names",
    [
        pytest.param([f"{ROOT}/ok.py", f"{ROOT}/../escape.py"], id="dot-dot"),
        pytest.param([f"{ROOT}/ok.py", f"{ROOT}//etc/passwd"], id="absolute-inside"),
        pytest.param(["/etc/passwd"], id="absolute"),
        pytest.param(
            [f"{ROOT}/ok.py", "other-root/evil.py"], id="second-top-directory"
        ),
        pytest.param([f"{ROOT}/ok.py", f"{ROOT}/ok.py"], id="duplicate"),
        pytest.param([f"{ROOT}/a\\..\\b.py"], id="backslash"),
        pytest.param(["just-a-file"], id="no-top-directory"),
    ],
)
def test_unsafe_member_paths_refuse_the_whole_repository(names: list[str]) -> None:
    with pytest.raises(RepositoryError) as refused:
        read_archive(raw_archive(names))

    assert refused.value.code == "repository_unsupported"


def test_too_many_files_is_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "MAX_FILES", 2)

    with pytest.raises(RepositoryError) as refused:
        read_archive(make_archive(SAMPLE_FILES))

    assert refused.value.code == "repository_too_large"


def test_too_many_bytes_is_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "MAX_SNAPSHOT_BYTES", 40)

    with pytest.raises(RepositoryError) as refused:
        read_archive(make_archive(SAMPLE_FILES))

    assert refused.value.code == "repository_too_large"


def test_decompression_stops_at_the_cap_before_the_tar_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A small download that inflates without bound: 50 MB of zeros in a few KB.
    bomb = make_archive({"zeros.bin": bytes(50 * 1024 * 1024)})
    assert len(bomb) < 200_000
    monkeypatch.setattr(repository, "MAX_TAR_BYTES", 1024 * 1024)
    opened: list[object] = []
    monkeypatch.setattr(tarfile, "open", lambda *a, **k: opened.append(a) or None)

    with pytest.raises(RepositoryError) as refused:
        read_archive(bomb)

    assert refused.value.code == "repository_too_large"
    assert opened == []


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"not an archive", id="not-gzip"),
        pytest.param(make_archive(SAMPLE_FILES)[:-40], id="truncated"),
        pytest.param(b"\x1f\x8b\x08\x00" + b"\x00" * 20, id="corrupt"),
    ],
)
def test_broken_archives_are_unsupported(data: bytes) -> None:
    with pytest.raises(RepositoryError) as refused:
        read_archive(data)

    assert refused.value.code == "repository_unsupported"


def test_reading_an_archive_never_writes_to_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_open = builtins.open

    def read_only_open(file: object, mode: str = "r", *args: object, **kwargs: object):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"wrote to {file}")
        return real_open(file, mode, *args, **kwargs)

    def no_extraction(*args: object, **kwargs: object) -> None:
        raise AssertionError("extracted to disk")

    monkeypatch.setattr(builtins, "open", read_only_open)
    for name in ("extract", "extractall", "_extract_member", "makefile"):
        monkeypatch.setattr(tarfile.TarFile, name, no_extraction)
    monkeypatch.chdir(tmp_path)

    files = read_archive(make_archive(SAMPLE_FILES))

    assert files == SAMPLE_FILES
    assert list(tmp_path.iterdir()) == []
