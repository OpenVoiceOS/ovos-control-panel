# Pre-release quirks

Behavior changes since the last stable release, newest first. This file is
reset at each stable release.

## 0.0.1a26

- The Voice settings page reads the pipeline stages from the ovos-config
  installed on the device instead of from a copy kept in the panel. The picker
  now offers what the device will accept, which is not the same on every
  device: `ovos-padatious-pipeline-plugin-medium` ships from ovos-config
  2.3.9a1 onward and is absent on the current stable, and a copy could only
  ever describe one of the two. The medium stage rescues open-slot utterances
  whose auto-registered entity values score below the padatious high threshold.
