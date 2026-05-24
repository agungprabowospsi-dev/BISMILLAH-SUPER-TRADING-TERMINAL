# backend/app/knowledge_base/kb_service.py
import os
import json
import asyncio
import re
from typing import List, Dict, Any, Optional
import asyncpg
from anthropic import AsyncAnthropic

from .kb_models import ALL_34_ENGINES, ENGINE_NAMES, ENGINE_COUNT, CREATE_TABLES_SQL

anthropic_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
AUTO_APPROVE_THRESHOLD = 0.60


async def get_db_conn():
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return await asyncpg.connect(db_url)


async def ensure_tables_exist():
    conn = await get_db_conn()
    try:
        await conn.execute(CREATE_TABLES_SQL)
    finally:
        await conn.close()


def extract_text_from_pdf(pdf_bytes: bytes) -> Dict[str, Any]:
    import fitz
    import io

    # Tulis ke buffer dulu, hindari "document closed"
    pdf_stream = io.BytesIO(pdf_bytes)
    doc = fitz.open(stream=pdf_stream.read(), filetype="pdf")

    total_pages = len(doc)
    pages = []
    full_text_parts = []

    for page_num in range(total_pages):
        try:
            page = doc[page_num]
            text = page.get_text("text")
            if text:
                text = text.strip()
                if text:
                    pages.append({"page_num": page_num + 1, "text": text})
                    full_text_parts.append(f"[Page {page_num + 1}]\n{text}")
        except Exception as e:
            print(f"[KB] Skip page {page_num+1}: {e}")
            continue

    doc.close()

    return {
        "pages": pages,
        "total_pages": total_pages,
        "full_text": "\n\n".join(full_text_parts)
    }


def chunk_text(pages: List[Dict], chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[Dict]:
    chunks = []
    chunk_index = 0

    for page_data in pages:
        text = page_data["text"]
        page_num = page_data["page_num"]
        paragraphs = re.split(r'\n{2,}', text)
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current_chunk) + len(para) + 1 <= chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append({
                        "chunk_index": chunk_index,
                        "page_number": page_num,
                        "content": current_chunk.strip(),
                        "content_length": len(current_chunk)
                    })
                    chunk_index += 1
                overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                current_chunk = overlap_text + "\n\n" + para

        if current_chunk.strip():
            chunks.append({
                "chunk_index": chunk_index,
                "page_number": page_num,
                "content": current_chunk.strip(),
                "content_length": len(current_chunk)
            })
            chunk_index += 1

    return chunks


async def analyze_relevance_with_claude(book_title: str, sample_text: str, engine_batch: List[Dict]) -> List[Dict]:
    engine_list_str = "\n".join([
        f"{e['index']}. {e['name']} (Category: {e['category']})"
        for e in engine_batch
    ])

    prompt = f"""Kamu adalah expert sistem trading saham IDX Indonesia.

Aku punya sebuah buku/dokumen trading dengan judul: "{book_title}"

Berikut sample teks dari buku tersebut:
---
{sample_text[:3000]}
---

Aku memiliki {len(engine_batch)} trading analysis engines berikut:
{engine_list_str}

Tugas kamu: Untuk setiap engine di atas, berikan skor relevansi (0.0 - 1.0).

Kriteria scoring:
- 0.8-1.0: Sangat relevan, banyak konten berguna
- 0.6-0.79: Cukup relevan
- 0.4-0.59: Sedikit relevan
- 0.2-0.39: Kurang relevan
- 0.0-0.19: Tidak relevan

Jawab HANYA JSON array, tanpa teks lain:
[
  {{"engine_name": "NamaEngine", "score": 0.85, "reasoning": "Alasan singkat 1-2 kalimat"}},
  ...
]"""

    response = await anthropic_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = response.content[0].text.strip()

    try:
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        raise ValueError("No JSON array found")
    except Exception as e:
        print(f"[KB] Claude parse error: {e}")
        return [{"engine_name": e["name"], "score": 0.0, "reasoning": "Parse error"} for e in engine_batch]


async def analyze_all_engines(book_title: str, sample_text: str) -> List[Dict]:
    all_results = []
    batch_size = 10
    for i in range(0, len(ALL_34_ENGINES), batch_size):
        batch = ALL_34_ENGINES[i:i + batch_size]
        print(f"  [KB] Analyzing engines {i+1}-{min(i+batch_size, ENGINE_COUNT)}...")
        results = await analyze_relevance_with_claude(book_title, sample_text, batch)
        all_results.extend(results)
        await asyncio.sleep(0.5)
    return all_results


async def process_pdf_upload(pdf_bytes: bytes, original_filename: str, description: Optional[str] = None) -> Dict[str, Any]:
    await ensure_tables_exist()
    conn = await get_db_conn()
    doc_id = None

    try:
        print(f"[KB] Processing: {original_filename} ({len(pdf_bytes)} bytes)")

        extracted = extract_text_from_pdf(pdf_bytes)
        full_text = extracted["full_text"]
        pages = extracted["pages"]
        total_pages = extracted["total_pages"]
        print(f"[KB] Extracted {total_pages} pages, {len(pages)} with text, {len(full_text)} chars")

        if not pages:
            raise ValueError("PDF tidak mengandung teks yang bisa dibaca (mungkin PDF gambar/scan)")

        book_title = original_filename.replace(".pdf", "").replace("_", " ").replace("-", " ")

        doc_id = await conn.fetchval("""
            INSERT INTO kb_documents (filename, original_name, file_size, page_count, status, description)
            VALUES ($1, $2, $3, $4, 'analyzing', $5) RETURNING id
        """, original_filename, original_filename, len(pdf_bytes), total_pages, description or "")
        print(f"[KB] Document ID: {doc_id}")

        chunks = chunk_text(pages)
        print(f"[KB] Created {len(chunks)} chunks")

        sample_text = full_text[:5000]
        engine_scores_raw = await analyze_all_engines(book_title, sample_text)

        engine_scores_saved = []
        for engine_info in ALL_34_ENGINES:
            claude_result = next((r for r in engine_scores_raw if r.get("engine_name") == engine_info["name"]), None)
            score = float(claude_result.get("score", 0.0)) if claude_result else 0.0
            reasoning = claude_result.get("reasoning", "") if claude_result else "Not analyzed"
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

        approved_engines = [e["engine_name"] for e in engine_scores_saved if e["is_approved"]]
        engine_tags_json = json.dumps(approved_engines)

        for chunk in chunks[:500]:
            await conn.execute("""
                INSERT INTO kb_chunks (document_id, chunk_index, page_number, content, content_length, engine_tags)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, doc_id, chunk["chunk_index"], chunk["page_number"],
                chunk["content"], chunk["content_length"], engine_tags_json)

        await conn.execute("""
            UPDATE kb_documents SET status = 'analyzed', total_chunks = $1 WHERE id = $2
        """, len(chunks), doc_id)

        approved_count = len(approved_engines)
        print(f"[KB] Done! {approved_count}/{ENGINE_COUNT} engines auto-approved")

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
        import traceback
        traceback.print_exc()
        if doc_id:
            try:
                await conn.execute("UPDATE kb_documents SET status = 'error' WHERE id = $1", doc_id)
            except:
                pass
        raise
    finally:
        await conn.close()


async def update_engine_approval(document_id: int, engine_name: str, is_approved: bool) -> Dict[str, Any]:
    conn = await get_db_conn()
    try:
        result = await conn.fetchrow("""
            UPDATE kb_engine_scores SET is_approved = $1, user_override = TRUE
            WHERE document_id = $2 AND engine_name = $3
            RETURNING id, engine_name, is_approved, relevance_score
        """, is_approved, document_id, engine_name)

        if not result:
            return {"success": False, "message": "Engine score not found"}

        approved_engines = await conn.fetch("""
            SELECT engine_name FROM kb_engine_scores
            WHERE document_id = $1 AND is_approved = TRUE
        """, document_id)
        engine_tags_json = json.dumps([r["engine_name"] for r in approved_engines])
        await conn.execute("UPDATE kb_chunks SET engine_tags = $1 WHERE document_id = $2", engine_tags_json, document_id)

        return {"success": True, "engine_name": engine_name, "is_approved": is_approved, "document_id": document_id}
    finally:
        await conn.close()


async def get_all_documents() -> List[Dict]:
    conn = await get_db_conn()
    try:
        rows = await conn.fetch("""
            SELECT d.id, d.original_name, d.file_size, d.page_count,
                   d.status, d.total_chunks, d.description, d.created_at,
                   COUNT(CASE WHEN es.is_approved THEN 1 END) as approved_engines
            FROM kb_documents d
            LEFT JOIN kb_engine_scores es ON es.document_id = d.id
            GROUP BY d.id ORDER BY d.created_at DESC
        """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_document_scores(document_id: int) -> Dict:
    conn = await get_db_conn()
    try:
        doc = await conn.fetchrow("SELECT * FROM kb_documents WHERE id = $1", document_id)
        if not doc:
            return {"success": False, "message": "Document not found"}
        scores = await conn.fetch("""
            SELECT engine_name, engine_index, relevance_score, is_approved,
                   user_override, claude_reasoning
            FROM kb_engine_scores WHERE document_id = $1 ORDER BY engine_index
        """, document_id)
        return {"success": True, "document": dict(doc), "engine_scores": [dict(s) for s in scores]}
    finally:
        await conn.close()


async def search_chunks_for_engine(engine_name: str, query: str, limit: int = 5) -> List[Dict]:
    conn = await get_db_conn()
    try:
        query_terms = [
            t.lower() for t in re.findall(r"[A-Za-z0-9_]{3,}", query or "")
            if t.lower() not in {"saham", "stock", "engine", "idx", "yang", "dan", "atau", "the"}
        ][:12]
        fetch_limit = max(limit * 12, 40)
        rows = await conn.fetch("""
            SELECT c.id, c.content, c.page_number, c.chunk_index,
                   d.original_name as source_document
            FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id
            WHERE c.engine_tags::text LIKE $1
              AND d.status = 'analyzed'
            LIMIT $2
        """, f'%{engine_name}%', fetch_limit)

        candidates = [dict(r) for r in rows]
        if not candidates:
            return []

        def rank(row: Dict) -> tuple:
            text = (row.get("content") or "").lower()
            src = (row.get("source_document") or "").lower()
            score = sum(3 if term in src else 1 for term in query_terms if term in text or term in src)
            early_page_bonus = max(0, 3 - int(row.get("page_number") or 0) // 100)
            return (score, early_page_bonus, -int(row.get("chunk_index") or 0))

        candidates.sort(key=rank, reverse=True)

        selected = []
        seen_docs = set()
        for row in candidates:
            src = row.get("source_document") or ""
            if src in seen_docs and len(selected) < min(limit, 3):
                continue
            selected.append(row)
            seen_docs.add(src)
            if len(selected) >= limit:
                break
        return selected
    finally:
        await conn.close()


async def get_kb_context_for_engine(engine_name: str, ticker: str = "") -> str:
    chunks = await search_chunks_for_engine(engine_name, ticker or engine_name)
    if not chunks:
        return ""
    context_parts = [f"[KB: {c['source_document']} p.{c['page_number']}]\n{c['content'][:500]}" for c in chunks[:3]]
    return "\n\n---\n\n".join(context_parts)
