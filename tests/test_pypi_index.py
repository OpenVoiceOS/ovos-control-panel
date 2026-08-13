"""The package index the Plugins page reads can be pointed at a self-hosted
mirror through ``webui.pypi_index``; a non-URL value is ignored so a bad
setting can never redirect the request somewhere unexpected."""
import json

from ovos_webui import configio, pypi


def _cfg(data):
    configio.user_config_path().write_text(json.dumps(data), encoding="utf-8")


def test_index_defaults_to_pypi():
    _cfg({})
    assert pypi._index_base() == "https://pypi.org"
    assert pypi._simple_index_url() == "https://pypi.org/simple/"
    assert pypi._project_json_url("ovos-core") == "https://pypi.org/pypi/ovos-core/json"


def test_index_uses_a_configured_mirror():
    _cfg({"webui": {"pypi_index": "https://devpi.lan:3141/root/pypi/"}})
    assert pypi._index_base() == "https://devpi.lan:3141/root/pypi"
    assert pypi._simple_index_url() == "https://devpi.lan:3141/root/pypi/simple/"
    assert pypi._project_json_url("ovos-core") == "https://devpi.lan:3141/root/pypi/pypi/ovos-core/json"


def test_index_ignores_a_non_http_value():
    for bad in ("file:///etc/passwd", "ftp://x/y", "not a url", 123, ["x"]):
        _cfg({"webui": {"pypi_index": bad}})
        assert pypi._index_base() == "https://pypi.org"
