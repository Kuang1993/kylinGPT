#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem

LIGANDS = [
    ("Ginsenoside_Rh2", 119307),
    ("Paeoniflorin", 442534),
    ("Matrine", 91466),
    ("Quercetin", 5280343),
    ("Kaempferol", 5280863),
    ("Luteolin", 5280445),
    ("Isovitexin", 162350),
]
CONTROL = ("SPD304_control", 5327044)
PDB_ID = "2AZ5"
PDB_URL = f"https://files.rcsb.org/download/{PDB_ID}.pdb"


def ligand_url(cid: int) -> str:
    return (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/CID/{cid}/record/SDF"
        f"?record_type=3d&response_type=save&response_basename=Structure3D_COMPOUND_CID_{cid}"
    )


def run(cmd, cwd=None, stdout_file=None):
    print("+", " ".join(map(str, cmd)), flush=True)
    if stdout_file:
        with open(stdout_file, "w", encoding="utf-8") as fh:
            p = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, text=True)
    else:
        p = subprocess.run(cmd, cwd=cwd, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(map(str, cmd))}")


def download(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "GHYSJ-TNF-docking/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    if dest.stat().st_size == 0:
        raise RuntimeError(f"Empty download: {url}")


def parse_pdb_atom(line: str):
    return {
        "record": line[0:6].strip(),
        "atom": line[12:16].strip(),
        "altloc": line[16:17],
        "resname": line[17:20].strip(),
        "chain": line[21:22],
        "resseq": line[22:26].strip(),
        "icode": line[26:27],
        "x": float(line[30:38]),
        "y": float(line[38:46]),
        "z": float(line[46:54]),
        "element": line[76:78].strip() if len(line) >= 78 else "",
        "line": line,
    }


def prepare_receptor_and_box(pdb_file: Path, out_dir: Path):
    lines = pdb_file.read_text(errors="ignore").splitlines()
    atoms = []
    lig_groups = {}
    for line in lines:
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        try:
            a = parse_pdb_atom(line)
        except Exception:
            continue
        atoms.append(a)
        if a["record"] == "HETATM" and a["resname"] == "307":
            key = (a["chain"], a["resseq"], a["icode"])
            lig_groups.setdefault(key, []).append(a)

    if not lig_groups:
        raise RuntimeError("No crystallographic ligand 307 found in 2AZ5")

    # Prefer the crystallographic ligand instance in auth chain C because RCSB validation
    # reports it as the best-fitted instance; fall back to the first instance.
    keys = list(lig_groups)
    chosen_key = next((k for k in keys if k[0] == "C"), keys[0])
    lig_atoms = lig_groups[chosen_key]
    lig_xyz = np.array([[a["x"], a["y"], a["z"]] for a in lig_atoms], dtype=float)
    center = lig_xyz.mean(axis=0)
    span = lig_xyz.max(axis=0) - lig_xyz.min(axis=0)

    # Use the co-crystal ligand envelope plus 10 A padding in each dimension.
    # Minimum 26 A per dimension; maximum 38 A to keep the search volume tractable.
    size = np.clip(span + 20.0, 26.0, 38.0)

    # Determine which TNF chains contact the selected co-crystal ligand within 8 A.
    protein_atoms = [a for a in atoms if a["record"] == "ATOM"]
    contact_chains = set()
    for a in protein_atoms:
        xyz = np.array([a["x"], a["y"], a["z"]])
        if np.min(np.linalg.norm(lig_xyz - xyz, axis=1)) <= 8.0:
            contact_chains.add(a["chain"])
    if len(contact_chains) < 2:
        # Preserve all protein chains if contact inference is unexpectedly sparse.
        contact_chains = {a["chain"] for a in protein_atoms}

    receptor_pdb = out_dir / "TNF_2AZ5_contact_chains.pdb"
    with open(receptor_pdb, "w", encoding="utf-8") as f:
        for line in lines:
            if line.startswith("ATOM  "):
                a = parse_pdb_atom(line)
                if a["chain"] in contact_chains and a["altloc"] in (" ", "A"):
                    # Normalize altloc A to blank to reduce parser ambiguity.
                    if a["altloc"] == "A":
                        line = line[:16] + " " + line[17:]
                    f.write(line + "\n")
        f.write("END\n")

    native_lig_pdb = out_dir / "2AZ5_native_307.pdb"
    with open(native_lig_pdb, "w", encoding="utf-8") as f:
        for a in lig_atoms:
            f.write(a["line"] + "\n")
        f.write("END\n")

    box = {
        "native_ligand_instance": {"chain": chosen_key[0], "resseq": chosen_key[1]},
        "contact_chains": sorted(contact_chains),
        "center_x": float(center[0]),
        "center_y": float(center[1]),
        "center_z": float(center[2]),
        "size_x": float(size[0]),
        "size_y": float(size[1]),
        "size_z": float(size[2]),
        "padding_rule": "co-crystal ligand 307 bounding box + 10 A per side; clipped to 26-38 A",
    }
    (out_dir / "BOX.json").write_text(json.dumps(box, indent=2), encoding="utf-8")
    return receptor_pdb, native_lig_pdb, box


def prepare_ligand_sdf(raw_sdf: Path, prepared_sdf: Path):
    suppl = Chem.SDMolSupplier(str(raw_sdf), removeHs=False, sanitize=True)
    mol = next((m for m in suppl if m is not None), None)
    if mol is None:
        raise RuntimeError(f"RDKit could not parse {raw_sdf}")
    mol = Chem.AddHs(mol, addCoords=True)
    # Retain PubChem 3D coordinates as the starting conformer; only relax after H addition.
    # MMFF94 is preferred; UFF is a fallback.
    try:
        props = AllChem.MMFFGetMoleculeProperties(mol, mmffVariant="MMFF94")
        if props is not None:
            AllChem.MMFFOptimizeMolecule(mol, mmffVariant="MMFF94", maxIters=500)
        else:
            AllChem.UFFOptimizeMolecule(mol, maxIters=500)
    except Exception:
        pass
    w = Chem.SDWriter(str(prepared_sdf))
    w.write(mol)
    w.close()
    return mol


def parse_best_vina_score(pdbqt: Path):
    pat = re.compile(r"REMARK VINA RESULT:\s+(-?\d+(?:\.\d+)?)")
    for line in pdbqt.read_text(errors="ignore").splitlines():
        m = pat.search(line)
        if m:
            return float(m.group(1))
    return math.nan


def parse_pose_xyz(pdbqt: Path):
    xyz = []
    for line in pdbqt.read_text(errors="ignore").splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            try:
                xyz.append(np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])]))
            except Exception:
                pass
        if line.startswith("ENDMDL") and xyz:
            break
    return xyz


def contact_residues(receptor_pdb: Path, pose_pdbqt: Path, cutoff=4.0):
    lig_xyz = parse_pose_xyz(pose_pdbqt)
    if not lig_xyz:
        return []
    lig_xyz = np.array(lig_xyz)
    residues = set()
    for line in receptor_pdb.read_text(errors="ignore").splitlines():
        if not line.startswith("ATOM  "):
            continue
        a = parse_pdb_atom(line)
        xyz = np.array([a["x"], a["y"], a["z"]])
        if np.min(np.linalg.norm(lig_xyz - xyz, axis=1)) <= cutoff:
            residues.add(f"{a['chain']}:{a['resname']}{a['resseq']}")
    return sorted(residues)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out).resolve()
    raw_dir = out / "01_raw_inputs"
    prep_dir = out / "02_prepared_inputs"
    dock_dir = out / "03_docking"
    tab_dir = out / "04_tables"
    log_dir = out / "05_logs"
    for d in (raw_dir, prep_dir, dock_dir, tab_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Provenance / URLs.
    urls = []
    for name, cid in LIGANDS:
        urls.append((name, f"PubChem CID {cid}", ligand_url(cid)))
    urls.append((CONTROL[0], f"PubChem CID {CONTROL[1]}", ligand_url(CONTROL[1])))
    urls.append(("TNF_alpha", "PDB 2AZ5", PDB_URL))
    with open(out / "SOURCE_URLS.txt", "w", encoding="utf-8") as f:
        for name, ident, url in urls:
            f.write(f"{name} | {ident}\n{url}\n\n")

    # Download receptor and ligands.
    pdb_file = raw_dir / "2AZ5.pdb"
    download(PDB_URL, pdb_file)
    receptor_pdb, native_lig_pdb, box = prepare_receptor_and_box(pdb_file, prep_dir)

    prepared = []
    for name, cid in LIGANDS + [CONTROL]:
        raw_sdf = raw_dir / f"{name}_CID{cid}_PubChem3D.sdf"
        prep_sdf = prep_dir / f"{name}_CID{cid}_prepared.sdf"
        download(ligand_url(cid), raw_sdf)
        mol = prepare_ligand_sdf(raw_sdf, prep_sdf)
        prepared.append((name, cid, prep_sdf, mol.GetNumHeavyAtoms(), Chem.rdMolDescriptors.CalcExactMolWt(mol)))

    # Record environment.
    run(["vina", "--version"], stdout_file=log_dir / "vina_version.txt")
    run([sys.executable, "-m", "pip", "freeze"], stdout_file=log_dir / "python_environment.txt")

    # Receptor PDBQT + Vina box config.
    rec_base = prep_dir / "TNF_2AZ5_receptor"
    cmd = [
        "mk_prepare_receptor.py", "--read_pdb", str(receptor_pdb),
        "-o", str(rec_base), "-p", "-v",
        "--default_altloc", "A",
        "--box_center", f"{box['center_x']:.3f}", f"{box['center_y']:.3f}", f"{box['center_z']:.3f}",
        "--box_size", f"{box['size_x']:.3f}", f"{box['size_y']:.3f}", f"{box['size_z']:.3f}",
    ]
    run(cmd, stdout_file=log_dir / "receptor_preparation.log")
    receptor_pdbqt = prep_dir / "TNF_2AZ5_receptor.pdbqt"
    if not receptor_pdbqt.exists():
        # Meeko may append suffixes depending on version.
        candidates = list(prep_dir.glob("TNF_2AZ5_receptor*.pdbqt"))
        if not candidates:
            raise RuntimeError("Meeko did not create receptor PDBQT")
        receptor_pdbqt = candidates[0]

    # Prepare each ligand and dock. Same receptor, box, seed, exhaustiveness.
    rows = []
    for name, cid, prep_sdf, heavy_atoms, exact_mw in prepared:
        lig_pdbqt = prep_dir / f"{name}_CID{cid}.pdbqt"
        run(["mk_prepare_ligand.py", "-i", str(prep_sdf), "-o", str(lig_pdbqt)],
            stdout_file=log_dir / f"{name}_ligand_preparation.log")

        pose = dock_dir / f"{name}_CID{cid}_vina_out.pdbqt"
        vlog = log_dir / f"{name}_vina.log"
        vina_cmd = [
            "vina",
            "--receptor", str(receptor_pdbqt),
            "--ligand", str(lig_pdbqt),
            "--center_x", f"{box['center_x']:.3f}",
            "--center_y", f"{box['center_y']:.3f}",
            "--center_z", f"{box['center_z']:.3f}",
            "--size_x", f"{box['size_x']:.3f}",
            "--size_y", f"{box['size_y']:.3f}",
            "--size_z", f"{box['size_z']:.3f}",
            "--exhaustiveness", "64",
            "--num_modes", "20",
            "--energy_range", "5",
            "--seed", "20260816",
            "--out", str(pose),
        ]
        run(vina_cmd, stdout_file=vlog)
        score = parse_best_vina_score(pose)
        contacts = contact_residues(receptor_pdb, pose, cutoff=4.0)

        # Export docking poses to SDF when possible.
        exported = dock_dir / f"{name}_CID{cid}_vina_out.sdf"
        try:
            run(["mk_export.py", str(pose), "-s", str(exported)],
                stdout_file=log_dir / f"{name}_export.log")
        except Exception as e:
            (log_dir / f"{name}_export_error.txt").write_text(str(e), encoding="utf-8")

        rows.append({
            "compound": name,
            "pubchem_cid": cid,
            "role": "positive_control" if name == CONTROL[0] else "GHYSJ_TNF_candidate",
            "best_vina_affinity_kcal_mol": score,
            "heavy_atoms": heavy_atoms,
            "exact_mol_wt": round(exact_mw, 4),
            "contact_residues_within_4A": "; ".join(contacts),
            "receptor": "TNF-alpha 2AZ5",
            "native_pocket_ligand": "307 / SPD-304",
            "seed": 20260816,
            "exhaustiveness": 64,
            "num_modes": 20,
        })

    # Rank GHYSJ candidates only, score more negative = better.
    ghysj = [r for r in rows if r["role"] == "GHYSJ_TNF_candidate"]
    ghysj.sort(key=lambda r: (math.isnan(r["best_vina_affinity_kcal_mol"]), r["best_vina_affinity_kcal_mol"]))
    for i, r in enumerate(ghysj, 1):
        r["rank_within_7"] = i
    for r in rows:
        if r["role"] == "positive_control":
            r["rank_within_7"] = ""

    fields = [
        "rank_within_7", "compound", "pubchem_cid", "role",
        "best_vina_affinity_kcal_mol", "heavy_atoms", "exact_mol_wt",
        "contact_residues_within_4A", "receptor", "native_pocket_ligand",
        "seed", "exhaustiveness", "num_modes"
    ]
    with open(tab_dir / "GHYSJ_TNF_docking_summary.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for r in ghysj + [r for r in rows if r["role"] == "positive_control"]:
            w.writerow(r)

    with open(tab_dir / "GHYSJ_TNF_docking_summary.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in ghysj + [r for r in rows if r["role"] == "positive_control"]:
            w.writerow(r)

    method = f"""GHYSJ-TNF molecular docking reproducibility note
================================================
Receptor: human TNF-alpha, PDB 2AZ5 (X-ray, co-crystallized ligand 307/SPD-304).
Pocket definition: geometric center of crystallographic ligand 307 instance {box['native_ligand_instance']}.
Protein chains retained: {', '.join(box['contact_chains'])} (chains with protein atoms within 8 A of the chosen crystallographic ligand; fallback all chains if <2).
Grid center (A): {box['center_x']:.3f}, {box['center_y']:.3f}, {box['center_z']:.3f}
Grid size (A): {box['size_x']:.3f}, {box['size_y']:.3f}, {box['size_z']:.3f}
Ligands: PubChem 3D SDF structures; explicit H added with RDKit; MMFF94 minimization when available, UFF fallback.
PDBQT preparation: Meeko 0.7.1.
Docking: AutoDock Vina 1.2.7; exhaustiveness=64; num_modes=20; energy_range=5 kcal/mol; seed=20260816.
Positive control: SPD-304, PubChem CID 5327044, docked into its crystallographic TNF pocket as a score/pose plausibility reference. No RMSD claim is made in this automated run.
Contact residues: protein residues with any receptor atom within 4.0 A of the best Vina pose; these are proximity contacts, not automatically classified as hydrogen bonds.
Interpretation: docking affinity and pose are computational structural-support evidence only and do not establish biochemical binding or regulatory direction.
"""
    (out / "METHODS_AND_INTERPRETATION.txt").write_text(method, encoding="utf-8")

    # Machine-readable provenance.
    provenance = {
        "pdb_id": PDB_ID,
        "pdb_url": PDB_URL,
        "ligands": [{"name": n, "cid": c, "url": ligand_url(c)} for n, c in LIGANDS],
        "positive_control": {"name": CONTROL[0], "cid": CONTROL[1], "url": ligand_url(CONTROL[1])},
        "box": box,
        "vina": {"version": "1.2.7", "exhaustiveness": 64, "num_modes": 20, "energy_range": 5, "seed": 20260816},
        "meeko": "0.7.1",
    }
    (out / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Docking completed. Summary:")
    for r in ghysj:
        print(r["rank_within_7"], r["compound"], r["best_vina_affinity_kcal_mol"])


if __name__ == "__main__":
    main()
