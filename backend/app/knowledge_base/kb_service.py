# backend/app/knowledge_base/kb_service.py
"""
Service utama Knowledge Base:
1. Extract text dari PDF (PyMuPDF)
2. Chunk text
3. Claude analyze relevance ke 34 engines
4. Score dan simpan ke DB
"""

import os
import json
import asyncio
import re
from typing import List, Dict, Any, Optional
import asyncpg
from anthropic import AsyncAnthropic

from .kb_models import ALL_34_ENGINES, ENGINE_NAMES, CREATE_TABLES_SQL

# ============================================================
# INIT
# ============================================================

anthropic_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

CHUNK_SIZE = 1500      # karakter per chunk
CHUNK_OVERLAP = 200    # overlap antar chunk
AUTO_APPROVE_THRESHOLD = 0.60  # 60%


# ============================================================
# DATABASE HELPERS
# ============================================================

async def get_db_conn():
    """Ambil koneksi DB dari DATABASE_URL."""
    db_url = os.environ.get("DATABASE_URL", "")
    # asyncpg pakai format postgresql:// (ganti postgres:// jika perlu)
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return await asyncpg.connect(db_url)


async def ensure_tables_exist():
    """Buat tabel KB kalau belum ada."""
    conn = await get_db_conn()
    try:
        await conn.execute(CREATE_TABLES_SQL)
    finally:
        await conn.close()


# ============================================================
# PDF EXTRACTION (PyMuPDF)
# ============================================================

def extract_text_from_pdf(pdf_bytes: bytes) -> Dict[str, Any]:
    """
    Extract text dari PDF bytes menggunakan PyMuPDF (fitz).
    Return: {pages: [{page_num, text}], total_pages, full_text}
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError("PyMuPDF tidak terinstall. Jalankan: pip install pymupdf")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    full_text_parts = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        text = text.strip()
        if text:
            pages.append({
                "page_num": page_num + 1,
                "text": text
            })
            full_text_parts.append(f"[Page {page_num + 1}]\n{text}")

    doc.close()

    return {
        "pages": pages,
        "total_pages": len(doc),
        "full_text": "\n\n".join(full_text_parts)
    }


# ============================================================
# CHUNKING
# ============================================================

def chunk_text(pages: List[Dict], chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[Dict]:
    """
    Split text per halaman menjadi chunks.
    Return list of {chunk_index, page_number, content}
    """
    chunks = []
    chunk_index = 0

    for page_data in pages:
        text = page_data["text"]
        page_num = page_data["page_num"]

        # Split per paragraph dulu
        paragraphs = re.split(r'\n{2,}', text)
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 1 <= chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                # Simpan chunk saat ini
                if current_chunk:
                    chunks.append({
                        "chunk_index": chunk_index,
                        "page_number": page_num,
                        "content": current_chunk.strip(),
                        "content_length": len(current_chunk)
                    })
                    chunk_index += 1
                # Mulai chunk baru dengan overlap
                overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                current_chunk = overlap_text + "\n\n" + para

        # Sisa chunk
        if current_chunk.strip():
            chunks.append({
                "chunk_index": chunk_index,
                "page_number": page_num,
                "content": current_chunk.strip(),
                "content_length": len(current_chunk)
            })
            chunk_index += 1

    return chunks


# ============================================================
# CLAUDE ANALYZE — RELEVANCE KE 34 ENGINES
# ============================================================

async def analyze_relevance_with_claude(
    book_title: str,
    sample_text: str,  # 3000 karakter pertama sebagai sampel
    engine_batch: List[Dict]  # batch 10 engines per request
) -> List[Dict]:
    """
    Minta Claude score relevance PDF ke batch engines.
    Return list {engine_name, score, reasoning}
    """
    engine_list_str = "\n".join([
        f"{e['index']}. {e['name']} (Category: {e['category']})"
        for e in engine_batch
    ])

    prompt = f"""Kamu adalah expert sistem trading saham IDX Indonesia.

Aku punya sebuah buku/dokumen trading dengan judul: "{book_title}"

Berikut sample teks dari buku tersebut (3000 karakter pertama):
---
{sample_text[:3000]}
---

Aku memiliki {len(engine_batch)} trading analysis engines berikut:
{engine_list_str}

Tugas kamu: Untuk setiap engine di atas, berikan skor relevansi (0.0 - 1.0) yang menunjukkan seberapa relevan isi buku ini terhadap engine tersebut.

Kriteria scoring:
- 0.8-1.0: Buku sangat relevan, banyak konten yang bisa dipakai engine ini
- 0.6-0.79: Cukup relevan, ada konten yang berguna
- 0.4-0.59: Sedikit relevan, ada beberapa konsep yang berkaitan
- 0.2-0.39: Kurang relevan, hanya konsep umum yang berkaitan
- 0.0-0.19: Tidak relevan

PENTING: Jawab HANYA dalam format JSON array berikut, tanpa teks lain:
[
  {{"engine_name": "NamaEngine", "score": 0.85, "reasoning": "Alasan singkat dalam 1-2 kalimat"}},
  ...
]"""

    response = await anthropic_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = response.content[0].text.strip()

    # Parse JSON
    try:
        # Cari JSON array dalam response
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return result
        else:
            raise ValueError("No JSON array found in response")
    except Exception as e:
        print(f"Error parsing Claude response: {e}")
        print(f"Raw response: {response_text[:500]}")
        # Return default scores jika parsing gagal
        return [
            {"engine_name": e["name"], "score": 0.0, "reasoning": "Failed to parse Claude response"}
            for e in engine_batch
        ]


async def analyze_all_engines(book_title: str, sample_text: str) -> List[Dict]:
    """
    Analyze relevance ke semua 34 engines.
    Batch per 10 untuk efisiensi token.
    """
    all_results = []
    batch_size = 10

    for i in range(0, len(ALL_34_ENGINES), batch_size):
        batch = ALL_34_ENGINES[i:i + batch_size]
        print(f"  Analyzing engines {i+1}-{min(i+batch_size, 34)}...")

        batch_results = await analyze_relevance_with_claude(book_title, sample_text, batch)
        all_results.extend(batch_results)

        # Small delay antar batch
        await asyncio.sleep(0.5)

    return all_results


# ============================================================
# MAIN PROCESSING PIPELINE
# ============================================================

async def process_pdf_upload(
    pdf_bytes: bytes,
    original_filename: str,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Full pipeline: Upload → Extract → Analyze → Score → Simpan DB.
    Return document_id dan engine_scores untuk ditampilkan ke user.
    """
    await ensure_tables_exist()
    conn = await get_db_conn()

    try:
        print(f"[KB] Processing: {original_filename}")

        # Step 1: Extract text
        print("[KB] Step 1: Extracting text from PDF...")
        extracted = extract_text_from_pdf(pdf_bytes)
        full_text = extracted["full_text"]
        pages = extracted["pages"]
        total_pages = extracted["total_pages"]
        print(f"[KB] Extracted {total_pages} pages, {len(full_text)} chars")

        # Step 2: Simpan dokumen ke DB
        book_title = original_filename.replace(".pdf", "").replace("_", " ").replace("-", " ")
        doc_id = await conn.fetchval("""
            INSERT INTO kb_documents (filename, original_name, file_size, page_count, status, description)
            VALUES ($1, $2, $3, $4, 'analyzing', $5)
            RETURNING id
        """, original_filename, original_filename, len(pdf_bytes), total_pages, description or "")
        print(f"[KB] Document saved with ID: {doc_id}")

        # Step 3: Chunk text
        print("[KB] Step 3: Chunking text...")
        chunks = chunk_text(pages)
        print(f"[KB] Created {len(chunks)} chunks")

        # Step 4: Analyze dengan Claude (gunakan 5000 karakter pertama sebagai sampel)
        print("[KB] Step 4: Analyzing relevance with Claude...")
        sample_text = full_text[:5000]
        engine_scores_raw = await analyze_all_engines(book_title, sample_text)

        # Step 5: Simpan engine scores ke DB
        print("[KB] Step 5: Saving engine scores...")
        engine_scores_saved = []

        for engine_info in ALL_34_ENGINES:
            # Cari score dari Claude result
            claude_result = next(
                (r for r in engine_scores_raw if r.get("engine_name") == engine_info["name"]),
                None
            )

            if claude_result:
                score = float(claude_result.get("score", 0.0))
                reasoning = claude_result.get("reasoning", "")
            else:
                score = 0.0
                reasoning = "Not analyzed"

            # Auto-approve jika score >= threshold
            is_approved = score >= AUTO_APPROVE_THRESHOLD

            await conn.execute("""
                INSERT INTO kb_engine_scores
                    (document_id, engine_name, engine_index, relevance_score, is_approved, claude_reasoning)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, doc_id, engine_info["name"], engine_info["index"], score, is_approved, reasoning)

            engine_scores_saved.append({
                "engine_name": engine_info["name"],
                "engine_index": engine_info["index"],
                "category": engine_info["category"],
                "group": engine_info["group"],
                "score": round(score, 3),
                "score_pct": round(score * 100, 1),
                "is_approved": is_approved,
                "user_override": False,
                "reasoning": reasoning
            })

        # Step 6: Simpan chunks ke DB
        print("[KB] Step 6: Saving chunks...")
        # Determine engine tags per chunk (engines yang approved)
        approved_engines = [
            e["engine_name"] for e in engine_scores_saved if e["is_approved"]
        ]
        engine_tags_json = json.dumps(approved_engines)

        for chunk in chunks[:500]:  # Limit 500 chunks untuk performance
            await conn.execute("""
                INSERT INTO kb_chunks (document_id, chunk_index, page_number, content, content_length, engine_tags)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, doc_id, chunk["chunk_index"], chunk["page_number"],
                chunk["content"], chunk["content_length"], engine_tags_json)

        # Update status dokumen
        await conn.execute("""
            UPDATE kb_documents
            SET status = 'analyzed', total_chunks = $1
            WHERE id = $2
        """, len(chunks), doc_id)

        approved_count = sum(1 for e in engine_scores_saved if e["is_approved"])
        print(f"[KB] Done! {approved_count}/34 engines auto-approved (≥60%)")

        return {
            "success": True,
            "document_id": doc_id,
            "filename": original_filename,
            "total_pages": total_pages,
            "total_chunks": len(chunks),
            "engine_scores": engine_scores_saved,
            "approved_count": approved_count,
            "threshold": AUTO_APPROVE_THRESHOLD,
            "message": f"PDF berhasil dianalisis. {approved_count} engines auto-approved (score ≥ 60%)"
        }

    except Exception as e:
        print(f"[KB] Error: {e}")
        # Update status error jika doc sudah dibuat
        try:
            if 'doc_id' in locals():
                await conn.execute(
                    "UPDATE kb_documents SET status = 'error' WHERE id = $1", doc_id
                )
        except:
            pass
        raise
    finally:
        await conn.close()


# ============================================================
# UPDATE ENGINE APPROVAL (User manual edit)
# ============================================================

async def update_engine_approval(
    document_id: int,
    engine_name: str,
    is_approved: bool
) -> Dict[str, Any]:
    """User manually toggle approve/unapprove engine."""
    conn = await get_db_conn()
    try:
        result = await conn.fetchrow("""
            UPDATE kb_engine_scores
            SET is_approved = $1, user_override = TRUE
            WHERE document_id = $2 AND engine_name = $3
            RETURNING id, engine_name, is_approved, relevance_score
        """, is_approved, document_id, engine_name)

        if not result:
            return {"success": False, "message": "Engine score not found"}

        # Update engine_tags di chunks
        approved_engines = await conn.fetch("""
            SELECT engine_name FROM kb_engine_scores
            WHERE document_id = $1 AND is_approved = TRUE
        """, document_id)
        approved_list = [r["engine_name"] for r in approved_engines]
        engine_tags_json = json.dumps(approved_list)

        await conn.execute("""
            UPDATE kb_chunks SET engine_tags = $1 WHERE document_id = $2
        """, engine_tags_json, document_id)

        return {
            "success": True,
            "engine_name": engine_name,
            "is_approved": is_approved,
            "document_id": document_id
        }
    finally:
        await conn.close()


# ============================================================
# GET DOCUMENTS LIST
# ============================================================

async def get_all_documents() -> List[Dict]:
    """Ambil semua dokumen KB."""
    conn = await get_db_conn()
    try:
        rows = await conn.fetch("""
            SELECT d.id, d.original_name, d.file_size, d.page_count,
                   d.status, d.total_chunks, d.description, d.created_at,
                   COUNT(CASE WHEN es.is_approved THEN 1 END) as approved_engines
            FROM kb_documents d
            LEFT JOIN kb_engine_scores es ON es.document_id = d.id
            GROUP BY d.id
            ORDER BY d.created_at DESC
        """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_document_scores(document_id: int) -> Dict:
    """Ambil skor per engine untuk satu dokumen."""
    conn = await get_db_conn()
    try:
        doc = await conn.fetchrow(
            "SELECT * FROM kb_documents WHERE id = $1", document_id
        )
        if not doc:
            return {"success": False, "message": "Document not found"}

        scores = await conn.fetch("""
            SELECT engine_name, engine_index, relevance_score, is_approved,
                   user_override, claude_reasoning
            FROM kb_engine_scores
            WHERE document_id = $1
            ORDER BY engine_index
        """, document_id)

        return {
            "success": True,
            "document": dict(doc),
            "engine_scores": [dict(s) for s in scores]
        }
    finally:
        await conn.close()


# ============================================================
# RAG: SEARCH CHUNKS
# ============================================================

async def search_chunks_for_engine(
    engine_name: str,
    query: str,
    limit: int = 5
) -> List[Dict]:
    """
    Simple text search chunks yang relevan untuk engine tertentu.
    (Tanpa vector search — pakai LIKE untuk compatibility)
    """
    conn = await get_db_conn()
    try:
        # Cari chunks yang:
        # 1. Engine-nya approved untuk engine ini
        # 2. Content mengandung kata kunci dari query
        words = query.split()[:5]  # Ambil 5 kata pertama
        search_term = " ".join(words)

        rows = await conn.fetch("""
            SELECT c.id, c.content, c.page_number, c.chunk_index,
                   d.original_name as source_document
            FROM kb_chunks c
            JOIN kb_documents d ON d.id = c.document_id
            WHERE c.engine_tags::text LIKE $1
              AND c.content ILIKE $2
            ORDER BY c.id DESC
            LIMIT $3
        """, f'%{engine_name}%', f'%{search_term[:50]}%', limit)

        # Kalau tidak ada hasil dengan filter content, ambil semua chunks untuk engine ini
        if not rows:
            rows = await conn.fetch("""
                SELECT c.id, c.content, c.page_number, c.chunk_index,
                       d.original_name as source_document
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE c.engine_tags::text LIKE $1
                ORDER BY c.id DESC
                LIMIT $2
            """, f'%{engine_name}%', limit)

        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_kb_context_for_engine(engine_name: str, ticker: str = "") -> str:
    """
    Ambil konteks KB untuk inject ke engine prompt.
    Return string siap pakai.
    """
    chunks = await search_chunks_for_engine(engine_name, ticker or engine_name)
    if not chunks:
        return ""

    context_parts = [
        f"[KB: {c['source_document']} p.{c['page_number']}]\n{c['content'][:500]}"
        for c in chunks[:3]
    ]
    return "\n\n---\n\n".join(context_parts)
