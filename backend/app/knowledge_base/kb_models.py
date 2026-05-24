# backend/app/knowledge_base/kb_models.py
"""
Database models and canonical engine metadata for Knowledge Base.
PostgreSQL only for now; embeddings are stored as JSON text.
"""

from datetime import datetime
from typing import Optional
import json


CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS kb_documents (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(500) NOT NULL,
    original_name VARCHAR(500) NOT NULL,
    file_size INTEGER,
    page_count INTEGER,
    upload_time TIMESTAMP DEFAULT NOW(),
    status VARCHAR(50) DEFAULT 'processing',
    total_chunks INTEGER DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kb_engine_scores (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES kb_documents(id) ON DELETE CASCADE,
    engine_name VARCHAR(200) NOT NULL,
    engine_index INTEGER,
    relevance_score FLOAT DEFAULT 0.0,
    is_approved BOOLEAN DEFAULT FALSE,
    user_override BOOLEAN DEFAULT FALSE,
    claude_reasoning TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER,
    page_number INTEGER,
    content TEXT NOT NULL,
    content_length INTEGER,
    embedding_json TEXT,
    engine_tags TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_chunks_document ON kb_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_engine_scores_document ON kb_engine_scores(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_engine_scores_approved ON kb_engine_scores(is_approved);
"""


# Kept as ALL_34_ENGINES for backward-compatible imports, but REV28+
# currently runs 35 engines after BrokerBehaviorEngine was added.
ALL_34_ENGINES = [
    {"index": 1,  "name": "PriceActionEngine",         "group": 1, "category": "Technical"},
    {"index": 2,  "name": "TrendStructureEngine",      "group": 1, "category": "Technical"},
    {"index": 3,  "name": "SupportResistanceEngine",   "group": 1, "category": "Technical"},
    {"index": 4,  "name": "VolumeIntelligenceEngine",  "group": 1, "category": "Technical"},
    {"index": 5,  "name": "RelativeVolumeEngine",      "group": 1, "category": "Technical"},
    {"index": 6,  "name": "MultiTimeframeEngine",      "group": 1, "category": "Technical"},
    {"index": 7,  "name": "OrderBlockEngine",          "group": 1, "category": "SMC"},
    {"index": 8,  "name": "BreakOrderEngine",          "group": 1, "category": "SMC"},
    {"index": 9,  "name": "FairValueGapEngine",        "group": 1, "category": "SMC"},
    {"index": 10, "name": "LiquidityEngine",           "group": 1, "category": "SMC"},
    {"index": 11, "name": "BandarmologyEngine",        "group": 2, "category": "Bandarmology"},
    {"index": 12, "name": "InventoryEngine",           "group": 2, "category": "Bandarmology"},
    {"index": 13, "name": "FlowMappingEngine",         "group": 2, "category": "Bandarmology"},
    {"index": 14, "name": "IntradayPositioningEngine", "group": 2, "category": "Bandarmology"},
    {"index": 15, "name": "BrokerBehaviorEngine",      "group": 2, "category": "Bandarmology"},
    {"index": 16, "name": "ForeignFlowEngine",         "group": 2, "category": "Bandarmology"},
    {"index": 17, "name": "QuantEdgeEngine",           "group": 3, "category": "Quant"},
    {"index": 18, "name": "OrderbookEngine",           "group": 3, "category": "Quant"},
    {"index": 19, "name": "RelativeStrengthEngine",    "group": 3, "category": "Quant"},
    {"index": 20, "name": "FibonacciEngine",           "group": 3, "category": "Technical"},
    {"index": 21, "name": "AIPatternRecognitionEngine","group": 3, "category": "AI"},
    {"index": 22, "name": "SectorRotationEngine",      "group": 3, "category": "Macro"},
    {"index": 23, "name": "MacroMarketEngine",         "group": 3, "category": "Macro"},
    {"index": 24, "name": "MacroEconomicsEngine",      "group": 3, "category": "Macro"},
    {"index": 25, "name": "GeopoliticsEngine",         "group": 3, "category": "Macro"},
    {"index": 26, "name": "NewsSentimentEngine",       "group": 3, "category": "Sentiment"},
    {"index": 27, "name": "InsiderOwnershipEngine",    "group": 3, "category": "Fundamental"},
    {"index": 28, "name": "ProbabilityEngine",         "group": 3, "category": "Quant"},
    {"index": 29, "name": "TradingSetupEngine",        "group": 3, "category": "Decision"},
    {"index": 30, "name": "RiskManagementEngine",      "group": 4, "category": "Risk"},
    {"index": 31, "name": "FinalScorecardEngine",      "group": 4, "category": "Decision"},
    {"index": 32, "name": "AIConfidenceEngine",        "group": 4, "category": "AI"},
    {"index": 33, "name": "SmartRotationEngine",       "group": 4, "category": "Decision"},
    {"index": 34, "name": "RealtimeAlertEngine",       "group": 4, "category": "Alert"},
    {"index": 35, "name": "LiquidityQualityEngine",    "group": 4, "category": "Quant"},
]

ENGINE_COUNT = len(ALL_34_ENGINES)
ENGINE_NAMES = [e["name"] for e in ALL_34_ENGINES]
