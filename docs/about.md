# About

The About page shows what is installed on this device and where to get help.

![The About page](images/about-wide.png)

![The same page on a phone](images/about-mobile.png)

## Common tasks

- **Report a problem**: open this page and copy the version list into your
  report. See "When to use it" below.
- **Find the documentation or chat**: use the links on this page.
- **Restart or reboot the device**: see "Device power" below.

## What it shows

- The version of ovos-control-panel, and the versions of the main OVOS packages it
  found.
- The address the page is served on.
- Links to the OpenVoiceOS documentation, the chat, and the source code.

## When to use it

Open this page when you report a problem. The version list is the first thing
a maintainer asks for, and it saves you looking each package up by hand.

## Device power

Restarting and rebooting live on the [Device page](controls.md), not here. It
sends the standard system messages over the bus, `system.mycroft.service.restart`
and `system.reboot`, which `ovos-PHAL-plugin-system` acts on where it is
installed. Without that plugin the buttons are disabled and the page offers to
install it. Both need the access token and a confirmation, and neither runs a
shell command.

![The device power section](images/about-power.png)

## If it doesn't work

If a version is missing from the list, that package is not installed on this
device. For anything else, see [troubleshooting.md](troubleshooting.md).

---
[← Backup](backup-restore.md) · [Home](README.md) · [Security →](security.md)
