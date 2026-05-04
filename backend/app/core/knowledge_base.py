import os
import logging
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

BOOKS_DIR = Path("/app/knowledge_base/books")
CHROMA_DIR = Path("/app/knowledge_base/chroma_db")

_chroma_client = None
_embedding_model = None
_collections = {}

BOOK_CONFIG = {
    "anna_couling": {
        "file": "anna_couling.epub",
        "collection": "price_action",
        "description": "Volume Price Action Analysis by Anna Couling"
    },
    "carolyn_boroden": {
        "file": "carolyn_boroden.epub",
        "collection": "fibonacci",
        "description": "Fibonacci Trading by Carolyn Boroden"
    },
    "bulkowski": {
        "file": "bulkowski.pdf",
        "collection": "candlestick_patterns",
        "description": "Encyclopedia of Candlestick Charts by Thomas Bulkowski"
    }
}

async def init_knowledge_base():
    global _chroma_client, _embedding_model, _collections
    try:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

        for key, config in BOOK_CONFIG.items():
            collection = _chroma_client.get_or_create_collection(
                name=config["collection"],
                metadata={"description": config["description"]}
            )
            _collections[key] = collection

            # Index jika belum ada
            if collection.count() == 0:
                book_path = BOOKS_DIR / config["file"]
                if book_path.exists():
                    logger.info(f"Indexing {config['file']}...")
                    chunks = _extract_text(book_path)
                    if chunks:
                        embeddings = _embedding_model.encode(chunks).tolist()
                        ids = [f"{key}_{i}" for i in range(len(chunks))]
                        collection.add(documents=chunks, embeddings=embeddings, ids=ids)
                        logger.info(f"✅ Indexed {len(chunks)} chunks from {config['file']}")
                else:
                    logger.warning(f"⚠️ Book not found: {book_path}")

        logger.info("✅ Knowledge Base ready")
    except Exception as e:
        logger.error(f"Knowledge Base init error: {e}")

def _extract_text(path: Path) -> list:
    chunks = []
    try:
        if path.suffix == ".epub":
            book = epub.read_epub(str(path))
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator=" ", strip=True)
                chunks.extend(_split_text(text))
        elif path.suffix == ".pdf":
            doc = fitz.open(str(path))
            for page in doc:
                text = page.get_text()
                chunks.extend(_split_text(text))
    except Exception as e:
        logger.error(f"Text extraction error for {path}: {e}")
    return chunks

def _split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list:
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if len(chunk) > 100:
            chunks.append(chunk)
    return chunks

async def query_knowledge_base(collection_key: str, query: str, n_results: int = 3) -> str:
    """Query knowledge base dan return relevant context"""
    try:
        if collection_key not in _collections:
            return ""
        collection = _collections[collection_key]
        if collection.count() == 0:
            return ""
        query_embedding = _embedding_model.encode([query]).tolist()
        results = collection.query(query_embeddings=query_embedding, n_results=n_results)
        if results and results["documents"]:
            return "\n\n".join(results["documents"][0])
    except Exception as e:
        logger.error(f"KB query error: {e}")
    return ""
