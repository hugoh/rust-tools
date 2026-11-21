"""Render the Copier template against each fixture and validate the output.

Run with `mise run render-check`.
"""

import json
import os
import shutil
import subprocess
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import copier
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = sorted((ROOT / "test" / "fixtures").glob("*.yml"))

# Copier clones git HEAD when the template is a git repository, which in a colocated jj
# repo is not the change being edited: render from a plain copy of the working tree.
NOT_COPIED = shutil.ignore_patterns(
    ".git", ".jj", ".cache", ".venv", "__pycache__", "*_cache"
)

# copier.yml _skip_if_exists: written once, then owned by the repo.
SEEDED = [
    "rust-toolchain.toml",
    "deny.toml",
    ".config/mise/conf.d/coverage.toml",
    ".renovaterc.json",
]


@dataclass
class Rendered:
    path: Path
    answers: dict

    def tasks(self) -> Iterator[Path]:
        return (p for p in sorted((self.path / "mise-tasks").rglob("*")) if p.is_file())

    def header(self, task: str, key: str) -> object:
        """The value of a `#MISE key=value` line of a task, parsed as JSON."""
        prefix = f"#MISE {key}="
        for line in (self.path / "mise-tasks" / task).read_text().splitlines():
            if line.startswith(prefix):
                return json.loads(line.removeprefix(prefix))
        raise AssertionError(f"mise-tasks/{task} has no {prefix}")


def render(source: Path, destination: Path, answers: dict) -> None:
    copier.run_copy(
        str(source),
        str(destination),
        data=answers,
        defaults=True,
        overwrite=True,
        quiet=True,
    )


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    copy = tmp_path_factory.mktemp("template") / "src"
    shutil.copytree(ROOT, copy, ignore=NOT_COPIED)
    return copy


@pytest.fixture(scope="module", params=FIXTURES, ids=lambda f: f.stem)
def rendered(
    request: pytest.FixtureRequest,
    source: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Rendered:
    answers = yaml.safe_load(request.param.read_text())
    destination = tmp_path_factory.mktemp(request.param.stem)
    render(source, destination, answers)
    return Rendered(destination, answers)


def test_no_jinja_is_left_unrendered(rendered: Rendered) -> None:
    leftovers = []
    for p in rendered.path.rglob("*"):
        if not p.is_file() or p.suffix == ".pkl" or p.name == ".copier-answers.yml":
            continue
        text = p.read_text(errors="ignore")
        if "[[" in text or "[%" in text:
            leftovers.append(str(p.relative_to(rendered.path)))
    assert leftovers == []


def test_config_files_parse(rendered: Rendered) -> None:
    parsers = {
        ".toml": lambda text: tomllib.loads(text),
        ".json": lambda text: json.loads(text),
        ".yml": lambda text: yaml.safe_load(text),
    }
    checked = 0
    for p in rendered.path.rglob("*"):
        if p.is_file() and p.suffix in parsers:
            parsers[p.suffix](p.read_text())
            checked += 1
    assert checked > 10


def test_mise_tasks_are_runnable(rendered: Rendered) -> None:
    tasks = list(rendered.tasks())
    assert tasks
    for task in tasks:
        name = task.relative_to(rendered.path)
        assert task.stat().st_mode & 0o111, f"{name} is not executable"
        text = task.read_text()
        assert text.startswith("#!/usr/bin/env bash\n"), f"{name} has no bash shebang"
        assert "#MISE description=" in text, f"{name} has no description"
        syntax = subprocess.run(
            ["bash", "-n", str(task)], check=False, capture_output=True, text=True
        )
        assert syntax.returncode == 0, f"{name}: {syntax.stderr}"


def test_prebuild_dependency_follows_has_prebuild(rendered: Rendered) -> None:
    wanted = rendered.answers.get("has_prebuild", False)
    for task in ("build", "dev", "coverage", "lint/rust", "test/_default"):
        depends = rendered.header(task, "depends")
        assert isinstance(depends, list)
        assert ("prebuild" in depends) == wanted, f"{task}: {depends}"


def test_repo_specific_tasks_are_chained(rendered: Rendered) -> None:
    answers = rendered.answers
    assert rendered.header("ci/test", "depends") == [
        "coverage",
        "crap",
        *answers.get("ci_test_extra_depends", []),
    ]
    assert rendered.header("lint/_default", "depends") == [
        "lint:rust",
        "lint:release",
        *answers.get("lint_extra_depends", []),
    ]
    assert rendered.header("build", "sources") == [
        "src/**/*.rs",
        "Cargo.toml",
        "Cargo.lock",
        *answers.get("build_extra_sources", []),
    ]


def test_the_binary_is_named_after_the_project(rendered: Rendered) -> None:
    name = rendered.answers["project_name"]
    assert rendered.header("build", "outputs") == [f"target/release/{name}"]


def test_seeded_files_are_not_overwritten_but_managed_files_are(
    rendered: Rendered, source: Path
) -> None:
    for name in SEEDED:
        (rendered.path / name).write_text("owned by the repo\n")
    managed = rendered.path / "clippy.toml"
    original = managed.read_text()
    managed.write_text("edited\n")
    render(source, rendered.path, rendered.answers)
    assert managed.read_text() == original
    for name in SEEDED:
        assert (rendered.path / name).read_text() == "owned by the repo\n", name


def run_lint_release(
    rendered: Rendered, tmp_path: Path, anodizer_yaml: str
) -> subprocess.CompletedProcess[str]:
    stubs = tmp_path / "bin"
    stubs.mkdir()
    stub = stubs / "anodizer"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    stub.chmod(0o755)
    (tmp_path / ".anodizer.yaml").write_text(anodizer_yaml)
    return subprocess.run(
        [
            "mise",
            "x",
            "yq@4.54.2",
            "--",
            "env",
            f"PATH={stubs}:{os.environ['PATH']}",
            "bash",
            str(rendered.path / "mise-tasks" / "lint" / "release"),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )


CLOUDSMITH = """cloudsmiths:
  - organization: hugoh-oss
    repository: {repository}
{extra}"""


@pytest.mark.skipif(shutil.which("mise") is None, reason="mise is not installed")
class TestCloudsmithRetention:
    def test_a_cloudsmith_entry_without_keep_versions_fails(
        self, rendered: Rendered, tmp_path: Path
    ) -> None:
        result = run_lint_release(
            rendered, tmp_path, CLOUDSMITH.format(repository="upd", extra="")
        )
        assert result.returncode != 0
        assert "keep_versions" in result.stderr
        assert "upd" in result.stderr

    def test_a_cloudsmith_entry_with_keep_versions_passes(
        self, rendered: Rendered, tmp_path: Path
    ) -> None:
        result = run_lint_release(
            rendered,
            tmp_path,
            CLOUDSMITH.format(repository="upd", extra="    keep_versions: 2\n"),
        )
        assert result.returncode == 0, result.stderr

    def test_a_config_without_cloudsmith_passes(
        self, rendered: Rendered, tmp_path: Path
    ) -> None:
        result = run_lint_release(rendered, tmp_path, "project_name: x\n")
        assert result.returncode == 0, result.stderr


SHELL_LINTERS = [
    ["shfmt", "-d", "--apply-ignore"],
    ["shellharden", "--check"],
    ["shellcheck"],
]


@pytest.mark.parametrize("linter", SHELL_LINTERS, ids=lambda cmd: cmd[0])
def test_mise_tasks_pass_the_shell_linters(
    rendered: Rendered, linter: list[str]
) -> None:
    if shutil.which(linter[0]) is None:
        pytest.skip(f"{linter[0]} is not installed")
    tasks = [str(task) for task in rendered.tasks()]
    result = subprocess.run(
        [*linter, *tasks],
        cwd=rendered.path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
