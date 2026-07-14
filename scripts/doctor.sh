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
for cand in "$HERMES_HOME"/plugins/*/nvhermes_main.py; do
  if [ -f "$cand" ]; then plugin_dir="$(dirname "$cand")"; break; fi
done
if [ -n "$plugin_dir" ]; then
  pass "plugin installed ($plugin_dir)"
else
  failf "plugin installed under $HERMES_HOME/plugins (hermes plugins install PicoNVIDIA/meld --enable)"
fi

if grep -q "nemo-switchyard" "$HERMES_HOME/config.yaml" 2>/dev/null; then
  pass "plugin enabled in config.yaml"
else
  failf "plugin enabled in config.yaml (hermes plugins enable nemo-switchyard)"
fi

if command -v nvhermes >/dev/null 2>&1; then
  pass "nvhermes launcher on PATH (optional)"
else
  info "nvhermes launcher not installed — optional; the footer works in plain hermes via the plugin"
fi

if curl -fsS -m 2 "$URL/health" 2>/dev/null | grep -q '"ok"'; then
  pass "switchyard reachable at $URL"
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
  info "no switchyard router at $URL — router checks skipped (set SWITCHYARD_URL or start one)"
fi

exit "$fail"
