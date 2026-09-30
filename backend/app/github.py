"""GitHub, read-only: resolve a repository to its default branch's current commit, and
download the repository at exactly that commit.

The only module that talks to GitHub or holds a GitHub credential. What it returns never
carries the credential, and it never unpacks or runs what it downloads.
"""

import logging
import re
from typing import Any, NoReturn, Protocol
from urllib.parse import quote, urlsplit

import httpx2
from pydantic import SecretStr

from app.repository import RepositoryError, parse_repository
from app.state import RepositoryRef

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com"
API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "AstraAi",
}
# The archive endpoint redirects here; nowhere else is followed.
ARCHIVE_HOST = "codeload.github.com"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
COMMIT_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
TIMEOUT_SECONDS = 30


class GitHubProvider(Protocol):
    async def resolve(self, repository: str) -> RepositoryRef: ...

    async def download(self, repository: RepositoryRef) -> bytes: ...


class _WithoutQueries(logging.Filter):
    """httpx2 logs every request URL; a private archive's download URL carries a
    short-lived access token in its query, so logged URLs lose their query."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                arg.copy_with(query=None) if isinstance(arg, httpx2.URL) else arg
                for arg in record.args
            )
        return True


logging.getLogger("httpx2").addFilter(_WithoutQueries())


class GitHub:
    """GitHub's REST API. Public repositories need no token; a token, if configured,
    goes to api.github.com only and never follows a redirect."""

    def __init__(
        self,
        token: SecretStr | None = None,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._token = token if token is not None and token.get_secret_value() else None
        self._client = http_client or httpx2.AsyncClient(timeout=TIMEOUT_SECONDS)

    async def close(self) -> None:
        await self._client.aclose()

    async def resolve(self, repository: str) -> RepositoryRef:
        """The default branch and its current commit: the version the run will use."""
        found = await self._api_json(f"/repos/{parse_repository(repository)}")
        branch = found.get("default_branch")
        full_name = found.get("full_name")
        if not isinstance(branch, str) or not branch or not isinstance(full_name, str):
            raise RepositoryError("github_unavailable")
        full_name = parse_repository(full_name)
        head = await self._api_json(
            f"/repos/{full_name}/branches/{quote(branch, safe='')}",
            missing="repository_empty",
        )
        sha = (head.get("commit") or {}).get("sha")
        if not isinstance(sha, str) or not COMMIT_SHA.fullmatch(sha):
            raise RepositoryError("github_unavailable")
        return RepositoryRef(full_name=full_name, default_branch=branch, commit_sha=sha)

    async def download(self, repository: RepositoryRef) -> bytes:
        """The repository's .tar.gz at the pinned commit, never the branch's latest."""
        if not COMMIT_SHA.fullmatch(repository.commit_sha):
            raise RepositoryError("github_unavailable")
        path = f"/repos/{parse_repository(repository.full_name)}"
        response = await self._api(f"{path}/tarball/{repository.commit_sha}")
        location = response.headers.get("location", "")
        target = urlsplit(location)
        if response.status_code != 302 or target.scheme != "https":
            self._refuse(response, "repository_not_found")
        if target.hostname != ARCHIVE_HOST:
            logger.warning("GitHub archive redirect to an unexpected host was refused")
            raise RepositoryError("github_unavailable")
        # The redirect carries its own short-lived access, so no credential goes along.
        try:
            async with self._client.stream(
                "GET", location, headers={"User-Agent": "AstraAi"}
            ) as archive:
                if archive.status_code != 200:
                    self._refuse(archive, "repository_not_found")
                declared = archive.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_ARCHIVE_BYTES:
                    raise RepositoryError("repository_too_large")
                chunks: list[bytes] = []
                size = 0
                async for chunk in archive.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        raise RepositoryError("repository_too_large")
                    chunks.append(chunk)
        except httpx2.HTTPError as exc:
            logger.warning("GitHub archive download failed: %s", type(exc).__name__)
            raise RepositoryError("github_unavailable") from exc
        return b"".join(chunks)

    async def _api(self, path: str) -> httpx2.Response:
        headers = dict(API_HEADERS)
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        try:
            return await self._client.get(f"{API_URL}{path}", headers=headers)
        except httpx2.HTTPError as exc:
            logger.warning("GitHub request failed: %s", type(exc).__name__)
            raise RepositoryError("github_unavailable") from exc

    async def _api_json(
        self, path: str, missing: str = "repository_not_found"
    ) -> dict[str, Any]:
        response = await self._api(path)
        if response.status_code != 200:
            self._refuse(response, missing)
        try:
            body = response.json()
        except ValueError as exc:
            raise RepositoryError("github_unavailable") from exc
        if not isinstance(body, dict):
            raise RepositoryError("github_unavailable")
        return body

    def _refuse(self, response: httpx2.Response, missing: str) -> NoReturn:
        """Turn a GitHub refusal into a safe, specific error. GitHub's own message and
        the request's URL are never passed on."""
        status = response.status_code
        if status in (404, 409, 451):
            if missing == "repository_not_found" and self._token is None:
                # Without a token a private repository looks exactly like a missing one.
                raise RepositoryError("repository_not_public")
            raise RepositoryError(missing)
        if status == 401 and self._token is not None:
            logger.warning("GitHub rejected the configured token")
        else:
            logger.warning("GitHub answered %d", status)
        raise RepositoryError("github_unavailable")
