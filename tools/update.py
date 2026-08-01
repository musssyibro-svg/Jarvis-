"""
tools/update.py — get the newest Jarvis without needing git.

Why this exists: the working copy on the target machine is not a git checkout.
It was unzipped, so `git pull` answers "fatal: not a git repository" forever,
and the only way to update is to download a ZIP by hand and copy files around —
which is where a database, a saved login or a .env quietly gets destroyed.

Two paths, chosen automatically:

  * a real checkout  -> git pull
  * anything else    -> download the branch ZIP and unpack it over the top

The second path is the careful one. It NEVER touches:

    backend/jarvis.db          your history, learned timings, settings
    backend/browser-profile/   sites you're logged into
    backend/.env               your keys
    backend/.jarvis_token      your auth token
    backend/screenshots/       proof of what was submitted

Those are yours. Everything else is code and gets replaced.

From mainland China, github.com is frequently unreachable — that is exactly the
failure in the logs, a 21-second timeout to port 443. So several mirrors are
tried in order, the China-hosted ones first, and each one reports its own
result rather than the whole thing failing with one opaque message.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER, REPO = "musssyibro-svg", "Jarvis-"
BRANCH = os.getenv("JARVIS_BRANCH", "claude/jarvis-automation-rebuild-37xvhr")

# Anything here is the user's, not ours. Never overwritten, never deleted.
KEEP = [
    "backend/jarvis.db",
    "backend/jarvis.db-wal",
    "backend/jarvis.db-shm",
    "backend/.env",
    "backend/.jarvis_token",
    "backend/browser-profile",
    "backend/screenshots",
    "backend/agents/custom",
    "frontend/node_modules",
]


def _zip_urls() -> list[str]:
    """Mirrors first — codeload.github.com is the one that times out from here."""
    q = BRANCH.replace("/", "%2F")
    return [
        f"https://ghproxy.net/https://github.com/{OWNER}/{REPO}/archive/refs/heads/{BRANCH}.zip",
        f"https://mirror.ghproxy.com/https://github.com/{OWNER}/{REPO}/archive/refs/heads/{BRANCH}.zip",
        f"https://gh-proxy.com/https://github.com/{OWNER}/{REPO}/archive/refs/heads/{BRANCH}.zip",
        f"https://codeload.github.com/{OWNER}/{REPO}/zip/refs/heads/{BRANCH}",
        f"https://github.com/{OWNER}/{REPO}/archive/refs/heads/{q}.zip",
    ]


def say(msg: str = "") -> None:
    print(msg, flush=True)


def _is_git_checkout() -> bool:
    return (ROOT / ".git").is_dir()


def _git_pull() -> bool:
    say("  This is a git checkout. Pulling.")
    try:
        r = subprocess.run(["git", "pull", "origin", BRANCH], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=300)
        say("  " + (r.stdout or r.stderr or "").strip().replace("\n", "\n  "))
        return r.returncode == 0
    except FileNotFoundError:
        say("  git isn't installed. Falling back to the ZIP download.")
        return False
    except Exception as e:
        say(f"  git pull failed: {e}")
        return False


def _download() -> bytes | None:
    last = ""
    for i, url in enumerate(_zip_urls(), 1):
        host = url.split("/")[2]
        say(f"  [{i}/{len(_zip_urls())}] trying {host} ...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jarvis-update"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            if len(data) < 10_000:
                last = f"{host} returned only {len(data)} bytes"
                say(f"        too small, skipping ({last})")
                continue
            say(f"        got {len(data) / 1e6:.1f} MB")
            return data
        except Exception as e:
            last = f"{host}: {str(e)[:90]}"
            say(f"        no ({str(e)[:70]})")
    say("")
    say("  Every source failed. The last error was:")
    say(f"      {last}")
    say("")
    say("  Your network can't reach GitHub or any of its mirrors right now.")
    say("  Try again in a few minutes, or download the ZIP in a browser:")
    say(f"      https://github.com/{OWNER}/{REPO}/tree/{BRANCH}")
    say("      Code -> Download ZIP, then extract over this folder.")
    return None


def _protect() -> Path | None:
    """Move the user's files somewhere safe before we overwrite anything."""
    stash = ROOT / f".update-keep-{int(time.time())}"
    moved = []
    for rel in KEEP:
        src = ROOT / rel
        if not src.exists():
            continue
        dst = stash / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append(rel)
    if not moved:
        return None
    say(f"  Set aside {len(moved)} of your own file(s)/folder(s): "
        + ", ".join(m.split('/')[-1] for m in moved))
    return stash


def _restore(stash: Path | None) -> None:
    if not stash or not stash.exists():
        return
    for rel in KEEP:
        src = stash / rel
        if not src.exists():
            continue
        dst = ROOT / rel
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True) if dst.is_dir() else dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    shutil.rmtree(stash, ignore_errors=True)
    say("  Put your data back.")


def _unpack(data: bytes) -> bool:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:
        say(f"  That download isn't a valid ZIP ({e}). Nothing was changed.")
        return False

    names = zf.namelist()
    if not names:
        say("  The ZIP is empty. Nothing was changed.")
        return False
    top = names[0].split("/")[0] + "/"

    # Unpack to a temporary folder FIRST. Extracting straight over the working
    # copy means a download that dies half-way leaves a half-replaced install,
    # which is worse than not updating at all.
    tmp = ROOT / f".update-new-{int(time.time())}"
    try:
        zf.extractall(tmp)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        say(f"  Couldn't unpack: {e}. Nothing was changed.")
        return False

    src_root = tmp / top.rstrip("/")
    if not src_root.is_dir():
        shutil.rmtree(tmp, ignore_errors=True)
        say("  The ZIP has an unexpected shape. Nothing was changed.")
        return False

    stash = _protect()
    copied = 0
    try:
        for item in src_root.iterdir():
            dst = ROOT / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
            copied += 1
    finally:
        _restore(stash)
        shutil.rmtree(tmp, ignore_errors=True)
    say(f"  Replaced {copied} top-level item(s) with the new version.")
    return True


def main() -> int:
    say()
    say("=" * 62)
    say("  JARVIS UPDATE")
    say("=" * 62)
    say(f"  Folder: {ROOT}")
    say(f"  Branch: {BRANCH}")
    say()

    if _is_git_checkout() and _git_pull():
        say()
        say("  Updated. Now run START.bat.")
        return 0

    if _is_git_checkout():
        say("  git pull didn't work. Trying the ZIP instead.")
    else:
        say("  This folder isn't a git checkout, so there's nothing to pull.")
        say("  Downloading the current version as a ZIP.")
    say()

    data = _download()
    if data is None:
        return 1
    say()
    if not _unpack(data):
        return 1

    say()
    say("  Updated. Your database, logins and settings were kept.")
    say("  Now run START.bat - it will install anything new.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\n  Cancelled. Nothing was changed.")
        sys.exit(1)
