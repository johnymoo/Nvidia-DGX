#!/usr/bin/env python3
"""
Nemotron Chat Web Interface

A simple web interface for chatting with Nemotron-3-Super-120B model
with real-time system stats (CPU, Memory, GPU).

Usage:
    python3 app.py

Environment Variables:
    MODEL_API: Model API URL (default: http://127.0.0.1:8090)
    PORT: Server port (default: 5000)
"""

import os
import psutil
from flask import Flask, render_template, request, jsonify, Response
import requests

app = Flask(__name__)

# Configuration
MODEL_API = os.environ.get("MODEL_API", "http://127.0.0.1:8090")
SERVER_PORT = int(os.environ.get("PORT", "5000"))


# Enable CORS for all routes
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/api/stats")
def get_stats():
    """Get system stats (CPU, memory, GPU)."""
    # Use interval=None for non-blocking call (returns % since last call)
    cpu_percent = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    
    # Try to get GPU memory from nvidia-smi (GB10 has unified memory)
    gpu_memory_used = "N/A"
    gpu_memory_total = str(int(memory.total / (1024**2)))  # Total system memory as GPU total
    try:
        import subprocess
        # Use query-compute-apps for GB10 unified memory
        result = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=used_memory", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            # Sum all process GPU memory
            total_gpu_mem = sum(int(x.strip()) for x in result.stdout.strip().split('\n') if x.strip().isdigit())
            gpu_memory_used = str(total_gpu_mem)
    except Exception:
        pass
    
    return jsonify({
        "cpu_percent": cpu_percent,
        "memory_percent": memory.percent,
        "memory_used_gb": round(memory.used / (1024**3), 1),
        "memory_total_gb": round(memory.total / (1024**3), 1),
        "gpu_memory_used_mb": gpu_memory_used,
        "gpu_memory_total_mb": gpu_memory_total
    })


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    """Proxy chat requests to the model API."""
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"})
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        # Forward the request to the model API
        response = requests.post(
            f"{MODEL_API}/v1/chat/completions",
            json=data,
            stream=data.get("stream", False),
            timeout=300
        )
        
        if response.status_code != 200:
            return jsonify({"error": f"Model API error: {response.status_code}"}), 500
        
        if data.get("stream", False):
            # Stream the response
            def generate():
                for chunk in response.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
            return Response(generate(), content_type=response.headers.get("content-type"))
        else:
            return jsonify(response.json())
    
    except requests.exceptions.Timeout:
        return jsonify({"error": "Model API timeout"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Cannot connect to model API (is llama-server running?)"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/models")
def models():
    """Get available models."""
    try:
        response = requests.get(f"{MODEL_API}/v1/models", timeout=10)
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "model_api": MODEL_API})


if __name__ == "__main__":
    print(f"Starting Nemotron Chat on port {SERVER_PORT}")
    print(f"Model API: {MODEL_API}")
    app.run(host="0.0.0.0", port=SERVER_PORT, debug=False)