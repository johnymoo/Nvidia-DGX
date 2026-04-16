# PDF to Markdown Docker Deployment

## Service Information

| Property | Value |
|----------|-------|
| **Service Name** | pdf2md-api |
| **Image** | pdf2md:latest (custom build) |
| **Port** | **21212** (host) → 9999 (container) |
| **Base Image** | python:3.11-slim |
| **Model Cache** | ~/.cache/huggingface, ~/.cache/datalab |
| **Task Cache** | /workspace/pdf2md_cache/ |
| **Status** | 🟢 Running |

## Features

- ✅ **PDF to Markdown** - AI-powered layout detection using marker-pdf
- ✅ **Async Processing** - Background tasks for large files
- ✅ **GPU Acceleration** - CUDA support on GB10
- ✅ **Persistent Cache** - Task results survive service restarts
- ✅ **Content-Based Deduplication** - Same file content returns cached result instantly
- ✅ **OpenAI-Compatible API** - `/v1/chat/completions` endpoint

## Quick Start

```bash
cd ~/docker/pdf2md
docker compose up -d
```

## API Endpoints

**Base URL**: `http://localhost:21212`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/convert` | POST | Convert PDF (sync/async) |
| `/tasks/{task_id}` | GET | Get task status & result |
| `/tasks` | GET | List all tasks |
| `/cache/check` | GET | Check if file hash exists in cache |
| `/health` | GET | Health check |
| `/llm` | GET | LLM usage guide |
| `/v1/chat/completions` | POST | OpenAI-compatible endpoint |

## Usage Examples

### Health Check
```bash
curl http://localhost:21212/health
```

### Sync Conversion
```bash
curl -X POST http://localhost:21212/convert \
  -F "file=@document.pdf" \
  -o output.md
```

### Async Conversion (Large Files)
```bash
# Submit task
curl -X POST 'http://localhost:21212/convert?async_mode=true' \
  -F 'file=@large.pdf'
# Returns: {"task_id": "xxx", "file_hash": "md5_hash", "status": "pending"}

# Poll for result
curl http://localhost:21212/tasks/{task_id}
```

### Content-Based Cache (Deduplication)

The service automatically computes MD5 hash of file content to detect duplicates:

```bash
# First upload - processes the file
curl -X POST http://localhost:21212/convert -F 'file=@document.pdf'
# Returns: {"cached": false, ...}

# Second upload (same file content, any filename) - returns cached result instantly
curl -X POST http://localhost:21212/convert -F 'file=@renamed.pdf'
# Returns: {"cached": true, "message": "File previously processed, returning cached result"}

# Check cache before uploading
curl http://localhost:21212/cache/check?file_hash=<md5_hash>

# Force re-processing (skip cache)
curl -X POST 'http://localhost:21212/convert?use_cache=false' -F 'file=@document.pdf'
```

### Compute File Hash
```bash
# Get MD5 hash of file
md5sum document.pdf
# or
md5 -q document.pdf  # macOS
```

## Management Commands

```bash
# Start service
cd ~/docker/pdf2md && docker compose up -d

# Stop service
docker compose down

# View logs
docker logs -f pdf2md-api

# Rebuild
docker compose build --no-cache

# Restart with updates
docker compose down && docker compose up -d --build
```

## Configuration

Environment variables in `docker-compose.yml`:

```yaml
environment:
  - PYTHONUNBUFFERED=1
  - HF_HOME=/root/.cache/huggingface
  - CUDA_VISIBLE_DEVICES=0
  - PDF2MD_CACHE_DIR=/workspace/pdf2md_cache
```

## Performance

- **Model Loading**: ~30-60s on first startup (downloads ~1-2GB)
- **Processing Speed**: ~8 seconds per page (GPU accelerated)
- **Cache Hit**: Instant return (< 10ms)
- **Supported**: Multi-page PDFs, scanned documents (OCR), tables

## Update History

| Date | Version | Changes |
|------|---------|---------|
| 2026-04-16 | 2.0.2 | Add content-based deduplication (MD5 cache) |
| 2026-04-14 | 2.0.1 | Add persistent cache, fix /llm port info |
| 2026-04-14 | 2.0.0 | Add GPU support, fix datalab cache mount |
| 2026-03-31 | 1.0.0 | Initial deployment |

## Notes

- First run downloads model weights to HF cache (~1-2GB)
- Task results are cached to `/workspace/pdf2md_cache/` and survive restarts
- Content-based deduplication prevents re-processing identical files
- GPU acceleration requires NVIDIA runtime (`--gpus all`)
