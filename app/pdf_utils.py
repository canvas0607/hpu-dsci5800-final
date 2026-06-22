from __future__ import annotations

import base64
from dataclasses import dataclass, field


@dataclass
class PdfContext:
    page_count: int = 0
    text: str = ""
    page_images: list[str] = field(default_factory=list)
    notes: str = ""


def analyze_pdf_bytes(pdf_bytes: bytes, max_pages: int = 3) -> PdfContext:
    context = PdfContext()
    context.text = _extract_pdf_text(pdf_bytes)
    context.page_images = _render_pdf_pages(pdf_bytes, max_pages=max_pages)
    context.page_count = max(len(context.page_images), _count_pages(pdf_bytes))
    text_note = context.text[:1200] if context.text else "未提取到可读文本，可能是扫描版或纯图纸 PDF。"
    image_note = f"已渲染前 {len(context.page_images)} 页供视觉模型分析。" if context.page_images else "未能渲染 PDF 页面图片。"
    context.notes = f"PDF 页数：{context.page_count}。文本线索：{text_note} {image_note}"
    return context


def _count_pages(pdf_bytes: bytes) -> int:
    try:
        from pypdf import PdfReader
        import io

        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        return 0


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        import io

        reader = PdfReader(io.BytesIO(pdf_bytes))
        chunks = []
        for page in reader.pages[:8]:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks).strip()
    except Exception:
        return ""


def _render_pdf_pages(pdf_bytes: bytes, max_pages: int) -> list[str]:
    try:
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images: list[str] = []
        for index in range(min(max_pages, doc.page_count)):
            page = doc.load_page(index)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            images.append(base64.b64encode(pix.tobytes("png")).decode("utf-8"))
        doc.close()
        return images
    except Exception:
        return []
