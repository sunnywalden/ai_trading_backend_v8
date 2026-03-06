from __future__ import annotations

import runpy
import sys
from pathlib import Path


def run_archived_script(script_name: str, version_dir: str = "v10_4_3") -> None:
    target = Path(__file__).resolve().parent / "archived" / version_dir / script_name
    if not target.exists():
        raise FileNotFoundError(f"Archived script not found: {target}")
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
