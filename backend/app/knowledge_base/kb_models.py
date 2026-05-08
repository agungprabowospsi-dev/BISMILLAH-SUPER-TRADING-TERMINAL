# backend/app/knowledge_base/kb_models.py
"""
Database models untuk Knowledge Base.
Gunakan PostgreSQL standard (tanpa pgvector extension dulu).
Simpan embeddings sebagai JSON array — compatible dengan Termux/Railway.
"""

from datetime import datetime
from typing import Optional
import json


# ============================================================
# SQL SCHEMA — jalankan sekali untuk setup DB
# ============================================================

CREATE_TABLES_SQL = """
-- Tabel untuk buku/dokumen yang diupload
CREATE TABLE IF NOT EXISTS kb_documents (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(500) NOT NULL,
    original_name VARCHAR(500) NOT NULL,
    file_size INTEGER,
    page_count INTEGER,
    upload_time TIMESTAMP DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'processing',  -- processing, analyzed, approved, rejected
    total_chunks INTEGER DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Tabel untuk skor relevansi per engine
CREATE TABLE IF NOT EXISTS kb_engine_scores (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES kb_documents(id) ON DELETE CASCADE,
    engine_name VARCHAR(200) NOT NULL,
    engine_index INTEGER,  -- 1-34
    relevance_score FLOAT DEFAULT 0.0,  -- 0.0 - 1.0
    is_approved BOOLEAN DEFAULT FALSE,  -- true jika score >= 0.6 atau user centang manual
    user_override BOOLEAN DEFAULT FALSE,  -- true jika user yang edit manual
    claude_reasoning TEXT,  -- alasan Claude kenapa relevan/tidak
    created_at TIMESTAMP DEFAULT NOW()
);

-- Tabel untuk text chunks dari PDF
CREATE TABLE IF NOT EXISTS kb_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER,
    page_number INTEGER,
    content TEXT NOT NULL,
    content_length INTEGER,
    embedding_json TEXT,  -- JSON array float (embeddings sebagai text)
    engine_tags TEXT,  -- JSON array engine names yang relevan
    created_at TIMESTAMP DEFAULT NOW()
);

-- Index untuk performance
CREATE INDEX IF NOT EXISTS idx_kb_chunks_document ON kb_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_engine_scores_document ON kb_engine_scores(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_engine_scores_approved ON kb_engine_scores(is_approved);
"""

# ============================================================
# 34 ENGINE NAMES (sama persis dengan master_runner)
# ============================================================

ALL_34_ENGINES = [
    # Group 1 — Technical
    {"index": 1,  "name": "PriceActionEngine",         "group": 1, "category": "Technical"},
    {"index": 2,  "name": "TrendStructureEngine",       "group": 1, "category": "Technical"},
    {"index": 3,  "name": "SupportResistanceEngine",    "group": 1, "category": "Technical"},
    {"index": 4,  "name": "VolumeIntelligenceEngine",   "group": 1, "category": "Technical"},
    {"index": 5,  "name": "RelativeVolumeEngine",       "group": 1, "category": "Technical"},
    {"index": 6,  "name": "MultiTimeframeEngine",       "group": 1, "category": "Technical"},
    {"index": 7,  "name": "OrderBlockEngine",           "group": 1, "category": "SMC"},
    {"index": 8,  "name": "BreakOrderEngine",           "group": 1, "category": "SMC"},
    {"index": 9,  "name": "FairValueGapEngine",         "group": 1, "category": "SMC"},
    {"index": 10, "name": "LiquidityEngine",            "group": 1, "category": "SMC"},
    # Group 2 — Bandarmology
    {"index": 11, "name": "BandarmologyEngine",         "group": 2, "category": "Bandarmology"},
    {"index": 12, "name": "InventoryEngine",            "group": 2, "category": "Bandarmology"},
    {"index": 13, "name": "FlowMappingEngine",          "group": 2, "category": "Bandarmology"},
    {"index": 14, "name": "IntradayPositioningEngine",  "group": 2, "category": "Bandarmology"},
    {"index": 15, "name": "ForeignFlowEngine",          "group": 2, "category": "Bandarmology"},
    # Group 3 — Quant & Macro
    {"index": 16, "name": "QuantEdgeEngine",            "group": 3, "category": "Quant"},
    {"index": 17, "name": "OrderbookEngine",            "group": 3, "category": "Quant"},
    {"index": 18, "name": "RelativeStrengthEngine",     "group": 3, "category": "Quant"},
    {"index": 19, "name": "FibonacciEngine",            "group": 3, "category": "Technical"},
    {"index": 20, "name": "AIPatternRecognitionEngine", "group": 3, "category": "AI"},
    {"index": 21, "name": "SectorRotationEngine",       "group": 3, "category": "Macro"},
    {"index": 22, "name": "MacroMarketEngine",          "group": 3, "category": "Macro"},
    {"index": 23, "name": "MacroEconomicsEngine",       "group": 3, "category": "Macro"},
    {"index": 24, "name": "GeopoliticsEngine",          "group": 3, "category": "Macro"},
    {"index": 25, "name": "NewsSentimentEngine",        "group": 3, "category": "Sentiment"},
    {"index": 26, "name": "InsiderOwnershipEngine",     "group": 3, "category": "Fundamental"},
    {"index": 27, "name": "ProbabilityEngine",          "group": 3, "category": "Quant"},
    {"index": 28, "name": "TradingSetupEngine",         "group": 3, "category": "Decision"},
    # Group 4 — Decision & Risk
    {"index": 29, "name": "RiskManagementEngine",       "group": 4, "category": "Risk"},
    {"index": 30, "name": "FinalScorecardEngine",       "group": 4, "category": "Decision"},
    {"index": 31, "name": "AIConfidenceEngine",         "group": 4, "category": "AI"},
    {"index": 32, "name": "SmartRotationEngine",        "group": 4, "category": "Decision"},
    {"index": 33, "name": "RealtimeAlertEngine",        "group": 4, "category": "Alert"},
    {"index": 34, "name": "LiquidityQualityEngine",     "group": 4, "category": "Quant"},
]

ENGINE_NAMES = [e["name"] for e in ALL_34_ENGINES]
