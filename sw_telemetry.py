"""NeMo Relay telemetry surface for the /router panel and /telemetry.

Reads real state only — the relay library's presence, the bundled
observability plugin's enablement, its in-process runtime when loaded, and
the ATOF/ATIF export files its env config points at. Telemetry is opt-in:
this module never enables anything by itself and never invents numbers.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERMES_CONFIG = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "config.yaml"
_PLUGIN_KEYS = ("observability/nemo_relay", "nemo_relay", "nemo-relay")


def relay_lib():
    """(available: bool, version: str)."""
    try:
        import importlib.util
        if importlib.util.find_spec("nemo_relay") is None:
            return False, ""
        try:
            import importlib.metadata
            return True, importlib.metadata.version("nemo-relay")
        except Exception:
            return True, "?"
    except Exception:
        return False, ""


def plugin_enabled():
    try:
        text = HERMES_CONFIG.read_text()
    except Exception:
        return False
    return any(k in text for k in _PLUGIN_KEYS)


def runtime():
    """The nemo_relay plugin's live _Runtime in this process, or None."""
    for name, mod in list(sys.modules.items()):
        if "nemo_relay" in name and hasattr(mod, "_RUNTIME"):
            rt = getattr(mod, "_RUNTIME")
            if rt is not None and type(rt).__name__ == "_Runtime":
                return rt
    return None


def atof_file():
    """Path to the configured ATOF export file, or None."""
    if os.environ.get("HERMES_NEMO_RELAY_ATOF_ENABLED", "").lower() not in ("1", "true", "yes", "on"):
        return None
    directory = os.environ.get("HERMES_NEMO_RELAY_ATOF_OUTPUT_DIRECTORY", "").strip()
    if not directory:
        return None
    return Path(directory) / (os.environ.get("HERMES_NEMO_RELAY_ATOF_FILENAME", "").strip() or "hermes-atof.jsonl")


def atof_stats():
    """(path, event_count, mtime) for the ATOF export file, or None."""
    path = atof_file()
    if not path or not path.exists():
        return None
    try:
        with open(path, "rb") as fh:
            count = sum(1 for _ in fh)
        return path, count, path.stat().st_mtime
    except Exception:
        return None


def state():
    """One of: 'no-lib', 'off', 'enabled' (restart pending), 'on'."""
    lib, _v = relay_lib()
    if not lib:
        return "no-lib"
    if not plugin_enabled():
        return "off"
    return "on" if runtime() is not None else "enabled"


def toggle():
    """Enable/disable the bundled plugin via the hermes CLI. Returns (ok, msg)."""
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        return False, "hermes not on PATH"
    action = "disable" if plugin_enabled() else "enable"
    last = ""
    for key in _PLUGIN_KEYS:
        res = subprocess.run([hermes_bin, "plugins", action, key],
                             capture_output=True, text=True, timeout=60)
        last = (res.stdout or res.stderr).strip()
        if (action == "enable") == plugin_enabled():
            return True, f"telemetry {action}d — restart hermes to apply"
    return False, f"could not {action} the nemo_relay plugin: {last[:160]}"


def status_report(color_green="", color_dim="", color_bold="", color_reset=""):
    g, d, b, r = color_green, color_dim, color_bold, color_reset
    lib, version = relay_lib()
    st = state()
    lines = [f"{g}{b}── telemetry (NeMo Relay) ──{r}"]
    lines.append(f"  relay library   {'✓ ' + version if lib else '✗ not installed in the hermes venv'}")
    lines.append(f"  plugin          {'✓ enabled' if plugin_enabled() else '○ off (opt-in)'}"
                 + ("" if st != "enabled" else f"  {d}— restart hermes to load it{r}"))
    rt = runtime()
    if rt is not None:
        try:
            s = rt.settings
            lines.append(f"  active session  ✓ hooked ({len(rt.sessions)} session(s) tracked)")
            lines.append(f"  atof export     {'✓ ' + (s.atof_output_directory or '?') if s.atof_enabled else '○ not configured'}")
            lines.append(f"  atif export     {'✓ ' + (s.atif_output_directory or '?') if s.atif_enabled else '○ not configured'}")
        except Exception:
            pass
    st_atof = atof_stats()
    if st_atof:
        path, count, _m = st_atof
        lines.append(f"  exported        {b}{count}{r} events → {d}{path}{r}")
    envs = sorted(k for k in os.environ if k.startswith("HERMES_NEMO_RELAY_"))
    if envs:
        lines.append(f"  {d}env config: {', '.join(envs)}{r}")
    if st == "no-lib":
        lines.append(f"  {d}install the relay library into the hermes venv to use telemetry{r}")
    elif st == "off":
        lines.append(f"  {d}nothing is collected or exported until you opt in (/telemetry on){r}")
    return "\n".join(lines)
