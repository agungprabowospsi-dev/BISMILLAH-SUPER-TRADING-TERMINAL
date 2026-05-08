# backend/app/api/knowledge_base.py
"""
API Router untuk Knowledge Base.
Endpoints:
- POST /api/kb/upload          — Upload PDF
- GET  /api/kb/documents       — List semua dokumen
- GET  /api/kb/documents/{id}  — Detail + engine scores
- PUT  /api/kb/documents/{id}/engines/{engine_name} — Toggle approval
- DELETE /api/kb/documents/{id} — Hapus dokumen
- GET  /api/kb/search          — Search chunks (RAG test)
- POST /api/kb/approve-all/{id} — Approve all atau apply threshold
"""

import os
import json
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
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

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# ============================================================
# MODELS
# ============================================================

class EngineApprovalUpdate(BaseModel):
    is_approved: bool


class BulkApprovalRequest(BaseModel):
    threshold: Optional[float] = 0.60  # Apply threshold ke semua engines


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/health")
async def kb_health():
    """Check KB health dan pastikan tables ada."""
    try:
        await ensure_tables_exist()
        return {"status": "ok", "message": "Knowledge Base ready"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None)
):
    """
    Upload PDF dan proses:
    1. Extract text (PyMuPDF)
    2. Analyze relevance ke 34 engines (Claude)
    3. Auto-approve jika score >= 60%
    4. Return engine scores untuk user review
    """
    # Validasi file
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Hanya file PDF yang diizinkan")

    pdf_bytes = await file.read()

    if len(pdf_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File terlalu besar. Maksimal 50MB, file ini {len(pdf_bytes)//1024//1024}MB"
        )

    if len(pdf_bytes) < 100:
        raise HTTPException(status_code=400, detail="File PDF terlalu kecil atau rusak")

    try:
        result = await process_pdf_upload(
            pdf_bytes=pdf_bytes,
            original_filename=file.filename,
            description=description
        )
        return JSONResponse(content=result)

    except RuntimeError as e:
        if "PyMuPDF" in str(e):
            raise HTTPException(
                status_code=500,
                detail="PyMuPDF tidak terinstall di server. Hubungi admin."
            )
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")


@router.get("/documents")
async def list_documents():
    """List semua dokumen yang sudah diupload."""
    try:
        documents = await get_all_documents()
        # Serialize datetime fields
        for doc in documents:
            if "created_at" in doc and doc["created_at"]:
                doc["created_at"] = str(doc["created_at"])
        return {"success": True, "documents": documents, "count": len(documents)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{document_id}")
async def get_document(document_id: int):
    """Get detail dokumen + semua engine scores."""
    try:
        result = await get_document_scores(document_id)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("message", "Not found"))
        # Serialize datetime
        if "document" in result and result["document"].get("created_at"):
            result["document"]["created_at"] = str(result["document"]["created_at"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/documents/{document_id}/engines/{engine_name}")
async def toggle_engine_approval(
    document_id: int,
    engine_name: str,
    body: EngineApprovalUpdate
):
    """
    User manually toggle approve/unapprove engine untuk dokumen.
    Ini adalah 'edit manual' dari user.
    """
    try:
        result = await update_engine_approval(
            document_id=document_id,
            engine_name=engine_name,
            is_approved=body.is_approved
        )
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("message"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{document_id}/apply-threshold")
async def apply_threshold(document_id: int, body: BulkApprovalRequest):
    """
    Apply threshold ke semua engines untuk dokumen ini.
    Engines dengan score >= threshold akan di-approve.
    Engines yang sudah di-override user tidak akan diubah.
    """
    from ..knowledge_base.kb_service import get_db_conn
    conn = await get_db_conn()
    try:
        threshold = body.threshold or 0.60

        # Update semua yang belum di-override user
        await conn.execute("""
            UPDATE kb_engine_scores
            SET is_approved = (relevance_score >= $1)
            WHERE document_id = $2 AND user_override = FALSE
        """, threshold, document_id)

        # Ambil hasil terbaru
        scores = await conn.fetch("""
            SELECT engine_name, relevance_score, is_approved, user_override
            FROM kb_engine_scores
            WHERE document_id = $1
            ORDER BY engine_index
        """, document_id)

        approved_count = sum(1 for s in scores if s["is_approved"])

        return {
            "success": True,
            "document_id": document_id,
            "threshold_applied": threshold,
            "approved_count": approved_count,
            "total_engines": len(scores)
        }
    finally:
        await conn.close()


@router.delete("/documents/{document_id}")
async def delete_document(document_id: int):
    """Hapus dokumen + semua chunks + engine scores."""
    from ..knowledge_base.kb_service import get_db_conn
    conn = await get_db_conn()
    try:
        result = await conn.fetchrow(
            "DELETE FROM kb_documents WHERE id = $1 RETURNING id, original_name",
            document_id
        )
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "success": True,
            "deleted_id": document_id,
            "filename": result["original_name"]
        }
    finally:
        await conn.close()


@router.get("/search")
async def search_knowledge_base(engine_name: str, query: str = "", limit: int = 5):
    """
    Test RAG search: cari chunks relevan untuk engine tertentu.
    """
    try:
        chunks = await search_chunks_for_engine(engine_name, query, limit)
        return {
            "success": True,
            "engine_name": engine_name,
            "query": query,
            "results_count": len(chunks),
            "chunks": chunks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_kb_stats():
    """Statistik Knowledge Base."""
    from ..knowledge_base.kb_service import get_db_conn
    conn = await get_db_conn()
    try:
        stats = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT d.id) as total_documents,
                SUM(d.total_chunks) as total_chunks,
                SUM(d.page_count) as total_pages,
                COUNT(DISTINCT CASE WHEN es.is_approved THEN es.engine_name END) as engines_with_kb
            FROM kb_documents d
            LEFT JOIN kb_engine_scores es ON es.document_id = d.id
            WHERE d.status NOT IN ('error', 'rejected')
        """)

        # Top engines yang paling banyak di-approve
        top_engines = await conn.fetch("""
            SELECT engine_name,
                   COUNT(*) as approved_books,
                   AVG(relevance_score) as avg_score
            FROM kb_engine_scores
            WHERE is_approved = TRUE
            GROUP BY engine_name
            ORDER BY approved_books DESC, avg_score DESC
            LIMIT 10
        """)

        return {
            "success": True,
            "stats": dict(stats) if stats else {},
            "top_engines": [
                {
                    "engine_name": r["engine_name"],
                    "approved_books": r["approved_books"],
                    "avg_score": round(float(r["avg_score"]) * 100, 1)
                }
                for r in top_engines
            ]
        }
    finally:
        await conn.close()
