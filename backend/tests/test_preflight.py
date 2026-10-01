"""The repository preflight: before any sandbox run or model call, a repository that
clearly isn't a Python project with pytest tests and no packages to install is refused."""

import pytest

from app.preflight import check_supported, dependencies
from app.repository import RepositoryError
from tests.fake_github import SAMPLE_FILES, FakeGitHub
from tests.fake_sandbox import TESTS_PASSED, FakeSandbox
from tests.test_develop import BOTH_PASS, run_once

JAVASCRIPT = {
    "package.json": b'{"name": "x", "scripts": {"test": "jest"}}\n',
    "src/index.js": b"module.exports = 1\n",
    "src/index.test.js": b"test('x', () => {})\n",
}
NO_TESTS = {
    "README.md": b"# tool\n",
    "tool/__init__.py": b"def run():\n    return 1\n",
}


def refused(files: dict[str, bytes]) -> str:
    with pytest.raises(RepositoryError) as caught:
        check_supported(files)
    return caught.value.code


# The rules.


def test_a_python_repository_with_pytest_tests_is_supported() -> None:
    check_supported(SAMPLE_FILES)


@pytest.mark.parametrize(
    "tests",
    [
        {"tests/test_add.py": b""},
        {"pkg/add_test.py": b""},
        {"conftest.py": b"", "checks/run.py": b""},
        # Its own file pattern, in a tests directory pytest is configured for.
        {
            "pytest.ini": b"[pytest]\npython_files = check_*.py\n",
            "tests/check_add.py": b"",
        },
        {"pyproject.toml": b"[tool.pytest.ini_options]\n", "test/check_add.py": b""},
    ],
    ids=["test_-prefix", "_test-suffix", "conftest", "pytest.ini", "pyproject"],
)
def test_any_test_setup_pytest_would_find_is_recognized(
    tests: dict[str, bytes],
) -> None:
    check_supported({"pkg/__init__.py": b"", **tests})


def test_a_repository_without_python_is_refused() -> None:
    assert refused(JAVASCRIPT) == "not_python"


def test_python_without_tests_pytest_would_run_is_refused() -> None:
    assert refused(NO_TESTS) == "no_pytest_tests"
    # A configuration alone isn't tests.
    assert refused({**NO_TESTS, "pytest.ini": b"[pytest]\n"}) == "no_pytest_tests"


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("pyproject.toml", b'[project]\nname = "x"\ndependencies = ["requests>=2"]\n'),
        (
            "pyproject.toml",
            b'[tool.poetry.dependencies]\npython = "^3.12"\nnumpy = "*"\n',
        ),
        ("requirements.txt", b"# runtime\nrequests==2.32.3\n"),
        ("setup.cfg", b"[options]\ninstall_requires =\n    click>=8\n"),
        ("setup.py", b"setup(name='x', install_requires=['attrs', \"six\"])\n"),
    ],
    ids=["pyproject", "poetry", "requirements", "setup.cfg", "setup.py"],
)
def test_declared_packages_to_install_are_refused(path: str, content: bytes) -> None:
    assert refused({**SAMPLE_FILES, path: content}) == "needs_dependencies"


def test_only_packages_that_would_need_installing_count() -> None:
    files = {
        **SAMPLE_FILES,
        "pyproject.toml": b'[project]\nname = "x"\ndependencies = []\n'
        b"[project.optional-dependencies]\ndocs = ['sphinx']\n",
        "requirements.txt": b"-e .\n# nothing else\npytest>=8\n"
        b'typing-extensions; python_version < "3.11"\n',
        "setup.py": b"setup(name='x')\n",
    }

    assert dependencies(files) == []
    check_supported(files)


# Whole runs.


def test_an_unsupported_repository_stops_before_any_test_run_or_model_call() -> None:
    run, github, sandbox, llm = run_once(github=FakeGitHub(files=NO_TESTS))

    assert (run.status, run.error.code, run.error.stage) == (
        "failed",
        "no_pytest_tests",
        "fetching_repository",
    )
    # Fetched once; nothing run, nothing asked, nothing changed, nothing repaired.
    assert len(github.downloaded) == 1
    assert (sandbox.repositories, llm.calls) == ([], [])
    assert (run.existing_tests, run.changes, run.revision_count) == (None, None, 0)
    assert run.verification is None


def test_an_inaccessible_repository_stops_before_the_preflight_and_any_work() -> None:
    run, github, sandbox, llm = run_once(
        github=FakeGitHub(error="repository_not_public")
    )

    assert run.error.code == "repository_not_public"
    assert (github.downloaded, sandbox.repositories, llm.calls) == ([], [], [])


def test_a_supported_repository_goes_on_with_its_real_default_branch() -> None:
    run, _, sandbox, llm = run_once(
        github=FakeGitHub(default_branch="trunk"),
        sandbox=FakeSandbox(repository_result=[TESTS_PASSED, BOTH_PASS]),
    )

    assert (run.status, run.outcome) == ("completed", "ready")
    assert run.repository_ref.default_branch == "trunk"
    assert llm.calls == ["ChangePlan", "CodeChanges", "CriticResult"]
    assert len(sandbox.repositories) == 2
