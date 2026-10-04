---
name: Control panel test run
about: Manual QA of ovos-control-panel, page by page, on a real device
title: "Test run: <panel version> on <device>, <channel>"
labels: []
assignees: []
---

<!--
One issue per test run.

Every step checks the control panel itself: is what a page shows true,
does each control do what it says, and does the page cope when something
is missing or goes wrong. The device is only used to confirm the page.

Tick a step when it behaves as described.
If a step fails, open its own issue and write it after the step, like:  ❌ #123
If you skip a step, say why, like:  ⏭️ no screen

Some steps need hardware to verify:
  🎤 microphone   🔊 speaker   📶 Wi-Fi   🖥️ screen
On a device without that part, check that the page says the part
(or the plugin for it) is missing, instead of hanging or showing an error.

Screenshots and longer notes go in a comment below.
-->

## Test setup

| | |
|---|---|
| `ovos-control-panel` version | <!-- shown on the About page --> |
| Installed with | <!-- e.g. `pip install --pre ovos-control-panel`, from git --> |
| OVOS channel / `ovos-core` version | <!-- the panel needs the alpha channel for now --> |
| Device | <!-- e.g. Mark II, Raspberry Pi 4 + ReSpeaker, headless VM --> |
| Browsers | <!-- e.g. Firefox on Android, Safari on iPhone, Chrome on desktop --> |

## Install and sign in

- [ ] On an alpha device, the README install command installs the **current** release. Note which version pip actually picked.
- [ ] Started as a service with `--host 0.0.0.0` and a token, the panel answers on `http://<device ip>:8500/`.
- [ ] A wrong token gives a clear error, and you stay on the sign-in page.
- [ ] The right token takes you to the dashboard.
- [ ] With no token set, every page shows the red warning banner.
- [ ] **Sign out** really signs you out. Pressing back in the browser does not show any data.

## Every page

- [ ] Every page in the menu loads, without errors in the browser console.
- [ ] Every page that has to wait for the device shows its result or a clear message within a few seconds. Nothing stays on "Loading…" or "Checking…".
- [ ] Every button that changes the device asks you to confirm first.
- [ ] Every save leaves a backup that can be found under **Backup → Go back to an earlier save**.

## Dashboard

- [ ] Each service shows its real state.
- [ ] Stop one service (`systemctl --user stop ovos-audio`) and press **Check again**. It shows as down, with advice. Start it again and press **Check again**: it is ready again.
- [ ] **Your setup** shows the wake word, STT, TTS and language the device really uses.

## Setup

- [ ] Step 1 sees whether a token is set.
- [ ] Step 2: the chosen language is saved to the config, and the page says what has to be restarted.
- [ ] Step 3 suggests plugins for the chosen language. **Install** finishes, and the plugin then shows as installed.
- [ ] 🔊 Step 4: the sentence is spoken from the device.
- [ ] Step 5 leads to Try it.
- [ ] 🎤 Step 6: the page reacts when the wake word is said near the device.

## Try it

- [ ] **Ask the device.** A typed sentence shows which skill answered and what it said.
- [ ] A sentence that nothing matches gives a clear "nothing answered" message.
- [ ] 🔊 **Hear the voice.** The text is spoken from the device.
- [ ] 🎤 **Live activity.** A spoken question and its answer appear in the list while it happens.
- [ ] **Pause updates** stops the list from changing, and resuming starts it again.

## Device

- [ ] 🔊 **Volume.** Moving the slider changes how loud the device really is.
- [ ] 🔊 After changing the volume on the device itself (its buttons, or by voice), reloading the page shows the new value.
- [ ] 🔊 **Mute** and unmute work, and the page shows the current state.
- [ ] 🎤 **Mute the microphone.** The device stops listening, and the page shows it as muted. Unmuting works.
- [ ] **Restart the voice services.** After you confirm, the page shows the restart, comes back by itself, and you are still signed in.
- [ ] **Reboot the device.** After you confirm and the device boots, the panel comes back by itself, and you are still signed in.
- [ ] **Companion plugins** shows which plugins are installed. Installing a missing one works.

## Media

- [ ] Start playback on the device. **Refresh** shows what is playing.
- [ ] Previous, Play/Pause, Next and Stop control the device.
- [ ] **Shuffle** and **Repeat** show their real state after a refresh.
- [ ] With nothing playing, the page says so.

## Apps 🖥️

- [ ] The list loads, or the page says the app-launcher plugin is missing.
- [ ] **Launch** opens the app on the device screen, and **Close** closes it.

## Network 📶

- [ ] **Current network** shows the right network within a few seconds. On a wired device it says the device is wired, not "not connected".
- [ ] **Scan** lists the networks around the device.
- [ ] **Join** another network. The page warns you before it changes anything, and the device ends up on that network.
- [ ] A wrong Wi-Fi password gives a clear error.
- [ ] Without a Wi-Fi adapter or the network plugin, the page says so.

## Servers

- [ ] Add a server to a list and save. It is written to the config and is still there after reloading.
- [ ] Remove it again and save.
- [ ] A malformed address is refused with a clear message.

## System

- [ ] **SSH** shows the real state. Turning it off and on works (check with `ssh`).
- [ ] **Device language** saves, and the rest of the panel follows the new language.
- [ ] **Connectivity** shows the real online state.
- [ ] **Detect my location** saves a plausible location.

## Sensors

- [ ] With the sensors plugin, real readings appear and update on their own.
- [ ] Without it, the page says what to install.

## Wallpaper 🖥️

- [ ] The thumbnails show pictures, not broken images.
- [ ] Picking a wallpaper changes the device screen, and **Current wallpaper** updates.
- [ ] **Set** with an image address works.
- [ ] **Rotate through wallpapers** turns on and off.

## Settings

- [ ] **Simple:** change a value and save. Only that key changes in `mycroft.conf`.
- [ ] **Undo my last change** puts the file back exactly as it was.
- [ ] **Advanced (JSON and YAML):** a valid edit saves. An invalid one is refused with a clear message and changes nothing.
- [ ] **Discard my unsaved edits** throws away what you typed.
- [ ] **Where these settings live** names the right files.

## Voice settings

- [ ] Each picker shows the value in use right now.
- [ ] 🎤 A new wake word takes effect when saved, as the page says.
- [ ] 🔊 A new voice takes effect after the restart the page asks for.
- [ ] **Pipeline order** saves, and the page says a restart is needed.

## Skills and Abilities

- [ ] Every installed skill is listed, both on Skills and on Abilities.
- [ ] A changed skill setting is saved and used by the skill.
- [ ] **Find an ability** filters the list.

## Intents

- [ ] **Test** shows the skill, intent and pipeline that would match, without the device answering.
- [ ] **Active skills** updates after you use a skill. **Deactivate** removes one.
- [ ] **All intents** lists the registered intents, and the filter works.

## Plugins

- [ ] **Check for updates** lists real pending upgrades, and **Upgrade** on one works.
- [ ] Switching the **release channel** is saved, and the update list follows the new channel.
- [ ] **Install** a plugin from the catalog. It finishes, and the plugin shows as installed. Note how long it took on this hardware.
- [ ] **Package check** reports conflicts honestly. Compare with `pip check`.

## Transformers

- [ ] Turning a plugin on or off is saved, and so is changing the order.
- [ ] **Bidirectional translation** turns on both plugins, as the page describes.

## Personas

- [ ] Make a persona with one answer source, then edit it and delete it.

## Translate

- [ ] Save a translation for a skill. The page says which parts take effect now and which do not yet.

## Send over sound 🔊🎤 (needs two devices)

- [ ] The page loads without errors and says whether the ggwave listener is installed.
- [ ] Text sent from the panel of device 1 is received by device 2.

## Backup

- [ ] **Download a backup** gives a file with a sensible name.
- [ ] Change a setting, then **restore** the file from the phone's file picker. After you confirm, the setting is back as it was.
- [ ] Restoring an unrelated file is refused with a clear message.
- [ ] **Go back to an earlier save** lists the saves you made during this run, and **Look at it** shows the file.

## About

- [ ] The version numbers match `pip show` on the device.
- [ ] The links work.

## On a phone

- [ ] The menu reaches every page and does not hide the page content.
- [ ] No page scrolls sideways, in portrait or in landscape.
- [ ] Dark mode follows the phone's setting, and text is readable everywhere.
- [ ] The text-size button makes text bigger without anything overlapping.
- [ ] **Show only the everyday pages** hides and shows pages as it says.

## When things go wrong

- [ ] Stop the message bus. The dashboard says the bus does not answer, and other pages give a clear message instead of hanging. Start the bus again: the pages recover without restarting the panel.
- [ ] Take the device offline while a page is open. The page says it lost the connection, and it recovers when the device is back.

## Not part of a normal run

**Factory reset** (on System) erases the device. Only test it on a device you are ready to set up again, and if you do, write down what happened in a comment.
