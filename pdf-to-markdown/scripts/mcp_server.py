#!/home/chriswang/.openclaw/workspaces/admin/skills/pdf-to-markdown/.venv/bin/python
"""MCP server for PDF to Markdown conversion."""

import json
import sys
from pathlib import Path

# MCP protocol implementation
class MCPServer:
    def __init__(self):
        self.tools = {
            "pdf_to_markdown": {
                "name": "pdf_to_markdown",
                "description": "Convert a PDF file to Markdown using AI-powered layout detection",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pdf_path": {
                            "type": "string",
                            "description": "Path to the PDF file"
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Output path for the Markdown file (optional)"
                        },
                        "extract_images": {
                            "type": "boolean",
                            "description": "Whether to extract images (default: false)",
                            "default": False
                        }
                    },
                    "required": ["pdf_path"]
                }
            },
            "pdf_batch_convert": {
                "name": "pdf_batch_convert",
                "description": "Convert multiple PDF files to Markdown",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pdf_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of PDF file paths"
                        },
                        "output_dir": {
                            "type": "string",
                            "description": "Output directory for converted files"
                        },
                        "extract_images": {
                            "type": "boolean",
                            "description": "Whether to extract images (default: false)",
                            "default": False
                        }
                    },
                    "required": ["pdf_paths", "output_dir"]
                }
            }
        }
    
    def send_response(self, response):
        json_str = json.dumps(response)
        sys.stdout.write(f"Content-Length: {len(json_str)}\r\n\r\n{json_str}")
        sys.stdout.flush()
    
    def handle_initialize(self, params):
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "pdf-to-markdown",
                "version": "1.0.0"
            }
        }
    
    def handle_list_tools(self, params):
        return {"tools": list(self.tools.values())}
    
    def handle_call_tool(self, params):
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        if tool_name == "pdf_to_markdown":
            return self.convert_single(
                arguments["pdf_path"],
                arguments.get("output_path"),
                arguments.get("extract_images", False)
            )
        elif tool_name == "pdf_batch_convert":
            return self.convert_batch(
                arguments["pdf_paths"],
                arguments["output_dir"],
                arguments.get("extract_images", False)
            )
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
    
    def convert_single(self, pdf_path: str, output_path: str | None = None, extract_images: bool = False):
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered
        
        pdf = Path(pdf_path)
        if not pdf.exists():
            return {
                "content": [{"type": "text", "text": f"Error: File not found: {pdf_path}"}],
                "isError": True
            }
        
        try:
            converter = PdfConverter(create_model_dict())
            rendered = converter(str(pdf))
            text, _, images = text_from_rendered(rendered)
            
            out = Path(output_path) if output_path else pdf.with_suffix('.md')
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding='utf-8')
            
            result_text = f"Converted {pdf_path} to {out}"
            
            if extract_images and images:
                images_dir = out.parent / f"{out.stem}_images"
                images_dir.mkdir(exist_ok=True)
                for name, img in images.items():
                    img.save(images_dir / name)
                result_text += f"\nExtracted {len(images)} images to {images_dir}"
            
            return {
                "content": [{"type": "text", "text": result_text}]
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True
            }
    
    def convert_batch(self, pdf_paths: list[str], output_dir: str, extract_images: bool = False):
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered
        
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        
        converter = PdfConverter(create_model_dict())
        results = []
        
        for pdf_path in pdf_paths:
            pdf = Path(pdf_path)
            if not pdf.exists():
                results.append(f"✗ {pdf.name}: File not found")
                continue
            
            try:
                rendered = converter(str(pdf))
                text, _, images = text_from_rendered(rendered)
                
                out_path = out_dir / f"{pdf.stem}.md"
                out_path.write_text(text, encoding='utf-8')
                
                if extract_images and images:
                    images_dir = out_dir / f"{pdf.stem}_images"
                    images_dir.mkdir(exist_ok=True)
                    for name, img in images.items():
                        img.save(images_dir / name)
                
                results.append(f"✓ {pdf.name}")
            except Exception as e:
                results.append(f"✗ {pdf.name}: {str(e)}")
        
        return {
            "content": [{"type": "text", "text": "\n".join(results)}]
        }
    
    def run(self):
        buffer = ""
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            
            if line.startswith("Content-Length:"):
                length = int(line.split(":")[1].strip())
                sys.stdin.readline()  # empty line
                body = sys.stdin.read(length)
                
                try:
                    request = json.loads(body)
                    method = request.get("method", "")
                    params = request.get("params", {})
                    request_id = request.get("id")
                    
                    if method == "initialize":
                        result = self.handle_initialize(params)
                    elif method == "tools/list":
                        result = self.handle_list_tools(params)
                    elif method == "tools/call":
                        result = self.handle_call_tool(params)
                    else:
                        result = {}
                    
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result
                    }
                    self.send_response(response)
                except Exception as e:
                    self.send_response({
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {"code": -32603, "message": str(e)}
                    })


if __name__ == '__main__':
    MCPServer().run()
