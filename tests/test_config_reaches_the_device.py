"""Every configuration write must reach the running services.

A write that only lands on disk leaves the device running the old value until
someone restarts it, while the page reports success. Most writes already send
`configuration.patch`; these tests cover the ones that were writing straight to
the file with no bus, so they behaved differently from every other page for no
reason the user could see.
"""
import pytest


@pytest.fixture
def patches(bus):
    """Record the configuration patches sent to the device."""
    seen = []
    bus.on("configuration.patch", lambda m: seen.append(m.msg_type))
    bus.on("configuration.patch.clear", lambda m: seen.append(m.msg_type))
    return seen


def test_saving_a_server_list_reaches_the_device(token_client, patches):
    response = token_client.post("/api/servers/stt", json={"urls": ["https://stt.example.com"]},
                                 headers={"Authorization": "Bearer s3cret-token"})
    assert response.status_code == 200, response.text
    assert "error" not in response.json(), response.json()
    assert patches == ["configuration.patch.clear", "configuration.patch"], (
        "the server list was written to the file but the running services were "
        "never told, so the device keeps using the old servers"
    )


def test_saving_translation_servers_reaches_the_device(token_client, patches):
    response = token_client.post("/api/servers/translate",
                                 json={"urls": ["https://translate.example.com"]},
                                 headers={"Authorization": "Bearer s3cret-token"})
    assert response.status_code == 200, response.text
    assert "error" not in response.json(), response.json()
    assert patches == ["configuration.patch.clear", "configuration.patch"]


def test_reverting_the_configuration_reaches_the_device(client, patches):
    # Save twice so there is a backup of mycroft.conf to revert to.
    client.put("/api/config", json={"text": '{"lang": "en-us"}', "format": "json"})
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    patches.clear()

    listed = client.get("/api/backups").json()
    backups = listed.get("backups") or []
    assert backups, f"no backup was kept to revert to: {listed}"

    response = client.post("/api/backups/revert", json={"id": backups[0]["id"]})
    assert response.status_code == 200, response.text
    assert patches == ["configuration.patch.clear", "configuration.patch"], (
        "reverting put the old configuration back on disk but never told the "
        "running services, so the device keeps the value that was just reverted"
    )


def test_restoring_a_backup_reaches_the_device(client, token_client, patches):
    """Restoring an archive is the heaviest configuration write the panel has."""
    client.put("/api/config", json={"text": '{"lang": "en-us"}', "format": "json"})
    archive = client.get("/api/backup")
    assert archive.status_code == 200, archive.text
    patches.clear()

    response = token_client.post(
        "/api/restore",
        files={"file": ("backup.tar.gz", archive.content, "application/gzip")},
        headers={"Authorization": "Bearer s3cret-token"})
    assert response.status_code == 200, response.text
    assert patches == ["configuration.patch.clear", "configuration.patch"], (
        "the restored configuration went to disk but the running services were "
        "never told, so the device keeps the values the restore replaced"
    )


def test_reverting_still_reaches_the_device_through_a_symlinked_config_home(
        client, patches, tmp_path, monkeypatch):
    """The config home may sit behind a symlink; the notify must still happen.

    Backup ids resolve to a real path, so comparing them against an unresolved
    config path silently skips the notify on any device whose XDG config home
    passes through a link -- and skips it without saying so, because the
    `applied` key is simply absent rather than False.
    """
    from ovos_webui import configio, history

    real = tmp_path / "real"
    (real / "mycroft").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)

    config = link / "mycroft" / "mycroft.conf"
    monkeypatch.setattr(configio, "user_config_path", lambda: config)
    monkeypatch.setattr(history, "roots", lambda: [link, real])

    client.put("/api/config", json={"text": '{"lang": "en-us"}', "format": "json"})
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    backups = client.get("/api/backups").json().get("backups") or []
    assert backups, "no backup was kept to revert to"
    patches.clear()

    response = client.post("/api/backups/revert", json={"id": backups[0]["id"]})
    assert response.status_code == 200, response.text
    assert response.json().get("applied") is not None, (
        "the notify was skipped and nothing said so"
    )
    assert patches == ["configuration.patch.clear", "configuration.patch"]
