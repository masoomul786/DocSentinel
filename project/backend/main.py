"""
DocSentinel — Self-Healing Multimodal Document Intelligence
FastAPI Backend
"""

import os
import uuid
import json
import time
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ingestion import DocumentIngestionPipeline
from vector_store import ActianVectorStore
from agent import DocSentinelAgent

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("docsentinel")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="DocSentinel API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Globals ───────────────────────────────────────────────────────────────────
vector_store = ActianVectorStore()
agent = DocSentinelAgent(vector_store)
active_connections: List[WebSocket] = []

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Runtime config (overrides env defaults)
_runtime_config: Dict[str, str] = {
    "lm_model_name": os.getenv("LM_MODEL_NAME", ""),  # empty = auto-detect
    "lm_studio_url": os.getenv("LM_STUDIO_URL", "http://localhost:1234"),
}


# ── WebSocket Manager ─────────────────────────────────────────────────────────
async def broadcast(message: dict):
    for ws in list(active_connections):
        try:
            await ws.send_json(message)
        except Exception:
            active_connections.remove(ws)


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)


# ── Models ────────────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question: str
    document_id: Optional[str] = None
    image_base64: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[Dict]
    retries: int
    confidence: float
    persona: str
    query_id: str
    reasoning_trace: List[str]


# ── Routes ────────────────────────────────────────────────────────────────────
@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and ingest a PDF document"""
    # Safely get just the filename (handles Windows paths like C:\...\file.pdf)
    safe_name = Path(file.filename).name if file.filename else "upload.pdf"

    if not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Read file content and validate it's actually a PDF (check magic bytes)
    content = await file.read()
    if len(content) < 5 or content[:5] != b"%PDF-":
        raise HTTPException(status_code=400, detail="File does not appear to be a valid PDF")

    doc_id = str(uuid.uuid4())[:8]
    # Sanitize filename for filesystem safety
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in "._- ").strip()
    if not safe_name:
        safe_name = f"document_{doc_id}.pdf"
    file_path = UPLOAD_DIR / f"{doc_id}_{safe_name}"

    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        log.error(f"Failed to save file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    log.info(f"Uploaded {safe_name} ({len(content)} bytes) → doc_id={doc_id}")

    # Run ingestion pipeline in background
    async def run_ingestion():
        try:
            pipeline = DocumentIngestionPipeline(broadcast_fn=broadcast)
            result = await pipeline.process(str(file_path), doc_id, safe_name)
            return result
        except Exception as e:
            log.error(f"Ingestion failed for {doc_id}: {e}")
            await broadcast({
                "type": "log",
                "level": "error",
                "message": f"[ERROR] Ingestion failed: {str(e)}",
                "phase": "INGEST",
                "timestamp": datetime.utcnow().isoformat(),
            })

    asyncio.create_task(run_ingestion())

    return {"doc_id": doc_id, "filename": safe_name, "status": "processing", "size_bytes": len(content)}


@app.post("/api/query", response_model=QueryResponse)
async def query_document(req: QueryRequest):
    """Run agentic query against ingested documents"""
    result = await agent.run(
        question=req.question,
        document_id=req.document_id,
        image_base64=req.image_base64,
        broadcast_fn=broadcast,
    )
    return result


@app.get("/api/documents")
async def list_documents():
    """List all ingested documents"""
    docs = vector_store.list_documents()
    return {"documents": docs}


@app.get("/api/audit")
async def get_audit_log(limit: int = 20):
    """Retrieve audit log from Actian VectorAI DB"""
    logs = vector_store.get_audit_log(limit=limit)
    return {"logs": logs}


@app.get("/api/audit/search")
async def search_audit(q: str):
    """Semantic search over audit history"""
    results = vector_store.search_audit(q)
    return {"results": results}


@app.get("/api/health")
async def health():
    # LM Studio check is non-blocking — health endpoint must return fast
    # so the frontend connection indicator doesn't time out while LM Studio
    # is unreachable (which is the normal startup state)
    lm_status = _lm_studio_status  # cached, updated in background
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "vector_store": vector_store.health_check(),
        "lm_studio": lm_status,
    }


@app.get("/api/config")
async def get_config():
    """Get runtime configuration"""
    detected = await _detect_model_name()
    return {
        "lm_model_name": _runtime_config["lm_model_name"],
        "lm_studio_url": _runtime_config["lm_studio_url"],
        "detected_model": detected,
    }


@app.post("/api/config")
async def set_config(body: Dict[str, Any] = Body(...)):
    """Update runtime configuration (model name, LM Studio URL)"""
    if "lm_model_name" in body:
        _runtime_config["lm_model_name"] = str(body["lm_model_name"]).strip()
        agent.override_model_name = _runtime_config["lm_model_name"] or None
    if "lm_studio_url" in body:
        _runtime_config["lm_studio_url"] = str(body["lm_studio_url"]).strip()
        agent.lm_studio_url = _runtime_config["lm_studio_url"]
    return {"status": "ok", "config": _runtime_config}


@app.get("/api/documents/{doc_id}/persona")
async def get_document_persona(doc_id: str):
    """Get the persona for a specific document"""
    docs = vector_store.list_documents()
    for doc in docs:
        if doc["doc_id"] == doc_id:
            return {
                "doc_id": doc_id,
                "domain": doc.get("domain", "General"),
                "safety_level": doc.get("safety_level", "low"),
                "generated_system_prompt": doc.get("persona", ""),
                "key_topics": [],
            }
    raise HTTPException(status_code=404, detail="Document not found")


async def _detect_model_name() -> str:
    try:
        url = _runtime_config.get("lm_studio_url", "http://localhost:1234")
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{url}/v1/models")
            if r.status_code == 200:
                models = r.json().get("data", [])
                if models:
                    return models[0]["id"]
    except Exception:
        pass
    return ""


# Cached LM Studio status — updated in background to keep /api/health fast
_lm_studio_status: str = "checking"

async def check_lm_studio():
    """Background task: probe LM Studio and update cached status."""
    global _lm_studio_status
    try:
        url = _runtime_config.get("lm_studio_url", "http://localhost:1234")
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"{url}/v1/models")
            _lm_studio_status = "ok" if r.status_code == 200 else "unavailable"
    except Exception:
        _lm_studio_status = "unavailable"
    return _lm_studio_status


@app.on_event("startup")
async def startup_tasks():
    """Run background LM Studio probe on startup and every 30s."""
    async def _poll_lm():
        while True:
            await check_lm_studio()
            await asyncio.sleep(30)
    asyncio.create_task(_poll_lm())


@app.delete("/api/reset")
async def reset_all():
    """Delete all vectors, documents, and uploaded files — full reset"""
    result = vector_store.reset_all()
    log.info("Full reset performed")
    await broadcast({"type": "reset", "message": "All data cleared"})
    return result


def _find_frontend() -> Path:
    """Find frontend dir in any layout: local, Docker, or env override."""
    candidates = []
    root_env = os.getenv("DOCSENTINEL_ROOT")
    if root_env:
        candidates.append(Path(root_env) / "frontend")
    candidates += [
        Path(__file__).parent / "frontend",        # Docker: /app/frontend
        Path(__file__).parent.parent / "frontend", # Local:  ../frontend
    ]
    for p in candidates:
        if (p / "index.html").exists():
            return p
    return candidates[-1]  # fallback — will 404 gracefully

_frontend_dir = _find_frontend()
if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")

@app.get("/")
async def root():
    """Serve the frontend UI"""
    index = _frontend_dir / "index.html"
    if index.exists():
        return FileResponse(str(index), media_type="text/html")
    return HTMLResponse(
        "<h1>DocSentinel API is running</h1>"
        "<p>Frontend not found. If using Docker, check the volume mount in docker-compose.yml.<br>"
        "If running locally, ensure <code>frontend/index.html</code> exists next to the <code>backend/</code> folder.</p>"
        "<p><a href='/docs'>API Docs →</a></p>"
    )
