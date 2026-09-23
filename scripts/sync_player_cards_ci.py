#!/usr/bin/env python3
"""Pull merged card store + PBP caches from the latest player-cards-build workflow."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_cards.leagues import player_cards_work_root

REPO = "emilyfehr99/automated-scraping"
WORKFLOW = "player-cards-build.yml"
DEFAULT_PBP_ROOT = None  # resolved at runtime via player_cards_work_root()
DEFAULT_STORE = Path.home() / ".cache" / "player-cards" / "card_store.db"
ALL_SHARDS = range(1, 10)


def _run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def latest_success_run_id() -> str:
    rows = json.loads(
        _run([
            "gh", "run", "list",
            f"--repo={REPO}",
            f"--workflow={WORKFLOW}",
            "--limit=20",
            "--json=databaseId,status,conclusion",
        ])
    )
    for row in rows:
        if row.get("status") == "completed" and row.get("conclusion") == "success":
            return str(row["databaseId"])
    raise RuntimeError("No successful player-cards-build run found")


def _extract_tar(arc: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(arc, "r:gz") as tf:
        tf.extractall(dest)


def _download_artifact(run_id: str, name: str, dest: Path) -> bool:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        _run([
            "gh", "run", "download", run_id,
            f"--repo={REPO}",
            f"--name={name}",
            f"--dir={dest}",
        ])
        return True
    except subprocess.CalledProcessError:
        return False


def sync_pbp_shards(run_id: str, dest: Path) -> int:
    staging = dest.parent / f".player-cards-sync-{run_id}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    ok = 0

    for shard in ALL_SHARDS:
        name = f"pbp-cache-shard-{shard}"
        shard_dir = staging / name
        print(f"Downloading {name}...")
        if not _download_artifact(run_id, name, shard_dir):
            print(f"  skip: {name} not in run")
            continue
        archives = list(shard_dir.rglob("pbp-cache-shard-*.tar.gz"))
        if not archives:
            print(f"  skip: no tar in {name}")
            continue
        for arc in archives:
            print(f"  extracting {arc.name} -> {dest}")
            _extract_tar(arc, dest)
        ok += 1

    shutil.rmtree(staging, ignore_errors=True)
    return ok


def sync_store(run_id: str, store_path: Path) -> None:
    staging = store_path.parent / f".store-sync-{run_id}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    print("Downloading card-store-merged...")
    if not _download_artifact(run_id, "card-store-merged", staging):
        raise RuntimeError("card-store-merged artifact missing from workflow run")
    candidates = list(staging.rglob("card_store.db"))
    if not candidates:
        raise RuntimeError("card_store.db not found in merged artifact")
    store_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidates[0], store_path)
    shutil.rmtree(staging, ignore_errors=True)
    print(f"Installed store -> {store_path}")


def count_pbp(root: Path) -> tuple[int, int]:
    files = list(root.glob("**/Instat_API_Downloads/*_pbp.csv"))
    teams = {f.parent.parent.name for f in files}
    return len(files), len(teams)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync PBP + card store from GitHub Actions player-cards-build",
    )
    parser.add_argument("--run-id", help="Workflow run id (default: latest success)")
    parser.add_argument(
        "--pbp-dest",
        type=Path,
        default=None,
        help="Unpack PBP team folders here (default: PLAYER_CARDS_WORK_ROOT / Desktop)",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE,
        help="Install merged SQLite card store",
    )
    parser.add_argument("--pbp-only", action="store_true")
    parser.add_argument("--store-only", action="store_true")
    args = parser.parse_args()
    pbp_dest = args.pbp_dest or player_cards_work_root()

    run_id = args.run_id or latest_success_run_id()
    print(f"Syncing from workflow run {run_id}")

    if not args.store_only:
        n = sync_pbp_shards(run_id, pbp_dest)
        files, teams = count_pbp(pbp_dest)
        print(f"PBP: {n} shards unpacked | {files} CSV files | {teams} team folders")
        if files == 0:
            print("No PBP files unpacked", file=sys.stderr)
            sys.exit(1)

    if not args.pbp_only:
        sync_store(run_id, args.store)

    print("Done. Generate cards with:")
    print('  cd automated-scraping && PYTHONPATH=. python3 -m player_cards "Player Name"')


if __name__ == "__main__":
    main()
