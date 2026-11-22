# Give your skill or plugin a page

The control panel can show a page for your skill or plugin: its settings, what
it is doing, its lists and its buttons. You do not write HTML or Python for
it. You describe the page in a file, and the panel draws it and talks to your
skill over the message bus it already listens to.

Start at the top and stop where your skill has what it needs. Most skills stop
at step 1 or 2.

| Step | You add | You get |
| --- | --- | --- |
| [1. Settings](#1-settings-settingsmetajson) | `settingsmeta.json` | A settings form on the Skills page |
| [2. Settings in every language](#2-settings-in-every-language) | `locale/<lang>/controlpanel.json` | The same form in the reader's language |
| [3. A page of its own](#3-a-page-of-its-own-controlpaneljson) | `controlpanel.json` | A page in the menu |
| [4. Talking to the skill](#4-talking-to-the-skill) | A few bus handlers | Status, lists and buttons |
| [5. A plugin's page](#5-a-plugins-page) | `controlpanel.json` in a plugin | Its settings in `mycroft.conf`, made the voice in use |
| [6. When a file is not enough](#6-when-a-file-is-not-enough) | A panel extension | A page with its own HTML and Python |

Every key is in the [reference](controlpanel-json.md).

## 1. Settings: settingsmeta.json

A skill with settings ships a `settingsmeta.json`, the plain OVOS standard. The
Skills page shows it as a form, and saves in the skill's `settings.json`, which
the skill reads as `self.settings`:

```json
{
  "skillMetadata": {
    "sections": [
      {"name": "Radio", "fields": [
        {"name": "station", "type": "text", "label": "Station", "value": "DR P1"},
        {"name": "quality", "type": "select", "label": "Quality",
         "options": "Low|128;High|320", "value": "320"}
      ]}
    ]
  }
}
```

A skill without settings needs nothing at all.

## 2. Settings in every language

settingsmeta has one text per field. Put the texts in other languages in
`locale/<lang>/controlpanel.json`, by the field's name:

```json
{
  "settings.section.Radio": "Radio",
  "settings.station": "Radiostation",
  "settings.station.hint": "Som stationen selv kalder sig",
  "settings.quality.option.320": "Høj"
}
```

The form uses the reader's language, then English, then the text in
settingsmeta. See [Settings in your language](skills.md#settings-in-your-language).

## 3. A page of its own: controlpanel.json

When the skill has more than settings to show, put a `controlpanel.json`
next to `skill.json`:

```json
{
  "controlpanel": 1,
  "id": "radio",
  "title": "radio.title",
  "group": "library",
  "icon": "controlpanel.svg",
  "bus": "ovos.radio.",
  "blocks": [
    {"type": "text", "text": "radio.intro"},
    {"type": "form", "save": {"settings": true}, "fields": [
      {"name": "station", "label": "radio.station", "type": "text", "required": true},
      {"name": "quality", "label": "radio.quality", "type": "select", "options": [
        {"value": "128", "label": "radio.low"}, {"value": "320", "label": "radio.high"}]}
    ]}
  ]
}
```

and its strings in `locale/en-us/controlpanel.json`,
`locale/da-dk/controlpanel.json` and so on:

```json
{"radio.title": "Radio", "radio.intro": "The station the radio plays.",
 "radio.station": "Station", "radio.quality": "Quality",
 "radio.low": "Low", "radio.high": "High"}
```

Add both, and the icon, to the package's data in `pyproject.toml`:

```toml
[tool.setuptools.package-data]
ovos_skill_radio = ["locale/**/*", "controlpanel.json", "controlpanel.svg"]
```

Install the skill, restart the panel, and the page is in the menu under
Library. A form that saves `{"settings": true}` writes the same
`settings.json` as settingsmeta, with what this format adds: web addresses,
required fields, limits, fields shown only when another has a value.

Choose the group by what the page is about: see
[Where a page belongs](pages.md#where-a-page-belongs).

## 4. Talking to the skill

Everything else on the page is a message to the skill, under the page's own
`bus` prefix. The skill answers as any OVOS skill answers a question, with
`message.response()`:

```json
{"type": "list", "query": "ovos.radio.stations", "items": "stations", "key": "id",
 "title": "{name}", "text": "{genre}",
 "actions": [{"label": "common.play", "send": "ovos.radio.play"}]}
```

```python
def initialize(self):
    self.add_event("ovos.radio.stations", self.handle_stations)
    self.add_event("ovos.radio.play", self.handle_play)

def handle_stations(self, message):
    self.bus.emit(message.response({"stations": [
        {"id": "p1", "name": "DR P1", "genre": "Talk"},
        {"id": "p6", "name": "DR P6 Beat", "genre": "Music"}]}))

def handle_play(self, message):
    station = message.data["id"]          # the row's key
    ...
    self.bus.emit(message.response({"ok": True}))
```

What you can build with that:

- a **status** card that asks once and shows the answer, with buttons;
- a **list** with buttons on each row, a rename, a filter, a picture;
- **tabs** (`choice`) whose value goes with every question;
- a **download** of a file the skill hands back, and an **upload** to it;
- a list that **listens** to what a plugin broadcasts, for a sensor.

Answer `{"error": "radio.err.offline"}` to show an error in the reader's
language. A button whose message gets no answer says `"answer": false`.

The panel sends only what the file declares, so the skill can trust the data
it gets: see [What the panel checks](controlpanel-json.md#what-the-panel-checks).

## 5. A plugin's page

A PHAL, TTS or STT plugin describes its page the same way. Its form saves in
the plugin's own place in `mycroft.conf`, and asks it to read it again:

```json
{"type": "form", "save": {"config": "tts.ovos-tts-plugin-piper"},
 "fields": [{"name": "voice", "label": "piper.voice", "type": "select", "voices": true}]}
```

A plugin's own places are `PHAL.<package>` and the section its entry points
name (`tts.<module>`, `stt.<module>`, `PHAL.<name>`). A TTS or STT plugin can
add `{"type": "module", "kind": "tts"}`: whether it is the voice in use,
buttons to make it so, and a sentence to hear it.

Until a plugin brings its own file, the panel may bring one for it: see
[Pages the panel brings](controlpanel-json.md#pages-the-panel-brings). Those
make good examples: `ovos_webui/bundled/`.

## 6. When a file is not enough

A drawing editor, a live preview, a flow of its own: what a file cannot say
goes in a **panel extension**, a package that registers a Python page with its
own HTML and routes. It runs in the panel, needs the panel's web packages, and
shows in this panel only, so it is the exception. See
[Panel extensions](pages.md#panel-extensions) and, as an example,
[ovos-control-panel-mark1](https://github.com/andlo/ovos-control-panel-mark1).

## Check your file

- The [JSON Schema](controlpanel.schema.json) catches a wrong key or type in
  an editor. Name it at the top of the file, and the panel passes the line by:

  ```json
  {"$schema": "https://raw.githubusercontent.com/OpenVoiceOS/ovos-control-panel/dev/docs/controlpanel.schema.json",
   "controlpanel": 1, ...}
  ```
- The panel names a file it left out, and why, on the About page.
- The panel's test `test_every_page_the_panel_brings_is_sound` shows how to
  check a file and its strings in your own tests.
