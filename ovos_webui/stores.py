"""Stores: lists of skills and plugins someone has checked for a device.

A store is a URL to a JSON list of packages, set in ``webui.stores`` (a list
of ``{"name": ..., "url": ...}``) on the Control panel page. The panel has
none of its own: a distribution sets its store (Emkay sets the Emkay store),
and anyone can add one. Two formats are read, told apart by their records,
the same two that ovos-skill-store reads:

- the Emkay store's: ``package``, ``kind``, texts per language (``texts``:
  name, description, examples) and ``status`` (works, untested, builtin);
- ovos-klondike-mercantile's: ``package_name``, ``component_type``, English
  texts, ``archived`` and ``on_pypi``.

What a store says is archived, broken or not on PyPI is left out. A package
the panel does not take as an OVOS package (:func:`ovos_webui.pypi.classify`)
is left out too, so a store cannot offer anything the Plugins page would not.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from ovos_utils.log import LOG

MAX_STORES = 8
MAX_BYTES = 8 * 1024 * 1024
TTL = 6 * 3600
RETRY = 10 * 60
_URL = re.compile(r"^https://[^\s/]+\S*$")

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, list[dict] | None, str | None]] = {}


def configured() -> list[dict[str, str]]:
    """The stores set in ``webui.stores``, in their order; anything that is
    not a name and an https URL is skipped."""
    from ovos_webui import configio
    raw = configio.user_or_merged(["webui", "stores"])
    out: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not _URL.match(url.strip()):
            continue
        name = item.get("name") if isinstance(item.get("name"), str) and item["name"].strip() else url
        out.append({"name": name.strip()[:60], "url": url.strip()})
        if len(out) >= MAX_STORES:
            break
    return out


def check(stores: Any) -> list[dict[str, str]]:
    """A list of stores to save; raises ValueError saying what is wrong."""
    if not isinstance(stores, list) or len(stores) > MAX_STORES:
        raise ValueError(f"stores is a list of at most {MAX_STORES}")
    out = []
    for item in stores:
        if not isinstance(item, dict):
            raise ValueError("each store is a name and a URL")
        name = item.get("name")
        url = item.get("url")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
            raise ValueError("each store needs a name of at most 60 characters")
        if not isinstance(url, str) or not _URL.match(url.strip()) or len(url) > 500:
            raise ValueError(f"{name.strip()}: the address must start with https://")
        out.append({"name": name.strip(), "url": url.strip()})
    return out


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _texts(raw: Any) -> dict[str, dict[str, Any]]:
    out = {}
    for lang, t in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(t, dict) or not isinstance(lang, str):
            continue
        examples = [_text(e, 200) for e in (t.get("examples") or []) if isinstance(e, str)][:5]
        out[lang.lower()] = {"name": _text(t.get("name"), 120),
                             "description": _text(t.get("description"), 600), "examples": examples}
    return out


def _from_emkay(r: dict) -> dict | None:
    if r.get("status") not in ("works", "untested", "builtin"):
        return None
    return {"package": r.get("package"), "texts": _texts(r.get("texts")),
            "works": True if r.get("status") in ("works", "builtin") else None}


def _from_klondike(r: dict) -> dict | None:
    if r.get("archived") or not r.get("on_pypi"):
        return None
    texts = _texts({"en-us": {"name": r.get("name"), "description": r.get("description"),
                              "examples": r.get("examples") or []}})
    return {"package": r.get("package_name"), "texts": texts, "works": None}


def parse(records: Any) -> list[dict]:
    """The packages in a store's list, whichever of the two formats it is."""
    from packaging.utils import canonicalize_name

    from ovos_webui.pypi import classify
    out, seen = [], set()
    for r in records if isinstance(records, list) else []:
        if not isinstance(r, dict):
            continue
        if "texts" in r and "package" in r:
            found = _from_emkay(r)
        elif "package_name" in r:
            found = _from_klondike(r)
        else:
            found = None
        if not found or not isinstance(found["package"], str):
            continue
        name = canonicalize_name(found["package"].strip())
        kind = classify(name)
        if kind is None or name in seen:
            continue
        seen.add(name)
        out.append(dict(found, package=name, kind=kind))
    return out


def _read(url: str) -> Any:
    from ovos_webui.pypi import _open
    with _open(url) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("the store's list is too large")
    return json.loads(data.decode("utf-8"))


def packages(url: str, refresh: bool = False) -> tuple[list[dict] | None, str | None]:
    """A store's packages, kept :data:`TTL`; the last good list when a read
    fails. ``(None, error)`` when it was never read."""
    now = time.time()
    with _LOCK:
        at, found, error = _CACHE.get(url, (0.0, None, None))
        fresh = (found is not None and now - at < TTL) or (found is None and error and now - at < RETRY)
        if refresh or not fresh:
            try:
                found, error = parse(_read(url)), None
            except (OSError, ValueError) as err:
                LOG.info(f"the store {url} could not be read: {err}")
                error = str(err)
                found = _CACHE.get(url, (0.0, None, None))[1]
            _CACHE[url] = (now, found, error)
        return found, error


def text(entry: dict, lang: str) -> dict[str, Any]:
    """Name, description and examples in ``lang``, else English."""
    texts = entry.get("texts") or {}
    lang = (lang or "en-us").lower()
    base = texts.get("en-us") or next(iter(texts.values()), {}) if texts else {}
    for key, t in texts.items():
        if key == lang or key.split("-")[0] == lang.split("-")[0]:
            if t.get("name") or t.get("description"):
                return {"name": t.get("name") or base.get("name") or "",
                        "description": t.get("description") or base.get("description") or "",
                        "examples": t.get("examples") or base.get("examples") or []}
    return {"name": base.get("name") or "", "description": base.get("description") or "",
            "examples": base.get("examples") or []}


def clear() -> None:
    with _LOCK:
        _CACHE.clear()
