"""The Setup guide: which steps it has, in which order.

The guide on the Setup page is a list of steps. Without configuration it is
the panel's own six, in the order they have always had. A distribution can
choose its own in ``webui.setup``, as it chooses its menu and its look::

    {"webui": {"setup": {
        "steps": ["language", "voice", "emkay-home", "speak", "tryit"],
        "intro": "emkay-home.setup.intro"
    }}}

- The panel's own steps are named by their ids (``STEPS``).
- Any other id is a page described in ``controlpanel.json``: its blocks are
  drawn right in the guide, under its heading, with the same checks and the
  same messages as on the page itself. So a distribution's own step is a page
  it already has, and no code of its runs in the panel.
- ``intro`` is a label (a key in one of the pages' strings, or
  ``{"key", "label"}`` with its English text) for the line at the top.

A step that cannot be shown (an id nobody knows, a page that is turned off,
a page the panel draws from Python) is left out and named in ``problems``, which
the About page lists with the other settings it could not use.
"""
from __future__ import annotations

from typing import Any

#: The panel's own steps, in the order of the guide it has always had.
STEPS = ("token", "language", "voice", "speak", "tryit", "wake")

#: The most steps a guide has; past this it is not a short guide any more.
MAX_STEPS = 12


def _intro(raw: Any, english: dict[str, str]) -> tuple[dict[str, str] | None, str | None]:
    """The intro label, or a problem."""
    if raw is None:
        return None, None
    if isinstance(raw, str) and raw.strip():
        key = raw.strip()
        return {"key": key, "label": english.get(key, "")}, None
    if isinstance(raw, dict) and isinstance(raw.get("key"), str) and raw["key"].strip():
        label = raw.get("label") if isinstance(raw.get("label"), str) else ""
        return {"key": raw["key"].strip(), "label": label or english.get(raw["key"].strip(), "")}, None
    return None, "webui.setup.intro: needs a label (a key, or {\"key\", \"label\"})"


def guide(setup: Any, registry: Any, disabled: frozenset | set = frozenset()) -> dict[str, Any]:
    """The guide as the Setup page draws it.

    ``setup`` is the ``webui.setup`` section, ``registry`` the page registry
    and ``disabled`` the pages turned off (``webui.pages.disabled``).
    Returns ``{"steps": [...], "intro": label or None, "custom": bool,
    "problems": [...]}``; each step is ``{"id"}`` for one of the panel's own,
    or ``{"id", "page", "heading", "heading_key"}`` for a described page.
    """
    problems: list[str] = []
    if setup is not None and not isinstance(setup, dict):
        problems.append("webui.setup: not a mapping")
    setup = setup if isinstance(setup, dict) else {}
    raw = setup.get("steps")
    custom = raw is not None
    if raw is None:
        wanted = list(STEPS)
    elif isinstance(raw, list) and all(isinstance(s, str) for s in raw):
        wanted = raw
    else:
        problems.append("webui.setup.steps: a list of step ids")
        wanted, custom = list(STEPS), False
    by_id = registry.by_id()
    steps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sid in wanted:
        if sid in seen:
            problems.append(f"webui.setup.steps: {sid} is named twice; the first counts")
            continue
        seen.add(sid)
        if len(steps) >= MAX_STEPS:
            problems.append(f"webui.setup.steps: at most {MAX_STEPS} steps; {sid} and the rest are left out")
            break
        if sid in STEPS:
            steps.append({"id": sid})
            continue
        page = by_id.get(sid)
        if page is None:
            problems.append(f"webui.setup.steps: no step or page {sid}")
        elif sid in disabled:
            problems.append(f"webui.setup.steps: the page {sid} is turned off")
        elif page.described is None:
            problems.append(f"webui.setup.steps: {sid} is not a described page, so it cannot be a step")
        else:
            steps.append({"id": sid, "page": page.described,
                          "heading": page.heading, "heading_key": page.heading_key})
    if custom and not steps:
        problems.append("webui.setup.steps: none of the steps can be shown, so the guide is the panel's own")
        steps, custom = [{"id": s} for s in STEPS], False
    english = registry.strings("en", {}) if hasattr(registry, "strings") else {}
    intro, problem = _intro(setup.get("intro"), english)
    if problem:
        problems.append(problem)
    return {"steps": steps, "intro": intro, "custom": custom, "problems": problems}
