"""GitHub REST, read-only, against a mock of GitHub's real responses."""

import asyncio
import logging
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app import github as github_module
from app.github import GitHub
from app.repository import RepositoryError
from app.state import RepositoryRef
from tests.fake_github import SAMPLE_FILES, SHA, make_archive

TOKEN = "github_pat_test_0123456789_secret"
DOWNLOAD_TOKEN = "codeload_temporary_secret"
CANONICAL = "Octo/Sample"


class GitHubApi:
    """Answers like api.github.com and codeload.github.com, and records every request."""

    def __init__(self, **overrides: Any) -> None:
        self.repo_status = 200
        self.default_branch = "main"
        self.branch_status = 200
        self.tarball_status = 302
        self.location = (
            f"https://codeload.github.com/{CANONICAL}/legacy.tar.gz/{SHA}"
            f"?token={DOWNLOAD_TOKEN}"
        )
        self.archive = make_archive(SAMPLE_FILES)
        self.archive_headers: dict[str, str] = {}
        self.error: Exception | None = None
        self.__dict__.update(overrides)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        path = request.url.path
        if request.url.host == "api.github.com":
            if path == "/repos/octo/sample":
                return httpx2.Response(
                    self.repo_status,
                    json={"full_name": CANONICAL, "default_branch": self.default_branch}
                    if self.repo_status == 200
                    else {"message": "Not Found: internal detail"},
                )
            if path == f"/repos/{CANONICAL}/branches/{self.default_branch}":
                return httpx2.Response(
                    self.branch_status,
                    json={"name": self.default_branch, "commit": {"sha": SHA}},
                )
            if path == f"/repos/{CANONICAL}/tarball/{SHA}":
                return httpx2.Response(
                    self.tarball_status, headers={"location": self.location}
                )
        if request.url.host == "codeload.github.com":
            return httpx2.Response(
                200, content=self.archive, headers=self.archive_headers
            )
        return httpx2.Response(404)

    def to(self, host: str) -> list[httpx2.Request]:
        return [request for request in self.requests if request.url.host == host]


def client(api: GitHubApi, token: str | None = None) -> GitHub:
    return GitHub(
        SecretStr(token) if token is not None else None,
        httpx2.AsyncClient(transport=httpx2.MockTransport(api)),
    )


async def fetch(
    provider: GitHub, repository: str = "octo/sample"
) -> tuple[RepositoryRef, bytes]:
    try:
        ref = await provider.resolve(repository)
        return ref, await provider.download(ref)
    finally:
        await provider.close()


def failure(api: GitHubApi, token: str | None = None) -> str:
    with pytest.raises(RepositoryError) as refused:
        asyncio.run(fetch(client(api, token)))
    return refused.value.code


def test_resolves_the_default_branch_and_pins_its_current_commit() -> None:
    api = GitHubApi(default_branch="trunk")

    ref, archive = asyncio.run(fetch(client(api)))

    assert ref == RepositoryRef(
        full_name=CANONICAL, default_branch="trunk", commit_sha=SHA
    )
    assert [request.url.path for request in api.to("api.github.com")] == [
        "/repos/octo/sample",
        f"/repos/{CANONICAL}/branches/trunk",
        # The archive is asked for at the pinned commit, never at the branch.
        f"/repos/{CANONICAL}/tarball/{SHA}",
    ]
    assert archive == api.archive


def test_a_public_repository_needs_no_token() -> None:
    api = GitHubApi()

    asyncio.run(fetch(client(api)))

    assert all("authorization" not in request.headers for request in api.requests)


def test_the_token_goes_to_the_api_only_and_never_follows_the_redirect() -> None:
    api = GitHubApi()

    asyncio.run(fetch(client(api, TOKEN)))

    assert all(
        request.headers["authorization"] == f"Bearer {TOKEN}"
        for request in api.to("api.github.com")
    )
    [download] = api.to("codeload.github.com")
    assert "authorization" not in download.headers
    assert download.url.path == f"/{CANONICAL}/legacy.tar.gz/{SHA}"


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/archive.tar.gz",
        f"http://codeload.github.com/{CANONICAL}/legacy.tar.gz/{SHA}",
        "https://codeload.github.com.evil.example/archive.tar.gz",
        "",
    ],
)
def test_a_redirect_anywhere_else_is_never_followed(location: str) -> None:
    api = GitHubApi(location=location)

    assert failure(api, TOKEN) == "github_unavailable"
    assert {request.url.host for request in api.requests} == {"api.github.com"}


def test_a_private_repository_without_a_token_says_access_isnt_configured() -> None:
    # Without a token GitHub answers 404 for a private repository, as for a missing one.
    assert failure(GitHubApi(repo_status=404)) == "repository_not_public"


def test_a_missing_repository_with_a_token_is_not_found() -> None:
    assert failure(GitHubApi(repo_status=404), TOKEN) == "repository_not_found"


def test_github_messages_are_never_passed_on() -> None:
    with pytest.raises(RepositoryError) as refused:
        asyncio.run(fetch(client(GitHubApi(repo_status=404))))

    assert "internal detail" not in refused.value.message
    assert "GitHub access isn't configured yet" in refused.value.message


def test_an_empty_repository_is_named_as_such() -> None:
    assert failure(GitHubApi(branch_status=404)) == "repository_empty"


@pytest.mark.parametrize("status", [401, 403, 429, 500, 502])
def test_refusals_and_outages_are_unavailable(status: int) -> None:
    assert failure(GitHubApi(repo_status=status), TOKEN) == "github_unavailable"


def test_a_network_error_is_unavailable() -> None:
    assert (
        failure(GitHubApi(error=httpx2.ConnectError("no route")))
        == "github_unavailable"
    )


def test_a_declared_oversized_archive_is_refused_before_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github_module, "MAX_ARCHIVE_BYTES", 100)
    api = GitHubApi(archive_headers={"content-length": "1000000"})

    assert failure(api) == "repository_too_large"


def test_an_oversized_archive_is_cut_off_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github_module, "MAX_ARCHIVE_BYTES", 100)

    assert failure(GitHubApi(archive=bytes(10_000))) == "repository_too_large"


def test_unexpected_answers_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    api = GitHubApi()
    original = api.__call__

    def bad_sha(request: httpx2.Request) -> httpx2.Response:
        if "/branches/" in request.url.path:
            return httpx2.Response(200, json={"commit": {"sha": "main; rm -rf /"}})
        return original(request)

    provider = GitHub(None, httpx2.AsyncClient(transport=httpx2.MockTransport(bad_sha)))
    with pytest.raises(RepositoryError) as refused:
        asyncio.run(fetch(provider))

    assert refused.value.code == "github_unavailable"


def test_an_invalid_address_is_refused_before_any_request() -> None:
    api = GitHubApi()

    with pytest.raises(ValueError):
        asyncio.run(fetch(client(api), "https://evil.example/octo/sample"))

    assert api.requests == []


def test_no_token_or_download_url_secret_reaches_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    asyncio.run(fetch(client(GitHubApi(), TOKEN)))
    with pytest.raises(RepositoryError):
        asyncio.run(fetch(client(GitHubApi(repo_status=401), TOKEN)))

    assert TOKEN not in caplog.text
    assert DOWNLOAD_TOKEN not in caplog.text
    # The request log still names the download host, just not its query.
    assert "codeload.github.com" in caplog.text
