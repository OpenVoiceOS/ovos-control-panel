# Changelog

## [0.0.1a26](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a26) (2026-08-25)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a25...0.0.1a26)

**Merged pull requests:**

- fix: run the build tests, which have never started [\#60](https://github.com/OpenVoiceOS/ovos-control-panel/pull/60) ([JarbasAl](https://github.com/JarbasAl))
- fix: clear ruff lint errors so the lint check can pass [\#56](https://github.com/OpenVoiceOS/ovos-control-panel/pull/56) ([JarbasAl](https://github.com/JarbasAl))
- fix: install the transformer plugins the tests require [\#55](https://github.com/OpenVoiceOS/ovos-control-panel/pull/55) ([JarbasAl](https://github.com/JarbasAl))
- feat: add Portuguese and Spanish UI locales [\#54](https://github.com/OpenVoiceOS/ovos-control-panel/pull/54) ([JarbasAl](https://github.com/JarbasAl))
- fix: correct the config-union comment \(caching, not schema filtering\) [\#53](https://github.com/OpenVoiceOS/ovos-control-panel/pull/53) ([JarbasAl](https://github.com/JarbasAl))
- feat: hear the current voice from the Voice page [\#52](https://github.com/OpenVoiceOS/ovos-control-panel/pull/52) ([JarbasAl](https://github.com/JarbasAl))
- feat: cross-link the Voice and Transformers pages [\#51](https://github.com/OpenVoiceOS/ovos-control-panel/pull/51) ([JarbasAl](https://github.com/JarbasAl))
- fix: re-subscribe the live feeds after a bus reconnect [\#50](https://github.com/OpenVoiceOS/ovos-control-panel/pull/50) ([JarbasAl](https://github.com/JarbasAl))
- feat: show the device's setup at a glance on the Dashboard [\#49](https://github.com/OpenVoiceOS/ovos-control-panel/pull/49) ([JarbasAl](https://github.com/JarbasAl))
- feat: undo the last settings change [\#48](https://github.com/OpenVoiceOS/ovos-control-panel/pull/48) ([JarbasAl](https://github.com/JarbasAl))
- test: catch pages that use an undefined i18n key [\#47](https://github.com/OpenVoiceOS/ovos-control-panel/pull/47) ([JarbasAl](https://github.com/JarbasAl))
- feat: add a real wake-word test to setup [\#46](https://github.com/OpenVoiceOS/ovos-control-panel/pull/46) ([JarbasAl](https://github.com/JarbasAl))
- feat: save and share your own Mark-1 faceplate drawings [\#45](https://github.com/OpenVoiceOS/ovos-control-panel/pull/45) ([JarbasAl](https://github.com/JarbasAl))
- docs: smooth the first-run guide \(Wi-Fi, phone access, token button\) [\#44](https://github.com/OpenVoiceOS/ovos-control-panel/pull/44) ([JarbasAl](https://github.com/JarbasAl))
- feat: generate an access token in the browser, no terminal [\#43](https://github.com/OpenVoiceOS/ovos-control-panel/pull/43) ([JarbasAl](https://github.com/JarbasAl))
- feat: add the Mark-1 eye volume-meter slider [\#42](https://github.com/OpenVoiceOS/ovos-control-panel/pull/42) ([JarbasAl](https://github.com/JarbasAl))
- rename: ovos-webui is now ovos-control-panel [\#41](https://github.com/OpenVoiceOS/ovos-control-panel/pull/41) ([JarbasAl](https://github.com/JarbasAl))
- feat: collapse the advanced Voice settings behind a disclosure [\#40](https://github.com/OpenVoiceOS/ovos-control-panel/pull/40) ([JarbasAl](https://github.com/JarbasAl))
- feat: sensors page — live readings from the device's sensors [\#39](https://github.com/OpenVoiceOS/ovos-control-panel/pull/39) ([JarbasAl](https://github.com/JarbasAl))
- fix: confirm before saving on the Transformers page [\#38](https://github.com/OpenVoiceOS/ovos-control-panel/pull/38) ([JarbasAl](https://github.com/JarbasAl))
- feat: configurable package index for self-hosters [\#37](https://github.com/OpenVoiceOS/ovos-control-panel/pull/37) ([JarbasAl](https://github.com/JarbasAl))
- feat: larger-text toggle for low-vision and elderly users [\#36](https://github.com/OpenVoiceOS/ovos-control-panel/pull/36) ([JarbasAl](https://github.com/JarbasAl))
- feat: Simple mode — hide advanced pages for everyday use [\#35](https://github.com/OpenVoiceOS/ovos-control-panel/pull/35) ([JarbasAl](https://github.com/JarbasAl))
- fix: audit a11y defects \(pipeline focus, wallpaper labels\) + security doc accuracy [\#34](https://github.com/OpenVoiceOS/ovos-control-panel/pull/34) ([JarbasAl](https://github.com/JarbasAl))
- feat: wallpaper — set the background, browse the collection, auto-rotate [\#33](https://github.com/OpenVoiceOS/ovos-control-panel/pull/33) ([JarbasAl](https://github.com/JarbasAl))
- feat: app launcher — list, launch and close desktop applications [\#32](https://github.com/OpenVoiceOS/ovos-control-panel/pull/32) ([JarbasAl](https://github.com/JarbasAl))
- feat: intent inspector — dry-run, active skills, and the intent manifest [\#31](https://github.com/OpenVoiceOS/ovos-control-panel/pull/31) ([JarbasAl](https://github.com/JarbasAl))
- feat: transformers panel — manage all six transformer chains [\#30](https://github.com/OpenVoiceOS/ovos-control-panel/pull/30) ([JarbasAl](https://github.com/JarbasAl))
- feat: Voice settings — pickers for wake word, VAD, STT, TTS, pipeline, transformers, language [\#29](https://github.com/OpenVoiceOS/ovos-control-panel/pull/29) ([JarbasAl](https://github.com/JarbasAl))
- feat: System panel — SSH, factory reset, language, connectivity, detect-location [\#28](https://github.com/OpenVoiceOS/ovos-control-panel/pull/28) ([JarbasAl](https://github.com/JarbasAl))
- feat: Servers panel — self-hosted STT/TTS/translate URLs with failover [\#27](https://github.com/OpenVoiceOS/ovos-control-panel/pull/27) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a25](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a25) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a24...0.0.1a25)

**Merged pull requests:**

- fix: audit wave-6 \(reconcile the buswait abandoned-permit count\) [\#26](https://github.com/OpenVoiceOS/ovos-control-panel/pull/26) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a24](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a24) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a23...0.0.1a24)

**Merged pull requests:**

- fix: audit wave-5 \(global decaying login throttle; regression from wave-3\) [\#25](https://github.com/OpenVoiceOS/ovos-control-panel/pull/25) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a23](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a23) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a22...0.0.1a23)

**Merged pull requests:**

- fix: audit wave-4 frontend \(login i18n, personas escaping, translate/try-it races\) [\#24](https://github.com/OpenVoiceOS/ovos-control-panel/pull/24) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a22](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a22) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a21...0.0.1a22)

**Merged pull requests:**

- fix: audit wave-4 backend \(restore off the loop + serialized, idempotent deletes, atomic caches\) [\#23](https://github.com/OpenVoiceOS/ovos-control-panel/pull/23) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a21](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a21) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a20...0.0.1a21)

**Merged pull requests:**

- fix: audit wave-3 \(health essential set, translate size cap, per-source login throttle\) [\#22](https://github.com/OpenVoiceOS/ovos-control-panel/pull/22) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a20](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a20) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a19...0.0.1a20)

**Merged pull requests:**

- fix: broadcast plugin installs by default \(targeted topic answered by nobody\) [\#21](https://github.com/OpenVoiceOS/ovos-control-panel/pull/21) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a19](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a19) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a18...0.0.1a19)

**Merged pull requests:**

- fix: audit wave-2a \(history backup ordering, try-it serialization\) [\#20](https://github.com/OpenVoiceOS/ovos-control-panel/pull/20) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a18](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a18) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a17...0.0.1a18)

**Merged pull requests:**

- fix: audit wave-1 findings \(volume scaling, validation bounds, reply correlation\) [\#19](https://github.com/OpenVoiceOS/ovos-control-panel/pull/19) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a17](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a17) (2026-08-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a16...0.0.1a17)

**Merged pull requests:**

- feat: Mark-1 faceplate panel — eyes, mouth, image editor and simulator [\#18](https://github.com/OpenVoiceOS/ovos-control-panel/pull/18) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a16](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a16) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a15...0.0.1a16)

**Merged pull requests:**

- feat: Media panel — now playing, transport and volume [\#17](https://github.com/OpenVoiceOS/ovos-control-panel/pull/17) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a15](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a15) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a14...0.0.1a15)

**Merged pull requests:**

- docs: Network panel page + wide/mobile screenshots for the new panels [\#16](https://github.com/OpenVoiceOS/ovos-control-panel/pull/16) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a14](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a14) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a13...0.0.1a14)

**Merged pull requests:**

- fix: allow WebAssembly in the CSP so the ggwave sound engine loads [\#15](https://github.com/OpenVoiceOS/ovos-control-panel/pull/15) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a13](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a13) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a12...0.0.1a13)

**Merged pull requests:**

- feat: send data to nearby devices over sound \(ggwave panel\) [\#13](https://github.com/OpenVoiceOS/ovos-control-panel/pull/13) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a12](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a12) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a11...0.0.1a12)

**Merged pull requests:**

- chore: shorten the AI-assistance note in credits [\#14](https://github.com/OpenVoiceOS/ovos-control-panel/pull/14) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a11](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a11) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a10...0.0.1a11)

**Merged pull requests:**

- feat: Wi-Fi / network panel [\#12](https://github.com/OpenVoiceOS/ovos-control-panel/pull/12) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a10](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a10) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a9...0.0.1a10)

**Merged pull requests:**

- docs: STE nav footers and prose cleanup [\#11](https://github.com/OpenVoiceOS/ovos-control-panel/pull/11) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a9](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a9) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a8...0.0.1a9)

**Merged pull requests:**

- fix: plugin refs \(network-manager, pipeline family\), de-jargon, credits, static-asset auth [\#10](https://github.com/OpenVoiceOS/ovos-control-panel/pull/10) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a8](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a8) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a7...0.0.1a8)

**Merged pull requests:**

- docs: navigation hub, widescreen + mobile screenshots per page, tutorials, troubleshooting [\#9](https://github.com/OpenVoiceOS/ovos-control-panel/pull/9) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a7](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a7) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a6...0.0.1a7)

**Merged pull requests:**

- fix: unauthenticated pages redirect to /login, not a bare 401 \(found on ser9\) [\#8](https://github.com/OpenVoiceOS/ovos-control-panel/pull/8) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a6](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a6) (2026-08-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a5...0.0.1a6)

**Merged pull requests:**

- fix: webui hardening — 3-round adversarial + persona review \(incorporates \#5, \#6\) [\#7](https://github.com/OpenVoiceOS/ovos-control-panel/pull/7) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a5](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a5) (2026-08-11)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a4...0.0.1a5)

**Merged pull requests:**

- feat: manual theme control \(match-device / dark / light\) [\#4](https://github.com/OpenVoiceOS/ovos-control-panel/pull/4) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a4](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a4) (2026-08-11)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a3...0.0.1a4)

**Merged pull requests:**

- feat: try-it console, setup wizard, updates + release channel, backup history, skill disable, persona activation [\#3](https://github.com/OpenVoiceOS/ovos-control-panel/pull/3) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a3](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a3) (2026-08-11)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/0.0.1a2...0.0.1a3)

**Merged pull requests:**

- feat: plugin browser, persona creator, resource translation + OVOS theme, a11y, i18n [\#2](https://github.com/OpenVoiceOS/ovos-control-panel/pull/2) ([JarbasAl](https://github.com/JarbasAl))

## [0.0.1a2](https://github.com/OpenVoiceOS/ovos-control-panel/tree/0.0.1a2) (2026-08-10)

[Full Changelog](https://github.com/OpenVoiceOS/ovos-control-panel/compare/4fb8f8d9c6200eefbdf847c8a0700db26570600e...0.0.1a2)

**Merged pull requests:**

- feat: local web UI for OpenVoiceOS devices [\#1](https://github.com/OpenVoiceOS/ovos-control-panel/pull/1) ([JarbasAl](https://github.com/JarbasAl))



\* *This Changelog was automatically generated by [github_changelog_generator](https://github.com/github-changelog-generator/github-changelog-generator)*
