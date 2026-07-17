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
    """True only when the plugin is in plugins.enabled and NOT deny-listed.

    Parsed line-by-line — a substring search can't tell `enabled:` from
    `disabled:` entries, and the deny-list wins.
    """
    try:
        lines = HERMES_CONFIG.read_text().splitlines()
    except Exception:
        return False
    section, bucket = None, None
    enabled, disabled = set(), set()
    for line in lines:
        s = line.strip()
        if line and not line[0].isspace():
            section = s[:-1] if s.endswith(":") else None
            bucket = None
            continue
        if section != "plugins" or not s:
            continue
        if s.startswith(("enabled:", "disabled:")):
            bucket = "enabled" if s.startswith("enabled:") else "disabled"
            inline = s.split(":", 1)[1].strip()
            if inline.startswith("["):
                names = {n.strip() for n in inline.strip("[]").split(",") if n.strip()}
                (enabled if bucket == "enabled" else disabled).update(names)
            continue
        if s.startswith("- ") and bucket:
            (enabled if bucket == "enabled" else disabled).add(s[2:].strip())
    if any(k in disabled for k in _PLUGIN_KEYS):
        return False
    return any(k in enabled for k in _PLUGIN_KEYS)


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
    if os.environ.get("HERMES_NEMO_RELAY_ATOF_ENABLED", "").lower() in ("1", "true", "yes", "on"):
        directory = os.environ.get("HERMES_NEMO_RELAY_ATOF_OUTPUT_DIRECTORY", "").strip()
        if directory:
            return Path(directory) / (os.environ.get("HERMES_NEMO_RELAY_ATOF_FILENAME", "").strip() or "hermes-atof.jsonl")
    cfg = _load_meld_settings().get("telemetry") or {}
    if cfg.get("export"):
        return Path(cfg.get("dir") or DEFAULT_EXPORT_DIR) / "hermes-atof.jsonl"
    return None


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


DEFAULT_EXPORT_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "telemetry"


def _settings_path():
    return Path(__file__).resolve().parent / "settings.json"


def _load_meld_settings():
    import json
    try:
        data = json.loads(_settings_path().read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_meld_setting(key, value):
    import json
    data = _load_meld_settings()
    data[key] = value
    try:
        _settings_path().write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def apply_env_from_settings():
    """Inject HERMES_NEMO_RELAY_* env from meld settings at plugin load.

    Hermes doesn't propagate unknown .env keys, and the relay plugin reads
    os.environ lazily on its first hook — which fires after plugin
    registration, so setting the env here is guaranteed early enough.
    Existing environment always wins (setdefault only).
    """
    cfg = _load_meld_settings().get("telemetry") or {}
    if not cfg.get("export"):
        return False
    directory = str(cfg.get("dir") or DEFAULT_EXPORT_DIR)
    Path(directory).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HERMES_NEMO_RELAY_ATOF_ENABLED", "true")
    os.environ.setdefault("HERMES_NEMO_RELAY_ATOF_OUTPUT_DIRECTORY", directory)
    os.environ.setdefault("HERMES_NEMO_RELAY_ATIF_ENABLED", "true")
    os.environ.setdefault("HERMES_NEMO_RELAY_ATIF_OUTPUT_DIRECTORY", directory)
    return True


def toggle():
    """Opt in/out: plugin enablement + export config. Returns (ok, msg)."""
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
            if action == "enable":
                _save_meld_setting("telemetry", {"export": True, "dir": str(DEFAULT_EXPORT_DIR)})
                return True, (f"telemetry enabled — restart hermes to apply; "
                              f"exports (ATOF events + per-session ATIF trajectories) → {DEFAULT_EXPORT_DIR}")
            _save_meld_setting("telemetry", {"export": False})
            return True, "telemetry disabled — restart hermes to apply"
    return False, f"could not {action} the nemo_relay plugin: {last[:160]}"


def sessions_report(color_green="", color_dim="", color_bold="", color_reset=""):
    """Tracked live sessions + exported ATIF trajectory files."""
    g, d, b, r = color_green, color_dim, color_bold, color_reset
    lines = [f"{g}{b}── telemetry sessions ──{r}"]
    rt = runtime()
    if rt is not None:
        try:
            live = list(rt.sessions.keys())
            lines.append(f"  live (hooked this session): {b}{len(live)}{r}"
                         + (f"  {d}{', '.join(s[:12] for s in live[:4])}{r}" if live else ""))
        except Exception:
            pass
    cfg = _load_meld_settings().get("telemetry") or {}
    directory = Path(cfg.get("dir") or DEFAULT_EXPORT_DIR)
    trajs = sorted(directory.glob("hermes-atif-*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True) if directory.exists() else []
    if trajs:
        lines.append(f"  exported trajectories ({len(trajs)}):")
        import time as _t
        for p in trajs[:8]:
            when = _t.strftime("%m-%d %H:%M", _t.localtime(p.stat().st_mtime))
            lines.append(f"    {d}·{r} {p.name}  {d}{p.stat().st_size // 1024}KB · {when}{r}")
    else:
        lines.append(f"  {d}no exported trajectories yet ({directory}){r}")
    st = atof_stats()
    if st:
        lines.append(f"  event stream: {b}{st[1]}{r} events {d}→ {st[0]}{r}")
    return "\n".join(lines)


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
