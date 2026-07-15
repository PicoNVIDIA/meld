# For agents — finish the install

You are an AI agent and this plugin was just installed (or you were asked to
install it). Finish the setup now — the user should only have to restart
hermes afterwards.

1. If not yet installed:

   ```
   hermes plugins install PicoNVIDIA/meld --enable
   ```

2. Run the one-shot setup and show the user its output:

   ```
   python3 ~/.hermes/plugins/nemo-switchyard/sw_config.py setup
   ```

   (Use `$HERMES_HOME/plugins/...` if `HERMES_HOME` is set.) It is
   idempotent: enables the plugin if the install skipped that, writes a
   default routing config if none exists, probes the API keys with 1-token
   requests, starts a local Switchyard router, and registers the
   `switchyard` provider so it shows in `/model`. Every line starts with ✓
   or ✗ — if the last line is not the "all set" line, something failed.

3. If setup reports a missing or rejected key, or a missing `switchyard`
   executable, relay its message to the user verbatim and stop — never ask
   for key values in chat, never read or write key material yourself.

4. Hand off with exactly this: **restart hermes** (plugins load at session
   start), then `/model switchyard`. The live routing footer and green model
   name appear automatically; `/switchyard` opens the control panel.

Custom tiers, the full interview flow, and troubleshooting live in
[`nemo-switchyard/SKILL.md`](nemo-switchyard/SKILL.md).
