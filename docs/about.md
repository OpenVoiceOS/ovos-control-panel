# About

The About page shows what is installed on this device and where to get help.

![The About page on a phone](images/about.png)

## What it shows

- The version of ovos-webui, and the versions of the main OVOS packages it
  found.
- The address the page is served on.
- Links to the OpenVoiceOS documentation, the chat, and the source code.

## When to use it

Open this page when you report a problem. The version list is the first thing
a maintainer asks for, and it saves you looking each package up by hand.

## Device power

The About page can send the standard system messages over the bus:
`system.mycroft.service.restart` and `system.reboot`. They are acted on by
`ovos-PHAL-plugin-system` where it is installed; on a device without it the
message is ignored and nothing happens. Both need the access token and a
confirmation, and the page never runs a shell command itself.

![The device power section](images/about-power.png)
