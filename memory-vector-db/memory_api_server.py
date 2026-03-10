#!/usr/bin/env python3
"""
Memory Vector DB API Server - Multi-User Edition
Exposes memory retrieval and embedding APIs with user isolation.
Authentication: X-API-Key header (user_id)
"""
import sys
import json
import argparse
import uuid as uuid_module
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

try:
    from pysqlite3 import dbapi2 as sqlite3
except ImportError:
    import sqlite3

import numpy as np
import sqlite_vec
import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configuration
MEMORY_DIR = Path.home() / ".my-memory"
DB_PATH = MEMORY_DIR / "my-memories.db"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "bge-m3"
EMBEDDING_DIM = 1024

# FastAPI app
app = FastAPI(
    title="Memory Vector DB API (Multi-User)",
    description="API for semantic memory search and embeddings with user isolation",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Models ====================

class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    semantic_weight: float = 0.7


class SearchResponse(BaseModel):
    results: List[Dict[str, Any]]
    query: str
    total: int
    user_id: str


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    embedding: List[float]
    dimensions: int
    model: str


class AddMemoryRequest(BaseModel):
    date: Optional[str] = None
    type: str = "note"
    summary: str
    importance: float = 0.5
    tags: List[str] = []


class AddMemoryResponse(BaseModel):
    uuid: str
    user_id: str
    date: str
    type: str
    summary: str
    importance: float
    tags: List[str]


class HealthResponse(BaseModel):
    status: str
    ollama: bool
    database: bool
    model: str
    multi_user: bool = True


# ==================== Auth ====================

async def get_user_id(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    """
    Extract user_id from X-API-Key header.
    The API key IS the user_id - simple identity-based auth.
    """
    if not x_api_key or not x_api_key.strip():
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    
    # Sanitize user_id (alphanumeric + underscore + dash only)
    user_id = x_api_key.strip()
    if not all(c.isalnum() or c in '_-' for c in user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id format")
    
    # Limit length
    if len(user_id) > 64:
        raise HTTPException(status_code=400, detail="user_id too long (max 64 chars)")
    
    return user_id


# ==================== Database ====================

def get_embedding(text: str) -> List[float]:
    """Get embedding from Ollama HTTP API"""
    import urllib.request
    
    url = f"{OLLAMA_HOST}/api/embeddings"
    data = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": text
    }).encode('utf-8')
    
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get("embedding", [])
    except Exception as e:
        print(f"Error getting embedding: {e}")
        return []


def init_db():
    """Initialize the database with multi-user support"""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    
    cursor = conn.cursor()
    
    # Create memories table (with user_id)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            uuid TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            summary TEXT NOT NULL,
            importance REAL DEFAULT 0.5,
            metadata TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Migrate old data if needed (add user_id column)
    try:
        cursor.execute("SELECT user_id FROM memories LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, need to migrate
        print("Migrating database to multi-user schema...")
        try:
            cursor.execute("ALTER TABLE memories ADD COLUMN user_id TEXT DEFAULT 'default'")
            cursor.execute("UPDATE memories SET user_id = 'default' WHERE user_id IS NULL")
        except:
            pass  # Column might already exist
    
    # Create index on user_id for fast filtering
    try:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id)
        """)
    except:
        pass
    
    # Create composite index for user_id + date
    try:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_user_date ON memories(user_id, date)
        """)
    except:
        pass
    
    # Create vector table
    cursor.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories USING vec0(
            embedding float[{EMBEDDING_DIM}]
        )
    """)
    
    # Create mapping table (with user_id)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vec_memory_mapping (
            vec_rowid INTEGER PRIMARY KEY,
            memory_uuid TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'default'
        )
    """)
    
    # Migrate mapping table if needed
    try:
        cursor.execute("SELECT user_id FROM vec_memory_mapping LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cursor.execute("ALTER TABLE vec_memory_mapping ADD COLUMN user_id TEXT DEFAULT 'default'")
            cursor.execute("UPDATE vec_memory_mapping SET user_id = 'default' WHERE user_id IS NULL")
        except:
            pass
    
    # Create index on mapping user_id
    try:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_mapping_user_id ON vec_memory_mapping(user_id)
        """)
    except:
        pass
    
    conn.commit()
    conn.close()


def semantic_search(user_id: str, query_embedding: List[float], limit: int = 10) -> List[Dict]:
    """Search memories by semantic similarity, filtered by user_id"""
    if not DB_PATH.exists():
        return []
    
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    cursor = conn.cursor()
    
    query_array = np.array(query_embedding, dtype=np.float32)
    
    try:
        # KEY: Filter by user_id in the query
        cursor.execute("""
            SELECT
                m.uuid,
                m.date,
                m.type,
                m.summary,
                m.importance,
                m.metadata,
                vec_distance_cosine(v.embedding, ?) as distance
            FROM vec_memories v
            JOIN vec_memory_mapping map ON v.rowid = map.vec_rowid
            JOIN memories m ON map.memory_uuid = m.uuid
            WHERE v.embedding IS NOT NULL
              AND m.user_id = ?
            ORDER BY distance ASC
            LIMIT ?
        """, (query_array, user_id, limit))
        
        results = []
        for row in cursor.fetchall():
            memory_uuid, date, mem_type, summary, importance, metadata_json, distance = row
            similarity = 1.0 - distance
            
            try:
                metadata = json.loads(metadata_json) if metadata_json else {}
                tags = metadata.get("tags", [])
            except:
                tags = []
            
            results.append({
                "uuid": memory_uuid,
                "date": date,
                "type": mem_type,
                "summary": summary,
                "importance": importance,
                "tags": tags,
                "similarity": round(similarity, 4)
            })
        
        return results
    except Exception as e:
        print(f"Search error: {e}")
        return []
    finally:
        conn.close()


def add_memory(user_id: str, date: str, mem_type: str, summary: str, 
               importance: float = 0.5, tags: List[str] = None) -> str:
    """Add a new memory for a user"""
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    
    cursor = conn.cursor()
    
    # Generate UUID
    memory_uuid = str(uuid_module.uuid4())
    
    # Get embedding
    embedding = get_embedding(summary)
    
    # Prepare metadata
    metadata = json.dumps({"tags": tags or []})
    
    # Insert memory
    cursor.execute("""
        INSERT INTO memories (uuid, user_id, date, type, summary, importance, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (memory_uuid, user_id, date, mem_type, summary, importance, metadata))
    
    # Insert embedding if available
    if embedding:
        embedding_array = np.array(embedding, dtype=np.float32)
        cursor.execute("""
            INSERT INTO vec_memories (embedding) VALUES (?)
        """, (embedding_array,))
        
        vec_rowid = cursor.lastrowid
        
        cursor.execute("""
            INSERT INTO vec_memory_mapping (vec_rowid, memory_uuid, user_id)
            VALUES (?, ?, ?)
        """, (vec_rowid, memory_uuid, user_id))
    
    conn.commit()
    conn.close()
    
    return memory_uuid


def get_recent_memories_db(user_id: str, days: int = 7, limit: int = 20) -> List[Dict]:
    """Get recent memory entries for a user"""
    if not DB_PATH.exists():
        return []
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    # KEY: Filter by user_id
    cursor.execute("""
        SELECT uuid, date, type, summary, importance, metadata
        FROM memories
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC, importance DESC
        LIMIT ?
    """, (user_id, since_date, limit))
    
    memories = []
    for row in cursor.fetchall():
        uuid, date, mem_type, summary, importance, metadata_json = row
        try:
            metadata = json.loads(metadata_json) if metadata_json else {}
            tags = metadata.get("tags", [])
        except:
            tags = []
        
        memories.append({
            "uuid": uuid,
            "date": date,
            "type": mem_type,
            "summary": summary,
            "importance": importance,
            "tags": tags
        })
    
    conn.close()
    
    return memories


def delete_user_memories(user_id: str) -> int:
    """Delete all memories for a user"""
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    
    cursor = conn.cursor()
    
    # Get memory UUIDs
    cursor.execute("SELECT uuid FROM memories WHERE user_id = ?", (user_id,))
    uuids = [row[0] for row in cursor.fetchall()]
    
    # Delete from vector mapping
    for uuid in uuids:
        cursor.execute("SELECT vec_rowid FROM vec_memory_mapping WHERE memory_uuid = ?", (uuid,))
        rowids = [row[0] for row in cursor.fetchall()]
        
        for rowid in rowids:
            cursor.execute("DELETE FROM vec_memories WHERE rowid = ?", (rowid,))
        
        cursor.execute("DELETE FROM vec_memory_mapping WHERE memory_uuid = ?", (uuid,))
    
    # Delete memories
    cursor.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
    deleted_count = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return deleted_count


# ==================== Endpoints ====================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check service health (no auth required)"""
    import urllib.request
    
    ollama_ok = False
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags", method='GET')
        with urllib.request.urlopen(req, timeout=5) as response:
            ollama_ok = response.status == 200
    except:
        pass
    
    db_ok = DB_PATH.exists()
    
    return HealthResponse(
        status="healthy" if ollama_ok and db_ok else "degraded",
        ollama=ollama_ok,
        database=db_ok,
        model=OLLAMA_MODEL,
        multi_user=True
    )


@app.post("/embed", response_model=EmbedResponse)
async def get_embedding_api(
    request: EmbedRequest,
    user_id: str = Depends(get_user_id)
):
    """Get embedding vector for text"""
    embedding = get_embedding(request.text)
    
    if not embedding:
        raise HTTPException(status_code=503, detail="Embedding service unavailable")
    
    return EmbedResponse(
        embedding=embedding,
        dimensions=len(embedding),
        model=OLLAMA_MODEL
    )


@app.post("/search", response_model=SearchResponse)
async def search_memories(
    request: SearchRequest,
    user_id: str = Depends(get_user_id)
):
    """Search memories using semantic + keyword hybrid search (user-isolated)"""
    query_embedding = get_embedding(request.query)
    
    if not query_embedding:
        raise HTTPException(status_code=503, detail="Embedding service unavailable")
    
    # Semantic search (user-isolated)
    semantic_results = semantic_search(user_id, query_embedding, limit=request.limit)
    
    # Combine results
    all_results = []
    seen_uuids = set()
    
    for r in semantic_results:
        if r["uuid"] not in seen_uuids:
            r["final_score"] = r["similarity"] * request.semantic_weight
            r["source"] = "semantic"
            all_results.append(r)
            seen_uuids.add(r["uuid"])
    
    # Sort by final score
    all_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    
    return SearchResponse(
        results=all_results[:request.limit],
        query=request.query,
        total=len(all_results),
        user_id=user_id
    )


@app.post("/memories/add", response_model=AddMemoryResponse)
async def add_memory_api(
    request: AddMemoryRequest,
    user_id: str = Depends(get_user_id)
):
    """Add a new memory (user-isolated)"""
    date = request.date or datetime.now().strftime("%Y-%m-%d")
    
    memory_uuid = add_memory(
        user_id=user_id,
        date=date,
        mem_type=request.type,
        summary=request.summary,
        importance=request.importance,
        tags=request.tags
    )
    
    return AddMemoryResponse(
        uuid=memory_uuid,
        user_id=user_id,
        date=date,
        type=request.type,
        summary=request.summary,
        importance=request.importance,
        tags=request.tags
    )


@app.get("/memories/recent")
async def get_recent_memories_api(
    days: int = 7,
    limit: int = 20,
    user_id: str = Depends(get_user_id)
):
    """Get recent memory entries (user-isolated)"""
    memories = get_recent_memories_db(user_id, days=days, limit=limit)
    
    return {
        "memories": memories,
        "total": len(memories),
        "user_id": user_id
    }


@app.delete("/memories/all")
async def delete_all_memories(user_id: str = Depends(get_user_id)):
    """Delete all memories for the authenticated user"""
    deleted_count = delete_user_memories(user_id)
    
    return {
        "deleted": deleted_count,
        "user_id": user_id
    }


@app.get("/user/stats")
async def get_user_stats(user_id: str = Depends(get_user_id)):
    """Get statistics for the authenticated user"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Total memories
    cursor.execute("SELECT COUNT(*) FROM memories WHERE user_id = ?", (user_id,))
    total_memories = cursor.fetchone()[0]
    
    # Earliest memory
    cursor.execute("SELECT MIN(date) FROM memories WHERE user_id = ?", (user_id,))
    earliest = cursor.fetchone()[0]
    
    # Latest memory
    cursor.execute("SELECT MAX(date) FROM memories WHERE user_id = ?", (user_id,))
    latest = cursor.fetchone()[0]
    
    # Memory types
    cursor.execute("""
        SELECT type, COUNT(*) 
        FROM memories 
        WHERE user_id = ? 
        GROUP BY type
    """, (user_id,))
    types = {row[0]: row[1] for row in cursor.fetchall()}
    
    conn.close()
    
    return {
        "user_id": user_id,
        "total_memories": total_memories,
        "earliest_date": earliest,
        "latest_date": latest,
        "memory_types": types
    }


# ==================== Startup ====================

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    init_db()
    print(f"🗄️  Memory DB: {DB_PATH}")
    print(f"🤖 Ollama Model: {OLLAMA_MODEL}")
    print(f"🔐 Multi-user mode: enabled (X-API-Key header)")
    print(f"📡 API ready on http://0.0.0.0:8000")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Memory Vector DB API Server (Multi-User)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--model", default="bge-m3", help="Ollama embedding model")
    
    args = parser.parse_args()
    
    OLLAMA_MODEL = args.model
    
    print(f"🚀 Starting Memory API Server (Multi-User) on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)