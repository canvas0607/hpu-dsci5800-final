from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.models import FurnitureItem


def calculate_cart_total(items: list[FurnitureItem]) -> dict[str, Any]:
    """Deterministically calculate cart totals from selected furniture items."""
    currency = _resolve_currency(items)
    lines = []
    subtotal = Decimal("0.00")
    unknown_price_items: list[str] = []

    for item in items:
        price = _money(item.price)
        if price <= Decimal("0.00"):
            unknown_price_items.append(item.name)
        subtotal += price
        lines.append(
            {
                "name": item.name,
                "category": item.category,
                "price": float(price),
                "currency": item.currency or currency,
            }
        )

    total = _money(subtotal)
    return {
        "currency": currency,
        "subtotal": float(total),
        "total": float(total),
        "line_items": lines,
        "unknown_price_items": unknown_price_items,
        "calculation_note": (
            "总金额由后端 pricing tool 使用候选商品价格逐项相加；不含税费、配送、安装和实时折扣。"
        ),
    }


def _money(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _resolve_currency(items: list[FurnitureItem]) -> str:
    currencies = [item.currency for item in items if item.currency]
    return currencies[0] if currencies else "USD"
