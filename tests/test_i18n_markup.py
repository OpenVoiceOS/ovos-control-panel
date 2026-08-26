"""The shipped markup must survive translation.

`applyI18n` swaps the text of every `[data-i18n]` element. An element holding
a control keeps that control, so only its own text is replaced; every other
element is one whole message and is replaced entire. A sentence that continues
*after* a control therefore cannot be translated -- the tail stays in English
beside the translation of the same sentence.

These tests pin both halves of the contract: no message strands English after a
control, and the English written on the page is the same English shipped in
en.json, so correcting one can never leave the other behind.
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from ovos_webui.service import STATIC_DIR

VOID = {"br", "img", "input", "meta", "link", "hr", "source"}
CONTROLS = {"input", "select", "textarea", "button"}


def _pages():
    return sorted(Path(STATIC_DIR).glob("*.html"))


def _en():
    return json.loads((Path(STATIC_DIR) / "i18n" / "en.json").read_text(encoding="utf-8"))


class _Marked(HTMLParser):
    """Collect every [data-i18n] element with its text and child elements."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.found = []

    def handle_starttag(self, tag, attrs):
        if self.stack:
            self.stack[-1]["seq"].append(("el", tag))
        if tag in VOID:
            return
        self.stack.append({"tag": tag, "key": dict(attrs).get("data-i18n"), "seq": []})

    def handle_startendtag(self, tag, attrs):
        if self.stack:
            self.stack[-1]["seq"].append(("el", tag))

    def handle_endtag(self, tag):
        while self.stack:
            frame = self.stack.pop()
            if frame["key"]:
                self.found.append(frame)
            if self.stack and frame["tag"] not in CONTROLS and not frame["key"]:
                # <code>/<em> text belongs to the sentence that encloses it. A
                # child carrying its own key is its own message, and a control's
                # own contents (<option>s) are never part of one.
                self.stack[-1]["seq"].extend(frame["seq"])
            if frame["tag"] == tag:
                break

    def handle_data(self, data):
        if self.stack and data.strip():
            self.stack[-1]["seq"].append(("txt", data))


def _marked(path):
    parser = _Marked()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.found


@pytest.mark.parametrize("path", _pages(), ids=lambda p: p.name)
def test_no_translated_element_strands_an_english_tail(path):
    stranded = []
    for frame in _marked(path):
        seq = frame["seq"]
        control = next(
            (i for i, (kind, name) in enumerate(seq) if kind == "el" and name in CONTROLS), None
        )
        if control is None:
            continue  # no control: the whole element is replaced, nothing strands
        # `firstTextNode` scans every child, so text sitting only AFTER the
        # control is still the first text run and translates correctly. It is
        # a stranded tail only when a message already started before it.
        head = "".join(v for kind, v in seq[:control] if kind == "txt").strip()
        tail = "".join(v for kind, v in seq[control + 1:] if kind == "txt").strip()
        if head and tail:
            stranded.append(
                f"{frame['key']}: English left after the control: {tail[:60]!r}"
                " -- move it into its own element"
            )
    assert not stranded, (
        f"{path.name} would show a translation followed by untranslated English:\n  "
        + "\n  ".join(stranded)
    )


@pytest.mark.parametrize("path", _pages(), ids=lambda p: p.name)
def test_page_english_matches_the_english_locale(path):
    en = _en()
    drifted = []
    for frame in _marked(path):
        key = frame["key"]
        if key not in en:
            continue
        seq = frame["seq"]
        control = next(
            (i for i, (kind, name) in enumerate(seq) if kind == "el" and name in CONTROLS), None
        )
        if control is not None:
            # A label around a control: `applyI18n` swaps its first text run, so
            # that run is the message and nothing after the first child is.
            first_child = next((i for i, (kind, _) in enumerate(seq) if kind == "el"), control)
            seq = seq[:first_child]
        # <code>/<em> inside a sentence are part of the message: their text counts.
        page = " ".join("".join(v for k, v in seq if k == "txt").split())
        if not page:
            if control is not None:
                # `firstTextNode` returns None, so nothing is ever replaced and
                # the element stays English in every locale, silently.
                drifted.append(
                    f"{key}: has a control but no text of its own, so it can "
                    "never be translated -- move the text into its own element"
                )
            continue
        if page != " ".join(en[key].split()):
            drifted.append(f"{key}:\n      page    : {page[:90]!r}\n      en.json : {en[key][:90]!r}")
    assert not drifted, (
        f"{path.name} ships English that differs from en.json, so correcting one "
        f"leaves the other stale:\n    " + "\n    ".join(drifted)
    )


def test_javascript_fallbacks_match_the_english_locale():
    en = _en()
    call = re.compile(r'\bt\(\s*"([a-zA-Z0-9_.]+)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)')
    drifted = []
    for path in _pages() + [Path(STATIC_DIR) / "app.js"]:
        for key, raw in call.findall(path.read_text(encoding="utf-8")):
            if key not in en:
                continue
            fallback = raw.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
            if fallback != en[key]:
                drifted.append(
                    f"{path.name} {key}:\n      fallback: {fallback[:90]!r}\n      en.json : {en[key][:90]!r}"
                )
    assert not drifted, (
        "a t(key, fallback) call ships English that differs from en.json, so a "
        "reader whose locale fails to load sees the stale text:\n    " + "\n    ".join(drifted)
    )


def test_applyi18n_replaces_whole_messages_and_spares_controls():
    """`applyI18n` must branch on whether a control is inside the element.

    An element holding a control keeps it, so only the element's own first text
    node may be swapped. Every other element is one message and must be replaced
    entire -- swapping only its first text node leaves the English written after
    a `<code>` or `<em>` child sitting on the page next to the translation of the
    same sentence.

    This guards the shape of the branch. The behaviour itself is covered by
    `test_no_translated_element_strands_an_english_tail`, which pins the markup
    the branch relies on.
    """
    source = (Path(STATIC_DIR) / "app.js").read_text(encoding="utf-8")
    body = source.split("function applyI18n(root)", 1)
    assert len(body) == 2, "applyI18n is no longer declared as a function"
    body = body[1].split("function setLangDir", 1)[0]

    guard = 'querySelector("input,select,textarea,button")'
    assert guard in body, "applyI18n no longer checks for a control"
    assert "firstTextNode(node)" in body, "applyI18n no longer uses firstTextNode"
    assert body.index(guard) < body.index("firstTextNode(node)"), (
        "applyI18n must test for a control before it falls back to firstTextNode; "
        "otherwise a sentence with a <code> child keeps its English tail when translated"
    )
    assert "node.textContent = STRINGS[key]" in body, (
        "an element without a control must have its whole text replaced, not just "
        "its first text node"
    )
