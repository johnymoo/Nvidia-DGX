# Nemotron Chat Web Interface

A simple web interface for chatting with Nemotron-3-Super-120B model with real-time system stats.

## Requirements

- Python 3.8+
- Flask
- psutil
- requests

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Start the model server

First, ensure the Nemotron model is running:

```bash
cd ..
./deploy.sh
```

### Start the web interface

```bash
python3 app.py
```

Or with custom settings:

```bash
MODEL_API=http://localhost:8090 PORT=5000 python3 app.py
```

### Access the interface

Open your browser and navigate to:

- Local: http://localhost:5000
- Network: http://<your-ip>:5000

## Features

- Chat with Nemotron-3-Super-120B model
- Real-time CPU usage display
- Real-time memory usage display
- GPU memory usage (for GB10 unified memory)
- Dark theme UI
- Conversation history

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main chat interface |
| `/api/stats` | GET | System stats (CPU, Memory, GPU) |
| `/api/chat` | POST | Chat with the model |
| `/api/models` | GET | Available models |
| `/api/health` | GET | Health check |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_API` | `http://127.0.0.1:8090` | Model API URL |
| `PORT` | `5000` | Server port |