# System

SSH access, the device location, and a factory reset. These are the controls
you reach for when setting up or troubleshooting a device. The language is set
on the [Voice and language](voice-settings.md) page, and the internet status is
on the [Network](network.md) page.

![The System page](img/system-wide.png)

![The same page on a phone](img/system-mobile.png)

## What it needs

SSH and factory reset need the `ovos-PHAL-plugin-system` plugin, installed
and running on the device. Detect my location needs `ovos-PHAL-plugin-ipgeo`.
Without `ovos-PHAL-plugin-system` the page leaves the menu, and if you open it
anyway it says which plugin it needs. Install any of these on the
[Plugins](plugins.md) page. Where a plugin is missing, the matching part of
the page shows a note instead of a working control.

## Read it top to bottom

The page has three parts, in this order:

1. **SSH**: shows whether SSH is on, and a button to turn it on or off. SSH
   lets you log into the device over the network with a terminal. Turning it
   off or on asks you to confirm first.
2. **Location**: **Detect my location** looks up an approximate location
   from the device's public IP address and saves it as the device location. Review it afterwards on the
   [Settings](configuration.md) page.

   The lookup goes out to the internet, so give it a few seconds. It writes
   the location into the lowest configuration layer the device reads, which
   means a location you have set yourself keeps winning; when that happens the
   page says so and points you at the Settings page to clear it. On a device
   whose administrator has switched off the remote configuration layer, or
   protected the location key, the detected location cannot be stored at all
   and the page says that instead — there is nothing to clear, and the device
   keeps the location it has.
3. **Factory reset**: erases all settings, skills, and personal data, and
   returns the device to its factory defaults.

## Before you reset

**A factory reset cannot be undone.** It erases everything on the device:
settings, skills, and personal data. The button asks you to type `RESET`
and then confirm before it sends anything. Make a [backup](backup-restore.md)
first if you want to keep your settings.

## If it doesn't work

If a part of the page shows a message that a plugin is missing, install the
plugin it names on the [Plugins](plugins.md) page and restart the PHAL
service. For anything else, see [troubleshooting.md](troubleshooting.md).

---
[← Mark-1 faceplate](mark1.md) · [Home](README.md) · [Sensors →](sensors.md)
