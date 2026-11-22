# Pages: how the control panel is put together

The control panel is a small shell. The shell does the sign in, the menu,
the languages, the look and the safety checks. Everything you see in the menu
is a **page**.

There are two ways to give the panel a page:

- **`controlpanel.json`, the normal way.** A skill or plugin describes its
  settings, status, lists and buttons in a file, and the panel draws it. It is
  data, no code, so another user interface (Home Assistant, a phone app) can
  draw the same file. Until a plugin brings one, the panel may bring one for
  it, in its `bundled/` folder.
- **A panel extension, for what a file cannot say.** A package written only
  to add a richer page to this panel (the Mark-1 drawing editors and firmware
  updates, in `ovos-control-panel-mark1`) registers a Python page. It runs
  code in the panel and shows only here, so it is the exception.

| To | Read |
| --- | --- |
| give a skill or plugin a page | [the guide](guide-pages.md) |
| look up a block, a field or a rule | [the controlpanel.json reference](controlpanel-json.md) |
| draw the same pages in another user interface | [For other user interfaces](for-other-uis.md) |
| check a file in an editor or CI | [the JSON Schema](controlpanel.schema.json) |
| write a Python page: the panel's own, or an extension | this page |

This page is about the Python pages, and about what every page shares: the
menu, the languages, the configuration, the branding and the trust.

## Contents

- [Panel extensions](#panel-extensions)
- [The page description](#the-page-description)
- [The menu](#the-menu)
- [Languages](#languages)
- [Pages with their own routes](#pages-with-their-own-routes)
- [What the shell gives a page](#what-the-shell-gives-a-page)
- [Configuration](#configuration)
- [Branding](#branding)
- [Trust and safety](#trust-and-safety)
- [The core pages](#the-core-pages)
- [Versions](#versions)

## Panel extensions

The panel's own pages are Python modules in `ovos_webui/pages/`, each listed
in `BUILTIN` and each with a `PAGE` description. A **panel extension** adds a
page the same way: a package, installed beside the panel, that registers its
page description under the `opm.control_panel.page` entry point group:

```toml
[project.entry-points."opm.control_panel.page"]
mark1 = "ovos_control_panel_mark1:PAGE"
```

Use one only for what `controlpanel.json` cannot say: a drawing editor, a
live preview, a flow of its own. An extension runs in the panel's process,
needs the panel's web packages, and is drawn by no other user interface. A
plugin's settings and buttons belong in its `controlpanel.json`. A package
that has both keeps the described page.

An extension's page with the same `id` as a page the panel describes for a
plugin takes its place: the panel's plain Mark-1 page says the extension
exists, and steps aside when it is installed.

A page whose description is broken is left out and named in the log and on
the About page. It never stops the panel from starting.

## The page description

This is the description of a Python page: one of the panel's own, or an
extension's.

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
    "routes": routes,
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
| `html` | yes | The page's body, as a file name next to the page's module, or as `(package, name)`. The shell wraps it in the common header and menu, inside `<main>`; a `<style>` or `<script>` element in it stays where it is. A whole document (starting with `<!doctype html>`) is served as it is, with the menu added to its head. |
| `assets` | no | A folder of files served under `/pages/<id>/`: a path next to the module (it may have several parts, as `gui/images`), or `(package, path)` for a folder elsewhere in the page's package. |
| `i18n` | no | A folder of `<lang>.json` files. See [Languages](#languages). |
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
| `screen` | 40 | A device with a screen: what it shows | Apps 10, Wallpaper 20, Mark-1 faceplate 30 (pages the panel brings) |
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
      "disabled": ["personas", "sound"],
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

The Setup guide is chosen the same way, in `webui.setup`: which of the
panel's steps, in which order, and described pages as steps of their own. See
[A distribution's own guide](setup.md#a-distributions-own-guide).

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

### The largest file

`webui.max_upload_mb` is the largest file, in MB, that a page may put on the
device: 1024 (enough for a film) unless it is set. It is set on the Control
panel page, or by a distribution that is never meant to hold films. A page
that writes files in parts reads it with
`ovos_webui.configio.max_upload_mb()` (the Media extension does); each request
is still held to the page's own `uploads` size.

## Trust and safety

A panel extension runs with the panel's full trust. Its Python runs in the
panel's process, and its JavaScript runs on the panel's origin with your sign
in. That is acceptable because a page can only come from a package already
installed on the device, and installing a package already trusts it with
everything.

What the panel does about it:

- The About page lists every page, the package it comes from, and its version,
  so you can always see what has been added.
- A page from another package is marked as such in that list.
- A page described in a `controlpanel.json` runs no code at all, and the panel
  sends only the messages and the data its file declares: see
  [What the panel checks](controlpanel-json.md#what-the-panel-checks).
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

A page of the panel's own that only talks to one plugin belongs with that
plugin. Apps, Wallpaper, Sensors and Mark 1 have moved: the panel now brings a
`controlpanel.json` for each, and the plugin can take it over by shipping its
own. Network and System stay for now; they should follow.

A plugin takes such a page over by bringing a page with the same `id` (and
usually the same `path`). The panel's own copy then steps aside, whichever is
loaded first. The core pages above cannot be taken over. An extension's page
also takes the place of a page the panel brings for a plugin.

## Versions

`api_version` is the version of the Python page contract. The version of
`controlpanel.json` is its own: see
[Versions and older panels](controlpanel-json.md#versions-and-older-panels).

- The panel says which versions it supports, for example `1`.
- A page asking for a version the panel does not support is left out and named
  on the About page, with the version it wanted.
- A change that breaks pages raises the version. The panel keeps supporting the
  previous version for at least one release with the new one.
- New optional fields do not raise the version. A page that sets a field the
  panel does not know yet still loads, and the panel names the field in the log.
