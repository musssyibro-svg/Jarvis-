"""
services/app_resolver.py — find the real executable for an app name, and REMEMBER it.

The "Windows cannot find the file qq" dialog came from open_app falling back to
`cmd /c start qq`, which pops a visible error when the name isn't a shell target.
Chinese-market apps (QQ, Doubao, WeChat) aren't on PATH and aren't in the small
KNOWN map, so every launch was a guess.

Fix (this is the World Model's "executable paths" the roadmap asked for):
  1. Look the name up in a cache table (app_paths). If we've resolved it before,
     launch that exact .exe — instant, reliable, no dialog.
  2. Otherwise search the Start Menu shortcuts, the registry App Paths, and
     common install dirs. Resolve any .lnk to its target. Cache the winner.
  3. Only if nothing is found do we fall back to the Start-Menu-search keystroke
     trick (Win -> type -> Enter), which is what actually worked for QQ before.

All Windows calls are guarded and time-boxed; on non-Windows it degrades to PATH
lookup. Nothing here raises.
"""
import os
import shutil
import subprocess
from datetime import datetime, timezone

from models.db import conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_paths (
    name       TEXT PRIMARY KEY,     -- lowercased app name/alias
    path       TEXT NOT NULL,        -- resolved executable
    source     TEXT,                 -- cache origin: startmenu | registry | known | manual
    verified_at TEXT
);
"""

# Common alias -> search terms (helps QQ/Doubao/WeChat resolve their real names).
ALIASES = {
    "qq": ["qq", "腾讯qq", "tencent qq"],
    "wechat": ["wechat", "weixin", "微信"],
    "doubao": ["doubao", "豆包"],
    "tim": ["tim"],
    "chrome": ["google chrome", "chrome"],
    "edge": ["microsoft edge", "edge"],
    "vscode": ["visual studio code", "code"],
    "notepad": ["notepad"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_app_paths() -> None:
    with conn() as db:
        db.executescript(SCHEMA)


def _key(name: str) -> str:
    return (name or "").strip().lower()


def get_cached(name: str) -> str | None:
    try:
        init_app_paths()
        with conn() as db:
            row = db.execute("SELECT path FROM app_paths WHERE name=?", (_key(name),)).fetchone()
        if row and row["path"] and os.path.exists(row["path"]):
            return row["path"]
    except Exception:
        pass
    return None


def remember(name: str, path: str, source: str = "startmenu") -> None:
    try:
        init_app_paths()
        with conn() as db:
            db.execute("INSERT OR REPLACE INTO app_paths(name,path,source,verified_at) "
                       "VALUES(?,?,?,?)", (_key(name), path, source, _now()))
    except Exception:
        pass


def _ps(cmd: str, timeout: int = 8) -> str:
    """Run a PowerShell one-liner, return stdout (empty on any failure)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _find_start_menu(name: str) -> str | None:
    """Search Start Menu .lnk shortcuts and resolve the best match to its target exe."""
    terms = ALIASES.get(_key(name), [name])
    like = " -or ".join([f"$_.BaseName -like '*{t}*'" for t in terms])
    # Find a matching shortcut, preferring shorter names (closer match).
    find = (
        "$dirs=@(\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\","
        "\"$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\");"
        f"Get-ChildItem -Path $dirs -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | "
        f"Where-Object {{ {like} }} | Sort-Object {{ $_.BaseName.Length }} | "
        "Select-Object -First 1 -ExpandProperty FullName"
    )
    lnk = _ps(find)
    if not lnk:
        return None
    # Resolve the shortcut's target executable.
    resolve = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
               "$s.TargetPath")
    target = _ps(resolve)
    if target and target.lower().endswith(".exe") and os.path.exists(target):
        return target
    # Some shortcuts point at a launcher folder; return the .lnk itself as a
    # last resort (Popen can start a .lnk via the shell).
    return lnk if os.path.exists(lnk) else None


def _find_registry(name: str) -> str | None:
    """Windows 'App Paths' registry — where installers register launchable exes."""
    exe = _key(name)
    if not exe.endswith(".exe"):
        exe += ".exe"
    q = (f"$p='HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{exe}';"
         "if(Test-Path $p){(Get-ItemProperty $p).'(default)'}")
    val = _ps(q)
    if val and os.path.exists(val.strip('"')):
        return val.strip('"')
    return None


def _find_common_dirs(name: str) -> str | None:
    exe = _key(name)
    if not exe.endswith(".exe"):
        exe += ".exe"
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.environ.get("LOCALAPPDATA", ""),
             os.environ.get("APPDATA", "")]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        # shallow walk (2 levels) to stay fast
        try:
            for entry in os.scandir(root):
                if not entry.is_dir():
                    continue
                cand = os.path.join(entry.path, exe)
                if os.path.exists(cand):
                    return cand
        except Exception:
            continue
    return None


def resolve(name: str) -> str | None:
    """
    Return a launchable path for an app name, using cache first, then discovery.
    Caches any hit. Returns None if nothing found (caller uses Start-Menu search).
    """
    cached = get_cached(name)
    if cached:
        return cached
    if shutil.which(name):          # already on PATH
        p = shutil.which(name)
        remember(name, p, "path")
        return p
    if os.name != "nt":
        return None
    for finder, src in ((_find_registry, "registry"),
                        (_find_start_menu, "startmenu"),
                        (_find_common_dirs, "common")):
        try:
            hit = finder(name)
        except Exception:
            hit = None
        if hit:
            remember(name, hit, src)
            return hit
    return None


def list_known() -> list[dict]:
    try:
        init_app_paths()
        with conn() as db:
            rows = db.execute("SELECT name, path, source, verified_at FROM app_paths "
                              "ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
