"""Load upstream helpers without running main(), constructing a controller or touching media."""

import importlib.util
import sys
from pathlib import Path


def load():
    name = "_insta360_legacy"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).resolve().parents[1] / "auto-sticher.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]
