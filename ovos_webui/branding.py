"""A distribution's own name, logo and colours, from ``webui.branding``.

Everything here is configuration: a distribution such as Emkay sets it in the
system layer of ``mycroft.conf``, and the user can change it in their own.

``webui.branding`` holds:

* ``name``: replaces "OpenVoiceOS" in the header and the window title.
* ``logo``: an SVG, PNG, JPEG or WebP file on the device, at most 512 KB. It
  replaces the waveform in the header.
* ``colors`` and ``colors_dark``: values for the theme's CSS variables, in
  light and dark mode. Only the variables in :data:`COLOR_VARS` are taken, and
  only plain colour values, so nothing else can reach the stylesheet.

Next to it, ``webui.theme`` and ``webui.text_size`` say whether the viewer
chooses (``"choose"``, the default: the header has a button) or the device
decides (``"dark"``/``"light"``, ``"normal"``/``"large"``/``"xlarge"``: no
button). See :func:`appearance`.

:func:`css` turns the colours into the small stylesheet every page loads after
``app.css``; :func:`warnings` says when a chosen colour makes text hard to read.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DEFAULT_NAME = "OpenVoiceOS"
MAX_NAME = 40
MAX_LOGO = 512 * 1024
LOGO_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
              ".jpeg": "image/jpeg", ".webp": "image/webp"}
#: The theme's colour variables a distribution may set.
COLOR_VARS = ("bg", "bg-soft", "card", "card-soft", "ink", "muted", "line", "accent",
              "accent-strong", "accent-hover", "accent-ink", "accent-wash", "ok", "warn", "bad")
_COLOR_RE = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|(rgb|rgba|hsl|hsla)\(\s*[0-9.%\s,/]+\))$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f<>]")


#: webui.theme: the viewer chooses, or the device always shows one.
THEMES = ("choose", "dark", "light")
#: webui.text_size: the viewer chooses, or the device always uses one.
TEXT_SIZES = ("choose", "normal", "large", "xlarge")


def appearance() -> dict[str, str]:
    """``webui.theme`` and ``webui.text_size``, read fresh; anything else is
    "choose"."""
    from ovos_webui import configio
    try:
        theme = configio.user_or_merged(["webui", "theme"])
        text = configio.user_or_merged(["webui", "text_size"])
    except Exception:  # noqa: BLE001 - a broken config must not stop a page
        theme = text = None
    return {"theme": theme if theme in THEMES else "choose",
            "text_size": text if text in TEXT_SIZES else "choose"}


def html_attrs(look: dict[str, str]) -> str:
    """Attributes for the page's <html>: a theme or text size the device
    decides is set by the server, so the page paints that way at once and the
    header has no button for it (app.js)."""
    out = ""
    if look["theme"] != "choose":
        out += f' data-theme="{look["theme"]}" data-theme-locked'
    if look["text_size"] not in ("choose", "normal"):
        out += f' data-text="{look["text_size"]}"'
    if look["text_size"] != "choose":
        out += " data-text-locked"
    return out


def _config() -> dict[str, Any]:
    from ovos_webui import configio
    try:
        raw = configio.section("webui").get("branding") or {}
    except Exception:  # noqa: BLE001 - a broken config must not stop a page
        return {}
    return raw if isinstance(raw, dict) else {}


def _colors(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {k: v.strip() for k, v in raw.items()
            if k in COLOR_VARS and isinstance(v, str) and _COLOR_RE.match(v.strip())}


def read(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """The branding in force, with anything unusable left out."""
    raw = _config() if raw is None else raw
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip() or _CONTROL_RE.search(name):
        name = DEFAULT_NAME
    logo = raw.get("logo")
    logo = logo if isinstance(logo, str) and logo.strip() else None
    return {"name": name.strip()[:MAX_NAME], "logo": logo,
            "colors": _colors(raw.get("colors")), "colors_dark": _colors(raw.get("colors_dark"))}


def logo_file(brand: dict[str, Any]) -> tuple[Path, str] | None:
    """The logo to serve, as (path, media type), or None."""
    if not brand.get("logo"):
        return None
    path = Path(brand["logo"]).expanduser()
    media = LOGO_TYPES.get(path.suffix.lower())
    try:
        if media is None or not path.is_file() or path.stat().st_size > MAX_LOGO:
            return None
    except OSError:
        return None
    return path, media


def _block(colors: dict[str, str]) -> str:
    return "".join(f"  --{k}: {v};\n" for k, v in colors.items())


def css(brand: dict[str, Any]) -> str:
    """The stylesheet that sets the chosen colours.

    The dark block repeats app.css's two dark selectors, so it wins over the
    default dark colours however dark mode was chosen.
    """
    out = "/* webui.branding */\n"
    if brand["colors"]:
        out += ":root {\n" + _block(brand["colors"]) + "}\n"
    if brand["colors_dark"]:
        block = _block(brand["colors_dark"])
        out += ('@media (prefers-color-scheme: dark) {\n:root:not([data-theme="light"]) {\n'
                + block + "}\n}\n:root[data-theme=\"dark\"] {\n" + block + "}\n")
    return out


# ── is the text still readable? ──────────────────────────────────────────────
def _rgb(value: str) -> tuple[float, float, float] | None:
    if not value.startswith("#") or len(value) not in (4, 7):
        return None
    if len(value) == 4:
        value = "#" + "".join(c * 2 for c in value[1:])
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float | None:
    """The WCAG contrast ratio of two hex colours, or None if one is not hex."""
    ra, rb = _rgb(a), _rgb(b)
    if ra is None or rb is None:
        return None
    la, lb = sorted((_luminance(ra), _luminance(rb)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


#: Text and the background it sits on, as the theme pairs them.
_PAIRS = (("ink", "bg"), ("ink", "card"), ("muted", "card"), ("accent-ink", "accent-strong"))
#: The default light colours, for a pair where only one side was chosen.
_DEFAULTS = {"bg": "#efeae6", "card": "#fbf9f7", "ink": "#191517", "muted": "#574f56",
             "accent-strong": "#a5161c", "accent-ink": "#ffffff"}


def warnings(brand: dict[str, Any]) -> list[str]:
    """Pairs of chosen light colours with less than 4.5:1 contrast."""
    colors = brand["colors"]
    out = []
    for text, back in _PAIRS:
        if text not in colors and back not in colors:
            continue
        ratio = contrast(colors.get(text, _DEFAULTS[text]), colors.get(back, _DEFAULTS[back]))
        if ratio is not None and ratio < 4.5:
            out.append(f"--{text} on --{back} has a contrast of {ratio:.1f}:1; text needs 4.5:1")
    return out
