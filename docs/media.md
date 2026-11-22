# Media

What the device is playing, play and pause, the queue, shuffle and repeat,
seeking, the volume, the other matches for what you asked for, and the songs
you have liked; and your own songs and films, put on the device from the
browser where its local media search finds them (ovos-media-provider-local,
or the older ovos-skill-local-media), up to the largest file set on the
Control panel page.

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

Media providers, the plugins OpenVoiceOS is moving its media search to
(`ovos-media-provider-*`), each get a page of their own beside Media, with a
switch to turn them on or off; see
[controlpanel-json.md](controlpanel-json.md#provider).

---
[← Device controls](controls.md) · [Home](README.md) · [Apps →](apps.md)
