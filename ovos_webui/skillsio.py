"""Find installed skills and edit their settings.

A skill keeps its settings in ``<xdg config>/skills/<skill_id>/settings.json``.
This is the same place that ovos-workshop uses, so an edit here is what the
skill reads. A skill can also ship a ``settingsmeta.json`` or
``settingsmeta.yaml`` in its own directory. That file describes the fields, so
the UI can show a form instead of raw JSON.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ovos_webui.fsutils import atomic_write, is_within, validate_skill_id


class SkillSettingsError(ValueError):
    """Raised when settings text is not usable."""


def skills_root() -> Path:
    """Return the directory that holds every skill settings directory."""
    from ovos_config.locations import get_xdg_config_save_path

    return Path(get_xdg_config_save_path()) / "skills"


def settings_path(skill_id: str) -> Path:
    """Return the settings file path of ``skill_id``.

    The skill id is checked first, and the result is checked again against the
    skills directory. A path that escapes the directory is refused.
    """
    validate_skill_id(skill_id)
    root = skills_root()
    path = root / skill_id / "settings.json"
    if not is_within(root, path.parent):
        raise SkillSettingsError("the resolved path is outside the skills directory")
    return path


def list_skills() -> list[dict[str, Any]]:
    """Return one entry per installed skill, sorted by skill id."""
    root = skills_root()
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            validate_skill_id(child.name)
        except ValueError:
            continue
        settings = child / "settings.json"
        out.append({
            "skill_id": child.name,
            "has_settings": settings.is_file(),
            "has_meta": find_settingsmeta(child.name) is not None,
            "loaded": child.name in _installed_skill_ids(),
        })
    return out


def _installed_skill_ids() -> set:
    """Return the skill ids that are installed as plugins."""
    try:
        from ovos_plugin_manager.utils import PluginTypes, find_plugins
        return set(find_plugins(PluginTypes.SKILL) or {})
    except Exception:  # noqa: BLE001 # pragma: no cover - a broken plugin is not fatal
        return set()


def _skill_source_dir(skill_id: str) -> Path | None:
    """Return the directory the skill package was installed into."""
    try:
        from ovos_plugin_manager.utils import PluginTypes, find_plugins
        plugins = find_plugins(PluginTypes.SKILL) or {}
    except Exception:  # noqa: BLE001 # pragma: no cover
        return None
    clazz = plugins.get(skill_id)
    if clazz is None:
        return None
    try:
        import inspect
        return Path(inspect.getfile(clazz)).parent
    except (TypeError, OSError):  # pragma: no cover
        return None


def find_settingsmeta(skill_id: str) -> dict[str, Any] | None:
    """Return the settingsmeta of ``skill_id``, or ``None``.

    The file is looked for in the skill settings directory first, then in the
    directory the skill package was installed into.
    """
    validate_skill_id(skill_id)
    candidates: list[Path] = []
    sdir = skills_root() / skill_id
    candidates += [sdir / "settingsmeta.json", sdir / "settingsmeta.yaml", sdir / "settingsmeta.yml"]
    src = _skill_source_dir(skill_id)
    if src is not None:
        candidates += [src / "settingsmeta.json", src / "settingsmeta.yaml", src / "settingsmeta.yml"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and data.get("skillMetadata"):
            return data
    return None


def read_settings(skill_id: str) -> dict[str, Any]:
    """Return the settings of ``skill_id``. Missing files read as empty."""
    path = settings_path(skill_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise SkillSettingsError(f"settings.json is not valid JSON: {err}") from err
    if not isinstance(data, dict):
        raise SkillSettingsError("settings.json must hold a mapping")
    return data


def settings_meta(skill_id: str) -> dict[str, Any]:
    """Return a settingsmeta for ``skill_id``, generated if the skill has none.

    ``ovos_workshop.settings.settings2meta`` builds the fallback, so the form
    matches what other OVOS tools show.
    """
    meta = find_settingsmeta(skill_id)
    if meta is not None:
        return meta
    settings = read_settings(skill_id)
    try:
        from ovos_workshop.settings import settings2meta
        return settings2meta(settings, skill_id)
    except ImportError:  # pragma: no cover - ovos-workshop is optional
        return {"skillMetadata": {"sections": []}}


def write_settings(skill_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Replace the settings of ``skill_id``. Returns the paths that changed."""
    if not isinstance(data, dict):
        raise SkillSettingsError("settings must be a mapping")
    path = settings_path(skill_id)
    backup = atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))
    return {"path": str(path), "backup": str(backup) if backup else None}


def parse_settings_text(text: str) -> dict[str, Any]:
    """Parse settings JSON text and check it is a mapping."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise SkillSettingsError(str(err)) from err
    if not isinstance(data, dict):
        raise SkillSettingsError("settings must be a mapping")
    return data
