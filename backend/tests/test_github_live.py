"""Opt-in check against the real GitHub API, with no token, on a tiny public repository.

Run with ASTRAAI_LIVE_GITHUB=1. Never part of the normal test run.
"""

import asyncio
import os
import re

import pytest

from app.github import GitHub
from app.repository import read_archive

pytestmark = [
    pytest.mark.github,
    pytest.mark.skipif(
        os.getenv("ASTRAAI_LIVE_GITHUB") != "1",
        reason="set ASTRAAI_LIVE_GITHUB=1 to call the real GitHub API",
    ),
]


def test_a_public_repository_resolves_downloads_and_reads_without_a_token() -> None:
    async def fetch() -> tuple[object, dict[str, bytes]]:
        github = GitHub()
        try:
            ref = await github.resolve("https://github.com/octocat/Hello-World")
            return ref, read_archive(await github.download(ref))
        finally:
            await github.close()

    ref, files = asyncio.run(fetch())

    assert ref.full_name == "octocat/Hello-World"
    assert ref.default_branch == "master"
    assert re.fullmatch(r"[0-9a-f]{40}", ref.commit_sha)
    assert files == {"README": b"Hello World!\n"}
