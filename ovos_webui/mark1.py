"""Drive the Mark-1 faceplate (eyes + mouth) over the message bus.

The ``enclosure.*`` topics here already exist and are wrapped, not invented;
the two ``enclosure.firmware.*`` topics are new, and deliberately so -- Mark-1
hardware sits outside the architecture spec. This wraps the topics that
``ovos-PHAL-plugin-mk1`` listens on, the same way ``network.py`` wraps the network-manager plugin and
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
``visemes``). The animation and viseme topics are the only gated ones, and
``PHALPlugin.__init__`` activates them, so the activate this sends first only
matters where a skill deliberately deactivated them to own the display.

System: ``enclosure.system.reset`` / ``.mute`` / ``.unmute`` (no data);
``enclosure.system.blink`` (``times``).

Per pixel: ``enclosure.eyes.setpixel`` (``idx``, ``r``, ``g``, ``b``) -- no
underscore, which the mk1 plugin's own docstring gets wrong; the binding is in
``ovos_plugin_manager.templates.phal``, and the binding is what decides. The
eyes are two rings of twelve addressable LEDs, ``0``-``11`` on the left and
``12``-``23`` on the right, which is why the panel draws them as rings of
twelve rather than as two blobs of colour.

Capability probe: ``enclosure.eyes.rgb.get`` (no data) → reply
``enclosure.eyes.rgb`` (``pixels``). This is the only readback the mk1 plugin
offers -- in principle. Nothing binds it: ``handle_get_color`` is defined in
the mk1 plugin and registered nowhere, so the readback goes unanswered on a
device that is working perfectly. Until that is fixed upstream the eyes cannot
be mirrored, and a device that answers the firmware question instead is
confirmed present with the live face reporting that it cannot read them.

What it reports is also narrower than it looks. Only ``on_eyes_color`` and
``on_eyes_set_pixel`` update ``_current_rgb``; ``on_eyes_off``, ``on_eyes_on``,
``fill``, ``blink``, ``narrow``, ``look``, ``volume``, ``brightness`` and
``spin`` all write to the serial port and leave it stale. So a mirrored face
follows colour changes and per-pixel writes, and not the animations.

Every function returns a plain dict and never raises on a bus problem — a
missing plugin or a dead bus turns into ``{"ok": False, "error": ...}``, the
same shape ``network.py`` uses.
"""
from __future__ import annotations

from typing import Any

#: How long the capability probe waits for a reply.
PROBE_TIMEOUT = 3.0

#: The faceplate firmware is built on the device before it is flashed -- there
#: is no prebuilt binary to fetch any more -- so an update is minutes of work,
#: not seconds. The panel does not wait for it: it asks, then follows the
#: progress messages the plugin emits.
FIRMWARE_ASK_TIMEOUT = 5.0

#: A grid too far off shape or with numbers that plainly cannot come from a
#: real click-to-toggle pixel editor is rejected before it reaches the bus.
GRID_HEIGHT = 8
GRID_WIDTH = 32

#: The eyes are two rings of twelve addressable LEDs. The plugin addresses
#: them as one flat range: the left eye is 0-11 and the right eye 12-23, which
#: is also the order ``enclosure.eyes.rgb`` reports them in.
EYE_PIXELS = 12
EYE_PIXEL_COUNT = EYE_PIXELS * 2

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

    The faceplate can be asked two things: what colour the eyes are showing,
    and what firmware it runs. Either answer proves a listener is there. Both
    are needed because a plugin can answer one and not the other, and a plugin
    that answers neither is indistinguishable from no hardware -- which is why
    a silent probe only removes the live mirror and the firmware card, and
    never stops a control from sending.

    Asked at the same time rather than one after the other: on a device that
    answers neither, which is every device until the plugin gains a readback,
    asking in turn makes every page load wait out both timeouts.
    """
    from concurrent.futures import ThreadPoolExecutor

    from ovos_webui import buswait

    if not buswait.is_connected(bus):
        return {"available": False}
    with ThreadPoolExecutor(max_workers=2) as pool:
        pixels = pool.submit(_read_pixels, bus)
        version = pool.submit(firmware, bus)
        answered = (pixels.result() is not None
                    or bool(version.result().get("ok")))
    return {"available": answered}


def _read_pixels(bus):
    """The raw ``enclosure.eyes.rgb`` reply, or ``None`` if nothing answered."""
    from ovos_webui import buswait

    return buswait.call(
        lambda: bus.wait_for_response(_msg("enclosure.eyes.rgb.get"),
                                      reply_type="enclosure.eyes.rgb",
                                      timeout=PROBE_TIMEOUT),
        timeout=PROBE_TIMEOUT + 1.0, default=None)


def eyes_state(bus) -> dict[str, Any]:
    """What each of the twenty-four eye LEDs is currently showing.

    The plugin tracks this for every eye message it handles, so the face the
    panel draws follows the device even when something else is driving it --
    a skill, the volume knob, another panel in another tab.

    A short pixel list is padded and a long one truncated rather than
    rejected: an older plugin that reports fewer pixels should still light up
    the ring it does report, not blank the whole face.
    """
    from ovos_webui import buswait

    if not buswait.is_connected(bus):
        return {"ok": False, "error": "no device is connected"}
    reply = _read_pixels(bus)
    if reply is None:
        return {"ok": False,
                "error": "nothing answered 'enclosure.eyes.rgb.get'. A "
                         "running ovos-PHAL-plugin-mk1 stays silent on that "
                         "topic until it binds its own readback handler, so "
                         "this does not mean the plugin is missing."}
    raw = (reply.data or {}).get("pixels") or []
    pixels = []
    for index in range(EYE_PIXEL_COUNT):
        entry = raw[index] if index < len(raw) else None
        pixels.append(_as_rgb(entry))
    return {"ok": True, "pixels": pixels}


def firmware(bus) -> dict[str, Any]:
    """What faceplate firmware this Mark-1 is running, and what is available.

    The board reports its version on serial, at boot and in reply to the
    ``version`` command, and the plugin keeps the parsed value. ``version`` is
    ``None`` when the board has not said yet -- which is a different thing from
    an old version, and is reported as such rather than guessed.
    """
    from ovos_webui import buswait

    if not buswait.is_connected(bus):
        return {"ok": False, "error": "no device is connected"}
    reply = buswait.call(
        lambda: bus.wait_for_response(_msg("enclosure.firmware.version.get"),
                                      reply_type="enclosure.firmware.version",
                                      timeout=PROBE_TIMEOUT),
        timeout=PROBE_TIMEOUT + 1.0, default=None)
    if reply is None:
        return {"ok": False,
                "error": "this Mark-1 plugin does not report firmware "
                         "versions — update ovos-PHAL-plugin-mk1 to manage "
                         "firmware from here"}
    data = reply.data or {}
    running = data.get("version")
    supported = data.get("supported")
    result = {"ok": True, "version": running, "supported": supported}
    if running and supported:
        result["outdated"] = _older(running, supported)
    return result


def _older(running: str, supported: str) -> bool:
    """Whether ``running`` is behind ``supported``, compared as version tuples.

    Compared field by field as integers rather than as strings, so 1.10.0 is
    not read as older than 1.4.2.
    """
    def parts(value):
        out = []
        for chunk in str(value).split("."):
            digits = "".join(c for c in chunk if c.isdigit())
            out.append(int(digits) if digits else 0)
        return out

    left, right = parts(running), parts(supported)
    width = max(len(left), len(right))
    left += [0] * (width - len(left))
    right += [0] * (width - len(right))
    return left < right


def firmware_update(bus) -> dict[str, Any]:
    """Ask the device to build and flash the current faceplate firmware.

    Fire-and-forget on purpose: the plugin clones the firmware source, builds
    it with PlatformIO and flashes it with avrdude, which is minutes of work.
    Holding an HTTP request open for that would time out somewhere in the
    middle of a flash. The plugin reports progress on its own topic; this only
    reports whether the request was accepted.
    """
    return _emit(bus, "enclosure.firmware.update")


def _as_rgb(entry: Any) -> list[int]:
    """One reported pixel as ``[r, g, b]``, clamped; anything odd reads dark."""
    if not isinstance(entry, (list, tuple)) or len(entry) != 3:
        return [0, 0, 0]
    out = []
    for value in entry:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [0, 0, 0]
        out.append(max(0, min(255, int(value))))
    return out


def set_pixel(bus, idx: Any, r: Any, g: Any, b: Any) -> dict[str, Any]:
    """Light one eye LED. ``idx`` is 0-11 on the left eye, 12-23 on the right."""
    index = _int(idx)
    if index is None or not 0 <= index < EYE_PIXEL_COUNT:
        return {"ok": False,
                "error": f"the eye pixel must be 0-{EYE_PIXEL_COUNT - 1}"}
    channels = []
    for value in (r, g, b):
        channel = _int(value)
        if channel is None or not 0 <= channel <= 255:
            return {"ok": False, "error": "each colour channel must be 0-255"}
        channels.append(channel)
    return _emit(bus, "enclosure.eyes.setpixel",
                 {"idx": index, "r": channels[0],
                  "g": channels[1], "b": channels[2]})


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


def _activate_mouth_events(bus) -> None:
    from ovos_webui import buswait

    buswait.emit(bus, _msg("enclosure.mouth.events.activate"))


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
