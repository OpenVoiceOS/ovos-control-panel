# Pages: how the control panel is put together

> **Status: partly built.** Comments go in #115.
>
> - **Built:** the registry and the `opm.control_panel.page` entry point, the
>   checks on a page description, groups a page brings, the menu built from
>   the registry, `needs`, icons, `heading`, `routes`, `assets`, per-page
>   `i18n`, wrapping a page's body in the shell, and the list of pages on the
>   About page. Every one of the panel's own pages uses it: each is a body in
>   its own folder, with its own routes and strings where it has any. What
>   several pages share (configuration, plugins and installs, voice, events,
>   system actions, sign in) stays with the shell.
>   `webui.pages`, `webui.groups` and `webui.branding` (name, logo, colours)
>   are built too.
> - **Not yet:** the bus bridge, and `manual` in `webui.branding`.

The control panel is a small shell. The shell does the sign in, the menu,
the languages, the look and the safety checks. Everything you see in the menu
is a **page**, and every page is registered the same way, whether it ships with
the panel, with a plugin, with a skill, or in a package written only to extend
the panel.

The panel's own pages use the same mechanism as everyone else's. So moving a
page out of the panel later (the Mark-1 page to the Mark-1 plugin, say) is a
matter of moving a folder.

## Contents

- [Two kinds of page](#two-kinds-of-page)
- [Pages described in a file](#pages-described-in-a-file)
- [Registering a page](#registering-a-page)
- [The page description](#the-page-description)
- [The menu](#the-menu)
- [Languages](#languages)
- [The bus bridge](#the-bus-bridge)
- [Pages with their own routes](#pages-with-their-own-routes)
- [What the shell gives a page](#what-the-shell-gives-a-page)
- [Configuration](#configuration)
- [Branding](#branding)
- [Trust and safety](#trust-and-safety)
- [The core pages](#the-core-pages)
- [Versions](#versions)
- [Open questions](#open-questions)

## Two kinds of page

| | Data page | Page with routes |
| --- | --- | --- |
| Made of | HTML, JS, CSS, images, language files | the same, plus Python |
| Talks to the device | over the [bus bridge](#the-bus-bridge) | over its own API routes, and the bus bridge |
| Needs | nothing extra | FastAPI, in the panel's environment |
| Meant for | skills, PHAL plugins, hardware, distributions | the panel's own heavy pages (Plugins, Backup, Settings) |

A data page is the normal case. A skill or a PHAL plugin can ship one without
adding a single dependency, because the page is only files, and everything it
does goes over the message bus that the plugin already listens to.

## Pages described in a file

A skill or plugin can describe its page in `controlpanel.json` instead of
bringing HTML and Python. The panel draws it and talks to the skill over the
bus, sending only what the file declares. This is the way new pages should
be made; HTML pages (below) stay for what does not fit.

The file sits at the root of the package, next to `skill.json`. The panel
finds it in the installed OVOS packages without importing them, so no code
from the package runs in the panel. Its strings go in
`locale/<lang>/controlpanel.json` (`da-DK` or `da`), next to the skill's
other locale files; a label can also carry its English text in the file
(`{"key": "midi.title", "en": "MIDI"}`). The panel has the common words
itself: `common.save`, `common.delete`, `common.play`, `common.stop`,
`common.download`, `common.rename`, `common.sure` and more.

```json
{
  "controlpanel": 1,
  "id": "jamband",
  "title": "jamband.title",
  "group": "music",
  "order": 10,
  "icon": "controlpanel.svg",
  "bus": "ovos.jamband.",
  "blocks": [
    {"type": "text", "text": "jamband.intro"},
    {"type": "status", "query": "ovos.jamband.jams.list", "show": "playing",
     "text": "jamband.playing", "actions": [{"label": "common.stop", "send": "ovos.jamband.stop"}]},
    {"type": "list", "query": "ovos.jamband.jams.list", "items": "jams", "key": "id",
     "title": "{name}", "meta": "jamband.meta", "empty": "jamband.none",
     "split": {"by": "bundled", "false": "jamband.mine.title", "true": "jamband.skill.title"},
     "rename": {"field": "name", "send": "ovos.jamband.jams.rename", "when": "!bundled"},
     "actions": [
       {"label": "common.play", "send": "ovos.jamband.jams.play"},
       {"label": "jamband.midi", "download": "ovos.jamband.jams.midi",
        "file": {"data": "midi", "name": "{name}.mid", "type": "audio/midi"}},
       {"label": "common.delete", "send": "ovos.jamband.jams.delete", "when": "!bundled"}]}
  ]
}
```

The page around the blocks: `id`, `title`, `group` (default `everyday`),
`groups`, `order`, `icon` (an SVG in the package), `path` (default
`/<id>`), `heading`, `needs` (default: the package itself) and `bus`, the
prefix every message of the page starts with.

| Block | Fields |
|---|---|
| `text` | `text`: a label, and/or `steps`: labels shown as numbered steps. |
| `status` | `query`, `text` (a label with `{field}` from the answer) and/or `rows` (`label`, `value` with `{field}` or `text` a label, `when`, and `empty`, the label shown when the value is empty), `show` (a field that must be true), `actions`, `refresh` (seconds). |
| `list` | `query`, `items` (the answer's list), `key` (a row's id), `title` (`{field}`), `meta` (a label with `{field}`), `empty`, `split` (`by` a true/false field into two lists, each with a heading), `rename` (`field`, `send`, `when`, `max_length`), `actions` (one per row), `refresh`, `heading`. |
| `actions` | `actions`: buttons. |
| `form` | `fields` and `save`: `{"config": "PHAL.<package>", "reload": "<message>"}` writes in the plugin's own place in `mycroft.conf` and asks it to read it again; `{"send": "<message>"}` with a `query` sends the values to the skill. |
| `choice` | `param` and `options`: tabs whose value goes with every query on the page. |

An action is `{"label", "send"}`, with `data` it always sends (a test sound),
or a download, `{"label", "download", "file":
{"data": <answer field, base64>, "name": "{name}.mid", "type": <media type>}}`,
with `when` (`"field"` or `"!field"` on the row) and `confirm` (a label).
A field is `{"name", "label", "type"}`, the type one of `text`, `password`,
`url` (http:// or https://), `number`, `slider`, `checkbox`, `select`
(`options`, or `options_from` a query) and `lines`, with `required`, `hint`, `min`, `max`, `step` and `max_length`.
A field can have a `default` (a value equal to it is left out of
`mycroft.conf`, so the file says only what was changed), `show_when`
(`{"synth": "port"}`: shown only for that value of another field), and a
checkbox `on` and `off` values for a setting that is not true or false
(`"on": ["*"], "off": []`). A form saved in `mycroft.conf` sends its
`reload` message with the section as saved (`{"config": {...}}`).

In `{field}` a field can be nested (`{ports.outputs}`), a list is joined with
commas, a value can be shown as a date (`{saved:date}`) or a date and time
(`{last:time}`), both in seconds since 1970, or as a label
(`{engine@midi.engine}` shows the label `midi.engine.fluidsynth`, or nothing
when there is no such label; the label can hold the answer's values too).

A skill that answers with `{"error": ...}` can give a label of its page
(`"jamband.err.gone"`), shown in the reader's language; other text is shown
as it is.

A block this panel does not know is shown as "this part needs a newer control
panel"; the rest of the page still works.

### What a described page can and cannot do

- **No code.** The file is data; a file that does not follow the format is
  left out and named on the About page.
- **Only its own messages.** Every message starts with the page's `bus`
  prefix, and a prefix of OVOS's own (`mycroft.`, `ovos.skills.`,
  `ovos.phal.`, `system.`, `recognizer_loop:` and more) is refused.
- **Only the data it declared.** A request names a part of the page; the
  panel takes the message from the file and sends only a row's key, a
  rename's text, a choice from its options, or a form's fields, each checked
  against its type and length.
- **Changes need the token.** An action or a rename is privileged unless it
  says `"privileged": false`; a form always is. A download is a read unless
  it says otherwise.
- **Destructive actions ask.** A message with delete, remove, forget, reset,
  wipe or erase in it gets a confirmation if the file gives none.
- **A form writes only in the plugin's own place** in `mycroft.conf`
  (`PHAL.<package>`). A password is never sent back to the browser; an empty
  one keeps what is there.
- **Downloads** are only of a short list of types (MIDI, audio, PDF, plain
  text, JSON, CSV, images, EPUB), always as attachments.
- **Values are text.** What the skill answers is put on the page as text,
  never as HTML.

A package that has both a described page and an HTML page with the same id
keeps the described one.

## Registering a page

A package registers its pages under the `opm.control_panel.page` entry point
group, the same way it registers any other OVOS plugin:

```toml
[project.entry-points."opm.control_panel.page"]
emkay-guardian = "ovos_skill_guardian.panel:PAGE"
```

The entry point points at a page description: a dict, or a `ControlPanelPage`
from `ovos_webui.pages`. One package can register several pages.

The panel looks the group up when it starts. A page whose description is broken
is left out and named in the log and on the About page. It never stops the panel
from starting.

## The page description

```python
PAGE = {
    "api_version": 1,
    "id": "emkay-guardian",
    "path": "/emkay/guardian",
    "title": {"key": "guardian.title", "label": "Guardian"},
    "group": "emkay",
    "order": 20,
    "needs": ["ovos-skill-guardian"],
    "icon": "icon.svg",
    "html": "page.html",
    "assets": "static",
    "i18n": "i18n",
    "bus": {
        "emit": ["guardian.set_mode"],
        "listen": ["guardian.status", "guardian.mode_changed"],
        "privileged": ["guardian.set_mode"],
    },
    "manual": "https://openvoiceos.github.io/beta-technical-manual/guardian/",
}
```

| Field | Required | What it is |
| --- | --- | --- |
| `api_version` | yes | The version of this contract the page is written for. See [Versions](#versions). |
| `id` | yes | Unique, lowercase, `a-z0-9-`. Settings and logs refer to the page by it. |
| `path` | yes | Where the page is served. Must start with `/` and must not clash with another page or with `/api`, `/static`, `/login`, `/healthz`. A clash leaves the later page out. |
| `title` | yes | An i18n key and the English text. Used in the menu and the window title. |
| `heading` | no | An i18n key and the English text for the page's heading, when it should say more than the menu does ("About this device"). Default: the title. |
| `group` | yes | An existing group (`everyday`, `library`, `music`, `voice`, `understanding`, `device`, `screen`, `maintenance`) or a group the page defines. See [The menu](#the-menu). |
| `order` | no | Position within the group, lowest first. Default 100. |
| `needs` | no | Packages that make the page work; any one of them is enough. If none is installed on a device that shares the assistant's environment, the page leaves the menu, and says it needs the first one if you reach it anyway. |
| `icon` | no | An SVG file (at most 16 KB) in the page's folder. It is used as a mask, so it takes the menu's colour. |
| `html` | yes | The page's body, as a file name next to the module the entry point is in, or as `(package, name)`. The shell wraps it in the common header and menu, inside `<main>`; a `<style>` or `<script>` element in it stays where it is. A whole document (starting with `<!doctype html>`) is served as it is, with the menu added to its head. |
| `assets` | no | A folder of files served under `/pages/<id>/`: a path next to the module (it may have several parts, as `gui/images`), or `(package, path)` for a folder elsewhere in the page's package. |
| `i18n` | no | A folder of `<lang>.json` files. See [Languages](#languages). |
| `bus` | no | The messages the page may send and listen for. See [The bus bridge](#the-bus-bridge). |
| `routes` | no | Python only: a function that adds API routes. See [Pages with their own routes](#pages-with-their-own-routes). |
| `uploads` | no | Routes of the page's own that take an upload, with the largest body each may take: `{"/api/documents/upload": 50 * 1024 * 1024}`. Every other request is held to 1 MB. The panel caps a page's upload at 64 MB. |
| `manual` | no | Link for the "Learn more in the technical manual" line. |

The files are read with `importlib.resources`, so a page works from a wheel, a
zip or a source checkout alike.

## The menu

The menu is built by the shell from the registered pages. It is no longer
written into `app.js`.

A page picks a group. To define a new group, the page (or any page in the same
package) adds a `groups` entry:

```python
PAGE = {
    # ...
    "group": "emkay",
    "groups": [{"id": "emkay", "title": {"key": "emkay.group", "label": "Emkay"},
                "order": 15, "level": "advanced"}],
}
```

`level` is `everyday` (at the top: the `everyday` group's pages always show,
and any other everyday group, as Library and Music, is a row that folds its
pages open) or `advanced` (a foldable row inside Advanced, which itself folds
all the advanced groups away at once). A group with no pages left shows nothing. If two
packages define the same group id, the first one wins and the other is named in
the log; the panel's own groups always win, so a page may define one of them
too, for panels older than the group.

### Where a page comes from

The shell puts a quiet line at the foot of every page that is not the panel's
own: the skill's name from its `skill.json` in the device's language, and the
package and version. A page cannot leave it out. When two pages in the menu
have the same title, as two music services might, each also shows where it
comes from under its name in the menu.

Where the panel shows an icon for a skill or plugin (the Skills page, the
search results, the About page's list of pages) and the package brings none,
it shows its own, in grey because they are stand-ins: a speech bubble for a
skill, a plug for a PHAL plugin, a speaker for TTS, a microphone for STT, and
so on by kind (`KIND_ICONS`), and a puzzle piece for any other plugin. They are
in `static/icons/`.

How the menu behaves does not change: groups fold, the open ones are remembered,
the group of the page you are on opens, and pages the device cannot use leave
the menu.

The configuration can move, reorder and hide pages. See
[Configuration](#configuration).

### Where a page belongs

Pick the group by what the page is about, and an `order` between the panel's
own pages, which are numbered in tens so there is always room. Lowest first.

| Group | `order` | For | The panel's own pages |
| --- | --- | --- | --- |
| `everyday` | 0 | What most people use: always shown, at the top | Dashboard 10, Setup 20, Try it 30, Device 40, Network 50, Voice and language 60, Skills 70, Backup 80, About 90 |
| `library` | 5 | What the device reads and plays for you: documents, books, podcasts, news, radio. A foldable row under the everyday pages | Media 5 |
| `music` | 6 | Music you make with the device: playing along, lessons, karaoke, instruments. Shown like Library | |
| `voice` | 10 | How the device listens, speaks and translates | All voice settings 10, Servers 20, Translate 30 |
| `understanding` | 20 | How it understands and who answers | Intents 10, Transformers 20, Personas 30 |
| `device` | 30 | The hardware and what runs on it | System 10, Sensors 20 |
| `screen` | 40 | A device with a screen: what it shows | Apps 10, Wallpaper 20, Mark-1 faceplate 30 |
| `maintenance` | 50 | Keeping the panel and the device in shape | Plugins 10, Settings 20, Send over sound 30 |

Some examples:

- A page with facts about a device ("About Emkay") goes in `everyday` after
  About, `order` 95, or in `device`.
- A page for a skill that reads or plays something (documents, e-books, a
  podcast or news provider) goes in `library`; a page for making music
  (a jam band, lessons, an instrument) in `music`.
- A page that shows what is on the screen goes in `screen`.
- A distribution's own group sits between the panel's: `order` 15 puts it
  between Voice and Understanding.

A distribution can still move any page with `webui.pages.move`, so the place a
page picks is a sensible default, not a lock.

## Languages

Each page brings its own `i18n/<lang>.json` with its own keys. The shell merges
them with its own strings for the device language.

- A key the page does not have in the device language falls back to English,
  and then to the text in the HTML.
- The panel's own pages still have to have every key in every language the
  panel ships. The tests check this.
- Pages from other packages are not held to that. A page in English only works
  everywhere.
- Keys are global, so a page prefixes its own keys with its id or its group
  (`guardian.`, `emkay.`). The panel's own strings always win, so a page can
  not change what the shell or another page says. A key two pages define
  differently keeps the first, and the log says so.
- The merged strings for a language are served at `/static/i18n/<lang>.json`,
  where `app.js` has always fetched them. A file may be named for a language
  (`de.json`) or a language in a country (`de-DE.json`); the browser asks for
  the language, so a regional file counts for it.
- The menu data lists every language there are strings for, the panel's and
  the pages', so a page can bring a language the panel itself does not have.

## The bus bridge

The bus bridge lets a page talk to the device without Python of its own.

```js
const bus = OvosWebUI.bus("emkay-guardian");
bus.on("guardian.status", (data) => show(data));
await bus.emit("guardian.set_mode", {mode: "night"});
const reply = await bus.ask("guardian.get_status", {}, "guardian.status");
```

- A page can only send the message types it lists in `bus.emit`, and only hear
  the ones in `bus.listen`. The shell checks this on the server, not in the
  browser.
- A message type in `bus.privileged` needs the access token, as installing and
  device controls do today. Everything else follows the same rules as the rest
  of the panel's API.
- `ask` sends a message and waits for one reply, with a timeout, so a page can
  do request and answer without its own route.
- Message types are exact names. `*` is not allowed. A page that wants
  everything has to say so, message by message.
- Messages reach the page through one connection per browser tab, which the
  shell shares between all pages in that tab.

This is the part that makes data pages possible, and it is where most of the
care goes: the list in the page description is what stands between a page and
the whole bus.

## Pages with their own routes

A page in Python can add API routes:

```python
def routes(r):
    @r.api.get("/backup/history")
    def history(): ...

    @r.privileged.post("/backup/restore")
    def restore(body: RestoreBody): ...

PAGE = {..., "routes": routes}
```

`r` gives the page the panel's routers, with the sign in and the cross-site
checks already on them:

| Router | For |
| --- | --- |
| `r.api` | Reading and ordinary changes. Needs sign in when a token is set. |
| `r.privileged` | Anything that changes software or controls the device. Always needs the token. |
It also gives `r.need_bus()`, which returns the message bus or answers 503
when it is not reachable, and `r.config`, the panel's configuration module
(read and write the user's configuration layer, with backups). There is no
public router: only the shell answers without sign in.

A page's routes live under `/api/`, and the path should start with the page's
id or group. A page whose `routes` function fails, or that adds a route the
panel or an earlier page already has, is left out entirely, because its HTML
would not work without its routes.

## What the shell gives a page

The shell's own files are the public API for pages. Everything else in them is
internal and can change.

| | |
| --- | --- |
| `app.css` | The look: cards, buttons, tabs, lists, messages, light and dark. A page uses the classes and the CSS variables, so it follows the theme and the [branding](#branding). |
| `OvosWebUI.ready(fn)` | Runs the page once the menu, the language and the sign in are ready. |
| `OvosWebUI.api(path, options)` | Calls the panel's API with the cross-site header and the sign in. |
| `OvosWebUI.bus(pageId)` | The [bus bridge](#the-bus-bridge). |
| `OvosWebUI.t(key, fallback)` | A translated string. |
| `OvosWebUI.say(id, text, isError)` | Shows a message in an element on the page. |
| `OvosWebUI.confirmed(question)` | Asks before something that changes the device. |
| `OvosWebUI.installPackage(name)` | Installs a package, with the check before an install. |
| `OvosWebUI.esc(text)` | Escapes text for HTML. |

Pages run under the same Content Security Policy as today: scripts, styles,
images and connections from the panel's own origin only. A page cannot load
anything from the internet. An image from outside has to go through the panel,
as skill icons do.

## Configuration

Everything that decides what is shown is configuration, in `mycroft.conf`, in
the `webui` section. A distribution sets its defaults in the system layer, and
the user can change them in their own layer, as with the rest of OVOS.

```json
{
  "webui": {
    "pages": {
      "disabled": ["mark1", "sound"],
      "move": {"emkay-guardian": {"group": "device", "order": 5}}
    },
    "groups": {
      "order": ["voice", "emkay", "understanding", "device", "screen", "maintenance"],
      "rename": {"device": {"label": "Hardware"}}
    }
  }
}
```

- `pages.disabled` takes pages out entirely: no menu entry, and the page and
  its routes answer 404.
- `pages.move` puts a page in another group, or at another place in its group
  (`group`, `order`, or both).
- `groups.order` lists advanced groups to show first, in that order; the rest
  follow in their usual order. `groups.rename` gives a group another `label`,
  shown as written in every language (add a `key` to translate it).

The core pages cannot be disabled. A setting the panel cannot use is skipped
and named on the About page, which also lists the pages that are turned off.
A change shows on the next page load: the panel reads the user's layer again
for every page, so nothing needs a restart. See
[The core pages](#the-core-pages).

## Branding

A distribution can give the panel its own name and look, with configuration only:

```json
{
  "webui": {
    "branding": {
      "name": "Emkay",
      "logo": "/usr/share/emkay/logo.svg",
      "colors": {"accent": "#1f6feb", "accent-strong": "#1158c7"}
    }
  }
}
```

- `name` replaces "OpenVoiceOS" in the window title, on the Dashboard's
  heading and on the sign in page. At most 40 characters, no markup.
- `logo` replaces the waveform in the header. It is an SVG, PNG, JPEG or WebP
  file on the device, at most 512 KB, served by the panel at
  `/static/branding/logo`.
- `colors` set the theme's CSS variables for light mode, and `colors_dark`
  for dark mode: `bg`, `bg-soft`, `card`, `card-soft`, `ink`, `muted`, `line`,
  `accent`, `accent-strong`, `accent-hover`, `accent-ink`, `accent-wash`, `ok`,
  `warn`, `bad`. Only plain colour values (`#rrggbb`, `rgb()`, `hsl()`) are
  taken. The About page says when a light colour leaves text below a 4.5:1
  contrast.
- Not yet: `manual`, a base for the manual links.

Two more settings sit next to `branding` and say whether each viewer chooses
or the device decides:

```json
{"webui": {"theme": "dark", "text_size": "choose"}}
```

- `theme`: `choose` (the default: a button in the header), `dark` or `light`.
  A fixed theme is set on the page by the server, so it paints that way at
  once, and the header has no theme button.
- `text_size`: `choose` (the default), `normal`, `large` or `xlarge`, the same
  way. Larger text helps people who see less well, so a distribution should
  think twice before taking the button away.

### A distribution's own recommendations

Setup and the Plugins page recommend plugins for the device's language from
the recommendations that ovos-config ships (`ovos_config/recommends/<profile>/<lang>.conf`).
A distribution can ship its own, laid out the same way, and name the folder:

```json
{"webui": {"recommends": "/usr/share/emkay/recommends"}}
```

For a language the folder has a file for, its recommendations are used; for
any other language, OpenVoiceOS's own. `"openvoiceos"` uses OpenVoiceOS's own
even where the device came with others.

All of these can be changed on the Control panel page. What you choose there
goes in your own layer, so it wins over what the distribution set, and
"Back to the default" takes it out again.

The panel turns this into a small `branding.css` and loads it after `app.css`.
The name, the logo and the colours are public, like `app.css`, because the
sign in page wears them too.
A theme plugin can come later if a distribution needs more than this.

## Trust and safety

A page from another package runs with the panel's full trust. Its Python runs
in the panel's process, and its JavaScript runs on the panel's origin with your
sign in. That is acceptable because a page can only come from a package already
installed on the device, and installing a package already trusts it with
everything.

What the panel does about it:

- The About page lists every page, the package it comes from, and its version,
  so you can always see what has been added.
- A page from another package is marked as such in that list.
- The [bus bridge](#the-bus-bridge) only passes the messages a page has listed.
  That does not stop a hostile page, but it keeps an honest page from doing
  more than it says.
- `webui.pages.disabled` turns off any page that is not a core page.
- A page that fails to load is left out, and named on the About page, without
  taking the panel down.

## The core pages

These always ship with the panel and cannot be disabled, because without them
you cannot get the panel back into shape:

- sign in
- Dashboard
- Settings
- Plugins
- Skills
- Backup
- About
- Control panel (the panel's own settings: its name and colour, the added pages, the token)

Everything else, the panel's own pages included, can be disabled.

### Moving a page into its plugin

Several of the panel's own pages only talk to one PHAL plugin: Network to the
network-manager plugin, System to the system plugin, Mark 1, Sensors, Apps and
Wallpaper to theirs. They belong with that plugin, the way the MIDI page ships
with the MIDI plugin.

A plugin takes such a page over by bringing a page with the same `id` (and
usually the same `path`). The panel's own copy then steps aside, whichever is
loaded first, so a plugin can ship the page before the panel drops its copy.
The core pages above cannot be taken over. Until a page has moved, its
`needs` keeps it out of the menu on a device without the plugin.

## Versions

`api_version` is the version of this contract.

- The panel says which versions it supports, for example `1`.
- A page asking for a version the panel does not support is left out and named
  on the About page, with the version it wanted.
- A change that breaks pages raises the version. The panel keeps supporting the
  previous version for at least one release with the new one.
- New optional fields do not raise the version. A page that sets a field the
  panel does not know yet still loads, and the panel names the field in the log.

## Open questions

1. **The bus connection.** A WebSocket, or Server-Sent Events plus a POST for
   sending? Server-Sent Events are simpler behind proxies and fit the CSP as it
   is. A WebSocket is one connection both ways.
2. **Per-page settings.** Should a page be able to declare settings that the
   shell shows as a form, as `settingsmeta.json` does for skills? That would
   make simple pages need no HTML at all.
3. **Where a skill's page lives.** Data pages in a skill would be installed
   with the skill, in the skills service's environment. The panel can only find
   entry points in its own environment. On a device where the two differ, the
   skill would have to tell the panel about its page over the bus instead. Is
   that worth doing in version 1, or later?
4. **A page for one skill.** A skill's own page could also appear inside that
   skill's detail on the Skills page, instead of in the menu. One place, or
   both?

## What it means for the panel

1. This contract, and comments on it.
2. The registry and the bus bridge, with two or three of the panel's own pages
   moved over as proof. At least one of them is a data page.
3. The rest of the pages, then `webui.pages`, `webui.groups` and
   `webui.branding`.
4. The first page from outside the panel, as a data page in an Emkay skill.
