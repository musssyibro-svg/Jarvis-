"""
services/brain_service.py — Jarvis Brain: local personal knowledge base (RAG).

Feed it anything — notes, pasted text, .txt/.md files, project docs — and it
becomes retrievable context for chat. Design constraints (deliberate):

  - 100% local and free. No cloud APIs, nothing leaves the machine.
  - Zero REQUIRED downloads: retrieval falls back to BM25 keyword search
    (pure Python, stdlib only) when no embedding model is installed, so the
    brain works on day one on a fresh machine, offline, behind any firewall.
  - Optional upgrade: `ollama pull nomic-embed-text` (~274MB, CPU-friendly,
    fine on 16GB RAM) enables semantic search. Chunks embedded lazily; text
    ingested while Ollama was down is backfilled the next time it's up.
  - SQLite storage in the existing jarvis.db — no new database, no server.

Embedding vectors are stored as float32 blobs via array('f') — stdlib only,
no numpy required at ingest/search time.
"""
import json
import logging
import math
import os
import re
from array import array
from datetime import datetime, timezone

from models.db import conn

logger = logging.getLogger("jarvis.brain")

OLLAMA_URL  = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

CHUNK_CHARS   = 1200   # target chunk size
CHUNK_OVERLAP = 150    # carried into the next chunk for continuity


# ── Schema ────────────────────────────────────────────────────────────────────

BRAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS brain_documents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    source     TEXT DEFAULT 'note',        -- note | file | chat
    chars      INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS brain_chunks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id    INTEGER NOT NULL REFERENCES brain_documents(id) ON DELETE CASCADE,
    seq       INTEGER NOT NULL,
    text      TEXT NOT NULL,
    embedding BLOB                          -- float32 array; NULL until embedded
);
CREATE INDEX IF NOT EXISTS idx_brain_chunks_doc ON brain_chunks(doc_id);
"""


def init_brain() -> None:
    with conn() as db:
        db.executescript(BRAIN_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Embeddings (optional, lazily probed) ──────────────────────────────────────

_embed_available: bool | None = None  # None = unprobed


def embeddings_available(force: bool = False) -> bool:
    """Cached probe: is Ollama up AND is the embed model pulled?"""
    global _embed_available
    if _embed_available is not None and not force:
        return _embed_available
    ok = False
    try:
        import requests
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        models = [m.get("name", "") for m in r.json().get("models", [])]
        ok = any(m == EMBED_MODEL or m.startswith(EMBED_MODEL + ":") for m in models)
    except Exception:
        ok = False
    _embed_available = ok
    return ok


def _embed(texts: list[str]) -> list[list[float]] | None:
    """Embed a batch of texts via Ollama. Returns None on any failure."""
    try:
        import requests
        r = requests.post(f"{OLLAMA_URL}/api/embed",
                          json={"model": EMBED_MODEL, "input": texts}, timeout=60)
        r.raise_for_status()
        embs = r.json().get("embeddings")
        return embs if embs and len(embs) == len(texts) else None
    except Exception as e:
        logger.warning(f"embedding call failed: {e}")
        global _embed_available
        _embed_available = None   # re-probe next time; Ollama may have gone down
        return None


def _pack(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def _unpack(blob: bytes) -> array:
    a = array("f")
    a.frombytes(blob)
    return a


def _cosine(a, b) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / math.sqrt(na * nb)


# ── Chunking ──────────────────────────────────────────────────────────────────

def _chunk_text(text: str) -> list[str]:
    """Split on paragraph boundaries into ~CHUNK_CHARS pieces with overlap."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_CHARS:
        return [text]
    paragraphs = re.split(r"\n\s*\n", text)
    chunks, current = [], ""
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        # single paragraph bigger than a chunk: hard-split it
        while len(p) > CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(p[:CHUNK_CHARS])
            p = p[CHUNK_CHARS - CHUNK_OVERLAP:]
        if len(current) + len(p) + 2 > CHUNK_CHARS and current:
            chunks.append(current)
            current = current[-CHUNK_OVERLAP:] + "\n\n" + p if CHUNK_OVERLAP else p
        else:
            current = (current + "\n\n" + p) if current else p
    if current.strip():
        chunks.append(current.strip())
    return chunks


# ── BM25 keyword fallback (stdlib only — always works) ────────────────────────

_WORD_RE = re.compile(r"[a-z0-9一-鿿]+")


def _tokens(text: str) -> list[str]:
    """Lowercase word tokens; CJK characters are kept (split per char for zh)."""
    out = []
    for tok in _WORD_RE.findall(text.lower()):
        # split runs of CJK into single characters so Chinese text is searchable
        if re.search(r"[一-鿿]", tok):
            out.extend(list(tok))
        else:
            out.append(tok)
    return out


def _bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    q_terms = _tokens(query)
    if not q_terms or not docs:
        return [0.0] * len(docs)
    doc_tokens = [_tokens(d) for d in docs]
    N = len(docs)
    avgdl = sum(len(t) for t in doc_tokens) / max(N, 1) or 1.0
    df = {}
    for toks in doc_tokens:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    scores = []
    for toks in doc_tokens:
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for q in q_terms:
            if q not in tf:
                continue
            idf = math.log(1 + (N - df.get(q, 0) + 0.5) / (df.get(q, 0) + 0.5))
            s += idf * (tf[q] * (k1 + 1)) / (tf[q] + k1 * (1 - b + b * len(toks) / avgdl))
        scores.append(s)
    return scores


# ── Public API ────────────────────────────────────────────────────────────────

def ingest(title: str, text: str, source: str = "note") -> dict:
    """Store a document: chunk it, embed what we can, persist everything."""
    init_brain()
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    chunks = _chunk_text(text)
    embs = _embed(chunks) if embeddings_available() else None
    with conn() as db:
        cur = db.execute(
            "INSERT INTO brain_documents(title, source, chars, created_at) VALUES(?,?,?,?)",
            (title.strip() or f"Untitled {_now()[:10]}", source, len(text), _now()))
        doc_id = cur.lastrowid
        for i, chunk in enumerate(chunks):
            db.execute(
                "INSERT INTO brain_chunks(doc_id, seq, text, embedding) VALUES(?,?,?,?)",
                (doc_id, i, chunk, _pack(embs[i]) if embs else None))
    logger.info(f"brain: ingested '{title}' ({len(chunks)} chunks, "
                f"{'embedded' if embs else 'keyword-only'})")
    return {"ok": True, "doc_id": doc_id, "chunks": len(chunks),
            "embedded": bool(embs)}


def _backfill_embeddings(limit: int = 64) -> int:
    """Embed chunks stored while Ollama/the model was unavailable."""
    if not embeddings_available():
        return 0
    with conn() as db:
        rows = db.execute(
            "SELECT id, text FROM brain_chunks WHERE embedding IS NULL LIMIT ?",
            (limit,)).fetchall()
    if not rows:
        return 0
    embs = _embed([r["text"] for r in rows])
    if not embs:
        return 0
    with conn() as db:
        for r, e in zip(rows, embs):
            db.execute("UPDATE brain_chunks SET embedding=? WHERE id=?",
                       (_pack(e), r["id"]))
    logger.info(f"brain: backfilled embeddings for {len(rows)} chunks")
    return len(rows)


def search(query: str, k: int = 4) -> dict:
    """
    Hybrid retrieval. Vector search over embedded chunks when the model is up;
    BM25 keyword scoring over everything (and as the sole path when it isn't).
    Returns {ok, mode, results: [{doc_id, title, text, score}]}.
    """
    init_brain()
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "empty query", "results": []}
    _backfill_embeddings()
    with conn() as db:
        rows = db.execute(
            "SELECT c.id, c.doc_id, c.text, c.embedding, d.title "
            "FROM brain_chunks c JOIN brain_documents d ON d.id = c.doc_id").fetchall()
    if not rows:
        return {"ok": True, "mode": "empty", "results": []}

    mode = "keyword"
    scored: dict[int, float] = {}

    if embeddings_available():
        q_emb = _embed([query])
        if q_emb:
            qv = q_emb[0]
            for r in rows:
                if r["embedding"] is not None:
                    scored[r["id"]] = _cosine(qv, _unpack(r["embedding"]))
            if scored:
                mode = "vector"

    # BM25 over all chunks — sole scorer in keyword mode, and fills in any
    # never-embedded chunks in vector mode (scaled to stay comparable).
    bm25 = _bm25_scores(query, [r["text"] for r in rows])
    max_bm25 = max(bm25) or 1.0
    for r, s in zip(rows, bm25):
        if r["id"] not in scored:
            scored[r["id"]] = (s / max_bm25) * (0.5 if mode == "vector" else 1.0)

    by_id = {r["id"]: r for r in rows}
    top = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)[:k]
    results = [{"doc_id": by_id[cid]["doc_id"], "title": by_id[cid]["title"],
                "text": by_id[cid]["text"], "score": round(s, 4)}
               for cid, s in top if s > 0]
    return {"ok": True, "mode": mode, "results": results}


def context_for(query: str, k: int = 3, max_chars: int = 2400) -> str:
    """Formatted knowledge block for prompt injection. Empty string if no hits."""
    hits = search(query, k=k).get("results", [])
    if not hits:
        return ""
    parts, used = [], 0
    for h in hits:
        t = h["text"][: max_chars - used]
        parts.append(f"[{h['title']}]\n{t}")
        used += len(t)
        if used >= max_chars:
            break
    return "\n\n".join(parts)


def list_documents() -> list[dict]:
    init_brain()
    with conn() as db:
        rows = db.execute(
            "SELECT d.id, d.title, d.source, d.chars, d.created_at, "
            "COUNT(c.id) AS chunks, SUM(c.embedding IS NOT NULL) AS embedded "
            "FROM brain_documents d LEFT JOIN brain_chunks c ON c.doc_id = d.id "
            "GROUP BY d.id ORDER BY d.id DESC").fetchall()
    return [dict(r) for r in rows]


def delete_document(doc_id: int) -> dict:
    init_brain()
    with conn() as db:
        cur = db.execute("DELETE FROM brain_documents WHERE id=?", (doc_id,))
        db.execute("DELETE FROM brain_chunks WHERE doc_id=?", (doc_id,))
    return {"ok": cur.rowcount > 0, "deleted": doc_id}


def status() -> dict:
    init_brain()
    with conn() as db:
        docs = db.execute("SELECT COUNT(*) AS n FROM brain_documents").fetchone()["n"]
        chunks = db.execute("SELECT COUNT(*) AS n FROM brain_chunks").fetchone()["n"]
        embedded = db.execute(
            "SELECT COUNT(*) AS n FROM brain_chunks WHERE embedding IS NOT NULL").fetchone()["n"]
    return {
        "documents": docs, "chunks": chunks, "embedded_chunks": embedded,
        "embed_model": EMBED_MODEL,
        "embeddings_available": embeddings_available(force=True),
        "mode": "vector" if embeddings_available() else "keyword",
        "hint": (None if embeddings_available() else
                 f"Semantic search off — run: ollama pull {EMBED_MODEL} "
                 f"(~274MB, one time). Keyword search works meanwhile."),
    }
