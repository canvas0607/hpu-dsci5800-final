from __future__ import annotations

import os
import re
from typing import Any

import httpx

from app.models import FurnitureItem


DEMO_IKEA_ITEMS = [
    FurnitureItem(
        name="POANG Armchair",
        category="chair",
        price=129.0,
        url="https://www.ikea.com/us/en/search/?q=POANG%20armchair",
        reason="舒适阅读椅，线条简单，适合温和自然的角落。",
    ),
    FurnitureItem(
        name="KALLAX Shelf Unit",
        category="storage",
        price=89.99,
        url="https://www.ikea.com/us/en/search/?q=KALLAX%20shelf",
        reason="可放书、摆件和收纳篮，适合作为开放式储物。",
    ),
    FurnitureItem(
        name="LACK Coffee Table",
        category="table",
        price=39.99,
        url="https://www.ikea.com/us/en/search/?q=LACK%20coffee%20table",
        reason="价格低、体量轻，适合紧凑客厅或床边临时置物。",
    ),
    FurnitureItem(
        name="MALM Bed Frame",
        category="bed",
        price=299.0,
        url="https://www.ikea.com/us/en/search/?q=MALM%20bed%20frame",
        reason="卧室核心家具，造型干净，容易和白色、木色、织物搭配。",
    ),
    FurnitureItem(
        name="TARVA Bed Frame",
        category="bed",
        price=179.0,
        url="https://www.ikea.com/us/en/search/?q=TARVA%20bed%20frame",
        reason="松木材质比亮面白色更温暖，适合温馨卧室。",
    ),
    FurnitureItem(
        name="HEMNES Nightstand",
        category="nightstand",
        price=99.99,
        url="https://www.ikea.com/us/en/search/?q=HEMNES%20nightstand",
        reason="床头收纳实用，外形柔和，能增强卧室的温馨感。",
    ),
    FurnitureItem(
        name="RANARP Work Lamp",
        category="lamp",
        price=34.99,
        url="https://www.ikea.com/us/en/search/?q=RANARP%20lamp",
        reason="暖光床头灯，能让夜间氛围更柔和。",
    ),
    FurnitureItem(
        name="LOHALS Rug",
        category="rug",
        price=89.99,
        url="https://www.ikea.com/us/en/search/?q=LOHALS%20rug",
        reason="天然纤维质感能增加温度，也不会让 20 平卧室显得拥挤。",
    ),
    FurnitureItem(
        name="BRIMNES Wardrobe",
        category="wardrobe",
        price=249.0,
        url="https://www.ikea.com/us/en/search/?q=BRIMNES%20wardrobe",
        reason="封闭式衣物收纳，外观整洁，适合卧室保持清爽。",
    ),
    FurnitureItem(
        name="LINANAS Sofa",
        category="sofa",
        price=399.0,
        url="https://www.ikea.com/us/en/search/?q=LINANAS%20sofa",
        reason="紧凑型沙发，适合公寓和小户型客厅。",
    ),
]

QUERY_SYNONYMS = {
    "床": ["bed", "bedroom"],
    "床架": ["bed", "bedroom"],
    "卧室": ["bed", "bedroom"],
    "温馨": ["cozy", "warm", "wood", "lamp", "rug"],
    "暖": ["cozy", "warm", "wood", "lamp", "rug"],
    "20平": ["medium", "bedroom", "wardrobe"],
    "4x5": ["medium", "bedroom", "wardrobe"],
    "沙发": ["sofa", "living"],
    "客厅": ["sofa", "table", "storage", "living"],
    "椅子": ["chair", "armchair"],
    "扶手椅": ["chair", "armchair"],
    "茶几": ["coffee", "table"],
    "桌": ["table"],
    "储物": ["storage", "shelf"],
    "书架": ["storage", "shelf"],
    "收纳": ["storage", "shelf"],
}

ROOM_CATEGORY_PLAN = {
    "bedroom": ["bed", "nightstand", "lamp", "rug", "wardrobe", "storage"],
    "living": ["sofa", "table", "storage", "chair", "lamp", "rug"],
}


async def search_ikea_furniture(
    query: str, budget: float | None, preferences: dict[str, Any]
) -> list[FurnitureItem]:
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        items = await _search_with_tavily(tavily_key, query)
        if items:
            return _fit_budget(items, budget)

    query_text = f"{query} {preferences}".lower()
    scored = sorted(
        DEMO_IKEA_ITEMS,
        key=lambda item: _score_item(item, query_text),
        reverse=True,
    )
    room = _infer_room(query_text)
    if room:
        planned = _select_for_room(scored, ROOM_CATEGORY_PLAN[room], budget)
        if planned:
            return planned
    return _fit_budget(scored, budget)


async def _search_with_tavily(api_key: str, query: str) -> list[FurnitureItem]:
    payload = {
        "api_key": api_key,
        "query": f"site:ikea.com/us/en {query} furniture price image",
        "search_depth": "advanced",
        "include_images": True,
        "max_results": 8,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post("https://api.tavily.com/search", json=payload)
        response.raise_for_status()
        data = response.json()

    items: list[FurnitureItem] = []
    for result in data.get("results", []):
        title = result.get("title") or "IKEA furniture"
        content = result.get("content") or ""
        price = _extract_price(title + " " + content)
        items.append(
            FurnitureItem(
                name=title[:120],
                category="furniture",
                price=price,
                url=result.get("url") or "https://www.ikea.com/us/en/",
                reason=content[:220],
            )
        )
    return items


def _extract_price(text: str) -> float:
    match = re.search(r"\$?\s*(\d+(?:\.\d{1,2})?)", text)
    return float(match.group(1)) if match else 0.0


def _score_item(item: FurnitureItem, query_text: str) -> int:
    haystack = f"{item.name} {item.category} {item.reason}".lower()
    expanded_terms = query_text.split()
    for key, terms in QUERY_SYNONYMS.items():
        if key in query_text:
            expanded_terms.extend(terms)
    score = sum(1 for word in expanded_terms if word in haystack)
    room = _infer_room(query_text)
    if room and item.category in ROOM_CATEGORY_PLAN[room]:
        score += 5
    if ("温馨" in query_text or "warm" in query_text or "cozy" in query_text) and item.category in {
        "lamp",
        "rug",
        "nightstand",
        "bed",
    }:
        score += 3
    return score


def _infer_room(query_text: str) -> str:
    if any(token in query_text for token in ["卧室", "bedroom", "床", "bed"]):
        return "bedroom"
    if any(token in query_text for token in ["客厅", "living", "sofa", "沙发"]):
        return "living"
    return ""


def _select_for_room(
    items: list[FurnitureItem], categories: list[str], budget: float | None
) -> list[FurnitureItem]:
    selected: list[FurnitureItem] = []
    total = 0.0
    for category in categories:
        candidates = [item for item in items if item.category == category and item not in selected]
        if not candidates:
            continue
        candidate = candidates[0]
        if budget and candidate.price > 0 and total + candidate.price > budget:
            continue
        selected.append(candidate)
        total += candidate.price
        if len(selected) >= 5:
            break
    return selected


def _fit_budget(items: list[FurnitureItem], budget: float | None) -> list[FurnitureItem]:
    if not budget:
        return items[:5]
    selected: list[FurnitureItem] = []
    total = 0.0
    for item in items:
        if item.price <= 0 or total + item.price <= budget:
            selected.append(item)
            total += item.price
        if len(selected) >= 5:
            break
    return selected or items[:3]
