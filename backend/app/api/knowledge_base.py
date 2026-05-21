# backend/app/api/knowledge_base.py
import os
import json
import asyncio
import uuid
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..knowledge_base.kb_service import (
    process_pdf_upload,
    update_engine_approval,
    get_all_documents,
    get_document_scores,
    search_chunks_for_engine,
    ensure_tables_exist
)

router = APIRouter(prefix="/api/kb", tags=["knowledge_base"])
MAX_FILE_SIZE = 50 * 1024 * 1024

# ── JOB TRACKER ──────────────────────────────────────────────
_jobs = {}

def _new_job(jid):
    _jobs[jid] = {"status":"processing","progress":"Memulai...","step":0,"result":None,"error":None}

def _update_job(jid, step, progress):
    if jid in _jobs:
        _jobs[jid]["step"] = step
        _jobs[jid]["progress"] = progress

def _finish_job(jid, result):
    if jid in _jobs:
        _jobs[jid].update({"status":"done","progress":"Selesai!","step":6,"result":result})

def _fail_job(jid, error):
    if jid in _jobs:
        _jobs[jid].update({"status":"error","error":error})

# ── BACKGROUND TASK ──────────────────────────────────────────
async def _process_background(jid, pdf_bytes, filename, description):
    try:
        _update_job(jid, 1, "Mengekstrak teks dari PDF...")
        await asyncio.sleep(0.2)
        _update_job(jid, 2, "Membuat chunks teks...")
        await asyncio.sleep(0.2)
        _update_job(jid, 3, "Claude menganalisis engines 1-10...")
        result = await process_pdf_upload(pdf_bytes=pdf_bytes, original_filename=filename, description=description)
        _finish_job(jid, result)
    except Exception as e:
        _fail_job(jid, str(e))

# ── MODELS ───────────────────────────────────────────────────
class EngineApprovalUpdate(BaseModel):
    is_approved: bool

class BulkApprovalRequest(BaseModel):
    threshold: Optional[float] = 0.60

# ── ENDPOINTS ────────────────────────────────────────────────
@router.get("/health")
async def kb_health():
    try:
        await ensure_tables_exist()
        return {"status":"ok","message":"Knowledge Base ready"}
    except Exception as e:
        return {"status":"error","message":str(e)}

@router.post("/upload")
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...), description: Optional[str] = Form(None)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Hanya file PDF yang diizinkan")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File terlalu besar. Maksimal 50MB")
    if len(pdf_bytes) < 100:
        raise HTTPException(status_code=400, detail="File PDF terlalu kecil atau rusak")
    jid = str(uuid.uuid4())[:8]
    _new_job(jid)
    background_tasks.add_task(_process_background, jid, pdf_bytes, file.filename, description or "")
    return {"success":True,"job_id":jid,"status":"processing","filename":file.filename,"message":f"Upload diterima! Polling /api/kb/jobs/{jid}"}

@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    job = _jobs[job_id]
    return {"job_id":job_id,"status":job["status"],"progress":job["progress"],"step":job["step"],"total_steps":6,"result":job.get("result"),"error":job.get("error")}

@router.get("/documents")
async def list_documents():
    try:
        docs = await get_all_documents()
        for d in docs:
            if d.get("created_at"): d["created_at"] = str(d["created_at"])
        return {"success":True,"documents":docs,"count":len(docs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/documents/{document_id}")
async def get_document(document_id: int):
    try:
        result = await get_document_scores(document_id)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("message","Not found"))
        if result.get("document",{}).get("created_at"):
            result["document"]["created_at"] = str(result["document"]["created_at"])
        return result
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@router.put("/documents/{document_id}/engines/{engine_name}")
async def toggle_engine_approval(document_id: int, engine_name: str, body: EngineApprovalUpdate):
    try:
        result = await update_engine_approval(document_id=document_id, engine_name=engine_name, is_approved=body.is_approved)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("message"))
        return result
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@router.post("/documents/{document_id}/apply-threshold")
async def apply_threshold(document_id: int, body: BulkApprovalRequest):
    from ..knowledge_base.kb_service import get_db_conn
    conn = await get_db_conn()
    try:
        t = body.threshold or 0.60
        await conn.execute("UPDATE kb_engine_scores SET is_approved=(relevance_score>=$1) WHERE document_id=$2 AND user_override=FALSE", t, document_id)
        scores = await conn.fetch("SELECT is_approved FROM kb_engine_scores WHERE document_id=$1", document_id)
        return {"success":True,"document_id":document_id,"threshold_applied":t,"approved_count":sum(1 for s in scores if s["is_approved"]),"total_engines":len(scores)}
    finally: await conn.close()

@router.delete("/documents/{document_id}")
async def delete_document(document_id: int):
    from ..knowledge_base.kb_service import get_db_conn
    conn = await get_db_conn()
    try:
        result = await conn.fetchrow("DELETE FROM kb_documents WHERE id=$1 RETURNING id,original_name", document_id)
        if not result: raise HTTPException(status_code=404, detail="Document not found")
        return {"success":True,"deleted_id":document_id,"filename":result["original_name"]}
    finally: await conn.close()

@router.get("/search")
async def search_knowledge_base(engine_name: str, query: str = "", limit: int = 5):
    try:
        chunks = await search_chunks_for_engine(engine_name, query, limit)
        return {"success":True,"engine_name":engine_name,"query":query,"results_count":len(chunks),"chunks":chunks}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats")
async def get_kb_stats():
    from ..knowledge_base.kb_service import get_db_conn
    conn = await get_db_conn()
    try:
        stats = await conn.fetchrow("""
            SELECT COUNT(DISTINCT d.id) as total_documents, SUM(d.total_chunks) as total_chunks,
                   SUM(d.page_count) as total_pages,
                   COUNT(DISTINCT CASE WHEN es.is_approved THEN es.engine_name END) as engines_with_kb
            FROM kb_documents d LEFT JOIN kb_engine_scores es ON es.document_id=d.id
            WHERE d.status NOT IN ('error','rejected')
        """)
        top = await conn.fetch("""
            SELECT engine_name, COUNT(*) as approved_books, AVG(relevance_score) as avg_score
            FROM kb_engine_scores WHERE is_approved=TRUE
            GROUP BY engine_name ORDER BY approved_books DESC, avg_score DESC LIMIT 10
        """)
        return {"success":True,"stats":dict(stats) if stats else {},"top_engines":[{"engine_name":r["engine_name"],"approved_books":r["approved_books"],"avg_score":round(float(r["avg_score"])*100,1)} for r in top]}
    finally: await conn.close()

@router.get("/chunks/{document_id}")
async def get_document_chunks(document_id: int, limit: int = 20):
    from ..knowledge_base.kb_service import get_db_conn
    conn = await get_db_conn()
    try:
        rows = await conn.fetch("""
            SELECT c.page_number, c.engine_tags, c.content
            FROM kb_chunks c
            WHERE c.document_id = $1
            ORDER BY c.page_number
            LIMIT $2
        """, document_id, limit)
        return {
            "success": True,
            "document_id": document_id,
            "chunks": [{"page": r["page_number"], "tags": r["engine_tags"], "content": r["content"][:500]} for r in rows]
        }
    finally:
        await conn.close()
