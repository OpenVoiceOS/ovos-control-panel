"""What the device can do: the skills installed on it.

A plain-language list of every installed skill with the one-line description
from its own package metadata, so a household user can see what the device
knows how to do without reading package names. The data is read locally from
installed distribution metadata and the skill settings directory — no network,
no new bus message.
"""
from __future__ import annotations

import re
from typing import Any


def _pretty(name: str) -> str:
    base = re.split(r"[.@]", name)[0]
    base = re.sub(r"^(ovos|neon|mycroft)[-_]", "", base)
    base = re.sub(r"^skill[-_]", "", base)
    base = re.sub(r"[-_]", " ", base).strip()
    return base.title() or name


def _is_skill_package(name: str, dist=None) -> bool:
    """A skill package: ``ovos-skill-*`` by its name; any other skill-looking
    name (``skill-*``, ``*-skill-*``) only if it registers a skill or depends
    on OVOS, because most packages called that are something else."""
    from ovos_webui.pypi import classify

    if name.startswith("ovos-skill-"):
        return True
    if classify(name) != "skill" and "-skill-" not in name:
        return False
    if dist is None:
        return True
    from ovos_webui.skillinfo import installed_is_ovos_skill
    return installed_is_ovos_skill(dist)


def _summaries() -> dict[str, str]:
    """Map installed skill distribution name -> its one-line Summary."""
    from importlib.metadata import distributions

    out: dict[str, str] = {}
    for dist in distributions():
        try:
            name = (dist.metadata["Name"] or "").lower().replace("_", "-")
        except (KeyError, TypeError):  # pragma: no cover - broken metadata
            continue
        if _is_skill_package(name, dist):
            summary = ""
            try:
                summary = dist.metadata["Summary"] or ""
            except (KeyError, TypeError):  # pragma: no cover
                summary = ""
            out[name] = summary.strip()
    return out


def list_capabilities() -> dict[str, Any]:
    """Return the installed skills, each with a name, description and id.

    ``skill_id`` is set for a skill that has a settings directory (its
    settings and its on/off switch work by that id). ``package`` is the
    installed distribution, when it can be told, so the skill can be updated
    or removed; a skill whose package cannot be told has ``None``.
    """
    from ovos_webui import skillsio

    summaries = _summaries()
    seen = set()
    skills = []

    # Skills that have a settings directory carry a full skill_id.
    try:
        for entry in skillsio.list_skills():
            sid = entry.get("skill_id") if isinstance(entry, dict) else str(entry)
            if not sid or sid in seen:
                continue
            seen.add(sid)
            dist = sid.split(".")[0].replace("_", "-").lower()
            skills.append({
                "id": sid,
                "skill_id": sid,
                "package": dist if dist in summaries else None,
                "name": _pretty(sid),
                "description": summaries.get(dist, ""),
                "configurable": True,
            })
    except Exception:  # pragma: no cover - skills dir unreadable
        pass

    # Installed skill packages that have no settings directory still count as
    # abilities the device has.
    for dist, summary in sorted(summaries.items()):
        if any(dist == s["id"].split(".")[0].replace("_", "-").lower()
               for s in skills):
            continue
        skills.append({
            "id": dist,
            "skill_id": None,
            "package": dist,
            "name": _pretty(dist),
            "description": summary,
            "configurable": False,
        })

    skills.sort(key=lambda s: s["name"].lower())
    return {"skills": skills, "count": len(skills)}
