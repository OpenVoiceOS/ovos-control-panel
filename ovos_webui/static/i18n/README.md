# UI translations

Each file is one language, keyed by the same short keys the pages carry in
`data-i18n` attributes and the scripts pass to `OvosWebUI.t`. English is the
fallback: it is written into the pages themselves, so a missing key or a
missing file never breaks a page — it just shows English.

To add a language, copy `en.json` to `<code>.json` (the base language code,
e.g. `pt.json`, `de.json`) and translate the values. A right-to-left language
(`ar`, `he`, `fa`, `ur`, …) also flips the whole layout automatically.
