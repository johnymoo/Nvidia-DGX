#!/usr/bin/env python3
"""PDF to Markdown REST API Server with LLM-compatible endpoint."""

import tempfile
import base64
import time
import json
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Body
from fastapi.responses import PlainTextResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

app = FastAPI(
    title="PDF to Markdown API",
    description="Convert PDF documents to Markdown using AI-powered layout detection. Compatible with OpenAI API format.",
    version="1.0.0"
)


# ============ OpenAI-compatible models ============

class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "pdf2md"
    messages: List[ChatMessage]
    temperature: float = Field(default=0.7, ge=0, le=2)
    stream: bool = False


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


def get_converter():
    """Get or create the PDF converter instance."""
    global _converter
    if _converter is None:
        _converter = PdfConverter(create_model_dict())
    return _converter


def convert_pdf_bytes(pdf_bytes: bytes, filename: str = "document.pdf") -> str:
    """Convert PDF bytes to Markdown text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        pdf_path = tmpdir_path / filename
        pdf_path.write_bytes(pdf_bytes)
        
        converter = get_converter()
        rendered = converter(str(pdf_path))
        text, _, _ = text_from_rendered(rendered)
        return text


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


# ============ OpenAI-compatible endpoint ============

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest = Body(...)):
    """
    OpenAI-compatible chat completions endpoint.
    
    Send PDF as base64 in message content:
    - Format 1: `[PDF_BASE64:...base64_data...:END_PDF]`
    - Format 2: `{"type": "image_url", "image_url": {"url": "data:application/pdf;base64,..."}}`
    
    Returns converted Markdown in assistant message.
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
    
    try:
        markdown_text = convert_pdf_bytes(pdf_bytes, filename)
        
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


# ============ Direct PDF upload endpoint ============

@app.post("/convert")
async def convert_pdf_upload(
    file: UploadFile = File(..., description="PDF file to convert"),
    extract_images: bool = Query(False, description="Extract images from PDF"),
    return_json: bool = Query(False, description="Return JSON response instead of plain text")
):
    """
    Convert a PDF file to Markdown via direct upload.
    
    Returns the Markdown content directly as plain text (or JSON if return_json=true).
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    
    pdf_bytes = await file.read()
    
    try:
        markdown_text = convert_pdf_bytes(pdf_bytes, file.filename)
        
        if return_json:
            return {
                "success": True,
                "filename": file.filename,
                "markdown": markdown_text
            }
        else:
            return PlainTextResponse(content=markdown_text, media_type="text/markdown")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "pdf-to-markdown"}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "PDF to Markdown API",
        "version": "1.0.0",
        "endpoints": {
            "POST /v1/chat/completions": "OpenAI-compatible chat completions (send PDF as base64)",
            "GET /v1/models": "List available models",
            "POST /convert": "Direct PDF upload and conversion",
            "GET /health": "Health check"
        },
        "usage": {
            "openai_compatible": {
                "description": "Use like OpenAI API - send PDF as base64 in messages",
                "example_request": {
                    "model": "pdf2md",
                    "messages": [
                        {"role": "user", "content": "[PDF_BASE64:<base64_data>:END_PDF]"}
                    ]
                }
            },
            "direct_upload": {
                "description": "Upload PDF file directly",
                "example": "curl -X POST http://host:9999/convert -F 'file=@doc.pdf'"
            }
        }
    }


@app.get("/llm")
async def llm_usage_guide():
    """
    使用说明端点 - 返回给 LLM 的使用指南。
    
    其他 AI 助手可以访问此端点了解如何使用本 API。
    """
    return {
        "service": "PDF to Markdown API",
        "description": "将 PDF 文档转换为 Markdown 格式的 API 服务",
        "endpoints": {
            "/v1/chat/completions": {
                "method": "POST",
                "description": "OpenAI 兼容接口 - 像调用 GPT 一样使用",
                "usage": {
                    "step1": "将 PDF 文件转换为 base64 编码",
                    "step2": "在 messages 中使用 [PDF_BASE64:<base64_data>:END_PDF] 格式",
                    "step3": "返回的 assistant message.content 即为 Markdown 内容"
                },
                "example_request": {
                    "model": "pdf2md",
                    "messages": [
                        {"role": "user", "content": "[PDF_BASE64:<你的PDF的base64编码>:END_PDF]"}
                    ]
                },
                "example_response": {
                    "choices": [
                        {"message": {"role": "assistant", "content": "<转换后的Markdown内容>"}}
                    ]
                }
            },
            "/convert": {
                "method": "POST",
                "description": "直接上传 PDF 文件转换",
                "usage": "curl -X POST http://host:9999/convert -F 'file=@document.pdf'",
                "returns": "Markdown 文本（或加 ?return_json=true 返回 JSON）"
            },
            "/v1/models": {
                "method": "GET",
                "description": "列出可用模型"
            },
            "/health": {
                "method": "GET", 
                "description": "健康检查"
            }
        },
        "integration_examples": {
            "python_openai": '''
import base64
import openai

client = openai.OpenAI(
    base_url="http://<HOST>:9999/v1",
    api_key="dummy"
)

with open("document.pdf", "rb") as f:
    pdf_b64 = base64.b64encode(f.read()).decode()

response = client.chat.completions.create(
    model="pdf2md",
    messages=[{
        "role": "user",
        "content": f"[PDF_BASE64:{pdf_b64}:END_PDF]"
    }]
)

print(response.choices[0].message.content)
''',
            "curl": '''
# 方式1: OpenAI 兼容接口
PDF_B64=$(base64 -w0 document.pdf)
curl -X POST http://localhost:9999/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model":"pdf2md","messages":[{"role":"user","content":"[PDF_BASE64:'$PDF_B64':END_PDF]"}]}'

# 方式2: 直接上传
curl -X POST http://localhost:9999/convert -F "file=@document.pdf"
'''
        },
        "tips": [
            "支持中文 PDF",
            "自动识别表格并转换为 Markdown 表格",
            "保留标题层级结构",
            "图片会标记为 ![](_page_X_Picture_Y.jpeg)"
        ]
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="PDF to Markdown API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9999, help="Port to bind to")
    args = parser.parse_args()
    
    print(f"🚀 Starting PDF to Markdown API on {args.host}:{args.port}")
    print(f"📖 OpenAI-compatible endpoint: POST http://{args.host}:{args.port}/v1/chat/completions")
    print(f"📄 Direct upload: POST http://{args.host}:{args.port}/convert")
    print(f"🤖 LLM usage guide: GET http://{args.host}:{args.port}/llm")
    uvicorn.run(app, host=args.host, port=args.port)
