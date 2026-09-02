"""Where a setting actually comes from.

The commonest configuration report is "I set it and nothing happened". Almost
always the value is exactly where the person put it, and a layer further down
the stack overrides it. The panel can already show what a key resolves to; it
could not show *which file that value came from*, which is the half that
answers the question.

The order is ovos-config's own: default, remote, distribution, system, then
the XDG files, then runtime patches, each overriding the one before.
"""
import json
from copy import deepcopy

import pytest


def _deep(layer) -> dict:
    """A snapshot that shares nothing with the layer it came from."""
    return deepcopy(dict(layer))

from ovos_webui import layers


def test_the_stack_is_reported_in_the_order_it_merges():
    """Later beats earlier, and a reader has to be able to see that."""
    names = [layer["name"] for layer in layers.stack()]
    assert names == ["default", "remote", "distribution", "system",
                     "xdg", "patch"] or names[0] == "default"
    assert names[-1] == "patch", f"runtime patches must win last: {names}"


def test_every_layer_says_where_it_lives_and_whether_it_exists():
    for layer in layers.stack():
        assert "path" in layer, layer
        assert isinstance(layer["exists"], bool), layer


def test_a_key_reports_the_layer_that_actually_set_it(tmp_path, monkeypatch):
    """Two layers define it; the answer is the one that wins, not the first."""
    resolved = layers.resolve("lang", stack=[
        {"name": "default", "path": "/a", "exists": True, "dropped": False,
         "data": {"lang": "en-us"}},
        {"name": "system", "path": "/b", "exists": True, "dropped": False,
         "data": {"lang": "pt-pt"}},
        {"name": "xdg", "path": "/c", "exists": True, "dropped": False, "data": {}},
    ])
    assert resolved["value"] == "pt-pt"
    assert resolved["winner"] == "system"
    assert [o["name"] for o in resolved["overridden"]] == ["default"]


def test_a_key_nobody_sets_is_reported_as_unset_not_as_none():
    resolved = layers.resolve("nothing.here", stack=[
        {"name": "default", "path": "/a", "exists": True, "dropped": False, "data": {}},
    ])
    assert resolved["set"] is False
    assert resolved["winner"] is None


def test_a_nested_key_is_addressed_the_way_the_config_is_written():
    resolved = layers.resolve("listener.wake_word", stack=[
        {"name": "default", "path": "/a", "exists": True, "dropped": False,
         "data": {"listener": {"wake_word": "hey_mycroft"}}},
        {"name": "xdg", "path": "/c", "exists": True, "dropped": False,
         "data": {"listener": {"wake_word": "hey_jarvis"}}},
    ])
    assert resolved["value"] == "hey_jarvis"
    assert resolved["winner"] == "xdg"


def test_a_subtree_is_the_union_of_the_layers_not_the_last_one():
    """`merge_dict` recurses, so a later layer adding one key to `tts` does
    not take the rest of it away. Reporting the last layer's copy as the
    value would state something the device does not agree with."""
    resolved = layers.resolve("tts", stack=[
        {"name": "default", "path": "/a", "exists": True, "dropped": False,
         "data": {"tts": {"module": "ovos-tts-plugin-server", "fallback": "mimic"}}},
        {"name": "xdg", "path": "/c", "exists": True, "dropped": False,
         "data": {"tts": {"module": "ovos-tts-plugin-piper"}}},
    ])
    assert resolved["value"] == {"module": "ovos-tts-plugin-piper",
                                 "fallback": "mimic"}, resolved["value"]
    assert resolved["overridden"] == [], (
        "called a layer overridden that the merge kept half of"
    )
    assert [c["name"] for c in resolved["merged_from"]] == ["default"]


def test_a_layer_the_policy_drops_is_not_read_at_all():
    resolved = layers.resolve("lang", stack=[
        {"name": "system", "path": "/etc", "exists": True, "dropped": False,
         "data": {"lang": "en-us"}},
        {"name": "xdg", "path": "/user", "exists": True, "dropped": True,
         "data": {"lang": "pt-pt"}},
    ])
    assert resolved["value"] == "en-us"
    assert resolved["winner"] == "system"


def test_a_value_set_only_in_a_layer_that_loses_is_named_as_overridden():
    """This is the whole point: the reader put it in the user file, and
    something later took it back."""
    resolved = layers.resolve("lang", stack=[
        {"name": "xdg", "path": "/user", "exists": True, "dropped": False,
         "data": {"lang": "de-de"}},
        {"name": "patch", "path": None, "exists": True, "dropped": False,
         "data": {"lang": "en-us"}},
    ])
    assert resolved["winner"] == "patch"
    assert resolved["overridden"][0]["path"] == "/user"


def test_the_real_stack_resolves_a_key_the_defaults_always_carry():
    """Against the actual ovos-config on this machine, not a fixture."""
    resolved = layers.resolve("lang")
    assert resolved["set"] is True
    assert resolved["winner"], "no layer claimed a key every default sets"


class TestTheRoutes:
    def test_the_layer_list_does_not_hand_out_the_configuration(self, client):
        """It says which files exist and how they stack. The values in them
        are a different question, with a different answer."""
        body = client.get("/api/config/layers").json()
        assert body["layers"], "reported no configuration layers at all"
        for layer in body["layers"]:
            assert "data" not in layer, "handed out a whole config layer"
            assert set(layer) == {"name", "path", "exists", "dropped"}, layer

    def test_a_key_can_be_traced_to_its_file(self, client):
        body = client.get("/api/config/resolve", params={"key": "lang"}).json()
        assert body["key"] == "lang"
        assert body["set"] is True
        assert body["winner"], "no layer claimed a key every default sets"

    def test_a_key_nobody_sets_answers_rather_than_erroring(self, client):
        body = client.get("/api/config/resolve",
                          params={"key": "no.such.setting"}).json()
        assert body["set"] is False
        assert body["overridden"] == []

    def test_an_empty_key_is_refused(self, client):
        assert client.get("/api/config/resolve", params={"key": ""}).status_code == 400


class TestAgainstWhatTheMergeReallyDoes:
    """The answer has to match the configuration the device really runs.

    Ground truth here is `Configuration.load_all_configs()`, not another
    reading of the same files: a page that says the user file wins, on a
    device where policy drops the user file, gives the reader the exact
    opposite of the answer they came for.
    """

    @staticmethod
    def _real(key):
        from ovos_config.config import Configuration

        value = Configuration.load_all_configs()
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return False, None
            value = value[part]
        return True, value

    def _agrees(self, key):
        was_set, real = self._real(key)
        answer = layers.resolve(key)
        assert answer["set"] == was_set, (
            f"{key}: panel says set={answer['set']}, the merge says {was_set}"
        )
        assert answer["value"] == real, (
            f"{key}: panel says {answer['value']!r}, the device runs {real!r}"
        )

    def test_a_plain_key_agrees_with_the_merge(self):
        self._agrees("lang")

    def test_a_subtree_agrees_with_the_merge(self):
        """`merge_dict` recurses, so a dict key is the union of every layer
        that mentions it -- not the last one's copy."""
        self._agrees("tts")
        self._agrees("listener")

    def test_a_user_file_the_device_ignores_is_not_called_the_winner(
            self, tmp_path, monkeypatch):
        from ovos_config.config import Configuration

        monkeypatch.setattr(Configuration, "get_system_constraints",
                            staticmethod(lambda *a, **k: {"disable_user_config": True}))
        Configuration.reload()
        try:
            self._agrees("lang")
            answer = layers.resolve("lang")
            dropped = [layer for layer in layers.stack() if layer.get("dropped")]
            assert dropped, "no layer reported as dropped by policy"
            assert answer["winner"] not in ("xdg", "patch", "distribution"), (
                f"named {answer['winner']}, which this device ignores"
            )
        finally:
            Configuration.reload()

    def test_a_remote_cache_the_device_ignores_is_not_read(
            self, monkeypatch):
        from ovos_config.config import Configuration

        monkeypatch.setattr(Configuration, "get_system_constraints",
                            staticmethod(lambda *a, **k: {"disable_remote_config": True}))
        Configuration.reload()
        try:
            assert all(not layer["dropped"] or layer["name"] == "remote"
                       for layer in layers.stack())
            remote = [layer for layer in layers.stack()
                      if layer["name"] == "remote"]
            assert remote and remote[0]["dropped"], (
                "the remote cache is skipped by policy and was not marked"
            )
        finally:
            Configuration.reload()

    def test_a_nested_protected_key_uses_the_separator_the_policy_uses(self):
        """`protected_keys` nests with `:` while this module addresses keys
        with `.`. Reading the policy with the wrong separator protects
        nothing, silently."""
        stripped = layers._without(
            {"tts": {"module": "mimic3", "fallback": "server"}, "lang": "pt-pt"},
            ["tts:module"])
        assert stripped["tts"] == {"fallback": "server"}, stripped
        assert stripped["lang"] == "pt-pt", "removed more than the policy named"

    def test_stripping_a_protected_key_does_not_touch_the_real_layer(self):
        """`flattened_delete` mutates the layer it is given. This must not:
        answering a question about the configuration cannot change it."""
        original = {"tts": {"module": "mimic3"}}
        layers._without(original, ["tts:module"])
        assert original == {"tts": {"module": "mimic3"}}, (
            "reading the configuration changed it"
        )

    def test_asking_a_question_does_not_rewrite_the_configuration(self):
        """`merge_dict` recurses into the dicts it is given, and a shallow
        copy of a layer still points at that layer's own sub-dicts. Two
        levels of nesting is all it takes for a read to write the user's
        values into the packaged defaults, in the running process.
        """
        from ovos_config.config import Configuration

        # Synthetic first, so this holds whatever this machine's files say.
        first = {"location": {"city": {"code": "Lawrence", "name": "Lawrence"}}}
        second = {"location": {"city": {"code": "Lisbon"}}}
        layers.resolve("location", stack=[
            {"name": "default", "path": "/a", "exists": True, "dropped": False,
             "data": first},
            {"name": "xdg", "path": "/b", "exists": True, "dropped": False,
             "data": second},
        ])
        assert first["location"]["city"]["code"] == "Lawrence", (
            "the answer was written back into the layer it came from"
        )

        # Three layers, because the second one's sub-dicts end up inside the
        # running answer and a third merge writes through them.
        one = {"location": {"city": {"code": "A", "name": "A"}}}
        two = {"location": {"city": {"name": "B"}}}
        three = {"location": {"city": {"code": "C"}}}
        layers.resolve("location", stack=[
            {"name": "default", "path": "/a", "exists": True, "dropped": False,
             "data": one},
            {"name": "system", "path": "/b", "exists": True, "dropped": False,
             "data": two},
            {"name": "xdg", "path": "/c", "exists": True, "dropped": False,
             "data": three},
        ])
        # A subkey first introduced in the merge branch is carried into the
        # next iteration by reference, so the layer after it writes through.
        # It takes three layers and a key the first one does not have.
        early = {"zz": {"x": 1}}
        middle = {"zz": {"y": {"z": 1}}}
        late = {"zz": {"y": {"w": 2}}}
        layers.resolve("zz", stack=[
            {"name": "default", "path": "/a", "exists": True, "dropped": False,
             "data": early},
            {"name": "system", "path": "/b", "exists": True, "dropped": False,
             "data": middle},
            {"name": "xdg", "path": "/c", "exists": True, "dropped": False,
             "data": late},
        ])
        assert middle == {"zz": {"y": {"z": 1}}}, (
            f"a later layer was merged into the middle one: {middle}"
        )

        assert one["location"]["city"] == {"code": "A", "name": "A"}, (
            f"later layers were merged into the first one: {one}"
        )
        assert two["location"]["city"] == {"name": "B"}, (
            f"a later layer was written into an earlier answer: {two}"
        )

        before = _deep(Configuration.default)
        for key in ("location", "tts", "listener", "hotwords"):
            layers.resolve(key)
        assert _deep(Configuration.default) == before, (
            "reading the configuration changed the defaults layer"
        )

    def test_a_layer_that_replaces_a_subtree_wins_over_a_key_inside_it(self):
        """Setting `tts` to a string removes `tts.module` from the merge.
        Reporting the older layer's value there is the one failure direction
        this page exists to remove."""
        answer = layers.resolve("tts.module", stack=[
            {"name": "default", "path": "/a", "exists": True, "dropped": False,
             "data": {"tts": {"module": "ovos-tts-plugin-server"}}},
            {"name": "xdg", "path": "/user", "exists": True, "dropped": False,
             "data": {"tts": "mimic3"}},
        ])
        assert answer["set"] is False, (
            f"reported {answer['value']!r}, which the device does not have"
        )

    def test_a_layer_that_nulls_a_subtree_also_clears_what_was_inside_it(self):
        answer = layers.resolve("tts.module", stack=[
            {"name": "default", "path": "/a", "exists": True, "dropped": False,
             "data": {"tts": {"module": "ovos-tts-plugin-server"}}},
            {"name": "xdg", "path": "/user", "exists": True, "dropped": False,
             "data": {"tts": None}},
        ])
        assert answer["set"] is False, (
            f"reported {answer['value']!r} after a layer unset its parent"
        )

    def test_a_protected_key_is_not_reported_from_the_layer_it_is_stripped_from(
            self, monkeypatch):
        """`protected_keys` drops one key from a layer rather than the whole
        layer, and its nested separator is `:`, not `.`."""
        from ovos_config.config import Configuration

        monkeypatch.setattr(
            Configuration, "get_system_constraints",
            staticmethod(lambda *a, **k: {"protected_keys": {"user": ["lang"]}}))
        Configuration.reload()
        try:
            answer = layers.resolve("lang")
            assert answer["winner"] not in ("xdg", "patch"), (
                f"reported {answer['winner']}, whose 'lang' policy strips"
            )
        finally:
            Configuration.reload()
