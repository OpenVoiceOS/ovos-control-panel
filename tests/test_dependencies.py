"""Every library the panel imports is one it says it needs, so a clean
install (a python:slim image, say) starts."""
import ast
import sys
from pathlib import Path

import ovos_webui

ROOT = Path(ovos_webui.__file__).parent
#: import name -> the distribution that brings it, where they differ
DIST = {"yaml": "PyYAML", "multipart": "python-multipart", "ovos_spec_tools": "ovos-spec-tools"}
#: what comes with a declared dependency: pydantic with fastapi
COMES_WITH = {"pydantic"}


def imported():
    names = set()
    for f in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
    return names


def test_every_library_imported_is_a_dependency():
    import tomllib
    deps = tomllib.loads((ROOT.parent / "pyproject.toml").read_text())["project"]["dependencies"]
    declared = {d.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower().replace("_", "-")
                for d in deps}
    third = {n for n in imported() if n not in sys.stdlib_module_names and n != "ovos_webui"}
    # an OpenVoiceOS package the panel only uses where the device has it
    # (ovos_persona) is imported inside a try, and is not counted here
    missing = sorted(n for n in third - COMES_WITH
                     if DIST.get(n, n).lower().replace("_", "-") not in declared and not n.startswith("ovos_"))
    assert not missing, f"imported but not in pyproject's dependencies: {missing}"
