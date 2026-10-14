#!/usr/bin/env python3
"""
push_code.py — bot ki CODE files GitHub repo mein push karta hai (git ke bina).
GitHub API use karta hai. Push hone par Railway khud naya deploy chala dega.

Usage:
  python push_code.py              # code files sync karo
  python push_code.py --dry-run    # sirf batao kya push hoga

Secrets (.env) aur netflix_accounts/ yahan nahi jate — unchahi push_accounts.py.
"""
import sys
from pathlib import Path

import httpx

import push_accounts as pa

BASE_DIR = Path(__file__).resolve().parent

# Ye files repo mein push hongi (secrets aur accounts NAHI)
CODE_FILES = [
    "bot.py",
    "push_accounts.py",
    "push_code.py",
    "requirements.txt",
    "Dockerfile",
    "Procfile",
    "deploy.sh",
    "push.bat",
    ".dockerignore",
    ".gitignore",
    ".env.example",
]


def main() -> None:
    dry = "--dry-run" in sys.argv

    print(f"📦 Repo  : {pa.GITHUB_REPO}")
    print(f"🔑 Token : {'✅ set' if pa.GITHUB_TOKEN else '⚠️  missing'}")
    print(f"🧪 Mode  : {'DRY-RUN' if dry else 'LIVE'}\n")

    if not pa.GITHUB_TOKEN and not dry:
        print("❌ GITHUB_TOKEN missing — .env mein daalo.")
        return

    counts = {"new": 0, "updated": 0, "skip": 0, "na": 0}
    with httpx.Client(timeout=30.0) as client:
        for name in CODE_FILES:
            local = BASE_DIR / name
            if not local.exists():
                counts["na"] += 1
                print(f"   ➖ {name} (local par nahi hai)")
                continue
            result = pa.upload(client, local, name, dry)
            counts[result] += 1
            icon = {"new": "🆕", "updated": "♻️ ", "skip": "⚠️ "}[result]
            print(f"   {icon} {name}")

    print(f"\n✅ Done — new: {counts['new']}, updated: {counts['updated']}, "
          f"failed: {counts['skip']}, missing: {counts['na']}")
    if not dry and counts["skip"]:
        print("\n⚠️  Kuch files fail hui — upar error hint dekho.")
        print("   Token ke liye: classic token mein 'repo' scope, ya fine-grained mein Contents=Read/write.")
    elif not dry:
        print("🚀 Railway ab khud naya deploy chala dega (repo se auto-deploy).")


if __name__ == "__main__":
    main()