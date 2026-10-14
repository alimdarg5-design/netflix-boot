#!/usr/bin/env python3
"""
push_accounts.py — netflix_accounts/ folder ka data GitHub repo mein upload karta hai.
Git ki zaroorat NAHI — GitHub REST API use karta hai (httpx, jo pehle se installed hai).

Usage:
  python push_accounts.py                 # ek baar: poora folder sync karo
  python push_accounts.py --watch         # har 30s check karo, nayi file auto-push
  python push_accounts.py --watch --interval 10
  python push_accounts.py --dry-run       # sirf batao kya push hoga, upload na karo
  python push_accounts.py --folder netflix_accounts

Config (.env se ya environment variables se):
  GITHUB_REPO   -> alimdarg5-design/netflix-boot
  GITHUB_TOKEN  -> GitHub PAT (Contents: Read and write)
  ACCOUNTS_FOLDER -> netflix_accounts
"""
import os
import sys
import time
import base64
import argparse
from pathlib import Path

import httpx

# Windows console (cp1252) emoji print nahi kar sakta — UTF-8 force karo
for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent


def load_env() -> None:
    """Chhota .env loader (python-dotenv dependency ke bina)."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_env()

GITHUB_REPO     = os.environ.get("GITHUB_REPO", "alimdarg5-design/netflix-boot")
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
ACCOUNTS_FOLDER = os.environ.get("ACCOUNTS_FOLDER", "netflix_accounts")
API             = "https://api.github.com"


def headers() -> dict:
    h = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "NetflixVIPBot-Pusher/1.0",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def remote_sha(client: httpx.Client, path: str) -> str | None:
    """Repo mein file ka maujooda sha (update ke liye)."""
    url = f"{API}/repos/{GITHUB_REPO}/contents/{path}"
    r = client.get(url, headers=headers())
    if r.status_code == 200:
        return r.json().get("sha")
    return None


def upload(client: httpx.Client, local: Path, repo_path: str, dry: bool) -> str:
    """File ko create ya update karta hai. Return: 'new' | 'updated' | 'skip'."""
    content = base64.b64encode(local.read_bytes()).decode()
    sha = remote_sha(client, repo_path)

    if dry:
        return "updated" if sha else "new"

    payload = {
        "message": f"📤 Sync account: {local.name}",
        "content": content,
    }
    if sha:
        payload["sha"] = sha

    url = f"{API}/repos/{GITHUB_REPO}/contents/{repo_path}"
    r = client.put(url, headers=headers(), json=payload)
    if r.status_code in (200, 201):
        return "updated" if sha else "new"

    # Friendly error hints — 403/404 aksar token permission ka masla hota hai
    msg = (r.json().get("message") if r.headers.get("content-type", "").startswith("application/json") else r.text[:160])
    print(f"   ❌ {local.name} -> {r.status_code}: {msg}")
    if r.status_code in (401, 403, 404):
        print("      ⚠️  Token ki permission check karo:")
        print("         Classic token : scope mein 'repo' tick hona chahiye.")
        print("         Fine-grained  : Contents = Read and write, repo select ho.")
    return "skip"


def collect_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".txt")


def sync_file(client: httpx.Client, folder: Path, f: Path, dry: bool) -> str:
    """Ek file ko upload karo. Return: 'new' | 'updated' | 'skip'."""
    rel = f.relative_to(folder).as_posix()
    repo_path = f"{ACCOUNTS_FOLDER}/{rel}"
    result = upload(client, f, repo_path, dry)
    icon = {"new": "🆕", "updated": "♻️ ", "skip": "⚠️ "}[result]
    print(f"   {icon} {repo_path}")
    return result


def sync_once(folder: Path, dry: bool) -> int:
    files = collect_files(folder)
    if not files:
        print(f"⚠️  '{folder}' mein koi .txt file nahi mili.")
        return 0
    if not GITHUB_TOKEN and not dry:
        print("❌ GITHUB_TOKEN missing hai — .env mein daalo.")
        return 0

    print(f"🔎 {len(files)} file(s) mili — repo '{GITHUB_REPO}' mein upload ho rahi hain...")
    counts = {"new": 0, "updated": 0, "skip": 0}
    with httpx.Client(timeout=30.0) as client:
        for f in files:
            counts[sync_file(client, folder, f, dry)] += 1
    print(f"\n✅ Done — new: {counts['new']}, updated: {counts['updated']}, failed: {counts['skip']}")
    return counts["new"] + counts["updated"]


def main() -> None:
    ap = argparse.ArgumentParser(description="netflix_accounts/ folder ko GitHub par push karo")
    ap.add_argument("--folder", default=None, help="local folder (default: ACCOUNTS_FOLDER)")
    ap.add_argument("--watch", action="store_true", help="folder ko monitor karo, nayi file auto-push")
    ap.add_argument("--interval", type=int, default=30, help="watch interval seconds (default 30)")
    ap.add_argument("--dry-run", action="store_true", help="upload na karo, sirf report")
    args = ap.parse_args()

    folder = BASE_DIR / (args.folder or ACCOUNTS_FOLDER)
    print(f"📁 Folder : {folder}")
    print(f"📦 Repo   : {GITHUB_REPO}")
    print(f"🔑 Token  : {'✅ set' if GITHUB_TOKEN else '⚠️  missing'}\n")

    if not args.watch:
        sync_once(folder, args.dry_run)
        return

    print(f"👀 Watch mode — har {args.interval}s check hoga. Rokne ke liye Ctrl+C.\n")
    fingerprint: dict[str, float] = {}
    try:
        with httpx.Client(timeout=30.0) as client:
            while True:
                files = collect_files(folder)
                current = {f.relative_to(folder).as_posix(): f.stat().st_mtime for f in files}

                # Nayi ya badli hui files hi push karo (warna har cycle naya commit)
                pending = [f for f in files
                           if current[f.relative_to(folder).as_posix()] != fingerprint.get(f.relative_to(folder).as_posix())]

                if pending:
                    print(f"\n🔄 {len(pending)} file(s) change hui — push ho rahi hain...")
                    for f in pending:
                        sync_file(client, folder, f, args.dry_run)
                    fingerprint = current
                    print(f"⏳ Agla check {args.interval}s baad...")

                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n🛑 Watch band kar diya.")


if __name__ == "__main__":
    main()