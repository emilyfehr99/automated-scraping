#!/usr/bin/env python3
"""Sync NHL InStat PBP from GitHub Actions pbp-cache-shard-*.tar.gz artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = "emilyfehr99/automated-scraping"
WORKFLOW = "player-cards-build.yml"
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / ".player-cards-data"
NHL_SHARDS = range(1, 9)


def _run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def latest_run_id() -> str:
    rows = json.loads(_run([
        "gh", "run", "list",
        f"--repo={REPO}",
        f"--workflow={WORKFLOW}",
        "--limit=30",
        "--json=databaseId,status,conclusion",
    ]))
    for row in rows:
        if row.get("status") == "completed" and row.get("conclusion") in ("success", "failure"):
            return str(row["databaseId"])
    raise RuntimeError("No completed workflow runs found")


def _extract_tar(arc: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(arc, "r:gz") as tf:
        tf.extractall(dest)


def download_shards(run_id: str, dest: Path) -> int:
    staging = dest.parent / f".pbp-sync-staging-{run_id}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    ok = 0

    for shard in NHL_SHARDS:
        name = f"pbp-cache-shard-{shard}"
        shard_dir = staging / name
        shard_dir.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {name} from run {run_id}...")
        try:
            _run([
                "gh", "run", "download", run_id,
                f"--repo={REPO}",
                f"--name={name}",
                f"--dir={shard_dir}",
            ])
        except subprocess.CalledProcessError:
            print(f"  skip: {name} not in run artifacts", file=sys.stderr)
            continue

        archives = list(shard_dir.rglob("pbp-cache-shard-*.tar.gz"))
        if not archives:
            print(f"  skip: no tar in {name}", file=sys.stderr)
            continue
        for arc in archives:
            print(f"  extracting {arc.name}")
            _extract_tar(arc, dest)
        ok += 1

    shutil.rmtree(staging, ignore_errors=True)
    return ok


def count_games(root: Path) -> tuple[int, int]:
    files = list(root.glob("**/Instat_API_Downloads/*_pbp.csv"))
    game_ids = set()
    for f in files:
        parts = f.stem.split("_")
        game_ids.add(parts[-1] if parts else f.stem)
    teams = {f.parent.parent.name for f in files}
    return len(game_ids), len(teams)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and unpack PBP cache from player-cards-build workflow",
    )
    parser.add_argument("--run-id", help="Workflow run id (default: latest completed)")
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_ROOT,
        help="PLAYER_CARDS_WORK_ROOT (default: automated-scraping/.player-cards-data)",
    )
    args = parser.parse_args()

    run_id = args.run_id or latest_run_id()
    dest: Path = args.dest
    dest.mkdir(parents=True, exist_ok=True)

    print(f"Syncing PBP from run {run_id} -> {dest}")
    n = download_shards(run_id, dest)
    games, teams = count_games(dest)
    print(f"Shards unpacked: {n} | ~{games} games | {teams} team folders")
    if games == 0:
        print(
            "\nNo PBP files yet. The workflow must finish with pbp-cache-shard tar artifacts.\n"
            "Trigger: gh workflow run player-cards-build.yml -f shard=all",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
