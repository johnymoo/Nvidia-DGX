#!/home/chriswang/.openclaw/workspaces/admin/skills/pdf-to-markdown/.venv/bin/python
"""PDF to Markdown converter using marker-pdf."""

import argparse
import sys
from pathlib import Path

def convert_single(pdf_path: Path, output_path: Path | None = None, extract_images: bool = False) -> Path:
    """Convert a single PDF to Markdown."""
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
    
    converter = PdfConverter(create_model_dict())
    rendered = converter(str(pdf_path))
    text, _, images = text_from_rendered(rendered)
    
    if output_path is None:
        output_path = pdf_path.with_suffix('.md')
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding='utf-8')
    
    if extract_images and images:
        images_dir = output_path.parent / f"{output_path.stem}_images"
        images_dir.mkdir(exist_ok=True)
        for name, img in images.items():
            img_path = images_dir / name
            img.save(img_path)
        print(f"Extracted {len(images)} images to {images_dir}")
    
    print(f"Converted: {pdf_path} -> {output_path}")
    return output_path


def convert_batch(pdf_paths: list[Path], output_dir: Path, extract_images: bool = False) -> list[Path]:
    """Convert multiple PDFs."""
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
    
    output_dir.mkdir(parents=True, exist_ok=True)
    converter = PdfConverter(create_model_dict())
    results = []
    
    for pdf_path in pdf_paths:
        try:
            rendered = converter(str(pdf_path))
            text, _, images = text_from_rendered(rendered)
            
            output_path = output_dir / f"{pdf_path.stem}.md"
            output_path.write_text(text, encoding='utf-8')
            
            if extract_images and images:
                images_dir = output_dir / f"{pdf_path.stem}_images"
                images_dir.mkdir(exist_ok=True)
                for name, img in images.items():
                    img.save(images_dir / name)
            
            print(f"✓ {pdf_path.name}")
            results.append(output_path)
        except Exception as e:
            print(f"✗ {pdf_path.name}: {e}", file=sys.stderr)
    
    print(f"\nConverted {len(results)}/{len(pdf_paths)} files")
    return results


def main():
    parser = argparse.ArgumentParser(description='Convert PDF to Markdown')
    parser.add_argument('pdf', nargs='+', help='PDF file(s) to convert')
    parser.add_argument('-o', '--output', help='Output file or directory')
    parser.add_argument('--images', action='store_true', help='Extract images')
    args = parser.parse_args()
    
    pdf_paths = [Path(p) for p in args.pdf]
    
    for p in pdf_paths:
        if not p.exists():
            print(f"Error: {p} not found", file=sys.stderr)
            sys.exit(1)
    
    if len(pdf_paths) == 1:
        output = Path(args.output) if args.output else None
        convert_single(pdf_paths[0], output, args.images)
    else:
        output_dir = Path(args.output) if args.output else Path('.')
        convert_batch(pdf_paths, output_dir, args.images)


if __name__ == '__main__':
    main()
