# Dashboard

The dashboard answers one question: does this device work?

## What it shows

The first card shows the message bus. Every OVOS service talks through the bus.
When the bus does not answer, no other check can answer either. Start
`ovos-messagebus` first.

Then there is one card for each service:

| Card | Service | Message it answers |
| --- | --- | --- |
| Skills | ovos-core skill manager | `mycroft.skills.is_ready` |
| Intents | ovos-core intent service | `mycroft.intents.is_ready` |
| Audio | ovos-audio or ovos-media | `mycroft.audio.is_ready` |
| Listener | ovos-dinkum-listener | `mycroft.voice.is_ready` |
| GUI | ovos-gui | `mycroft.gui_service.is_ready` |
| PHAL | ovos-PHAL | `mycroft.PHAL.is_ready` |

## What each state means

| State | Meaning |
| --- | --- |
| ready | The service runs and has finished starting. |
| starting | The service runs but is not ready yet. Wait and check again. |
| not ready | The service answered but reports a problem. |
| no answer | Nothing answered. The service is not running. |

A device without a screen has no GUI service, and a device without hardware
plugins has no PHAL. "No answer" for those two is normal.

`ovos-simple-listener` does not register a status handler at all, so a device
that uses it instead of `ovos-dinkum-listener` shows "no answer" for the
listener even while it is listening. That is a limit of this page, not a fault
on the device.

## How the check works

`ovos_utils.process_utils.ProcessStatus` gives every OVOS service two message
handlers, `mycroft.<name>.is_alive` and `mycroft.<name>.is_ready`. The dashboard
sends those messages and waits one second for the answer. It adds no new
message type to the bus.

All six services are asked at the same time, so the whole check costs one
second, not six.

## If something is down

Read the log of the service:

```bash
journalctl --user -u ovos-skills -n 100
```

Start it again:

```bash
systemctl --user restart ovos-skills
```

To see the messages themselves, use
[ovos-busmon](https://github.com/OpenVoiceOS/ovos-busmon). The dashboard links
to it on port 8000 of the same device.
