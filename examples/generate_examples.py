"""Regenerate deterministic packaged synthetic examples from a source checkout."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "generate_synthetic_examples.py"), run_name="__main__")
