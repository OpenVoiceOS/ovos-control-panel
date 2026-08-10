# Security

This page changes the configuration of your device. Anyone who can open it can
change how the device listens and what it says. Treat the address like a key.

## Default

The service binds to `127.0.0.1:8500`, so only a user of the device can reach
it. Use `--host 0.0.0.0` to reach it from your phone, and set a token when you
do.

## Set a token

In `mycroft.conf`:

```json
{"webui": {"access_token": "a long random string"}}
```

Or on the command line:

```bash
ovos-webui --token "a long random string"
```

Make the token long and random:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Open the page and it asks you to sign in. The token is sent in the body of a
POST, never in the address, so it is not written to an access log and not kept
in the browser history. The reply sets a cookie marked `HttpOnly` and
`SameSite=Strict`, which only this site can send. A program can send the token
in an `Authorization: Bearer` header instead.

Without a token on a network address the page shows a red banner on every
screen.

## What is protected

With a token set, every page, every asset and every API call needs a sign in.
Only four things answer without one, and none of them read or change anything:

- `GET /api/status` — says only whether a token is needed
- `POST /api/login` and `POST /api/logout`
- `GET /login` — the sign in page
- `GET /healthz` — the word `ok`, for a service monitor
- `GET /static/app.css` — the stylesheet the sign-in page needs; it ships in
  the package, so anyone can already read it on PyPI

The interactive documentation and the OpenAPI schema are turned off.

## Cross-site request forgery

A web page you visit can send a request to a device on your own network. It
cannot read the answer, but a write does not need one, so without a check any
site could rewrite your configuration.

Every request that changes something must prove where it came from. If the
browser sends `Sec-Fetch-Site` it must say `same-origin`; failing that, an
`Origin` or `Referer` header must match the host. A request that carries none
of these headers is refused unless it authenticates with an
`Authorization: Bearer` header — a web page cannot make a browser attach one
to a cross-site request without a preflight, and no preflight is ever
approved, so that is what keeps `curl` and other programs working.

Every answer carries `Referrer-Policy: same-origin`, `X-Content-Type-Options`,
`X-Frame-Options: DENY` and a content security policy that allows only this
origin.

## DNS rebinding, and the Host header

The cross-site check above trusts what the browser reports about the origin. A
DNS rebinding attack works around that: an attacker points their own domain at
your device's address, so the browser believes their page and your device share
an origin and reports every request as same-origin.

The one thing the attacker cannot change is the name the browser puts in the
`Host` header — it is still their domain. So every request, a read as much as a
write, must carry a `Host` this service answers to. A numeric IP address and
the loopback names (`localhost`, `127.0.0.1`, `::1`) are always accepted,
because that is how you reach the device yourself. Any other name is refused
unless you list it, which you do for a reverse proxy or an mDNS name such as
`ovos.local`:

    ovos-webui --hostname ovos.local

or in `mycroft.conf`::

    {"webui": {"hostnames": ["ovos.local"]}}

A request for any other host name is answered with `400`.

## The token

When you set a token it must be at least eight characters. There is no account
and no lock-out, so a short token could be guessed over the network; the
service refuses to start with one that is too short. Use a long random string.
Every refused sign in is written to the log.

## What the service does not do

- It never runs a shell command. No handler starts a process.
- It never writes outside your configuration file and the skill settings
  directory.
- It never sends anything to the internet. Every asset is in the package.

## Limits

- A request body over 1 MB is refused, and the count is made while the body
  arrives, so a chunked request with no declared length is refused too.
- An upload over 16 MB is refused.
- An archive that unpacks to over 64 MB, or holds over 5000 members, is
  refused while it is being read. A single member over 1 MB is refused too, so
  one settings file cannot be made large enough to exhaust the memory of a
  small device when it is decoded.
- YAML anchors and aliases are refused, so a few hundred bytes cannot expand
  into gigabytes.
- Every value the simple form writes is checked against its type and its list
  of allowed values.

## What this does not protect against

- **There is no TLS.** A token on a plain HTTP connection can be read by
  anyone who can watch the traffic, and so can everything else. Do not put this
  page on the public internet. Use a reverse proxy with TLS, or a VPN.
- There is no user account. One token is one level of access. There is no
  full audit log, though every refused sign in and every refused host is
  written to the service log.
- A token is not a defence against someone who already has a shell on the
  device, or who can write to your configuration file another way.
- The page trusts the browser's `Sec-Fetch-Site` and `Origin` headers. A very
  old browser that sends neither, driven by a hostile page, is refused a write
  outright — its requests carry no `Authorization` header either — so it loses
  the page rather than the check.
- Restoring a backup replaces your settings. It checks that every file in the
  archive is where it should be and that it parses, but it cannot tell whether
  the contents are sensible.
