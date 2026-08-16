#!/usr/bin/env python3
"""Patch wrapper for GHYSJ-TNF docking v3.
Uses Meeko 0.7.1's actual -a/--allow_bad_res switch and surfaces captured logs on failure.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

src = Path(__file__).with_name("run_ghysj_tnf_docking.py")
text = src.read_text(encoding="utf-8")

old = '"--default_altloc", "A",\n        "--box_center"'
new = '"--default_altloc", "A", "-a",\n        "--box_center"'
if old not in text:
    raise SystemExit("Could not patch receptor command: expected source fragment not found")
text = text.replace(old, new, 1)

old2 = 'if p.returncode != 0:\n        raise RuntimeError(f"Command failed ({p.returncode}): {\' \'.join(map(str, cmd))}")'
new2 = '''if p.returncode != 0:\n        if stdout_file:\n            try:\n                print("\\n--- captured command log ---", flush=True)\n                print(Path(stdout_file).read_text(errors="ignore"), flush=True)\n                print("--- end captured command log ---\\n", flush=True)\n            except Exception:\n                pass\n        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(map(str, cmd))}")'''
if old2 in text:
    text = text.replace(old2, new2, 1)

with tempfile.TemporaryDirectory() as td:
    patched = Path(td) / "run_patched.py"
    patched.write_text(text, encoding="utf-8")
    cmd = [sys.executable, str(patched)] + sys.argv[1:]
    raise SystemExit(subprocess.call(cmd))
