# PDF to Markdown Docker Deployment

## Service Information

| Property | Value |
|----------|-------|
| **Service Name** | pdf2md-api |
| **Image** | pdf2md:latest (custom build) |
| **Port** | **21212** (host) → 9999 (container) |
| **Base Image** | python:3.11-slim |
| **Model Cache** | ~/.cache/huggingface |
| **Status** | 🟢 Running |

## Quick Start

```bash
cd ~/docker/pdf2md
docker compose up -d
```

## API Endpoint

**Base URL**: `http://localhost:21212`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/convert` | POST | Convert PDF (sync/async) |
| `/tasks/{task_id}` | GET | Get task status |
| `/tasks` | GET | List all tasks |
| `/health` | GET | Health check |

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

# Check status
curl http://localhost:21212/tasks/{task_id}
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
```

## Notes
- First run downloads model weights (~1-2GB) to HF cache
- Typical speed: ~8 seconds per page
- Supports OCR for scanned documents
- Deployed: 2026-03-31
