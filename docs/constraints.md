# The constraints file

`constraints.txt` records one resolution of every dependency, direct and
transitive, at the newest version that satisfies the floors in
`pyproject.toml` — pre-releases included.

It is not a lockfile. The floors in `pyproject.toml` decide what may be
installed; this file only writes down what "newest" meant when it was
generated, so a failure can be reproduced against the same set of versions
somebody else had.

Nothing installs from it by default. Reach for it when you want the exact set:

```bash
uv pip install --prerelease=allow -c constraints.txt -e ".[dev]"
```

## Regenerating it

Never edit it by hand. It is generated:

```bash
uv pip compile --prerelease=allow --extra dev pyproject.toml -o constraints.txt
```

Regenerate it when a floor in `pyproject.toml` moves, and whenever you want the
recorded set to catch up with the latest alphas. A diff on this file is a
readable summary of what moved underneath the panel since the last time.
