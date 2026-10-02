"""R20.2 — `dossier`'s version is derived from git when it is installed, and
never written by hand.

`dossier_version` is in every manifest and record (R4.9, R11.19), and said
`0.1.0` for every commit since the first. `hatch-vcs` now derives it from git
when an install is built. Two halves here. The configuration that makes it so
is read in the default suite: nothing names a number, the install is rebuilt
when the commit moves, and CI has the history the count is made from. The
versions themselves are measured as an install makes them, by building a wheel
from a clone of this repository with `uv build`. That needs `uv`, and the
network for the build's own requirements, so it is `live` and run deliberately.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
# A commit in a clone needs a name; this one is no person's.
GIT = ["git", "-c", "user.name=dossier tests", "-c", "user.email=tests@example.invalid"]


def _toml(name: str) -> dict:
    return tomllib.loads((ROOT / name).read_text(encoding="utf-8"))


class TestNoVersionIsWrittenByHand:
    """R20.2 rows 6 and 7 — the configuration rows 1 to 5 rest on."""

    def test_neither_pyproject_nor_the_lock_names_a_version(self):
        """Row 7, counter-example — the one where there is no number left to forget."""
        project = _toml("pyproject.toml")
        packages = _toml("uv.lock")["package"]
        (own,) = [package for package in packages if package["name"] == "dossier"]

        assert "version" not in project["project"]
        assert "version" in project["project"]["dynamic"]
        assert project["tool"]["hatch"]["version"] == {"source": "vcs"}
        assert "hatch-vcs" in project["build-system"]["requires"]
        assert "version" not in own

    def test_a_new_commit_rebuilds_the_install(self):
        """Row 6, counter-example — the one where the commit moved after `uv sync`."""
        keys = _toml("pyproject.toml")["tool"]["uv"]["cache-keys"]

        assert {"git": {"commit": True, "tags": True}} in keys
        # Named again because a `cache-keys` list replaces uv's default, which
        # is this file: without it, a changed dependency would not rebuild.
        assert {"file": "pyproject.toml"} in keys

    def test_ci_checks_out_the_whole_history(self):
        """Rows 2 and 4 — the one where the count is made from a checkout of one commit."""
        ci = ROOT / ".github" / "workflows" / "ci.yml"
        workflow = yaml.safe_load(ci.read_text(encoding="utf-8"))
        checkouts = [
            step
            for job in workflow["jobs"].values()
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/checkout")
        ]

        assert checkouts
        assert all(step.get("with", {}).get("fetch-depth") == 0 for step in checkouts)


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=_environ())


def _environ() -> dict[str, str]:
    """This environment, without a version anyone pretended (row 5's variable)."""
    return {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("SETUPTOOLS_SCM_PRETEND_VERSION", "VCS_VERSIONING_PRETEND"))
    }


def _git(clone: Path, *args: str) -> str:
    done = _run(*GIT, *args, cwd=clone)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _built(source: Path, out: Path) -> str:
    """The version `uv build` gives the wheel it builds from `source`."""
    shutil.rmtree(out, ignore_errors=True)
    done = _run("uv", "build", "--wheel", "--out-dir", str(out), cwd=source)
    assert done.returncode == 0, done.stdout + done.stderr
    (wheel,) = out.glob("*.whl")
    return wheel.name.split("-")[1]


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """This repository, untagged, with this checkout's `pyproject.toml` committed on top."""
    if shutil.which("uv") is None:
        pytest.skip("uv builds the wheel, and is not on PATH")
    clone = tmp_path / "clone"
    done = _run("git", "clone", "-q", "--no-hardlinks", str(ROOT), str(clone), cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    for tag in _git(clone, "tag", "--list").split():
        _git(clone, "tag", "-d", tag)
    shutil.copy(ROOT / "pyproject.toml", clone / "pyproject.toml")
    _git(clone, "commit", "-q", "--allow-empty", "-am", "this checkout's pyproject.toml")
    return clone


@pytest.mark.live
class TestTheVersionAnInstallIsBuiltWith:
    """R20.2 rows 1 to 5 — measured by building a wheel, as an install does."""

    def test_a_tagged_commit_is_its_tag(self, clone: Path, tmp_path: Path):
        """Row 1 — the one installed from the commit tagged `v0.2.0`."""
        _git(clone, "tag", "v0.2.0")

        assert _built(clone, tmp_path / "dist") == "0.2.0"

    def test_three_commits_past_a_tag_name_the_commit(self, clone: Path, tmp_path: Path):
        """Row 2 — the one installed three commits past `v0.2.0`."""
        _git(clone, "tag", "v0.2.0")
        for _ in range(3):
            _git(clone, "commit", "-q", "--allow-empty", "-m", "past the tag")
        head = _git(clone, "rev-parse", "HEAD")

        version = _built(clone, tmp_path / "dist")

        found = re.fullmatch(r"0\.2\.1\.dev3\+g([0-9a-f]{7,})", version)
        assert found, version
        assert head.startswith(found.group(1))

    def test_uncommitted_changes_add_the_date(self, clone: Path, tmp_path: Path):
        """Row 3 — the one three commits past `v0.2.0`, with changes no commit holds."""
        _git(clone, "tag", "v0.2.0")
        for _ in range(3):
            _git(clone, "commit", "-q", "--allow-empty", "-m", "past the tag")
        (clone / "README.md").write_text("changed\n", encoding="utf-8")

        version = _built(clone, tmp_path / "dist")

        assert re.fullmatch(r"0\.2\.1\.dev3\+g[0-9a-f]{7,}\.d\d{8}", version), version

    def test_no_tag_counts_every_commit(self, clone: Path, tmp_path: Path):
        """Row 4 — the one with no tag yet, as on 2026-10-02."""
        count = _git(clone, "rev-list", "--count", "HEAD")
        head = _git(clone, "rev-parse", "HEAD")

        version = _built(clone, tmp_path / "dist")

        found = re.fullmatch(rf"0\.1\.dev{count}\+g([0-9a-f]{{7,}})", version)
        assert found, version
        assert head.startswith(found.group(1))

    def test_a_source_with_no_history_refuses_to_build(self, tmp_path: Path):
        """Row 5, counter-example — the one copied without `.git`, as GitHub's zip is."""
        if shutil.which("uv") is None:
            pytest.skip("uv builds the wheel, and is not on PATH")
        source = tmp_path / "source"
        source.mkdir()
        for name in ("pyproject.toml", "README.md"):
            shutil.copy(ROOT / name, source / name)
        caches = shutil.ignore_patterns("__pycache__")
        shutil.copytree(ROOT / "src", source / "src", ignore=caches)

        done = _run("uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist"), cwd=source)

        assert done.returncode != 0
        assert "SETUPTOOLS_SCM_PRETEND_VERSION" in done.stdout + done.stderr
        assert not (tmp_path / "dist").exists() or not list((tmp_path / "dist").glob("*.whl"))
