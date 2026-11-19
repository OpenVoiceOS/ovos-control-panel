
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

Without it those tests skip locally. CI installs the browser before the tests
(`pre_test_command` in `.github/workflows/build-tests.yml`) and sets
`OVOS_WEBUI_REQUIRE_BROWSER=1`, so there a missing browser fails the build
instead of skipping. Set the same variable locally to make sure the gate ran.
