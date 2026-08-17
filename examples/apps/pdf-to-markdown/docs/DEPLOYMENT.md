# 部署文档

## 系统要求

- Python 3.10+
- 4GB+ 可用内存
- 10GB+ 磁盘空间（用于模型缓存）

## 安装步骤

### 1. 克隆仓库

```bash
git clone https://github.com/ShiliIntelligence/pdf-to-markdown-api.git
cd pdf-to-markdown-api
```

### 2. 创建虚拟环境

```bash
uv venv
source .venv/bin/activate  # Linux/macOS
# 或
.venv\Scripts\activate  # Windows
```

### 3. 安装依赖

```bash
uv pip install marker-pdf fastapi uvicorn python-multipart
```

### 4. 启动服务

```bash
python scripts/api_server.py --host 0.0.0.0 --port 9999
```

首次运行会自动下载模型（约 3GB），请耐心等待。

## 部署方式

### Docker

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install marker-pdf fastapi uvicorn python-multipart

COPY scripts/ /app/scripts/

EXPOSE 9999

CMD ["python", "scripts/api_server.py", "--host", "0.0.0.0", "--port", "9999"]
```

构建和运行：

```bash
docker build -t pdf2md-api .
docker run -d -p 9999:9999 -v ~/.cache/datalab:/root/.cache/datalab pdf2md-api
```

### Systemd 服务

创建服务文件：

```bash
sudo nano /etc/systemd/system/pdf2md-api.service
```

内容：

```ini
[Unit]
Description=PDF to Markdown API
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/project/pdf-to-markdown-api
ExecStart=/home/YOUR_USERNAME/project/pdf-to-markdown-api/.venv/bin/python scripts/api_server.py --host 0.0.0.0 --port 9999
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable pdf2md-api
sudo systemctl start pdf2md-api
sudo systemctl status pdf2md-api
```

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name pdf2md.yourdomain.com;

    client_max_body_size 50M;  # 允许大文件上传

    location / {
        proxy_pass http://127.0.0.1:9999;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 增加超时时间（PDF 转换可能需要较长时间）
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

## 模型缓存

模型会缓存到 `~/.cache/datalab/models/`，包括：

- `layout/` - 布局识别模型（~1.4GB）
- `text_recognition/` - 文字识别模型（~1.4GB）
- `text_detection/` - 文字检测模型（~74MB）
- `table_recognition/` - 表格识别模型（~202MB）
- `ocr_error_detection/` - OCR 错误检测模型（~258MB）

**总计约 3.3GB**

## 性能调优

### GPU 加速

如果有 NVIDIA GPU，安装 CUDA 版本的 PyTorch：

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

### 多进程

使用 Gunicorn 运行多个工作进程：

```bash
pip install gunicorn
gunicorn scripts.api_server:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:9999
```

注意：每个进程都会加载模型，注意内存占用。

## 监控

### 健康检查

```bash
curl http://localhost:9999/health
```

### 日志

查看日志：

```bash
# Systemd
sudo journalctl -u pdf2md-api -f

# Docker
docker logs -f <container_id>
```

## 故障排除

### 内存不足

如果遇到 OOM 错误：
1. 减少并发请求数
2. 使用更小的批次处理
3. 增加系统交换空间

### 模型下载失败

如果模型下载失败：
1. 检查网络连接
2. 手动下载模型到 `~/.cache/datalab/models/`
3. 使用代理或镜像

### 转换质量差

如果转换质量不理想：
1. 确保 PDF 文件清晰
2. 检查是否为扫描件（需要 OCR）
3. 尝试调整 marker-pdf 参数
