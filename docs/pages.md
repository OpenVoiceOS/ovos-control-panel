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

`level` is `everyday` (always shown, at the top; a group other than `everyday`
itself gets a small heading, as Library and Music do) or `advanced` (a foldable
row under Advanced, as today). A group with no pages left shows nothing. If two
packages define the same group id, the first one wins and the other is named in
the log; the panel's own groups always win, so a page may define one of them
too, for panels older than the group.

### Where a page comes from

The shell puts a line at the top of every page that is not the panel's own:
the page's icon, the skill's name from its `skill.json` in the device's
language (with the skill's own icon, when it has one), and the package and
version. A page cannot leave it out. When two pages in the menu have the same
title, as two music services might, each also shows where it comes from under
its name in the menu.

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
| `library` | 5 | What the device reads and plays for you: documents, books, podcasts, news, radio. Shown under the everyday pages, with a heading | Media 5 |
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

Everything else, the panel's own pages included, can be disabled. In time, a
page that belongs with a plugin can move there.

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
