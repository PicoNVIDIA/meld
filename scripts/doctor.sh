#!/usr/bin/env bash
# doctor.sh — PASS/FAIL checks for the nemo-switchyard Hermes integration.
# Exits 0 when all required checks pass. Router checks run against
# $SWITCHYARD_URL (default http://127.0.0.1:4000) and are skipped, not failed,
# when no router is up.
set -u

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
URL="${SWITCHYARD_URL:-http://127.0.0.1:4000}"
URL="${URL%/}"; URL="${URL%/v1}"
fail=0

pass() { printf 'PASS  %s\n' "$1"; }
failf() { printf 'FAIL  %s\n' "$1"; fail=1; }
info() { printf 'INFO  %s\n' "$1"; }

if command -v hermes >/dev/null 2>&1; then pass "hermes on PATH"; else failf "hermes on PATH"; fi

plugin_dir=""
for cand in "$HERMES_HOME"/plugins/*/sw_config.py; do
  if [ -f "$cand" ]; then plugin_dir="$(dirname "$cand")"; break; fi
done
if [ -n "$plugin_dir" ]; then
  pass "plugin installed ($plugin_dir)"
else
  failf "plugin installed under $HERMES_HOME/plugins (hermes plugins install PicoNVIDIA/meld --enable)"
fi

if hermes plugins list 2>/dev/null | grep -a "nemo-switchyard" | grep -v "not enabled" | grep -q "enabled"; then
  pass "plugin enabled"
else
  failf "plugin enabled (hermes plugins enable nemo-switchyard — note: a plugins.disabled deny-list entry wins)"
fi

if curl -fsS -m 2 "$URL/health" 2>/dev/null | grep -q '"ok"'; then
  pass "router reachable at $URL"
  if curl -fsS -m 2 "$URL/v1/models" 2>/dev/null | grep -q '"owned_by": *"switchyard"'; then
    pass "fingerprint (owned_by: switchyard)"
  else
    failf "fingerprint (owned_by: switchyard in $URL/v1/models)"
  fi
  if curl -fsS -m 2 "$URL/v1/routing/stats" >/dev/null 2>&1; then
    pass "stats endpoint (/v1/routing/stats)"
  else
    failf "stats endpoint (/v1/routing/stats)"
  fi
  if curl -fsS -m 2 "$URL/v1/routing/decisions" >/dev/null 2>&1; then
    pass "decisions endpoint (/v1/routing/decisions) — optional"
  else
    info "decisions endpoint unavailable (needs a deterministic routing profile) — optional"
  fi
else
  info "no router at $URL — router checks skipped (set SWITCHYARD_URL or start one)"
fi

# telemetry (optional, opt-in)
HPY="$HERMES_HOME/hermes-agent/venv/bin/python3"
if [ -x "$HPY" ] && "$HPY" -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('nemo_relay') else 1)" 2>/dev/null; then
  pass "telemetry library present (optional)"
  if hermes plugins list 2>/dev/null | grep -a "nemo_relay" | grep -v "not enabled" | grep -q "enabled"; then
    info "telemetry plugin enabled (opt-in) — exports configured via /telemetry"
  else
    info "telemetry off (opt-in) — /telemetry on to enable"
  fi
else
  info "telemetry library not installed — optional; setup installs it"
fi

exit "$fail"
