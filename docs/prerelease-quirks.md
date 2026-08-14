# Pre-release quirks

Behavior changes since the last stable release, newest first. This file is
reset at each stable release.

## 0.0.1a26

- The voice-config picker's seeded pipeline list now includes
  `ovos-padatious-pipeline-plugin-medium`, matching the list ovos-config
  ships (2.3.8a3+): the medium stage rescues open-slot utterances whose
  auto-registered entity values score below the padatious high threshold.
