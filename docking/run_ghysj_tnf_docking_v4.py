#!/usr/bin/env python3
"""GHYSJ-TNF docking v4 wrapper.
Uses Scripps ADFR Suite prepare_receptor for 2AZ5 because Meeko 0.7.1
fails on the crystallographic TNF disulfide topology. Ligands remain prepared by Meeko.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

src = Path(__file__).with_name("run_ghysj_tnf_docking.py")
text = src.read_text(encoding="utf-8")

# Surface captured logs on failure.
old2 = 'if p.returncode != 0:\n        raise RuntimeError(f"Command failed ({p.returncode}): {\' \'.join(map(str, cmd))}")'
new2 = '''if p.returncode != 0:\n        if stdout_file:\n            try:\n                print("\\n--- captured command log ---", flush=True)\n                print(Path(stdout_file).read_text(errors="ignore"), flush=True)\n                print("--- end captured command log ---\\n", flush=True)\n            except Exception:\n                pass\n        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(map(str, cmd))}")'''
if old2 in text:
    text = text.replace(old2, new2, 1)

start = text.index('    # Receptor PDBQT + Vina box config.')
end = text.index('    # Prepare each ligand and dock. Same receptor, box, seed, exhaustiveness.')
replacement = '''    # Receptor PDBQT: Scripps ADFR Suite is used because Meeko 0.7.1\n    # can fail on the native TNF disulfide topology (Cys69-Cys101).\n    receptor_pdbqt = prep_dir / "TNF_2AZ5_receptor.pdbqt"\n    run(["prepare_receptor", "-r", str(receptor_pdb), "-o", str(receptor_pdbqt)],\n        stdout_file=log_dir / "ADFR_prepare_receptor.log")\n    if not receptor_pdbqt.exists() or receptor_pdbqt.stat().st_size == 0:\n        raise RuntimeError("ADFR prepare_receptor did not create a usable receptor PDBQT")\n\n'''
text = text[:start] + replacement + text[end:]

# Correct the methods note so it records the actual receptor preparation route.
text = text.replace(
    'PDBQT preparation: Meeko 0.7.1.',
    'Ligand PDBQT preparation: Meeko 0.7.1. Receptor PDBQT preparation: Scripps ADFR Suite prepare_receptor (used to preserve the native TNF disulfide topology).'
)
text = text.replace(
    '"meeko": "0.7.1",',
    '"meeko_ligand_prep": "0.7.1",\n        "receptor_prep": "Scripps ADFR Suite prepare_receptor",'
)

with tempfile.TemporaryDirectory() as td:
    patched = Path(td) / "run_patched_v4.py"
    patched.write_text(text, encoding="utf-8")
    cmd = [sys.executable, str(patched)] + sys.argv[1:]
    raise SystemExit(subprocess.call(cmd))
