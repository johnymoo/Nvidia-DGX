FROM python:3.12-slim

LABEL maintainer="Shili Intelligence"
LABEL description="PDF to Markdown API with OpenAI-compatible interface"

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install --no-cache-dir \
    marker-pdf \
    fastapi \
    uvicorn \
    python-multipart

# 复制脚本
COPY scripts/ /app/scripts/

# 创建模型缓存目录
RUN mkdir -p /root/.cache/datalab/models

# 暴露端口
EXPOSE 9999

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:9999/health || exit 1

# 启动服务
CMD ["python", "scripts/api_server.py", "--host", "0.0.0.0", "--port", "9999"]
