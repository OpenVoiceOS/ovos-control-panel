# Mark-1 faceplate

A Mark-1 has two rings of twelve LEDs for eyes and an 8×32 grid for a mouth,
driven by a small board of its own. Where the `ovos-PHAL-plugin-mk1` plugin
is installed, the panel shows a **Mark-1 faceplate** page for it.

## The plain page

The panel brings a plain page for the plugin, described in
`ovos_webui/bundled/ovos-phal-plugin-mk1/` (see
[Pages](pages.md#pages-the-panel-describes)):

- **Eyes**: on, off, blink, narrow, spin and reset.
- **Colour**: blue, green, red or white.
- **Brightness**: dim, medium or bright.
- **Mouth**: scroll a text across it, or reset it.
- **System**: mute, unmute, blink and reset the faceplate.

The plugin answers none of these, so the page sends them and says nothing
came back. The buttons need an access token.

## The editors: ovos-control-panel-mark1

The drawing editors for the mouth and the eye rings, the animations, the
live preview and the firmware updates are a panel extension of their own:

```
pip install ovos-control-panel-mark1
```

Install it where the panel runs and restart the panel. Its page takes the
plain page's place. See its README for what it does.

---
[← Servers](servers.md) · [Home](README.md) · [Wallpaper →](wallpaper.md)
