# Network

Whether the device is online, the Wi-Fi networks near it, and joining,
leaving or forgetting one.

Not every OpenVoiceOS device needs Wi-Fi set up from a browser: one on a
cable, in a container or in a browser does not. So the Network page is a
panel extension of its own,
[ovos-control-panel-network](https://github.com/andlo/ovos-control-panel-network),
rather than part of the panel. Install it where the panel runs, and restart
the panel:

```
pip install --pre ovos-control-panel-network
```

(`--pre`, as for the panel itself.) Wi-Fi needs
`ovos-PHAL-plugin-network-manager` on the device, the internet check
`ovos-PHAL-plugin-connectivity-events`. Its README says what the page does.

---
[← Apps](apps.md) · [Home](README.md) · [Servers →](servers.md)
