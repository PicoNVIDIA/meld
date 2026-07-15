# For agents — finish the install

You are an AI agent and this plugin was just installed (or you were asked to
install it). Your job is **install + enable + hand off** — the setup itself
is an interactive one-keystroke experience inside hermes that the user
should get to see.

1. Install (idempotent):

   ```
   hermes plugins install PicoNVIDIA/meld --enable
   ```

2. Verify it is **enabled** — `hermes plugins list` must say `enabled` for
   `nemo-switchyard`. If it says `not enabled` (the installer's enable
   prompt is a no-op in non-TTY shells), run:

   ```
   hermes plugins enable nemo-switchyard
   ```

3. Hand off with exactly this: **restart hermes** (plugins load at session
   start). A `⏚ switchyard` hint line will appear above the status bar —
   type `/switchyard` and press **Enter on the Quick setup row**. It does
   everything (config, key preflight, local router, provider registration)
   with live progress, in about 30 seconds. Then `/model switchyard` — the
   live routing footer and green model name appear automatically.

**Only if the user explicitly asks you to do the whole setup for them**
(e.g. headless, or "set it all up"), run it yourself and show the output:

```
python3 ~/.hermes/plugins/nemo-switchyard/sw_config.py setup
```

(`$HERMES_HOME/plugins/...` if `HERMES_HOME` is set.) Idempotent; every
line starts with ✓ or ✗. If it reports a missing or rejected key or a
missing `switchyard` executable, relay the message verbatim and stop —
never ask for key values in chat, never read or write key material.

Custom tiers, the full interview flow, and troubleshooting live in
[`nemo-switchyard/SKILL.md`](nemo-switchyard/SKILL.md).
