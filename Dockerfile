FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including CUDA libraries
RUN apt-get update && apt-get install -y \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install marker with CUDA support
RUN pip install --no-cache-dir marker-pdf[cuda]

# Copy application code
COPY api_server.py .

# Expose port
EXPOSE 9999

# Run server
CMD ["python", "api_server.py", "--host", "0.0.0.0", "--port", "9999"]
