#!/usr/bin/env python3
"""nvhermes — Hermes Agent with the NeMo Switchyard footer.

Rebinds the module-global HermesCLI to SwitchyardCLI before invoking the
stock entry point: cli.main() instantiates the module-global class, so the
full CLI (arg parsing, toolsets, skills preload) is inherited unchanged.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli  # hermes-agent's top-level cli module (from its venv)
from nvhermes_cli import SwitchyardCLI

cli.HermesCLI = SwitchyardCLI

from hermes_cli.main import main

if __name__ == "__main__":
    sys.exit(main())
