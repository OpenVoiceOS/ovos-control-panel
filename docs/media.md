# Media

What the device is playing, play and pause, the queue, shuffle and repeat,
seeking, the volume, the other matches for what you asked for, and the songs
you have liked.

Not every OpenVoiceOS device plays media: one that guides guests at a
reception desk, or answers a phone line, does not. So the Media page is a
panel extension of its own,
[ovos-control-panel-media](https://github.com/andlo/ovos-control-panel-media),
rather than part of the panel. Install it where the panel runs, and restart
the panel:

```
pip install --pre ovos-control-panel-media
```

(`--pre`, as for the panel itself.) It works with `ovos-media` and with the
older `ovos-plugin-common-play`. Its README says what the page does.

The [Dashboard](dashboard.md) still shows whether `ovos-media` answers.

---
[← Device controls](controls.md) · [Home](README.md) · [Apps →](apps.md)
