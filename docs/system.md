# System

SSH access and a factory reset, from the `ovos-PHAL-plugin-system` plugin.
These are the controls you reach for when setting up or troubleshooting a
device. The device's location is detected on the
[Voice and language](voice-settings.md#location) page, and the internet
status comes with the [Network](network.md) extension.

## What it needs

The page shows only where `ovos-PHAL-plugin-system` is installed. Install it on
the [Plugins](plugins.md) page. The panel brings the page, described in
`ovos_webui/bundled/ovos-phal-plugin-system/`, until the plugin brings its own
(see [Pages the panel brings](controlpanel-json.md#pages-the-panel-brings)).

## Read it top to bottom

1. **SSH**: whether SSH is on, and a button to turn it on or off. SSH lets you
   log into the device over the network with a terminal. Turning it on or off
   asks you to confirm first, and the card reads it again after a few seconds,
   once the plugin has started or stopped the service.
2. **Factory reset**: erases all settings, skills, and personal data, and
   returns the device to its factory defaults.

## Before you reset

**A factory reset cannot be undone.** It erases everything on the device:
settings, skills, and personal data. The button asks you to type `RESET`
and then confirm before it sends anything. Make a [backup](backup-restore.md)
first if you want to keep your settings.

## If it doesn't work

If the SSH card says the plugin did not answer, check that the PHAL service
is running. For anything else, see [troubleshooting.md](troubleshooting.md).

---
[← Mark-1 faceplate](mark1.md) · [Home](README.md) · [Sensors →](sensors.md)
