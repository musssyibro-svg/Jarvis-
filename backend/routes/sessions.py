"""
routes/sessions.py — Platform login sessions + credential vault API.

GET    /sessions/platforms                — supported platforms
GET    /sessions/status?refresh=1         — logged-in status per platform (cached)
POST   /sessions/open-login/{platform}    — open a visible login window (persistent profile)
GET    /sessions/vault                    — masked credential listing
POST   /sessions/vault                    — store {platform, username, password} (encrypted locally)
DELETE /sessions/vault/{platform}         — remove a credential
POST   /sessions/check-replies            — sweep the inbox for client replies

Secrets never leave this machine: the vault encrypts to backend/jarvis.db with
a local key file, the API only ever returns masked usernames, and login forms
are pre-filled locally in the user's own browser profile.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

router = APIRouter()


class CredentialIn(BaseModel):
    platform: str
    username: str
    password: str


@router.get("/platforms")
def platforms():
    from services.session_manager import list_platforms
    return {"platforms": list_platforms()}


@router.get("/status")
def status(refresh: bool = False):
    from services.session_manager import check_status
    return check_status(refresh=refresh)


@router.post("/open-login/{platform}")
def open_login(platform: str):
    from services.session_manager import open_login as do_open
    r = do_open(platform)
    if not r.get("ok") and "unknown platform" in (r.get("error") or ""):
        raise HTTPException(404, r["error"])
    return r


@router.get("/vault")
def vault_list():
    from services.vault import list_credentials, vault_ready
    return {"ready": vault_ready(), "credentials": list_credentials()}


@router.post("/vault")
def vault_store(body: CredentialIn):
    from services.vault import store_credential
    r = store_credential(body.platform, body.username, body.password)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "failed"))
    return r


@router.delete("/vault/{platform}")
def vault_delete(platform: str):
    from services.vault import delete_credential
    return delete_credential(platform)


@router.post("/check-replies")
def check_replies(background_tasks: BackgroundTasks):
    """Sync the Freelancer inbox in the background; results land in Messages."""
    from services.session_manager import check_replies as sweep
    background_tasks.add_task(sweep)
    return {"message": "Reply sweep started — new messages appear in the Messages tab."}
