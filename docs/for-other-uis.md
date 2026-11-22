# For other user interfaces

A `controlpanel.json` is data, not code, so any user interface can draw it:
Home Assistant, a phone app, a text screen. The page a skill or plugin
describes once then works in all of them. This page says how. The format
itself is in the [reference](controlpanel-json.md).

There are two ways in:

- **Through the panel.** The panel has found, checked and translated the page
  already; you draw it and send through the panel's API. This is the simple
  way when the panel runs on the device.
- **Straight from the package and the bus.** You read the file yourself and
  talk to the skill over the message bus. Then you take on the checks the
  panel does.

## Through the panel

Sign in as the panel's own pages do: with the access token as
`Authorization: Bearer <token>`. Reads need it when a token is set; changes
always need it.

### The pages

`GET /api/pages` lists the pages in the menu: `id`, `path`, `title`,
`group`, the `package` and `version` it comes from, and `described`: true for
a page made from a `controlpanel.json`, the ones you can draw yourself.

`GET /api/cp/<id>/page?lang=da` gives the page as the panel checked it:

```json
{
  "lang": "da",
  "page": {
    "id": "jamband",
    "blocks": [
      {"type": "text", "ref": "b0", "text": {"key": "jamband.intro"}},
      {"type": "list", "ref": "b1", "query": "ovos.jamband.jams.list", "items": "jams",
       "key": "id", "title": "{name}", "actions": [{"ref": "b1.a0", "label": {"key": "common.play"}, ...}]}
    ],
    "en": {"jamband.intro": "Play along with ..."}
  },
  "strings": {"jamband.title": "Jam band", "jamband.intro": "Spil med ..."}
}
```

Every part you can act on has a `ref`. A label is `{"key"}`: look it up in
`strings` (the package's own, in that language over English), then in
`page.en`, then in the panel's common words (`common.play`). Labels are not
filled in for you, because a label can hold values from an answer: see
[Templates](controlpanel-json.md#templates).

### Asking and acting

| Request | Body | Does |
| --- | --- | --- |
| `POST /api/cp/<id>/query` | `{"ref": "b1", "params": {"period": "week"}}` | Asks a status's or a list's `query`, and returns the answer. `params` are the page's `choice` values. A list that listens returns `{"items": [...]}`. |
| `POST /api/cp/<id>/act` | `{"ref": "b1.a0", "key": "<the row's key>"}` | Sends an action, or a rename with `"value"`. Needs the token. Returns the answer, or `{}` for one that gets none. |
| `POST /api/cp/<id>/act-open` | the same | An action marked `"privileged": false`. |
| `GET /api/cp/<id>/download?ref=b1.a1&key=...` | | A download; `download-locked` for one that needs the token. |
| `POST /api/cp/<id>/options` | `{"ref": "b3.form", "field": "voice"}` | A select's `options_from`. |
| `GET /api/cp/<id>/voices?ref=...&field=...&lang=da` | | A select's `voices`: the plugin's voices for a language. |
| `GET /api/cp/<id>/form?ref=b3.form` | | A form's values: from `mycroft.conf`, `settings.json` or the skill. A password comes as `{"set": true}`, never its value. |
| `POST /api/cp/<id>/form` | `{"ref": "b3.form", "values": {...}}` | Saves a form, after checking each value. Needs the token. |
| `POST /api/cp/<id>/upload` | multipart: `ref`, `file`, the field | An upload. Needs the token. |
| `GET /api/cp/<id>/module?ref=b2.module` | | A `module` block: whether the plugin is in use or the fallback. |
| `POST /api/cp/<id>/module` | `{"ref": ..., "as": "module" or "fallback_module"}` | Makes it so. Needs the token. |
| `POST /api/cp/<id>/module/test` | `{"ref": ..., "text": "...", "lang": "da"}` | Speaks the sentence, when the plugin is the voice in use. |

An error is an HTTP status with `{"detail": ...}`: `400` for a value the
file does not allow, `403` without the token, `504` when the skill did not
answer, and the skill's own `{"error": ...}` as `400` with its text or label.

### The Setup guide

`GET /api/setup/guide` gives the steps of the device's Setup guide, as the
distribution chose them ([webui.setup](setup.md#a-distributions-own-guide)):

```json
{"custom": true, "intro": {"key": "house.setup.intro", "label": "..."},
 "steps": [{"id": "language"},
           {"id": "house", "heading": "Devices in the house", "heading_key": "house.heading",
            "page": {"id": "house", "blocks": [...], "en": {...}}},
           {"id": "tryit"}],
 "problems": []}
```

A step with a `page` is a described page: draw its blocks as above, and ask
and act on them under `/api/cp/<id>/`. The other ids are the panel's own steps
(`token`, `language`, `voice`, `speak`, `tryit`, `wake`); draw your own for
those you have, and skip the rest. `custom` is false when the device has no
guide of its own.

### A skill's settings

A skill with only a `settingsmeta.json` has no page, but its settings form is
there too: `GET /api/skills/<skill id>?lang=da` returns it as `form`, with the
texts in that language. See
[Settings in your language](skills.md#settings-in-your-language).

## Straight from the package and the bus

### Finding the files

The file is `controlpanel.json` at the root of an installed package's code,
with `locale/<lang>/controlpanel.json` beside it: see
[Where the files go](controlpanel-json.md#where-the-files-go). Look in the
packages that are skills or plugins; do not import them to find it. Pages the
panel brings for packages without one are in the panel's
`ovos_webui/bundled/<package>/`, each with the versions it is for in `for`.

Draw a version of the format you know (`"controlpanel": 1`), and draw a block
you do not know as "needs a newer version", as the panel does.

### Talking to the skill

Each part's message is in the file. Send it on the bus and wait for the
answer, the type with `.response` on the end (`message.response()`), for up to
ten seconds:

| Part | Send | Data |
| --- | --- | --- |
| status, list | `query` | the page's choice values |
| list that listens | nothing: listen to the `listen` messages, keep the latest per `key` | |
| action | `send` | the action's `data`, the row's `key` field, the choice values |
| action marked `"answer": false` | `send`, and do not wait | the same |
| download | `download` | the row's key; the answer's `file.data` field is base64 |
| rename | `rename.send` | the row's key and the new text in `rename.field` |
| form saving with `send` | `save.send` | the values; `query` reads them |
| upload | `send`, once per 512 KB part | `upload`, `name`, `part`, `parts`, `data`, the field |

A form that saves in `config` or `settings` does not go to the skill: write
the values yourself in the plugin's section of the user's `mycroft.conf`
(then send `save.reload` with `{"config": <the section>}`), or in the skill's
`settings.json`. A `module` block is yours to draw: it reads and writes
`tts.module` / `stt.module` and their fallbacks.

### The checks you take on

The panel is what keeps a page to its word. Without it, do the same:

- send only messages under the page's `bus` prefix, never under a reserved
  one, and for a page the panel brings, only its `messages`;
- send only the data the file declares, each value checked against its field;
- write a form only in the package's own place;
- ask before a destructive action;
- show what a skill answers as text, never as HTML;
- keep changes behind your own sign in.

The [JSON Schema](controlpanel.schema.json) checks the shape of a file; the
rules above are what the panel adds on top.
