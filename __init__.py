"""NeMo Switchyard integration for Hermes Agent.

Registers /nvusage and /nvfooter slash commands and bundles the
nemo-switchyard skill. The TUI footer itself lives in nvhermes_cli.py
(a wrapper CLI — Hermes has no plugin API for the status bar).
"""
from __future__ import annotations

import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import sw_settings
import switchyard_client as swc

_NOT_FOUND_HINT = (
    "no switchyard router detected.\n"
    "  · start one:  switchyard serve --config <routes.yaml> --port <port>\n"
    "  · route a session through it:  OPENROUTER_BASE_URL=http://127.0.0.1:<port>/v1"
    " OPENROUTER_API_KEY=dummy nvhermes --provider openrouter -m <route-id>\n"
    "  · or set model.base_url in ~/.hermes/config.yaml for every session\n"
    "  · or set SWITCHYARD_URL for inspection without routing\n"
    "  · checks: /nvusage status"
)


def register(ctx):
    def _cli_ref():
        try:
            return ctx._manager._cli_ref
        except Exception:
            return None

    def _session_base_url():
        ref = _cli_ref()
        if ref is None:
            return None
        url = getattr(ref, "base_url", None)
        if url:
            return url
        return getattr(getattr(ref, "agent", None), "base_url", None)

    def _status_report():
        g, d, b, r = swc.GREEN, swc.DIM, swc.BOLD, swc.RST
        lines = [f"{g}{b}── switchyard status ──{r}"]

        def check(ok, label, optional=False):
            if ok:
                mark = f"{g}PASS{r}"
            elif optional:
                mark = f"{d}  — {r}"
            else:
                mark = "FAIL"
            lines.append(f"  {mark}  {label}")
            return bool(ok)

        ref = _cli_ref()
        check(True, "plugin loaded (/nvusage, /nvfooter registered)")
        session_url = _session_base_url()
        root = swc.resolve_url(session_url)
        routed = bool(session_url) and swc.detect(session_url) is not None
        check(root is not None, f"switchyard reachable ({root or 'none found'})")
        if root:
            check(swc.health_ok(root), f"health ok at {root}/health")
            check(swc.stats(root) is not None, "stats endpoint (/v1/routing/stats)")
            check(swc.decisions(root) is not None,
                  "decisions endpoint (/v1/routing/decisions — needs deterministic profile)",
                  optional=True)
        check(routed, "this session routes through switchyard (green model name)", optional=True)
        is_wrapper = ref is not None and hasattr(ref, "_sw_footer_mode")
        check(is_wrapper, "running under nvhermes (footer available)", optional=True)
        lines.append(f"  {d}footer mode: {sw_settings.load_mode()}{r}")
        return "\n".join(lines)

    def _handle_nvusage(raw_args=""):
        args = (raw_args or "").strip().lower()
        if args == "status":
            return _status_report()
        root = swc.resolve_url(_session_base_url())
        if root is None:
            return _NOT_FOUND_HINT
        if args == "reset":
            result = swc.reset(root)
            if result is not None:
                return f"switchyard stats reset at {root}"
            return f"reset failed — POST {root}/v1/stats/reset not available"
        if args:
            return "usage: /nvusage [status|reset]"
        return swc.render_usage(root, swc.stats(root), swc.decisions(root))

    def _handle_nvfooter(raw_args=""):
        mode = (raw_args or "").strip().lower()
        current = sw_settings.load_mode()
        if mode in ("", "status"):
            return (f"footer mode: {current}  (styles: row · bar · min · off)\n"
                    "set with /nvfooter <mode>; shown when running nvhermes against a switchyard router")
        if mode not in sw_settings.MODES:
            return f"unknown mode {mode!r} — pick one of: row, bar, min, off (or 'status')"
        sw_settings.save_mode(mode)
        ref = _cli_ref()
        applied = False
        if ref is not None and hasattr(ref, "_sw_footer_mode"):
            ref._sw_footer_mode = mode
            try:
                ref._invalidate()
            except Exception:
                pass
            applied = True
        note = "" if applied else " (persisted — takes effect under nvhermes)"
        return f"footer → {mode}{note}"

    ctx.register_command(
        "nvusage",
        _handle_nvusage,
        description="NeMo Switchyard usage & routing stats (/nvusage [status|reset])",
    )
    ctx.register_command(
        "nvfooter",
        _handle_nvfooter,
        description="Switchyard footer style: row|bar|min|off|status",
    )
    try:
        ctx.register_skill(
            "nemo-switchyard",
            _DIR / "nemo-switchyard" / "SKILL.md",
            description="Set up and use the NeMo Switchyard integration for Hermes",
        )
    except Exception:
        pass
