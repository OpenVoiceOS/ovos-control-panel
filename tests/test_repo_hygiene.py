"""Nothing that belongs to a working copy may be committed.

A virtualenv, a cache directory or a build artefact in the tree is noise at
best and, when it is a symlink into somebody's home directory, a broken
checkout for everyone else. `.gitignore` covers the directory forms; a symlink
named `.venv` is not a directory and slips past a pattern written with a
trailing slash, so the tree itself is checked here.
"""
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: Names that only ever exist in a working copy.
NEVER_COMMITTED = {".venv", "venv", ".env", "__pycache__", ".pytest_cache",
                   ".ruff_cache", ".coverage", "htmlcov", "build", "dist"}


def _tracked():
    """Every path git has staged, with its mode.

    The index rather than HEAD, so a stray file is caught when it is added
    rather than one commit too late. In a fresh checkout the two agree, so CI
    sees the same thing.
    """
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         cwd=REPO, capture_output=True, text=True, check=True)
    if Path(top.stdout.strip()).resolve() != REPO:
        # Vendored inside somebody else's checkout: their index is not ours.
        raise FileNotFoundError(f"{REPO} is not the root of its git repository")
    out = subprocess.run(["git", "ls-files", "--stage"],
                         cwd=REPO, capture_output=True, text=True, check=True)
    for line in out.stdout.splitlines():
        meta, path = line.split("\t", 1)
        yield meta.split()[0], path


@pytest.fixture(scope="module")
def tracked():
    """The staged files, or a skip when there is no checkout to read.

    A source tarball has no `.git`, and this check is about what reaches the
    repository, which such a copy cannot answer for.
    """
    try:
        return list(_tracked())
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        pytest.skip(f"not a git checkout, nothing to check: {err}")


def test_no_symlinks_are_committed(tracked):
    """Mode 120000 is a symlink. One pointing outside the repo breaks clones."""
    links = [path for mode, path in tracked if mode == "120000"]
    assert not links, f"symlinks are committed: {links}"


def test_no_working_copy_directories_are_committed(tracked):
    strays = sorted({
        path for _mode, path in tracked
        if any(part in NEVER_COMMITTED for part in Path(path).parts)
    })
    assert not strays, f"these belong to a working copy, not the repo: {strays}"


def test_no_compiled_or_packaging_leftovers_are_committed(tracked):
    strays = sorted(
        path for _mode, path in tracked
        if path.endswith((".pyc", ".pyo", ".egg-info", ".orig", ".rej"))
        or ".egg-info/" in path
    )
    assert not strays, f"build leftovers are committed: {strays}"


def test_the_constraints_file_covers_every_declared_dependency():
    """`constraints.txt` must not go stale against `pyproject.toml`.

    It records one resolution of the dependency tree at the newest versions the
    floors allow. A direct dependency missing from it means the file was not
    regenerated after `pyproject.toml` changed, and anyone installing with it
    would silently get a different set from the one it claims to describe.
    """
    import re
    from importlib.metadata import requires

    # The installed distribution's metadata, rather than parsing pyproject:
    # tomllib arrived in 3.11 and this package supports 3.10.
    declared = requires("ovos-control-panel") or []

    pinned = {
        line.split("==")[0].strip().lower().replace("_", "-")
        for line in (REPO / "constraints.txt").read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.startswith("#")
    }
    names = {re.split(r"[<>=!\[; ]", spec, 1)[0].strip().lower().replace("_", "-")
             for spec in declared}
    missing = sorted(n for n in names if n and n not in pinned)
    assert not missing, (
        f"constraints.txt does not pin {missing}; regenerate it with "
        "`uv pip compile --prerelease=allow --extra dev pyproject.toml -o constraints.txt`"
    )
