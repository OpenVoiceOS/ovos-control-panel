"""The plugin families the webui can classify (and therefore search/install),
and the PHAL capability providers — grounded in the real, non-archived repos."""
import pytest

from ovos_webui.pypi import classify


@pytest.mark.parametrize("name,kind", [
    # the modern intent stack was previously unclassifiable -> un-installable
    ("ovos-adapt-pipeline-plugin", "pipeline"),
    ("ovos-padatious-pipeline-plugin", "pipeline"),
    ("ovos-ocp-pipeline-plugin", "pipeline"),
    ("ovos-common-query-pipeline-plugin", "pipeline"),
    ("ovos-ollama-intent-pipeline-plugin", "pipeline"),
    # both solver naming conventions
    ("ovos-solver-wikipedia-plugin", "solver"),
    ("ovos-solver-plugin-wikipedia", "solver"),
    ("ovos-ddg-solver-plugin", "solver"),
    # both translate naming conventions
    ("ovos-translate-plugin-nllb", "translate"),
    ("ovos-google-translate-plugin", "translate"),
    ("ovos-gguf-translate-plugin", "translate"),
    # both lang-detect naming conventions
    ("ovos-lang-detect-plugin-linguonnx", "lang_detect"),
    ("ovos-lang-detector-fasttext-plugin", "lang_detect"),
    ("ovos-lang-detector-classics-plugin", "lang_detect"),
    # the client-of-a-server plugins still classify by their family
    ("ovos-tts-plugin-server", "tts"),
    ("ovos-stt-plugin-server", "stt"),
    ("ovos-translate-plugin-server", "translate"),
])
def test_family_is_classified(name, kind):
    assert classify(name) == kind


def test_network_capability_points_at_the_live_plugin():
    # the archived wifi-setup must not be referenced; network-manager is live
    from ovos_webui import phal

    net = phal.CAPABILITIES["network"]["plugins"]
    assert any("network-manager" in p for p in net)
    assert not any("wifi-setup" in p for p in net)


def test_admin_phal_package_set_is_the_live_plugin():
    # _admin_phal_packages derives from CAPABILITIES admin=True; it must be the
    # live network-manager, not the archived wifi-setup (drives admin routing)
    from ovos_webui.installer import _admin_phal_packages

    pkgs = _admin_phal_packages()
    assert any("network-manager" in p for p in pkgs)
    assert not any("wifi-setup" in p for p in pkgs)


def test_pipeline_plugin_broadcasts_because_core_has_no_installer(monkeypatch):
    """ovos-core binds only the plain `ovos.pip.install` and builds no
    ServiceInstaller, so there is no `ovos.pip.install.ovos_core` to target."""
    from ovos_webui import configio, installer

    # opt in to service targeting (a present webui.install_services block);
    # otherwise the install broadcasts and there is no per-family routing to assert.
    monkeypatch.setattr(configio, "user_or_merged",
                        lambda keys: {} if list(keys) == ["webui", "install_services"] else None)
    assert installer._install_service_for("ovos-adapt-pipeline-plugin") is None
