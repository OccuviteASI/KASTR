# bin/

Helper binaries bundled into the frozen app: `ffmpeg`, `moq-relay`, `moq` (Windows `.exe` and Linux
builds side by side). They are not in git. Restore them with

```bash
python fetch-helpers.py
```

which downloads the pinned versions (see `fetch-helpers.py` for the pins and hashes).
