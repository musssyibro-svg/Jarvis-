"""
routes/brain.py — API for the Jarvis Brain (personal knowledge base).

POST /brain/ingest          {title, text}         — save pasted text / a note
POST /brain/upload          multipart file        — .txt / .md (PDF if pypdf installed)
GET  /brain/search?q=&k=                          — retrieve relevant chunks
GET  /brain/documents                             — list everything stored
DELETE /brain/document/{id}                       — forget a document
GET  /brain/status                                — counts + embedding mode
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from services import brain_service as brain

router = APIRouter()


class IngestIn(BaseModel):
    title: str = ""
    text: str
    project: str = ""
    source: str = "note"      # note | fact | decision


@router.post("/ingest")
def ingest(body: IngestIn):
    source = body.source if body.source in ("note", "fact", "decision") else "note"
    r = brain.ingest(body.title, body.text, source=source,
                     project=body.project or None)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "ingest failed"))
    return r


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    raw = await file.read()
    name = file.filename or "upload"
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large (10MB max)")
    lower = name.lower()
    if lower.endswith(".pdf"):
        try:
            import io

            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text = "\n\n".join((p.extract_text() or "") for p in reader.pages)
        except ImportError:
            raise HTTPException(
                415, "PDF support needs pypdf — run: pip install pypdf "
                     "(or paste the text instead)")
        except Exception as e:
            raise HTTPException(422, f"Could not read PDF: {e}")
    else:
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception as e:
            raise HTTPException(422, f"Could not decode file: {e}")
    r = brain.ingest(name, text, source="file")
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "ingest failed"))
    return r


@router.get("/search")
def search(q: str, k: int = 4, project: str = ""):
    return brain.search(q, k=min(max(k, 1), 20), project=project or None)


@router.get("/documents")
def documents(project: str = ""):
    return {"documents": brain.list_documents(project=project or None)}


@router.get("/projects")
def list_projects():
    return {"projects": brain.projects()}


@router.delete("/document/{doc_id}")
def delete(doc_id: int):
    r = brain.delete_document(doc_id)
    if not r.get("ok"):
        raise HTTPException(404, f"No document with id {doc_id}")
    return r


@router.get("/status")
def status():
    return brain.status()
