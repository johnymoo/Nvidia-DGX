#!/usr/bin/env python3
"""PDF to Markdown REST API Server with async processing support."""

import tempfile
import base64
import time
import json
import uuid
import asyncio
import threading
import os
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Body, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

# Configuration
CACHE_DIR = Path(os.environ.get("PDF2MD_CACHE_DIR", "/workspace/pdf2md_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Content-based cache index (file_hash -> task_id)
CONTENT_CACHE_FILE = CACHE_DIR / ".content_cache.json"

app = FastAPI(
    title="PDF to Markdown API",
    description="Convert PDF documents to Markdown using AI-powered layout detection. Supports async processing for large files.",
    version="2.0.2"
)


# ============ Content-based Cache ============

def load_content_cache() -> Dict[str, str]:
    """Load content-based cache index (file_hash -> task_id)."""
    if CONTENT_CACHE_FILE.exists():
        try:
            with open(CONTENT_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_content_cache(cache: Dict[str, str]):
    """Save content-based cache index."""
    with open(CONTENT_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def compute_file_hash(data: bytes, algorithm: str = "md5") -> str:
    """Compute file hash for content-based deduplication."""
    if algorithm == "md5":
        return hashlib.md5(data).hexdigest()
    elif algorithm == "sha256":
        return hashlib.sha256(data).hexdigest()
    else:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")


# Global content cache (loaded on startup)
content_cache: Dict[str, str] = load_content_cache()


# ============ Task Status ============

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    def __init__(self, task_id: str, filename: str, file_hash: Optional[str] = None):
        self.task_id = task_id
        self.filename = filename
        self.file_hash = file_hash  # Content-based hash for deduplication
        self.status = TaskStatus.PENDING
        self.created_at = datetime.utcnow()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.result: Optional[str] = None
        self.error: Optional[str] = None
        self.progress: str = "Waiting to start..."

    def to_dict(self) -> Dict[str, Any]:
        elapsed = None
        if self.started_at:
            end = self.completed_at or datetime.utcnow()
            elapsed = (end - self.started_at).total_seconds()
        
        return {
            "task_id": self.task_id,
            "filename": self.filename,
            "file_hash": self.file_hash,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "elapsed_seconds": elapsed,
            "progress": self.progress,
            "result": self.result,
            "error": self.error
        }
    
    def save_to_cache(self):
        """Save task to cache file."""
        cache_file = CACHE_DIR / f"{self.task_id}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load_from_cache(cls, task_id: str) -> Optional["Task"]:
        """Load task from cache file."""
        cache_file = CACHE_DIR / f"{task_id}.json"
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            task = cls(task_id, data["filename"], data.get("file_hash"))
            task.status = TaskStatus(data["status"])
            task.created_at = datetime.fromisoformat(data["created_at"])
            task.started_at = datetime.fromisoformat(data["started_at"]) if data["started_at"] else None
            task.completed_at = datetime.fromisoformat(data["completed_at"]) if data["completed_at"] else None
            task.progress = data["progress"]
            task.result = data.get("result")
            task.error = data.get("error")
            return task
        except Exception:
            return None


# In-memory task storage with cache backing
tasks: Dict[str, Task] = {}


def load_tasks_from_cache():
    """Load all cached tasks on startup."""
    for cache_file in CACHE_DIR.glob("*.json"):
        if cache_file.name == ".content_cache.json":
            continue
        task_id = cache_file.stem
        task = Task.load_from_cache(task_id)
        if task:
            tasks[task_id] = task


# Load cached tasks on startup
load_tasks_from_cache()


# ============ OpenAI-compatible models ============

class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "pdf2md"
    messages: List[ChatMessage]
    temperature: float = Field(default=0.7, ge=0, le=2)
    stream: bool = False
    async_mode: bool = Field(default=False, description="Enable async processing for large files")


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: Usage


# Global converter instance (lazy loaded)
_converter = None
_converter_lock = threading.Lock()


def get_converter():
    """Get or create the PDF converter instance (thread-safe)."""
    global _converter
    with _converter_lock:
        if _converter is None:
            _converter = PdfConverter(create_model_dict())
        return _converter


def convert_pdf_bytes(pdf_bytes: bytes, filename: str = "document.pdf", task: Optional[Task] = None) -> str:
    """Convert PDF bytes to Markdown text with progress updates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        pdf_path = tmpdir_path / filename
        pdf_path.write_bytes(pdf_bytes)
        
        converter = get_converter()
        
        if task:
            task.progress = "Converting PDF..."
        
        rendered = converter(str(pdf_path))
        text, _, _ = text_from_rendered(rendered)
        return text


def process_task(task_id: str, pdf_bytes: bytes, filename: str):
    """Background task processor."""
    task = tasks.get(task_id)
    if not task:
        return
    
    try:
        task.status = TaskStatus.PROCESSING
        task.started_at = datetime.utcnow()
        task.progress = "Starting conversion..."
        task.save_to_cache()
        
        result = convert_pdf_bytes(pdf_bytes, filename, task)
        
        task.result = result
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        task.progress = "Completed"
        task.save_to_cache()
        
    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.progress = f"Failed: {e}"
        task.completed_at = datetime.utcnow()
        task.save_to_cache()


def extract_pdf_from_messages(messages: List[ChatMessage]) -> tuple[bytes, str] | None:
    """Extract PDF content from messages (base64 encoded in content)."""
    for msg in messages:
        if isinstance(msg.content, str):
            # Check for base64 PDF marker
            if "[PDF_BASE64:" in msg.content and ":END_PDF]" in msg.content:
                start = msg.content.find("[PDF_BASE64:") + len("[PDF_BASE64:")
                end = msg.content.find(":END_PDF]")
                b64_data = msg.content[start:end].strip()
                try:
                    pdf_bytes = base64.b64decode(b64_data)
                    return pdf_bytes, "document.pdf"
                except Exception:
                    pass
        elif isinstance(msg.content, list):
            # Handle multimodal content (OpenAI format)
            for part in msg.content:
                if isinstance(part, dict):
                    # Image URL format with data URL
                    if part.get("type") == "image_url":
                        image_url = part.get("image_url", {})
                        url = image_url.get("url", "")
                        if url.startswith("data:application/pdf;base64,"):
                            b64_data = url.split(",", 1)[1]
                            pdf_bytes = base64.b64decode(b64_data)
                            return pdf_bytes, "document.pdf"
                    # Direct base64 content
                    elif part.get("type") == "file" and part.get("file", {}).get("mime_type") == "application/pdf":
                        b64_data = part["file"].get("data", "")
                        pdf_bytes = base64.b64decode(b64_data)
                        return pdf_bytes, part["file"].get("name", "document.pdf")
    return None


# ============ Task Endpoints ============

@app.post("/convert")
async def convert_pdf_upload(
    file: UploadFile = File(..., description="PDF file to convert"),
    extract_images: bool = Query(False, description="Extract images from PDF"),
    return_json: bool = Query(False, description="Return JSON response instead of plain text"),
    async_mode: bool = Query(False, description="Enable async processing - returns task_id immediately"),
    wait: bool = Query(True, description="Wait for completion (ignored if async_mode=true)"),
    use_cache: bool = Query(True, description="Use content-based cache to skip duplicate files")
):
    """
    Convert a PDF file to Markdown via direct upload.
    
    Options:
    - async_mode=true: Returns task_id immediately, poll GET /tasks/{task_id} for result
    - async_mode=false + wait=true: Waits for conversion (may timeout for large files)
    - async_mode=false + wait=false: Same as async_mode
    - return_json=true: Returns JSON instead of plain text
    - use_cache=true: Returns cached result if file was previously processed
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    
    pdf_bytes = await file.read()
    
    # Compute file hash for content-based deduplication
    file_hash = compute_file_hash(pdf_bytes)
    
    # Check content-based cache
    global content_cache
    if use_cache and file_hash in content_cache:
        cached_task_id = content_cache[file_hash]
        cached_task = tasks.get(cached_task_id) or Task.load_from_cache(cached_task_id)
        
        if cached_task and cached_task.status == TaskStatus.COMPLETED and cached_task.result:
            # Return cached result immediately
            if return_json:
                return {
                    "success": True,
                    "filename": file.filename,
                    "task_id": cached_task_id,
                    "markdown": cached_task.result,
                    "cached": True,
                    "file_hash": file_hash,
                    "message": "File previously processed, returning cached result"
                }
            else:
                return PlainTextResponse(
                    content=cached_task.result, 
                    media_type="text/markdown",
                    headers={"X-Cached": "true", "X-Task-ID": cached_task_id, "X-File-Hash": file_hash}
                )
    
    # Create new task
    task_id = str(uuid.uuid4())[:8]
    task = Task(task_id, file.filename, file_hash)
    tasks[task_id] = task
    task.save_to_cache()
    
    # Update content cache
    content_cache[file_hash] = task_id
    save_content_cache(content_cache)
    
    if async_mode or not wait:
        # Async mode - start background thread
        thread = threading.Thread(
            target=process_task,
            args=(task_id, pdf_bytes, file.filename)
        )
        thread.start()
        
        return {
            "task_id": task_id,
            "status": "pending",
            "file_hash": file_hash,
            "message": "Task created. Poll GET /tasks/{task_id} for result.",
            "poll_url": f"/tasks/{task_id}"
        }
    
    # Sync mode - process immediately (may timeout for large files)
    try:
        task.status = TaskStatus.PROCESSING
        task.started_at = datetime.utcnow()
        task.progress = "Converting..."
        
        markdown_text = convert_pdf_bytes(pdf_bytes, file.filename, task)
        
        task.result = markdown_text
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        task.progress = "Completed"
        task.save_to_cache()
        
        if return_json:
            return {
                "success": True,
                "filename": file.filename,
                "task_id": task_id,
                "markdown": markdown_text,
                "file_hash": file_hash,
                "cached": False
            }
        else:
            return PlainTextResponse(
                content=markdown_text, 
                media_type="text/markdown",
                headers={"X-File-Hash": file_hash, "X-Task-ID": task_id}
            )
            
    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.completed_at = datetime.utcnow()
        task.save_to_cache()
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")


@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """
    Get the status and result of an async conversion task.
    
    Returns:
    - status: pending | processing | completed | failed
    - result: Markdown content (only when completed)
    - error: Error message (only when failed)
    """
    # First check memory
    task = tasks.get(task_id)
    
    # If not in memory, try loading from cache
    if not task:
        task = Task.load_from_cache(task_id)
        if task:
            tasks[task_id] = task
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task.to_dict()


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a completed or failed task."""
    task = tasks.get(task_id)
    
    # Also check cache
    if not task:
        task = Task.load_from_cache(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status == TaskStatus.PROCESSING:
        raise HTTPException(status_code=400, detail="Cannot delete a running task")
    
    # Remove from content cache if present
    global content_cache
    if task.file_hash and task.file_hash in content_cache:
        if content_cache[task.file_hash] == task_id:
            del content_cache[task.file_hash]
            save_content_cache(content_cache)
    
    # Remove from memory
    if task_id in tasks:
        del tasks[task_id]
    
    # Remove from cache
    cache_file = CACHE_DIR / f"{task_id}.json"
    if cache_file.exists():
        cache_file.unlink()
    
    return {"deleted": True, "task_id": task_id}


@app.get("/tasks")
async def list_tasks(
    status: Optional[TaskStatus] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100)
):
    """List all tasks, optionally filtered by status."""
    # Load all cached tasks to ensure we have the latest
    load_tasks_from_cache()
    
    result = []
    for task in sorted(tasks.values(), key=lambda t: t.created_at, reverse=True):
        if status and task.status != status:
            continue
        result.append(task.to_dict())
        if len(result) >= limit:
            break
    return {"count": len(result), "tasks": result}


@app.get("/cache/check")
async def check_content_cache(file_hash: str = Query(..., description="MD5 or SHA256 hash of file content")):
    """
    Check if a file with given hash has been processed before.
    
    Returns cached task info if found, otherwise 404.
    """
    global content_cache
    
    if file_hash not in content_cache:
        raise HTTPException(status_code=404, detail="File not found in cache")
    
    cached_task_id = content_cache[file_hash]
    cached_task = tasks.get(cached_task_id) or Task.load_from_cache(cached_task_id)
    
    if not cached_task:
        # Stale cache entry, remove it
        del content_cache[file_hash]
        save_content_cache(content_cache)
        raise HTTPException(status_code=404, detail="Cached task not found (stale entry removed)")
    
    return {
        "found": True,
        "file_hash": file_hash,
        "task_id": cached_task_id,
        "status": cached_task.status.value,
        "filename": cached_task.filename,
        "completed": cached_task.status == TaskStatus.COMPLETED,
        "result_available": cached_task.result is not None
    }


# ============ OpenAI-compatible endpoint ============

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest = Body(...)):
    """
    OpenAI-compatible chat completions endpoint.
    
    Send PDF as base64 in message content:
    - Format 1: `[PDF_BASE64:...base64_data...:END_PDF]`
    - Format 2: `{"type": "image_url", "image_url": {"url": "data:application/pdf;base64,..."}}`
    
    Set async_mode=true for large files to get a task_id to poll.
    """
    pdf_data = extract_pdf_from_messages(request.messages)
    
    if not pdf_data:
        return ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time())}",
            created=int(time.time()),
            model=request.model,
            choices=[ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content="No PDF found in messages. Please include a PDF file as base64 in your message.\n\n"
                           "Usage:\n"
                           "1. Base64 format: `[PDF_BASE64:<base64_encoded_pdf>:END_PDF]`\n"
                           "2. Data URL: `{\"type\": \"image_url\", \"image_url\": {\"url\": \"data:application/pdf;base64,<data>\"}}`"
                ),
                finish_reason="stop"
            )],
            usage=Usage(prompt_tokens=0, completion_tokens=50, total_tokens=50)
        )
    
    pdf_bytes, filename = pdf_data
    
    # Compute file hash for content-based deduplication
    file_hash = compute_file_hash(pdf_bytes)
    
    # Check content-based cache
    global content_cache
    if file_hash in content_cache:
        cached_task_id = content_cache[file_hash]
        cached_task = tasks.get(cached_task_id) or Task.load_from_cache(cached_task_id)
        
        if cached_task and cached_task.status == TaskStatus.COMPLETED and cached_task.result:
            return ChatCompletionResponse(
                id=f"chatcmpl-{int(time.time())}",
                created=int(time.time()),
                model=request.model,
                choices=[ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=cached_task.result
                    ),
                    finish_reason="stop"
                )],
                usage=Usage(
                    prompt_tokens=len(pdf_bytes) // 4,
                    completion_tokens=len(cached_task.result) // 4,
                    total_tokens=(len(pdf_bytes) + len(cached_task.result)) // 4
                )
            )
    
    # Create task
    task_id = str(uuid.uuid4())[:8]
    task = Task(task_id, filename, file_hash)
    tasks[task_id] = task
    task.save_to_cache()
    
    # Update content cache
    content_cache[file_hash] = task_id
    save_content_cache(content_cache)
    
    if request.async_mode:
        # Async mode - start background thread
        thread = threading.Thread(
            target=process_task,
            args=(task_id, pdf_bytes, filename)
        )
        thread.start()
        
        return ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time())}",
            created=int(time.time()),
            model=request.model,
            choices=[ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content=json.dumps({
                        "async": True,
                        "task_id": task_id,
                        "file_hash": file_hash,
                        "status": "pending",
                        "message": "Task created. Poll GET /tasks/{task_id} for result.",
                        "poll_url": f"/tasks/{task_id}"
                    })
                ),
                finish_reason="stop"
            )],
            usage=Usage(prompt_tokens=len(pdf_bytes) // 4, completion_tokens=10, total_tokens=len(pdf_bytes) // 4 + 10)
        )
    
    # Sync mode - process immediately
    try:
        task.status = TaskStatus.PROCESSING
        task.started_at = datetime.utcnow()
        task.progress = "Converting..."
        
        markdown_text = convert_pdf_bytes(pdf_bytes, filename, task)
        
        task.result = markdown_text
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        task.progress = "Completed"
        task.save_to_cache()
        
        return ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time())}",
            created=int(time.time()),
            model=request.model,
            choices=[ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content=markdown_text
                ),
                finish_reason="stop"
            )],
            usage=Usage(
                prompt_tokens=len(pdf_bytes) // 4,
                completion_tokens=len(markdown_text) // 4,
                total_tokens=(len(pdf_bytes) + len(markdown_text)) // 4
            )
        )
    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.completed_at = datetime.utcnow()
        task.save_to_cache()
        raise HTTPException(status_code=500, detail=f"PDF conversion failed: {str(e)}")


@app.get("/v1/models")
async def list_models():
    """List available models (OpenAI-compatible)."""
    return {
        "object": "list",
        "data": [
            {
                "id": "pdf2md",
                "object": "model",
                "created": 1700000000,
                "owned_by": "pdf-to-markdown",
                "permission": [],
                "root": "pdf2md",
                "parent": None,
            }
        ]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    global content_cache
    return {
        "status": "ok", 
        "service": "pdf-to-markdown",
        "version": "2.0.2",
        "active_tasks": len([t for t in tasks.values() if t.status == TaskStatus.PROCESSING]),
        "total_tasks": len(tasks),
        "content_cached_files": len(content_cache),
        "cache_dir": str(CACHE_DIR)
    }


@app.get("/")
async def root():
    """Root endpoint with API info."""
    # Get actual host and port from environment or use defaults
    host = os.environ.get("PDF2MD_HOST", "localhost")
    port = os.environ.get("PDF2MD_PORT", "9999")
    base_url = f"http://{host}:{port}"
    
    return {
        "service": "PDF to Markdown API",
        "version": "2.0.2",
        "features": ["async_processing", "openai_compatible", "persistent_cache", "content_based_deduplication"],
        "cache_dir": str(CACHE_DIR),
        "endpoints": {
            "POST /convert": "Convert PDF (use ?async_mode=true for large files, use_cache=false to skip cache)",
            "GET /tasks/{task_id}": "Get async task status and result",
            "GET /tasks": "List all tasks",
            "DELETE /tasks/{task_id}": "Delete completed task",
            "GET /cache/check": "Check if file hash exists in cache",
            "POST /v1/chat/completions": "OpenAI-compatible endpoint",
            "GET /v1/models": "List available models",
            "GET /health": "Health check"
        },
        "usage": {
            "sync": {
                "description": "Small files - waits for result",
                "example": f"curl -X POST {base_url}/convert -F 'file=@doc.pdf'"
            },
            "async": {
                "description": "Large files - returns task_id immediately",
                "steps": [
                    f"1. curl -X POST '{base_url}/convert?async_mode=true' -F 'file=@large.pdf'",
                    "2. Returns: {\"task_id\": \"abc123\", \"file_hash\": \"md5_hash\", \"status\": \"pending\"}",
                    f"3. curl {base_url}/tasks/abc123",
                    "4. Poll until status=\"completed\", then get result"
                ]
            },
            "cache": {
                "description": "Content-based deduplication - same file returns cached result",
                "check": f"curl {base_url}/cache/check?file_hash=<md5_hash>"
            }
        }
    }


@app.get("/llm")
async def llm_usage_guide():
    """
    LLM Usage Guide - Instructions for other AI assistants.
    
    Access this endpoint to learn how to use the PDF to Markdown API.
    """
    # Get actual host and port from environment or use defaults
    host = os.environ.get("PDF2MD_HOST", "localhost")
    port = os.environ.get("PDF2MD_PORT", "9999")
    base_url = f"http://{host}:{port}"
    
    return {
        "service": "PDF to Markdown API",
        "version": "2.0.2",
        "description": "Convert PDF documents to Markdown format with AI-powered layout detection. Supports async processing for large files. Results are cached to disk for persistence. Content-based deduplication prevents re-processing identical files.",
        "base_url": base_url,
        "cache_dir": str(CACHE_DIR),
        
        "quick_start": {
            "sync_small_files": f"curl -X POST {base_url}/convert -F 'file=@doc.pdf' -o output.md",
            "async_large_files": [
                f"1. curl -X POST '{base_url}/convert?async_mode=true' -F 'file=@large.pdf'",
                "2. Returns: {\"task_id\": \"xxx\", \"file_hash\": \"md5_hash\", \"status\": \"pending\"}",
                f"3. curl {base_url}/tasks/xxx",
                "4. Poll until status=\"completed\", then use result field"
            ],
            "check_cache": f"curl {base_url}/cache/check?file_hash=<md5_hash>"
        },
        
        "endpoints": {
            "/convert": {
                "method": "POST",
                "description": "Upload PDF for conversion",
                "params": {
                    "async_mode": "true = return task_id immediately, false = wait for result (may timeout)",
                    "return_json": "true = return JSON, false = return plain text",
                    "use_cache": "true = check content hash for deduplication (default), false = always process"
                },
                "example_sync": f"curl -X POST {base_url}/convert -F 'file=@doc.pdf' -o output.md",
                "example_async": f"curl -X POST '{base_url}/convert?async_mode=true' -F 'file=@large.pdf'",
                "example_no_cache": f"curl -X POST '{base_url}/convert?use_cache=false' -F 'file=@doc.pdf'"
            },
            "/tasks/{task_id}": {
                "method": "GET",
                "description": "Get async task status and result",
                "returns": {
                    "status": "pending | processing | completed | failed",
                    "progress": "Current progress description",
                    "result": "Markdown content (only when completed)",
                    "error": "Error message (only when failed)",
                    "elapsed_seconds": "Processing time in seconds",
                    "file_hash": "MD5 hash of file content"
                }
            },
            "/tasks": {
                "method": "GET",
                "description": "List all tasks",
                "params": {"status": "Filter by status", "limit": "Max results"}
            },
            "/cache/check": {
                "method": "GET",
                "description": "Check if a file with given hash has been processed",
                "params": {"file_hash": "MD5 or SHA256 hash of file content"},
                "returns": {
                    "found": "true if file was previously processed",
                    "task_id": "ID of the cached task",
                    "status": "Task status",
                    "result_available": "true if result is ready"
                }
            },
            "/v1/chat/completions": {
                "method": "POST",
                "description": "OpenAI-compatible endpoint",
                "note": "Send PDF as base64 in message content: [PDF_BASE64:<data>:END_PDF]",
                "async_mode": "Add \"async_mode\": true to request body for async processing"
            },
            "/v1/models": {
                "method": "GET",
                "description": "List available models (OpenAI-compatible)"
            },
            "/health": {
                "method": "GET",
                "description": "Health check with task statistics and cache info"
            }
        },
        
        "content_based_cache": {
            "description": "Files are identified by MD5 hash of content, not filename",
            "benefits": [
                "Same file with different names returns cached result instantly",
                "Duplicate uploads are automatically deduplicated",
                "No wasted processing on identical files"
            ],
            "compute_hash": "md5sum file.pdf  # or use any MD5 tool",
            "check_before_upload": f"curl {base_url}/cache/check?file_hash=<hash>  # Returns 404 if not cached"
        },
        
        "integration_examples": {
            "python_async": {
                "description": "Python async upload with polling",
                "code": f'''
import requests
import time
import hashlib

# Compute file hash first
with open("large.pdf", "rb") as f:
    file_bytes = f.read()
    file_hash = hashlib.md5(file_bytes).hexdigest()

# Check if already cached
cache_check = requests.get(f"{base_url}/cache/check?file_hash={{file_hash}}")
if cache_check.status_code == 200:
    print("File already processed, getting cached result...")
    task_id = cache_check.json()["task_id"]
else:
    # Upload PDF
    with open("large.pdf", "rb") as f:
        resp = requests.post(
            "{base_url}/convert",
            params={{"async_mode": True}},
            files={{"file": f}}
        )
    task_id = resp.json()["task_id"]
    print(f"Task created: {{task_id}}")

# Poll for result
while True:
    status = requests.get(f"{base_url}/tasks/{{task_id}}").json()
    print(f"Status: {{status['status']}}, Progress: {{status['progress']}}")
    
    if status["status"] == "completed":
        with open("output.md", "w") as f:
            f.write(status["result"])
        print("Saved to output.md")
        break
    elif status["status"] == "failed":
        print(f"Error: {{status['error']}}")
        break
    
    time.sleep(10)  # Poll every 10 seconds
'''
            },
            "curl_async": {
                "description": "Bash/curl async workflow with cache check",
                "code": f'''
# Compute file hash
FILE_HASH=$(md5sum large.pdf | cut -d' ' -f1)
echo "File hash: $FILE_HASH"

# Check cache first
CACHE_RESULT=$(curl -s "{base_url}/cache/check?file_hash=$FILE_HASH")
if echo "$CACHE_RESULT" | jq -e '.found' > /dev/null 2>&1; then
    echo "File already processed!"
    TASK_ID=$(echo "$CACHE_RESULT" | jq -r '.task_id')
else
    # Upload and get task_id
    TASK_ID=$(curl -s -X POST '{base_url}/convert?async_mode=true' \\
      -F 'file=@large.pdf' | jq -r '.task_id')
    echo "Task ID: $TASK_ID"
fi

# Poll until completed
while true; do
  STATUS=$(curl -s "{base_url}/tasks/$TASK_ID")
  echo "$STATUS" | jq -c '{{status, progress}}'
  
  if [ "$(echo "$STATUS" | jq -r '.status')" = "completed" ]; then
    echo "$STATUS" | jq -r '.result' > output.md
    echo "Saved to output.md"
    break
  elif [ "$(echo "$STATUS" | jq -r '.status')" = "failed" ]; then
    echo "Error: $(echo "$STATUS" | jq -r '.error')"
    break
  fi
  
  sleep 10
done
'''
            }
        },
        
        "tips": [
            "Large files (>10 pages) MUST use async_mode=true to avoid timeout",
            "Typical processing time: ~8 seconds per page",
            "Poll interval: 5-10 seconds recommended",
            "Task results are cached to disk and survive service restarts",
            "Content-based deduplication: same file content returns cached result regardless of filename",
            "Use /cache/check endpoint to verify if file was processed before uploading",
            "Supports Chinese and other non-English PDFs",
            "Tables are converted to Markdown tables",
            "Images are referenced as ![](_page_X_Picture_Y.jpeg)"
        ],
        
        "error_handling": {
            "timeout": "Use async_mode=true - sync mode may timeout for large files",
            "task_not_found": "Task expired or invalid task_id (check cache_dir)",
            "conversion_failed": "Check if PDF is corrupted or password-protected",
            "cache_miss": "File not previously processed, upload required"
        }
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="PDF to Markdown API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9999, help="Port to bind to")
    args = parser.parse_args()
    
    # Set environment variables for other endpoints to use
    os.environ["PDF2MD_HOST"] = args.host
    os.environ["PDF2MD_PORT"] = str(args.port)
    
    print(f"🚀 Starting PDF to Markdown API v2.0.2 on {args.host}:{args.port}")
    print(f"📖 OpenAI-compatible: POST http://{args.host}:{args.port}/v1/chat/completions")
    print(f"📄 Direct upload: POST http://{args.host}:{args.port}/convert")
    print(f"⚡ Async mode: POST http://{args.host}:{args.port}/convert?async_mode=true")
    print(f"💾 Cache check: GET http://{args.host}:{args.port}/cache/check?file_hash=<hash>")
    print(f"🤖 LLM usage guide: GET http://{args.host}:{args.port}/llm")
    print(f"💾 Cache directory: {CACHE_DIR}")
    print(f"🔍 Content-based deduplication: ENABLED (MD5)")
    uvicorn.run(app, host=args.host, port=args.port)
