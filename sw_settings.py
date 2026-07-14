"""Persisted settings for the nemo-switchyard integration (footer mode).

settings.json lives next to this file (inside the installed plugin directory)
and is gitignored, so `hermes plugins update` never clobbers it.
Resolution order: $SWITCHYARD_FOOTER > settings.json > "row".
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MODES = ("row", "bar", "min", "off")
DEFAULT_MODE = "row"
_SETTINGS = Path(__file__).resolve().parent / "settings.json"


def load_mode():
    env = os.environ.get("SWITCHYARD_FOOTER", "").strip().lower()
    if env in MODES:
        return env
    try:
        data = json.loads(_SETTINGS.read_text())
        if isinstance(data, dict) and data.get("footer") in MODES:
            return data["footer"]
    except Exception:
        pass
    return DEFAULT_MODE


def save_mode(mode):
    if mode not in MODES:
        raise ValueError(f"footer mode must be one of {MODES}, got {mode!r}")
    try:
        data = json.loads(_SETTINGS.read_text())
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data["footer"] = mode
    fd, tmp = tempfile.mkstemp(dir=str(_SETTINGS.parent), prefix=".settings-")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, _SETTINGS)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
