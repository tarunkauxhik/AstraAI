"""Whether a downloaded repository fits what AstraAi V1 supports, decided before any
sandbox run or model call: Python code, tests pytest would run, and no packages declared
that would have to be installed. Deterministic and conservative: it only reads the
snapshot, and refuses what clearly doesn't fit. The existing tests' own run, still before
any model call, remains the final check.
"""

import configparser
import re
import tomllib

from app.repository import RepositoryError, Snapshot

# pytest's default test files, and the configuration files it reads.
TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test)\.py$")
TEST_DIRECTORY = re.compile(r"(?:^|/)tests?/[^/]*\.py$")
PYTEST_CONFIG = {
    "pytest.ini": "",
    "pyproject.toml": "[tool.pytest.ini_options]",
    "setup.cfg": "[tool:pytest]",
    "tox.ini": "[pytest]",
}
# The one package the test environment has.
PROVIDED = frozenset({"pytest"})
REQUIREMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SETUP_PY_REQUIRES = re.compile(r"install_requires\s*=\s*\[([^\]]*)\]", re.DOTALL)
QUOTED = re.compile(r"""["']([^"']+)["']""")


def text(snapshot: Snapshot, path: str) -> str:
    try:
        return snapshot[path].decode("utf-8") if path in snapshot else ""
    except UnicodeDecodeError:
        return ""


def has_pytest_tests(snapshot: Snapshot) -> bool:
    """Files pytest finds by default, or a pytest configuration with a tests directory."""
    if any(TEST_FILE.search(path) or path.endswith("conftest.py") for path in snapshot):
        return True
    configured = any(
        path in snapshot and marker in text(snapshot, path)
        for path, marker in PYTEST_CONFIG.items()
    )
    return configured and any(TEST_DIRECTORY.search(path) for path in snapshot)


def declared(requirements: list[str]) -> list[str]:
    """Package names from requirement lines, leaving out options, comments and lines whose
    environment marker may not apply here (pytest's Python is recent)."""
    names = []
    for line in requirements:
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-") or ";" in line:
            continue
        match = REQUIREMENT_NAME.match(line)
        if match and match.group(0).lower() not in PROVIDED:
            names.append(match.group(0))
    return names


def dependencies(snapshot: Snapshot) -> list[str]:
    """Packages the repository's root files say it needs installed to run."""
    found: list[str] = []
    pyproject = text(snapshot, "pyproject.toml")
    if pyproject:
        try:
            data = tomllib.loads(pyproject)
        except tomllib.TOMLDecodeError:
            data = {}
        found += declared(list(data.get("project", {}).get("dependencies", [])))
        poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        found += [name for name in poetry if name.lower() != "python"]
    found += declared(text(snapshot, "requirements.txt").splitlines())
    setup_cfg = text(snapshot, "setup.cfg")
    if setup_cfg:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(setup_cfg)
            found += declared(
                parser.get("options", "install_requires", fallback="").splitlines()
            )
        except configparser.Error:
            pass
    requires = SETUP_PY_REQUIRES.search(text(snapshot, "setup.py"))
    if requires:
        found += declared(QUOTED.findall(requires.group(1)))
    return found


def check_supported(snapshot: Snapshot) -> None:
    """RepositoryError, before anything runs, when the repository clearly isn't one AstraAi
    V1 supports: no Python, no tests pytest would run, or packages it would need installed."""
    if not any(path.endswith(".py") for path in snapshot):
        raise RepositoryError("not_python")
    if not has_pytest_tests(snapshot):
        raise RepositoryError("no_pytest_tests")
    if dependencies(snapshot):
        raise RepositoryError("needs_dependencies")
