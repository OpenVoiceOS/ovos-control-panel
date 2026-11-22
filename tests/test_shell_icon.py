"""Every page names its icon, so the browser does not ask for /favicon.ico
and log a 404 on each page."""


def test_the_shell_and_the_sign_in_name_the_icon(client):
    for path in ("/", "/login"):
        got = client.get(path)
        if got.status_code in (302, 303, 307):
            got = client.get(got.headers["location"])
        assert '<link rel="icon" href="/static/icon-192.png"' in got.text, path
    assert client.get("/static/icon-192.png").headers["content-type"] == "image/png"
