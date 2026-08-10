# Accessibility and languages

## Accessibility

The interface is built to be used without sight or a mouse.

- Every page starts with a **Skip to content** link, so a keyboard or screen
  reader user can jump past the navigation.
- The page is one `header`, one `nav` (named for a screen reader), and one
  `main` landmark, so a screen reader can move between them.
- Every control has a real label, and the keyboard focus ring is always
  visible.
- Status that changes on its own — the service checks on the dashboard, the
  "saved" and error messages, the insecure-network warning — is announced to a
  screen reader as it changes.
- The colour of a status is never its only signal: each one also carries a
  word (`ready`, `starting`, `no answer`).
- Motion is small, and it is turned off for anyone who asks the system to
  reduce motion.

## Languages and right-to-left

The interface follows the device language. Set `lang` in `mycroft.conf` (for
example `ar-sa`, `he-il`, `pt-pt`) and the page shows that language and, for a
right-to-left language, flips the whole layout to read right-to-left.

![The dashboard in Arabic, right-to-left](images/dashboard-rtl-arabic.png)

![The settings page in Arabic, right-to-left](images/settings-rtl-arabic.png)

Translations live in `ovos_webui/static/i18n/`, one file per language, keyed by
the same short keys the pages carry. English is written into the pages
themselves and is the fallback, so a missing translation shows English rather
than nothing. To add a language, copy `en.json` to `<code>.json` and translate
the values. See `ovos_webui/static/i18n/README.md`.
