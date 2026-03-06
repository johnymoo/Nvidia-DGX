# PDF to Markdown API

🦞 **小龙虾专用 PDF 转 Markdown 服务**

基于 [marker-pdf](https://github.com/VikParuchuri/marker) 的 AI 驱动 PDF 转 Markdown API，支持 OpenAI 兼容接口。

## 功能特点

- ✅ **AI 布局识别** - 自动识别标题、表格、列表、代码块
- ✅ **中文支持** - 完美支持中文 PDF
- ✅ **表格转换** - 自动转换为 Markdown 表格
- ✅ **OpenAI 兼容** - 像调用 GPT 一样使用
- ✅ **REST API** - 直接上传转换
- ✅ **MCP Server** - Model Context Protocol 支持

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/ShiliIntelligence/pdf-to-markdown-api.git
cd pdf-to-markdown-api

# 创建虚拟环境并安装依赖
uv venv
source .venv/bin/activate
uv pip install marker-pdf fastapi uvicorn python-multipart
```

### 启动服务

```bash
python scripts/api_server.py --host 0.0.0.0 --port 9999
```

首次运行会自动下载 AI 模型（约 3GB）。

## 使用方法

### 方式 1: OpenAI 兼容接口（推荐）

完全兼容 OpenAI Chat Completions API：

```python
import base64
import openai

client = openai.OpenAI(
    base_url="http://localhost:9999/v1",
    api_key="dummy"
)

# 读取 PDF 并转换为 base64
with open("document.pdf", "rb") as f:
    pdf_b64 = base64.b64encode(f.read()).decode()

# 调用 API
response = client.chat.completions.create(
    model="pdf2md",
    messages=[{
        "role": "user",
        "content": f"[PDF_BASE64:{pdf_b64}:END_PDF]"
    }]
)

print(response.choices[0].message.content)
```

### 方式 2: 直接上传

```bash
# 直接上传 PDF 文件
curl -X POST http://localhost:9999/convert \
  -F "file=@document.pdf" \
  -o output.md

# 返回 JSON 格式
curl -X POST "http://localhost:9999/convert?return_json=true" \
  -F "file=@document.pdf"
```

### 方式 3: 命令行工具

```bash
python scripts/convert.py input.pdf -o output.md

# 批量转换
python scripts/convert.py *.pdf -o ./output/

# 提取图片
python scripts/convert.py input.pdf -o output.md --images
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | OpenAI 兼容接口 |
| `/v1/models` | GET | 列出可用模型 |
| `/convert` | POST | 直接上传转换 |
| `/llm` | GET | LLM 使用指南 |
| `/health` | GET | 健康检查 |

## LLM 集成指南

其他 AI 助手访问 `/llm` 端点获取使用说明：

```bash
curl http://localhost:9999/llm
```

返回完整的集成示例和 API 文档。

## MCP Server

支持 Model Context Protocol：

```bash
python scripts/mcp_server.py
```

工具列表：
- `pdf_to_markdown` - 单文件转换
- `pdf_batch_convert` - 批量转换

## 项目结构

```
pdf-to-markdown-api/
├── README.md
├── pyproject.toml
├── scripts/
│   ├── api_server.py      # REST API 服务
│   ├── convert.py         # CLI 转换工具
│   └── mcp_server.py      # MCP Server
├── docs/
│   └── DEPLOYMENT.md      # 部署文档
└── examples/
    └── example_usage.py   # 使用示例
```

## 部署

### Docker（推荐）

```bash
docker build -t pdf2md-api .
docker run -d -p 9999:9999 -v ~/.cache/datalab:/root/.cache/datalab pdf2md-api
```

### Systemd

```bash
# 创建服务文件
sudo tee /etc/systemd/system/pdf2md-api.service << EOF
[Unit]
Description=PDF to Markdown API
After=network.target

[Service]
Type=simple
User=chriswang
WorkingDirectory=/home/chriswang/project/pdf-to-markdown-api
ExecStart=/home/chriswang/project/pdf-to-markdown-api/.venv/bin/python scripts/api_server.py --host 0.0.0.0 --port 9999
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
sudo systemctl enable pdf2md-api
sudo systemctl start pdf2md-api
```

## 性能

- **模型缓存**: 首次下载后模型缓存到 `~/.cache/datalab/models/`
- **转换速度**: 约 2-5 秒/页（取决于复杂度）
- **内存占用**: 约 4-6GB（加载模型后）

## 常见问题

### Q: 支持哪些 PDF 类型？
A: 支持文本 PDF、扫描 PDF（OCR）、表格 PDF、学术论文、技术文档等。

### Q: 转换质量如何？
A: 使用 AI 布局识别，对复杂排版、多栏、表格有很好的识别效果。

### Q: 可以商用吗？
A: marker-pdf 采用 GPL-3.0 许可证，商用需遵守许可证条款。

## 致谢

- [marker-pdf](https://github.com/VikParuchuri/marker) - 核心转换引擎
- [surya-ocr](https://github.com/VikParuchuri/surya) - OCR 引擎

## License

GPL-3.0

---

🦞 **Shili Intelligence - 让小龙虾们更高效地处理文档**
