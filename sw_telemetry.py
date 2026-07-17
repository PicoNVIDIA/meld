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

# Render-path callers hit these dozens of times per second — memoise the
# expensive probes (dist-info scans, file line counts) with short TTLs.
_MEMO = {}


def _memo(key, ttl, fn):
    import time
    now = time.monotonic()
    hit = _MEMO.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _MEMO[key] = (now, val)
    return val


def _memo_clear():
    _MEMO.clear()


def relay_lib():
    """(available: bool, version: str). Cached — importlib.metadata scans disk."""
    def probe():
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
    # a present library never disappears mid-session; absence is re-checked
    hit = _MEMO.get("relay_lib")
    if hit and hit[1][0]:
        return hit[1]
    return _memo("relay_lib", 15.0, probe)


def plugin_enabled():
    """True only when the plugin is in plugins.enabled and NOT deny-listed."""
    import sw_config
    enabled, disabled = sw_config.plugins_buckets()
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
    """(path, event_count, mtime) for the ATOF export file, or None. Cached 5s."""
    def compute():
        path = atof_file()
        if not path or not path.exists():
            return None
        try:
            with open(path, "rb") as fh:
                count = sum(1 for _ in fh)
            return path, count, path.stat().st_mtime
        except Exception:
            return None
    return _memo("atof_stats", 5.0, compute)


def atof_breakdown():
    """Counter of ATOF event categories (llm/tool/agent/mark). Cached 5s."""
    def compute():
        import json
        from collections import Counter
        path = atof_file()
        counts = Counter()
        if not path or not path.exists():
            return counts
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    counts[e.get("category") or e.get("kind") or "other"] += 1
        except Exception:
            pass
        return counts
    return _memo("atof_breakdown", 5.0, compute)


def atif_dir():
    """Trajectory export directory: env override first, then meld settings."""
    env_dir = os.environ.get("HERMES_NEMO_RELAY_ATIF_OUTPUT_DIRECTORY", "").strip()
    if env_dir:
        return Path(env_dir)
    cfg = _load_meld_settings().get("telemetry") or {}
    return Path(cfg.get("dir") or DEFAULT_EXPORT_DIR)


def trajectories():
    """Exported ATIF trajectory files, newest first."""
    directory = atif_dir()
    if not directory.exists():
        return []
    return sorted(directory.glob("hermes-atif-*.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def view_report(selector="", color_green="", color_dim="", color_bold="", color_reset=""):
    """Summarize one exported ATIF trajectory (ATIF v1.7 shape).

    selector: empty/1 = newest, N = Nth newest, or a session-id substring.
    """
    import json
    from collections import Counter
    g, d, b, r = color_green, color_dim, color_bold, color_reset
    trajs = trajectories()
    if not trajs:
        return f"no exported trajectories yet ({atif_dir()})"
    sel = (selector or "").strip()
    path = None
    if not sel or sel.isdigit():
        idx = max(1, int(sel or 1)) - 1
        if idx >= len(trajs):
            return f"only {len(trajs)} trajectories — /telemetry view [1..{len(trajs)}]"
        path = trajs[idx]
    else:
        path = next((p for p in trajs if sel in p.name), None)
        if path is None:
            return f"no trajectory matching {sel!r} — /telemetry sessions to list them"
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return f"could not parse {path.name}: {exc}"
    agent = data.get("agent") or {}
    steps = data.get("steps") or []
    metrics = data.get("final_metrics") or {}
    sources = Counter(s.get("source") or "?" for s in steps if isinstance(s, dict))
    times = [s.get("timestamp") for s in steps if isinstance(s, dict) and s.get("timestamp")]
    lines = [f"{g}{b}── trajectory {data.get('session_id', path.name)} ──{r}  {d}{path.name}{r}"]
    lines.append(f"  agent    {agent.get('name', '?')} {d}(model {agent.get('model_name', '?')},"
                 f" schema {data.get('schema_version', '?')}){r}")
    if times:
        lines.append(f"  span     {d}{times[0]}  →  {times[-1]}{r}")
    src_txt = " · ".join(f"{k} {v}" for k, v in sources.most_common())
    lines.append(f"  steps    {b}{len(steps)}{r}  {d}({src_txt}){r}")
    if metrics:
        lines.append(f"  tokens   prompt {b}{metrics.get('total_prompt_tokens', 0)}{r}"
                     f" · completion {b}{metrics.get('total_completion_tokens', 0)}{r}"
                     f" · cached {metrics.get('total_cached_tokens', 0)}")
    tail = [s for s in steps if isinstance(s, dict)][-4:]
    if tail:
        lines.append(f"  {d}last steps:{r}")
        for s in tail:
            lines.append(f"    {d}·{r} #{s.get('step_id', '?')} {s.get('source', '?')}"
                         f"  {d}{str(s.get('message', ''))[:60]}{r}")
    return "\n".join(lines)


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
    trajs = trajectories()
    if trajs:
        lines.append(f"  exported trajectories ({len(trajs)}):")
        import time as _t
        for i, p in enumerate(trajs[:8], 1):
            when = _t.strftime("%m-%d %H:%M", _t.localtime(p.stat().st_mtime))
            lines.append(f"    {d}{i}.{r} {p.name}  {d}{p.stat().st_size // 1024}KB · {when}{r}")
        lines.append(f"  {d}open one: /telemetry view <n>{r}")
    else:
        lines.append(f"  {d}no exported trajectories yet ({atif_dir()}){r}")
    st = atof_stats()
    if st:
        bd = atof_breakdown()
        bd_txt = " · ".join(f"{k} {v}" for k, v in bd.most_common(4)) if bd else ""
        lines.append(f"  event stream: {b}{st[1]}{r} events {d}({bd_txt}) → {st[0]}{r}")
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
        bd = atof_breakdown()
        bd_txt = f"  {d}({' · '.join(f'{k} {v}' for k, v in bd.most_common(4))}){r}" if bd else ""
        lines.append(f"  exported        {b}{count}{r} events{bd_txt} → {d}{path}{r}")
    envs = sorted(k for k in os.environ if k.startswith("HERMES_NEMO_RELAY_"))
    if envs:
        lines.append(f"  {d}env config: {', '.join(envs)}{r}")
    if st == "no-lib":
        lines.append(f"  {d}install the relay library into the hermes venv to use telemetry{r}")
    elif st == "off":
        lines.append(f"  {d}nothing is collected or exported until you opt in (/telemetry on){r}")
    return "\n".join(lines)
