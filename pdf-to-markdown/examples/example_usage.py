#!/usr/bin/env python3
"""
PDF to Markdown API 使用示例

演示如何通过各种方式调用 API
"""

import base64
import httpx
import openai
from pathlib import Path


# ============ 方式 1: OpenAI SDK（推荐）============

def convert_with_openai_sdk(pdf_path: str, api_base: str = "http://localhost:9999/v1"):
    """
    使用 OpenAI SDK 调用 API
    
    最简单的方式，完全兼容 OpenAI API
    """
    # 读取 PDF 并转为 base64
    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode()
    
    # 创建客户端
    client = openai.OpenAI(
        base_url=api_base,
        api_key="dummy"  # 任意值即可
    )
    
    # 调用 API
    response = client.chat.completions.create(
        model="pdf2md",
        messages=[{
            "role": "user",
            "content": f"[PDF_BASE64:{pdf_b64}:END_PDF]"
        }]
    )
    
    return response.choices[0].message.content


# ============ 方式 2: 直接 HTTP 请求 ============

def convert_with_http(pdf_path: str, api_base: str = "http://localhost:9999"):
    """
    使用 HTTP 直接上传 PDF
    """
    with open(pdf_path, "rb") as f:
        files = {"file": (Path(pdf_path).name, f, "application/pdf")}
        response = httpx.post(f"{api_base}/convert", files=files)
    
    return response.text


# ============ 方式 3: JSON 响应 ============

def convert_with_json_response(pdf_path: str, api_base: str = "http://localhost:9999"):
    """
    获取 JSON 格式的响应
    """
    with open(pdf_path, "rb") as f:
        files = {"file": (Path(pdf_path).name, f, "application/pdf")}
        response = httpx.post(
            f"{api_base}/convert",
            files=files,
            params={"return_json": True}
        )
    
    return response.json()


# ============ 方式 4: 批量转换 ============

def batch_convert(pdf_paths: list, api_base: str = "http://localhost:9999"):
    """
    批量转换多个 PDF
    """
    results = {}
    
    for pdf_path in pdf_paths:
        try:
            markdown = convert_with_http(pdf_path, api_base)
            results[pdf_path] = {
                "success": True,
                "markdown": markdown
            }
        except Exception as e:
            results[pdf_path] = {
                "success": False,
                "error": str(e)
            }
    
    return results


# ============ 主程序 ============

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python example_usage.py <pdf_file>")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    
    print(f"📄 Converting: {pdf_file}")
    print("=" * 50)
    
    # 使用 OpenAI SDK 方式
    print("\n🤖 Using OpenAI SDK:")
    try:
        markdown = convert_with_openai_sdk(pdf_file)
        print(f"✅ Success! Length: {len(markdown)} chars")
        print("\nFirst 500 chars:")
        print(markdown[:500])
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # 保存结果
    output_file = Path(pdf_file).stem + ".md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"\n💾 Saved to: {output_file}")
