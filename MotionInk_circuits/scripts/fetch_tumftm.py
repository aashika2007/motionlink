#!/usr/bin/env python3
"""Download real circuit data from the TUMFTM racetrack-database (LGPL-3.0).

    python scripts/fetch_tumftm.py --tracks Spielberg Monza Silverstone
    python scripts/fetch_tumftm.py --all
    python scripts/fetch_tumftm.py --from-clone ../racetrack-database --tracks Spielberg   # offline copy
    python scripts/fetch_tumftm.py --list

Each file is checked against the git blob SHA that GitHub reports for it, so the local
copy is byte-identical to the repository. Results go to motionink/circuits/data/tumftm/
(or $MOTIONINK_CIRCUIT_DATA) with a manifest.json recording commit, URLs and hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "TUMFTM/racetrack-database"
API = f"https://api.github.com/repos/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path(os.environ.get("MOTIONINK_CIRCUIT_DATA") or ROOT / "motionink" / "circuits" / "data" / "tumftm")


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def get(url: str, as_json=False):
    req = urllib.request.Request(url, headers={"User-Agent": "motionink-fetch", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return json.loads(data) if as_json else data


def list_remote():
    commit = get(f"{API}/commits/master", as_json=True)["sha"]
    files = {}
    for folder in ("tracks", "racelines"):
        for item in get(f"{API}/contents/{folder}?ref={commit}", as_json=True):
            if item["type"] == "file" and item["name"].lower().endswith(".csv"):
                files[f"{folder}/{item['name']}"] = {"sha": item["sha"], "url": f"{RAW}/{commit}/{folder}/{item['name']}"}
    return commit, files


def list_clone(path: Path):
    try:
        commit = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    files = {}
    for folder in ("tracks", "racelines"):
        for f in sorted((path / folder).glob("*.csv")):
            files[f"{folder}/{f.name}"] = {"sha": None, "url": None, "local": str(f)}
    return commit, files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tracks", nargs="*", default=[], help="Track names, e.g. Spielberg Monza (case-insensitive)")
    ap.add_argument("--all", action="store_true", help="Download every track")
    ap.add_argument("--list", action="store_true", help="List available tracks and exit")
    ap.add_argument("--from-clone", type=Path, help="Copy from a local git clone instead of downloading")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args()

    try:
        commit, files = list_clone(a.from_clone) if a.from_clone else list_remote()
    except urllib.error.HTTPError as exc:
        sys.exit(f"GitHub API error {exc.code}. If rate-limited, wait an hour or use:\n"
                 f"  git clone https://github.com/{REPO}\n  python scripts/fetch_tumftm.py --from-clone racetrack-database --tracks ...")
    except urllib.error.URLError as exc:
        sys.exit(f"Network error: {exc.reason}. Use --from-clone with a local git clone.")

    names = sorted({k.split("/", 1)[1][:-4] for k in files if k.startswith("tracks/")})
    if a.list or not (a.all or a.tracks):
        print(f"{REPO} @ {commit or 'unknown commit'}: {len(names)} tracks")
        for n in names:
            print(f"  {n:15s} raceline: {'yes' if f'racelines/{n}.csv' in files else 'no'}")
        if not (a.all or a.tracks):
            print("\nChoose with --tracks NAME ... or --all")
        return

    lookup = {n.lower(): n for n in names}
    wanted = names if a.all else []
    for t in a.tracks:
        if t.lower() not in lookup:
            sys.exit(f"Unknown track '{t}'. Available: {', '.join(names)}")
        wanted.append(lookup[t.lower()])

    out = a.out
    (out / "tracks").mkdir(parents=True, exist_ok=True)
    (out / "racelines").mkdir(parents=True, exist_ok=True)
    man_path = out / "manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else {"files": {}}
    if manifest.get("commit") and commit and manifest["commit"] != commit:
        print(f"Note: existing files came from commit {manifest['commit']}; new files from {commit}.")

    ok = True
    for name in wanted:
        for folder in ("tracks", "racelines"):
            key = f"{folder}/{name}.csv"
            if key not in files:
                if folder == "racelines":
                    print(f"  {name}: no reference race line in the dataset")
                continue
            info = files[key]
            data = Path(info["local"]).read_bytes() if a.from_clone else get(info["url"])
            blob = git_blob_sha(data)
            verified = info["sha"] is None or blob == info["sha"]
            if not verified:
                ok = False
                print(f"  {key}: HASH MISMATCH (got {blob}, GitHub says {info['sha']}), not saved")
                continue
            (out / key).write_bytes(data)
            manifest["files"][key] = {
                "url": info["url"] or f"local clone {a.from_clone}", "git_blob_sha1": blob,
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "verified_against_github": info["sha"] is not None,
            }
            print(f"  {key}: {len(data):,} bytes, {'blob hash verified' if info['sha'] else 'copied from clone'}")

    lic_src = (a.from_clone / "LICENSE") if a.from_clone else None
    try:
        lic = lic_src.read_bytes() if lic_src else get(f"{RAW}/{commit}/LICENSE")
        (out / "LICENSE").write_bytes(lic)
    except (OSError, urllib.error.URLError):
        print("  (could not copy LICENSE; the dataset is LGPL-3.0)")
    manifest.update(dataset=f"https://github.com/{REPO}", license="LGPL-3.0", commit=commit,
                    fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    man_path.write_text(json.dumps(manifest, indent=2))
    print(f"Saved to {out}")
    print("Next: python -m motionink.circuits.report " + " ".join(wanted[:3]))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
