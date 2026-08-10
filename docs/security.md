# Security

This page changes the configuration of your device. Anyone who can open it can
change how the device listens and what it says. Treat the address like a key.

## Default

The service binds to `0.0.0.0:8500`, so the whole local network can reach it.
Use `--host 127.0.0.1` to keep it on the device alone.

There is no token by default. On `127.0.0.1` that is safe: only a user of the
device can reach the port. On any other address it is not. The page then shows a
red banner on every screen until you set a token.

## Set a token

In `mycroft.conf`:

```json
{"webui": {"access_token": "a long random string"}}
```

Or on the command line:

```bash
ovos-webui --token "a long random string"
```

Make the token long and random. For example:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then open the page with `?token=...`. The browser keeps the token for the tab
only, and every later request carries it in an `Authorization: Bearer` header.

`/api/status` needs no token. It only reports the version and whether a token is
set, so the page can show the banner to a user who has not signed in.

## What the service does not do

- It never runs a shell command. No HTTP handler starts a process.
- It never writes outside your configuration file and the skill settings
  directory.
- It never sends anything to the internet. Every asset is in the package.

## Limits

- A request body over 1 MB is refused, except an upload to `/api/restore`.
- An upload over 16 MB is refused.
- An archive that unpacks to over 64 MB is refused.

## What this does not protect against

- There is no TLS. A token on a plain HTTP connection can be read by anyone who
  can watch the traffic. Do not put this page on the public internet. Use a
  reverse proxy with TLS, or a VPN, when you need access from outside.
- There is no user account and no audit log.
- Anyone who can already write to your configuration file, for example over SSH,
  does not need this page at all.
