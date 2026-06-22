from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Iterable

import fitz

from app.models import FurnitureItem, RecommendationResponse


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 48
FONT = "china-ss"
TEXT_COLOR = (0.10, 0.13, 0.18)
MUTED_COLOR = (0.38, 0.45, 0.55)
ACCENT_COLOR = (0.06, 0.46, 0.43)


def build_plan_pdf(plan: RecommendationResponse) -> bytes:
    writer = _PdfWriter()
    writer.heading("家具搭配方案", size=22)
    writer.paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", color=MUTED_COLOR)
    writer.paragraph(f"预计总金额：{_money(plan.total, plan.currency)}", size=13, color=ACCENT_COLOR)
    if plan.budget is not None:
        writer.paragraph(f"用户预算：{_money(plan.budget, plan.currency)}", color=MUTED_COLOR)

    writer.divider()
    writer.heading("方案说明", size=16)
    writer.markdown_text(plan.text)

    if plan.room_image_url:
        writer.heading("整体效果图", size=16)
        writer.image(plan.room_image_url)

    if plan.room_plans:
        writer.heading("分房间方案", size=16)
        for room in plan.room_plans:
            writer.heading(room.room_name, size=14)
            if room.room_image_url:
                writer.image(room.room_image_url)
            writer.markdown_text(room.text)
            writer.items_table(room.items)
    elif plan.items:
        writer.heading("商品清单", size=16)
        writer.items_table(plan.items)

    writer.divider()
    writer.paragraph(
        "提示：价格、库存、配送和安装条件请以官网信息为准。",
        color=MUTED_COLOR,
    )
    return writer.bytes()


class _PdfWriter:
    def __init__(self) -> None:
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.y = MARGIN

    def bytes(self) -> bytes:
        return self.doc.tobytes(garbage=4, deflate=True)

    def heading(self, text: str, size: int = 16) -> None:
        self._ensure(size + 16)
        self.page.insert_text(
            (MARGIN, self.y),
            _clean_inline(text),
            fontsize=size,
            fontname=FONT,
            color=ACCENT_COLOR if size >= 16 else TEXT_COLOR,
        )
        self.y += size + 12

    def paragraph(
        self,
        text: str,
        size: int = 11,
        color: tuple[float, float, float] = TEXT_COLOR,
    ) -> None:
        for raw in str(text or "").splitlines():
            line = _clean_inline(raw).strip()
            if not line:
                self.y += 6
                continue
            for wrapped in _wrap(line, max_units=72):
                self._ensure(size + 8)
                self.page.insert_text((MARGIN, self.y), wrapped, fontsize=size, fontname=FONT, color=color)
                self.y += size + 6
        self.y += 4

    def markdown_text(self, text: str) -> None:
        for block in _markdown_blocks(text):
            self.paragraph(block)

    def items_table(self, items: Iterable[FurnitureItem]) -> None:
        rows = list(items)
        if not rows:
            return
        self._table_header()
        for item in rows:
            self._ensure(38)
            y0 = self.y
            self.page.draw_rect(
                fitz.Rect(MARGIN, y0 - 12, PAGE_WIDTH - MARGIN, y0 + 24),
                color=(0.86, 0.89, 0.93),
                width=0.5,
            )
            self._cell(item.name, MARGIN + 8, y0, 27)
            self._cell(item.category, MARGIN + 218, y0, 12)
            self._cell(_money(item.price, item.currency), MARGIN + 312, y0, 12)
            self._cell(_short_url(item.url), MARGIN + 392, y0, 23, color=MUTED_COLOR)
            self.y += 36
        self.y += 8

    def image(self, data_url: str) -> None:
        image_bytes = _decode_data_url(data_url)
        if not image_bytes:
            return
        rect_width = PAGE_WIDTH - MARGIN * 2
        rect_height = min(230, rect_width * 2 / 3)
        self._ensure(rect_height + 18)
        rect = fitz.Rect(MARGIN, self.y, PAGE_WIDTH - MARGIN, self.y + rect_height)
        try:
            self.page.insert_image(rect, stream=image_bytes, keep_proportion=True)
            self.y += rect_height + 14
        except Exception:
            return

    def divider(self) -> None:
        self._ensure(18)
        self.page.draw_line(
            (MARGIN, self.y),
            (PAGE_WIDTH - MARGIN, self.y),
            color=(0.82, 0.86, 0.90),
            width=0.8,
        )
        self.y += 16

    def _table_header(self) -> None:
        self._ensure(32)
        self.page.draw_rect(
            fitz.Rect(MARGIN, self.y - 14, PAGE_WIDTH - MARGIN, self.y + 16),
            color=(0.06, 0.46, 0.43),
            fill=(0.06, 0.46, 0.43),
        )
        for text, x in [
            ("商品", MARGIN + 8),
            ("品类", MARGIN + 218),
            ("价格", MARGIN + 312),
            ("链接", MARGIN + 392),
        ]:
            self.page.insert_text((x, self.y + 4), text, fontsize=10, fontname=FONT, color=(1, 1, 1))
        self.y += 28

    def _cell(
        self,
        text: str,
        x: float,
        y: float,
        max_units: int,
        color: tuple[float, float, float] = TEXT_COLOR,
    ) -> None:
        lines = _wrap(_clean_inline(text), max_units=max_units)[:2]
        for index, line in enumerate(lines):
            self.page.insert_text((x, y + index * 12), line, fontsize=8.5, fontname=FONT, color=color)

    def _ensure(self, height: float) -> None:
        if self.y + height <= PAGE_HEIGHT - MARGIN:
            return
        self.page = self.doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.y = MARGIN


def _markdown_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            blocks.append("")
            continue
        if re.match(r"^\|[-:|\s]+\|?$", line):
            continue
        if line.startswith("|"):
            blocks.append(" / ".join(part.strip() for part in line.strip("|").split("|")))
            continue
        blocks.append(line)
    return blocks


def _clean_inline(text: str) -> str:
    cleaned = re.sub(r"^#{1,6}\s*", "", str(text or ""))
    cleaned = re.sub(r"^\s*[-*]\s+", "• ", cleaned)
    cleaned = cleaned.replace("**", "")
    cleaned = cleaned.replace("`", "")
    return cleaned.strip()


def _wrap(text: str, max_units: int) -> list[str]:
    lines: list[str] = []
    current = ""
    units = 0
    for char in str(text or ""):
        char_units = 2 if ord(char) > 127 else 1
        if units + char_units > max_units and current:
            lines.append(current)
            current = char
            units = char_units
        else:
            current += char
            units += char_units
    if current:
        lines.append(current)
    return lines or [""]


def _decode_data_url(value: str) -> bytes | None:
    if not value.startswith("data:image/"):
        return None
    try:
        _, b64 = value.split(",", 1)
        return base64.b64decode(b64)
    except Exception:
        return None


def _money(value: float, currency: str | None = "CNY") -> str:
    if currency == "USD":
        return f"${float(value):.2f}"
    if currency == "CNY" or not currency:
        return f"¥{float(value):.2f}"
    return f"{float(value):.2f} {currency}"


def _short_url(url: str) -> str:
    if not url:
        return ""
    return url.replace("https://www.", "").replace("https://", "")[:48]
