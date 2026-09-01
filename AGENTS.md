
## Browser tests

`tests/test_pages_run.py` runs every page in a real browser and asserts its
script does not throw. Nothing else in the suite executes page JavaScript, so
without it a page whose script dies on load still passes everything: the
markup is there, the strings are there, the routes answer, and the page does
nothing.

It needs the Playwright browser, which is a separate download from the
Playwright package:

```bash
python -m playwright install chromium
```

Without it those tests skip. The shared build workflow has no hook to run a
command before the test step, so they currently skip in CI too — run them
locally before touching anything that ships JavaScript.
