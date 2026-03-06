# PDF to Markdown 服务搭建过程

## 📋 项目概述

基于 [marker-pdf](https://github.com/VikParuchuri/marker) 的 AI 驱动 PDF 转 Markdown 服务，提供 OpenAI 兼容的 REST API。

**服务端口**: `9999`  
**API 地址**: `http://<host>:9999`  
**核心功能**: AI 布局识别、中文支持、表格转换、OpenAI 兼容接口

---

## 🏗️ 搭建过程

### 1. 环境准备

```bash
# 基础依赖
- Python 3.12+
- Docker (可选，用于容器化部署)
- 约 6GB 磁盘空间 (模型缓存)
```

### 2. 创建项目结构

```
pdf-to-markdown/
├── README.md              # 项目说明
├── Dockerfile             # Docker 镜像定义
├── docker-compose.yml     # Docker Compose 配置
├── pyproject.toml         # Python 项目配置
├── .gitignore            # Git 忽略规则
├── scripts/
│   ├── api_server.py     # REST API 服务 (FastAPI)
│   ├── convert.py        # CLI 转换工具
│   └── mcp_server.py     # MCP Server
├── docs/
│   └── DEPLOYMENT.md     # 部署文档
└── examples/
    └── example_usage.py  # 使用示例
```

### 3. 核心依赖安装

```bash
pip install marker-pdf fastapi uvicorn python-multipart
```

**首次运行自动下载模型** (约 3GB):
- `layout/` - 布局识别模型 (1.4GB)
- `text_recognition/` - 文字识别 (1.4GB)
- `text_detection/` - 文字检测 (74MB)
- `table_recognition/` - 表格识别 (202MB)
- `ocr_error_detection/` - OCR 错误检测 (258MB)

模型缓存: `~/.cache/datalab/models/`

### 4. API 服务实现

#### 4.1 OpenAI 兼容接口

```python
POST /v1/chat/completions

# 请求格式
{
  "model": "pdf2md",
  "messages": [{
    "role": "user",
    "content": "[PDF_BASE64:<base64_data>:END_PDF]"
  }]
}

# 响应格式 (标准 OpenAI ChatCompletion)
{
  "id": "chatcmpl-xxx",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "<markdown_content>"
    }
  }]
}
```

#### 4.2 直接上传接口

```python
POST /convert
Content-Type: multipart/form-data

file: <PDF file>
```

#### 4.3 其他端点

| 端点 | 说明 |
|------|------|
| `GET /v1/models` | 列出可用模型 |
| `GET /health` | 健康检查 |
| `GET /llm` | LLM 使用指南 |

### 5. Docker 部署

```bash
# 构建镜像
docker build -t pdf2md-api .

# 运行服务
docker run -d -p 9999:9999 \
  -v model-cache:/root/.cache/datalab \
  pdf2md-api
```

**docker-compose.yml** 关键配置:
- 端口映射: `9999:9999`
- 模型缓存卷: `model-cache`
- 健康检查: 30s 间隔
- 自动重启: `unless-stopped`

### 6. 启动服务

```bash
# Docker 方式 (推荐)
docker-compose up -d

# 直接运行
python scripts/api_server.py --host 0.0.0.0 --port 9999
```

服务启动后:
- 首次需下载模型 (5-10 分钟)
- 健康检查: `curl http://localhost:9999/health`

---

## 🔧 使用方法

### OpenAI SDK 方式

```python
import base64
import openai

client = openai.OpenAI(
    base_url="http://localhost:9999/v1",
    api_key="dummy"
)

with open("doc.pdf", "rb") as f:
    pdf_b64 = base64.b64encode(f.read()).decode()

response = client.chat.completions.create(
    model="pdf2md",
    messages=[{
        "role": "user",
        "content": f"[PDF_BASE64:{pdf_b64}:END_PDF]"
    }]
)

print(response.choices[0].message.content)
```

### cURL 直接上传

```bash
curl -X POST http://localhost:9999/convert \
  -F "file=@document.pdf" \
  -o output.md
```

### CLI 工具

```bash
python scripts/convert.py input.pdf -o output.md

# 批量处理
python scripts/convert.py *.pdf -o ./output/

# 提取图片
python scripts/convert.py input.pdf -o output.md --images
```

---

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| 转换速度 | 2-5 秒/页 |
| 内存占用 | 4-6GB (模型加载后) |
| 模型大小 | ~3GB |
| 支持语言 | 中文、英文等 |

---

## 🎯 技术亮点

1. **AI 布局识别**: 自动识别标题、表格、列表、代码块
2. **OpenAI 兼容**: 无缝集成现有 AI 工作流
3. **多语言支持**: 完美支持中文 PDF
4. **表格转换**: 自动转为 Markdown 表格
5. **MCP 协议**: 支持 Model Context Protocol
6. **容器化部署**: Docker 一键部署

---

## 📁 工程文件清单

| 文件 | 说明 |
|------|------|
| `README.md` | 项目说明文档 |
| `Dockerfile` | Docker 镜像构建 |
| `docker-compose.yml` | Docker Compose 配置 |
| `pyproject.toml` | Python 项目配置 |
| `.gitignore` | Git 忽略规则 |
| `scripts/api_server.py` | FastAPI REST 服务 |
| `scripts/convert.py` | CLI 转换工具 |
| `scripts/mcp_server.py` | MCP Server |
| `docs/DEPLOYMENT.md` | 部署文档 |
| `examples/example_usage.py` | 使用示例 |

---

## 🦞 备注

- 服务绑定端口: `9999`
- 模型自动缓存在: `~/.cache/datalab/`
- 其他 AI 助手可通过 `GET /llm` 获取使用说明

搭建日期: 2026-03-06
搭建环境: GB10 (DGX Spark) / Ubuntu / Docker
