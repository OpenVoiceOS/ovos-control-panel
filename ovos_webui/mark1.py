"""Drive the Mark-1 faceplate (eyes + mouth) over the message bus.

Every message here already exists — this module invents no new bus message
types. It only wraps the ``enclosure.*`` topics that ``ovos-PHAL-plugin-mk1``
listens on, the same way ``network.py`` wraps the network-manager plugin and
``devicecontrol.py`` wraps volume/mic:

Eyes: ``enclosure.eyes.on`` / ``.off`` / ``.reset`` / ``.narrow`` / ``.spin``
(no data); ``enclosure.eyes.blink`` (``side``); ``enclosure.eyes.look``
(``side``); ``enclosure.eyes.color`` (``r``, ``g``, ``b``); ``enclosure.eyes.fill``
(``percentage``); ``enclosure.eyes.level`` (``level``); ``enclosure.eyes.volume``
(``volume``).

Mouth: ``enclosure.mouth.reset`` (no data); ``enclosure.mouth.text`` (``text``);
``enclosure.mouth.display`` (``img_code``, ``xOffset``, ``yOffset``,
``clearPrev``); ``enclosure.mouth.talk`` / ``.think`` / ``.listen`` / ``.smile``
(no data, animation topics); ``enclosure.mouth.viseme_list`` (``start``,
``visemes``). The animation topics are dropped by the plugin unless
``enclosure.mouth.events.activate`` was sent first, so every animation call
sends that once before the animation itself.

System: ``enclosure.system.reset`` / ``.mute`` / ``.unmute`` (no data);
``enclosure.system.blink`` (``times``).

Capability probe: ``enclosure.eyes.rgb.get`` (no data) → reply
``enclosure.eyes.rgb`` (``pixels``). This is the only readback the mk1 plugin
offers, so it doubles as "is a Mark-1 listener present at all".

Every function returns a plain dict and never raises on a bus problem — a
missing plugin or a dead bus turns into ``{"ok": False, "error": ...}``, the
same shape ``network.py`` uses.
"""
from __future__ import annotations

from typing import Any

#: How long the capability probe waits for a reply.
PROBE_TIMEOUT = 3.0

#: A grid too far off shape or with numbers that plainly cannot come from a
#: real click-to-toggle pixel editor is rejected before it reaches the bus.
GRID_HEIGHT = 8
GRID_WIDTH = 32

_SIDES = {"r", "l", "b"}
_LOOKS = {"r", "l", "u", "d", "c"}
_ANIMS = {"talk", "think", "listen", "smile"}


def _msg(msg_type: str, data: dict[str, Any] | None = None):
    from ovos_bus_client.message import Message

    return Message(msg_type, data or {}, {"source": "ovos-webui",
                                          "destination": ["enclosure"]})


def _emit(bus, msg_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    from ovos_webui import buswait

    ok = buswait.emit(bus, _msg(msg_type, data))
    if not ok:
        return {"ok": False, "error": "the message bus did not accept that "
                                      "in time"}
    return {"ok": True, "sent": msg_type}


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


# ── capability probe ─────────────────────────────────────────────────────────
def available(bus) -> dict[str, Any]:
    """Probe for a Mark-1 hardware listener.

    Emits ``enclosure.eyes.rgb.get`` and waits for ``enclosure.eyes.rgb``. A
    reply, of any shape, means a listener (``ovos-PHAL-plugin-mk1``) is
    present. No reply means either no listener or no bus.
    """
    from ovos_webui import buswait

    if not buswait.is_connected(bus):
        return {"available": False}
    reply = buswait.call(
        lambda: bus.wait_for_response(_msg("enclosure.eyes.rgb.get"),
                                      reply_type="enclosure.eyes.rgb",
                                      timeout=PROBE_TIMEOUT),
        timeout=PROBE_TIMEOUT + 1.0, default=None)
    return {"available": reply is not None}


# ── mouth: drawn image ───────────────────────────────────────────────────────
def _valid_grid(grid: Any) -> bool:
    if not isinstance(grid, list) or len(grid) != GRID_HEIGHT:
        return False
    for row in grid:
        if not isinstance(row, list) or len(row) != GRID_WIDTH:
            return False
        for cell in row:
            if isinstance(cell, bool) or cell not in (0, 1):
                return False
    return True


def display_grid(bus, grid: Any, x: int = 0, y: int = 0,
                 clear: bool = True) -> dict[str, Any]:
    """Encode ``grid`` (8 rows x 32 columns of 0/1) and show it on the mouth.

    Uses ``ovos_mark1.faceplate.FaceplateGrid`` — the canonical encoder the
    mk1 plugin itself uses — so the ``img_code`` this produces is exactly what
    a real ``display()`` call would send. ``invert=True`` matches
    ``FaceplateGrid.display``'s own default.
    """
    if not _valid_grid(grid):
        return {"ok": False,
                "error": f"the grid must be {GRID_HEIGHT} rows of "
                         f"{GRID_WIDTH} values, each 0 or 1"}
    try:
        from ovos_mark1.faceplate import FaceplateGrid
    except Exception as err:  # noqa: BLE001 - a declared dependency, but be explicit
        return {"ok": False,
                "error": f"the ovos-mark1-utils encoder is not available: {err}"}
    # Pass the web UI's own bus: FaceplateGrid falls back to get_mycroft_bus()
    # (which opens a fresh messagebus connection) when no bus is given, and we
    # only need it to encode, never to connect.
    img_code = FaceplateGrid(grid=grid, bus=bus).encode(invert=True)
    result = _emit(bus, "enclosure.mouth.display",
                   {"img_code": img_code, "xOffset": int(x), "yOffset": int(y),
                    # The plugin lower-cases this before comparing it to
                    # "true", so it has to be a string: a bool raises there and
                    # nothing is drawn, for either value of the checkbox.
                    "clearPrev": "true" if clear else "false"})
    result["img_code"] = img_code
    return result


def mouth_text(bus, text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        return {"ok": False, "error": "text must be a string"}
    return _emit(bus, "enclosure.mouth.text", {"text": text})


def mouth_reset(bus) -> dict[str, Any]:
    return _emit(bus, "enclosure.mouth.reset")


def _activate_mouth_events(bus) -> None:
    from ovos_webui import buswait

    buswait.emit(bus, _msg("enclosure.mouth.events.activate"))


def mouth_anim(bus, kind: str) -> dict[str, Any]:
    """Play a mouth animation. The animation topics are dropped by the plugin
    unless ``enclosure.mouth.events.activate`` was sent first."""
    if kind not in _ANIMS:
        return {"ok": False,
                "error": f"kind must be one of {sorted(_ANIMS)}"}
    _activate_mouth_events(bus)
    return _emit(bus, f"enclosure.mouth.{kind}")


#: How long a single viseme stays on the faceplate, in seconds.
VISEME_SECONDS = 0.4


def mouth_viseme(bus, code: int) -> dict[str, Any]:
    """Show a single viseme, wrapped as a one-entry ``viseme_list``."""
    import time

    code = _int(code)
    if code is None or not 0 <= code <= 6:
        return {"ok": False, "error": "code must be a whole number from 0 to 6"}
    _activate_mouth_events(bus)
    # ``start`` is a timestamp, not an offset: the plugin skips any pair whose
    # ``start + end`` has already passed, so a start of 0 means every viseme is
    # in the distant past and nothing is ever written. The code goes over as a
    # string because the plugin concatenates it onto "mouth.viseme=".
    return _emit(bus, "enclosure.mouth.viseme_list",
                {"start": time.time(),
                 "visemes": [[str(code), VISEME_SECONDS]]})


# ── eyes ──────────────────────────────────────────────────────────────────────
def eyes_color(bus, r: int, g: int, b: int) -> dict[str, Any]:
    r, g, b = _int(r), _int(g), _int(b)
    if r is None or g is None or b is None or not all(0 <= v <= 255 for v in (r, g, b)):
        return {"ok": False, "error": "r, g, b must be whole numbers from 0 to 255"}
    return _emit(bus, "enclosure.eyes.color", {"r": r, "g": g, "b": b})


def eyes_on(bus) -> dict[str, Any]:
    return _emit(bus, "enclosure.eyes.on")


def eyes_off(bus) -> dict[str, Any]:
    return _emit(bus, "enclosure.eyes.off")


def eyes_reset(bus) -> dict[str, Any]:
    return _emit(bus, "enclosure.eyes.reset")


def eyes_narrow(bus) -> dict[str, Any]:
    return _emit(bus, "enclosure.eyes.narrow")


def eyes_spin(bus) -> dict[str, Any]:
    return _emit(bus, "enclosure.eyes.spin")


def eyes_blink(bus, side: str) -> dict[str, Any]:
    if side not in _SIDES:
        return {"ok": False, "error": f"side must be one of {sorted(_SIDES)}"}
    return _emit(bus, "enclosure.eyes.blink", {"side": side})


def eyes_look(bus, side: str) -> dict[str, Any]:
    if side not in _LOOKS:
        return {"ok": False, "error": f"side must be one of {sorted(_LOOKS)}"}
    return _emit(bus, "enclosure.eyes.look", {"side": side})


def eyes_fill(bus, pct: int) -> dict[str, Any]:
    pct = _int(pct)
    if pct is None or not 0 <= pct <= 100:
        return {"ok": False, "error": "percentage must be a whole number from 0 to 100"}
    return _emit(bus, "enclosure.eyes.fill", {"percentage": pct})


def eyes_brightness(bus, level: int) -> dict[str, Any]:
    level = _int(level)
    if level is None or not 1 <= level <= 30:
        return {"ok": False, "error": "level must be a whole number from 1 to 30"}
    return _emit(bus, "enclosure.eyes.level", {"level": level})


def eyes_volume(bus, volume: int) -> dict[str, Any]:
    volume = _int(volume)
    if volume is None or not 0 <= volume <= 11:
        return {"ok": False, "error": "volume must be a whole number from 0 to 11"}
    return _emit(bus, "enclosure.eyes.volume", {"volume": volume})


# ── system ────────────────────────────────────────────────────────────────────
def system_reset(bus) -> dict[str, Any]:
    return _emit(bus, "enclosure.system.reset")


def system_mute(bus) -> dict[str, Any]:
    return _emit(bus, "enclosure.system.mute")


def system_unmute(bus) -> dict[str, Any]:
    return _emit(bus, "enclosure.system.unmute")


def system_blink(bus, times: int) -> dict[str, Any]:
    times = _int(times)
    if times is None or not 1 <= times <= 20:
        return {"ok": False, "error": "times must be a whole number from 1 to 20"}
    return _emit(bus, "enclosure.system.blink", {"times": times})
