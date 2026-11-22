# Pages the panel describes

A folder here, named as the package (`ovos-skill-weather`), describes a page
for a skill or plugin that has no `controlpanel.json` of its own. Same format
and the same checks as the package's own file (see docs/pages.md), and:

- `"for"` says which versions it is for: `"for": "ovos-skill-weather>=1.0,<2"`.
  Another version gets no page rather than one that writes the wrong keys.
- It only does what the package already does: a form to the skill's
  `settings.json` or the plugin's own place in `mycroft.conf`, and bus messages
  the package already answers.
- The package's own file always wins.
- Each one should also go to the package as a pull request, so it can leave here.

`_plugin/` is not a package: it holds the strings of the page the panel makes
for a TTS or STT plugin that nobody describes (`described.plugin_page`).
