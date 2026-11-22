# controlpanel.json: the reference

This is every part of the `controlpanel.json` format, version 1, as the panel
checks it. To make a first page, start with the
[guide](guide-pages.md). To draw the same file in another user interface, see
[For other user interfaces](for-other-uis.md). The
[JSON Schema](controlpanel.schema.json) says the same as this page in a form
an editor or CI can check.

## Contents

- [Where the files go](#where-the-files-go)
- [The page](#the-page)
- [Labels and strings](#labels-and-strings)
- [Templates](#templates)
- [Blocks](#blocks)
- [Actions](#actions)
- [Fields](#fields)
- [Messages](#messages)
- [What the panel checks](#what-the-panel-checks)
- [Pages the panel brings](#pages-the-panel-brings)
- [Versions and older panels](#versions-and-older-panels)

## Where the files go

| File | Where |
| --- | --- |
| `controlpanel.json` | At the root of the package's code, next to `skill.json` and `locale/`. At most 256 KB. |
| `locale/<lang>/controlpanel.json` | The page's strings, one file per language: `da-DK`, `da` and `da_DK` all count as `da`. At most 256 KB each. |
| The icon | An SVG of at most 16 KB, named by `icon`, next to `controlpanel.json`. |
| Pictures | A folder named by `pictures`, as `gui/images`. |

All of them must be in the package's data (`package-data` in
`pyproject.toml`), or a wheel leaves them out. The panel finds the file in the
installed OVOS packages without importing them, so no code from the package
runs in the panel.

## The page

```json
{
  "controlpanel": 1,
  "id": "jamband",
  "title": "jamband.title",
  "group": "music",
  "order": 10,
  "icon": "controlpanel.svg",
  "bus": "ovos.jamband.",
  "blocks": [ ... ]
}
```

| Key | Required | What it is |
| --- | --- | --- |
| `controlpanel` | yes | The version of the format: `1`. |
| `id` | yes | The page's id: lowercase, `a-z0-9-`, at most 64. Settings and logs use it. |
| `title` | yes | A [label](#labels-and-strings): the name in the menu and the window title. |
| `heading` | no | A label for the page's heading, when it should say more than the menu. Default: the title. |
| `path` | no | Where the page is served. Default `/<id>`. Not under `/api`, `/static`, `/pages`, `/login`, `/logout` or `/healthz`, and not another page's path (a clash leaves the later page out). |
| `group` | no | The menu group: `everyday` (the default), `library`, `music`, `voice`, `understanding`, `device`, `screen`, `maintenance`, or one the page defines in `groups`. See [Where a page belongs](pages.md#where-a-page-belongs). |
| `groups` | no | Groups the page brings: `{"id", "title", "order", "level": "everyday" or "advanced"}`, the title a key or `{"key", "label"}` with its English text. The panel's own groups always win. |
| `order` | no | The place in the group, lowest first. Default 100. |
| `needs` | no | Packages that make the page work, any one enough. Default: the package itself. |
| `icon` | no | The SVG, used as a mask so it takes the menu's colour. |
| `pictures` | no | A folder in the package whose pictures are served under `/pages/<id>/`: PNG, JPEG, GIF, WebP and SVG, nothing else. A list can show them (`picture`). |
| `bus` | yes, or `messages` | The prefix every message of the page starts with, ending in a dot: `ovos.jamband.`. |
| `messages` | no | Only in a page [the panel brings](#pages-the-panel-brings): the exact messages it may use, under any prefix. |
| `for` | only there | Only in a page the panel brings: the package and the versions it was written for. |
| `blocks` | yes | The page, top to bottom. At most 50. |

## Labels and strings

A **label** is a key, as `"jamband.title"`, looked up in
`locale/<lang>/controlpanel.json` in the reader's language, then English. A
label can also carry its English text in the file:
`{"key": "jamband.title", "en": "Jam band"}`.

Keys are global, so prefix them with the page's id. The panel has the common
words itself, and its own strings always win:

`common.save`, `common.saved`, `common.delete`, `common.play`,
`common.stop`, `common.download`, `common.rename`, `common.name`,
`common.sure`, `common.cancel`, `common.done`, `common.loading`,
`common.none`, `common.all`, `common.refresh`, `common.noanswer`, `common.needed`.

A skill's settingsmeta texts go in the same file: see
[Settings in your language](skills.md#settings-in-your-language).

## Templates

A list's `title` and `text`, a status row's `value`, and the text of any label
can hold values from the answer:

| Template | Shows |
| --- | --- |
| `{name}` | The field. Nested with dots: `{ports.outputs}`. A list is joined with commas. Nothing when it is not there. |
| `{saved:date}` | A date, from seconds since 1970, in the reader's language. |
| `{last:time}` | A date and a time, the same way. |
| `{engine@midi.engine}` | The label `midi.engine.<value>`, as `midi.engine.fluidsynth`, or nothing when there is no such label. The label may hold values too. |

## Blocks

Every block has a `type` and may have a `heading` (a label). A block of a type
this panel does not know is drawn as "this part needs a newer control panel";
the rest of the page still works.

### text

| Key | |
| --- | --- |
| `text` | A label. |
| `steps` | Up to 20 labels, shown as numbered steps. With or without `text`. |

### status

Asks once, and shows the answer.

| Key | |
| --- | --- |
| `query` | The message to ask. |
| `text` | A label, with templates. |
| `rows` | `{"label", "value"}`: a label and a value with templates; or `{"label", "text"}` with a label as the value. `empty`: a label shown when the value is empty. `when`: a [condition](#conditions). A row with no `label` is a note across the card. |
| `show` | A field that must be true for the card to show at all (a card for "playing now"). |
| `actions` | [Buttons](#actions) under it. Their `when` is read on the answer. |
| `refresh` | Ask again every so many seconds, 2 to 3600. |

### list

| Key | |
| --- | --- |
| `query` | The message to ask; or `listen`, below. |
| `items` | The field of the answer that holds the rows. Default `items`. A list of text has rows with that text as their `key`. |
| `key` | The field that tells a row from the others. Default `id`. It goes with every row's action. |
| `title` | The row's title, a template. Default `{<key>}`. |
| `text` | The row's text under its title, a template. |
| `meta` | A label with templates, under it in small text. |
| `picture` | A field holding a file name in the page's `pictures`, shown beside the row. A row without one keeps the place, so the rows line up. |
| `empty` | A label for no rows. |
| `split` | `{"by", "true", "false"}`: two lists by a true/false field, each with its label as heading. |
| `filter` | `{"by", "label", "all"}`: a choice of the values of a field above the list, made in the browser. `all` is the label for no filter (default `common.all`). |
| `rename` | `{"field", "send", "when", "max_length", "label", "privileged"}`: the row's name as a text box, sent with the row's key and the new text in `field`. |
| `actions` | Buttons on each row. |
| `refresh` | Ask again every so many seconds. |
| `listen` | Instead of `query`: up to five of the page's messages that a plugin broadcasts and never answers (a sensor's readings). The panel keeps the latest message of each `key`, with `heard`, when it came, up to 200 rows, from the first time the page is read, and the list reads them every five seconds. |

### actions

| Key | |
| --- | --- |
| `actions` | [Buttons](#actions) in a row. |

### form

| Key | |
| --- | --- |
| `fields` | The [fields](#fields). |
| `save` | Where the values go, one of the four below. `label`: a label for the button, where "Save" would be wrong. |
| `query` | With `save.send`: the message that reads the values to show. |

| `save` | |
| --- | --- |
| `{"config": "PHAL.<package>", "reload": "<message>"}` | Writes in the plugin's own place in `mycroft.conf`, then sends `reload` with `{"config": <the section as saved>}`. A plugin's own places are `PHAL.<package>` and the section its entry points name: `tts.<module>`, `stt.<module>`, `PHAL.<name>`, and for a transformer the section its service loads it from (`audio_transformers.<name>`, `utterance_transformers.<name>`, `metadata_transformers.<name>`, `intent_transformers.<name>`, `dialog_transformers.<name>`, `tts_transformers.<name>`). Never the choice of module itself. |
| `{"settings": true}` | Reads and writes the skill's own `settings.json`, merged over what is there so keys the form has not are kept; the skill reads them as `self.settings`. Only for a package that registers one skill. |
| `{"send": "<message>"}` | Sends the values to the skill; `query` reads them. |
| `{"send": "<message>", "answer": false}` | Sends the values, and no answer comes; there is nothing to read, so the form starts from its defaults (text for the Mark-1 mouth). |

A form always needs the access token.

### choice

| Key | |
| --- | --- |
| `param` | A field name. |
| `options` | `{"value", "label"}`: tabs. The chosen value goes as `param` with every query on the page (`today`, `week`). |

### upload

| Key | |
| --- | --- |
| `send` | The message each part goes in. |
| `accept` | The file endings it takes: `[".pdf", ".txt"]`. |
| `max_mb` | 1 to 64, default 10. |
| `field` | `{"name", "label", "max_length"}`: a text sent along, such as a title. |

The file reaches the skill in parts of 512 KB, each a message with `upload`
(one id for all the parts), `name` (a bare file name), `part` (from 0),
`parts`, `data` (base64) and the field. The answer to the last part is the
answer. An upload always needs the token.

### module

| Key | |
| --- | --- |
| `kind` | `tts` or `stt`, on the page of a package that brings one such plugin. |

The panel's own part: whether this plugin is the voice or the listener in use,
or the fallback, buttons to make it so, and for a voice in use, a sentence to
hear it. Nothing of it comes from the file.

## Actions

```json
{"label": "common.play", "send": "ovos.jamband.jams.play"}
```

| Key | |
| --- | --- |
| `label` | A label. |
| `send` | The message. On a row, the row's `key` goes with it. |
| `data` | An object it always sends (a test sound, a colour), at most 4 KB. |
| `answer` | `false` for a message that gets no answer: the panel sends it and is done. |
| `download` | Instead of `send`: a message whose answer is a file, with `file`: `{"data": <the answer's field, base64>, "name": "{name}.mid", "type": <media type>}`. |
| `when` | A [condition](#conditions): on a row, on the row; in a status, on the answer. |
| `confirm` | A label: asked before it is sent. |
| `confirm_text` | For what cannot be undone: a word in capitals, as `RESET`, the reader must type before it is sent; `confirm` is then the question that asks for it. |
| `done` | A label said once it is sent, in place of "Done.": "The device is wiping now and will restart." |
| `privileged` | Default `true`: it needs the token. A download defaults to `false`. |

The media types a download may have: `audio/midi`, `audio/mpeg`, `audio/ogg`,
`audio/wav`, `audio/flac`, `application/pdf`, `text/plain`,
`application/json`, `text/csv`, `image/png`, `image/jpeg`, `image/webp`,
`application/epub+zip`. It is always an attachment.

### Conditions

`"field"` is true when the field is (a list is true when it has items);
`"!field"` when it is not.

## Fields

```json
{"name": "host", "label": "server.host", "type": "url", "required": true}
```

| Key | |
| --- | --- |
| `name` | The setting's name: `a-z0-9_-`, starting with a letter or `_`. |
| `label` | A label. |
| `type` | `text`, `password`, `url` (http:// or https://), `number`, `slider`, `checkbox`, `select` or `lines` (one value per line, saved as a list). Default `text`. |
| `hint` | A label under it. |
| `required` | It must have a value to save. |
| `min`, `max`, `step` | For `number` and `slider`. |
| `max_length` | Default 300, at most 2000. |
| `default` | Shown when there is no value; a value equal to it is left out of `mycroft.conf`, so the file says only what was changed. |
| `show_when` | `{"synth": "port"}`: shown only for that value of another field. |
| `on`, `off` | For a checkbox whose setting is not true or false: `"on": ["*"], "off": []`. |
| `options` | For a select: `{"value", "label"}`. |
| `options_from` | For a select: `{"query", "items", "value", "label"}`, options read from the skill. |
| `voices` | For a select on a TTS plugin's page: `true`, the voices the plugin itself lists for the reader's language, read in a process of their own so its code never runs in the panel. |

A password is never sent back to the browser; an empty one keeps what is there.

## Messages

Every message the page sends starts with its `bus` prefix. A query or an
action is answered the usual OVOS way, with `message.response(data)`: the
type with `.response` on the end. The panel waits ten seconds.

The data a request carries is only what the file declared: a row's `key`, a
rename's text, a choice from its options, a form's fields, an action's `data`,
an upload's parts.

An answer with `{"error": ...}` is shown as an error: a label of the page
(`"jamband.err.gone"`) in the reader's language, or the text as it is.

## What the panel checks

- **No code.** The file is data. A file that does not follow the format is
  left out and named on the About page.
- **Only its own messages.** A prefix of OVOS's own (`mycroft.`,
  `ovos.skills.`, `ovos.phal.`, `enclosure.`, `system.`, `recognizer_loop:`,
  `speak`, `gui.` and more) is refused as `bus`.
- **Only the data it declared**, each value checked against its type and length.
- **Changes need the token.** An action and a rename unless they say
  `"privileged": false`; a form, an upload and the module buttons always.
- **Destructive actions ask.** A message with delete, remove, forget, reset,
  wipe or erase in it gets a confirmation if the file gives none.
- **A form writes only in the package's own place.**
- **Values are text.** What the skill answers goes on the page as text, never
  as HTML.

A package that has both a `controlpanel.json` and a Python page with the same
id keeps the described one.

## Pages the panel brings

For a skill or plugin with no `controlpanel.json` of its own, the panel can
bring one: `ovos_webui/bundled/<package>/controlpanel.json`, with its
`locale/` and icon, where `<package>` is the package's name as pip writes it
in lowercase (`ovos-phal-plugin-mk1`). It is the same format with the same
checks, and it says which versions it was written for:

```json
{"controlpanel": 1, "for": "ovos-phal-plugin-mk1>=0.1.0,<1", "id": "mark1", ...}
```

The package's own file wins; then the panel's for that version; then nothing.
A version the file was not written for gets no page rather than one that
writes the wrong keys. The page says at its foot that the panel described it.

A plugin that has answered bus messages for years did not pick them under a
prefix of the page's own, and many are under the reserved ones. So such a
page, and only such a page, may name the exact messages it uses, under any
prefix, in `messages` (up to 30). It is safe because the file is the panel's
own, read in the panel's review: a package cannot name them for itself. `bus`
is then not needed; with both, the page may use either.

Each such page should also go to the package as a pull request, so it can
leave the panel. The pages the panel brings today: the TTS and STT server
plugins, Piper, the app launcher, the wallpaper manager, ovos-PHAL-sensors, the
Mark-1 plugin and the system plugin.

## Versions and older panels

`controlpanel` is the version of the format. A file for a version this panel
does not draw is left out and named on the About page.

New blocks, keys and field types do not raise the version, so a file written
for a newer panel still works on an older one:

- a block it does not know is drawn as "this part needs a newer control panel";
- a key it does not know is passed by;
- a field type it does not know leaves the page out, so a form never writes a
  value it cannot check.

A change that would break files raises the version, and the panel draws the
previous one for at least one release with the new.
