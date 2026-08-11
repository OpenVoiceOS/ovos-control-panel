"""Translate skill resources into a language, at the user level.

The installed skill package is never touched. The translated files go to the
user override directory that ovos-workshop already reads first:

    <XDG data>/<base>/resources/<skill_id>/<lang>/<file>

The code path, in ``ovos-workshop``:

- ``ResourceType.locate_user_directory`` (``ovos_workshop/resource_files.py``
  line 183) sets ``user_directory`` to
  ``Path(get_xdg_data_save_path(), "resources", skill_id)`` when it exists.
- ``SkillResources._define_resource_types`` (line 617) calls that for every
  resource type.
- ``ResourceFile._locate`` (lines 296-300) walks ``user_directory`` **before**
  the skill's own directory, with the comment "first check for user defined
  resource files ... usually these resources are overrides to customize
  dialogs or provide additional languages". The directory is walked
  recursively, so a per-language subdirectory works.

So this is an override, not a fork, and it survives a skill upgrade.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ovos_utils.log import LOG

from ovos_webui.fsutils import atomic_write, is_within, validate_skill_id

#: The resource files a user can usefully translate.
TRANSLATABLE_SUFFIXES = {".dialog", ".intent", ".voc", ".word", ".list", ".value",
                         ".template"}

#: A language tag and nothing else.
LANG_RE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$")

#: Refuse a resource file larger than this.
MAX_RESOURCE_BYTES = 256 * 1024

#: Refuse to translate more lines than this in one request.
MAX_LINES = 500


class TranslateError(ValueError):
    """Raised when a translation request cannot be served."""


def validate_lang(lang: str) -> str:
    """Return ``lang`` when it is a language tag, else raise."""
    if not isinstance(lang, str) or not LANG_RE.match(lang):
        raise TranslateError("that is not a language code, for example pt-pt")
    return lang


def user_resources_root() -> Path:
    """Return the directory that holds the user overrides."""
    from ovos_config.locations import get_xdg_data_save_path

    return Path(get_xdg_data_save_path()) / "resources"


def override_path(skill_id: str, lang: str, file_name: str) -> Path:
    """Return the user override path of one resource file."""
    validate_skill_id(skill_id)
    validate_lang(lang)
    validate_resource_name(file_name)
    root = user_resources_root()
    path = root / skill_id / lang.lower() / file_name
    if not is_within(root, path.parent):
        raise TranslateError("the resolved path is outside the resources directory")
    return path


def validate_resource_name(name: str) -> str:
    """Return ``name`` when it is a plain resource file name, else raise."""
    if not isinstance(name, str) or not name:
        raise TranslateError("the file name is empty")
    if "/" in name or "\\" in name or "\x00" in name:
        raise TranslateError("the file name holds a path separator")
    if name.startswith(".") or name in (".", ".."):
        raise TranslateError("the file name starts with a dot")
    if len(name) > 128:
        raise TranslateError("the file name is too long")
    if Path(name).suffix not in TRANSLATABLE_SUFFIXES:
        raise TranslateError(
            f"'{Path(name).suffix or name}' is not a resource file this page translates")
    return name


def _skill_directory(skill_id: str) -> Path | None:
    """Return the directory the installed skill package lives in."""
    validate_skill_id(skill_id)
    try:
        from ovos_plugin_manager.utils import PluginTypes, find_plugins
        plugins = find_plugins(PluginTypes.SKILL) or {}
    except Exception as err:  # noqa: BLE001
        LOG.warning(f"could not list skill plugins: {err}")
        return None
    clazz = plugins.get(skill_id)
    if clazz is None:
        return None
    try:
        import inspect
        return Path(inspect.getfile(clazz)).parent
    except (TypeError, OSError):  # pragma: no cover
        return None


def list_skills() -> list[dict[str, Any]]:
    """Return the installed skills whose resources can be read."""
    out = []
    try:
        from ovos_plugin_manager.utils import PluginTypes, find_plugins
        plugins = find_plugins(PluginTypes.SKILL) or {}
    except Exception as err:  # noqa: BLE001
        LOG.warning(f"could not list skill plugins: {err}")
        plugins = {}
    for skill_id in sorted(plugins):
        try:
            validate_skill_id(skill_id)
        except ValueError:
            continue
        directory = _skill_directory(skill_id)
        out.append({"skill_id": skill_id, "has_source": directory is not None})
    return out


def source_languages(skill_id: str) -> list[str]:
    """Return the languages the installed skill ships resources for."""
    directory = _skill_directory(skill_id)
    if directory is None:
        return []
    langs = set()
    for locale in ("locale", "dialog", "vocab", "regex"):
        base = directory / locale
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and LANG_RE.match(child.name):
                langs.add(child.name.lower())
    return sorted(langs)


def list_resources(skill_id: str, lang: str) -> list[dict[str, Any]]:
    """Return the resource files the skill ships for ``lang``."""
    validate_lang(lang)
    directory = _skill_directory(skill_id)
    if directory is None:
        return []
    seen: dict[str, Path] = {}
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix not in TRANSLATABLE_SUFFIXES:
            continue
        parts = [p.lower() for p in path.parts]
        if lang.lower() not in parts:
            continue
        seen.setdefault(path.name, path)
    out = []
    for name, path in sorted(seen.items()):
        try:
            target = override_path(skill_id, lang, name)
            has_override = target.is_file()
        except TranslateError:
            continue
        out.append({"file": name, "source": str(path), "translated": has_override})
    return out


def read_source(skill_id: str, lang: str, file_name: str) -> list[str]:
    """Return the lines of a shipped resource file."""
    validate_resource_name(file_name)
    directory = _skill_directory(skill_id)
    if directory is None:
        raise LookupError(f"the skill {skill_id} is not installed")
    for path in directory.rglob(file_name):
        if not path.is_file():
            continue
        if lang.lower() not in [p.lower() for p in path.parts]:
            continue
        if path.stat().st_size > MAX_RESOURCE_BYTES:
            raise TranslateError("that resource file is too large")
        return path.read_text(encoding="utf-8").splitlines()
    raise LookupError(f"{file_name} was not found for {lang}")


def read_override(skill_id: str, lang: str, file_name: str) -> list[str] | None:
    """Return the lines of the user override, or ``None`` when there is none."""
    path = override_path(skill_id, lang, file_name)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").splitlines()


def write_override(skill_id: str, lang: str, file_name: str,
                   lines: list[str]) -> dict[str, Any]:
    """Write the accepted translation as a user override."""
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise TranslateError("the translation must be a list of lines")
    if len(lines) > MAX_LINES:
        raise TranslateError("that is too many lines")
    body = "\n".join(line.rstrip("\n") for line in lines)
    if len(body.encode("utf-8")) > MAX_RESOURCE_BYTES:
        raise TranslateError("the translation is too large")
    path = override_path(skill_id, lang, file_name)
    backup = atomic_write(path, body + "\n")
    return {"path": str(path), "backup": str(backup) if backup else None}


def delete_override(skill_id: str, lang: str, file_name: str) -> dict[str, Any]:
    """Remove a user override, so the shipped resource applies again."""
    from ovos_webui.fsutils import make_backup

    path = override_path(skill_id, lang, file_name)
    if not path.is_file():
        raise LookupError("there is no translation to remove")
    backup = make_backup(path)
    path.unlink()
    return {"deleted": str(path), "backup": str(backup) if backup else None}


# ── translation plugins ──────────────────────────────────────────────────────
def translation_plugins() -> list[str]:
    """Return the translation plugins installed on this device."""
    try:
        from ovos_plugin_manager.utils import PluginTypes, find_plugins
        return sorted(find_plugins(PluginTypes.TRANSLATE) or {})
    except Exception as err:  # noqa: BLE001
        LOG.warning(f"could not list translation plugins: {err}")
        return []


def _load_translator(plugin: str):
    from ovos_plugin_manager.utils import PluginTypes, find_plugins

    plugins = find_plugins(PluginTypes.TRANSLATE) or {}
    clazz = plugins.get(plugin)
    if clazz is None:
        raise TranslateError(f"the translation plugin '{plugin}' is not installed")
    return clazz()


def machine_translate(lines: list[str], source: str, target: str,
                      plugin: str | None = None) -> dict[str, Any]:
    """Translate lines with an installed plugin.

    The result is a draft. The page marks every line as a draft until a person
    accepts it, and only accepted lines are written.
    """
    validate_lang(source)
    validate_lang(target)
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise TranslateError("send a list of lines")
    if len(lines) > MAX_LINES:
        raise TranslateError("that is too many lines")
    available = translation_plugins()
    if not available:
        raise TranslateError(
            "no translation plugin is installed. Install one from the Plugins page, "
            "for example a plugin whose name starts with ovos-translate-plugin-.")
    plugin = plugin or available[0]
    if plugin not in available:
        raise TranslateError(f"the translation plugin '{plugin}' is not installed")
    translator = _load_translator(plugin)
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            # Keep comments and blank lines as they are.
            out.append({"source": line, "draft": line, "machine": False})
            continue
        try:
            draft = translator.translate(line, target=target, source=source)
        except Exception as err:  # noqa: BLE001 - a plugin can fail on one line
            LOG.warning(f"translation failed for a line: {err}")
            out.append({"source": line, "draft": line, "machine": False,
                        "error": str(err)})
            continue
        out.append({"source": line, "draft": draft or line, "machine": True})
    return {"plugin": plugin, "lines": out}
