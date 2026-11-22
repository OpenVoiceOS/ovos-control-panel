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
    # Scan the installed plugins ONCE and reuse it for every skill, instead of
    # importing all skill packages twice per skill (loaded check + settingsmeta).
    plugins = _skill_plugins()
    installed = set(plugins)
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
            "has_meta": find_settingsmeta(child.name, plugins) is not None,
            "loaded": child.name in installed,
        })
    return out


def _skill_plugins() -> dict:
    """Return the installed skill plugins map (id -> class).

    ``find_plugins`` scans entry points and imports every skill package, so it
    is expensive — callers that need it more than once (e.g. ``list_skills``)
    must call this ONCE and thread the result through, not per skill.
    """
    try:
        from ovos_plugin_manager.utils import PluginTypes, find_plugins
        return find_plugins(PluginTypes.SKILL) or {}
    except Exception:  # noqa: BLE001 # pragma: no cover - a broken plugin is not fatal
        return {}


def _installed_skill_ids(plugins: dict | None = None) -> set:
    """Return the skill ids that are installed as plugins."""
    return set(_skill_plugins() if plugins is None else plugins)


def _skill_source_dir(skill_id: str, plugins: dict | None = None) -> Path | None:
    """Return the directory the skill package was installed into."""
    plugins = _skill_plugins() if plugins is None else plugins
    clazz = plugins.get(skill_id)
    if clazz is None:
        return None
    try:
        import inspect
        return Path(inspect.getfile(clazz)).parent
    except (TypeError, OSError):  # pragma: no cover
        return None


def find_settingsmeta(skill_id: str,
                      plugins: dict | None = None) -> dict[str, Any] | None:
    """Return the settingsmeta of ``skill_id``, or ``None``.

    The file is looked for in the skill settings directory first, then in the
    directory the skill package was installed into. ``plugins`` is the
    already-scanned installed-plugins map; pass it to avoid re-importing every
    skill on each call.
    """
    validate_skill_id(skill_id)
    candidates: list[Path] = []
    sdir = skills_root() / skill_id
    candidates += [sdir / "settingsmeta.json", sdir / "settingsmeta.yaml", sdir / "settingsmeta.yml"]
    src = _skill_source_dir(skill_id, plugins)
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
    """Merge ``data`` into the settings of ``skill_id``. Returns changed paths.

    ``settings.json`` is co-owned: the running skill process also writes it
    (OAuth tokens, refresh tokens, first-run flags, counters). The page's data
    is a snapshot taken when the form was opened, so replacing the whole file
    would silently revert any runtime write the skill made in the meantime.
    Instead, read the current file under the write lock and layer the page's
    keys over it, so keys the page never showed are kept. The lock is
    in-process, so this narrows — but cannot fully close — the window against
    the separate skill process; a skill write landing between this read and
    write is still lost. (A key removed in the raw editor is also kept, since a
    merge cannot express deletion; the UI notes this.)
    """
    if not isinstance(data, dict):
        raise SkillSettingsError("settings must be a mapping")
    path = settings_path(skill_id)
    from ovos_webui.fsutils import _WRITE_LOCK

    with _WRITE_LOCK:
        current: dict[str, Any] = {}
        if path.exists():
            try:
                on_disk = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(on_disk, dict):
                    current = on_disk
            except (OSError, ValueError):
                current = {}
        merged = {**current, **data}
        backup = atomic_write(path, json.dumps(merged, indent=2,
                                               ensure_ascii=False))
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


# ── settingsmeta as a form, in the reader's language ──────────────────────────
#: settingsmeta field types and what the form shows for them
_FIELD_TYPES = {"text": "text", "email": "text", "password": "password", "checkbox": "checkbox",
                "number": "number", "select": "select", "label": "note"}


def _options(raw: Any) -> list[tuple[str, str]]:
    """settingsmeta's options: ``"Label|value;Label|value"``, or a list of
    such pairs or of ``{"label", "value"}``."""
    out: list[tuple[str, str]] = []
    items = raw.split(";") if isinstance(raw, str) else raw if isinstance(raw, list) else []
    for item in items:
        if isinstance(item, dict):
            label, value = item.get("label"), item.get("value")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            label, value = item
        elif isinstance(item, str) and item.strip():
            label, _, value = item.partition("|")
            value = value if _ else label
        else:
            continue
        out.append((str(label).strip(), str(value).strip()))
    return out


def settings_form(skill_id: str, lang: str = "en") -> dict[str, Any]:
    """The skill's settingsmeta as a form in ``lang``: its sections with a
    heading and fields, each with a type, a label, a hint and its options.

    The texts come from the skill's own ``locale/<lang>/controlpanel.json`` by
    the field's name (``settings.<field>``, ``settings.<field>.hint``,
    ``settings.<field>.option.<value>``, ``settings.section.<name>``): the
    reader's language, then English, then the text in settingsmeta. So
    settingsmeta stays the plain OVOS standard, and any user interface can
    draw the form it returns."""
    from ovos_webui import described

    validate_skill_id(skill_id)
    meta = settings_meta(skill_id)
    src = _skill_source_dir(skill_id)
    found = described.strings(src) if src is not None else {}
    base = (lang or "en").replace("_", "-").lower().split("-")[0]
    tables = [found.get(base) or {}, found.get("en") or {}]

    def text(key: str, fallback: str | None) -> str | None:
        for table in tables:
            if table.get(key):
                return table[key]
        return fallback

    sections = []
    for s in ((meta or {}).get("skillMetadata") or {}).get("sections") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "")
        fields = []
        for f in s.get("fields") or []:
            if not isinstance(f, dict):
                continue
            kind = _FIELD_TYPES.get(str(f.get("type") or "text"), "text")
            fname = str(f.get("name") or "")
            if kind == "note":
                key = "settings." + fname if fname else None
                label = (text(key, None) if key else None) or str(f.get("label") or "")
                fields.append({"type": "note", "label": label})
                continue
            if not fname:
                continue
            field = {"name": fname, "type": kind,
                     "label": text("settings." + fname, str(f.get("label") or fname)),
                     "hint": text(f"settings.{fname}.hint", None),
                     "default": f.get("value")}
            if kind == "select":
                field["options"] = [{"value": v, "label": text(f"settings.{fname}.option.{v}", label)}
                                    for label, v in _options(f.get("options"))]
            fields.append(field)
        if fields:
            sections.append({"heading": text("settings.section." + name, name) if name else None,
                             "fields": fields})
    return {"sections": sections, "translated": bool(found)}
