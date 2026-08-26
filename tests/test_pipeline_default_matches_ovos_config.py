"""The seeded pipeline stages come from ovos-config, not from a copy.

`voicecfg` used to keep its own copy of ovos-config's default `intents.pipeline`
to seed the "add a stage" picker. A copy goes stale whenever ovos-config adds or
drops a stage, and it describes whichever version it was taken from rather than
the ovos-config on this device -- devices do not all run the same one.

Comparing the seeded list against the shipped list is not enough on its own: the
two agree today, so a build that quietly went back to the copy would still pass.
The reading itself is pinned separately, against a list ovos-config could never
return.
"""
from pathlib import Path

import pytest

from ovos_webui import voicecfg

SENTINEL = ["sentinel-stage-one", "sentinel-stage-two"]


def _shipped_pipeline() -> list[str]:
    """The default `intents.pipeline` read from the file ovos-config ships."""
    import ovos_config
    from ovos_utils.json_helper import load_commented_json

    conf = Path(ovos_config.__file__).parent / "mycroft.conf"
    if not conf.is_file():
        pytest.fail(f"ovos-config ships no mycroft.conf at {conf}")
    # The shipped file is JSON with // comments; ovos-utils has the loader.
    stages = load_commented_json(str(conf)).get("intents", {}).get("pipeline")
    if not isinstance(stages, list):
        pytest.fail(f"ovos-config's mycroft.conf has no intents.pipeline list: {stages!r}")
    return stages


def test_the_seeded_stages_are_read_from_ovos_config(monkeypatch):
    """The proof that the list is read: ovos-config could never ship this one."""
    import ovos_config.models

    monkeypatch.setattr(ovos_config.models, "MycroftDefaultConfig",
                        lambda: {"intents": {"pipeline": list(SENTINEL)}})
    assert voicecfg.default_pipeline() == SENTINEL, (
        "the picker is not reading ovos-config; it is serving a copy that will "
        "go stale the next time ovos-config changes its default pipeline"
    )


def test_the_seeded_stages_are_the_ones_this_ovos_config_ships():
    assert voicecfg.default_pipeline() == _shipped_pipeline(), (
        "the picker is not offering the stages the installed ovos-config ships"
    )


def test_a_broken_ovos_config_still_leaves_the_picker_usable(monkeypatch):
    def explode():
        raise RuntimeError("no ovos-config here")

    monkeypatch.setattr(voicecfg, "_FALLBACK_PIPELINE", ["only-this-stage"])
    import ovos_config.models

    monkeypatch.setattr(ovos_config.models, "MycroftDefaultConfig", explode)
    assert voicecfg.default_pipeline() == ["only-this-stage"], (
        "a broken ovos-config must fall back, not leave the picker empty"
    )


def test_a_nonsense_pipeline_in_ovos_config_falls_back(monkeypatch):
    monkeypatch.setattr(voicecfg, "_FALLBACK_PIPELINE", ["only-this-stage"])
    import ovos_config.models

    monkeypatch.setattr(ovos_config.models, "MycroftDefaultConfig",
                        lambda: {"intents": {"pipeline": "not-a-list"}})
    assert voicecfg.default_pipeline() == ["only-this-stage"]


def test_the_fallback_is_a_plausible_pipeline():
    """The fallback only matters on a broken install, but it must not be junk."""
    fallback = voicecfg._FALLBACK_PIPELINE
    assert fallback, "the fallback must not be empty"
    assert len(set(fallback)) == len(fallback), "the fallback repeats a stage"
    assert all(isinstance(s, str) and s.strip() for s in fallback)
