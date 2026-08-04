"""
services/vault.py — Encrypted local credential vault.

Stores freelance-platform logins ON THE USER'S PC ONLY, encrypted at rest with
Fernet (AES-128-CBC + HMAC). The key lives in backend/vault.key next to the
database — nothing ever leaves the machine, and credentials are never logged
or returned in plaintext by the API (only masked previews).

Used by the session manager to pre-fill login forms in the persistent browser
profile. If `cryptography` isn't installed the vault refuses to store secrets
rather than silently downgrading to plaintext.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

from models.db import conn

BASE_DIR = Path(__file__).resolve().parent.parent
KEY_FILE = BASE_DIR / "vault.key"

VAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_credentials (
    platform   TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    secret_enc TEXT NOT NULL,
    updated_at TEXT
);
"""

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except BaseException:
    # BaseException, not ImportError: a broken/partial cryptography install
    # (mismatched native wheel) raises pyo3 PanicException, which is NOT an
    # Exception subclass. Letting that escape would take down every module that
    # merely imports the vault. Degrade to "no vault" instead.
    Fernet = None
    HAS_CRYPTO = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_vault() -> None:
    with conn() as db:
        db.executescript(VAULT_SCHEMA)


def _key() -> bytes:
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass  # Windows: NTFS ACLs already restrict to the user profile
    return key


def vault_ready() -> dict:
    return {"crypto": HAS_CRYPTO, "key_file": str(KEY_FILE),
            "note": None if HAS_CRYPTO else
            "Install `pip install cryptography` to enable the credential vault."}


def store_credential(platform: str, username: str, password: str) -> dict:
    if not HAS_CRYPTO:
        return {"ok": False, "error": "cryptography not installed — refusing to "
                "store secrets unencrypted. Run: pip install cryptography"}
    platform = (platform or "").strip().lower()
    if not platform or not username or not password:
        return {"ok": False, "error": "platform, username and password required"}
    init_vault()
    token = Fernet(_key()).encrypt(password.encode("utf-8")).decode("ascii")
    with conn() as db:
        db.execute("INSERT OR REPLACE INTO vault_credentials"
                   "(platform,username,secret_enc,updated_at) VALUES(?,?,?,?)",
                   (platform, username, token, _now()))
    return {"ok": True, "platform": platform, "username": _mask(username)}


def get_credential(platform: str) -> dict | None:
    """Decrypted credential for INTERNAL use (login autofill). Never expose via API."""
    if not HAS_CRYPTO:
        return None
    init_vault()
    with conn() as db:
        row = db.execute("SELECT * FROM vault_credentials WHERE platform=?",
                         ((platform or "").strip().lower(),)).fetchone()
    if not row:
        return None
    try:
        secret = Fernet(_key()).decrypt(row["secret_enc"].encode("ascii")).decode("utf-8")
        return {"platform": row["platform"], "username": row["username"],
                "password": secret}
    except Exception:
        return None


def list_credentials() -> list[dict]:
    """Masked listing — safe for the UI."""
    init_vault()
    with conn() as db:
        rows = db.execute("SELECT platform, username, updated_at "
                          "FROM vault_credentials ORDER BY platform").fetchall()
    return [{"platform": r["platform"], "username": _mask(r["username"]),
             "updated_at": r["updated_at"]} for r in rows]


def delete_credential(platform: str) -> dict:
    init_vault()
    with conn() as db:
        cur = db.execute("DELETE FROM vault_credentials WHERE platform=?",
                         ((platform or "").strip().lower(),))
    return {"ok": cur.rowcount > 0}


def _mask(username: str) -> str:
    if "@" in username:
        head, _, domain = username.partition("@")
        return (head[:2] + "***@" + domain) if len(head) > 2 else "***@" + domain
    return username[:2] + "***" if len(username) > 2 else "***"
